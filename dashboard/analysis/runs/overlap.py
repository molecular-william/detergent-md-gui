"""How faithfully a coarse-grained model reproduces its atomistic reference, per bead pair.

The coefficient here is the **overlap coefficient** -- the intersection of two probability densities -- and not the
Bhattacharyya coefficient or a Kullback-Leibler divergence. The three are routinely confused by name, and only the
overlap coefficient is bounded by 1 and symmetric, which is what lets a matrix of it be read as a matrix at all.

The method is shaker's (`Martini-Force-Field-Initiative/shaker`, LGPL-2.1, `shaker/overlap.py`), reimplemented from
its definition rather than imported: the arithmetic is a histogram intersection, and depending on that package would
bring nglview and rdkit -- its whole stack -- for about fifty lines. `docs/design/2026-10-05-shaker-and-taster-
assessment.md` records why, and the comparison that validated this against shaker's own output.
"""
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
