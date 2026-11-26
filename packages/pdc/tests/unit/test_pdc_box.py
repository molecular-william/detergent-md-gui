"""The box arithmetic the protocol was agreed with, checked as arithmetic.

The requests were 20 A of margin in x and y, a 60 A starting box in z, and then a z extension so that every face
ends up at least 20 A from the system. Those are claims about numbers, so they are tested as numbers rather than
through a run.
"""
import numpy as np
import pytest
from detergent_pdc.execution.adapters import pdc_box


def test_a_stated_initial_x_and_y_are_the_cells_dimension_and_a_smaller_one_is_widened():
    """A stated box dimension is what the run writes when it can hold the system; below that it is widened to fit.

    The footprint is 4 x 2 nm, so with a 2 nm margin the derived box is 8 x 6. A stated 1 nm cannot hold the
    protein, so the cell is that derived 8 x 6 (the build reports the widening); a stated 10 x 12 is the caller's
    cell exactly, and the derived 8 x 6 is accepted as itself. The same call with no x/y is today's derived box.
    """
    points = [[0.0, 0.0, 0.0], [4.0, 2.0, 1.0]]

    assert pdc_box.initial_box(points, margin_nm=2.0, initial_z_nm=6.0) == [8.0, 6.0, 6.0]
    assert pdc_box.initial_box(points, margin_nm=2.0, initial_z_nm=6.0, initial_x_nm=1.0,
                               initial_y_nm=1.0) == [8.0, 6.0, 6.0]
    assert pdc_box.initial_box(points, margin_nm=2.0, initial_z_nm=6.0, initial_x_nm=10.0,
                               initial_y_nm=12.0) == [10.0, 12.0, 6.0]
    assert pdc_box.initial_box(points, margin_nm=2.0, initial_z_nm=6.0, initial_x_nm=8.0,
                               initial_y_nm=6.0) == [8.0, 6.0, 6.0], 'the derived number is accepted as itself'


def test_a_stated_initial_x_or_y_that_is_not_a_positive_dimension_is_refused():
    with pytest.raises(ValueError, match='positive'):
        pdc_box.initial_box([[0.0, 0.0, 0.0]], initial_x_nm=0.0)
    with pytest.raises(ValueError, match='positive'):
        pdc_box.initial_box([[0.0, 0.0, 0.0]], initial_y_nm=-1.0)


def test_a_stated_xy_in_a_membrane_box_must_hold_the_belts_radial_reach():
    """The stated cell is used when it contains what the belt needs; below that the belt's reach wins.

    The footprint is 4 x 2 nm and the margin 2 nm; a 3 nm belt radius reaches 2 x 3 + 2 x 2 = 10 nm, so a stated
    9 nm cannot hold the belt and the box is that 10 nm, while a stated 12/13 is the caller's cell exactly.
    """
    points = [[0.0, 0.0, -0.2], [4.0, 2.0, 0.2]]
    derived = pdc_box.membrane_box(points, half_thickness_nm=1.48, margin_nm=2.0, belt_radius_nm=3.0)

    assert derived[:2] == [10.0, 10.0]
    assert pdc_box.membrane_box(points, half_thickness_nm=1.48, margin_nm=2.0, belt_radius_nm=3.0,
                                initial_x_nm=9.0, initial_y_nm=9.0)[:2] == [10.0, 10.0]
    assert pdc_box.membrane_box(points, half_thickness_nm=1.48, margin_nm=2.0, belt_radius_nm=3.0,
                                initial_x_nm=12.0, initial_y_nm=13.0)[:2] == [12.0, 13.0]


