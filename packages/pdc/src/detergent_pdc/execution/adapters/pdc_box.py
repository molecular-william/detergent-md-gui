"""The box rules: what the protein's own extent becomes before and after the detergent arrives.

The rules are pure functions of coordinates, because the protocol's box arithmetic is the part most worth checking
without GROMACS and the easiest part to get quietly wrong: an off-by-a-margin box either lets the protein touch a
periodic image or silently changes the density a placement was built for.

`initial_box` is the box a protein is inserted into, `extended_box` the one it gets once the detergents are placed,
`membrane_box` the one a protein that states its own membrane gets: centred on that membrane's plane, with z
clearing the protein and the belt, and x/y widened to the belt's radial reach. `auto_initial_z`/`auto_initial_xy`
are the numbers those insertion rules measure when the caller states none, which is what the form's Auto button asks
for.

A stated initial x, y or z is **exact**: the cell the build writes is the number the reader asked for, and a number
that cannot hold the protein (or, in `membrane_box`, the belt) is refused with both numbers rather than widened
silently. A blank axis is the derived value exactly, never zero. The refusal is what keeps an exact cell from putting a
face through the system it is meant to contain; before 2026-11-24 a stated value was a floor instead.

The density a placement was built at is its shape's, not its cell's: a lattice belt's volume is the torus's own
(measured from the band, not from the box), a sphere's is the ball's, so widening the box after the placement
leaves the recorded density where it was. Self-assembly is the one generator that samples inside the box it is
given, so its box is the placement's own and this module does not widen it.
"""


#: How far a stated dimension may sit below the derived one and still count as equal, covering the rounding both
#: sides apply (six places) without accepting a box that genuinely cuts the system.
TOLERANCE_NM = 1e-6


def _exact(stated, required, axis):
    """A stated dimension, or the derived one when none is stated; below what the system needs is a refusal.

    The message carries both numbers so a reader can type the smaller one and see why, and names the axis because the
    form has three of them.
    """
    if stated is None:
        return round(float(required), 6)
    value = float(stated)
    if value <= 0:
        raise ValueError('box extents must be positive')
    if value + TOLERANCE_NM < float(required):
        raise ValueError(f'the stated {axis} box ({value:g} nm) is smaller than this system needs '
                         f'({round(float(required), 6):g} nm)')
    return round(value, 6)


def auto_initial_xy(points, margin_nm=2.0):
    """The x/y a box should have when nobody states one, from the protein's own coordinates.

    The protein's footprint plus `margin_nm` at each face -- exactly what `initial_box` uses when no x or y is stated.
    The form's Auto button fills these numbers, and the panel shows them as the derived value while its x/y fields are
    blank; a blank field posts nothing, so the run derives the same number the panel displayed. The value is rounded
    like its neighbours' boxes.
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

    A stated x or y is **exact**, and a value below the footprint plus the margin is refused rather than widened:
    the reader asked for that cell, and a cell that cannot hold the protein is a mistake to correct, not to hide.
    `None` (the panel's blank field) is today's derived value exactly, byte for byte.
    """
    if not points:
        raise ValueError('a box needs at least one coordinate')
    if margin_nm <= 0 or initial_z_nm <= 0:
        raise ValueError('box extents must be positive')
    x, y = auto_initial_xy(points, margin_nm=margin_nm)
    return [_exact(initial_x_nm, x, 'x'), _exact(initial_y_nm, y, 'y'), round(float(initial_z_nm), 6)]


def auto_initial_z(points, half_thickness_nm=None, margin_nm=2.0):
    """The z a box should have when nobody states one, from the protein's own coordinates.

    This is `initial_box`'s and `membrane_box`'s z rule with the stated z replaced by a measurement, which is what the
    form's Auto button asks for. Without a membrane it is the protein's own z span plus the margin at each face -- the
    same answer `initial_box` gives when that number is passed as `initial_z_nm`. With a membrane it is
    `membrane_box`'s z, `2 x (max(furthest atom, half-thickness) + margin)`: the box is centred on the membrane plane,
    so the protein already clears it by the margin rather than needing a second span's worth of box.

    A caller that wants no belt in the measurement passes no `belt_reach_nm`; this is the box before the detergents
    are placed, exactly as `membrane_box`'s default states. The value is rounded like its neighbours' boxes.
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
    starting-box z is then the cell's exact height, and a value below the placed extent is refused rather than
    quietly widened. `None` (the panel's blank field) is today's derived z exactly.

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
    return [round(float(xy[0]), 6), round(float(xy[1]), 6), _exact(initial_z_nm, z, 'z')]


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

    A stated `initial_x_nm`/`initial_y_nm` is the cell's **exact** dimension, and it must hold the belt's own
    widening: below `max(initial_box's x, 2 x belt_radius_nm + 2 x margin)` it is refused with both numbers.
    `initial_box`'s x already refuses a value below the protein's footprint, so an accepted number clears both the
    protein and the belt. `None` is today's derived value exactly.

    Widening x and y after the placement does not change the density the placement was built at. A lattice belt's
    volume is the torus's own, measured from the band's radius and height, and a sphere's is the ball's; the box is
    the cell around that shape, not the volume the shape was sampled in. Self-assembly is never this rule: its
    generator samples inside the initial box and its cell goes through `extended_box` unchanged.

    A stated `initial_z_nm` is the cell's **exact** height, and a value below the measured membrane box is
    refused rather than widened. `None` (the panel's blank field) is the measured box exactly.

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
    return [_exact(initial_x_nm, required[0], 'x'),
            _exact(initial_y_nm, required[1], 'y'),
            _exact(initial_z_nm, required[2], 'z')]
