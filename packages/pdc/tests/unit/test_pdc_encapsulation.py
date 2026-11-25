"""The encapsulation estimate: the arithmetic, pinned by construction rather than by a surface library.

The estimate says how many detergents a membrane protein's transmembrane apolar surface roughly needs. Step 1 of it
is a solvent-accessible area, and a SASA implementation is a piece of numerics a test should not have to fight. So
the arithmetic that turns areas into the reported numbers is a function of its own, taking the areas as they are,
and it is pinned here with numbers chosen so the answer is known by hand. The SASA step is pinned separately with
structures whose area is analytic: atoms far enough apart that each contributes exactly its own sphere.

Nothing here reads the developer's workspace, runs GROMACS, or needs a deposited structure.
"""
from __future__ import annotations

import math

import pytest
from detergent_pdc.analysis.runs import encapsulation

PROBE = 0.191


def sphere_area(radius_nm, probe_nm=PROBE):
    """The SASA of an atom no other atom can shadow: 4 pi (r + probe)^2, in square nanometres."""
    return 4 * math.pi * (radius_nm + probe_nm) ** 2


# --- step 2 and 3: the slab and the apolar mask, on areas handed in --------------------------------------------

@pytest.mark.parametrize(('positions', 'areas', 'apolar', 'centre_nm', 'half_thickness_nm', 'expected'), [
    pytest.param([[0.0, 0.0, 0.0], [0.0, 0.0, 0.9], [0.0, 0.0, 2.0]], [10.0, 20.0, 40.0], [True, False, True],
                 0.0, 1.0, 10.0, id='only-in-slab-apolar-atoms-counted'),
    pytest.param([[0.0, 0.0, 1.5], [0.0, 0.0, 2.5], [0.0, 0.0, 2.6], [0.0, 0.0, 1.4]], [1.0, 2.0, 4.0, 8.0],
                 [True] * 4, 2.0, 0.5, 3.0, id='edges-measured-from-its-own-centre-and-inclusive'),
    pytest.param([[0, 0, 5.0], [0, 0, 6.0]], [1.0, 2.0], [True, True], 0.0, 1.0, 0.0,
                 id='empty-slab-is-zero-rather-than-missing'),
])
def test_only_atoms_in_the_slab_and_in_apolar_residues_are_added(positions, areas, apolar, centre_nm,
                                                                 half_thickness_nm, expected):
    """Known by construction: the mask tells apart an atom in the slab and apolar (counted), one inside but polar
    and one apolar outside it (both not counted); the planes are inclusive and an empty slab sums to zero."""
    assert encapsulation.slab_area(areas, positions, apolar, centre_nm=centre_nm,
                                   half_thickness_nm=half_thickness_nm) == expected


# --- steps 4 and 5: the count and the fraction ----------------------------------------------------------------

def test_the_count_is_the_apolar_area_over_the_coverage_area():
    radius = 0.264
    coverage = 2 * math.pi * radius ** 2

    numbers = encapsulation.counts(apolar_area_nm2=1000.0, coverage_area_nm2=coverage, requested=200)

    assert numbers['coverage_area_nm2'] == pytest.approx(coverage)
    assert numbers['needed'] == pytest.approx(1000.0 / coverage)
    assert numbers['requested'] == 200
    assert numbers['fraction'] == pytest.approx(200 * coverage / 1000.0)


def test_the_fraction_is_the_requested_count_over_the_needed_one():
    """The two reported numbers are reciprocals of one another, so a reader can check either against the other."""
    numbers = encapsulation.counts(apolar_area_nm2=500.0, coverage_area_nm2=0.3324, requested=150)

    assert numbers['fraction'] == pytest.approx(150.0 / numbers['needed'])


def test_an_area_with_no_coverage_to_divide_it_by_is_refused():
    with pytest.raises(ValueError, match='coverage area'):
        encapsulation.counts(apolar_area_nm2=100.0, coverage_area_nm2=0.0, requested=10)


# --- step 1 and the whole estimate: structures whose area is known by construction -----------------------------

def test_an_isolated_apolar_atom_contributes_its_own_sphere_area():
    """An atom alone in space is analytically accessible, which is what makes this a construction and not a fixture."""
    radius = 0.264

    numbers = encapsulation.estimate([[0.0, 0.0, 0.0]], [radius], [True],
                                     centre_nm=0.0, half_thickness_nm=1.0,
                                     coverage_radii_nm=[0.230], requested=10, probe_nm=PROBE)

    assert numbers['apolar_area_nm2'] == pytest.approx(sphere_area(radius), rel=1e-6)


