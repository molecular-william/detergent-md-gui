"""Detergent placement: the builder's geometry, with the gates that decide whether a run may proceed.

`micelle.packing` owns the arrangement and `micelle.validation` owns the overlap and count gates; this module owns
the protein-relative shape, the clearance gate and the decision to stop. That split is deliberate: the builder's
design says an impossible packing writes diagnostics and produces no run, and a placement is exactly where that has
to be decided.

Two modes, and a build states which one it used:

* `lattice` (the default, and the behaviour every existing run had) places the detergents on the micelle builder's
  deterministic arrangement -- the seed choosing its phase. Its *shape* is the membrane's when the protein states
  one: a build handed a `micelle.frame.MembraneFrame` places the belt as a **torus** about that frame's own
  cylinder (the user's correction, 2026-10-14). The protein's hydrophobic cylinder -- the circle of the measured
  slab radius lying in the membrane plane at the frame's centre -- is the tube's **centre-line**; the tube's radius
  is the **detergent's own length**, measured from the molecule the placement is handed rather than assumed; and
  every detergent's **head end sits on the tube's outer surface** with its body pointing back at the centre-line.
  The head-to-tail axis is therefore the tube's own radial direction, which turns with where around the half-circle
  a detergent sits -- a direction the cylinder wall this replaces had no way to express. A build with no stated
  membrane -- every packaged protein, every import that states nothing, and the empty micelle -- keeps the
  fixed-radius sphere about the protein's centroid, where `radius_nm` *is* the radius. The mode is still `lattice`
  either way: the tube is the lattice's own arrangement of a shape the frame decided, not a third generator.
* `self-assembly` places them **at random** inside the box the protein is inserted into, off the protein and off each
  other, so CG MD can let the belt find its own arrangement -- MemProtMD's Self Assembly route. The seed is the whole
  of the randomness, so the same seed rebuilds the same system and a different seed rebuilds a different one.
"""
import numpy as np

from micelle.frame import belt_points, unit_axis
from micelle.packing import golden_angle_directions, pack_micelle
from micelle.validation import validate_positions

MIN_CLEARANCE_NM = 0.5
# The placement radius: the sphere's own radius for a build with no membrane, and a *floor* on a protein build's
# belt. A belt's centre-line is measured from the protein (its slab radius), and this setting can only push that
# line further out -- never pull it inside the cylinder the protein was measured to occupy. See `place_detergents`.
DEFAULT_RADIUS_NM = 3.0
# The two shapes a lattice build can have. A build records which it used, because the coordinates alone cannot say
# whether a shell of sites about the centroid was a decision or the absence of a membrane to place them in.
SHAPE_TORUS = 'belt-torus'
SHAPE_SPHERE = 'sphere'
# The box the protein is inserted into, when the caller does not state the run's own numbers: the adapter's defaults.
DEFAULT_MARGIN_NM = 2.0
DEFAULT_INITIAL_Z_NM = 6.0
# The builder's overlap gate (`micelle.validation.validate_positions`'s default). The self-assembly sampler has to
# respect the same number, or it hands back a placement the builder's own gate then refuses; the tube's own draw
# respects it as it draws, for the same reason.
MIN_DISTANCE_NM = 0.25
# How many entries of the ladder a tube's draw may consume per requested detergent. The bound is what turns "this
# shape cannot hold that many" into the count gate's own sentence instead of an endless loop -- the same reason
# `_self_assemble` draws a bounded number of times.
DRAWS_PER_DETERGENT = 200

PLACEMENT_MODES = ('lattice', 'self-assembly')
DEFAULT_PLACEMENT_MODE = 'lattice'


def canonical_mode(mode) -> str:
    """The mode's own spelling: the two a build offers, and nothing else.

    A mode is a choice, so an unrecognised one is refused here rather than silently falling back to the lattice --
    a build that quietly placed the belt the caller did not ask for is worse than one that stops.
    """
    name = str(mode).strip().lower().replace('_', '-')
    if name not in PLACEMENT_MODES:
        raise ValueError(f'unknown placement mode {mode!r}: expected one of {", ".join(PLACEMENT_MODES)}')
    return name


