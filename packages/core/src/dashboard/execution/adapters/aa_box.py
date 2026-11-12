"""The box a single-solute atomistic run is solvated in.

The reference protocol this project reproduces puts one carbohydrate in a box of **fixed size** rather than growing
a box around whatever it found. A fixed size is a stronger promise than it looks: the solute has to fit inside it
with solvent to spare, and a box that cannot hold the solute must be **refused**, because a truncated solute is a
different molecule, not a smaller box. One number decides the box -- its minimum image distance d -- for every shape,
so the command that makes the box and the check that vets it cannot disagree.
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


#: The unit cells a run may be solvated in, all sized by the same minimum image distance d (`box_nm`).
#:
#: Every shape below has |a| = |b| = |c| = d, so the run's one number is the quantity the cut-off rule is stated in
#: (`Rc < d/2`) and the shape is a choice of how much else the cell encloses. `editconf` is asked for the image
#: distance it accepts for a named cell (`-box d`); the rhombic dodecahedron's xy-hexagon form has no `-bt` name and
#: is the triclinic cell with the manual's 60-degree angles. Volumes from the GROMACS manual's "Some useful box types"
#: table: cube d^3, both rhombic dodecahedra (sqrt(2)/2) d^3 = 0.707 d^3, truncated octahedron (4 sqrt(3)/9) d^3 =
#: 0.770 d^3 -- the non-cubic cells are the same image distance with less solvent, which is the reason to offer them.
SHAPES = ('cubic', 'dodecahedron', 'dodecahedron-hexagon', 'octahedron')
DEFAULT_SHAPE = 'cubic'


def editconf_arguments(box_nm, shape=DEFAULT_SHAPE):
    """The `editconf` arguments that build the cell whose minimum image distance is `box_nm`.

    `box_nm` is the minimum image distance for every shape, so all four cells have |a| = |b| = |c| = d and the same
    cut-off arithmetic applies to each. `-box` takes the image distance for a named cell; the xy-hexagon rhombic
    dodecahedron is written as the triclinic cell the manual's table names, because `editconf` has no `-bt` name for
    it. Numbers are spelled with `:g`, so 2.5 stays "2.5" and 3 is "3".
    """
    if shape not in SHAPES:
        raise ValueError(f'unknown box shape {shape!r}; known: {", ".join(SHAPES)}')
    if shape == 'cubic':
        return f'-box {box_nm:g} {box_nm:g} {box_nm:g} -c'
    if shape == 'dodecahedron':
        return f'-bt dodecahedron -box {box_nm:g} -c'
    if shape == 'dodecahedron-hexagon':
        return f'-bt triclinic -box {box_nm:g} {box_nm:g} {box_nm:g} -angles 60 60 60 -c'
    return f'-bt octahedron -box {box_nm:g} -c'


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
    """Refuse a box the solute cannot sit inside with its own periodic images clear of it.

    With the solute centred, the gap to its image is ``edge - extent``, so the images touch once
    ``edge <= 2 * extent``: the solute has to stay inside **half** the edge. That is a geometric requirement
    rather than a preference, and it is checked here rather than assumed because the failure it prevents is
    silent -- a solute bigger than its box is not truncated cleanly, it interacts with itself.

    Conservative for the tilted cells: the rule is the cube's, where the nearest image lies straight along an axis
    and half the edge is the clearance. A dodecahedron's or truncated octahedron's nearest image lies along a diagonal
    of the cell, where the solute is narrower, so a solute this rule refuses may still fit; it never accepts one that
    would not. Keeping one rule for all four makes the refusal the same sentence whatever shape is chosen.
    """
    extent = max(extent_nm(coordinates))
    if extent * 2 > edge_nm:
        raise ValueError(f'{name} spans {extent:.2f} nm, which does not fit a {edge_nm:g} nm cube: a single '
                         f'solute has to stay inside half the edge ({edge_nm / 2:.2f} nm)')
    return extent
