"""The ensemble arithmetic the consistency analyses share: distances, spread, and topology parsing."""
import numpy as np
from detergent_validation.analysis import sugar_ensemble

CENTRES = {'A': np.array([0.5, 0.0, 0.0]), 'B': np.array([0.0, 2.0, 0.0])}
PAIR = frozenset(('A', 'B'))


def test_a_distance_is_measured_between_the_named_beads():
    distances = sugar_ensemble.pair_distances(CENTRES, [('A', 'B')])
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


def test_a_topology_is_read_into_its_sections_without_its_comments():
    table = sugar_ensemble.sections('[ atoms ]\n; a comment\n1 CT 1 LIG C 1 0 12.011\n[ bonds ]\n1 2 1 0.15 1000\n')
    assert table['atoms'][0][:4] == ['1', 'CT', '1', 'LIG']
    assert table['bonds'][0][:2] == ['1', '2']