def test_a_protein_that_states_no_membrane_passes_its_stated_xy_to_the_initial_box():
    points = [[0.0, 0.0, 0.0], [4.0, 2.0, 1.0]]
    assert pdc_box.membrane_box(points, half_thickness_nm=None, initial_x_nm=10.0, initial_y_nm=7.0) == \
        pdc_box.initial_box(points, initial_x_nm=10.0, initial_y_nm=7.0) == [10.0, 7.0, 6.0]
    assert pdc_box.membrane_box(points, half_thickness_nm=None, initial_x_nm=10.0, initial_y_nm=1.0) == \
        [10.0, 6.0, 6.0], 'a stated y below the footprint is widened to it'


def test_auto_initial_xy_is_the_derived_footprint_and_agrees_with_initial_box():
    """The panel's placeholder/derived x/y is the same measurement `initial_box` makes when nothing is stated."""
    points = [[0.0, 0.0, 0.0], [4.0, 2.0, 1.0]]

    assert pdc_box.auto_initial_xy(points, margin_nm=2.0) == [8.0, 6.0]
    assert pdc_box.auto_initial_xy(points, margin_nm=2.0) == pdc_box.initial_box(points)[:2]
    with pytest.raises(ValueError, match='positive'):
        pdc_box.auto_initial_xy(points, margin_nm=0)


def test_the_initial_box_uses_a_two_nanometre_margin_in_x_and_y_and_the_stated_z():
    box = pdc_box.initial_box([[0, 0, 0], [4.0, 2.0, 1.0]], margin_nm=2.0, initial_z_nm=6.0)
    assert box == [8.0, 6.0, 6.0]          # extent + 2 x margin, and z exactly as asked


def test_the_initial_box_keeps_a_protein_that_is_not_at_the_origin_centred_by_extent():
    """Extent, not coordinates: a protein whose corner is at the origin and one offset by 100 nm give the same box."""
    assert pdc_box.initial_box([[100.0, 100.0, 100.0], [104.0, 102.0, 101.0]]) == [8.0, 6.0, 6.0]


def test_the_box_is_extended_in_z_so_every_face_is_two_nanometres_away():
    box = pdc_box.extended_box([8.0, 6.0], [[-1.0, -1.0, -0.5], [1.0, 1.0, 2.5]], margin_nm=2.0)
    assert box[2] == 2.0 * 2.0 + 3.0        # max_z - min_z + 2 x margin
    assert box[:2] == [8.0, 6.0]            # x and y pass through: this box is the placement's own cell


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


def test_a_membrane_box_contains_a_belt_that_reaches_past_the_slab():
    """The user's correction, in the box's own arithmetic: the belt reaches the detergent length either side.

    Measured on 1AT9: the slab is 1.48 nm and the belt's own extent is now the detergent's length (about 2.14 nm
    for DDM), so a z taken from the slab alone would cut the belt in half. The caller states the belt's reach and
    the box clears whichever of the three is furthest from the plane.
    """
    points = [[0.0, 0.0, -0.2], [0.0, 0.0, 0.2]]
    without = pdc_box.membrane_box(points, half_thickness_nm=1.48, margin_nm=2.0)
    with_belt = pdc_box.membrane_box(points, half_thickness_nm=1.48, margin_nm=2.0, belt_reach_nm=2.1431)

    assert without[2] == 2 * (1.48 + 2.0), 'no belt stated: the slab still sets the box'
    assert with_belt[2] == pytest.approx(2 * (2.1431 + 2.0)), "the belt's own reach sets it, and the slab is inside it"
    assert with_belt[:2] == without[:2], \
        "the belt's z reach does not touch x/y; its radial reach is the separate `belt_radius_nm` below"


