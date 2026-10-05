"""The membrane frame: where the bilayer is, which way it faces, and what that means for a belt.

This is the first definition of a belt in this repository. The closest thing before it was a band measured from a
protein's own centroid, with a half-thickness no input set -- which on the OPM structure that motivated the work put
361 of 1,158 atoms on the wrong side of the line.
"""
import pytest

from micelle import frame as frame_module


def _frame(half_thickness_nm=1.18, axis=(0.0, 0.0, 1.0)):
    return frame_module.frame_from_structure(half_thickness_nm, axis=axis, source="1qj8's own REMARK")


def test_the_belt_is_the_atoms_the_frame_puts_inside_its_slab():
    belt = frame_module.belt_mask([[0.0, 0.0, 0.0], [0.0, 0.0, 1.5], [0.0, 0.0, -3.0]], _frame())
    assert belt == [True, False, False]


def test_the_axis_is_projected_onto_rather_than_assumed_to_be_z():
    """A frame can face any way; a reader that indexed z would put every atom of a y-facing bilayer outside it."""
    belt = frame_module.belt_mask([[0.0, 0.0, 0.0], [0.0, 1.5, 0.0]], _frame(axis=(0.0, 1.0, 0.0)))
    assert belt == [True, False]


def test_the_belt_does_not_move_with_the_proteins_own_centre():
    """The point of the whole exercise: a protein whose atoms sit mostly to one side still has its belt at the plane."""
    atoms = [[0.0, 0.0, -1.0], [0.0, 0.0, 1.0], [0.0, 0.0, 4.0]]          # atom-mean z is +1.33, off the plane
    assert frame_module.belt_mask(atoms, _frame()) == [True, True, False]


def test_a_frame_states_its_planes_and_where_its_numbers_came_from():
    built = _frame()
    assert built.axis == (0.0, 0.0, 1.0)
    assert (built.plane_low_nm, built.plane_high_nm) == (-1.18, 1.18)
    assert built.half_thickness_nm == 1.18 and built.centre_nm == 0.0
    assert built.source == "1qj8's own REMARK"


def test_an_unstated_half_thickness_is_an_error_rather_than_a_default():
    """A guessed thickness is indistinguishable from a measured one once it is in a manifest -- which is how 1.0 nm
    came to be used on a structure that states 1.18."""
    with pytest.raises(ValueError, match='half-thickness'):
        frame_module.frame_from_structure(None)


def test_the_belt_points_are_the_atoms_themselves_so_a_footprint_can_be_measured():
    atoms = [[1.0, 2.0, 0.0], [3.0, 4.0, 9.0]]
    assert frame_module.belt_points(atoms, _frame()) == [[1.0, 2.0, 0.0]]


def test_the_axis_is_normalised_so_an_unscaled_vector_still_measures_nanometres():
    assert frame_module.belt_mask([[0.0, 0.0, 1.0]], _frame(axis=(0.0, 0.0, 7.0))) == [True]


def test_a_frame_with_no_direction_is_refused_rather_than_assumed():
    with pytest.raises(ValueError, match='direction'):
        frame_module.frame_from_structure(1.18, axis=(0.0, 0.0, 0.0))
