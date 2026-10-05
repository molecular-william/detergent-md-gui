"""The overlap coefficient, pinned as arithmetic on values that can be checked by hand.

A number called "overlap" invites at least three readings -- the overlap coefficient (the histogram intersection),
the Bhattacharyya coefficient, and the Kullback-Leibler divergence -- and they are different numbers. Only the first
is bounded by 1 and symmetric, which is what lets a matrix of it be read at all. So the tests pin which one this is,
including a case where two of them disagree by a factor of two.
"""
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
