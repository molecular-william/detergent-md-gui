"""Fit a torsional potential from a dihedral's distribution, and let a criterion choose how many terms it needs.

Reimplemented from the method shaker documents and uses (Martini-Force-Field-Initiative/shaker, commit `b7680219`,
LGPL-2.1): inverted Boltzmann, Savitzky-Golay smoothing, a cosine series, and AIC/BIC over the number of terms. This
is **our own implementation of that workflow**, written from the documented method rather than copied from their
source, and shaker is credited in `CREDITS.md` and cited here as the reference implementation.

The series is fitted as `c + sum_n [a_n cos(n phi) + b_n sin(n phi)]`, which is linear in its coefficients and so is a
least-squares problem rather than an optimisation. GROMACS writes a proper dihedral as `k (1 + cos(n phi - phi_s))`,
the same function with `k_n = hypot(a_n, b_n)` and `phi_s = atan2(b_n, a_n)`; both are reported, so the numbers can go
into a topology without anyone re-deriving the conversion.

**Angles are degrees in, degrees out, and radians in between.** GROMACS takes degrees and the trigonometry needs
radians; the conversion happens at the boundary and the reported unit travels with the number, because that mix-up is
invisible in the output -- the same trap the equipartition estimator carries for its angular force constants.

The potential of mean force has no absolute zero, so it is reported with its minimum subtracted and that minimum
recorded: a reader comparing two fits needs to know that the offset is a convention and not a measurement.
"""
import numpy as np

R_GAS = 8.314462618  # J / mol / K
DEFAULT_BINS = 60
DEFAULT_WINDOW = 9
DEFAULT_ORDER = 3
DEFAULT_MAX_TERMS = 6
CRITERIA = ('aic', 'bic')


def inverted_boltzmann(angles_deg, temperature, *, bins=DEFAULT_BINS):
    """The potential of mean force of a dihedral, `-R T ln p`, on a uniform grid over one period.

    Bins with no sample are dropped rather than given an infinite energy: `-R T ln 0` is not a large number, it is no
    number at all, and one empty bin would dominate every fit built on it. How many were dropped is reported.
    """
    values = np.asarray(angles_deg, dtype=float)
    if values.size < 2:
        raise ValueError('a distribution needs at least two frames to be a distribution')
    edges = np.linspace(-180.0, 180.0, int(bins) + 1)
    counts, _ = np.histogram(values, bins=edges)
    centres = 0.5 * (edges[:-1] + edges[1:])
    occupied = counts > 0
    probability = counts[occupied] / float(values.size)
    energy = -R_GAS * float(temperature) / 1000.0 * np.log(probability)
    return {'centres_deg': centres[occupied], 'probability': probability,
            'energy_kj_mol': energy - energy.min(), 'offset_kj_mol': float(energy.min()),
            'frames': int(values.size), 'bins': int(bins), 'empty_bins': int((~occupied).sum())}


def savitzky_golay(values, window=DEFAULT_WINDOW, order=DEFAULT_ORDER):
    """A Savitzky-Golay smoothing: a polynomial of `order` fitted to a window of `window` points, evaluated at its
    centre, then moved along.

    Implemented here rather than taken from scipy, which is present in this environment only as another package's
    dependency and is not declared by this project. Both edges keep their full width and are fitted in the same
    least-squares sense as the interior, which is what lets a closed curve stay closed where its ends meet.
    """
    data = np.asarray(values, dtype=float)
    if window < 3 or window % 2 == 0:
        raise ValueError('the window must be odd and at least three points wide')
    if order < 0 or order >= window:
        raise ValueError('the polynomial order must be non-negative and smaller than the window')
    if data.size < window:
        raise ValueError(f'a {window}-point window cannot smooth {data.size} points')
    half = window // 2
    smoothed = np.empty_like(data)
    for index in range(data.size):
        low, high = max(0, index - half), min(data.size, index + half + 1)
        offsets = np.arange(low, high, dtype=float) - index
        design = np.vander(offsets, order + 1, increasing=True)
        coefficients, *_ = np.linalg.lstsq(design, data[low:high], rcond=None)
        # Offset zero is the centre, which is where the polynomial is evaluated.
        smoothed[index] = coefficients[0]
    return smoothed


def series(angles_deg, amplitudes, phases_rad, multiplicities):
    """`sum_n k_n (1 + cos(n phi - phi_s))`, the form GROMACS writes a proper dihedral in."""
    phi = np.radians(np.asarray(angles_deg, dtype=float))
    total = np.zeros_like(phi)
    for amplitude, phase, multiplicity in zip(amplitudes, phases_rad, multiplicities):
        total = total + amplitude * (1.0 + np.cos(multiplicity * phi - phase))
    return total


