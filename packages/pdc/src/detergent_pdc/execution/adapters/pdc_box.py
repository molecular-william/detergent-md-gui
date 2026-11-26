"""The box rules: what the protein's own extent becomes before and after the detergent arrives.

The rules are pure functions of coordinates, because the protocol's box arithmetic is the part most worth checking
without GROMACS and the easiest part to get quietly wrong: an off-by-a-margin box either lets the protein touch a
periodic image or silently changes the density a placement was built for.

`initial_box` is the box a protein is inserted into, `extended_box` the one it gets once the detergents are placed,
`membrane_box` the one a protein that states its own membrane gets: centred on that membrane's plane, with z
clearing the protein and the belt, and x/y widened to the belt's radial reach. `auto_initial_xy` is the x/y those
insertion rules derive when the caller states none.

A stated initial x, y or z is the cell's dimension whenever it can hold the system (the protein, and in
`membrane_box` the belt too): that is the number the build writes and the preview draws. A number smaller than that
cannot be honoured without putting a face through the system, so the cell is widened to the requirement and the
caller records the difference -- `pdc_build` and `pdc_preview` compare the stated numbers with the written box and
report the widening (`box_notes`) rather than failing a run for a stale field. A blank axis is the derived value
exactly, never zero.

The density a placement was built at is its shape's, not its cell's: a lattice belt's volume is the torus's own
(measured from the band, not from the box), a sphere's is the ball's, so widening the box after the placement
leaves the recorded density where it was. Self-assembly is the one generator that samples inside the box it is
given, so its box is the placement's own and this module does not widen it.
"""
import math

#: How far a stated dimension may sit below the derived one and still count as equal, covering the rounding both
#: sides apply (six places) without accepting a box that genuinely cuts the system.
TOLERANCE_NM = 1e-6

#: The unit cells a PDC run may write. `rectangular` is the historical cell, three independent edge lengths; the four
#: after it are the validation panel's shapes, every vector of length d and the same minimum image distance, so a run
#: gets the same cut-off room with less solvent. The values are `aabase.SHAPES`' spelling on purpose: one vocabulary
#: for a cell in both workspaces.
SHAPES = ('rectangular', 'cubic', 'dodecahedron', 'dodecahedron-hexagon', 'octahedron')
DEFAULT_SHAPE = 'rectangular'


def cell(shape, lengths):
    """The three box vectors for a shape and the rectangular lengths it has to contain.

    A rectangular cell keeps its three independent edges. Every other shape has |a| = |b| = |c| = d, so its one
    number is the minimum image distance: `d = max(lengths)`, the smallest single edge that can hold the rectangular
    requirement the box rules derived. The vectors are the ones GROMACS `editconf` writes for `-bt dodecahedron`,
    `-bt triclinic -angles 60 60 60` and `-bt octahedron`; measured on the installed 2026.3 build.
    """
    if shape not in SHAPES:
        raise ValueError(f'unknown box shape {shape!r}; known: {", ".join(SHAPES)}')
    try:
        values = [float(value) for value in lengths]
    except (TypeError, ValueError) as exc:
        raise ValueError('box extents must be numbers') from exc
    if len(values) != 3:
        raise ValueError('a box needs three extents')
    if any(value <= 0 for value in values):
        raise ValueError('box extents must be positive')
    if shape == DEFAULT_SHAPE:
        vectors = [[values[0], 0.0, 0.0], [0.0, values[1], 0.0], [0.0, 0.0, values[2]]]
        minimum = min(values)
    else:
        d = max(values)
        sqrt2, sqrt3 = math.sqrt(2.0), math.sqrt(3.0)
        if shape == 'cubic':
            vectors = [[d, 0.0, 0.0], [0.0, d, 0.0], [0.0, 0.0, d]]
        elif shape == 'dodecahedron':
            vectors = [[d, 0.0, 0.0], [0.0, d, 0.0], [d / 2.0, d / 2.0, d / sqrt2]]
        elif shape == 'dodecahedron-hexagon':
            vectors = [[d, 0.0, 0.0], [d / 2.0, d * sqrt3 / 2.0, 0.0],
                       [d / 2.0, d / (2.0 * sqrt3), d * math.sqrt(2.0 / 3.0)]]
        else:
            vectors = [[d, 0.0, 0.0], [d / 3.0, 2.0 * sqrt2 * d / 3.0, 0.0],
                       [-d / 3.0, sqrt2 * d / 3.0, d * math.sqrt(2.0 / 3.0)]]
        minimum = d
    return {'shape': shape,
            'vectors': [[round(float(value), 6) for value in vector] for vector in vectors],
            'lengths': [round(math.sqrt(sum(float(value) * float(value) for value in vector)), 6)
                        for vector in vectors],
            'minimum_image_nm': round(float(minimum), 6)}


