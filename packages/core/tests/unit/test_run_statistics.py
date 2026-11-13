"""The per-series statistics a trajectory overview quotes, as arithmetic a person can check by hand.

The contract is the return dictionary, not a plot: the overview lane codes against these keys, so the tests pin each
one on a series short enough to compute in one's head, and pin the honest-standard-error and sampling-independence
claims that make a correlated MD series readable.
"""
import math

import numpy as np
import pytest
from dashboard.analysis.runs.statistics import block_summary, series_summary


def test_the_known_moments_of_a_short_series():
    """values 0..4: mean 2, sample std sqrt(2.5), median 2, linear percentiles 0.2 and 3.8."""
    summary = series_summary([0.0, 1.0, 2.0, 3.0, 4.0])

    assert summary['n'] == 5
    assert summary['mean'] == pytest.approx(2.0)
    assert summary['std'] == pytest.approx(math.sqrt(2.5))
    assert summary['sem'] == pytest.approx(math.sqrt(2.5) / math.sqrt(5))
    assert summary['median'] == pytest.approx(2.0)
    assert summary['p05'] == pytest.approx(0.2)
    assert summary['p95'] == pytest.approx(3.8)
    assert summary['min'] == pytest.approx(0.0)
    assert summary['max'] == pytest.approx(4.0)
    assert summary['first_half_mean'] == pytest.approx(0.5)
    assert summary['second_half_mean'] == pytest.approx(3.0)


def test_every_number_is_a_native_python_number():
    summary = series_summary([1.0, 2.0, 4.0], times_ns=[0.0, 1.0, 2.0])

    for key, value in summary.items():
        assert value is None or type(value) in (int, float), key


def test_a_perfect_line_is_its_own_fit():
    times = [0.0, 1.0, 2.0, 3.0, 4.0]
    summary = series_summary([2.0 * t + 1.0 for t in times], times_ns=times)

    assert summary['slope_per_ns'] == pytest.approx(2.0)
    assert summary['r2'] == pytest.approx(1.0)
    assert summary['rms_from_fit'] == pytest.approx(0.0, abs=1e-9)
    assert summary['slope_stderr'] == pytest.approx(0.0, abs=1e-9)


def test_a_reversed_line_slopes_the_other_way():
    summary = series_summary([9.0, 7.0, 5.0, 3.0, 1.0], times_ns=[0.0, 1.0, 2.0, 3.0, 4.0])

    assert summary['slope_per_ns'] == pytest.approx(-2.0)
    assert summary['slope_stderr'] == pytest.approx(0.0, abs=1e-9)


def test_noise_has_a_finite_slope_with_a_positive_stderr():
    rng = np.random.default_rng(0)
    summary = series_summary(rng.normal(size=50), times_ns=np.arange(50.0))

    assert math.isfinite(summary['slope_per_ns'])
    assert summary['slope_stderr'] is not None and summary['slope_stderr'] > 0.0
    assert 0.0 <= summary['r2'] <= 1.0
    assert math.isfinite(summary['rms_from_fit'])


def test_without_times_the_slope_keys_are_present_and_none():
    summary = series_summary([0.0, 1.0, 2.0, 1.0])

    for key in ('slope_per_ns', 'slope_stderr', 'r2', 'rms_from_fit'):
        assert summary[key] is None, key


def test_a_single_sample_has_no_spread_and_no_fit():
    summary = series_summary([3.5])

    assert summary['n'] == 1
    assert summary['std'] == 0.0
    assert summary['sem'] == 0.0
    assert summary['first_half_mean'] == summary['second_half_mean'] == pytest.approx(3.5)
    assert summary['slope_per_ns'] is None
    assert summary['autocorr_time_samples'] is None
    assert summary['effective_samples'] is None


def test_a_constant_series_has_no_slope_and_no_autocorrelation_time():
    summary = series_summary([5.0] * 20, times_ns=np.arange(20.0))

    assert summary['slope_per_ns'] == 0.0
    assert summary['r2'] is None
    assert summary['slope_stderr'] == 0.0
    assert summary['autocorr_time_samples'] is None
    assert summary['effective_samples'] is None


def test_the_block_sem_is_the_shared_block_summarys_stderr():
    values = [0.1, 0.4, 0.2, 0.9, 0.5, 0.3, 0.8, 0.6, 0.7, 0.25, 0.35, 0.55]
    default = series_summary(values)
    three = series_summary(values, block_count=3)

    assert default['block_sem'] == block_summary(values)['stderr']
    assert three['block_sem'] == block_summary(values, 3)['stderr']
    assert default['blocks'] == block_summary(values)['blocks']
    assert three['blocks'] == block_summary(values, 3)['blocks'] == 3


def test_a_length_mismatch_between_values_and_times_is_refused():
    with pytest.raises(ValueError):
        series_summary([1.0, 2.0, 3.0], times_ns=[0.0, 1.0])


def test_non_finite_values_and_times_are_refused():
    with pytest.raises(ValueError):
        series_summary([1.0, float('nan')])
    with pytest.raises(ValueError):
        series_summary([1.0, 2.0], times_ns=[0.0, float('inf')])
    with pytest.raises(ValueError):
        series_summary([])


def test_an_unstructured_series_is_worth_about_one_frame_each():
    rng = np.random.default_rng(1)
    summary = series_summary(rng.normal(size=200))

    tau = summary['autocorr_time_samples']
    assert tau is not None and math.isfinite(tau)
    assert 0.5 <= tau <= 5.0
    assert summary['effective_samples'] == pytest.approx(200 / (2.0 * tau))


def test_a_correlated_ramp_has_a_long_autocorrelation_time():
    summary = series_summary(np.arange(200.0))

    tau = summary['autocorr_time_samples']
    assert tau is not None and tau > 1.0
    assert summary['effective_samples'] < summary['n']
