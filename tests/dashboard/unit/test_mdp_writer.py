"""The MDP writer's parity gate: every reviewed profile renders the map today's code produces.

Phase 3, T3.1 of `docs/plans/2026-10-27-run-lifecycle-refactor.md`: a profile may replace a template or an adapter
patch only when its file parses to the same settings. Comments and formatting are ignored -- the comparison is the
key/value map GROMACS reads -- and where the current code patches a copied template at prepare time, these tests apply
the same patch through the same functions (`environment.update_mdp`, `cg.mdp_integration`) and compare the patched
result. The values a profile leaves for the run are supplied the way its adapter computes them.
"""
import math
import shutil
from dataclasses import replace

import pytest
from dashboard import paths
from dashboard.execution import environment, forcefields
from dashboard.execution.adapters import aa, cg, osmotic_mdp
from dashboard.execution.mdp import PROFILES, render, write_mdp
from dashboard.execution.mdp.writer import formatted
from detergent_pdc.execution.adapters import pdc

ROOT = paths.DEFAULT.project_root
TEMPLATES = ROOT / 'resources/templates'
FF_TEMPLATE = TEMPLATES / 'small_mols_fast_forward'
CG_INPUTS = FF_TEMPLATE / '4_CG_sim/inputs'
PDC_TEMPLATES = TEMPLATES / 'protein_detergent'

AA_KINDS = {'ions': 'aa-ions-v1', 'em': 'aa-em-v1', 'nvt': 'aa-nvt-v1', 'npt': 'aa-npt-v1',
            'production': 'aa-production-v1'}
AA_DURATION = {'aa-nvt-v1': 'aa_nvt_ps', 'aa-npt-v1': 'aa_npt_ps', 'aa-production-v1': 'aa_production_ps'}


# --------------------------------------------------------------------------------------------------------------------
# The comparison: an MDP as a key/value map, and two values as equal when they are the same number or the same text.
# --------------------------------------------------------------------------------------------------------------------

def parsed(text):
    """The MDP's settings: comments dropped, names folded (`xtc_grps`/`xtc-grps`/`Xtc-Grps` are one name), last wins."""
    settings = {}
    for raw in text.splitlines():
        line = raw.split(';', 1)[0].strip()
        if not line or '=' not in line:
            continue
        key, value = (part.strip() for part in line.split('=', 1))
        settings[key.lower().replace('_', '-')] = ' '.join(value.split())
    return settings


def equivalent(left, right):
    """Formatting differences -- `4.0` against `4`, `4.5e-5` against `4.5e-05` -- are not physics differences."""
    if len(left.split()) == 1 and len(right.split()) == 1:
        try:
            return float(left) == float(right)
        except ValueError:
            pass
    return left == right


#: The three neighbour-list keys the CG dynamics profiles own deliberately, against templates that were written for a
#: 20-step list with a pinned 1.35 nm buffer. The parity gate compares everything else; the values these three carry
#: are pinned by `test_cg_dynamics_states_the_reviewed_neighbour_list`, and the reason is in `profiles.py`.
NEIGHBOURS = ('nstlist', 'verlet-buffer-tolerance', 'rlist')


def assert_same(profile, expected_text, values=None, ignore=()):
    """One profile against what the current code writes: same keys, same values, nothing extra on either side."""
    produced = parsed(render(profile, values))
    expected = parsed(expected_text)
    for key in ignore:
        produced.pop(key, None)
        expected.pop(key, None)
    assert produced.keys() == expected.keys(), (
        f'{profile}: only in the current output: {sorted(set(expected) - set(produced))}; '
        f'only in the profile: {sorted(set(produced) - set(expected))}')
    differing = {key: (expected[key], produced[key]) for key in expected
                 if not equivalent(expected[key], produced[key])}
    assert differing == {}, f'{profile}: {differing}'


def stamped(tmp_path, name, changes, source=None):
    """Copy the template the current code copies, then patch it the way the current code patches it."""
    target = tmp_path / name
    shutil.copy2(source or CG_INPUTS / name, target)
    environment.update_mdp(target, changes)
    return target


# --------------------------------------------------------------------------------------------------------------------
# AA-only stages: `aa.mdp()` is the current builder.
# --------------------------------------------------------------------------------------------------------------------