@pytest.mark.parametrize(('positions', 'apolar'), [
    pytest.param([[0.0, 0.0, 0.0], [9.0, 0.0, 0.0]], [True, False], id='polar-atom-inside-the-slab'),
    pytest.param([[0.0, 0.0, 0.0], [0.0, 0.0, 5.0]], [True, True], id='apolar-atom-outside-the-slab'),
])
def test_an_atom_the_mask_excludes_adds_nothing_to_the_apolar_area(positions, apolar):
    """Two isolated atoms, one excluded by the mask -- polar inside the slab, or apolar outside it: the sum is the
    counted atom's own sphere and only that."""
    numbers = encapsulation.estimate(positions, [0.264, 0.264], apolar,
                                     centre_nm=0.0, half_thickness_nm=1.0,
                                     coverage_radii_nm=[0.230], requested=10, probe_nm=PROBE)

    assert numbers['apolar_area_nm2'] == pytest.approx(sphere_area(0.264), rel=1e-6)


def test_the_whole_structure_occludes_even_where_the_slab_stops():
    """The slab restricts which areas are *summed*, not which atoms shadow each other.

    A second atom 0.3 nm away sits outside a half-thickness-0.2 nm slab, so its own area is not counted -- but it
    still covers part of the first atom's surface, and the first atom's area must come back below its isolated one.
    """
    numbers = encapsulation.estimate([[0.0, 0.0, 0.0], [0.0, 0.0, 0.3]], [0.264, 0.264], [True, True],
                                     centre_nm=0.0, half_thickness_nm=0.2,
                                     coverage_radii_nm=[0.230], requested=10, probe_nm=PROBE)

    assert numbers['apolar_area_nm2'] < sphere_area(0.264), 'the out-of-slab atom must still occlude'


def test_the_reported_numbers_are_the_plan_s_five_steps_and_agree_with_the_area_they_report():
    """The invariant: the count is the reported area over the reported coverage area, not some other pair."""
    numbers = encapsulation.estimate([[0.0, 0.0, 0.0], [6.0, 0.0, 0.0]], [0.264, 0.230], [True, True],
                                     centre_nm=0.0, half_thickness_nm=1.0,
                                     coverage_radii_nm=[0.230], requested=120, probe_nm=PROBE)

    for key in ('apolar_area_nm2', 'coverage_area_nm2', 'coverage_radii_nm', 'tail_ends', 'needed', 'requested',
                'fraction'):
        assert key in numbers, key
    assert numbers['coverage_area_nm2'] == pytest.approx(2 * math.pi * 0.230 ** 2)
    assert numbers['coverage_radii_nm'] == [0.230] and numbers['tail_ends'] == 1
    assert numbers['needed'] == pytest.approx(numbers['apolar_area_nm2'] / numbers['coverage_area_nm2'])
    assert numbers['fraction'] == pytest.approx(numbers['requested'] / numbers['needed'])


def test_the_estimate_carries_its_method_and_its_caveat():
    """The panel renders what the server decided: the conventions travel with the number."""
    assert 'Shrake-Rupley' in encapsulation.ESTIMATE_METHOD
    assert 'free-end tail bead' in encapsulation.ESTIMATE_METHOD
    assert '2 * pi * sum(r^2)' in encapsulation.ESTIMATE_METHOD
    assert 'A, V, L, I, M, F, W, P' in encapsulation.ESTIMATE_METHOD
    assert 'roughly the right order' in encapsulation.ESTIMATE_CAVEAT
    assert 'flat surface' in encapsulation.ESTIMATE_CAVEAT
    assert 'estimate' in encapsulation.ESTIMATE_CAVEAT.lower()


def test_a_structure_with_no_apolar_surface_in_the_slab_is_refused_rather_than_divided_by_zero():
    with pytest.raises(ValueError, match='apolar'):
        encapsulation.estimate([[0.0, 0.0, 0.0]], [0.264], [False],
                               centre_nm=0.0, half_thickness_nm=1.0,
                               coverage_radii_nm=[0.230], requested=10, probe_nm=PROBE)


