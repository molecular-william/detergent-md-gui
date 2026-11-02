"""Selection: exactly K, distinct, deterministic, covering the pool's range, and refused when the pool is short.

The library's identity is its bytes, so the selection cannot depend on anything but the pool and K. These tests pin
that: two calls agree, the count is exact, the picks are distinct, and a K wider than the pool is a refusal naming
both numbers rather than a library that quietly shrank.
"""
import numpy as np
import pytest
from detergent_pdc.conformations import stratified


def ramp(count=600):
    """A pool whose only varying descriptor is the first, so the median split is a clear one-dimensional case."""
    values = np.zeros((count, 4))
    values[:, 0] = np.linspace(0.0, 1.0, count)
    return values


def test_exactly_k_distinct():
    pool = np.random.default_rng(7).random((500, 4))
    chosen = stratified(pool, 64)
    assert len(chosen) == 64
    assert len(set(chosen)) == 64
    assert chosen == sorted(chosen)
    assert all(0 <= index < len(pool) for index in chosen)


def test_deterministic_for_one_pool():
    pool = np.random.default_rng(11).random((400, 4))
    assert stratified(pool, 40, seed=0) == stratified(pool, 40, seed=0)
    assert stratified(pool, 40, seed=0) == stratified(pool, 40, seed=9), 'the method draws nothing'


def test_spans_the_descriptor_range():
    """One descriptor varies; the picks reach into the first and last cell, not just the middle of the pool."""
    chosen = stratified(ramp(), 60)
    selected = ramp()[chosen, 0]
    assert selected.min() <= 0.05
    assert selected.max() >= 0.95
    assert selected.max() - selected.min() >= 0.9


def test_pool_smaller_than_size_is_refused():
    with pytest.raises(ValueError) as error:
        stratified(np.zeros((5, 4)), 6)
    assert '5 candidates' in str(error.value) and '6 asked for' in str(error.value)


def test_identical_descriptors_still_split():
    """A zero interquartile range is a spread of one, not a division by zero: the pool can still supply K."""
    chosen = stratified(np.zeros((100, 4)), 10)
    assert len(chosen) == 10
    assert len(set(chosen)) == 10


def test_size_one_and_size_equal_to_the_pool():
    pool = np.random.default_rng(3).random((30, 4))
    assert len(stratified(pool, 1)) == 1
    assert stratified(pool, 30) == list(range(30))


def test_bad_arguments_are_named():
    pool = np.zeros((10, 4))
    with pytest.raises(ValueError, match='size must be an integer'):
        stratified(pool, 0)
    with pytest.raises(ValueError, match='size must be an integer'):
        stratified(pool, True)
    with pytest.raises(ValueError, match=r'\(n, 4\)'):
        stratified(np.zeros((10, 3)), 2)
    with pytest.raises(ValueError, match='non-finite'):
        stratified(np.full((10, 4), np.nan), 2)