def aa_values(profile, settings):
    if profile in ('aa-ions-v1', 'aa-em-v1'):
        return {'force_field': settings['force_field']}
    interval = max(1, round(settings['output_interval_ps'] / 0.002))
    values = {'force_field': settings['force_field'],
              'nsteps': round(settings[AA_DURATION[profile]] / 0.002),
              'ref-t': settings['temperature_k'], 'gen-temp': settings['temperature_k'],
              'gen-seed': settings['aa_seed'], 'ld-seed': settings['aa_seed'],
              'nstxout-compressed': interval, 'nstenergy': min(interval, 500), 'nstlog': min(interval, 500)}
    if profile != 'aa-nvt-v1':
        values['ref-p'] = settings['pressure_bar']
    return values


@pytest.mark.parametrize('force_field', forcefields.names())
@pytest.mark.parametrize('overrides', ({}, {'temperature_k': 310.0, 'pressure_bar': 2.0,
                                            'output_interval_ps': 20.0, 'aa_seed': 7}))
def test_aa_profiles_match_aa_mdp(force_field, overrides):
    settings = aa.normalize_settings(dict(overrides, force_field=force_field))
    for kind, profile in AA_KINDS.items():
        assert_same(profile, aa.mdp(settings, kind), aa_values(profile, settings))


# --------------------------------------------------------------------------------------------------------------------
# CG half: `cg.prepare` patches the shipped templates.
# --------------------------------------------------------------------------------------------------------------------

def current_cg_dynamics(tmp_path, settings, name):
    """The eq/md file as `cg.prepare` writes it, and the numbers it supplies, both from the template's own dt."""
    path = stamped(tmp_path, f'{name}.mdp', cg.mdp_integration(tmp_path, tmp_path / '1_AA-reference',
                                                               {'eq': 5000, 'md': 25000}[name]))
    environment.update_mdp(path, {'gen-seed': settings['cg_seed'], 'ld-seed': settings['cg_seed'],
                                  'gen-temp': settings['temperature_k']})
    dt = float(parsed(path.read_text())['dt'])
    values = {'nsteps': round(settings['cg_equil_ps' if name == 'eq' else 'cg_production_ps'] / dt),
              'nstxtcout': max(1, round(settings['output_interval_ps'] / dt)),
              'ref-t': settings['temperature_k'], 'gen-temp': settings['temperature_k'],
              'gen-seed': settings['cg_seed'], 'ld-seed': settings['cg_seed']}
    environment.update_mdp(path, {key: values[key] for key in ('nsteps', 'ref-t', 'nstxtcout')})
    return path.read_text(), values


CG_RUN = {'cg_equil_ps': 20.0, 'cg_production_ps': 200.0, 'temperature_k': 310.0,
          'output_interval_ps': 5.0, 'cg_seed': 12345}


@pytest.mark.parametrize('overrides', (None, CG_RUN))
def test_cg_profiles_match_prepare_patches(tmp_path, overrides):
    settings = cg.normalize_settings(overrides)
    initial = stamped(tmp_path, 'initial.mdp', {'nsteps': 0}, FF_TEMPLATE / '3_initial_CG/initial.mdp')
    assert_same('cg-initial-v1', initial.read_text())
    minimisation = stamped(tmp_path, 'minimization.mdp', {'nsteps': 20000, 'define': ''})
    assert_same('cg-minimization-v1', minimisation.read_text())
    for name, profile in (('eq', 'cg-equilibration-v1'), ('md', 'cg-production-v1')):
        expected, values = current_cg_dynamics(tmp_path, settings, name)
        assert_same(profile, expected, values, ignore=NEIGHBOURS)


