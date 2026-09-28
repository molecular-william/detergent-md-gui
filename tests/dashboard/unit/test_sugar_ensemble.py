"""The ensemble arithmetic: bead centres, distances, spread, and the comparison with the published values.

These are the numbers the 200 ns run exists to produce, so they are pinned without needing a trajectory: the shell
that reads one only fills the dictionary the samples arrive in.
"""
import numpy as np
import pytest

from dashboard.analysis import sugar_ensemble

POINTS = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 2.0, 0.0]]
BEADS = {'A': [0, 1], 'B': [2]}
PAIR = frozenset(('A', 'B'))


def test_a_bead_sits_at_the_centre_of_its_atoms():
    centres = sugar_ensemble.bead_centres(BEADS, POINTS)
    assert np.allclose(centres['A'], [0.5, 0.0, 0.0])
    assert np.allclose(centres['B'], [0.0, 2.0, 0.0])


def test_a_distance_is_measured_between_the_named_beads():
    centres = sugar_ensemble.bead_centres(BEADS, POINTS)
    distances = sugar_ensemble.pair_distances(centres, [('A', 'B')])
    assert np.isclose(distances[PAIR], np.hypot(0.5, 2.0))


def test_a_pair_with_a_missing_end_is_omitted_rather_than_guessed():
    distances = sugar_ensemble.pair_distances({'A': np.zeros(3)}, [('A', 'B')])
    assert distances == {}


def test_the_summary_reports_the_mean_the_deviation_and_the_observed_range():
    stats = sugar_ensemble.summarise({PAIR: [0.30, 0.40, 0.50]})[PAIR]
    assert stats['count'] == 3
    assert np.isclose(stats['mean'], 0.40)
    assert np.isclose(stats['min'], 0.30) and np.isclose(stats['max'], 0.50)
    assert stats['std'] > 0


def test_the_comparison_says_whether_the_observed_spread_reaches_the_published_value():
    covered = sugar_ensemble.compare({PAIR: 0.45}, {PAIR: [0.40, 0.50]})[0]
    assert covered['published_nm'] == 0.45
    assert covered['spread_covers_published'] is True
    assert np.isclose(covered['delta_pct'], 0.0)

    narrow = sugar_ensemble.compare({PAIR: 0.60}, {PAIR: [0.40, 0.50]})[0]
    assert narrow['spread_covers_published'] is False
    assert narrow['delta_pct'] < 0


def test_the_single_frame_number_is_carried_beside_the_ensemble_one():
    row = sugar_ensemble.compare({PAIR: 0.45}, {PAIR: [0.40, 0.50]}, single_frame={PAIR: 0.415})[0]
    assert np.isclose(row['single_frame_nm'], 0.415)


def test_an_unconstrained_pair_is_reported_as_unconstrained_rather_than_compared():
    row = sugar_ensemble.compare({}, {PAIR: [0.40]})[0]
    assert row['unconstrained'] is True
    assert row['delta_pct'] is None


def gro_line(index, name, element_mass, xyz):
    """A .gro atom line in the documented fixed columns, so the reader is tested against the format."""
    residue = f'{1:5d}{"LIG":<5}{name:>5}{index:5d}'
    return residue + ''.join(f'{value:8.3f}' for value in xyz)


def write_run(tmp_path, atom_count=2, declared=None):
    """A run's own inputs at the two paths the analysis reads, which is what makes a report reproducible."""
    stages = tmp_path / 'stages'
    (stages / 'common/molecule').mkdir(parents=True)
    (stages / '07_reference').mkdir(parents=True)
    (stages / 'common/molecule/molecule.itp').write_text('#include "lig1.itp"\n')
    (stages / 'common/molecule/lig1.itp').write_text(
        '[ atoms ]\n1 CT 1 LIG C 1 0 12.011\n2 OA 1 LIG O 2 0 15.999\n[bonds]\n1 2 1 0.15 1000\n')
    body = [gro_line(1, 'C', 12.011, [0.100, 0.200, 0.300]), gro_line(2, 'O', 15.999, [0.200, 0.300, 0.400])]
    (stages / '07_reference/lig.gro').write_text(
        '\n'.join(['solute', f'{atom_count if declared is None else declared:5d}']
                  + body[:atom_count] + ['   1.00000   1.00000   1.00000']) + '\n')
    return tmp_path


def test_a_topology_is_read_into_its_sections_without_its_comments():
    table = sugar_ensemble.sections('[ atoms ]\n; a comment\n1 CT 1 LIG C 1 0 12.011\n[ bonds ]\n1 2 1 0.15 1000\n')
    assert table['atoms'][0][:4] == ['1', 'CT', '1', 'LIG']
    assert table['bonds'][0][:2] == ['1', '2']


def test_the_element_comes_from_the_mass_and_not_from_a_threshold():
    """Oxygen is 15.999: a threshold that rounds it up turns every alcohol into an amine."""
    assert sugar_ensemble.element_for(15.999) == 'O'
    assert sugar_ensemble.element_for(14.007) == 'N'
    assert sugar_ensemble.element_for(12.011) == 'C'
    assert sugar_ensemble.element_for(1.008) == 'H'


def test_a_runs_own_inputs_are_read_and_converted_to_angstrom(tmp_path):
    """The report must be reproducible from an archived run, so it reads the run's copy of the topology."""
    solute = sugar_ensemble.read_solute(write_run(tmp_path))
    assert [atom['element'] for atom in solute['atoms']] == ['C', 'O']
    assert solute['bonds'] == [[1, 2]]
    assert solute['atoms'][0]['xyz'] == [1.0, 2.0, 3.0], '0.100 nm is 1.0 angstrom'
    assert solute['atoms'][1]['heavy'] is True


def test_inputs_that_are_not_the_same_molecule_are_refused(tmp_path):
    with pytest.raises(ValueError, match='not the same molecule'):
        sugar_ensemble.read_solute(write_run(tmp_path, atom_count=1))


def test_the_report_states_which_reference_entry_it_compared_against():
    text = sugar_ensemble.format_report({'molecule': 'Sucrose', 'entry': 'SUCR', 'frames': 2, 'rows': [
        {'label': [(1, 'A'), (1, 'B')], 'pair': [1, 2], 'count': 2, 'mean': 0.32, 'std': 0.01,
         'min': 0.30, 'max': 0.34, 'published_nm': 0.305, 'delta_pct': 4.8,
         'spread_covers_published': True, 'unconstrained': False}]})
    assert 'SUCR' in text and '0.305' in text and '+4.8%' in text and 'True' in text
