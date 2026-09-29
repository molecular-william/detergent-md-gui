"""Bead displacement: a shape claim that survives a rigid-body fit, and the units it is made in.

Mean bead positions are compared after fitting the coarse-grained ensemble onto the atomistic one on the
beads that own atoms. The cases here are the ones that decide whether the number means anything: a shared
translation must vanish, a virtual site that has drifted must still be visible, and the fixture writes its
trajectory in ångström the way MDAnalysis holds it, so a forgotten conversion fails a test.
"""
import numpy as np
import pytest

from dashboard.analysis.runs import consistency
from tests.dashboard import support

MAPPING = {
    'beads': [
        {'name': 'S1A', 'letter': 'A', 'residue': 1, 'size': 'S', 'type': 'SP1r', 'atoms': [1, 2]},
        {'name': 'S1B', 'letter': 'B', 'residue': 1, 'size': 'S', 'type': 'SP4r', 'atoms': [3, 4]},
        {'name': 'S1C', 'letter': 'C', 'residue': 1, 'size': 'S', 'type': 'SP1r', 'atoms': [5, 6]},
        {'name': 'S1VS', 'letter': 'VS', 'residue': 1, 'size': 'T', 'type': 'TC4', 'atoms': [],
         'virtual_site': {'parents': ['S1A', 'S1B', 'S1C'], 'function': 1}},
    ],
    'rings': [{'beads': ['S1A', 'S1B', 'S1C'], 'scale': 1.15}],
}

POSITIONS = [[0.0, 0.0, 0.0], [0.4, 0.0, 0.0], [0.0, 0.4, 0.0], [0.0, 0.0, 0.0]]


def means(array, beads=None):
    return {'mean': np.asarray(array, dtype=float), 'frames': 3,
            'beads': beads if beads is not None else consistency.mapping_currency(MAPPING)}


def test_a_shared_translation_vanishes_under_the_fit():
    """Both ensembles moved, nothing moved relative to each other: the displacement must be zero."""
    aa = means(POSITIONS)
    cg = means(np.asarray(POSITIONS) + np.array([2.0, -1.0, 0.5]))
    result = consistency.displacement(aa, cg, consistency.physical_indices(MAPPING))
    assert result['rmsd_nm'] < 1e-9 and result['max_nm'] < 1e-9


def test_a_virtual_site_that_moved_is_reported_while_the_physical_beads_agree():
    aa = means(POSITIONS)
    moved = np.asarray(POSITIONS, dtype=float)
    moved[3] = [0.0, 0.0, 0.1]
    result = consistency.displacement(aa, means(moved), consistency.physical_indices(MAPPING))
    assert result['rmsd_nm'] < 1e-9, 'the fit uses the physical beads, which did not move'
    virtual = next(row for row in result['per_bead'] if row['bead'] == [1, 'VS'])
    assert virtual['displacement_nm'] == pytest.approx(0.1, abs=1e-9)


def displacement_after_moving_bead_b(shift):
    """Move the second fitting bead along x by `shift` and compare the two ensembles."""
    moved = np.asarray(POSITIONS, dtype=float)
    moved[1] = [0.4 + shift, 0.0, 0.0]
    return consistency.displacement(means(POSITIONS), means(moved),
                                    consistency.physical_indices(MAPPING))


def test_a_moved_physical_bead_dominates_the_displacement_and_grows_with_the_move():
    """The fit is computed on the fitting beads, so one move is partly absorbed, and it re-solves for each
    perturbation — which is why proportionality is only approximate. What must hold is that the bead that
    moved carries the largest displacement, and that doubling the move roughly doubles the number."""
    small, large = displacement_after_moving_bead_b(0.1), displacement_after_moving_bead_b(0.2)
    assert 0 < small['max_nm'] < large['max_nm']
    assert large['max_nm'] == pytest.approx(2 * small['max_nm'], rel=0.05)
    largest = max(large['per_bead'], key=lambda row: row['displacement_nm'])
    assert largest['bead'] == [1, 'B']


def test_the_fit_lists_the_beads_it_used():
    result = displacement_after_moving_bead_b(0.1)
    assert result['fit_beads'] == [[1, 'A'], [1, 'B'], [1, 'C']]
    assert result['rmsd_nm'] > 0 and result['aa_frames'] == 3 and result['cg_frames'] == 3


def test_different_bead_counts_are_refused_rather_than_fitted():
    aa = means(POSITIONS)
    cg = means(POSITIONS[:3])
    with pytest.raises(ValueError, match='different bead counts'):
        consistency.displacement(aa, cg, consistency.physical_indices(MAPPING))


def test_a_fit_with_no_physical_bead_is_refused():
    with pytest.raises(ValueError, match='at least one bead that owns atoms'):
        consistency.displacement(means(POSITIONS), means(POSITIONS), [])


def test_the_physical_indices_are_the_beads_that_own_atoms():
    assert consistency.physical_indices(MAPPING) == [0, 1, 2]
    assert set(consistency.mapping_currency(MAPPING)) == {1, 2, 3, 4}
    assert set(consistency.mapping_currency(MAPPING, physical_only=True)) == {1, 2, 3}


def test_coarse_grained_mean_positions_are_read_in_nanometres(tmp_path):
    support.cg_fixture_run(tmp_path, POSITIONS, frames=4)
    result = consistency.cg_bead_means(tmp_path)
    assert result['frames'] == 4
    assert np.allclose(result['mean'][0], [0.0, 0.0, 0.0], atol=1e-6)
    assert np.allclose(result['mean'][1], [0.4, 0.0, 0.0], atol=1e-6), 'the trajectory is in ångström'
    assert result['beads'][1] == (1, 'B01'), "the coarse-grained run's own bead id"


def test_coarse_grained_means_refuse_a_trajectory_of_the_wrong_bead_count(tmp_path):
    support.cg_fixture_run(tmp_path, POSITIONS[:3], names=('A', 'B', 'C'), frames=2)
    (tmp_path / 'stages/3_initial_CG/SUCR_initial.itp').write_text(
        (tmp_path / 'stages/3_initial_CG/SUCR_initial.itp').read_text() + '4 SP1r 1 SUCR D 4 0 54\n')
    with pytest.raises(ValueError, match='not the same system'):
        consistency.cg_bead_means(tmp_path)


def test_coarse_grained_means_take_the_frames_the_caller_asked_for(tmp_path):
    support.cg_fixture_run(tmp_path, POSITIONS, frames=5)
    assert consistency.cg_bead_means(tmp_path, limit=2)['frames'] == 2
    assert consistency.cg_bead_means(tmp_path, stride=2)['frames'] == 3
