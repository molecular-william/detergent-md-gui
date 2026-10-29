"""The overlap coefficient, pinned as arithmetic on values that can be checked by hand.

A number called "overlap" invites at least three readings -- the overlap coefficient (the histogram intersection),
the Bhattacharyya coefficient, and the Kullback-Leibler divergence -- and they are different numbers. Only the first
is bounded by 1 and symmetric, which is what lets a matrix of it be read at all. So the tests pin which one this is,
including a case where two of them disagree by a factor of two.
"""
import pathlib

import MDAnalysis as mda
import numpy as np
import pytest
from dashboard.analysis.runs import overlap

BINS = np.array([0.0, 0.1, 0.2])            # one 0.1-wide bin each side of a boundary


def test_a_distribution_against_itself_overlaps_completely():
    """Densities, not counts: this is what makes the matrix's diagonal meaningful."""
    counts = np.array([1.0, 2.0, 3.0, 2.0, 1.0])
    bins = np.array([0.0, 0.1, 0.2, 0.3, 0.4, 0.5])
    density = counts / (counts.sum() * 0.1)

    assert overlap.overlap_coefficient(density, density, bins) == pytest.approx(1.0)


def test_distributions_with_no_bin_in_common_do_not_overlap():
    a = np.array([10.0, 0.0, 0.0, 0.0])
    b = np.array([0.0, 0.0, 0.0, 10.0])

    assert overlap.overlap_coefficient(a, b, np.array([0.0, 0.1, 0.2, 0.3, 0.4])) == 0.0


def test_the_coefficient_is_the_shared_mass():
    """Hand-computable: both are densities over the same bin, and they share exactly half of theirs."""
    a = np.array([5.0, 5.0])
    b = np.array([10.0, 0.0])

    assert overlap.overlap_coefficient(a, b, BINS) == pytest.approx(0.5)


def test_it_is_not_the_bhattacharyya_coefficient():
    """Two densities that agree on nothing but their total: overlap 0.4, Bhattacharyya 0.8 -- so a reader who
    assumes the other reading is looking at a number twice the size, and would call a poor model a good one."""
    a = np.array([8.0, 2.0])
    b = np.array([2.0, 8.0])

    assert overlap.overlap_coefficient(a, b, BINS) == pytest.approx(0.4)


def test_histograms_of_different_shapes_are_refused_rather_than_broadcast():
    """Silent broadcasting is how a comparison of two different pair sets reads as a comparison of one."""
    with pytest.raises(ValueError, match='same bins'):
        overlap.overlap_coefficient(np.array([1.0, 0.0]), np.array([1.0, 0.0, 0.0]), BINS)


def test_an_empty_or_single_bin_histogram_is_refused():
    """A bin width cannot be read from one edge, and a comparison needs at least one bin to compare."""
    with pytest.raises(ValueError, match='at least two bin edges'):
        overlap.overlap_coefficient(np.array([1.0]), np.array([1.0]), np.array([0.0]))


def test_values_that_do_not_match_the_bin_count_are_refused():
    """Three edges describe two bins: a third value has nowhere to sit, and summing it would read as a wider sample."""
    with pytest.raises(ValueError, match='3 values cannot be read against 2 bins'):
        overlap.overlap_coefficient(np.array([1.0, 1.0, 1.0]), np.array([1.0, 1.0, 1.0]), BINS)


# --- the measurement -------------------------------------------------------------------------------------------

def _bead_universe(frames):
    """A one-residue, three-bead universe whose bead distances are round numbers in nm."""
    universe = mda.Universe.empty(3, n_residues=1, atom_resindex=[0, 0, 0], trajectory=True)
    universe.add_TopologyAttr('names', ['B01', 'B02', 'B03'])
    universe.add_TopologyAttr('resnames', ['DDM'])
    universe.add_TopologyAttr('resids', [1])
    with mda.Writer(str(pathlib.Path.cwd() / 'beads.xtc'), n_atoms=3) as writer:
        for index, positions in enumerate(frames):
            universe.atoms.positions = positions
            universe.trajectory.ts.time = float(index)
            if index == 0:
                universe.atoms.write('beads.gro')
            writer.write(universe.atoms)
    return 'beads.gro', 'beads.xtc'


