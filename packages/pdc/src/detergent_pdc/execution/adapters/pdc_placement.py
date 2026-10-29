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
  membrane -- every packaged protein, every import that states nothing, and the empty micelle -- is placed in a
  **sphere** whose radius is *measured* from the protein it is handed (see the measurements below), with `radius_nm`
  acting as a floor. The mode is still `lattice` either way: the tube is the lattice's own arrangement of a shape the
  frame decided, not a third generator.
* `self-assembly` places them **at random** inside the box the protein is inserted into, off the protein and off each
  other, so CG MD can let the belt find its own arrangement -- MemProtMD's Self Assembly route. The seed is the whole
  of the randomness, so the same seed rebuilds the same system and a different seed rebuilds a different one, and
  each detergent's **orientation is drawn** from that same seed (uniform on the sphere) and then flipped so its head
  faces away from the protein -- not one radial for the whole cloud, which is what every molecule used to get.

Three measurements the module makes rather than assumes, and records:

* the **clearance is the detergent's own body**, not its head site alone: `detergent_profile` reads the molecule's
  head end and every bead's offset from it out of the molecule's own coordinates, `body_beads` lays that body down at
  a (site, direction) pair, and a draw is refused when any bead comes within `BEAD_CLEARANCE_NM` of a protein bead.
  A template whose molecule states no coordinates keeps the head-only gate and says so.
* the **sphere's radius is measured** from the protein the placement is handed -- extent about the centroid plus the
  clearance plus the molecule's reach -- with `radius_nm` demoted to a floor, exactly the role it already plays under
  a belt's centre-line. A run that selects one subunit gets that subunit's shell, and `radius_source` says which of
  the two numbers decided.
* the **capacity** is measured against those same gates when a count cannot be placed, so a refusal can say what the
  shape would hold. The requested number is never scaled (`capacity`).