def test_a_branched_detergent_sums_both_of_its_tail_ends():
    """LMNG presents two hemispheres, so its coverage is twice one S bead's -- the branching the method names."""
    numbers = encapsulation.estimate([[0.0, 0.0, 0.0]], [0.264], [True],
                                     centre_nm=0.0, half_thickness_nm=1.0,
                                     coverage_radii_nm=[0.230, 0.230], requested=10, probe_nm=PROBE)

    assert numbers['tail_ends'] == 2
    assert numbers['coverage_area_nm2'] == pytest.approx(4 * math.pi * 0.230 ** 2)
    assert numbers['needed'] == pytest.approx(numbers['apolar_area_nm2'] / numbers['coverage_area_nm2'])


def test_an_estimate_with_no_free_end_tail_bead_to_size_against_is_refused():
    with pytest.raises(ValueError, match='free-end tail bead'):
        encapsulation.estimate([[0.0, 0.0, 0.0]], [0.264], [True],
                               centre_nm=0.0, half_thickness_nm=1.0,
                               coverage_radii_nm=[], requested=10, probe_nm=PROBE)


# --- reading the structure: elements and residues -------------------------------------------------------------

def test_atom_radii_come_from_the_element_the_atom_name_names():
    """The rule surfaces.py already uses: strip the digits, take the first letter, title-case the two-letter ones."""
    assert encapsulation.atom_radii_nm(['N', 'CA', 'CB', 'O', '1H']) == [0.161, 0.175, 0.175, 0.156, 0.109]


def test_an_atom_whose_element_has_no_radius_here_is_refused_with_its_name():
    with pytest.raises(ValueError, match='Zz'):
        encapsulation.atom_radii_nm(['Zz'])


def test_the_apolar_mask_is_the_plan_s_eight_residues_by_their_one_letter_code():
    residues = ['ALA', 'VAL', 'LEU', 'ILE', 'MET', 'PHE', 'TRP', 'PRO',     # apolar
                'SER', 'THR', 'LYS', 'GLU', 'ASP', 'GLY', 'UNK']            # not apolar here

    assert encapsulation.apolar_mask(residues) == [True] * 8 + [False] * 7


def test_modified_residues_with_an_apolar_parent_are_apolar_too():
    """The defect this exists for: a deposited structure rarely carries plain MET, and an MSE counted as polar
    undercounts every SeMet-phased one. Each code below names its parent in the table; the mask reads it through."""
    modified = ['MSE', 'FME', 'MED', 'NLE', 'NVA', 'ABA', 'AIB',
                'DAL', 'DVA', 'DLE', 'DIL', 'DPN', 'DPR', 'DTR']

    assert encapsulation.apolar_mask(modified) == [True] * len(modified)


def test_modified_residues_whose_parent_is_polar_or_that_add_polarity_are_not_apolar():
    """SEP, TPO and CSO add a phosphate or a hydroxyl and their parents are polar besides; HYP's parent (proline) is
    apolar but it adds a hydroxyl, and KCX and MLY modify a polar lysine. None is nonpolar surface."""
    assert encapsulation.apolar_mask(['SEP', 'TPO', 'CSO', 'HYP', 'KCX', 'MLY']) == [False] * 6


def test_every_modified_code_in_the_table_has_an_apolar_parent():
    """The rule the table exists for, checked mechanically: a code is folded in only if its parent is one of the eight
    apolar residues. A future entry with a polar parent fails here rather than overcounting a belt."""
    assert set(encapsulation.MODIFIED_APOLAR.values()) <= set(encapsulation.APOLAR_CODES)
    assert set(encapsulation.MODIFIED_APOLAR) == {
        'MSE', 'FME', 'MED', 'NLE', 'NVA', 'ABA', 'AIB', 'DAL', 'DVA', 'DLE', 'DIL', 'DPN', 'DPR', 'DTR'}


@pytest.mark.parametrize(('residues', 'spheres'), [
    pytest.param(['MSE', 'NLE'], 2, id='both-modified-residues-have-apolar-parents'),
    pytest.param(['MSE', 'SEP'], 1, id='polar-modified-residue-adds-nothing'),
])
def test_modified_residues_inside_the_slab_add_the_area_their_parents_earn(residues, spheres):
    """Modified residues with an apolar parent are apolar surface, so inside the slab each adds its own sphere -- two
    isolated atoms folded in are both spheres. SEP (phosphoserine) adds a phosphate, so it stays polar and adds
    nothing even inside the slab."""
    numbers = encapsulation.estimate([[0.0, 0.0, 0.0], [9.0, 0.0, 0.0]], [0.264, 0.264],
                                     encapsulation.apolar_mask(residues),
                                     centre_nm=0.0, half_thickness_nm=1.0,
                                     coverage_radii_nm=[0.230], requested=10, probe_nm=PROBE)

    assert numbers['apolar_area_nm2'] == pytest.approx(spheres * sphere_area(0.264), rel=1e-6)