def _cell(stated, required, axis):
    """A stated dimension, or the derived one when none is stated; smaller than the system needs is widened.

    The stated number is honoured exactly when it can hold the system. A smaller one cannot be: the cell grows to the
    requirement, and the caller compares the stated number with the written box to report the widening (the axis is
    named here so the value has one owner; `axis` is otherwise unused -- the sentence is the caller's).
    """
    del axis  # the widening sentence names the axis where the stated and written boxes are compared
    if stated is None:
        return round(float(required), 6)
    value = float(stated)
    if value <= 0:
        raise ValueError('box extents must be positive')
    return round(max(value, float(required)), 6)


def auto_initial_xy(points, margin_nm=2.0):
    """The x/y a box should have when nobody states one, from the protein's own coordinates.

    The protein's footprint plus `margin_nm` at each face -- exactly what `initial_box` uses when no x or y is stated.
    The extent route publishes it as the belt-less initial box; the panel's own box line and its Auto button read the
    preview instead, because only a placement can measure the belt's radial reach. The value is rounded like its
    neighbours' boxes.
    """
    if not points:
        raise ValueError('a box needs at least one coordinate')
    if margin_nm <= 0:
        raise ValueError('box extents must be positive')
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return [round(max(xs) - min(xs) + 2 * margin_nm, 6),
            round(max(ys) - min(ys) + 2 * margin_nm, 6)]


def initial_box(points, margin_nm=2.0, initial_z_nm=6.0, initial_x_nm=None, initial_y_nm=None):
    """The box a protein is inserted into: its own extent plus the margin in x and y, and a stated z.

    z is its own number rather than a second margin -- the request asks for 20 A in x and y and 60 A in z -- so the
    caller passes it explicitly and GROMACS is given the box rather than asked to derive one.

    A stated x or y is the cell's dimension, and a value below the footprint plus the margin is widened to that
    footprint (a cell that cannot hold the protein is not honoured; the build reports the difference). `None` (the
    panel's blank field) is today's derived value exactly, byte for byte.
    """
    if not points:
        raise ValueError('a box needs at least one coordinate')
    if margin_nm <= 0 or initial_z_nm <= 0:
        raise ValueError('box extents must be positive')
    x, y = auto_initial_xy(points, margin_nm=margin_nm)
    return [_cell(initial_x_nm, x, 'x'), _cell(initial_y_nm, y, 'y'), round(float(initial_z_nm), 6)]


def auto_initial_z(points, half_thickness_nm=None, margin_nm=2.0):
    """The z a box should have when nobody states one, from the protein's own coordinates.

    This is `initial_box`'s and `membrane_box`'s z rule with the stated z replaced by a measurement. Without a
    membrane it is the protein's own z span plus the margin at each face -- the same answer `initial_box` gives when
    that number is passed as `initial_z_nm`. With a membrane it is `membrane_box`'s z, `2 x (max(furthest atom,
    half-thickness) + margin)`: the box is centred on the membrane plane, so the protein already clears it by the
    margin rather than needing a second span's worth of box.

    It measures no belt, so it is the box before the detergents are placed, exactly as `membrane_box`'s default
    states. The panel's Auto button does not read it: Auto writes the preview's own box, belt included. The value is
    rounded like its neighbours' boxes.
    """
    if not points:
        raise ValueError('a box needs at least one coordinate')
    if margin_nm <= 0:
        raise ValueError('box extents must be positive')
    zs = [float(point[2]) for point in points]
    if half_thickness_nm is None:
        return round(max(zs) - min(zs) + 2 * margin_nm, 6)
    furthest = max(abs(z) for z in zs)
    reach = max(furthest, abs(float(half_thickness_nm)))
    return round(2 * (reach + margin_nm), 6)


def extended_box(xy, placed_points, margin_nm=2.0, initial_z_nm=None):
    """The box after placement: z grows so every face is at least `margin_nm` from the placed system.

    `z = 2 x margin + (max_z - min_z)` of the placed coordinates, unless the form states `initial_z_nm`: the
    starting-box z is then the cell's height, and a value below the placed extent is widened to it (the build
    reports the difference). `None` (the panel's blank field) is today's derived z exactly.

    The x and y extents are passed through unchanged from the box the placement was built for: a self-assembly cloud
    is sampled uniformly inside exactly that box (`pdc_placement._self_assemble`), so resizing it afterwards would
    leave the placement describing a different region than the one the detergents came from. A belt is widened by
    `membrane_box` instead, because a belt's density is its torus's own volume and does not depend on the cell around
    it.
    """
    if not placed_points:
        raise ValueError('a box needs at least one placed coordinate')
    if margin_nm <= 0:
        raise ValueError('the box margin must be positive')
    if initial_z_nm is not None and initial_z_nm <= 0:
        raise ValueError('box extents must be positive')
    zs = [float(point[2]) for point in placed_points]
    z = max(zs) - min(zs) + 2 * margin_nm
    return [round(float(xy[0]), 6), round(float(xy[1]), 6), _cell(initial_z_nm, z, 'z')]


