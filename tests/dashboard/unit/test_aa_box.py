"""The cube box: its arithmetic, the command that makes it, and the fit check that refuses rather than truncates.

A box that is too small is not a smaller experiment, it is a different one -- the solute interacts with its own
periodic images -- so the rule is worth pinning as arithmetic rather than inspecting an mdrun log later.
"""
import pytest
from dashboard.execution.adapters import aa_box


def gro(tmp_path, points, name='molecule.gro', count=None, truncate=None):
    """A .gro in the documented fixed columns, so the reader is tested against the format rather than a guess."""
    lines = ['PDC system']
    declared = len(points) if count is None else count
    lines.append(f'{declared:5d}' if isinstance(declared, int) else str(declared))
    for index, point in enumerate(points, 1):
        line = (f'{index:5d}{"LIG":<5}{"C1":>5}{index:5d}'
                + ''.join(f'{value:8.3f}' for value in point))
        lines.append(line[:truncate] if truncate else line)
    lines.append('  10.00000  10.00000  10.00000')
    path = tmp_path / name
    path.write_text('\n'.join(lines) + '\n')
    return path


def test_the_default_edge_is_the_smallest_cube_the_cutoff_allows():
    """The protocol says 2.4 nm and the force field's cut-offs need more than that.

    CHARMM36's block asks for a 1.2 nm neighbour list, which has to be strictly inside half the box: half of 2.4
    is exactly 1.2, so the protocol's own box cannot hold the protocol's own run settings. The default is the
    smallest cube that can.
    """
    assert aa_box.DEFAULT_EDGE_NM == 2.5
    aa_box.check_cutoffs(aa_box.DEFAULT_EDGE_NM, 1.2)


def test_the_command_is_a_centred_cube_of_the_requested_edge():
    assert aa_box.editconf_arguments(2.4) == '-box 2.4 2.4 2.4 -c'
    assert aa_box.editconf_arguments(3) == '-box 3 3 3 -c'


def test_the_dodecahedron_is_asked_for_the_same_governing_half_width():
    """One number, two shapes: `-d` is the half-width a cube gets from its edge, and both hold the same cut-off.

    Measured, that is the *smallest* a dodecahedron may be with this protocol's cut-off -- and it still costs more
    water than the cube (919 against 494) and runs slower. The test pins the equivalence the setting claims, not a
    performance promise: the two commands differ only in the shape they ask for.
    """
    assert aa_box.editconf_arguments(2.5, 'dodecahedron') == '-bt dodecahedron -d 1.25 -c'
    assert aa_box.DEFAULT_SHAPE == 'cubic'


def test_an_unknown_box_shape_is_refused_rather_than_defaulted():
    with pytest.raises(ValueError, match='unknown box shape'):
        aa_box.editconf_arguments(2.5, 'octahedron')


def test_the_extent_is_the_span_along_each_axis():
    assert aa_box.extent_nm([[0.0, 0.0, 0.0], [1.0, 2.0, 0.5]]) == [1.0, 2.0, 0.5]


def test_a_gro_is_read_in_its_fixed_columns(tmp_path):
    path = gro(tmp_path, [[1.25, 2.5, 3.75], [2.25, 2.5, 3.75]])
    assert aa_box.read_coordinates(path) == [[1.25, 2.5, 3.75], [2.25, 2.5, 3.75]]


def test_a_gro_that_declares_more_atoms_than_it_holds_is_refused(tmp_path):
    path = gro(tmp_path, [[0.0, 0.0, 0.0]], count=4)
    with pytest.raises(ValueError, match='declares 4 atoms'):
        aa_box.read_coordinates(path)


def test_a_gro_with_a_truncated_atom_line_is_refused(tmp_path):
    path = gro(tmp_path, [[0.0, 0.0, 0.0]], truncate=30)
    with pytest.raises(ValueError, match='truncated atom line'):
        aa_box.read_coordinates(path)


def test_a_solute_inside_half_the_edge_is_accepted():
    assert aa_box.check_fit('sucrose', [[0.0, 0.0, 0.0], [1.0, 0.5, 0.4]], 2.4) == 1.0


def test_a_solute_wider_than_half_the_edge_is_refused():
    with pytest.raises(ValueError, match='does not fit a 2.4 nm cube'):
        aa_box.check_fit('too big', [[0.0, 0.0, 0.0], [1.3, 0.0, 0.0]], 2.4)


def test_exactly_half_the_edge_is_accepted_because_the_images_stay_clear():
    """At exactly half, the nearest image is a whole solute-span away, so nothing interacts with itself.

    The refusal begins when the solute is *wider* than half the edge, not at it: the requirement being protected
    is the absence of self-interaction, and at the boundary that still holds.
    """
    assert aa_box.check_fit('boundary', [[0.0, 0.0, 0.0], [1.2, 0.0, 0.0]], 2.4) == 1.2


def test_a_larger_box_admits_the_solute_that_the_default_refused():
    assert aa_box.check_fit('wider', [[0.0, 0.0, 0.0], [1.3, 0.0, 0.0]], 3.0) == 1.3


def test_a_box_of_exactly_twice_the_cutoff_is_refused():
    """The failure that started this: a 2.4 nm cube with CHARMM36's 1.2 nm cut-off, refused by grompp."""
    with pytest.raises(ValueError, match='cannot hold a 1.2 nm cut-off'):
        aa_box.check_cutoffs(2.4, 1.2)


def test_a_longer_cutoff_needs_a_proportionally_longer_edge():
    with pytest.raises(ValueError, match='edge has to exceed 2.6 nm'):
        aa_box.check_cutoffs(2.5, 1.3)


def test_a_cutoff_comfortably_inside_the_box_is_accepted():
    assert aa_box.check_cutoffs(2.5, 1.0) == 2.5
