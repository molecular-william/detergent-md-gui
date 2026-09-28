"""The box a single-solute atomistic run is solvated in.

The reference protocol this project reproduces puts one carbohydrate in a cube of **fixed edge** -- 2.4 nm --
rather than growing a dodecahedron around whatever it found. A fixed edge is a stronger promise than it looks:
the solute has to fit inside it with solvent to spare, and a box that cannot hold the solute must be **refused**,
because a truncated solute is a different molecule, not a smaller box. One place decides the edge so the command
that makes the box and the check that vets it cannot disagree.
"""
from pathlib import Path

#: The edge of the cube the reference protocol uses, in nanometres.
DEFAULT_EDGE_NM = 2.4


def editconf_arguments(edge_nm):
    """The `editconf` arguments that produce a centred cube of this edge."""
    return f'-box {edge_nm:g} {edge_nm:g} {edge_nm:g} -c'


def read_coordinates(path):
    """An .gro's atom coordinates, from its fixed columns and in its own unit (nanometres).

    Fixed columns rather than whitespace: the format pads fields and a name can carry a digit, so splitting on
    spaces reads the wrong number for some topologies.
    """
    lines = Path(path).read_text().splitlines()
    if len(lines) < 3:
        raise ValueError(f'{path} is not a readable .gro file')
    try:
        count = int(lines[1].split()[0])
    except (IndexError, ValueError) as exc:
        raise ValueError(f'{path} does not declare an atom count') from exc
    body = lines[2:2 + count]
    if len(body) != count:
        raise ValueError(f'{path} declares {count} atoms and holds {len(body)}')
    coordinates = []
    for line in body:
        if len(line) < 44:
            raise ValueError(f'{path} has a truncated atom line: {line!r}')
        coordinates.append([float(line[20:28]), float(line[28:36]), float(line[36:44])])
    return coordinates


def extent_nm(coordinates):
    """The solute's span along each axis: what a box has to be able to hold."""
    if not coordinates:
        raise ValueError('no coordinates to measure')
    return [max(point[axis] for point in coordinates) - min(point[axis] for point in coordinates)
            for axis in range(3)]


def check_fit(name, coordinates, edge_nm):
    """Refuse a cube the solute cannot sit inside with its own periodic images clear of it.

    With the solute centred, the gap to its image is ``edge - extent``, so the images touch once
    ``edge <= 2 * extent``: the solute has to stay inside **half** the edge. That is a geometric requirement
    rather than a preference, and it is checked here rather than assumed because the failure it prevents is
    silent -- a solute bigger than its box is not truncated cleanly, it interacts with itself.
    """
    extent = max(extent_nm(coordinates))
    if extent * 2 > edge_nm:
        raise ValueError(f'{name} spans {extent:.2f} nm, which does not fit a {edge_nm:g} nm cube: a single '
                         f'solute has to stay inside half the edge ({edge_nm / 2:.2f} nm)')
    return extent
