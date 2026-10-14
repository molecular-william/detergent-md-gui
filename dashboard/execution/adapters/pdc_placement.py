"""Detergent placement: the builder's geometry, with the gates that decide whether a run may proceed.

`micelle.packing` owns the geometry and `micelle.validation` owns the overlap and count gates; this module owns the
protein-relative clearance and the decision to stop. That split is deliberate: the builder's design says an
impossible packing writes diagnostics and produces no run, and a placement is exactly where that has to be decided.

Two modes, and a build states which one it used:

* `lattice` (the default, and the behaviour every existing run had) places the detergents on the micelle builder's
  deterministic lattice -- the seed only choosing its phase. Its *shape* is the membrane's when the protein states
  one: a build handed a `micelle.frame.MembraneFrame` places the belt as a **band** in that frame's plane, a
  cylinder whose radius is the protein's own in-slab radius plus the clearance gate and whose extent is the slab the
  structure stated, with every detergent facing across the membrane. A build with no stated membrane -- every
  packaged protein, every import that states nothing, and the empty micelle -- keeps the fixed-radius sphere about
  the protein's centroid. The mode is still `lattice` either way: the band is the lattice's own arrangement of a
  shape the frame decided, not a third generator.
* `self-assembly` places them **at random** inside the box the protein is inserted into, off the protein and off each
  other, so CG MD can let the belt find its own arrangement -- MemProtMD's Self Assembly route. The seed is the whole
  of the randomness, so the same seed rebuilds the same system and a different seed rebuilds a different one.
"""
import numpy as np

from micelle.frame import belt_points, unit_axis
from micelle.packing import golden_angle_directions, pack_micelle
from micelle.validation import validate_positions