def test_the_short_method_states_the_two_areas_and_that_nothing_was_simulated():
    """The panel's bubble says what was divided and that it was geometry; the long method stays the route's own."""
    summary = encapsulation.ESTIMATE_SUMMARY

    assert 'apolar' in summary.lower() and 'free-end tail bead' in summary
    assert 'No simulation' in summary
    assert len(summary.split()) <= 45, 'the bubble is the short form, not a paragraph in a tooltip'
    assert len(summary) < len(encapsulation.ESTIMATE_METHOD) / 2


def test_the_method_states_that_apolar_parented_modified_residues_are_folded_in():
    """The prose travels with the number, so it must say what the arithmetic did with a modified residue."""
    assert 'modified residue' in encapsulation.ESTIMATE_METHOD
    assert 'apolar parent' in encapsulation.ESTIMATE_METHOD
    assert 'MSE' in encapsulation.ESTIMATE_METHOD


def test_a_structure_is_read_in_nanometres_with_a_radius_per_atom(tmp_path):
    """A hand-made PDB: ATOM columns are Angstrom, and the radii come from the element each name names."""
    path = tmp_path / 'fixture.pdb'
    path.write_text(
        'REMARK      1/2 of bilayer thickness:   10.0\n'
        'ATOM      1  N   ALA A   1       1.000   2.000   3.000  1.00  0.00           N\n'
        'ATOM      2  CA  ALA A   1       1.300   2.000   3.000  1.00  0.00           C\n'
        'END\n')

    atoms = encapsulation.read_structure(path)

    assert atoms['residues'] == ['ALA', 'ALA']
    assert atoms['positions_nm'][0] == pytest.approx([0.1, 0.2, 0.3])
    assert atoms['radii_nm'] == [0.161, 0.175]


# --- where the free-end tail beads come from: the mapping's own beads and connections ---------------------------

# DDM-like: a linear tail TAIL1-TAIL2-TAIL3 bonded on into the head at TAIL3, so TAIL3 is not an end and TAIL1 is.
DDM_MAPPING = {
    'beads': [
        {'name': 'TAIL1', 'type': 'C1', 'size': 'R'},
        {'name': 'TAIL2', 'type': 'C1', 'size': 'R'},
        {'name': 'TAIL3', 'type': 'C1', 'size': 'R'},
        {'name': 'S1A', 'type': 'SP1r', 'size': 'S'},
        {'name': 'S1VS', 'type': 'TC4', 'size': 'T',
         'virtual_site': {'function': 1, 'parents': ['S1A', 'TAIL3']}},
    ],
    'connections': [['TAIL1', 'TAIL2'], ['TAIL2', 'TAIL3'], ['S1A', 'TAIL3'], ['S1VS', 'S1A']],
}
# LMNG-like: one tail bead branches into two leaves, each a small bead, so both ends present a hemisphere.
LMNG_MAPPING = {
    'beads': [
        {'name': 'HEAD', 'type': 'P1', 'size': 'R'},
        {'name': 'TAIL1', 'type': 'C1', 'size': 'R'},
        {'name': 'TAIL2', 'type': 'SC1', 'size': 'S'},
        {'name': 'TAIL3', 'type': 'SC1', 'size': 'S'},
    ],
    'connections': [['HEAD', 'TAIL1'], ['TAIL1', 'TAIL2'], ['TAIL1', 'TAIL3']],
}


def test_a_single_end_detergent_has_one_free_end_tail_bead():
    """DDM's linear tail: degree one is TAIL1, and the ring virtual site is not a tail bead even at degree one."""
    ends = encapsulation.edge_tail_beads(DDM_MAPPING)

    assert [bead['name'] for bead in ends] == ['TAIL1']
    assert encapsulation.mapping_coverage_radii(DDM_MAPPING) == [0.264]


