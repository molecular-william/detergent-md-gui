"""The AA reference a CG run's pairwise score is measured against: its name, its grid, and that it scores.

`ff_assess` never makes this reference. `fast_forward/score.py` asks for
`f'{resid1}_{name1}_{resid2}_{name2}_distances_distr.dat'` per bead pair out of the directory it is handed as `-d`, and
when the file is missing it `continue`s -- leaving that cell of the matrix at its 0.00 default, which reads "identical".
`ff_inter -dists -dist-matrix` is what writes the family while the fit runs, through the tool's own
`interaction_distribution`, on the tool's own `distances` bins.

Three things are therefore pinned here, because a plausible-looking substitute is worse than a missing file: the
invocation that produces the family, the shape a pair reference must have (the tool's bins, not the fit's bonded bins),
and that a matrix built from such references actually compares -- not the all-zeros matrix of a run that was never scored.
"""
from pathlib import Path

import MDAnalysis as mda
import numpy as np
from dashboard.models.bonded import parameterization
from vermouth.molecule import Molecule

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# The tool's own grid, taken from the copy the project's tools resolve to rather than restated here: `score.py` and
# `calc_score` both read it, and a reference saved on any other grid is a different measurement of the same thing.
from fast_forward.interaction_distribution import INTERACTIONS, interaction_distribution  # noqa: E402
from fast_forward.score import calc_score, score_matrix  # noqa: E402

from tests.dashboard.support import PACKAGE

DISTANCE_BINS = INTERACTIONS['distances']['bins']
NAMES = ('B01', 'B02', 'B03')


def universe(offset=0.0, seed=0, frames=200):
    """One three-bead molecule as the tool reads it: positions per frame, `moltype` for `find_mol_indices`."""
    rng = np.random.default_rng(seed)
    built = mda.Universe.empty(len(NAMES), n_frames=frames, trajectory=True,
                               atom_resindex=[0] * len(NAMES))
    built.add_TopologyAttr('names', list(NAMES))
    built.add_TopologyAttr('resids', [1])
    built.add_TopologyAttr('resnames', ['DDM'])
    built.add_TopologyAttr('moltypes', ['DDM'])
    built.add_TopologyAttr('molnums', [0])
    base = np.array([[0.0, 0.0, 0.0], [0.5, 0.0, 0.0], [0.0, 0.9, 0.0]]) + offset
    built.trajectory.coordinate_array = base[None, :, :] + np.cumsum(rng.normal(0, 0.02, (frames, 3, 3)), axis=0)
    return built


def block():
    """The topology half of the contract: atom names per node, and the residue each node belongs to."""
    built = Molecule()
    for index, name in enumerate(NAMES):
        built.add_node(index, atomname=name, resid=1)
    return built


def pair_names():
    return [f'1_{first}_1_{second}' for index, first in enumerate(NAMES) for second in NAMES[index + 1:]]


def write_references(directory, source):
    """Every pair's reference, written the way a fit writes them: the tool's writer, its bins, its file names."""
    written = {}
    for first, second in ((0, 1), (0, 2), (1, 2)):
        group = f'1_{NAMES[first]}_1_{NAMES[second]}'
        interaction_distribution(source, 'distances', [np.array([first, second])],
                                group_name=group, prefix='', save=str(directory))
        written[f'{group}_distances_distr.dat'] = Path(directory) / f'{group}_distances_distr.dat'
    return written


