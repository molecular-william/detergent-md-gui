"""The block-averaged summary two comparisons report: mean, spread and a standard error over blocks.

Both the CG topology comparison and the validation geometry report quote these numbers, so the arithmetic lives in
one place. A block summary is evidence with a stated block count, not a confidence interval: the blocks describe how
the samples were averaged, and the caller's own report says which count it used.
"""
import math

import numpy as np


def block_summary(values, block_count=5):
    values = np.asarray(list(values), dtype=float)
    if values.size == 0 or not np.isfinite(values).all():
        raise ValueError('Geometry values must be finite and non-empty')
    blocks = min(max(1, int(block_count)), values.size)
    block_values = np.array_split(values, blocks)
    means = np.array([block.mean() for block in block_values], dtype=float)
    stderr = float(means.std(ddof=1) / math.sqrt(len(means))) if len(means) > 1 else 0.0
    return {'samples': int(values.size), 'blocks': int(len(means)),
            'mean': float(values.mean()), 'std': float(values.std()), 'stderr': stderr}


def series_summary(values, *, times_ns=None, block_count=5):
    """One sampled series: centre, spread, distribution, halves, drift and sampling independence.

    Values are in the caller's own units and times in ``times_ns`` are nanoseconds, so ``slope_per_ns`` is in
    values per nanosecond. The standard error of the mean (``sem``) treats the samples as independent; MD frames are
    correlated, so ``block_sem`` -- the standard error of the block means from :func:`block_summary` -- is the honest
    standard error for a correlated MD series, and ``block_sem`` is what a report should quote. The least-squares
    slope is descriptive (a drift the series shows); it is not a convergence proof and says nothing about whether the
    run has equilibrated. ``autocorr_time_samples`` is the integrated autocorrelation time in frames, and
    ``effective_samples`` is how many independent frames the series is worth.

    Every number returned is a native ``float`` or ``int``, or ``None`` where the series cannot support it, so the
    caller decides the rounding it prints. ``times_ns`` must be the same length as ``values`` and finite; the times
    need not be strictly increasing (a repeated time simply contributes no leverage to the slope).
    """
    values = np.asarray(list(values), dtype=float)
    if values.size == 0 or not np.isfinite(values).all():
        raise ValueError('Series values must be finite and non-empty')
    n = int(values.size)
    mean = float(values.mean())
    std = float(values.std(ddof=1)) if n > 1 else 0.0
    sem = std / math.sqrt(n) if n > 1 else 0.0
    blocks = block_summary(values, block_count)
    if n < 2:
        first_half_mean = second_half_mean = mean
    else:
        split = n // 2
        first_half_mean = float(values[:split].mean())
        second_half_mean = float(values[split:].mean())

    slope_per_ns = slope_stderr = r2 = rms_from_fit = None
    if times_ns is not None:
        times = np.asarray(list(times_ns), dtype=float)
        if times.size != n:
            raise ValueError('Series times must have the same length as the values')
        if not np.isfinite(times).all():
            raise ValueError('Series times must be finite')
        centred_times = times - times.mean()
        centred_values = values - mean
        sxx = float(np.dot(centred_times, centred_times))
        sxy = float(np.dot(centred_times, centred_values))
        slope_per_ns = sxy / sxx if sxx > 0.0 and n > 1 else 0.0
        residual = values - (mean + slope_per_ns * centred_times)
        sum_squares_residual = float(np.dot(residual, residual))
        sum_squares_total = float(np.dot(centred_values, centred_values))
        rms_from_fit = float(np.sqrt(np.mean(residual ** 2)))
        r2 = None if sum_squares_total == 0.0 or sxx == 0.0 else float(1.0 - sum_squares_residual / sum_squares_total)
        if n >= 3 and sxx > 0.0:
            slope_stderr = float(math.sqrt(sum_squares_residual / (n - 2)) / math.sqrt(sxx))

    autocorr_time_samples = effective_samples = None
    if n >= 4 and std > 0.0:
        centred = values - mean
        size = 1 << (2 * n - 1).bit_length()
        spectrum = np.fft.rfft(centred, size)
        autocovariance = np.fft.irfft(spectrum * np.conj(spectrum), size)[:n]
        rho = autocovariance / autocovariance[0]
        tau = 1.0
        for k in range(1, n // 2 + 1):
            if rho[k] <= 0.0:
                break
            tau += 2.0 * float(rho[k])
        autocorr_time_samples = float(tau)
        effective_samples = float(n / (2.0 * tau))

    return {
        'n': n,
        'mean': mean,
        'std': std,
        'sem': float(sem),
        'block_sem': float(blocks['stderr']),
        'blocks': int(blocks['blocks']),
        'median': float(np.median(values)),
        'p05': float(np.percentile(values, 5)),
        'p95': float(np.percentile(values, 95)),
        'min': float(values.min()),
        'max': float(values.max()),
        'first_half_mean': first_half_mean,
        'second_half_mean': second_half_mean,
        'slope_per_ns': slope_per_ns,
        'slope_stderr': slope_stderr,
        'r2': r2,
        'rms_from_fit': rms_from_fit,
        'autocorr_time_samples': autocorr_time_samples,
        'effective_samples': effective_samples,
    }
