"""The shared Nonbonded and constraints section: one vocabulary, one set of refusals, one byte-identical default.

The section is the New run form's (docs/plans/2026-11-18-new-run-nonbonded-and-constraints.md): the AA dynamics
legs and the CG equilibration and production legs read one set, and a blank box means the reviewed profile or
force-field value (or, where neither states one, GROMACS' own default). These tests pin the two properties that
make that safe -- an untouched run's files do not move, and a combination GROMACS refuses is refused at the queue
route with the setting named -- and the read-back grouping the runs panel draws.
"""
import pytest
from dashboard.execution import nonbonded
from dashboard.execution.adapters import aa, cg, composition
from dashboard.execution.mdp import PROFILES, render
from dashboard.web import stage_settings


def parsed(text):
    settings = {}
    for raw in text.splitlines():
        line = raw.split(';', 1)[0].strip()
        if '=' in line:
            key, value = (part.strip() for part in line.split('=', 1))
            settings[key.lower().replace('_', '-')] = ' '.join(value.split())
    return settings


def rendered(settings, profile, adapter):
    return parsed(render(profile, adapter.mdp_values(settings, profile)))


def same(left, right):
    """Formatting differences (`1` against `1.0`) are not value differences."""
    try:
        return float(left) == float(right)
    except (TypeError, ValueError):
        return left.lower() == right.lower()


def test_an_untouched_run_leaves_the_shared_options_to_the_reviewed_sources():
    """The AA half has no shared values of its own; the CG half names the reviewed ones and renders them unchanged."""
    untouched_aa = aa.normalize_settings({})
    assert not set(nonbonded.AA_FIELDS) & set(untouched_aa)
    # The form's prefill is the force-field block's own values, so the boxes open on the physics that will run.
    defaults = aa.stage_defaults()['values']
    assert (defaults['rlist'], defaults['rcoulomb'], defaults['rvdw']) == (1.2, 1.2, 1.2)
    assert defaults['vdwtype'] == 'cutoff' and defaults['vdw_modifier'] == 'force-switch'
    # The coupling intervals and the AA LINCS numbers have no reviewed line, so they start blank.
    for key in ('nsttcouple', 'nstpcouple', 'lincs_order', 'lincs_warnangle', 'lincs_iter'):
        assert key not in defaults

    untouched_cg = cg.normalize_settings({})
    for profile in ('cg-equilibration-v1', 'cg-production-v1'):
        written = rendered(untouched_cg, profile, cg)
        for key, value in PROFILES[profile].settings.items():
            if value is not None:
                assert same(written[key], value), (profile, key)
        assert 'nsttcouple' not in written and 'nstpcouple' not in written


def test_a_shared_value_reaches_every_dynamics_leg_and_no_minimisation_leg():
    aa_settings = aa.normalize_settings({'rcoulomb': 1.2, 'rvdw': 1.0, 'rvdw_switch': 0.8, 'lincs_order': 6,
                                         'nsttcouple': 50})
    for profile in ('aa-nvt-v1', 'aa-npt-v1', 'aa-production-v1'):
        written = rendered(aa_settings, profile, aa)
        assert written['rvdw'] == '1' and written['rvdw-switch'] == '0.8'
        assert written['lincs-order'] == '6' and written['nsttcouple'] == '50'
    assert rendered(aa_settings, 'aa-em-v1', aa)['rvdw'] == '1.2'

    cg_settings = cg.normalize_settings({'rcoulomb': 1.0, 'rvdw': 1.0, 'lincs_order': 6})
    for profile in ('cg-equilibration-v1', 'cg-production-v1'):
        written = rendered(cg_settings, profile, cg)
        assert written['rcoulomb'] == '1' and written['rvdw'] == '1' and written['lincs-order'] == '6'
    assert rendered(cg_settings, 'cg-minimization-v1', cg)['rvdw'] == '1.1'


