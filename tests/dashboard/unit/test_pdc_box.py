"""The box arithmetic the protocol was agreed with, checked as arithmetic.

The requests were 20 A of margin in x and y, a 60 A starting box in z, and then a z extension so that every face
ends up at least 20 A from the system. Those are claims about numbers, so they are tested as numbers rather than
through a run.
"""
import pytest

from dashboard.execution.adapters import pdc_box


def test_the_initial_box_uses_a_two_nanometre_margin_in_x_and_y_and_the_stated_z():
    box = pdc_box.initial_box([[0, 0, 0], [4.0, 2.0, 1.0]], margin_nm=2.0, initial_z_nm=6.0)
    assert box == [8.0, 6.0, 6.0]          # extent + 2 x margin, and z exactly as asked


def test_the_initial_box_keeps_a_protein_that_is_not_at_the_origin_centred_by_extent():
    """Extent, not coordinates: a protein whose corner is at the origin and one offset by 100 nm give the same box."""
    assert pdc_box.initial_box([[100.0, 100.0, 100.0], [104.0, 102.0, 101.0]]) == [8.0, 6.0, 6.0]


def test_the_box_is_extended_in_z_so_every_face_is_two_nanometres_away():
    box = pdc_box.extended_box([8.0, 6.0], [[-1.0, -1.0, -0.5], [1.0, 1.0, 2.5]], margin_nm=2.0)
    assert box[2] == 2.0 * 2.0 + 3.0        # max_z - min_z + 2 x margin
    assert box[:2] == [8.0, 6.0]            # x and y pass through: widening them would change the density


def test_a_box_rule_refuses_input_it_cannot_compute():
    with pytest.raises(ValueError, match='at least one coordinate'):
        pdc_box.initial_box([])
    with pytest.raises(ValueError, match='positive'):
        pdc_box.initial_box([[0, 0, 0]], margin_nm=0)
    with pytest.raises(ValueError, match='at least one placed'):
        pdc_box.extended_box([8.0, 6.0], [])


def test_the_membrane_box_makes_z_clear_the_protein_rather_than_the_belt():
    """Phase C1: an asymmetric protein in a 1.18 nm slab.

    The belt's own span (a band inside the slab) is thinner than the protein, so a z taken from the placed centres
    leaves the protein a fraction of the margin: the defect this rule replaces.
    """
    points = [[0.0, 0.0, -2.26], [0.0, 0.0, 3.80]]
    box = pdc_box.membrane_box(points, half_thickness_nm=1.18, margin_nm=2.0)

    assert box[2] == 2 * (3.80 + 2.0), 'the furthest atom from the plane sets it, not the placed centres'
    assert box[:2] == [4.0, 4.0], 'x and y are the protein footprint plus the margin, as `initial_box` makes them'


def test_a_membrane_box_reaches_at_least_the_slab_it_is_centred_on():
    """A protein that barely enters the bilayer still gets a box the whole slab fits in: the belt lives inside it."""
    box = pdc_box.membrane_box([[0.0, 0.0, -0.2], [0.0, 0.0, 0.2]], half_thickness_nm=1.48, margin_nm=2.0)

    assert box[2] == 2 * (1.48 + 2.0)


def test_a_protein_that_states_no_membrane_keeps_todays_box_exactly():
    assert pdc_box.membrane_box([[0.0, 0.0, 0.0], [4.0, 2.0, 1.0]], half_thickness_nm=None) == [8.0, 6.0, 6.0]

