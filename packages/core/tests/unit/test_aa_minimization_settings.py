"""The AA minimization numbers the New run form edits, from the advertised setting to the written mdp.

The reviewed aa-em-v1 profile states 20000 steps, emtol 1000 and emstep 0.01. They become the run's own three
settings with those values as their defaults, so a run that changes none must still render the reviewed file byte
for byte -- that equality is the test the whole change turns on.
"""
import pytest
from dashboard.execution import mdp
from dashboard.execution.adapters import aa


def test_the_three_minimization_numbers_are_advertised_with_their_bounds():
    assert aa.SETTING_SPECS['aa_minimization_steps'] == ('Maximum steps', 1, 1000000)
    assert aa.SETTING_SPECS['aa_minimization_emtol'] == ('Force tolerance (kJ/mol/nm)', .001, 100000)
    assert aa.SETTING_SPECS['aa_minimization_emstep'] == ('Initial step (nm)', .0001, 1)


def test_their_defaults_are_the_reviewed_profiles():
    values = aa.stage_defaults()['values']
    assert (values['aa_minimization_steps'], values['aa_minimization_emtol'],
            values['aa_minimization_emstep']) == (20000, 1000, 0.01)


def test_a_run_may_name_each_of_them():
    settings = aa.normalize_settings({'aa_minimization_steps': 50, 'aa_minimization_emtol': 10,
                                      'aa_minimization_emstep': 0.005})
    assert settings['aa_minimization_steps'] == 50
    assert isinstance(settings['aa_minimization_steps'], int), 'a step count is a whole number'
    assert (settings['aa_minimization_emtol'], settings['aa_minimization_emstep']) == (10, 0.005)


def test_the_step_cap_is_a_count():
    with pytest.raises(ValueError, match='aa_minimization_steps must be an integer'):
        aa.normalize_settings({'aa_minimization_steps': 12.5})


def test_a_value_outside_the_reviewed_vendor_bound_is_refused():
    with pytest.raises(ValueError, match='must be between'):
        aa.normalize_settings({'aa_minimization_emstep': 2})


def test_mdp_values_carries_the_three_numbers():
    settings = aa.normalize_settings({'aa_minimization_steps': 50, 'aa_minimization_emtol': 10,
                                      'aa_minimization_emstep': 0.005})
    values = aa.mdp_values(settings, 'aa-em-v1')
    assert {key: values[key] for key in ('nsteps', 'emtol', 'emstep')} == \
           {'nsteps': 50, 'emtol': 10, 'emstep': 0.005}


def test_the_reviewed_profile_declares_the_three_numbers_as_the_runs_own():
    profile = mdp.PROFILES['aa-em-v1']
    assert set(profile.variable) == {'nsteps', 'emtol', 'emstep'}
    assert profile.settings['nsteps'] == 20000 and profile.settings['emtol'] == 1000
    assert profile.settings['emstep'] == 0.01, 'the reviewed values stay the defaults'


def test_an_untouched_run_renders_the_reviewed_profile_byte_for_byte():
    settings = aa.normalize_settings({})
    assert mdp.render('aa-em-v1', aa.mdp_values(settings, 'aa-em-v1')) == mdp.render('aa-em-v1')


def test_a_named_number_reaches_the_written_minimization_mdp(tmp_path):
    settings = aa.normalize_settings({'aa_minimization_steps': 50, 'aa_minimization_emtol': 10,
                                      'aa_minimization_emstep': 0.005})
    written = mdp.write_mdp('aa-em-v1', tmp_path / 'run.mdp',
                            aa.mdp_values(settings, 'aa-em-v1')).read_text()
    values = {line.split('=', 1)[0].strip(): line.split('=', 1)[1].split(';', 1)[0].strip()
              for line in written.splitlines() if '=' in line}
    assert (values['nsteps'], values['emtol'], values['emstep']) == ('50', '10', '0.005')