def _design(angles_rad, terms):
    """The regression matrix for harmonics 1..terms: a constant column, then a cosine and a sine per harmonic."""
    columns = [np.ones_like(angles_rad)]
    for harmonic in range(1, terms + 1):
        columns += [np.cos(harmonic * angles_rad), np.sin(harmonic * angles_rad)]
    return np.column_stack(columns)


def fit_terms(angles_deg, values, *, max_terms=DEFAULT_MAX_TERMS):
    """Cumulative cosine fits, one per number of harmonics, each with its information criteria.

    AIC and BIC in the Gaussian-error form on the residual sum of squares: `n ln(RSS/n) + 2k` and
    `n ln(RSS/n) + k ln(n)`. Their absolute values depend on conventions that differ between papers; their *ordering*
    does not, and the ordering is what chooses a model, so the table carries both and the choice names which it used.
    """
    angle_rad = np.radians(np.asarray(angles_deg, dtype=float))
    data = np.asarray(values, dtype=float)
    if angle_rad.size < 4 or angle_rad.size != data.size:
        raise ValueError('a fit needs at least four points, one value each')
    models = []
    for terms in range(1, int(max_terms) + 1):
        design = _design(angle_rad, terms)
        if design.shape[1] > angle_rad.size:
            break
        coefficients, *_ = np.linalg.lstsq(design, data, rcond=None)
        residual = float(np.sum((data - design @ coefficients) ** 2))
        parameters, count = design.shape[1], angle_rad.size
        # A perfect fit has no log to take. Zero is the boundary case, and it is reported as such rather than as a
        # large negative number that would win every comparison by arithmetic accident.
        log_term = float(np.log(residual / count)) if residual > 0 else -np.inf
        models.append({
            'terms': terms, 'parameters': parameters, 'residual': residual,
            'aic': float(2 * parameters + count * log_term),
            'bic': float(parameters * np.log(count) + count * log_term),
            'multiplicities': list(range(1, terms + 1)),
            'amplitudes': [float(np.hypot(coefficients[2 * i + 1], coefficients[2 * i + 2]))
                           for i in range(terms)],
            'phases_rad': [float(np.arctan2(coefficients[2 * i + 2], coefficients[2 * i + 1]))
                           for i in range(terms)],
        })
    if not models:
        raise ValueError('no model fits: there are fewer points than the smallest model has parameters')
    return models


def fit_dihedral(angles_deg, temperature, *, bins=DEFAULT_BINS, window=DEFAULT_WINDOW, order=DEFAULT_ORDER,
                 max_terms=DEFAULT_MAX_TERMS, criterion='bic'):
    """The whole workflow: histogram, invert, smooth, fit, and choose the number of terms by a criterion.

    Returns the potential of mean force it measured, every model's criterion, and the chosen one as GROMACS writes it
    -- a force constant, a multiplicity and a phase in degrees, with the unit named beside the number.
    """
    if criterion not in CRITERIA:
        raise ValueError(f'criterion must be one of {", ".join(CRITERIA)}, not {criterion!r}')
    pmf = inverted_boltzmann(angles_deg, temperature, bins=bins)
    smoothed = savitzky_golay(pmf['energy_kj_mol'], window=window, order=order)
    models = fit_terms(pmf['centres_deg'], smoothed, max_terms=max_terms)
    best = min(models, key=lambda model: model[criterion])
    angles = pmf['centres_deg']
    reconstructed = series(angles, best['amplitudes'], best['phases_rad'], best['multiplicities'])
    return {
        'temperature': float(temperature), 'criterion': criterion, 'frames': pmf['frames'],
        'bins': pmf['bins'], 'empty_bins': pmf['empty_bins'],
        'window': {'points': int(window), 'order': int(order)},
        'terms': best['terms'],
        'pmf': {'centres_deg': angles.tolist(), 'probability': pmf['probability'].tolist(),
                'energy_kj_mol': pmf['energy_kj_mol'].tolist(), 'smoothed_kj_mol': smoothed.tolist(),
                'offset_kj_mol': pmf['offset_kj_mol']},
        'models': models,
        'dihedrals': [{'multiplicity': multiplicity, 'force_constant_kj_mol': amplitude,
                       'phase_deg': float(np.degrees(phase)), 'phase_units': 'degrees'}
                      for amplitude, phase, multiplicity
                      in zip(best['amplitudes'], best['phases_rad'], best['multiplicities'])],
        'residual_rms_kj_mol': float(np.sqrt(np.mean((pmf['energy_kj_mol'] - reconstructed) ** 2))),
        'method': 'inverted Boltzmann, Savitzky-Golay smoothing, cumulative cosine series, chosen by ' + criterion,
        'credit': 'reimplemented from the method shaker documents (Martini-Force-Field-Initiative/shaker, commit '
                  'b7680219, LGPL-2.1); see CREDITS.md',
        'scientifically_validated': False,
    }