def test_a_branched_detergent_has_two_free_end_tail_beads():
    """LMNG's two leaves: both are ends of class S, so the coverage sums both hemispheres, not just the largest."""
    ends = encapsulation.edge_tail_beads(LMNG_MAPPING)

    assert [bead['name'] for bead in ends] == ['TAIL2', 'TAIL3']
    assert encapsulation.mapping_coverage_radii(LMNG_MAPPING) == [0.230, 0.230]


def test_the_coverage_area_is_two_pi_times_the_sum_of_the_squared_radii():
    """The decided arithmetic, pinned by hand against the two reference detergents.

    The reference numbers are quoted to four decimals (DDM 0.4378, LMNG 0.6648); the exact 2*pi*r^2 is 0.437913 for
    DDM's R bead, so the hand number is checked with a tolerance a four-decimal quote allows.
    """
    assert encapsulation.coverage_area_nm2([0.264]) == pytest.approx(2 * math.pi * 0.264 ** 2)
    assert encapsulation.coverage_area_nm2([0.230, 0.230]) == pytest.approx(4 * math.pi * 0.230 ** 2)
    assert encapsulation.coverage_area_nm2([0.264]) == pytest.approx(0.4378, abs=2e-4)
    assert encapsulation.coverage_area_nm2([0.230, 0.230]) == pytest.approx(0.6648, abs=2e-4)


def test_a_mapping_that_states_no_connections_is_refused_with_a_reason():
    """With no connectivity there is no way to tell an end from a bonded-through bead, so nothing is guessed."""
    with pytest.raises(ValueError, match='connections'):
        encapsulation.edge_tail_beads({'beads': DDM_MAPPING['beads']})
    with pytest.raises(ValueError, match='connections'):
        encapsulation.edge_tail_beads({'beads': DDM_MAPPING['beads'], 'connections': []})


def test_a_mapping_with_no_free_end_tail_bead_is_refused_with_a_reason():
    """Every tail bead bonded on both sides is a ring, not a chain with ends: there is no hemisphere to sum."""
    ring = {'beads': [{'name': f'TAIL{index}', 'type': 'C1', 'size': 'R'} for index in (1, 2, 3)],
            'connections': [['TAIL1', 'TAIL2'], ['TAIL2', 'TAIL3'], ['TAIL3', 'TAIL1']]}

    with pytest.raises(ValueError, match='free-end tail'):
        encapsulation.edge_tail_beads(ring)


def test_an_empty_coverage_area_is_refused_rather_than_divided_by():
    with pytest.raises(ValueError, match='free-end tail'):
        encapsulation.coverage_area_nm2([])


def test_the_tail_bead_s_size_class_is_the_one_the_mapping_records():
    assert encapsulation.size_class({'name': 'S1C', 'type': 'SN6', 'size': 'S'}) == 'S'
    assert encapsulation.size_radius_nm('R') == 0.264
    assert encapsulation.size_radius_nm('S') == 0.230
    assert encapsulation.size_radius_nm('T') == 0.191


def test_a_bead_that_records_no_size_falls_back_to_the_size_prefix_its_martini_type_carries():
    """Martini 3 spells the size class as a prefix on the bead type: S is small, T is tiny, everything else regular."""
    assert encapsulation.size_class({'name': 'H', 'type': 'SN6'}) == 'S'
    assert encapsulation.size_class({'name': 'H', 'type': 'TN6'}) == 'T'
    assert encapsulation.size_class({'name': 'H', 'type': 'C1'}) == 'R'
    assert encapsulation.size_class({'name': 'H', 'type': 'P1'}) == 'R'


def test_a_tail_bead_whose_size_class_this_repository_carries_no_radius_for_is_refused():
    """The mapping can only state R, S or T, and the repository carries a radius for exactly those three. Anything
    else is a class nothing here can turn into a radius, and the route must say so rather than pick one."""
    with pytest.raises(ValueError, match='no radius'):
        encapsulation.size_radius_nm('N')


def test_the_coverage_radii_come_from_the_mappings_own_free_end_tail_beads():
    assert encapsulation.mapping_coverage_radii(DDM_MAPPING) == [0.264]
    assert encapsulation.mapping_coverage_radii(LMNG_MAPPING) == [0.230, 0.230]


# --- the selection: a structure can be an assembly, and only some of it is simulated ---------------------------------