"""
import numpy as np

from micelle.frame import belt_points, unit_axis
from micelle.packing import golden_angle_directions, pack_micelle
from micelle.validation import validate_positions

MIN_CLEARANCE_NM = 0.5
# The gate on the detergent's **body**. `MIN_CLEARANCE_NM` stays what it has always been -- the distance a placed
# *head site* must keep from the protein -- and this is the distance any of the molecule's own beads must keep from
# it, in both generators. Kept as its own constant because the two measure different things: a head site is one point
# and a body is the molecule, so folding this into `MIN_CLEARANCE_NM` would either loosen the head gate or make the
# reported clearance mean something it does not.
BEAD_CLEARANCE_NM = 0.25
# The placement radius: the sphere's own radius for a build with no membrane, and a *floor* on a protein build's
# belt. A belt's centre-line is measured from the protein (its slab radius), and this setting can only push that
# line further out -- never pull it inside the cylinder the protein was measured to occupy. See `place_detergents`.
DEFAULT_RADIUS_NM = 3.0
# The two shapes a lattice build can have. A build records which it used, because the coordinates alone cannot say
# whether a shell of sites about the centroid was a decision or the absence of a membrane to place them in.
SHAPE_TORUS = 'belt-torus'
SHAPE_SPHERE = 'sphere'
# How each mode came by its orientations, recorded so a report can tell the two apart without inspecting vectors.
ORIENTATION_RADIAL = 'radial'
ORIENTATION_RANDOM_OUTWARD = 'random-outward'
# Which number decided a shape's radius: the protein's own measurement, or the setting used as a floor under it.
RADIUS_MEASURED = 'measured'
RADIUS_FLOOR = 'floor'
# The element letters a molecule's own coordinate file marks its polar end with. A temperature-coupling bead and a
# DDM's ten oxygens are both "not a carbon", but only the second is a head: this is what the geometry can read when
# the molecule carries no Martini types of its own (every packaged template: one bead typed `registered-template`).
POLAR_ELEMENTS = ('O', 'N', 'S', 'P')

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
    from detergent_pdc.execution.adapters.pdc_import import structure_atoms

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


def detergent_profile(template) -> dict | None:
    """The molecule's own body: its head end, its head-ward axis, and every bead's offset from that head end.

    `None` when the molecule states no coordinates at all: a profile invented from a length would be a guess the
    clearance gate then treats as a measurement -- the same reason `_belt_torus` refuses to build a tube without a
    length, and the reason the placement records `body_profile: None` instead of claiming a check it did not run.

    The positions are the molecule's own, in the order `detergent_length_nm` already reads them: the template's bead
    records when they carry coordinates (a mapping-derived template does), and the file the template names otherwise
    (`template.coordinates`, the DDM's 81-atom structure). Nothing here invents a bead.

    The **head end** is read from the molecule rather than assumed, in this order:

    * a bead whose record says `role: head` (the mapping's own label), against the beads labelled `tail`;
    * a bead whose Martini `type` distinguishes them the way `pdc_build.stamp` does -- a `C`-type bead is a tail, and
      anything else is a head;
    * a coordinate file's polar atoms (`O`, `N`, `S`, `P`): the sugar end of a DDM, and the only head a template
      with one bead typed `registered-template` states about itself;
    * failing all three, the principal component of the molecule's own bead centres, signed so the head faces away
      from the template's stated `tail_direction`.

    `head_source` in the record says which of the four it was, so a reader can tell a labelled head from a
    geometric one. The head **anchor** is the furthest bead along that axis -- the point `pdc_build.stamp` puts at
    the site -- so every recorded offset is zero-or-behind and `body_beads` reproduces the body the build stamps.
    """
    if template is None:
        return None
    beads = [bead for bead in (getattr(template, 'beads', ()) or ()) if isinstance(bead, dict)]
    stated = [bead.get('position') for bead in beads]
    if beads and all(isinstance(position, (list, tuple)) and len(position) == 3 for position in stated):
        points = np.asarray([[float(value) for value in position] for position in stated], dtype=float)
        labels, source = beads, 'beads'
    else:
        from detergent_pdc.execution.adapters.pdc_import import structure_atoms

        try:
            atoms = structure_atoms(template.coordinates)
        except (OSError, ValueError):
            return None
        points = np.asarray([[float(value) for value in atom['position']] for atom in atoms], dtype=float)
        labels, source = atoms, 'coordinates'
    if len(points) < 2 or not np.isfinite(points).all():
        return None

    axis, head_source = None, None
    roles = [str(label.get('role') or '').strip().lower() for label in labels]
    types = [str(label.get('type') or '').strip() for label in labels]
    names = [str(label.get('name') or '').strip() for label in labels]
    if 'head' in roles and 'tail' in roles:
        head = np.asarray([role == 'head' for role in roles])
        head_source = 'roles'
    elif any(types) and any(not kind.startswith('C') for kind in types) \
            and any(kind.startswith('C') for kind in types):
        head = np.asarray([not kind.startswith('C') for kind in types])
        head_source = 'types'
    elif any(name[:1].upper() in POLAR_ELEMENTS for name in names) \
            and any(name[:1].upper() not in POLAR_ELEMENTS for name in names):
        head = np.asarray([name[:1].upper() in POLAR_ELEMENTS for name in names])
        head_source = 'polar-atoms'
    else:
        head = None
    if head is not None:
        direction = points[head].mean(axis=0) - points[~head].mean(axis=0)
        span = float(np.linalg.norm(direction))
        if span > 1e-9:
            axis = direction / span
    if axis is None:
        axis = _principal_axis(points, getattr(template, 'tail_direction', (0.0, 0.0, -1.0)))
        head_source = 'principal-axis'
        if axis is None:
            return None

    # The head anchor: the point on the axis at the furthest bead's own projection. Everything below is measured
    # from it, which is what makes the site the molecule's *head end* rather than its centre of mass.
    centroid = points.mean(axis=0)
    head_point = centroid + axis * (float((points @ axis).max()) - float(centroid @ axis))
    offsets = points - head_point
    axial = offsets @ axis
    radial = offsets - np.outer(axial, axis)
    return {'offsets': offsets, 'axis': axis, 'head_point': head_point,
            'length_nm': float(-axial.min()), 'reach_nm': float(np.linalg.norm(offsets, axis=1).max()),
            'radial_nm': float(np.linalg.norm(radial, axis=1).max()),
            'bead_count': int(len(points)), 'source': source, 'head_source': head_source}


def _principal_axis(points, tail_direction=None):
    """The molecule's longest axis, signed so its head end is the end the tail direction points away from.

    The eigenvector of the largest eigenvalue of the bead centres' covariance -- the axis a molecule with no labelled
    head is longest along. Its sign is a choice, and it is decided by the template's own `tail_direction` when that
    says anything about this axis; a molecule whose stated tail is perpendicular to its long axis (every two-atom
    fixture, whose atoms lie along x and whose default tail points down z) is signed by its largest component
    instead, so the answer is the same on every call and never depends on the eigensolver's sign.
    """
    if len(points) < 2:
        return None
    centred = points - points.mean(axis=0)
    values, vectors = np.linalg.eigh(centred.T @ centred)
    axis = np.asarray(vectors[:, int(np.argmax(values))], dtype=float)
    span = float(np.linalg.norm(axis))
    if span <= 1e-12:
        return None
    axis = axis / span
    stated = None if tail_direction is None else np.asarray(tail_direction, dtype=float)
    if stated is not None and float(np.linalg.norm(stated)) > 0:
        projected = float(axis @ (stated / np.linalg.norm(stated)))
        if abs(projected) > 1e-6:
            # The head faces away from the stated tail: `axis` is head-ward, so its dot with the tail is negative.
            return axis if projected < 0 else -axis
    largest = int(np.argmax(np.abs(axis)))
    return axis if axis[largest] > 0 else -axis


def body_beads(site, direction, profile) -> np.ndarray:
    """Every bead of one detergent, in world coordinates, for a head at `site` and a body along `direction`.

    The rotation is the one `pdc_build.stamp` applies -- the minimal rotation taking the molecule's head-ward axis
    onto `direction` -- so the body measured here is the body the build writes, not an approximation of it. A
    template with no profile (`None`) answers with the head site alone, which is the gate this module had before the
    molecule's own shape was readable: one point per molecule.
    """
    site = np.asarray(site, dtype=float).reshape(3)
    if profile is None:
        return site.reshape(1, 3)
    target = np.asarray(direction, dtype=float).reshape(3)
    span = float(np.linalg.norm(target))
    target = target / span if span > 1e-12 else np.array([0.0, 0.0, 1.0])
    return site + profile['offsets'] @ _alignment(profile['axis'], target).T


def _alignment(axis, target):
    """The minimal rotation taking one unit vector onto another, including the antiparallel case.

    The same map `pdc_build.stamp` applies to a molecule, written here because the gate has to measure the body the
    stage writes and `pdc_build` imports this module (so this cannot import it back).
    """
    cross = np.cross(axis, target)
    sine = float(np.linalg.norm(cross))
    cosine = float(np.dot(axis, target))
    if sine < 1e-9:
        if cosine > 0:
            return np.eye(3)
        perpendicular = np.array([1.0, 0.0, 0.0]) if abs(axis[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        perpendicular = perpendicular - axis * float(np.dot(perpendicular, axis))
        perpendicular = perpendicular / np.linalg.norm(perpendicular)
        return 2.0 * np.outer(perpendicular, perpendicular) - np.eye(3)
    cross = cross / sine
    skew = np.array([[0.0, -cross[2], cross[1]], [cross[2], 0.0, -cross[0]], [-cross[1], cross[0], 0.0]])
    return np.eye(3) + sine * skew + (1.0 - cosine) * (skew @ skew)


def _bead_gate_sentence(profile) -> str | None:
    """Why the body gate is not being applied, or `None` when it is.

    A placement may never claim a check it did not run: a template whose molecule states no coordinates keeps the
    head-only gate and says so in its record.
    """
    if profile is not None:
        return None
    return ('the template\'s molecule states no coordinates, so the clearance is measured against the head site '
            'only and not against the detergent\'s own beads')


def body_clearance(site, direction, profile, points) -> float:
    """The closest approach of one placed detergent's own beads to any protein point, in nm.

    `inf` when there is nothing to measure against (no protein, or a template with no profile) -- which is the value
    that reads as "this gate has nothing to say", not the value that reads as "clear".
    """
    if profile is None or points is None or not len(points):
        return float('inf')
    offsets = np.asarray(points, dtype=float) - np.asarray(site, dtype=float)
    # Only a protein point within the molecule's own reach plus the gate can be within the gate of any bead, and the
    # triangle inequality makes that exact -- so a draw far from the protein costs one distance per point.
    limit = profile['reach_nm'] + BEAD_CLEARANCE_NM
    near = offsets[np.einsum('ij,ij->i', offsets, offsets) <= limit * limit]
    if not len(near):
        return float('inf')
    # Both sides in the site's own frame, so the comparison is bead-to-point and not offset-to-offset.
    beads = body_beads(site, direction, profile) - np.asarray(site, dtype=float)
    gap = beads[:, None, :] - near[None, :, :]
    return float(np.sqrt((gap * gap).sum(axis=2)).min())


def placed_bead_clearance(centers, directions, profile, points) -> float | None:
    """The closest any placed detergent's own bead comes to any protein point, over the whole placement.

    The gate above answers *yes or no* cheaply, because a protein bead far from the site cannot be within the gate of
    any bead. A reported number cannot be got that way -- the answer is the minimum over every bead and every point,
    including the ones far away -- so it is measured once, here, in blocks of detergents so the intermediate array
    stays small: 16 molecules of 81 atoms against 928 protein beads is 1.2 M distances, and the whole set is a few
    hundred milliseconds at most. `None` means there was nothing to measure (no protein, or a template with no
    profile), which is not the same answer as "zero".
    """
    if profile is None or points is None or not len(points) or not len(centers):
        return None
    cloud = np.asarray(points, dtype=float)
    best = float('inf')
    for start in range(0, len(centers), 16):
        block = np.asarray(centers[start:start + 16], dtype=float)
        headings = np.asarray(directions[start:start + 16], dtype=float)
        beads = np.concatenate([body_beads(site, direction, profile)
                                for site, direction in zip(block, headings)])
        gap = beads[:, None, :] - cloud[None, :, :]
        best = min(best, float(np.sqrt((gap * gap).sum(axis=2)).min()))
    return None if not np.isfinite(best) else best


def extent_about_centroid(points) -> float:
    """How far the protein's own coordinates reach from their centroid: the extent a shell has to clear.

    Measured from the centroid and not from the nearest point, so the number is a property of the selection handed
    in -- `protein_chains` are filtered before the placement sees the beads, and a smaller selection measures less.
    """
    cloud = np.asarray(points, dtype=float)
    if not len(cloud):
        return 0.0
    return float(np.linalg.norm(cloud - cloud.mean(axis=0), axis=1).max())


def _profile_record(profile) -> dict | None:
    """The body profile as the placement records it: the numbers the gate used, never the coordinates."""
    if profile is None:
        return None
    return {'bead_count': profile['bead_count'], 'length_nm': round(profile['length_nm'], 6),
            'radial_nm': round(profile['radial_nm'], 6), 'reach_nm': round(profile['reach_nm'], 6),
            'head_source': profile['head_source'], 'source': profile['source']}


def place_detergents(protein_points, template, aggregation_number, seed, *, radius_nm=DEFAULT_RADIUS_NM,
                     min_clearance_nm=MIN_CLEARANCE_NM, mode=DEFAULT_PLACEMENT_MODE, margin_nm=DEFAULT_MARGIN_NM,
                     initial_z_nm=DEFAULT_INITIAL_Z_NM, frame=None, measure_capacity=True):
    """Place `aggregation_number` detergents around the protein (or around nothing, for an empty micelle).

    Deterministic in the seed through whichever generator the mode names, and gated before anything runs: the
    returned mapping carries the positions, the mode, *and* the issues, so a caller cannot proceed past a failed gate
    without acknowledging it.

    Two clearances, and they measure different things. `min_clearance_nm` is the distance a placed **head site** keeps
    from the protein -- the number the panel has always reported. `BEAD_CLEARANCE_NM` is the distance any bead of the
    **molecule the build stamps** keeps from it: `body_beads` expands a (site, direction) pair into the detergent's
    own coordinates, and a draw whose body reaches inside the gate is refused rather than nudged, in both
    generators. A template whose molecule states no coordinates keeps the head-only gate, and the record says so
    (`body_profile: None` and `body_profile_reason`) rather than claiming a check it did not run.

    `frame` is the membrane the protein stated for itself (`micelle.frame`), or `None`. It is the *only* thing that
    decides the lattice's shape: with one, the belt is a **torus** about the protein's own cylinder -- its branch of
    the geometry is `_belt_torus`, and the sites it returns are the detergents' head ends; without one -- or when
    the frame's slab holds no atom of the protein, or the detergent's own length cannot be measured -- the placement
    is the sphere it has always been, and `belt_reason` says which of those it was.

    `radius_nm` is a **floor** under both lattice shapes, and the record keeps both numbers. A belt's centre-line is
    `max(measured slab radius, radius_nm)`; the sphere's shell is `max(radius_nm, extent about the centroid +
    min_clearance_nm + the molecule's own reach)`, so a shell follows the subunits the run actually includes instead
    of being the same 3 nm about the whole complex (`radius_source` says which of the two decided). The tube's own
    radius is not a setting at all -- it is the detergent's length (`detergent_length_nm`). An empty micelle has no
    protein to measure, so it keeps using `radius_nm` as the sphere's radius, and can only ever report that.

    A placement that fails its gates measures what a shell *could* hold (`capacity`), against the same gates, and
    records it as `capacity_aggregation` -- the requested number itself is never changed. `measure_capacity=False` is
    how that measurement calls back in without measuring itself again.
    """
    if aggregation_number < 1:
        raise ValueError('a placement needs at least one detergent')
    if radius_nm <= 0 or min_clearance_nm < 0:
        raise ValueError('the placement radius must be positive and the clearance cannot be negative')
    mode = canonical_mode(mode)
    profile = detergent_profile(template)
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

    band, belt_reason, shell = None, None, None
    if unplaced:
        # Nothing is drawn against a protein whose beads have no position: the sampler's own box is centred on the
        # beads' mean -- a `nan` -- and `numpy` refuses to draw from it (`OverflowError`), and the tube's ladder
        # would keep every site because no rejection could be measured.
        centers, directions = np.empty((0, 3)), np.empty((0, 3))
    elif mode == 'lattice':
        if points is not None and frame is not None:
            band, belt_reason = _belt_torus(points, aggregation_number, seed, frame, min_clearance_nm, radius_nm,
                                            template, profile)
        if band is None:
            shell = _sphere_shell(points, template, profile, radius_nm, min_clearance_nm)
            centers, directions = pack_micelle(points, template, aggregation_number, seed,
                                               radius=shell['radius_nm'])
        else:
            centers, directions = band['centers'], band['directions']
    else:
        centers, directions = _self_assemble(points, aggregation_number, seed, radius_nm=radius_nm,
                                             min_clearance_nm=min_clearance_nm, margin_nm=margin_nm,
                                             initial_z_nm=initial_z_nm, profile=profile)

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
    body = None
    if not unplaced and len(centers):
        body = placed_bead_clearance(centers, directions, profile, points)

    capacity_aggregation = None
    if issues and not unplaced and measure_capacity:
        capacity_aggregation = capacity(points, template, aggregation_number, mode=mode, radius_nm=radius_nm,
                                        min_clearance_nm=min_clearance_nm, margin_nm=margin_nm,
                                        initial_z_nm=initial_z_nm, frame=frame)
        if 0 < capacity_aggregation['count'] < aggregation_number:
            issues.append(_capacity_sentence(capacity_aggregation))

    # The numbers the shape was built at, and the settings they were measured over. `radius_nm` is the radius of the
    # shape this placement built -- the sphere's shell, the belt's centre-line -- and `radius_floor_nm` is the
    # setting that is only a floor under it; the two are equal for an empty micelle and whenever the setting decided.
    if shell is not None:
        radius, radius_source = shell['radius_nm'], shell['radius_source']
        _with_density(shell, len(centers), shell['volume_nm3'])
    elif band is not None:
        radius, radius_source = band['record']['centre_line_radius_nm'], band['record']['radius_source']
        _with_density(band['record'], len(centers), band['record']['volume_nm3'])
    else:
        # A self-assembled cloud is not a shape with a radius: `radius_nm` sizes the region an empty micelle is drawn
        # in and nothing else, so nothing was measured and nothing is claimed.
        radius, radius_source = float(radius_nm), None
    if unplaced:
        radius_source = None
    return {'centers': centers.tolist(), 'directions': directions.tolist(), 'mode': mode,
            # Nothing was drawn against a protein no measurement could be made of, so there is no shape to name.
            'placement_shape': None if unplaced else (SHAPE_TORUS if band is not None else SHAPE_SPHERE),
            'band': band['record'] if band is not None else None,
            'shell': shell,
            'belt_reason': belt_reason,
            'frame': frame.as_record() if frame is not None else None,
            'aggregation_number': aggregation_number, 'radius_nm': radius,
            'radius_floor_nm': round(float(radius_nm), 6), 'radius_source': radius_source,
            # Which generator's orientations these are: the lattice's are its shape's own normals, and a
            # self-assembled cloud's are drawn from the seed and flipped so each head faces away from the protein.
            'orientation_policy': None if unplaced else (
                ORIENTATION_RADIAL if mode == 'lattice' else ORIENTATION_RANDOM_OUTWARD),
            # The detergent's own shape, as the gate read it, and why it could not when it could not. A number here is
            # a measurement; `None` with a reason is the honest answer for a molecule that states no coordinates.
            'body_profile': _profile_record(profile), 'body_profile_reason': _bead_gate_sentence(profile),
            'seed': seed,
            'protein_free': points is None or not len(points), 'protein_clearance_nm': clearance,
            'bead_clearance_nm': None if body is None else round(float(body), 6),
            'capacity_aggregation': capacity_aggregation,
            'issues': issues, 'valid': not issues}


def _sphere_shell(points, template, profile, radius_nm, min_clearance_nm) -> dict:
    """The sphere's radius, measured from the protein the placement was handed, with `radius_nm` as its floor.

    `shell = max(radius_nm, extent about the centroid + min_clearance_nm + the molecule's own reach)`, which is the
    same relationship the torus already has to its centre-line: the measurement decides and the setting can only push
    the shape out. The extent is the furthest bead of the *selected* protein from its centroid, so a run whose
    `protein_chains` names one subunit gets the shell that subunit needs rather than the whole complex's -- the
    chains are filtered before the placement is called, so nothing here has to filter them again.

    The molecule's own reach is its measured length (`detergent_length_nm`, the greatest atom-to-atom distance) or,
    when its bead records are the only coordinates it states, the furthest bead from its head end. Taking the larger
    of the two is what makes the shell's guarantee true: every bead of a placed detergent stands within that reach of
    its site, so a shell at that radius keeps every bead clear of every protein point by `min_clearance_nm` -- and
    the bead gate's own 0.25 nm is satisfied with room to spare.

    A protein-free build has nothing to measure and a molecule may state no coordinates at all; both keep
    `radius_nm` as the radius and say so (`radius_reason`), because a shell computed from a guessed length would be
    indistinguishable from a measured one once it is in a run.
    """
    floor = round(float(radius_nm), 6)
    extent = measured = None
    length = detergent_length_nm(template)
    reach = None if profile is None else float(profile['reach_nm'])
    span = max([value for value in (length, reach) if value is not None], default=None)
    reason = None
    if points is None or not len(points):
        reason = 'an empty micelle has no protein to measure a shell from'
    elif span is None:
        reason = ('neither the molecule\'s own structure nor its bead records state a length, so the shell '
                  'cannot be measured and the radius stays the setting')
    else:
        extent = extent_about_centroid(points)
        measured = float(extent) + float(min_clearance_nm) + float(span)
    radius = floor if measured is None else round(max(floor, measured), 6)
    return {'shape': SHAPE_SPHERE, 'radius_nm': radius, 'radius_floor_nm': floor,
            'radius_source': RADIUS_MEASURED if measured is not None and measured > floor + 1e-12 else RADIUS_FLOOR,
            'measured_shell_nm': None if measured is None else round(measured, 6),
            'measured_extent_nm': None if extent is None else round(float(extent), 6),
            'detergent_length_nm': None if length is None else round(float(length), 6),
            'shell_reach_nm': None if span is None else round(float(span), 6),
            'radius_reason': reason,
            'volume_nm3': round(4.0 / 3.0 * np.pi * radius ** 3, 6)}


def _with_density(record, count, volume_nm3) -> None:
    """Record how crowded the shape is: the count over its own volume, and the volume one detergent has.

    Reported, never acted on -- the aggregation number stays the user's number (`capacity` measures what would fit;
    nothing is rescaled here). The pair is what lets a refusal be read as "this shell is too dense for 150" rather
    than as a mystery.
    """
    volume = float(volume_nm3)
    record['detergents'] = int(count)
    record['estimated_density_per_nm3'] = round(count / volume, 6) if count and volume > 0 else None
    record['capacity_nm3_per_detergent'] = round(volume / count, 6) if count and volume > 0 else None


def _capacity_sentence(measurement) -> str:
    """The one clause a refusal adds: how many detergents the shell would hold, and how that was measured."""
    return (f'the shell holds about {measurement["count"]} at the {MIN_DISTANCE_NM} nm overlap gate '
            f'(measured over {len(measurement["seeds"])} seeds)')


def capacity(points, template, requested, *, mode=DEFAULT_PLACEMENT_MODE, radius_nm=DEFAULT_RADIUS_NM,
             min_clearance_nm=MIN_CLEARANCE_NM, margin_nm=DEFAULT_MARGIN_NM,
             initial_z_nm=DEFAULT_INITIAL_Z_NM, frame=None, seeds=(1, 2, 3)) -> dict:
    """The largest count every seed places validly, by bisection over the placer's own gate.

    A bisection between 1 and `requested`, `ceil(log2(requested))` placements per seed and no geometry written down
    twice: the answer is whatever the placement the run would build accepts, including the count, the overlap gate,
    the clearance and the bead-level body gate. The one assumption is that a shell that holds `n` holds `n - 1`,
    which is what makes bisection meaningful at all -- and the count it answers with is one the gate accepted, on
    every seed, so a refusal built from it cannot promise a number the placement would then refuse.

    `count` is 0 when not even one detergent can be placed clear, and `requested` when the whole count fits. The
    requested number is never changed: this measures, it does not rescale.
    """
    requested = int(requested)
    seeds = tuple(int(seed) for seed in (seeds or (1,))) or (1,)

    def fits(count: int) -> bool:
        if count < 1:
            return False
        return all(place_detergents(points, template, count, seed=seed, radius_nm=radius_nm,
                                    min_clearance_nm=min_clearance_nm, mode=mode, margin_nm=margin_nm,
                                    initial_z_nm=initial_z_nm, frame=frame, measure_capacity=False)['valid']
                   for seed in seeds)

    if fits(requested):
        return {'count': requested, 'seeds': list(seeds), 'requested': requested}
    low, high = 0, requested
    while high - low > 1:
        middle = (low + high) // 2
        if fits(middle):
            low = middle
        else:
            high = middle
    return {'count': low, 'seeds': list(seeds), 'requested': requested}


def _belt_torus(points, count, seed, frame, min_clearance_nm, radius_nm, template, profile=None):
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
                                                             min_clearance_nm, profile)
    return {'centers': centers, 'directions': directions,
            'record': {'shape': SHAPE_TORUS, 'tube_radius_nm': round(length, 6),
                       'centre_line_radius_nm': round(centre_radius, 6),
                       'slab_radius_nm': round(slab_radius, 6), 'radius_floor_nm': round(float(radius_nm), 6),
                       'radius_source': RADIUS_MEASURED if slab_radius > float(radius_nm) + 1e-12 else RADIUS_FLOOR,
                       'radius_nm': round(length, 6), 'belt_reach_nm': round(length, 6),
                       # The tube's own volume (Pappus: 2 pi^2 R r^2), so the belt's density and the sphere's are the
                       # same measurement of a different shape and the panel can print either.
                       'volume_nm3': round(2.0 * np.pi ** 2 * centre_radius * length ** 2, 6),
                       'detergents_drawn': drawn, 'rejected': rejected, 'passes': passes, 'axis': list(axis),
                       'plane_low_nm': frame.plane_low_nm, 'plane_high_nm': frame.plane_high_nm,
                       'source': frame.source}}, None


def _tube_sites(count, seed, frame, centre_radius, length, protein_points, min_clearance_nm, profile=None):
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

    Two gates decide an entry, and the second is the one this could not measure before: the **head site** must keep
    `min_clearance_nm` from every protein bead (the number the placement reports), and the detergent's **own body**,
    expanded by `body_beads` along the site's meridian, must keep `BEAD_CLEARANCE_NM` from every one of them. A tube
    whose surface passes through a soluble domain is refused at the bead that reaches it, not only at the head that
    misses it. Both refuse the draw rather than moving it.
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
            if body_clearance(candidate, direction, profile, protein_points) < BEAD_CLEARANCE_NM:
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


def _self_assemble(points, count, seed, *, radius_nm, min_clearance_nm, margin_nm, initial_z_nm, profile=None):
    """A random cloud of `count` detergents inside the box the protein is inserted into, off the protein.

    The region is the box `pdc_box.initial_box` states for the protein -- the protein's own extent plus the margin in
    x and y, and the stated initial z -- centred on the protein, so every detergent is inside the box the run's own
    report records. An empty micelle has no extent to measure, so its region is a cube that follows the requested
    radius, which is the scale the lattice would have used.

    **Orientation is drawn, not inherited.** Each detergent's direction is a normal draw (three Gaussian components,
    normalised) from the same generator and in the same order as its site, so the cloud's orientations are uniform on
    the sphere instead of all being the one radial of the cloud's centre -- which made every molecule at the top and
    every molecule at the side point the same way. Each is then flipped, never rotated, so the head faces away from
    the protein: away from the nearest protein bead to its site, or -- for an empty micelle, which has no protein --
    away from the cloud's own centre. The flip leaves the *spread* alone (it only decides which end of the drawn axis
    is the head) and keeps the chemists' requirement that a head faces the water. `ORIENTATION_RANDOM_OUTWARD`
    records the policy.

    One `numpy` generator seeded by the build's seed is the entire source of randomness; a draw that lands on the
    protein, on an earlier detergent, or -- with a molecule whose own beads are readable -- whose **body** reaches
    within `BEAD_CLEARANCE_NM` of a protein bead, is discarded, not nudged.
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
    headings: list[np.ndarray] = []
    # A bounded number of draws. A region that cannot hold the count returns what it could place, and the count gate
    # then reports it as an impossible packing, rather than the sampler looping forever on a request with no answer.
    for _ in range(max(1000, 200 * count)):
        if len(accepted) >= count:
            break
        candidate = rng.uniform(low, high)
        drawn = rng.standard_normal(3)
        span = float(np.linalg.norm(drawn))
        direction = drawn / span if span > 1e-12 else np.array([0.0, 0.0, 1.0])
        nearest, nearest_point = None, None
        if points is not None and len(points):
            offsets = points - candidate
            distances = np.einsum('ij,ij->i', offsets, offsets)
            closest = int(np.argmin(distances))
            nearest, nearest_point = float(np.sqrt(distances[closest])), points[closest]
            if nearest < min_clearance_nm:
                continue
        if accepted and float(np.linalg.norm(candidate - np.asarray(accepted), axis=1).min()) < MIN_DISTANCE_NM:
            continue
        # The head faces away from what the detergent is up against: the protein bead nearest its site, or the
        # cloud's centre when there is no protein to be near. The flip comes **before** the body gate, because it
        # moves the body to the site's other side and the bead that has to be measured is the one that will be
        # stamped -- gate first and flipped after accepts a body nobody measured.
        away = (candidate - nearest_point) if nearest_point is not None else (candidate - middle)
        if float(np.dot(direction, away)) < 0:
            direction = -direction
        if body_clearance(candidate, direction, profile, points) < BEAD_CLEARANCE_NM:
            continue
        accepted.append(candidate)
        headings.append(direction)

    centers = np.asarray(accepted, dtype=float) if accepted else np.empty((0, 3))
    directions = np.asarray(headings, dtype=float) if headings else np.empty((0, 3))
    return centers, directions


