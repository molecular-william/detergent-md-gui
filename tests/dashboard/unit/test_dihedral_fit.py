"""The dihedral fit, on inputs whose answers can be checked by hand.

The decisive test is the round trip: a potential that *is* two cosines must come back as those two cosines with those
amplitudes and phases, because every step of the workflow -- histogram, inversion, smoothing, series -- is invertible
in that direction. A factor-of-57 error in the degrees/radians conversion survives every test that only looks at the
residual, and dies here.
"""
import numpy as np
import pytest

from dashboard.analysis.runs import dihedral_fit

R_GAS = dihedral_fit.R_GAS


def _two_cosine_potential(angles_deg):
    """8(1 + cos(2 phi - 0.5)) + 3(1 + cos(3 phi + 1.0)), in kJ/mol, as a function of degrees."""
    phi = np.radians(np.asarray(angles_deg, dtype=float))
    return 8.0 * (1.0 + np.cos(2 * phi - 0.5)) + 3.0 * (1.0 + np.cos(3 * phi + 1.0))


def _frames_from(potential, temperature, *, count=40000, seed=20261005):
    """Angles drawn from p(phi) proportional to exp(-F(phi)/RT), by sampling a fine grid with those weights.

    This is the exact inverse of the inversion the fit performs, which is what makes it an input with a known answer.
    """
    grid = np.linspace(-180.0, 180.0, 3601)[:-1]
    weights = np.exp(-potential(grid) / (R_GAS * temperature / 1000.0))
    weights /= weights.sum()
    return np.random.default_rng(seed).choice(grid, size=count, p=weights)


# --- the smoothing -------------------------------------------------------------------------------------------


def test_a_first_order_window_leaves_a_straight_line_alone():
    """A polynomial window of order one fits a line exactly, at the edges as well as in the interior -- which is the
    property that makes an edge treatment honest rather than an extrapolation."""
    line = np.linspace(-5.0, 5.0, 41)

    smoothed = dihedral_fit.savitzky_golay(line, window=7, order=1)

    assert smoothed == pytest.approx(line, abs=1e-9)


def test_a_zeroth_order_window_is_a_moving_average_away_from_the_edges():
    """Order zero is a plain window mean. The edges truncate the window instead of reaching beyond the data, so they
    are excluded here rather than asserted against a differently-weighted number."""
    values = np.array([1.0, 2.0, 9.0, 4.0, 5.0, 6.0, 7.0])

    smoothed = dihedral_fit.savitzky_golay(values, window=3, order=0)

    assert smoothed[1:6] == pytest.approx([(1 + 2 + 9) / 3, (2 + 9 + 4) / 3, (9 + 4 + 5) / 3,
                                           (4 + 5 + 6) / 3, (5 + 6 + 7) / 3])


def test_a_window_or_an_order_the_data_cannot_carry_is_refused():
    values = np.arange(20.0)
    with pytest.raises(ValueError, match='odd'):
        dihedral_fit.savitzky_golay(values, window=8, order=2)
    with pytest.raises(ValueError, match='smaller than the window'):
        dihedral_fit.savitzky_golay(values, window=5, order=5)
    with pytest.raises(ValueError, match='cannot smooth'):
        dihedral_fit.savitzky_golay(np.arange(4.0), window=9, order=2)


# --- the inversion -------------------------------------------------------------------------------------------


def test_an_even_distribution_gives_a_flat_potential_and_no_empty_bins():
    """36 bins with ten frames each: the probability is uniform, so -R T ln p is constant."""
    bins = 36
    edges = np.linspace(-180.0, 180.0, bins + 1)
    centres = 0.5 * (edges[:-1] + edges[1:])
    frames = np.repeat(centres - 1.0, 10)  # just inside each bin, away from an edge

    pmf = dihedral_fit.inverted_boltzmann(frames, 303.15, bins=bins)

    assert pmf['empty_bins'] == 0
    assert pmf['frames'] == 360
    assert float(np.ptp(pmf['energy_kj_mol'])) == pytest.approx(0.0, abs=1e-9)
    assert float(pmf['energy_kj_mol'].min()) == pytest.approx(0.0, abs=1e-12)


def test_an_empty_bin_is_dropped_and_counted_rather_than_given_an_infinite_energy():
    """-R T ln 0 is not a large number, it is no number: one empty bin would otherwise dominate every fit."""
    frames = np.linspace(-90.0, 90.0, 900)

    pmf = dihedral_fit.inverted_boltzmann(frames, 303.15, bins=60)

    assert pmf['empty_bins'] > 0
    assert len(pmf['centres_deg']) == pmf['bins'] - pmf['empty_bins']
    assert np.isfinite(pmf['energy_kj_mol']).all()
    # The zero of a potential of mean force is a convention, so the offset it was measured against is reported --
    # and here it is computable by hand: 30 of 60 bins hold 1/30 of the frames each, so the minimum energy is
    # -R T ln(1/30), which is positive because no bin can hold more than all of them.
    assert pmf['offset_kj_mol'] == pytest.approx(dihedral_fit.R_GAS * 303.15 / 1000.0 * np.log(30.0), rel=1e-9)