# Two subunits, each a chain of two apolar atoms 0.9 nm apart inside a 1.0 nm slab, and the two subunits 10 nm apart
# -- far enough that neither occludes the other, so the area is additive and known by construction.
MULTICHAIN = (
    'REMARK      1/2 of bilayer thickness:   10.0\n'
    'ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\n'
    'ATOM      2  CA  ALA A   2       0.000   0.000   9.000  1.00  0.00           C\n'
    'ATOM      3  CA  LEU B   1     100.000   0.000   0.000  1.00  0.00           C\n'
    'ATOM      4  CA  LEU B   2     100.000   0.000   9.000  1.00  0.00           C\n'
    'END\n')


def test_read_structure_reports_the_chains_a_file_names(tmp_path):
    path = tmp_path / 'assembly.pdb'
    path.write_text(MULTICHAIN)

    atoms = encapsulation.read_structure(path)

    assert atoms['chains_available'] == ['A', 'B']
    assert len(atoms['positions_nm']) == 4


def test_read_structure_filters_to_the_chosen_chains_before_the_surface_is_computed(tmp_path):
    """The plan's requirement: the area describes the object that will be simulated, not the file it came from."""
    path = tmp_path / 'assembly.pdb'
    path.write_text(MULTICHAIN)

    atoms = encapsulation.read_structure(path, chains=['A'])

    assert atoms['chains'] == ['A', 'A']
    assert atoms['residues'] == ['ALA', 'ALA']
    assert len(atoms['positions_nm']) == 2, 'the other subunit never reaches the SASA'
    assert atoms['chains_available'] == ['A', 'B'], 'what the file has is still reported'
    assert atoms['narrowed'] is True


# A file like 1AT9: the subunits in named chains, and a placeholder in no chain at all. The whole-file estimate
# counts it (it occludes), so selecting every chain must keep it -- only a strict subset may drop it.
WITH_PLACEHOLDER = (
    'ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\n'
    'ATOM      2  CA  LEU B   1     100.000   0.000   0.000  1.00  0.00           C\n'
    'HETATM    3  O   DUM     1      50.000   0.000   0.000  1.00  0.00           O\n'
    'END\n')


def test_selecting_every_declared_chain_is_the_whole_file_and_only_a_subset_narrows(tmp_path):
    """1AT9's 1,610 chain-less DUM placeholders are why the trimer's number is not 2x a subunit's: every declared
    chain selected is the whole file, exactly as a caller that chose nothing gets."""
    path = tmp_path / 'assembly.pdb'
    path.write_text(WITH_PLACEHOLDER)

    whole = encapsulation.read_structure(path)
    every = encapsulation.read_structure(path, chains=['A', 'B'])
    one = encapsulation.read_structure(path, chains=['A'])

    assert len(whole['positions_nm']) == 3 and whole['narrowed'] is False
    assert len(every['positions_nm']) == 3, 'every declared chain is the whole file, chain-less records included'
    assert every['narrowed'] is False
    assert [chain for chain in one['chains']] == ['A'] and one['narrowed'] is True
    assert len(one['positions_nm']) == 1, 'a strict subset is the only thing that drops the chain-less record'


def test_a_requested_chain_the_structure_does_not_name_is_reported_rather_than_dropped():
    """A chain that is not there must not be silently ignored: it sizes a different object than the one asked for."""
    assert encapsulation.unknown_chains(['A', 'B'], ['A', 'Z']) == ['Z']
    assert encapsulation.unknown_chains(['A', 'B'], ['A', 'B']) == []
    assert encapsulation.unknown_chains([], ['A']) == ['A']


def test_the_selection_is_the_area_of_the_chosen_chains_and_not_of_the_others(tmp_path):
    path = tmp_path / 'assembly.pdb'
    path.write_text(MULTICHAIN)

    def sized(atoms):
        return encapsulation.estimate(atoms['positions_nm'], atoms['radii_nm'],
                                      encapsulation.apolar_mask(atoms['residues']),
                                      centre_nm=0.0, half_thickness_nm=1.0,
                                      coverage_radii_nm=[0.230], requested=10, probe_nm=PROBE)

    everything = sized(encapsulation.read_structure(path))
    one = sized(encapsulation.read_structure(path, chains=['B']))

    assert one['atoms'] == 2 and everything['atoms'] == 4
    assert everything['apolar_area_nm2'] == pytest.approx(2 * one['apolar_area_nm2'], rel=1e-4)
