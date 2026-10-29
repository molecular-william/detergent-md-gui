"""Execution profiles: one vocabulary, and both halves of a run obey it.

The draft-smoke profile exists for diagnostic execution checks -- the carbohydrate
validation hand-off launches it -- so it must shorten the whole run it is applied to,
not half of it. Before this test, a draft-smoke AA-to-CG run shortened the CG half
(10 ps / 50 ps) while the AA reference it consumed still ran the full 1100 ps
equilibration and 10000 ps production: the CG composition derived the AA durations
from AA settings that had no profile to begin with.
"""
import pytest
from dashboard.execution.adapters import aa, cg


def test_the_smoke_profile_shortens_both_halves_of_an_aa_to_cg_run():
    settings = cg.normalize_settings(None, 'draft-smoke')
    assert settings['aa_equil_ps'] == 10
    assert settings['aa_production_ps'] == 50
    assert settings['cg_equil_ps'] == 10
    assert settings['cg_production_ps'] == 50
    assert settings['aa_nvt_ps'] + settings['aa_npt_ps'] == settings['aa_equil_ps']


def test_the_standard_profile_keeps_the_full_durations():
    settings = cg.normalize_settings(None, 'standard')
    assert settings['aa_equil_ps'] == 1100
    assert settings['aa_production_ps'] == 10000


def test_a_smoke_reference_keeps_a_real_aa_reference():
    """draft-smoke-reference shortens the CG half only: its AA reference is a real one."""
    settings = cg.normalize_settings(None, 'draft-smoke-reference')
    assert settings['aa_equil_ps'] == 1100
    assert settings['aa_production_ps'] == 10000
    assert settings['cg_equil_ps'] == 10
    assert settings['cg_production_ps'] == 10000


@pytest.mark.parametrize('profile', aa.PROFILES)
def test_the_aa_half_a_cg_run_consumes_is_the_aa_half_an_aa_only_run_would_use(profile):
    """The invariant that stops the two halves drifting apart again."""
    composed = cg.normalize_settings(None, profile)
    alone = aa.normalize_settings(None, profile)
    assert composed['aa_nvt_ps'] == alone['aa_nvt_ps']
    assert composed['aa_npt_ps'] == alone['aa_npt_ps']
    assert composed['aa_production_ps'] == alone['aa_production_ps']
    assert composed['aa_equil_ps'] == alone['aa_nvt_ps'] + alone['aa_npt_ps']


def test_a_supplied_aa_setting_still_wins_over_the_profile_default():
    settings = cg.normalize_settings({'aa_nvt_ps': 7, 'aa_npt_ps': 13, 'aa_production_ps': 900}, 'draft-smoke')
    assert settings['aa_equil_ps'] == 20
    assert settings['aa_production_ps'] == 900


def test_an_aa_only_run_accepts_the_same_profiles():
    assert aa.normalize_settings(None, 'draft-smoke')['aa_production_ps'] == 50
    assert aa.stage_defaults('draft-smoke')['values']['aa_production_ps'] == 50
    assert aa.stage_defaults()['values']['aa_production_ps'] == 10000


def test_the_aa_protocol_surface_passes_the_profile_through():
    """The protocol is what the coordinator calls; dropping the profile there is how
    the AA half of a smoke run kept the full durations."""
    assert aa.PROTOCOL.normalize_settings(None, 'draft-smoke')['aa_production_ps'] == 50


def test_an_unknown_profile_is_refused():
    with pytest.raises(ValueError):
        aa.normalize_settings(None, 'not-a-profile')
    with pytest.raises(ValueError):
        aa.stage_defaults('not-a-profile')
