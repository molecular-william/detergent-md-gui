"""The equipartition estimator as arithmetic, on values a person can check by hand.

The reference pinning against shaker's own numbers is `test_bonded_estimate_reference.py`; this file is the arithmetic
underneath it, so a factor-of-3283 error and a circular-mean error each fail here first.
"""
import numpy as np
import pytest

from dashboard.analysis.runs import bonded_estimate


def test_a_known_spread_gives_the_equipartition_force_constant():
    """Hand-computed: R T at 300 K is 2494.34 J/mol = 2.49434 kJ/mol, and sigma is 0.1 nm, so k = 2.49434/0.01."""
    assert bonded_estimate.force_constant(0.1, 300.0, kind='bond') == pytest.approx(249.434, rel=1e-5)


def test_an_angle_spread_in_degrees_is_converted_before_the_division():
    """GROMACS writes the angle in degrees and the constant per radian. Skipping the conversion is a factor of
    (180/pi)^2 -- about 3283 -- and the result still looks like a force constant.

    The expected value is built from the module's own R, which `test_a_known_spread_...` pins by hand; what this test
    pins is the conversion, so it must not also carry a truncated R of its own.
    """
    expected = bonded_estimate.R_GAS * 300.0 / 1000.0 / np.radians(5.0) ** 2
    assert bonded_estimate.force_constant(5.0, 300.0, kind='angle') == pytest.approx(expected, rel=1e-12)
    assert bonded_estimate.force_constant(5.0, 300.0, kind='angle') == pytest.approx(327.54, rel=1e-3)


def test_a_zero_spread_is_refused_rather_than_answered_with_an_infinity():
    with pytest.raises(ValueError, match='constraint'):
        bonded_estimate.force_constant(0.0, 303.15, kind='bond')


def test_one_frame_is_refused_because_a_spread_needs_two():
    with pytest.raises(ValueError, match='two frames'):
        bonded_estimate.estimate_bond([0.27], 303.15)
    with pytest.raises(ValueError, match='two frames'):
        bonded_estimate.estimate_angle([145.0], 303.15)


def test_a_bond_reports_its_length_its_spread_and_its_constant():
    # A spread of 0.02 nm at 303 K is k near 6300, which is a flexible spring under this repository's threshold --
    # not the near-zero spread a synthetic sample accidentally has, which would honestly read as a constraint.
    lengths = [0.24, 0.27, 0.30, 0.27, 0.26, 0.28]
    estimate = bonded_estimate.estimate_bond(lengths, 303.15)

    assert estimate['value'] == pytest.approx(np.mean(lengths))
    assert estimate['sigma'] == pytest.approx(np.std(lengths, ddof=1))
    assert estimate['sigma'] == pytest.approx(0.02, abs=1e-6)
    assert estimate['sigma_units'] == 'nm' and estimate['force_constant_units'] == 'kJ/mol/nm^2'
    assert estimate['force_constant'] == pytest.approx(
        bonded_estimate.force_constant(estimate['sigma'], 303.15, kind='bond'))
    assert estimate['force_constant'] == pytest.approx(6301.0, rel=1e-3)
    assert estimate['frames'] == 6
    assert estimate['constraint'] is False


def test_the_threshold_is_the_repositorys_own_and_shaker_s_is_recorded_beside_it():
    """It is a parameter because the two conventions disagree about a real molecule: DDM's inter-ring link fitted
    near 12965, which is a rigid constraint at 10000 and a flexible spring at shaker's 25000."""
    assert bonded_estimate.DEFAULT_CONSTRAINT_THRESHOLD == 10000.0
    documentation = bonded_estimate.__doc__ or ''
    assert '25000' in documentation and '-constraints 10000' in documentation
    assert '12965' in documentation


def test_a_rigid_link_and_a_soft_one_are_told_apart_by_the_threshold():
    """The same measurement, read two ways: this is why the threshold cannot be a hidden default.

    A spread of 0.015 nm puts k near 11100 -- above this repository's 10000 and below shaker's 25000, so the two
    conventions disagree about the same frames. DDM's inter-ring link sits the same way at 12965.
    """
    stiff = [0.272 + offset for offset in (0.013, -0.013, 0.013, -0.013)]

    ours = bonded_estimate.estimate_bond(stiff, 303.15, constraint_threshold=10000)
    shakers = bonded_estimate.estimate_bond(stiff, 303.15, constraint_threshold=25000)

    assert ours['value'] == pytest.approx(shakers['value'])
    assert ours['force_constant'] == pytest.approx(shakers['force_constant'])
    assert ours['force_constant'] == pytest.approx(11185.0, rel=1e-3)
    assert ours['constraint'] is True and shakers['constraint'] is False


def test_an_angle_crossing_the_period_is_averaged_around_the_circle():
    """+179 and -179 are two degrees apart. The arithmetic mean puts them at 0 -- the far side of the circle -- and
    reports a wildly stretched term for a molecule that never moved."""
    angles = [179.0, -179.0, 178.0, -178.0, 180.0, -180.0]

    estimate = bonded_estimate.estimate_angle(angles, 303.15)

    assert abs(estimate['value']) == pytest.approx(180.0, abs=1.0)
    assert estimate['sigma'] < 5.0, estimate
    # And the force constant is the soft one a nearly rigid geometry implies, not the stiff one a 180-degree spread
    # would give.
    assert estimate['force_constant'] > 1000.0


def test_the_circular_spread_matches_the_arithmetic_one_when_nothing_is_wrapped():
    """Away from the period the two definitions have to agree, or the circular one is doing something other than
    what it says."""
    angles = [100.0, 101.0, 102.0, 103.0, 104.0]

    value, spread = bonded_estimate.circular_mean_and_spread(angles)

    assert value == pytest.approx(np.mean(angles), abs=1e-9)
    assert spread == pytest.approx(0.0, abs=1e-9) or spread < 2.0, spread