def test_cg_dynamics_states_the_reviewed_neighbour_list():
    """`nstlist = 40` with a computed buffer, and no pinned `rlist`, in every CG file that integrates.

    The decision and the measurement behind it are in `profiles.py`; this pins that no profile drifts back to the
    template's 20 steps, and that a pinned `rlist` cannot come back with it -- 1.35 nm was the 20-step buffer.
    """
    dynamics = ('cg-equilibration-v1', 'cg-production-v1', 'pdc-nvt-v1', 'pdc-npt-v1',
                'pdc-restart-equilibration-v1')
    for profile in dynamics:
        settings = PROFILES[profile].settings
        assert settings['nstlist'] == 40, profile
        assert settings['verlet-buffer-tolerance'] == 0.005, profile
        assert 'rlist' not in settings, profile
    # The two CG production profiles leave the neighbour list to the run; its defaults are the same 40 / 0.005 /
    # 1.35, so an untouched run is still the reviewed list rather than a pinned one.
    for profile in ('pdc-assessment-v1', 'pdc-extension-v1'):
        numbers = pdc._mdp_run_values(profile, pdc.settings_from({}))
        assert numbers['nstlist'] == 40 and numbers['verlet-buffer-tolerance'] == 0.005
        assert 'rlist' not in numbers, 'the profile does not own a pinned neighbour cut-off'
    # A minimisation integrates nothing, so the pdc one keeps the pinned list it always had.
    assert PROFILES['pdc-minimisation-v1'].settings['rlist'] == 1.35


def test_a_run_value_the_profile_fixes_is_refused():
    """An override would be one reviewed profile run under another's name."""
    with pytest.raises(ValueError, match='nsteps'):
        render('aa-em-v1', {'nsteps': 5})


def test_a_missing_run_number_is_refused_instead_of_written_as_none():
    with pytest.raises(ValueError, match='nsteps'):
        render('aa-nvt-v1', {'force_field': forcefields.DEFAULT})


def test_the_force_field_block_is_read_at_render_time(monkeypatch):
    entry = forcefields.entry()
    monkeypatch.setitem(forcefields.ENTRIES, 'rendered-test-field',
                        replace(entry, mdp={**entry.mdp, 'rlist': 3.0}))
    assert parsed(render('aa-em-v1', {'force_field': 'rendered-test-field'}))['rlist'] == '3'
    assert 'rlist' not in PROFILES['aa-em-v1'].settings
    assert 'constraints' not in PROFILES['aa-em-v1'].settings


# --------------------------------------------------------------------------------------------------------------------
# PDC legs: three templates, the genion fix-up, and the production/extension legs built from the CG template.
# --------------------------------------------------------------------------------------------------------------------

def test_pdc_leg_profiles_match_the_templates_and_their_stamps(tmp_path):
    minimisation = stamped(tmp_path, 'minimisation.mdp', {'nsteps': 500}, PDC_TEMPLATES / 'minimisation.mdp')
    assert_same('pdc-minimisation-v1', minimisation.read_text(), {'nsteps': 500})
    nvt = stamped(tmp_path, 'nvt.mdp', {'nsteps': 10000, 'gen-seed': 42}, PDC_TEMPLATES / 'nvt.mdp')
    assert_same('pdc-nvt-v1', nvt.read_text(), {'nsteps': 10000, 'gen-seed': 42}, ignore=NEIGHBOURS)
    npt = stamped(tmp_path, 'npt.mdp', {'nsteps': 900000}, PDC_TEMPLATES / 'npt.mdp')
    assert_same('pdc-npt-v1', npt.read_text(), {'nsteps': 900000}, ignore=NEIGHBOURS)


def test_the_pdc_ions_profile_is_the_genion_fix_up():
    """The fix-up mdp had no template: it was a string in `pdc`, and these six keys are its whole definition."""
    assert parsed(render('pdc-ions-v1')) == {'integrator': 'steep', 'nsteps': '0', 'cutoff-scheme': 'Verlet',
                                             'rlist': '1.1', 'coulombtype': 'reaction-field', 'epsilon-r': '15'}


def test_pdc_production_profiles_match_the_adapter(tmp_path):
    stage = tmp_path / '2_assessment'
    stage.mkdir()
    steps = round(100 * 1000 / 0.02)
    numbers = pdc.settings_from({})
    assessment = stamped(stage, 'assessment.mdp', cg.mdp_integration(stage, stage / '1_AA-reference', steps),
                         CG_INPUTS / 'md.mdp')
    assert_same('pdc-assessment-v1', assessment.read_text(),
                pdc._mdp_run_values('pdc-assessment-v1', numbers, {'nsteps': steps}), ignore=NEIGHBOURS)
    extension = stamped(stage, 'extension.mdp', {'gen-vel': 'no'}, assessment)
    assert_same('pdc-extension-v1', extension.read_text(),
                pdc._mdp_run_values('pdc-extension-v1', numbers, {'nsteps': steps}), ignore=NEIGHBOURS)