# --- the series, which is the point --------------------------------------------------------------------------


def test_a_potential_made_of_two_cosines_comes_back_as_those_two_cosines():
    """The decisive arithmetic: the fit is linear in its coefficients, so an exact input must be recovered exactly."""
    angles = np.linspace(-180.0, 180.0, 721)[:-1]
    models = dihedral_fit.fit_terms(angles, _two_cosine_potential(angles), max_terms=4)

    three = next(model for model in models if model['terms'] == 3)
    assert three['multiplicities'] == [1, 2, 3]
    assert three['amplitudes'][0] == pytest.approx(0.0, abs=1e-8)   # nothing at the fundamental
    assert three['amplitudes'][1] == pytest.approx(8.0, rel=1e-8)
    assert three['amplitudes'][2] == pytest.approx(3.0, rel=1e-8)
    assert three['phases_rad'][1] == pytest.approx(0.5, abs=1e-8)
    # 3(1 + cos(3 phi + 1.0)) is 3(1 + cos(3 phi - (-1.0))), so the phase the GROMACS form wants is -1.0 rad.
    assert three['phases_rad'][2] == pytest.approx(-1.0, abs=1e-8)
    assert three['residual'] == pytest.approx(0.0, abs=1e-12)


def test_the_criterion_chooses_the_number_of_terms_the_data_needs():
    """With a little noise, so the residuals are above the machine floor: the criterion then has something real to
    weigh, and it must stop at the model that actually contains the potential rather than at the biggest one."""
    angles = np.linspace(-180.0, 180.0, 721)[:-1]
    noisy = _two_cosine_potential(angles) + np.random.default_rng(7).normal(0.0, 0.05, angles.size)

    models = dihedral_fit.fit_terms(angles, noisy, max_terms=6)

    assert [model['terms'] for model in models] == [1, 2, 3, 4, 5, 6]
    assert min(models, key=lambda model: model['bic'])['terms'] == 3
    # BIC penalises a parameter harder than AIC does, so it can never choose more terms than AIC on the same data.
    assert min(models, key=lambda model: model['aic'])['terms'] >= 3


def test_fit_dihedral_returns_gromacs_terms_with_the_phase_unit_named():
    """The end-to-end path on frames drawn from a known potential: histogram noise and smoothing make the recovery
    approximate, so the tolerances are loose and the *unit* is what is pinned exactly."""
    frames = _frames_from(_two_cosine_potential, 303.15)

    fitted = dihedral_fit.fit_dihedral(frames, 303.15)

    amplitudes = {term['multiplicity']: term['force_constant_kj_mol'] for term in fitted['dihedrals']}
    phases = {term['multiplicity']: term['phase_deg'] for term in fitted['dihedrals']}
    assert fitted['terms'] >= 2                       # a one-term model cannot hold a 2nd harmonic
    assert amplitudes[2] == pytest.approx(8.0, rel=0.35)
    assert phases[2] == pytest.approx(np.degrees(0.5), abs=25.0)
    assert all(term['phase_units'] == 'degrees' for term in fitted['dihedrals'])
    if 3 in amplitudes:
        # Only where the criterion kept the third harmonic: a factor-of-57 conversion error is nowhere near this.
        assert amplitudes[3] == pytest.approx(3.0, rel=0.6)
        assert phases[3] == pytest.approx(np.degrees(-1.0), abs=30.0)
    assert fitted['pmf']['centres_deg'][0] < -170.0 and fitted['pmf']['centres_deg'][-1] > 170.0
    assert float(min(fitted['pmf']['energy_kj_mol'])) == pytest.approx(0.0, abs=1e-12)
    assert fitted['criterion'] == 'bic' and len(fitted['models']) == 6
    assert 'shaker' in fitted['credit'] and 'CREDITS.md' in fitted['credit']
    assert 'Savitzky-Golay' in fitted['method']
    assert fitted['scientifically_validated'] is False


def test_an_unknown_criterion_is_refused_rather_than_defaulted():
    frames = _frames_from(_two_cosine_potential, 303.15, count=2000)

    with pytest.raises(ValueError, match='criterion must be one of'):
        dihedral_fit.fit_dihedral(frames, 303.15, criterion='rmsd')


def test_the_series_reproduces_the_gromacs_form_it_claims_to():
    """`k (1 + cos(n phi - phi_s))` peaks where `n phi = phi_s`, so its maximum is at `phi_s / n`, and half a period
    away from that it is zero.

    Angles are degrees and the phase is radians -- the mix this module exists to keep straight -- so the test converts
    once and passes degrees. Assuming the peak sits at `phi_s` rather than at `phi_s / n` is what made it fail first.
    """
    peak_deg = float(np.degrees(0.5 / 2))  # n = 2, so the peak is at half the phase
    angles = np.array([0.0, peak_deg, peak_deg + 90.0])  # 90 degrees is half a period of the 2nd harmonic

    values = dihedral_fit.series(angles, [4.0], [0.5], [2])

    assert values[1] == pytest.approx(8.0)
    assert values[2] == pytest.approx(0.0, abs=1e-12)
    assert values[0] == pytest.approx(4.0 * (1.0 + np.cos(-0.5)))