def _initial_box(points, margin_nm, initial_z_nm):
    """The box rule, imported where it is used: `pdc_box` is otherwise only reached through the build entry point."""
    from detergent_pdc.execution.adapters.pdc_box import initial_box

    return initial_box([list(point) for point in points], margin_nm=margin_nm, initial_z_nm=initial_z_nm)


def _outward(middle, centers):
    """Each detergent's outward direction: the way out of the cloud, which is the way its head faces.

    The lattice's directions are its shell's own radial vectors (`pack_micelle` builds the centres as the middle
    plus `radius * direction`) and its tube's are the meridian directions (`_tube_sites`), and this is the same
    convention expressed for a cloud of sites: the direction is the way out of it. `pdc_build.stamp` aims the
    detergent's head end along whichever direction it is handed, so a direction pointing inward would face the head
    at the micelle.

    The **self-assembly sampler no longer uses this** (2026-10-21): drawing one radial for every detergent made the
    whole cloud point one way, so `_self_assemble` draws each direction from its own seed and flips it outward
    instead. What remains here is the convention itself, named and tested, for anything that has a cloud of sites and
    needs the heads facing out of it.
    """
    if not len(centers):
        return np.empty((0, 3))
    offsets = np.asarray(centers, dtype=float) - np.asarray(middle, dtype=float)
    norms = np.linalg.norm(offsets, axis=1, keepdims=True)
    directions = offsets / np.where(norms > 1e-9, norms, 1.0)
    directions[norms[:, 0] <= 1e-9] = np.array([0.0, 0.0, 1.0])
    return directions