def _run_directory(tmp_path, aa_frames, cg_frames):
    """The three files the analysis reads, staged as the worker stages them: a reference, a model, a CG trajectory."""
    import json
    work = tmp_path / 'work'
    for name, frames in (('1_AA-reference/prod/lig', aa_frames), ('4_CG_sim/prod/lig_CG', cg_frames)):
        directory = work / pathlib.Path(name).parent
        directory.mkdir(parents=True, exist_ok=True)
        universe = mda.Universe.empty(3, n_residues=1, atom_resindex=[0, 0, 0], trajectory=True)
        universe.add_TopologyAttr('names', ['B01', 'B02', 'B03'])
        universe.add_TopologyAttr('resnames', ['DDM'])
        universe.add_TopologyAttr('resids', [1])
        with mda.Writer(str(directory / f'{pathlib.Path(name).name}.xtc'), n_atoms=3) as writer:
            for index, positions in enumerate(frames):
                universe.atoms.positions = positions
                universe.trajectory.ts.time = float(index)
                if index == 0:
                    universe.atoms.write(str(directory / f'{pathlib.Path(name).name}.gro'))
                writer.write(universe.atoms)
    (work / '2_mapping').mkdir(parents=True, exist_ok=True)
    (work / '2_mapping/model.json').write_text(json.dumps(
        {'beads': [{'export_name': name} for name in ('B01', 'B02', 'B03')], 'molecule_id': 'DDM'}))
    return work


