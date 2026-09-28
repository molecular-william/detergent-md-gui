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


def test_the_default_edge_is_the_protocols():
    assert aa_box.DEFAULT_EDGE_NM == 2.4


def test_the_command_is_a_centred_cube_of_the_requested_edge():
    assert aa_box.editconf_arguments(2.4) == '-box 2.4 2.4 2.4 -c'
    assert aa_box.editconf_arguments(3) == '-box 3 3 3 -c'


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
