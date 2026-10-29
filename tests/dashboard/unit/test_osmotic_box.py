"""The osmotic box's arithmetic, on values that can be checked without trusting the module.

The tile is the anchor: `inputs/water.gro` holds 400 beads in a 3.64428 nm cube, so a box of exactly that volume must
ask for exactly 400 beads. Everything else is a ratio against that, which is why these tests are written as
definitions rather than as remembered constants.
"""

import pytest
from detergent_validation.execution.adapters import osmotic_box


def test_the_box_is_the_papers_and_the_confining_wall_is_its_quarter():
    assert osmotic_box.BOX_NM == (5.04156, 5.04156, 10.08312)
    assert osmotic_box.box_volume_nm3() == pytest.approx(10.08312 * 5.04156 ** 2)
    assert osmotic_box.dividing_area_nm2() == pytest.approx(5.04156 ** 2)
    # 10.08312 / 4 = 2.52078 exactly, so the confinement sits at the quarter box.
    assert osmotic_box.CONFINEMENT_NM == pytest.approx(osmotic_box.BOX_NM[2] / 4.0, abs=1e-12)
    assert osmotic_box.CONFINEMENT_KJ_MOL_NM2 == pytest.approx(1000.0)


def test_the_water_bead_mass_is_the_one_the_topology_states():
    """72.0 is four waters, from `martini_v3.0.0.itp`'s atomtypes. Three would be 54.0, and the water count -- and so
    every molality in the series -- would be a third out with every internal check still passing."""
    assert osmotic_box.WATER_BEAD_MASS == pytest.approx(72.0)
    assert osmotic_box.WATER_BEAD_MASS / 18.015 == pytest.approx(4.0, abs=0.01)


def test_a_box_the_size_of_the_solvation_tile_asks_for_the_tile_s_beads():
    """The anchor test: the density is defined by the tile, so feeding the tile's own volume back must give the tile's
    own count. If this fails, the density and the tile have drifted apart."""
    bead = osmotic_box.WATER_TILE_NM ** 3 / osmotic_box.WATER_TILE_BEADS

    assert osmotic_box.solvent_density_beads_per_nm3() == pytest.approx(osmotic_box.WATER_TILE_BEADS
                                                                       / osmotic_box.WATER_TILE_NM ** 3)
    assert bead * osmotic_box.solvent_density_beads_per_nm3() == pytest.approx(1.0)
    # And the paper's box, which is about 5.3 tiles wide, lands in the low thousands of beads.
    assert 2000 <= osmotic_box.water_beads() <= 2300, osmotic_box.water_beads()


def test_the_water_mass_is_the_count_times_four_waters():
    assert osmotic_box.water_kg(400) == pytest.approx(400 * 0.072 / osmotic_box.AVOGADRO)
    # 400 W beads are 1600 waters: 1600 * 18.015 g/mol / N_A, in kilograms.
    assert osmotic_box.water_kg(400) == pytest.approx(1600 * 0.018015 / osmotic_box.AVOGADRO, rel=1e-3)


def test_a_requested_molality_comes_back_as_the_same_molality():
    """The round trip. Necessary and not sufficient: on its own it compares the arithmetic with itself, which is why
    the volume test below exists -- the first version of this module passed this loop while over-counting the solute."""
    for molality in (0.5, 1.0, 1.5, 2.0, 2.5):
        plan = osmotic_box.plan_condition(molality)
        assert plan['achieved_molality'] == pytest.approx(molality, rel=0.01), plan


