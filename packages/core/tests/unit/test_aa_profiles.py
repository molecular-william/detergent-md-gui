"""The execution profiles that decide how long an AA run samples.

`aa-200ns` exists because the paper's own geometry and volume comparisons sampled at least 200 ns of
atomistic data, and ensemble ring targets are only meaningful once the sampling is at that scale. It says
nothing about validation; it is a sampling scale.
"""
from dashboard.execution.adapters import aa


def test_the_long_profile_is_accepted_and_samples_two_hundred_nanoseconds():
    assert aa.validate_profile('aa-200ns') == 'aa-200ns'
    values = aa.stage_defaults('aa-200ns')['values']
    assert values['aa_production_ps'] == 200000.0, '200 ns of production'
    assert values['aa_npt_ps'] == 1000.0


def test_the_short_profiles_are_unchanged():
    assert aa.stage_defaults('standard')['values']['aa_production_ps'] == 10000.0
    assert aa.stage_defaults('draft-smoke')['values']['aa_production_ps'] == 50.0


def test_an_unknown_profile_is_still_refused():
    try:
        aa.validate_profile('aa-forever')
    except ValueError as error:
        assert 'Unsupported execution profile' in str(error)
    else:
        raise AssertionError('an unknown profile must raise')


def test_the_default_output_interval_fits_the_longest_profile():
    """The output interval has to divide into the production length, or the settings are refused."""
    values = aa.stage_defaults('aa-200ns')['values']
    assert values['output_interval_ps'] <= values['aa_production_ps']
