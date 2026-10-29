"""The bonded-term reader and its two metrics, with the geometry checked against known coordinates."""
import MDAnalysis as mda
import numpy as np
import pytest
from dashboard.analysis.runs import bonded_terms

TOPOLOGY = """[ moleculetype ]
SUCR 1

[ atoms ]
1 SP1r 1 SUCR A 1 0 54
2 SP4r 1 SUCR B 2 0 54
3 SP1r 1 SUCR C 3 0 54
4 TC4 1 SUCR VS 4 0 0

[ bonds ]
; i j funct length force
1 2 1 0.4600 1250

[ angles ]
2 1 3 2 120.0 25.0

[ dihedrals ]
1 2 3 4 1 5.0 10.0 1

[ proper-dihedrals ]
2 1 3 4 1 15.0 2.0 3
"""


def test_bonds_are_read_zero_based_and_unordered():
    terms = bonded_terms.read_terms(TOPOLOGY)
    assert terms['bonds'][0]['atoms'] == (0, 1)
    assert terms['bonds'][0]['function'] == 1
    assert terms['bonds'][0]['parameters'] == (0.46, 1250.0)


def test_angles_and_dihedrals_keep_their_atom_order():
    terms = bonded_terms.read_terms(TOPOLOGY)
    assert terms['angles'][0]['atoms'] == (1, 0, 2)
    assert terms['dihedrals'][0]['atoms'] == (0, 1, 2, 3)
    assert terms['proper-dihedrals'][0]['atoms'] == (1, 0, 2, 3)


def test_comments_and_other_sections_are_ignored():
    terms = bonded_terms.read_terms('[ virtual_sitesn ]\n1 2 3\n\n[bonds]\n; a comment\n1 2 1 0.3 900\n')
    assert len(terms['bonds']) == 1 and terms['angles'] == []


def test_an_invalid_atom_index_is_refused_rather_than_skipped():
    with pytest.raises(ValueError, match='Invalid bonds atom indices'):
        bonded_terms.read_terms('[ bonds ]\nzero 2 1 0.3 900\n')


def test_proper_dihedrals_join_the_dihedral_set():
    sets = bonded_terms.term_sets(bonded_terms.read_terms(TOPOLOGY))
    assert sets['dihedrals'] == {(0, 1, 2, 3), (1, 0, 2, 3)}
    assert sets['bonds'] == {(0, 1)}


def test_a_distance_is_measured_in_nanometres():
    positions = np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 10.0]])
    assert np.isclose(bonded_terms.distance_nm(positions, (0, 1)), 1.0)


def test_an_angle_is_measured_in_degrees_at_the_middle_bead():
    positions = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    assert np.isclose(bonded_terms.angle_deg(positions, (0, 1, 2)), 90.0)


def test_a_right_angle_dihedral_is_ninety_degrees():
    positions = np.array([[0.0, 1.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 1.0], [1.0, 0.0, 1.0]])
    assert np.isclose(abs(bonded_terms.dihedral_deg(positions, (0, 1, 2, 3))), 90.0)


def test_a_planar_trans_dihedral_is_one_hundred_and_eighty_degrees():
    """All four beads in one plane with the outer two opposed: the dihedral is trans, not cis."""
    positions = np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, 1.0, 1.0], [0.0, 1.0, 2.0]])
    assert abs(abs(bonded_terms.dihedral_deg(positions, (0, 1, 2, 3)) - 180.0) < 1e-6)


def build_trajectory(root, positions, atoms=4, frames=3):
    """A trajectory the test owns, with coordinates it chose."""
    structure = root / 'system.gro'
    lines = ['fixture', f'{atoms:5d}']
    for index, xyz in enumerate(positions, 1):
        lines.append(f"{1:5d}{'SUCR':<5}{'A':>5}{index:5d}" + ''.join(f'{value:8.3f}' for value in xyz))
    lines.append('   1.00000   1.00000   1.00000')
    structure.write_text('\n'.join(lines) + '\n')
    trajectory = root / 'system.xtc'
    universe = mda.Universe.empty(atoms, trajectory=True)
    universe.atoms.positions = np.asarray(positions, dtype=float)
    with mda.Writer(str(trajectory), n_atoms=atoms) as writer:
        for _ in range(frames):
            writer.write(universe)
    return trajectory, structure


def test_measure_reports_every_term_on_a_known_trajectory(tmp_path):
    positions = [[0.0, 0.0, 0.0], [4.0, 0.0, 0.0], [4.0, 4.0, 0.0], [4.0, 4.0, 4.0]]
    trajectory, structure = build_trajectory(tmp_path, positions)
    measured = bonded_terms.measure(trajectory, structure, bonded_terms.read_terms(TOPOLOGY))
    assert measured['frames'] == 3
    assert np.isclose(np.mean(measured['values']['bonds'][(0, 1)]), 0.4), 'B is 4 angstrom from A'
    # The angle term is (B, A, C): its middle bead is A at the origin, so the two arms are (4,0,0) and (4,4,0).
    assert np.isclose(np.mean(measured['values']['angles'][(1, 0, 2)]), 45.0)
    assert len(measured['values']['dihedrals'][(0, 1, 2, 3)]) == 3