def test_the_counts_fill_the_box_exactly_once():
    """The check the round trip cannot make, and the one that caught the first version of the module.

    That version asked for 381 maltose at 2.5 molal by computing the solute from a box assumed full of water, then
    subtracting the solute's volume afterwards. The box's own volume says about 244: solute and water together must
    occupy the box once, not more, and the round trip agreed with itself either way.
    """
    radii = [0.264, 0.23, 0.23, 0.23, 0.23, 0.23, 0.23, 0.191]
    water_bead_volume = 1.0 / osmotic_box.solvent_density_beads_per_nm3()

    for molality in (0.5, 1.0, 2.5):
        plan = osmotic_box.plan_condition(molality, bead_radii_nm=radii, solute_beads_per_molecule=8)
        occupied = plan['solute_volume_total_nm3'] + plan['water_beads'] * water_bead_volume
        # Never more than the box. That is the defect this test exists for: the first version sat at 156% of it.
        assert occupied <= plan['box_volume_nm3'] * 1.02, (molality, occupied, plan)
        # And no hole either. The spheres under-state a molecule's real volume, so 80% is the honest floor.
        assert occupied >= plan['box_volume_nm3'] * 0.80, (molality, occupied, plan)
        assert plan['solute_molecules'] > 0


def test_the_solute_count_falls_when_the_solute_takes_up_room():
    """More solute means less water, which means the same molality needs fewer molecules -- the fixed point moves
    the other way from the naive count."""
    radii = [0.264, 0.23, 0.23, 0.23, 0.23, 0.23, 0.23, 0.191]
    naive = osmotic_box.plan_condition(2.5, bead_radii_nm=[0.0] * 8)
    real = osmotic_box.plan_condition(2.5, bead_radii_nm=radii)

    assert real['solute_molecules'] < naive['solute_molecules']
    assert real['water_beads'] < naive['water_beads']


def test_zero_molal_is_a_box_of_water_and_no_solute():
    plan = osmotic_box.plan_condition(0.0)

    assert plan['solute_molecules'] == 0
    assert plan['achieved_molality'] == 0.0
    assert plan['water_beads'] > 0


def test_doubling_the_molality_doubles_the_solute_and_leaves_the_water_alone():
    """The water is what molality is measured against, so it must not move with the solute count."""
    half = osmotic_box.plan_condition(1.0)
    full = osmotic_box.plan_condition(2.0)

    assert full['solute_molecules'] == pytest.approx(2 * half['solute_molecules'], rel=0.01)
    assert full['water_beads'] == half['water_beads']
    assert full['dividing_area_nm2'] == half['dividing_area_nm2']


def test_the_solute_takes_room_from_the_water_and_not_from_the_box():
    """Maltose's eight mapped beads at their own radii take room that water cannot have, and the count must reflect it
    rather than pretend the box is all solvent."""
    radii = [0.264, 0.23, 0.23, 0.23, 0.23, 0.23, 0.23, 0.191]     # a disaccharide's mapped beads
    plain = osmotic_box.plan_condition(1.0)
    displaced = osmotic_box.plan_condition(1.0, bead_radii_nm=radii, solute_beads_per_molecule=8)

    assert displaced['solute_volume_nm3'] == pytest.approx(osmotic_box.solute_volume_nm3(radii))
    assert displaced['solute_volume_nm3'] > 0.0
    # It takes room: fewer waters fit. It is a sugar and not a polymer, so it takes a minority of it.
    assert displaced['water_beads'] < plain['water_beads']
    assert displaced['water_beads'] > plain['water_beads'] * 0.5
    assert displaced['solute_beads'] == displaced['solute_molecules'] * 8


def test_a_molality_outside_the_papers_range_is_refused_with_the_bound_named():
    with pytest.raises(ValueError, match='outside the paper'):
        osmotic_box.plan_condition(3.0)
    with pytest.raises(ValueError, match='outside the paper'):
        osmotic_box.plan_condition(-0.5)


def test_a_solute_that_cannot_fit_is_refused_rather_than_silently_shrunk():
    with pytest.raises(ValueError, match='displaces'):
        osmotic_box.water_beads(displaced_nm3=osmotic_box.box_volume_nm3() + 1.0)


def test_the_confinement_is_the_quarter_box_and_its_constant_is_the_papers():
    """Both are the method, not preferences, and a run that changes either is a different experiment."""
    assert osmotic_box.CONFINEMENT_NM == pytest.approx(2.52078)
    assert osmotic_box.CONFINEMENT_KJ_MOL_NM2 == pytest.approx(1000.0)
    assert osmotic_box.MOLALITY_RANGE == (0.0, 2.5)