# Beads on a line: B01 at 0, B02 at a, B03 at b -- so the pairs are a, b and b - a.
AGREEING = np.array([[[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [5.0, 0.0, 0.0]]], dtype=np.float32)
STRAYED = np.array([[[0.0, 0.0, 0.0], [6.0, 0.0, 0.0], [5.0, 0.0, 0.0]]], dtype=np.float32)


def test_a_side_reports_its_own_range_so_one_range_can_cover_both(tmp_path, monkeypatch):
    """The range is what lets the caller build bins spanning both ensembles, which is the only way the two
    histograms are comparable. It is reported rather than only used internally, because the union needs both sides."""
    monkeypatch.chdir(tmp_path)
    topology, trajectory = _bead_universe(FRAMES)
    measured = overlap.intra_bead_distances(mda.Universe(topology, trajectory), 'DDM')

    assert measured['range_nm'] == (0.2, 0.6)


# --- publishing ------------------------------------------------------------------------------------------------

def test_a_model_that_agrees_with_its_reference_overlaps_on_every_pair(tmp_path):
    work = _run_directory(tmp_path, AGREEING, AGREEING)
    report = overlap.publish(work)

    assert report['bead_names'] == ['B01', 'B02', 'B03']
    assert report['overlaps'] == pytest.approx([1.0, 1.0, 1.0])
    assert report['frames'] == {'reference': 1, 'model': 1}


def test_pairs_that_moved_into_different_bins_score_zero_and_the_rest_one(tmp_path):
    """Hand-checkable: the reference is 0.2, 0.5, 0.3 nm and the model 0.6, 0.5, 0.1 -- so the two pairs that stayed
    in their bin overlap completely and the two that moved share nothing."""
    work = _run_directory(tmp_path, AGREEING, STRAYED)
    report = overlap.publish(work)

    assert report['overlaps'] == pytest.approx([0.0, 1.0, 0.0])
    # The range spans both ensembles: 0.1 nm (the model's shortest) to 0.6 nm (the model's longest), not 0.2 to 0.5.
    assert (report['bins'][0], report['bins'][-1]) == pytest.approx((0.1, 0.6))


def test_the_report_carries_what_a_reader_needs_to_disagree_with_it(tmp_path):
    """"Agreement" without the pair set, the binning and the ensembles named is a number nobody can check."""
    work = _run_directory(tmp_path, AGREEING, STRAYED)
    report = overlap.publish(work)

    assert report['pairs'] == [['B01', 'B02'], ['B01', 'B03'], ['B02', 'B03']]
    assert len(report['bins']) == 41
    assert report['residue'] == 'DDM'
    assert report['trajectories']['reference']['frames'] == 1
    assert report['trajectories']['model']['frames'] == 1
    assert any('intra-residue' in line.lower() for line in report['limitations'])
    assert any('one bin range' in line.lower() for line in report['limitations'])
    assert report['scientifically_validated'] is False


def test_the_figure_is_written_and_named_by_the_report(tmp_path):
    """A self-contained file the run-artifact route can serve inline, named by the record rather than guessed."""
    work = _run_directory(tmp_path, AGREEING, STRAYED)
    report = overlap.publish(work)

    figure = work / report['figure']
    assert figure.is_file() and figure.stat().st_size > 1000
    assert '<html' in figure.read_text()[:2000].lower()


# Frame 0: B01-B02 0.2 nm, B01-B03 0.5 nm, B02-B03 0.3 nm.  Frame 1: 0.3, 0.6, 0.3 nm.
FRAMES = np.array([[[0.0, 0.0, 0.0], [0.0, 0.0, 2.0], [0.0, 0.0, 5.0]],
                   [[0.0, 0.0, 0.0], [0.0, 0.0, 3.0], [0.0, 0.0, 6.0]]], dtype=np.float32)


def test_every_intra_residue_pair_is_measured_in_nanometres(tmp_path, monkeypatch):
    """Angstroms in the file, nanometres in every builder here -- the conversion is asserted, not assumed."""
    monkeypatch.chdir(tmp_path)
    topology, trajectory = _bead_universe(FRAMES)
    measured = overlap.intra_bead_distances(mda.Universe(topology, trajectory), 'DDM',
                                            bins=np.arange(0.0, 0.8, 0.1))

    assert measured['bead_names'] == ['B01', 'B02', 'B03']
    assert measured['pairs'] == [('B01', 'B02'), ('B01', 'B03'), ('B02', 'B03')]
    assert measured['frames'] == 2
    assert [round(mean, 6) for mean in measured['mean_nm']] == [0.25, 0.55, 0.3]


def test_the_histograms_are_densities_over_the_bins_it_was_given(tmp_path, monkeypatch):
    """Density, not counts: the coefficient is the shared probability, so the histograms must integrate to 1."""
    monkeypatch.chdir(tmp_path)
    topology, trajectory = _bead_universe(FRAMES)
    bins = np.arange(0.0, 0.8, 0.1)
    measured = overlap.intra_bead_distances(mda.Universe(topology, trajectory), 'DDM', bins=bins)

    assert measured['hist'].shape == (3, 7)
    assert np.allclose(measured['hist'].sum(axis=1) * 0.1, 1.0)


def test_a_bead_name_the_residue_does_not_have_is_refused(tmp_path, monkeypatch):
    """A missing bead would otherwise drop out of the pairs silently, shrinking the sample and hiding the reason."""
    monkeypatch.chdir(tmp_path)
    topology, trajectory = _bead_universe(FRAMES)
    with pytest.raises(ValueError, match='B99'):
        overlap.intra_bead_distances(mda.Universe(topology, trajectory), 'DDM', bead_names=['B01', 'B99'])


def test_a_residue_name_the_trajectory_does_not_have_is_refused(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    topology, trajectory = _bead_universe(FRAMES)
    with pytest.raises(ValueError, match='no residue named LIG'):
        overlap.intra_bead_distances(mda.Universe(topology, trajectory), 'LIG')


# --- the matrix ------------------------------------------------------------------------------------------------

def _measured(pairs, histograms, histogram_bins, names=None):
    """A measurement as `intra_bead_distances` returns it, built by hand so the matrix's arithmetic is the subject."""
    return {'bead_names': names or ['B01', 'B02', 'B03'], 'pairs': pairs, 'bins': histogram_bins,
            'hist': np.array(histograms, dtype=float), 'mean_nm': [0.0] * len(pairs), 'frames': 2, 'residues': 1}


PAIR_BINS = np.array([0.0, 0.1, 0.2])
SHARED = np.array([10.0, 0.0])           # a density: 10 per nm over a 0.1 nm bin
DISJOINT = np.array([0.0, 10.0])
PAIRS = [('B01', 'B02'), ('B01', 'B03'), ('B02', 'B03')]


def test_a_model_that_matches_the_reference_overlaps_everywhere():
    reference = _measured(PAIRS, [SHARED] * 3, PAIR_BINS)
    result = overlap.overlap_matrix(reference, reference)

    assert result['matrix'].shape == (3, 3)
    assert np.allclose(result['matrix'], 1.0)              # the diagonal included: it is 1 by construction
    assert result['overlaps'] == pytest.approx([1.0, 1.0, 1.0])


def test_the_matrix_is_symmetric_and_only_the_disagreeing_pair_falls():
    model = _measured(PAIRS, [SHARED, DISJOINT, SHARED], PAIR_BINS)
    reference = _measured(PAIRS, [SHARED] * 3, PAIR_BINS)

    matrix = overlap.overlap_matrix(reference, model)['matrix']

    assert matrix[0, 1] == matrix[1, 0] == pytest.approx(1.0)
    assert matrix[0, 2] == matrix[2, 0] == pytest.approx(0.0)
    assert matrix[1, 2] == matrix[2, 1] == pytest.approx(1.0)
    assert np.allclose(np.diag(matrix), 1.0)


def test_each_beads_mean_leaves_its_own_diagonal_out():
    """A bead's own cell is 1 by construction, so leaving it in would lift every mean by the same amount and hide
    exactly the difference between a bead whose pairs agree and one whose pairs do not."""
    model = _measured(PAIRS, [SHARED, DISJOINT, SHARED], PAIR_BINS)
    reference = _measured(PAIRS, [SHARED] * 3, PAIR_BINS)

    means = {entry['bead']: entry['mean'] for entry in overlap.overlap_matrix(reference, model)['per_bead_mean']}

    assert means == pytest.approx({'B01': 0.5, 'B02': 1.0, 'B03': 0.5})    # B01 meets the disjoint pair, B02 does not


def test_two_sides_measured_over_different_pairs_are_refused():
    """Intersecting would compare a subset of the pairs and report it under the whole name."""
    reference = _measured(PAIRS, [SHARED] * 3, PAIR_BINS)
    fewer = _measured([('B01', 'B02')], [SHARED], PAIR_BINS)

    with pytest.raises(ValueError, match='same pairs'):
        overlap.overlap_matrix(reference, fewer)


def test_two_sides_measured_over_different_bins_are_refused():
    reference = _measured(PAIRS, [SHARED] * 3, PAIR_BINS)
    wider = _measured(PAIRS, [SHARED] * 3, np.array([0.0, 0.1, 0.2, 0.3]))

    with pytest.raises(ValueError, match='same bins'):
        overlap.overlap_matrix(reference, wider)


def test_two_sides_naming_different_beads_are_refused():
    reference = _measured(PAIRS, [SHARED] * 3, PAIR_BINS)
    renamed = _measured(PAIRS, [SHARED] * 3, PAIR_BINS, names=['B01', 'B02', 'B04'])

    with pytest.raises(ValueError, match='same beads'):
        overlap.overlap_matrix(reference, renamed)
