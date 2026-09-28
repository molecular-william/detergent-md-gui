"""The box rules: what the protein's own extent becomes before and after the detergent arrives.

Both are pure functions of coordinates, because the protocol's box arithmetic is the part most worth checking
without GROMACS and the easiest part to get quietly wrong: an off-by-a-margin box either lets the protein touch a
periodic image or silently changes the density a placement was built for.
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