def detergent_length_nm(template) -> float | None:
    """The detergent's own length, measured from the molecule the template names, or `None` when it has none.

    The tube's radius is this number and nothing else -- not a setting and not a constant -- so it is *measured*
    from the molecule the build actually places: the template's own coordinate file, whose greatest atom-to-atom
    distance is the molecule's own head-to-tail reach. Measured that way, the packaged DDM states 2.1431 nm (its
    81-atom structure, hydrogens included), and a molecule whose file holds no coordinate records states nothing --
    `None`, which is the answer that keeps the sphere rather than inventing a radius.

    The template is the one input every caller of `place_detergents` has (`pdc_build` and `pdc_preview` both hand
    over the loaded record), so a length measured here is the same number in a preview and in the run it previews.
    """
    if template is None:
        return None
    from .pdc_import import structure_atoms

    try:
        atoms = structure_atoms(template.coordinates)
    except (OSError, ValueError):
        return None
    if len(atoms) < 2:
        return None
    points = np.asarray([[float(value) for value in atom['position']] for atom in atoms])
    # sqrt of the squared-difference sum is memory-hungry for a large molecule, so the pairwise distances are taken
    # in chunks: a molecule of a few hundred atoms costs nothing either way, and one of a few thousand should not
    # decide whether a preview answers.
    span = 0.0
    for start in range(0, len(points), 1024):
        block = points[start:start + 1024]
        offsets = block[:, None, :] - points[None, :, :]
        span = max(span, float(np.sqrt((offsets * offsets).sum(axis=2)).max()))
    return round(span, 6) if span > 0 else None


def place_detergents(protein_points, template, aggregation_number, seed, *, radius_nm=DEFAULT_RADIUS_NM,
                     min_clearance_nm=MIN_CLEARANCE_NM, mode=DEFAULT_PLACEMENT_MODE, margin_nm=DEFAULT_MARGIN_NM,
                     initial_z_nm=DEFAULT_INITIAL_Z_NM, frame=None):
    """Place `aggregation_number` detergents around the protein (or around nothing, for an empty micelle).

    Deterministic in the seed through whichever generator the mode names, and gated before anything runs: the
    returned mapping carries the positions, the mode, *and* the issues, so a caller cannot proceed past a failed gate
    without acknowledging it. What this cannot yet check is the detergent's own bead shape -- the clearance uses the
    placed centres against the protein coordinates, and a template whose headgroup reaches further than that needs the
    bead geometry to say so.

    `frame` is the membrane the protein stated for itself (`micelle.frame`), or `None`. It is the *only* thing that
    decides the lattice's shape: with one, the belt is a **torus** about the protein's own cylinder -- its branch of
    the geometry is `_belt_torus`, and the sites it returns are the detergents' head ends; without one -- or when
    the frame's slab holds no atom of the protein, or the detergent's own length cannot be measured -- the placement
    is the sphere it has always been, and `belt_reason` says which of those it was.

    `radius_nm` is the sphere's own radius for a build with no membrane, and for a protein build it is a **floor** on
    the belt's *centre-line*: that line's radius is `max(measured slab radius, radius_nm)`, so the setting can push
    a belt out but can never pull it inside the cylinder the protein was measured to occupy. The tube's own radius
    is not a setting at all -- it is the detergent's length (`detergent_length_nm`). The returned `band` record
    carries every one of those numbers. An empty micelle has no protein to measure and no frame to read, so it keeps
    using `radius_nm` as the sphere's radius exactly as it always did.
    """
    if aggregation_number < 1:
        raise ValueError('a placement needs at least one detergent')
    if radius_nm <= 0 or min_clearance_nm < 0:
        raise ValueError('the placement radius must be positive and the clearance cannot be negative')
    mode = canonical_mode(mode)
    points = None
    unplaced = 0
    if protein_points is not None and len(protein_points):
        points = np.asarray([[float(value) for value in point] for point in protein_points])
        if points.ndim != 2:
            raise ValueError('protein coordinates must be a list of points')
        # A bead with no position is not a bead any distance can be measured to. It is counted here and gates the
        # whole placement below: `nan < gate` is False, so a clearance check over `nan` passes every site without
        # measuring one, and the clearance reported would be a `nan` -- which stops being JSON the moment a browser
        # reads it. Measured on 4iar (2026-10-14): 20 of its 928 CG beads are `nan`, and the panel lost the build's
        # own sentence because of it.
        unplaced = int(len(points) - int(np.isfinite(points).all(axis=1).sum()))

    band, belt_reason = None, None
    if unplaced:
        # Nothing is drawn against a protein whose beads have no position: the sampler's own box is centred on the
        # beads' mean -- a `nan` -- and `numpy` refuses to draw from it (`OverflowError`), and the tube's ladder
        # would keep every site because no rejection could be measured.
        centers, directions = np.empty((0, 3)), np.empty((0, 3))
    elif mode == 'lattice':
        if points is not None and frame is not None:
            band, belt_reason = _belt_torus(points, aggregation_number, seed, frame, min_clearance_nm, radius_nm,
                                            template)
        if band is None:
            centers, directions = pack_micelle(points, template, aggregation_number, seed, radius=radius_nm)
        else:
            centers, directions = band['centers'], band['directions']
    else:
        centers, directions = _self_assemble(points, aggregation_number, seed, radius_nm=radius_nm,
                                             min_clearance_nm=min_clearance_nm, margin_nm=margin_nm,
                                             initial_z_nm=initial_z_nm)

    issues = [] if unplaced else list(validate_positions(centers, aggregation_number)['issues'])
    if unplaced:
        total = 0 if points is None else len(points)
        issues.append(f'the protein has {unplaced} coarse-grained bead(s) without a position, of {total}, so '
                      f'no detergent can be placed clear of it')
    clearance = None
    if not unplaced and points is not None and len(points) and len(centers):
        clearance = min(float(np.linalg.norm(center - points, axis=1).min()) for center in centers)
        if clearance < min_clearance_nm:
            issues.append(f'detergent too close to the protein: {clearance:.3f} nm < {min_clearance_nm} nm')
    return {'centers': centers.tolist(), 'directions': directions.tolist(), 'mode': mode,
            # Nothing was drawn against a protein no measurement could be made of, so there is no shape to name.
            'placement_shape': None if unplaced else (SHAPE_TORUS if band is not None else SHAPE_SPHERE),
            'band': band['record'] if band is not None else None,
            'belt_reason': belt_reason,
            'frame': frame.as_record() if frame is not None else None,
            'aggregation_number': aggregation_number, 'radius_nm': radius_nm, 'seed': seed,
            'protein_free': points is None or not len(points), 'protein_clearance_nm': clearance,
            'issues': issues, 'valid': not issues}