def membrane_box(points, half_thickness_nm, margin_nm=2.0, initial_z_nm=None, belt_reach_nm=0.0,
                 belt_radius_nm=0.0, initial_x_nm=None, initial_y_nm=None):
    """The box for a protein that states its own membrane: z clears the protein, the slab *and* the belt.

    `z = 2 x (max(the furthest atom's distance from the membrane plane, the half-thickness, the belt's own reach)
    + margin)`, with the plane as the box's centre -- so the face nearest the furthest thing gets exactly the margin
    and the other face more. The `max` with the half-thickness is what includes a belt that sits inside the slab;
    the belt's own reach is what includes one that does not. Since the 2026-10-14 correction a belt is a **torus**
    whose tube radius is the detergent's own length, so its sites lie the detergent's length either side of the
    membrane centre -- about 2.14 nm for DDM, against a 1.48 nm slab on 1AT9 -- and a z taken from the slab alone
    would cut it in half. `belt_reach_nm` is that reach, which `pdc_build` reads out of the placement's own record;
    the default of zero is a caller with no belt to state, and then today's rule is today's answer exactly.

    Taking the belt's *own* extent instead of a maximum -- what `extended_box` does with the placed centres -- makes
    the margin the belt's, and on a protein whose soluble domain reaches past the belt that is a fraction of the
    margin the run asked for: measured on 1AT9 chain A, a 6.94 nm box against the protein's own 6.033 nm z span,
    0.45 nm per face where 2.0 was asked.

    x and y are the protein's own footprint plus the margin, widened when a belt is present to
    `2 x (max(the protein's half-extent along that axis, belt_radius_nm) + margin)`. `belt_radius_nm` is the belt's
    radial reach -- the band's `radius_max_nm` plus its `detergent_length_nm`, the local surface the heads stand
    off plus the detergent's own length -- which `pdc_build` and the preview read out of the band's own record. The
    default of zero is a caller with no belt to state, and then x and y are `initial_box`'s rule byte for byte.

    A stated `initial_x_nm`/`initial_y_nm` is the cell's dimension, and it must hold the belt's own widening: below
    `max(initial_box's x, 2 x belt_radius_nm + 2 x margin)` it is widened to that requirement rather than cutting the
    belt, and the build reports the difference. `initial_box`'s x already covers the protein's footprint, so an
    accepted number clears both the protein and the belt. `None` is today's derived value exactly.

    Widening x and y after the placement does not change the density the placement was built at. A lattice belt's
    volume is the torus's own, measured from the band's radius and height, and a sphere's is the ball's; the box is
    the cell around that shape, not the volume the shape was sampled in. Self-assembly is never this rule: its
    generator samples inside the initial box and its cell goes through `extended_box` unchanged.

    A stated `initial_z_nm` is the cell's height, and a value below the measured membrane box is widened to it.
    `None` (the panel's blank field) is the measured box exactly.

    A protein that states no membrane passes `half_thickness_nm=None` and gets today's box exactly: there is no frame
    to be centred on and no slab to clear. A protein-free build never reaches this rule at all.
    """
    if half_thickness_nm is None:
        return initial_box(points, margin_nm=margin_nm,
                           initial_z_nm=6.0 if initial_z_nm is None else initial_z_nm,
                           initial_x_nm=initial_x_nm, initial_y_nm=initial_y_nm)
    if not points:
        raise ValueError('a box needs at least one coordinate')
    if margin_nm <= 0 or (initial_z_nm is not None and initial_z_nm <= 0):
        raise ValueError('box extents must be positive')
    initial = initial_box(points, margin_nm=margin_nm,
                          initial_z_nm=6.0 if initial_z_nm is None else initial_z_nm,
                          initial_x_nm=initial_x_nm, initial_y_nm=initial_y_nm)
    furthest = max(abs(float(point[2])) for point in points)
    reach = max(furthest, abs(float(half_thickness_nm)), abs(float(belt_reach_nm or 0.0)))
    radial = abs(float(belt_radius_nm or 0.0))
    # The cell the belt needs, before the reader's own number replaces it: the protein's box or the belt's radial
    # reach, whichever is larger, and the membrane's z.
    required = [max(initial[0], 2 * radial + 2 * margin_nm), max(initial[1], 2 * radial + 2 * margin_nm),
                2 * (reach + margin_nm)]
    return [_cell(initial_x_nm, required[0], 'x'),
            _cell(initial_y_nm, required[1], 'y'),
            _cell(initial_z_nm, required[2], 'z')]


def centre_nm(box):
    """The Cartesian centre of a cell: half the sum of its three vectors, or half the edges of a rectangular one.

    A triclinic cell's centre is not half its edge lengths: the second and third vectors lean, so their half-sum is
    where the system has to be before the wrap folds it into 0..1 in every direction. Rectangular boxes keep their
    historical `[x/2, y/2, z/2]` answer.
    """
    if len(box) == 3 and all(hasattr(value, '__len__') for value in box):
        return [round(sum(float(vector[index]) for vector in box) / 2.0, 6) for index in range(3)]
    return [round(float(box[index]) / 2.0, 6) for index in range(3)]