def test_a_value_equal_to_the_reviewed_one_keeps_the_reviewed_spelling_and_line_count():
    """Naming the default must not turn `vdw-type = cutoff` into a second line or re-spell it."""
    default = cg.normalize_settings({})
    named = cg.normalize_settings({'vdwtype': 'cutoff', 'vdw_modifier': 'potential-shift-verlet',
                                   'epsilon_r': 15, 'epsilon_rf': 0, 'coulombtype': 'reaction-field'})
    for profile in ('cg-equilibration-v1', 'cg-production-v1', 'cg-minimization-v1'):
        assert render(profile, cg.mdp_values(named, profile)) == \
            render(profile, cg.mdp_values(default, profile)), profile
    aa_default = aa.normalize_settings({})
    aa_named = aa.normalize_settings({'rlist': 1.2, 'rcoulomb': 1.2, 'rvdw': 1.2, 'rvdw_switch': 1.0,
                                      'vdwtype': 'cutoff', 'vdw_modifier': 'force-switch'})
    for profile in ('aa-nvt-v1', 'aa-npt-v1', 'aa-production-v1'):
        assert render(profile, aa.mdp_values(aa_named, profile)) == \
            render(profile, aa.mdp_values(aa_default, profile)), profile


def test_the_choice_values_are_the_form_spelling_and_the_writer_spelling():
    assert nonbonded.CHOICES['vdwtype'][1] == ('cutoff', 'pme')
    changed = cg.normalize_settings({'vdwtype': 'pme', 'vdw_modifier': 'none'})
    written = rendered(changed, 'cg-production-v1', cg)
    assert written['vdw-type'] == 'PME' and written['vdw-modifier'] == 'none'


@pytest.mark.parametrize('settings, message', [
    ({'rlist': 1.0}, 'rlist'),
    ({'rcoulomb': 1.2}, 'rcoulomb'),
    ({'vdw_modifier': 'force-switch'}, 'rvdw_switch'),
    ({'vdw_modifier': 'force-switch', 'rcoulomb': 1.0, 'rvdw': 1.0, 'rvdw_switch': 1.0}, 'LJ switch start'),
    ({'coulombtype': 'pme', 'epsilon_rf': 5}, 'epsilon-rf'),
    ({'epsilon_r': 15, 'epsilon_rf': 10}, 'epsilon-rf'),
    ({'nsttcouple': 10.5}, 'nsttcouple must be an integer'),
])
def test_cg_settings_refuse_the_combinations_gromacs_refuses(settings, message):
    with pytest.raises(ValueError, match=message):
        cg.normalize_settings(settings)


def test_aa_settings_refuse_the_combinations_gromacs_refuses():
    with pytest.raises(ValueError, match='rcoulomb'):
        aa.normalize_settings({'rcoulomb': 1.0})
    with pytest.raises(ValueError, match='van der Waals type PME'):
        aa.normalize_settings({'vdwtype': 'pme'})
    with pytest.raises(ValueError, match='LJ switch start'):
        aa.normalize_settings({'rvdw': 1.0, 'rvdw_switch': 1.0})
    # A cut-off longer than half the box GROMACS would only discover at grompp.
    with pytest.raises(ValueError, match='cut-off'):
        aa.normalize_settings({'rvdw': 1.3})


def test_the_composition_and_published_sugar_kinds_publish_the_shared_vocabulary():
    from dashboard.execution.adapters import cg_run
    from detergent_validation.execution.adapters import sugar_cg

    numeric = set(nonbonded.numeric_specs(nonbonded.CG_FIELDS))
    choices = set(nonbonded.choice_specs(nonbonded.CG_FIELDS))
    for specs in (cg.PROTOCOL.settings_specs(), composition.PROTOCOL.settings_specs(),
                  sugar_cg.PROTOCOL.settings_specs(), cg_run.PROTOCOL.settings_specs()):
        assert numeric <= set(specs), specs
    for specs in (cg.PROTOCOL.choice_specs(), composition.PROTOCOL.choice_specs(),
                  sugar_cg.PROTOCOL.choice_specs()):
        assert choices <= set(specs), specs


def test_the_read_back_shows_one_shared_group_not_one_per_stage():
    settings = {'rlist': 1.2, 'rcoulomb': 1.2, 'rvdw': 1.2, 'vdwtype': 'cutoff',
                'aa_nvt_ps': 100, 'aa_nvt_dt_fs': 2, 'aa_nvt_nstlist': 20,
                'aa_npt_ps': 1000, 'aa_npt_dt_fs': 2, 'aa_npt_nstlist': 20,
                'aa_production_ps': 10000, 'aa_production_dt_fs': 2, 'aa_production_nstlist': 20}
    groups = stage_settings.groups({'run_type': 'aa_only', 'settings': settings}, {})
    shared = [group for group in groups if group['label'] == 'Nonbonded and constraints']
    assert len(shared) == 1
    assert [field['key'] for field in shared[0]['fields']] == ['rlist', 'rcoulomb', 'rvdw', 'vdwtype']
