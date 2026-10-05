"""How faithfully a coarse-grained model reproduces its atomistic reference, per bead pair.

The coefficient here is the **overlap coefficient** -- the intersection of two probability densities -- and not the
Bhattacharyya coefficient or a Kullback-Leibler divergence. The three are routinely confused by name, and only the
overlap coefficient is bounded by 1 and symmetric, which is what lets a matrix of it be read as a matrix at all.

The method is shaker's (`Martini-Force-Field-Initiative/shaker`, LGPL-2.1, `shaker/overlap.py`), reimplemented from
its definition rather than imported: the arithmetic is a histogram intersection, and depending on that package would
bring nglview and rdkit -- its whole stack -- for about fifty lines. `docs/design/2026-10-05-shaker-and-taster-
assessment.md` records why, and the comparison that validated this against shaker's own output.
"""
import itertools

import numpy as np


def overlap_coefficient(histogram_a, histogram_b, bins):
    """The overlap coefficient of two densities over the same bins: `sum(min(a, b)) * bin_width`.

    Both sides must be densities (`numpy.histogram(..., density=True)`), not counts: the coefficient is the shared
    *probability*, so counts answer a different question and inflate with the sample size. The two are required to
    have the same shape rather than being broadcast, because a comparison between different bin sets reads exactly
    like a comparison between the same one.
    """
    a = np.asarray(histogram_a, dtype=float)
    b = np.asarray(histogram_b, dtype=float)
    edges = np.asarray(bins, dtype=float)
    if edges.size < 2:
        raise ValueError('an overlap needs at least two bin edges to read a width from')
    if a.shape != b.shape:
        raise ValueError(f'both sides must be measured on the same bins, not {a.shape} against {b.shape}')
    if a.size != edges.size - 1:
        raise ValueError(f'{a.size} values cannot be read against {edges.size - 1} bins')
    return float(np.sum(np.minimum(a, b)) * (edges[1] - edges[0]))


def intra_bead_distances(universe, residue_name, *, bead_names=None, start=0, stop=None, stride=1, bins=None,
                         bin_count=40):
    """Every pairwise intra-residue bead distance, histogrammed as a density.

    Returns the bead names, the pairs, the bins, one density histogram per pair (`hist`, in `pairs` order), the mean
    distance per pair in nanometres, how many frames contributed, and how many copies of the residue were resolved.

    **One bin range has to cover both sides.** A histogram whose range stops at the reference's longest distance drops
    every coarse-grained distance beyond it, and a dropped sample reads as a model that does not overlap rather than
    as a range that was too short. So the caller derives one range covering both ensembles and passes it in; passing
    nothing derives it from this side alone, which is right for a single measurement and wrong for a comparison.

    Distances are nanometres. MDAnalysis reports angstroms, and the conversion happens here rather than at each
    reader: a beads file read in angstroms is a factor-of-ten error that looks like a model that is merely loose.
    """
    residues = universe.select_atoms(f'resname {residue_name}').residues
    if not len(residues):
        raise ValueError(f'no residue named {residue_name} in this trajectory')
    available = list(residues[0].atoms.names)
    names = list(bead_names) if bead_names else list(dict.fromkeys(available))
    missing = [name for name in names if name not in available]
    if missing:
        raise ValueError(f'{residue_name} has no bead named {", ".join(missing)}; it has {", ".join(available)}')
    pairs = list(itertools.combinations(names, 2))
    if not pairs:
        raise ValueError('an overlap needs at least two beads before there is a pair to measure')
    position = {name: i for i, name in enumerate(available)}
    wanted = [position[name] for name in names]
    endpoints = [(names.index(a), names.index(b)) for a, b in pairs]

    frames = list(range(*slice(start, stop, stride).indices(len(universe.trajectory))))
    series = {pair: [] for pair in pairs}
    for frame in frames:
        universe.trajectory[frame]
        for residue in residues:
            # MDAnalysis reports angstroms; every length in this repository is nanometres.
            positions = np.asarray(residue.atoms.positions, dtype=float)[wanted] / 10.0
            for pair, (i, j) in zip(pairs, endpoints):
                series[pair].append(float(np.linalg.norm(positions[i] - positions[j])))

    values = [np.asarray(series[pair], dtype=float) for pair in pairs]
    if bins is None:
        longest = max(float(value.max()) for value in values if value.size)
        bins = np.linspace(0.0, longest or 1.0, bin_count + 1)
    edges = np.asarray(bins, dtype=float)
    if edges.size < 2 or np.any(np.diff(edges) <= 0):
        raise ValueError('bins must be increasing edges, or the density cannot be read')
    histogram = np.vstack([np.histogram(value, bins=edges, density=True)[0] for value in values])
    if not np.isfinite(histogram).all():
        # A pair whose distance never varies over a zero-width range: refused here rather than carried into a
        # coefficient as a nan, which would silently poison a whole matrix cell.
        raise ValueError('a pair has no measurable spread over these bins')
    return {'bead_names': names, 'pairs': pairs, 'bins': edges, 'hist': histogram,
            'mean_nm': [float(value.mean()) for value in values],
            'frames': len(frames), 'residues': len(residues)}