def test_the_tools_writer_names_the_pair_family_and_saves_it_on_its_own_bins(tmp_path):
    """The reference is the tool's file: `<resid>_<name>_<resid>_<name>_distances_distr.dat` over 600 edges.

    `np.histogram` with an edge array returns one bin fewer than it has edges, so a pair reference carries
    `len(bins) - 1` rows -- 599 for `np.arange(0, 30, 0.05)`. A hand-rolled histogram with 600 rows, or the fit's
    bonded grid (`np.arange(0, 7, 0.01)`), is a different array, and `calc_score` compares it against 599 bin centres.
    """
    written = write_references(tmp_path, universe())

    assert sorted(written) == sorted(f'{name}_distances_distr.dat' for name in pair_names())
    reference = np.genfromtxt(written['1_B01_1_B02_distances_distr.dat'])
    assert reference.shape == (len(DISTANCE_BINS) - 1, 2)
    assert reference.shape[0] == 599
    assert np.allclose(reference.T[0], (DISTANCE_BINS[:-1] + np.diff(DISTANCE_BINS) / 2)), \
        'the x column is the tool\'s own bin centres, which is what `calc_score` weights against'
    assert np.isclose(reference.T[1].sum() * np.diff(DISTANCE_BINS)[0], 1.0), 'a density, as `density=True` writes it'


def test_the_pair_family_is_recognised_and_the_bonded_family_is_not():
    """What separates a scorable revision from one that only looks like a baseline, decided by name alone."""
    assert parameterization.PAIR_DISTRIBUTION.match('1_B01_1_B11_distances_distr.dat')
    assert not parameterization.PAIR_DISTRIBUTION.match('B01_B11_bonds_distr.dat'), \
        'the fit writes bonds and angles without a residue; they are not pair references'
    assert not parameterization.PAIR_DISTRIBUTION.match('B01_B02_B05_angles_distr.dat')
    assert not parameterization.PAIR_DISTRIBUTION.match('1_B01_1_B02_distances.dat'), \
        'the raw time series is not a distribution'
    assert parameterization.PAIR_DISTRIBUTION.match('1_B09_1_B10_distances_distr.dat')


def test_a_matrix_built_from_those_references_compares_instead_of_staying_zero(tmp_path):
    """The score the run exists to take: 0.00 for the same ensemble, non-zero for a displaced one.

    This is the difference the missing family made. With it, `score_matrix` fills the cells and `plot_data` carries
    every pair, so the distance-distribution figure has data. Without it every cell keeps its 0.00 default and the
    figure is empty -- a perfect score for a comparison that never happened.
    """
    reference_universe = universe()
    written = write_references(tmp_path, reference_universe)

    same, same_plot = score_matrix('DDM', block(), reference_universe, written, '')
    assert np.array_equal(same, np.zeros_like(same)), 'an identical ensemble scores 0.00 -- and only because it compared'
    assert sorted(same_plot['distances']) == pair_names(), 'every pair has reference and simulated data to plot'

    displaced, _ = score_matrix('DDM', block(), universe(offset=1.5, seed=1), written, '')
    assert displaced.max() > 0.1, 'a displaced ensemble is not identical, so the matrix is not all zeros'
    assert np.array_equal(displaced, displaced.T), 'the matrix is symmetric'

    # The scorer's own floor and ceiling, on the arrays the reference file carries.
    reference = np.genfromtxt(written['1_B01_1_B02_distances_distr.dat']).T[1]
    shifted = np.roll(reference, 40)
    assert calc_score(reference, reference) == 0.0
    assert calc_score(reference, shifted) > 0.0


def test_the_fit_script_asks_ff_inter_for_both_families():
    """Where the reference comes from: `ff_inter`'s own writer, asked for by the script a fit runs.

    Both switches are needed -- `-dists` decides that anything is saved, `-dist-matrix` that the pairwise family is
    measured at all -- and neither is `ff_assess`'s to invent. A script that drops one leaves stage 5 with a matrix of
    0.00, so the invocation is pinned beside the shape it must produce.
    """
    executable = [line for line in (PACKAGE / 'execution/scripts/fit_topology.sh').read_text().splitlines()
                  if not line.lstrip().startswith('#')]
    invocation = [line for line in executable if line.startswith('ff_inter ')]

    assert invocation, 'the fit script runs `ff_inter`'
    assert '-dist-matrix' in invocation[0], 'stage 5 builds its score matrix from this family'
    assert '-dists' in invocation[0], 'without `-dists` the tool saves no distribution at all'