def test_measure_stride_and_limit_take_the_frames_asked_for(tmp_path):
    positions = [[0.0, 0.0, 0.0], [4.0, 0.0, 0.0], [4.0, 4.0, 0.0], [4.0, 4.0, 4.0]]
    trajectory, structure = build_trajectory(tmp_path, positions, frames=6)
    terms = bonded_terms.read_terms(TOPOLOGY)
    assert bonded_terms.measure(trajectory, structure, terms, limit=2)['frames'] == 2
    assert bonded_terms.measure(trajectory, structure, terms, stride=2)['frames'] == 3


def test_overlap_is_one_for_identical_series_and_zero_for_disjoint_ones():
    assert bonded_terms.overlap([0.3, 0.31, 0.32], [0.3, 0.31, 0.32]) == 1.0
    assert bonded_terms.overlap([0.3, 0.31], [0.9, 0.91]) == 0.0


def test_overlap_refuses_an_empty_series_rather_than_returning_zero():
    with pytest.raises(ValueError, match='non-empty'):
        bonded_terms.overlap([], [0.3])


def test_a_few_outlying_values_do_not_move_the_metric():
    """The edges are the atomistic series', so two outlying values change nothing about the range."""
    anchor = np.linspace(0.0, 1.0, 2000)
    base = np.concatenate([np.linspace(0.2, 0.8, 900), np.linspace(0.35, 0.65, 100)])
    tails = np.concatenate([base, [3.0], [-3.0]])
    assert bonded_terms.overlap(anchor, tails, anchor=anchor) == pytest.approx(
        bonded_terms.overlap(anchor, base, anchor=anchor), abs=0.01)


def test_the_metric_does_not_depend_on_which_series_is_sampled_more():
    """The defect E2 exposed, exactly.

    Raw counts were compared, so with 20,001 atomistic frames against 1,001 coarse-grained ones the `min` was
    the smaller series wherever it had mass: the same model scored 0.98 at 1,001 frames and 0.62 at 20,001,
    which is a statement about the sampling. Repeating every coarse-grained sample twenty times leaves the
    distribution unchanged, and now leaves the metric unchanged too.
    """
    rng = np.random.default_rng(20260929)
    anchor = 120 + rng.normal(0, 5, 20000)
    cg = 118 + rng.normal(0, 6, 1001)
    assert bonded_terms.overlap(anchor, cg, anchor=anchor) == pytest.approx(
        bonded_terms.overlap(anchor, np.repeat(cg, 20), anchor=anchor), abs=1e-9)


def test_the_range_comes_from_the_anchor_and_not_from_the_wider_series():
    anchor = np.linspace(0.0, 1.0, 200)
    assert bonded_terms.bin_edges(anchor)[0] == pytest.approx(-0.1)
    assert bonded_terms.bin_edges(anchor)[-1] == pytest.approx(1.1)


def test_mass_beyond_the_range_counts_as_outside_rather_than_being_folded_in():
    anchor = np.linspace(0.0, 1.0, 200)
    outside = np.full(50, 9.0)
    assert bonded_terms.overlap(anchor, outside, anchor=anchor) == 0.0
    half = np.concatenate([np.full(25, 0.5), np.full(25, 9.0)])
    assert 0.0 < bonded_terms.overlap(anchor, half, anchor=anchor) < 1.0


def test_a_term_reads_as_the_mapping_names_its_beads():
    assert bonded_terms.label_for({1: (1, 'A'), 2: (1, 'B')}, (0, 1)) == '(1,A) - (1,B)'


def values_for(pairs):
    return {'frames': 3, 'values': {'bonds': pairs, 'angles': {}, 'dihedrals': {}, 'proper-dihedrals': {}},
            'source': {}}


def test_a_term_the_cg_run_lacks_is_reported_rather_than_scored():
    aa = values_for({(0, 1): [0.3, 0.31, 0.32]})
    rows = bonded_terms.compare_terms(aa, values_for({}))
    assert rows[0]['compared'] is False and rows[0]['cg'] is None
    assert 'holds no sample' in rows[0]['note']


def test_a_term_the_atomistic_side_lacks_is_compared_with_its_reason():
    cg = values_for({(0, 1): [0.3, 0.31, 0.32]})
    rows = bonded_terms.compare_terms(values_for({}), cg)
    assert rows[0]['compared'] is True and rows[0]['aa'] is None
    assert 'atomistic mapping holds no sample' in rows[0]['note']


def test_a_compared_term_carries_both_metrics_and_the_definition_reads_beside_it():
    aa = values_for({(0, 1): [0.30, 0.31, 0.32, 0.33]})
    cg = values_for({(0, 1): [0.35, 0.36, 0.37, 0.38]})
    row = bonded_terms.compare_terms(aa, cg, currency={1: (1, 'A'), 2: (1, 'B')})[0]
    assert row['compared'] is True and row['beads'] == '(1,A) - (1,B)'
    assert row['delta'] == pytest.approx(0.05, abs=1e-6)
    assert row['wasserstein'] == pytest.approx(0.05, abs=1e-6)
    assert row['overlap'] == 0.0
    assert row['aa']['stderr'] > 0 and row['cg']['stderr'] > 0