def _belt_torus(points, count, seed, frame, min_clearance_nm, radius_nm, template):
    """The belt as a torus about the protein's hydrophobic cylinder, and why it is the sphere instead, or `None`.

    The tube's **centre-line** is the circle of the measured slab radius lying in the membrane plane at the frame's
    centre: the furthest *in-slab* atom's distance from the frame's own axis, which is the one measurement the
    protein makes about itself. The tube's **radius** is the detergent's own length, measured from the molecule
    (`detergent_length_nm`) -- so a bigger detergent makes a bigger tube and a molecule nobody measured makes none.

    Every site it returns is a detergent's **head end**, standing on the tube's outer surface at the detergent's
    length from the centre-line, and every direction is that site's own meridian: `cos(phi)` outward in the plane
    and `sin(phi)` along the axis, which is the tube's radial direction at that point and not the cylinder's single
    heading. `pdc_build.stamp` puts the molecule's head end at the site and its body back along that direction, so
    the tails end up facing the centre-line -- the shape the correction asks for, measured rather than asserted.

    `None` is the answer when the slab holds no atom -- a stated membrane the protein is not in, or a structure whose
    atoms all sit in its soluble domains -- and when the detergent's own length cannot be measured, whether because
    no molecule was handed over or because its own structure states no coordinates. There is no measured radius to
    build a tube from then, and a guessed one is indistinguishable from a measured one once it is in a run, so the
    caller keeps the sphere it had and `belt_reason` names the measurement that was missing.

    The centre-line's radius is *measured* (the slab radius) and `radius_nm` is a **floor** under it: the greater of
    the two is used, so the setting can push a belt out but can never pull it inside the protein's own cylinder. The
    record carries every number, so a reader can tell a measured belt from one the setting enlarged and can re-add
    the floor.

    The gate is applied *while the sites are drawn*: an entry of the ladder whose site lands within the clearance of
    the protein -- or within the overlap gate of an earlier site -- is refused and the ladder carries on to its next
    entry. That is what "honour the requested count, the pairwise overlap gate and the 0.5 nm clearance gate" means
    for a shape that overlaps the protein: the sites the protein leaves no room for are dropped, not nudged, and the
    count is the number the draw actually kept. A draw that cannot reach the count places what it did and the count
    gate refuses it with the sentence it has always used.
    """
    axis = np.asarray(unit_axis(frame.axis), dtype=float)
    inside = np.asarray(belt_points(points, frame), dtype=float)
    if not len(inside):
        return None, 'the membrane frame\'s slab holds no atom of the protein, so no cylinder can be measured'
    axial = inside @ axis
    slab_radius = float(np.linalg.norm(inside - np.outer(axial, axis), axis=1).max())
    centre_radius = max(slab_radius, float(radius_nm))
    length = detergent_length_nm(template)
    if length is None:
        return None, ('the detergent\'s own length cannot be measured from the molecule the build carries, so the '
                      'tube has no radius and the placement keeps the sphere')
    centers, directions, drawn, rejected, passes = _tube_sites(count, seed, frame, centre_radius, length, points,
                                                             min_clearance_nm)
    return {'centers': centers, 'directions': directions,
            'record': {'shape': SHAPE_TORUS, 'tube_radius_nm': round(length, 6),
                       'centre_line_radius_nm': round(centre_radius, 6),
                       'slab_radius_nm': round(slab_radius, 6), 'radius_floor_nm': round(float(radius_nm), 6),
                       'radius_nm': round(length, 6), 'belt_reach_nm': round(length, 6),
                       'detergents_drawn': drawn, 'rejected': rejected, 'passes': passes, 'axis': list(axis),
                       'plane_low_nm': frame.plane_low_nm, 'plane_high_nm': frame.plane_high_nm,
                       'source': frame.source}}, None