def test_the_membrane_box_widens_x_and_y_to_the_belts_radial_reach():
    """The plan's item 2, measured on 1AT9 chain A: the belt's surface plus the detergent's length, then the margin.

    The inputs are the build's own measurement of the deposited structure (``1at9.pdb``, chain A, coarse-grained):
    a 4.3517 x 2.7817 nm footprint, the furthest bead 3.5402 nm from the membrane plane, a 1.48 nm slab, and -- at
    AN=40, where the placement is accepted -- a band whose furthest local surface is 2.346713 nm and whose DDM is
    2.143089 nm long. The old rule answered 8.3517 x 6.7817 x 11.0804 nm; the belt's radial reach (4.489802 nm)
    plus the margin gives x and y 12.979604 nm each, and z is unchanged. The band's density (0.246926 nm^-3) is
    the torus's own, so widening the cell after placement leaves it where the placement measured it.
    """
    points = [[0.0, 0.0, -3.5402], [4.3517, 2.7817, 3.5402]]
    old = pdc_box.membrane_box(points, half_thickness_nm=1.48, margin_nm=2.0,
                               belt_reach_nm=2.813206)
    new = pdc_box.membrane_box(points, half_thickness_nm=1.48, margin_nm=2.0,
                               belt_reach_nm=2.813206, belt_radius_nm=2.346713 + 2.143089)

    assert old == [8.3517, 6.7817, 11.0804], 'the rule before item 2'
    assert new == [12.979604, 12.979604, 11.0804], 'x and y clear the belt, z still clears the furthest bead'


def test_a_stated_initial_z_is_the_cell_height_and_a_smaller_one_is_widened():
    """The form's starting-box z is the cell height, like x and y: stated when it fits, widened when it would cut."""
    placed = [[0.0, 0.0, 0.0], [0.0, 0.0, 4.0]]
    assert pdc_box.extended_box([10.0, 8.0], placed, margin_nm=2.0)[2] == 8.0
    assert pdc_box.extended_box([10.0, 8.0], placed, margin_nm=2.0, initial_z_nm=12.0)[2] == 12.0
    assert pdc_box.extended_box([10.0, 8.0], placed, margin_nm=2.0, initial_z_nm=4.0)[2] == 8.0

    points = [[0.0, 0.0, -3.5402], [4.3517, 2.7817, 3.5402]]
    assert pdc_box.membrane_box(points, half_thickness_nm=1.48, margin_nm=2.0)[2] == 11.0804
    assert pdc_box.membrane_box(points, half_thickness_nm=1.48, margin_nm=2.0, initial_z_nm=12.0)[2] == 12.0
    assert pdc_box.membrane_box(points, half_thickness_nm=1.48, margin_nm=2.0, initial_z_nm=8.0)[2] == 11.0804


def test_a_belt_reach_inside_the_proteins_own_footprint_does_not_shrink_the_box():
    """The widened x/y is a maximum: a belt that sits inside the footprint keeps the footprint's own box."""
    points = [[0.0, 0.0, -0.2], [4.0, 2.0, 0.2]]

    assert pdc_box.membrane_box(points, half_thickness_nm=1.48, margin_nm=2.0, belt_radius_nm=1.0) \
        == pdc_box.membrane_box(points, half_thickness_nm=1.48, margin_nm=2.0) == [8.0, 6.0, 6.96]


def test_a_belt_inside_the_slab_does_not_shrink_a_membrane_box():
    """A reach shorter than the slab or the protein changes nothing: the box is a maximum, not a replacement."""
    points = [[0.0, 0.0, -3.0], [0.0, 0.0, 3.4]]

    assert pdc_box.membrane_box(points, half_thickness_nm=1.48, margin_nm=2.0, belt_reach_nm=1.0)[2] \
        == 2 * (3.4 + 2.0)


def test_a_protein_that_states_no_membrane_keeps_todays_box_exactly():
    points = [[0.0, 0.0, 0.0], [4.0, 2.0, 1.0]]
    assert pdc_box.membrane_box(points, half_thickness_nm=None) == [8.0, 6.0, 6.0]
    assert pdc_box.membrane_box(points, half_thickness_nm=None, belt_reach_nm=9.0, belt_radius_nm=9.0) == [8.0, 6.0, 6.0], \
        'no frame means no belt: the belt arguments cannot reach a box that is `initial_box` exactly'