def test_pdc_restart_profiles_match_the_unpatched_templates():
    """The removal path copies these two files as they are, so the profile is the template's map exactly."""
    assert_same('pdc-restart-minimization-v1', (CG_INPUTS / 'minimization.mdp').read_text())
    assert_same('pdc-restart-equilibration-v1', (CG_INPUTS / 'eq.mdp').read_text(), ignore=NEIGHBOURS)


# --------------------------------------------------------------------------------------------------------------------
# Osmotic series: `osmotic_mdp.osmotic_mdps` builds all three from the run's temperature, durations and interval.
# --------------------------------------------------------------------------------------------------------------------

TEMPERATURE = 308.15


@pytest.mark.parametrize('production_ps, equilibration_ps, interval_ps', (
    (osmotic_mdp.DEFAULT_PRODUCTION_PS, osmotic_mdp.DEFAULT_EQUILIBRATION_PS, osmotic_mdp.DEFAULT_OUTPUT_INTERVAL_PS),
    (2000.0, 1000.0, 5.0),
))
def test_osmotic_profiles_match_osmotic_mdps(production_ps, equilibration_ps, interval_ps):
    mdps = osmotic_mdp.osmotic_mdps(temperature=TEMPERATURE, solute_molecules=2, production_ps=production_ps,
                                    equilibration_ps=equilibration_ps, output_interval_ps=interval_ps)
    assert_same('osmotic-minimization-v1', mdps['minimization'])
    for stage, dt, steps, profile in (
            ('equilibration', osmotic_mdp.EQUILIBRATION_DT, math.ceil(equilibration_ps / osmotic_mdp.EQUILIBRATION_DT),
             'osmotic-equilibration-v1'),
            ('production', osmotic_mdp.PRODUCTION_DT, round(production_ps / osmotic_mdp.PRODUCTION_DT),
             'osmotic-production-v1')):
        stride = round(interval_ps / dt)
        values = {'nsteps': steps, 'nstxtcout': stride, 'nstenergy': stride,
                  'ref-t': TEMPERATURE, 'gen-temp': TEMPERATURE}
        assert_same(profile, mdps[stage], values)


# --------------------------------------------------------------------------------------------------------------------
# The writer's own contract.
# --------------------------------------------------------------------------------------------------------------------

def test_every_profile_is_registered_under_its_versioned_name():
    for name, profile in PROFILES.items():
        assert profile.version == name
        assert name.endswith('-v1'), f'{name} carries no version'
    assert {'aa-nvt-v1', 'cg-equilibration-v1', 'pdc-assessment-v1', 'osmotic-production-v1'} <= set(PROFILES)


def test_write_mdp_writes_the_rendered_file(tmp_path):
    path = write_mdp('pdc-ions-v1', tmp_path / 'ions.mdp')
    assert path == tmp_path / 'ions.mdp'
    assert path.read_text() == render('pdc-ions-v1')


def test_values_are_formatted_the_way_gromacs_reads_them():
    assert formatted(4.5e-5) == '4.5e-05'
    assert formatted(0.002) == '0.002'
    assert formatted(5000) == '5000'
    assert formatted(True) == 'yes' and formatted(False) == 'no'
    assert formatted('') == ''


def test_an_unknown_profile_is_refused_by_name():
    with pytest.raises(ValueError, match='unknown MDP profile'):
        render('nvt-cg-v1')


def test_an_empty_define_is_written_as_update_mdp_writes_it():
    text = render('cg-minimization-v1')
    line = next(line for line in text.splitlines() if line.split(';')[0].strip().startswith('define'))
    assert line.split(';')[0].rstrip() == 'define ='
    assert parsed(text)['define'] == ''

def test_pdc_production_keeps_the_cadence_the_run_sent(tmp_path):
    """The panel's numbers reach the assessment file unchanged, even when the leg is 1 us or longer."""
    numbers = pdc.settings_from({'nstlog': 100, 'nstenergy': 250, 'nstxtcout': 100})
    steps = round(1_000_000.0 / 0.02)
    text = render('pdc-assessment-v1', pdc._mdp_run_values('pdc-assessment-v1', numbers, {'nsteps': steps}))
    written = parsed(text)

    assert (written['nstlog'], written['nstenergy'], written['nstxtcout']) == ('100', '250', '100')