def _tube_sites(count, seed, frame, centre_radius, length, protein_points, min_clearance_nm):
    """`count` sites on the tube's own outer surface, drawn from the lattice's golden-angle ladder.

    The ladder is `pack_micelle`'s (`golden_angle_directions`), so both shapes are one arrangement of two surfaces:
    its azimuths become the belt's headings around the protein and its second coordinate the meridian angle around
    the half-circle -- the angle from the membrane plane to the membrane normal. A site is the centre-line point at
    that azimuth plus `length` along its own meridian, which puts every head end on the tube's outer surface.

    The ladder is drawn for the requested count, which is what spreads its meridian angle over the whole half-circle
    and its headings over the whole circumference. An entry the protein leaves no room for is refused -- the site it
    names is where the protein is -- and its replacement comes from the *next pass*: the same ladder with its phase
    advanced (`golden_angle_directions(count, seed + pass)`), which is the same arrangement turned about the axis and
    therefore still the seed's own golden angles, still spread over the shape. So the sites are the ladder's own
    sites wherever the protein allows them, plus the first pass on which each refused one found room elsewhere.

    The draw is bounded (`DRAWS_PER_DETERGENT` passes), so a shape that cannot hold the count returns what it could
    place and the count gate says so -- rather than the generator looping forever on a request with no answer.
    """
    axis = np.asarray(unit_axis(frame.axis), dtype=float)
    across, up = _plane_basis(axis)
    kept: list[np.ndarray] = []
    kept_directions: list[np.ndarray] = []
    drawn = rejected = passes = 0
    while len(kept) < count and passes < DRAWS_PER_DETERGENT:
        ladder = golden_angle_directions(count, seed + passes)
        headings = np.arctan2(ladder[:, 1], ladder[:, 0])
        meridians = 0.5 * np.pi * ladder[:, 2]
        outward = np.cos(headings)[:, None] * across + np.sin(headings)[:, None] * up
        directions = np.cos(meridians)[:, None] * outward + np.sin(meridians)[:, None] * axis
        centre_line = centre_radius * outward + frame.centre_nm * axis
        candidates = centre_line + length * directions
        for candidate, direction in zip(candidates, directions):
            if len(kept) >= count:
                break
            drawn += 1
            if float(np.linalg.norm(candidate - protein_points, axis=1).min()) < min_clearance_nm:
                rejected += 1
                continue
            if kept and float(np.linalg.norm(candidate - np.asarray(kept), axis=1).min()) < MIN_DISTANCE_NM:
                rejected += 1
                continue
            kept.append(candidate)
            kept_directions.append(direction)
        passes += 1
    if not kept:
        return np.empty((0, 3)), np.empty((0, 3)), drawn, rejected, passes
    return np.asarray(kept), np.asarray(kept_directions), drawn, rejected, passes