def test_auto_initial_z_without_a_membrane_is_the_points_own_z_span_plus_the_margins():
    """The Auto button's answer is the rule `initial_box` would apply when that number is passed as its z."""
    points = [[0.0, 0.0, -1.0], [0.0, 0.0, 3.5]]
    assert pdc_box.auto_initial_z(points, margin_nm=2.0) == 4.5 + 2 * 2.0
    assert pdc_box.auto_initial_z(points, margin_nm=2.0) == \
        pdc_box.initial_box(points, margin_nm=2.0, initial_z_nm=8.5)[2]


def test_auto_initial_z_with_a_membrane_is_the_membrane_box_z():
    """A membrane-stating protein's box is centred on the plane, so its z is the slab-or-protein reach plus margins."""
    points = [[0.0, 0.0, -2.26], [0.0, 0.0, 3.80]]
    assert pdc_box.auto_initial_z(points, half_thickness_nm=1.18, margin_nm=2.0) == 2 * (3.80 + 2.0)
    assert pdc_box.auto_initial_z(points, half_thickness_nm=1.18, margin_nm=2.0) == \
        pdc_box.membrane_box(points, half_thickness_nm=1.18, margin_nm=2.0)[2]


def test_auto_initial_z_reaches_at_least_the_slab_it_is_centred_on():
    assert pdc_box.auto_initial_z([[0.0, 0.0, -0.2], [0.0, 0.0, 0.2]], half_thickness_nm=1.48,
                                  margin_nm=2.0) == 2 * (1.48 + 2.0)


def test_auto_initial_z_refuses_input_it_cannot_compute():
    with pytest.raises(ValueError, match='at least one coordinate'):
        pdc_box.auto_initial_z([])
    with pytest.raises(ValueError, match='positive'):
        pdc_box.auto_initial_z([[0.0, 0.0, 0.0]], margin_nm=0)
    with pytest.raises(ValueError, match='positive'):
        pdc_box.auto_initial_z([[0.0, 0.0, 0.0]], margin_nm=-1.0)



def test_the_rectangular_cell_is_the_historical_box():
    """The default cell is exactly the three independent edges: no existing run's box moves."""
    cell = pdc_box.cell('rectangular', [18.0, 18.0, 13.0])

    assert cell['shape'] == 'rectangular'
    assert cell['vectors'] == [[18.0, 0.0, 0.0], [0.0, 18.0, 0.0], [0.0, 0.0, 13.0]]
    assert cell['lengths'] == [18.0, 18.0, 13.0]
    assert cell['minimum_image_nm'] == 13.0


def test_every_shaped_cell_has_three_equal_vectors_and_the_gromacs_volume():
    """The four validation shapes, sized by the same minimum image distance d = max(required)."""
    volumes = {'cubic': 1.0, 'dodecahedron': 0.70710678, 'dodecahedron-hexagon': 0.70710678,
               'octahedron': 0.76980036}
    for shape, factor in volumes.items():
        cell = pdc_box.cell(shape, [10.0, 10.0, 8.0])
        a, b, c = (np.asarray(vector) for vector in cell['vectors'])
        assert cell['lengths'] == [10.0, 10.0, 10.0], shape
        assert cell['minimum_image_nm'] == 10.0
        assert abs(float(np.linalg.det(np.asarray(cell['vectors']))) - factor * 1000.0) < 0.01, shape
        # The minimum image distance is the vector length: every |v| is d, and the volume is the only difference.
        assert np.allclose([np.linalg.norm(vector) for vector in (a, b, c)], 10.0)


def test_an_unknown_or_non_positive_cell_is_refused():
    with pytest.raises(ValueError, match='unknown box shape'):
        pdc_box.cell('dodecahedron-square', [10.0, 10.0, 10.0])
    with pytest.raises(ValueError, match='positive'):
        pdc_box.cell('cubic', [10.0, 0.0, 10.0])
    with pytest.raises(ValueError, match='three extents'):
        pdc_box.cell('cubic', [10.0, 10.0])
