"""The box rules: what the protein's own extent becomes before and after the detergent arrives.

The rules are pure functions of coordinates, because the protocol's box arithmetic is the part most worth checking
without GROMACS and the easiest part to get quietly wrong: an off-by-a-margin box either lets the protein touch a
periodic image or silently changes the density a placement was built for.

`initial_box` is the box a protein is inserted into, `extended_box` the one it gets once the detergents are placed,
and `membrane_box` the one a protein that states its own membrane gets: centred on that membrane's plane, with z
clearing the protein rather than the belt the placement put inside the slab.
"""


def initial_box(points, margin_nm=2.0, initial_z_nm=6.0):
    """The box a protein is inserted into: its own extent plus the margin in x and y, and a stated z.

    z is its own number rather than a second margin -- the request asks for 20 A in x and y and 60 A in z -- so the
    caller passes it explicitly and GROMACS is given the box rather than asked to derive one.
    """
    if not points:
        raise ValueError('a box needs at least one coordinate')
    if margin_nm <= 0 or initial_z_nm <= 0:
        raise ValueError('box extents must be positive')
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return [round(max(xs) - min(xs) + 2 * margin_nm, 6),
            round(max(ys) - min(ys) + 2 * margin_nm, 6),
            round(float(initial_z_nm), 6)]


def extended_box(xy, placed_points, margin_nm=2.0):
    """The box after placement: z grows so every face is at least `margin_nm` from the placed system.

    `z = 2 x margin + (max_z - min_z)` of the placed coordinates. The x and y extents are passed through unchanged
    from the box the placement was built for, because widening them would change the volume the detergents were
    placed into and quietly alter the density the build was designed at.
    """
    if not placed_points:
        raise ValueError('a box needs at least one placed coordinate')
    if margin_nm <= 0:
        raise ValueError('the box margin must be positive')
    zs = [float(point[2]) for point in placed_points]
    return [round(float(xy[0]), 6), round(float(xy[1]), 6), round(max(zs) - min(zs) + 2 * margin_nm, 6)]


def membrane_box(points, half_thickness_nm, margin_nm=2.0, initial_z_nm=6.0, belt_reach_nm=0.0):
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

    x and y are `initial_box`'s rule -- the protein's own footprint plus the margin -- because widening them beyond
    the box the placement was built for would change the volume the detergents were placed into and quietly alter
    the density the build was designed at.

    A protein that states no membrane passes `half_thickness_nm=None` and gets today's box exactly: there is no frame
    to be centred on and no slab to clear. A protein-free build never reaches this rule at all.
    """
    if half_thickness_nm is None:
        return initial_box(points, margin_nm=margin_nm, initial_z_nm=initial_z_nm)
    if not points:
        raise ValueError('a box needs at least one coordinate')
    if margin_nm <= 0:
        raise ValueError('box extents must be positive')
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    furthest = max(abs(float(point[2])) for point in points)
    reach = max(furthest, abs(float(half_thickness_nm)), abs(float(belt_reach_nm or 0.0)))
    return [round(max(xs) - min(xs) + 2 * margin_nm, 6),
            round(max(ys) - min(ys) + 2 * margin_nm, 6),
            round(2 * (reach + margin_nm), 6)]