def _plane_basis(axis):
    """Two unit vectors spanning the membrane plane, chosen from the axis, so the belt faces whichever way it does."""
    reference = np.array([1.0, 0.0, 0.0]) if abs(axis[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    across = reference - axis * float(np.dot(reference, axis))
    across = across / np.linalg.norm(across)
    return across, np.cross(axis, across)


def _self_assemble(points, count, seed, *, radius_nm, min_clearance_nm, margin_nm, initial_z_nm):
    """A random cloud of `count` detergents inside the box the protein is inserted into, off the protein.

    The region is the box `pdc_box.initial_box` states for the protein -- the protein's own extent plus the margin in
    x and y, and the stated initial z -- centred on the protein, so every detergent is inside the box the run's own
    report records. An empty micelle has no extent to measure, so its region is a cube that follows the requested
    radius, which is the scale the lattice would have used. One `numpy` generator seeded by the build's seed is the
    entire source of randomness; a draw that lands on the protein or on an earlier detergent is discarded, not nudged.
    """
    rng = np.random.default_rng(seed)
    if points is not None and len(points):
        middle = points.mean(axis=0)
        extents = np.asarray(_initial_box(points, margin_nm, initial_z_nm), dtype=float)
    else:
        middle = np.zeros(3, dtype=float)
        extents = np.full(3, 2.0 * radius_nm, dtype=float)
    low, high = middle - extents / 2.0, middle + extents / 2.0

    accepted: list[np.ndarray] = []
    # A bounded number of draws. A region that cannot hold the count returns what it could place, and the count gate
    # then reports it as an impossible packing, rather than the sampler looping forever on a request with no answer.
    for _ in range(max(1000, 200 * count)):
        if len(accepted) >= count:
            break
        candidate = rng.uniform(low, high)
        if points is not None and len(points) \
                and float(np.linalg.norm(candidate - points, axis=1).min()) < min_clearance_nm:
            continue
        if accepted and float(np.linalg.norm(candidate - np.asarray(accepted), axis=1).min()) < MIN_DISTANCE_NM:
            continue
        accepted.append(candidate)

    centers = np.asarray(accepted, dtype=float) if accepted else np.empty((0, 3))
    return centers, _outward(middle, centers)


def _initial_box(points, margin_nm, initial_z_nm):
    """The box rule, imported where it is used: `pdc_box` is otherwise only reached through the build entry point."""
    from .pdc_box import initial_box

    return initial_box([list(point) for point in points], margin_nm=margin_nm, initial_z_nm=initial_z_nm)


def _outward(middle, centers):
    """Each detergent's outward direction: the way out of the cloud, which is the way its head faces.

    The lattice's directions are its shell's own radial vectors (`pack_micelle` builds the centres as the middle
    plus `radius * direction`), and this is the same convention: for a self-assembled cloud the direction is the way
    out of it, and for a tube it is the site's own meridian direction (`_tube_sites`), which is the way out of the
    belt. `pdc_build.stamp` aims the detergent's head end along whichever direction it is handed, so a direction
    pointing inward would face the head at the micelle.
    """
    if not len(centers):
        return np.empty((0, 3))
    offsets = np.asarray(centers, dtype=float) - np.asarray(middle, dtype=float)
    norms = np.linalg.norm(offsets, axis=1, keepdims=True)
    directions = offsets / np.where(norms > 1e-9, norms, 1.0)
    directions[norms[:, 0] <= 1e-9] = np.array([0.0, 0.0, 1.0])
    return directions