MIN_CLEARANCE_NM = 0.5
DEFAULT_RADIUS_NM = 3.0
# The two shapes a lattice build can have. A build records which it used, because the coordinates alone cannot say
# whether a shell of sites about the centroid was a decision or the absence of a membrane to place them in.
SHAPE_BAND = 'belt-band'
SHAPE_SPHERE = 'sphere'
# The box the protein is inserted into, when the caller does not state the run's own numbers: the adapter's defaults.
DEFAULT_MARGIN_NM = 2.0
DEFAULT_INITIAL_Z_NM = 6.0
# The builder's overlap gate (`micelle.validation.validate_positions`'s default). The self-assembly sampler has to
# respect the same number, or it hands back a placement the builder's own gate then refuses.
MIN_DISTANCE_NM = 0.25

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
    decides the lattice's shape: with one, the belt is a band in that frame's plane and the clearance gate is applied
    to the band exactly as it is to the sphere; without one -- or when the frame's slab holds no atom of the protein,
    so no band radius can be measured -- the placement is the sphere it has always been. `radius_nm` is the sphere's
    radius; a band's radius is measured from the protein, and the returned `band` record carries it.
    """
    if aggregation_number < 1:
        raise ValueError('a placement needs at least one detergent')
    if radius_nm <= 0 or min_clearance_nm < 0:
        raise ValueError('the placement radius must be positive and the clearance cannot be negative')
    mode = canonical_mode(mode)
    points = None
    if protein_points is not None and len(protein_points):
        points = np.asarray([[float(value) for value in point] for point in protein_points])
        if points.ndim != 2:
            raise ValueError('protein coordinates must be a list of points')

    band = None
    if mode == 'lattice':
        if points is not None and frame is not None:
            band = _belt_band(points, aggregation_number, seed, frame, min_clearance_nm)
        if band is None:
            centers, directions = pack_micelle(points, template, aggregation_number, seed, radius=radius_nm)
        else:
            centers, directions = band['centers'], band['directions']
    else:
        centers, directions = _self_assemble(points, aggregation_number, seed, radius_nm=radius_nm,
                                             min_clearance_nm=min_clearance_nm, margin_nm=margin_nm,
                                             initial_z_nm=initial_z_nm)

    issues = list(validate_positions(centers, aggregation_number)['issues'])
    clearance = None
    if points is not None and len(points):
        clearance = min(float(np.linalg.norm(center - points, axis=1).min()) for center in centers)
        if clearance < min_clearance_nm:
            issues.append(f'detergent too close to the protein: {clearance:.3f} nm < {min_clearance_nm} nm')
    return {'centers': centers.tolist(), 'directions': directions.tolist(), 'mode': mode,
            'placement_shape': SHAPE_BAND if band is not None else SHAPE_SPHERE,
            'band': band['record'] if band is not None else None,
            'frame': frame.as_record() if frame is not None else None,
            'aggregation_number': aggregation_number, 'radius_nm': radius_nm, 'seed': seed,
            'protein_free': points is None or not len(points), 'protein_clearance_nm': clearance,
            'issues': issues, 'valid': not issues}


def _belt_band(points, count, seed, frame, min_clearance_nm):
    """The belt as a band in the membrane plane, or `None` when the frame's slab holds no atom of the protein.

    The band is a cylinder about the frame's own axis: its radius is the furthest *in-slab* atom's distance from that
    axis plus the clearance the gate asks for, and its extent is the slab the structure stated -- so the sites sit
    where a belt of detergent sits, in the membrane around the protein, rather than on a shell of a fixed radius
    about a centroid that need not be on the membrane at all. The seed only chooses the ladder's phase, exactly as it
    does on the sphere.

    `None` is the answer when the slab holds no atom -- a stated membrane the protein is not in, or a structure whose
    atoms all sit in its soluble domains. There is no measured radius to build a band from then, and a guessed one is
    indistinguishable from a measured one once it is in a run, so the caller keeps the sphere it had.

    The band's radius is *measured*, not chosen, and the gate is applied to the result rather than to the intent: an
    atom outside the slab can still sit close to a site, and when one does the placement is refused with the same
    reason it has always given instead of the band being moved out of its way.
    """
    axis = np.asarray(unit_axis(frame.axis), dtype=float)
    inside = np.asarray(belt_points(points, frame), dtype=float)
    if not len(inside):
        return None
    axial = inside @ axis
    slab_radius = float(np.linalg.norm(inside - np.outer(axial, axis), axis=1).max())
    radius = slab_radius + min_clearance_nm
    centers, directions = _band_sites(count, seed, frame, radius)
    return {'centers': centers, 'directions': directions,
            'record': {'shape': SHAPE_BAND, 'radius_nm': round(radius, 6),
                       'slab_radius_nm': round(slab_radius, 6), 'axis': list(axis),
                       'plane_low_nm': frame.plane_low_nm, 'plane_high_nm': frame.plane_high_nm,
                       'source': frame.source}}


def _band_sites(count, seed, frame, radius):
    """`count` sites on the band: the lattice's own golden-angle ladder, wrapped onto the cylinder.

    The ladder is `pack_micelle`'s (`golden_angle_directions`), so the two shapes are one arrangement of two
    surfaces: its azimuths become the band's headings and its z ladder the positions across the slab, with the seed
    choosing only the phase. Each site's direction is its own heading -- the way out of the belt, which is where the
    detergent's head faces -- measured from the band's axis and not from the protein's centre, because on a band
    those are two different points.
    """
    axis = np.asarray(unit_axis(frame.axis), dtype=float)
    ladder = golden_angle_directions(count, seed)
    headings = np.arctan2(ladder[:, 1], ladder[:, 0])
    across, up = _plane_basis(axis)
    outward = np.cos(headings)[:, None] * across + np.sin(headings)[:, None] * up
    axial = frame.centre_nm + frame.half_thickness_nm * ladder[:, 2]
    return axial[:, None] * axis + radius * outward, outward


def _plane_basis(axis):
    """Two unit vectors spanning the membrane plane, chosen from the axis, so the band faces whichever way it does."""
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
    out of it, and for a band it is the site's own membrane-plane heading (`_belt_band`), which is the way out of the
    belt. `pdc_build.stamp` aims the detergent's head-ward axis along whichever direction it is handed, so a
    direction pointing inward would face the head at the micelle.
    """
    if not len(centers):
        return np.empty((0, 3))
    offsets = np.asarray(centers, dtype=float) - np.asarray(middle, dtype=float)
    norms = np.linalg.norm(offsets, axis=1, keepdims=True)
    directions = offsets / np.where(norms > 1e-9, norms, 1.0)
    directions[norms[:, 0] <= 1e-9] = np.array([0.0, 0.0, 1.0])
    return directions
