"""The equipartition estimator as arithmetic: k = R T / sigma^2, with the constraint verdict as a stated parameter.

Adapted from shaker (Martini-Force-Field-Initiative/shaker, commit b7680219) as a **reference implementation** rather
than a dependency: the arithmetic is small and standard, so this module is this repository's and shaker is cited.
`test_bonded_estimate_reference.py` pins it to shaker's own numbers on a real case before any analysis relies on it.

**The constraint threshold is a parameter, not a constant.** shaker defaults to 25000; this repository's pipeline
passes `-constraints 10000` to Fast_Forward. That difference is not cosmetic: DDM's inter-ring link fitted near 12965,
so it became a *rigid constraint* under one convention and a *flexible spring* under the other, and which one a run
used has to travel with the numbers the run produced.

Angles are the trap here. GROMACS writes an angle in **degrees** and its force constant per **radian**, so a spread
measured in degrees is converted before the division -- mixing them is a factor of (180/pi)^2, about 3283, hidden
inside a number that still looks like a force constant.
"""
import numpy as np

R_GAS = 8.314462618  # J / mol / K
DEFAULT_CONSTRAINT_THRESHOLD = 10000.0


def circular_mean_and_spread(angles_deg):
    """The mean and spread of wrapped angles, taken around the circle.

    `+179` and `-179` are two degrees apart, not 358. An arithmetic mean puts them at 0, which is the far side of the
    circle, and it reports a wildly stretched term for a molecule that never moved. The spread comes back through the
    mean resultant length, the same quantity a von Mises fit is built on.
    """
    radians = np.radians(np.asarray(angles_deg, dtype=float))
    mean = np.arctan2(float(np.sin(radians).mean()), float(np.cos(radians).mean()))
    resultant = float(np.hypot(np.sin(radians).mean(), np.cos(radians).mean()))
    # 1 is no spread at all; 0 is a uniform circle, which no finite force constant describes.
    spread = float(np.sqrt(-2.0 * np.log(resultant))) if resultant > 0 else float(np.pi)
    return float(np.degrees(mean)), float(np.degrees(spread))


def force_constant(sigma, temperature, *, kind='bond'):
    """`k = R T / sigma^2` in the units GROMACS writes for that kind of term.

    A bond's constant is per nm^2 and `sigma` is a length in nm. An angle's is per rad^2, so `sigma` arrives in
    degrees and is converted. `sigma` of zero is refused rather than answered with an infinity: a term with no spread
    is a constraint, and saying so is the caller's job.
    """
    if not np.isfinite(sigma) or sigma <= 0:
        raise ValueError('a spread of zero has no equipartition force constant; that term is a constraint')
    spread = np.radians(float(sigma)) if kind == 'angle' else float(sigma)
    return float(R_GAS * float(temperature) / 1000.0 / spread ** 2)


def estimate_bond(lengths_nm, temperature, *, constraint_threshold=DEFAULT_CONSTRAINT_THRESHOLD):
    """A bond's length, its spread, and the force constant that spread implies."""
    values = np.asarray(lengths_nm, dtype=float)
    if values.size < 2:
        # One frame has no spread to measure, and `std` would answer 0.0 for it -- which reads as a rigid bond.
        raise ValueError('a spread needs at least two frames, not one')
    sigma = float(values.std(ddof=1))
    return {'kind': 'bond', 'value': float(values.mean()), 'sigma': sigma, 'sigma_units': 'nm',
            'force_constant': force_constant(sigma, temperature, kind='bond'),
            'force_constant_units': 'kJ/mol/nm^2', 'frames': int(values.size),
            'temperature': float(temperature), 'threshold': float(constraint_threshold),
            'constraint': force_constant(sigma, temperature, kind='bond') > float(constraint_threshold)}


def estimate_angle(angles_deg, temperature, *, constraint_threshold=DEFAULT_CONSTRAINT_THRESHOLD):
    """An angle's mean, its spread, and the force constant, all taken around the circle."""
    values = np.asarray(angles_deg, dtype=float)
    if values.size < 2:
        raise ValueError('a spread needs at least two frames, not one')
    value, sigma = circular_mean_and_spread(values)
    k = force_constant(sigma, temperature, kind='angle')
    return {'kind': 'angle', 'value': value, 'sigma': sigma, 'sigma_units': 'degrees',
            'force_constant': k, 'force_constant_units': 'kJ/mol/rad^2', 'frames': int(values.size),
            'temperature': float(temperature), 'threshold': float(constraint_threshold),
            'constraint': k > float(constraint_threshold)}
