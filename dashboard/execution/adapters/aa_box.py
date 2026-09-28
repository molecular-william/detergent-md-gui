"""The box a single-solute atomistic run is solvated in.

The reference protocol this project reproduces puts one carbohydrate in a cube of **fixed edge** -- 2.4 nm --
rather than growing a dodecahedron around whatever it found. A fixed edge is a stronger promise than it looks:
the solute has to fit inside it with solvent to spare, and a box that cannot hold the solute must be **refused**,
because a truncated solute is a different molecule, not a smaller box. One place decides the edge so the command
that makes the box and the check that vets it cannot disagree.
"""
from pathlib import Path

#: The edge of the cube the reference protocol uses, in nanometres.
#:
#: The protocol states a 2.4 nm cube and, in the same breath, the GROMACS-recommended run settings for the force
#: field it used. Those two cannot both hold: CHARMM36's block asks for `rlist = rvdw = rcoulomb = 1.2 nm`, and
#: GROMACS requires the cut-off to be **strictly** less than half the shortest box vector -- half of 2.4 is exactly
#: 1.2, so `grompp` refuses the system outright. The box is raised by one tenth of a nanometre, which is a 13%
#: volume change for a single solute in water, rather than shrinking a force field's published cut-offs, which is a
#: change to the physics. `check_cutoffs` makes the requirement explicit so it cannot be rediscovered as an error.
DEFAULT_EDGE_NM = 2.5


#: The unit cells a run may be solvated in.
#:
#: The dodecahedron was added on the GROMACS manual's recommendation for an approximately spherical solute, and then
#: measured on the real system rather than assumed. It loses: asked for the half-width a cube of the same edge
#: gives -- which is the smallest a dodecahedron may be and still hold this protocol's 1.2 nm cut-off -- it holds
#: **919 waters against the cube's 494** and runs 12% slower (1404 against 1589 ns/day, 500 ps each on this host).
#: A dodecahedron's `-d` and a cube's half-edge are not the same quantity, and at this size there is no room to
#: shrink `-d` far enough to pay for the difference. The shape stays available because the measurement is the
#: reason it exists, but the cube is both the protocol's shape and the faster one here.
SHAPES = ('cubic', 'dodecahedron')
DEFAULT_SHAPE = 'cubic'


def editconf_arguments(box_nm, shape=DEFAULT_SHAPE):
    """The `editconf` arguments that build `box_nm`'s clearance in the requested shape.

    `box_nm` stays the cube's edge, which is the protocol's own currency and what every existing setting means. For
    a dodecahedron the governing length is passed as `-d`, which is the same number's half -- measured, that is the
    *smallest* a dodecahedron may be while still holding the cut-off, and it costs more water than the cube rather
    than less (see SHAPES). The setting exists so the comparison can be made, not because it is the faster option.
    """
    if shape not in SHAPES:
        raise ValueError(f'unknown box shape {shape!r}; known: {", ".join(SHAPES)}')
    if shape == 'cubic':
        return f'-box {box_nm:g} {box_nm:g} {box_nm:g} -c'
    return f'-bt dodecahedron -d {box_nm / 2:g} -c'


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


def check_cutoffs(edge_nm, rlist_nm):
    """Refuse a box whose half-edge cannot contain the neighbour-list cut-off.

    GROMACS requires the cut-off to be strictly shorter than half of the shortest box vector, so a box of exactly
    twice the cut-off fails in `grompp` -- not with a warning about the box, but with an error a reader has to
    interpret. This is the same arithmetic the neighbour list uses, checked where the box is chosen.
    """
    if rlist_nm >= edge_nm / 2:
        raise ValueError(f'a {edge_nm:g} nm box cannot hold a {rlist_nm:g} nm cut-off: the neighbour list has to '
                         f'be shorter than half the box, so the edge has to exceed {rlist_nm * 2:g} nm')
    return edge_nm


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
