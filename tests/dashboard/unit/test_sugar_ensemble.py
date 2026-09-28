"""The ensemble arithmetic: bead centres, distances, spread, and the comparison with the published values.

These are the numbers the 200 ns run exists to produce, so they are pinned without needing a trajectory: the shell
that reads one only fills the dictionary the samples arrive in.
"""
import numpy as np

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
    row = sugar_ensemble.compare({PAIR: 0.45}, {PAIR: [0.40, 0.50]}, {PAIR: 0.415})[0]
    assert np.isclose(row['single_frame_nm'], 0.415)


def test_an_unconstrained_pair_is_reported_as_unconstrained_rather_than_compared():
    row = sugar_ensemble.compare({}, {PAIR: [0.40]})[0]
    assert row['unconstrained'] is True
    assert row['delta_pct'] is None
