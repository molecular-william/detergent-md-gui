"""The prepared pdc MDPs are the reviewed profiles at the run's own numbers.

Phase 3, T3.2 of `docs/plans/2026-10-27-run-lifecycle-refactor.md`: the adapter no longer copies a template and
patches it in place, it writes each file from a named profile in `dashboard.execution.mdp`. What is pinned here is the
pair the writer promises -- the file a stage reads parses to the profile's own map at the numbers the run chose, and
the manifest names that profile -- so a reader can name the physics without opening the file.

The profile's map is the physics; this file does not restate it. `values` below is the run's arithmetic only, the part
`render` cannot know: a duration in steps at the profile's timestep, and the seed of the leg that draws velocities.
"""
from __future__ import annotations

import json

import pytest
from dashboard.execution.mdp import PROFILES, render
from detergent_pdc.execution.adapters import pdc as pdc_adapter

from tests.harness.pdc_fixtures import inputs_dir, prepared_run, settings_of

#: The profile each file `prepare` writes is written from, keyed by the file name the stage scripts read.
EXPECTED = {
    'minimisation.mdp': 'pdc-minimisation-v1',
    'nvt.mdp': 'pdc-nvt-v1',
    'npt.mdp': 'pdc-npt-v1',
    'assessment.mdp': 'pdc-assessment-v1',
    'extension.mdp': 'pdc-extension-v1',
    'minimization.mdp': 'pdc-restart-minimization-v1',
    'equilibration.mdp': 'pdc-restart-equilibration-v1',
    'ions.mdp': 'pdc-ions-v1',
}


def parsed(text: str) -> dict:
    """An MDP as the key/value map GROMACS reads: comments dropped, names folded, the last value winning."""
    settings = {}
    for raw in text.splitlines():
        line = raw.split(';', 1)[0].strip()
        if '=' not in line:
            continue
        key, value = (part.strip() for part in line.split('=', 1))
        settings[key.lower().replace('_', '-')] = ' '.join(value.split())
    return settings


def dt(profile: str) -> float:
    return float(PROFILES[profile].settings['dt'])


def assessment_ns(settings: dict) -> float:
    """The assessment leg's duration: with removal off it is the whole sampling, there being no second leg."""
    duration = float(settings['assessment_ns'])
    if not settings['remove_out_of_micelle']:
        duration += float(settings['extension_ns'])
    return duration


def restrained(settings: dict, leg: str) -> bool:
    """Whether one leg holds the transient POSRES window; the defaults are minimisation and NPT on, NVT off."""
    setting = pdc_adapter.POSRES_SETTINGS[leg]
    return settings.get(setting, pdc_adapter.DEFAULTS[setting]) == 'yes'


def leg_dt(profile: str, settings: dict, setting: str) -> float:
    """One leg's timestep in ps: its own setting when stated, else the reviewed profile's own."""
    stated = settings.get(setting)
    return float(stated) / 1000 if stated is not None else dt(profile)


def values(profile: str, settings: dict) -> dict:
    """The run's numbers for one profile, computed the way `prepare` computes them."""
    if profile == 'pdc-minimisation-v1':
        numbers = {'nsteps': int(float(settings['minimisation_steps'])),
                   'emtol': settings['pdc_minimisation_emtol'],
                   'emstep': settings['pdc_minimisation_emstep']}
        if restrained(settings, 'minimisation'):
            numbers['define'] = pdc_adapter.POSRES_DEFINE
        return numbers
    if profile == 'pdc-nvt-v1':
        step = leg_dt(profile, settings, pdc_adapter.NVT_TIMESTEP)
        numbers = {'nsteps': round(int(float(settings['nvt_ps'])) / step), 'gen-seed': int(settings['seed']),
                   'nstlist': settings['pdc_nvt_nstlist'], 'ref-t': settings['pdc_nvt_ref_t'],
                   'tau-t': settings['pdc_nvt_tau_t']}
        if pdc_adapter.NVT_TIMESTEP in settings:
            numbers['dt'] = step
        if restrained(settings, 'nvt'):
            numbers['define'] = pdc_adapter.POSRES_DEFINE
        return numbers
    if profile == 'pdc-npt-v1':
        step = leg_dt(profile, settings, pdc_adapter.NPT_TIMESTEP)
        numbers = {'nsteps': round(int(float(settings['npt_ps'])) / step),
                   'nstlist': settings['pdc_npt_nstlist'], 'ref-t': settings['pdc_npt_ref_t'],
                   'tau-t': settings['pdc_npt_tau_t'],
                   'pcoupl': settings['pdc_npt_pcoupl'], 'pcoupltype': settings['pdc_npt_pcoupltype'],
                   'ref-p': settings['pdc_npt_ref_p'], 'tau-p': settings['pdc_npt_tau_p'],
                   'compressibility': settings['pdc_npt_compressibility']}
        if pdc_adapter.NPT_TIMESTEP in settings:
            numbers['dt'] = step
        if restrained(settings, 'npt'):
            numbers['define'] = pdc_adapter.POSRES_DEFINE
            numbers['refcoord-scaling'] = 'com'
        return numbers
    if profile in ('pdc-assessment-v1', 'pdc-extension-v1'):
        # Assessment folds the extension duration only when removal is off; the extension always runs its own.
        if profile == 'pdc-assessment-v1':
            step = leg_dt(profile, settings, pdc_adapter.ASSESSMENT_TIMESTEP)
            numbers = {'nsteps': round(assessment_ns(settings) * 1000 / step)}
            if pdc_adapter.ASSESSMENT_TIMESTEP in settings:
                numbers['dt'] = step
        else:
            step = leg_dt(profile, settings, pdc_adapter.EXTENSION_TIMESTEP)
            numbers = {'nsteps': round(float(settings['extension_ns']) * 1000 / step)}
            if pdc_adapter.EXTENSION_TIMESTEP in settings:
                numbers['dt'] = step
        # The production profile leaves its output cadence, cutoffs and ensemble targets to the run.
        for key, default in PROFILES[profile].settings.items():
            if default is None and key not in numbers:
                numbers[key] = settings[pdc_adapter._MDP_RUN_SETTINGS[key]]
        return numbers
    return {}


def test_every_prepared_mdp_parses_to_its_profiles_rendered_map(tmp_path):
    run = prepared_run(tmp_path, settings={'assessment_ns': 25, 'nvt_ps': 100})
    settings = settings_of(run)

    for name, profile in EXPECTED.items():
        produced = parsed((inputs_dir(run) / name).read_text())
        expected = parsed(render(profile, values(profile, settings)))
        assert produced == expected, name


def test_the_manifest_names_the_profile_behind_every_prepared_mdp(tmp_path):
    record = json.loads((prepared_run(tmp_path) / 'manifest.json').read_text())

    assert record['mdp_profiles'] == EXPECTED, 'a reader can name the physics without opening a file'


def test_a_file_prepare_did_not_write_is_not_recorded(tmp_path):
    """A skipped leg and a removed extension leave no file, so the record names no profile for one."""
    run = prepared_run(tmp_path, settings={'remove_out_of_micelle': False,
                                           'minimisation_steps': 0, 'nvt_ps': 0, 'npt_ps': 0})
    record = json.loads((run / 'manifest.json').read_text())

    assert record['mdp_profiles'] == {'assessment.mdp': 'pdc-assessment-v1'}
    assert not (inputs_dir(run) / 'ions.mdp').exists()


def test_the_other_run_options_reach_both_production_mdps(tmp_path):
    run = prepared_run(tmp_path, settings={'nstlog': 250, 'nstenergy': 50, 'nstxtcout': 500,
                                           'pdc_production_ref_t': 310, 'pdc_production_tau_p': 20.0,
                                           'rvdw': 1.2})

    for name in ('assessment.mdp', 'extension.mdp'):
        written = parsed((inputs_dir(run) / name).read_text())
        assert written['nstlog'] == '250' and written['nstenergy'] == '50'
        assert written['nstxtcout'] == '500' and written['xtc-precision'] == '1000'
        assert written['ref-t'] == '310' and written['tau-p'] == '20' and written['rvdw'] == '1.2'


def test_an_untouched_run_renders_the_reviewed_equilibration_files_byte_for_byte(tmp_path):
    """The per-leg physics writes the reviewed number back: the file an untouched run renders does not move.

    `render` at the run's arithmetic only is the reviewed file, so any difference from the prepared text would be a
    physics change this slice did not ask for.
    """
    run = prepared_run(tmp_path, settings={'nvt_ps': 500, 'npt_ps': 4500})
    settings = settings_of(run)

    expected = {
        'nvt.mdp': render('pdc-nvt-v1', {'nsteps': round(500 / dt('pdc-nvt-v1')), 'gen-seed': settings['seed']}),
        'npt.mdp': render('pdc-npt-v1', {'nsteps': round(4500 / dt('pdc-npt-v1')),
                                         'define': pdc_adapter.POSRES_DEFINE, 'refcoord-scaling': 'com'}),
    }
    for name, text in expected.items():
        assert (inputs_dir(run) / name).read_text() == text, name


def test_each_equilibration_leg_carries_its_own_neighbour_list_temperature_and_thermostat(tmp_path):
    """NVT and NPT are separate settings, and neither reaches the other leg nor the production files."""
    run = prepared_run(tmp_path, settings={'pdc_nvt_nstlist': 80, 'pdc_nvt_ref_t': 310, 'pdc_nvt_tau_t': 2.0,
                                           'pdc_npt_nstlist': 20, 'pdc_npt_ref_t': 320, 'pdc_npt_tau_t': 0.5,
                                           'nvt_ps': 500, 'npt_ps': 4500})
    nvt = parsed((inputs_dir(run) / 'nvt.mdp').read_text())
    npt = parsed((inputs_dir(run) / 'npt.mdp').read_text())

    assert (nvt['nstlist'], nvt['ref-t'], nvt['tau-t']) == ('80', '310', '2')
    assert (npt['nstlist'], npt['ref-t'], npt['tau-t']) == ('20', '320', '0.5')
    for name in ('assessment.mdp', 'extension.mdp'):
        production = parsed((inputs_dir(run) / name).read_text())
        assert (production['nstlist'], production['ref-t'], production['tau-t']) == ('40', '300', '1'), name
    # The minimisation is not integrated, so the per-leg physics cannot reach its pinned neighbour list.
    assert parsed((inputs_dir(run) / 'minimisation.mdp').read_text())['nstlist'] == '20'


def test_the_production_physics_set_reaches_both_production_files(tmp_path):
    run = prepared_run(tmp_path, settings={'pdc_production_nstlist': 80, 'pdc_production_ref_t': 320,
                                           'pdc_production_tau_t': 2.0, 'pdc_production_ref_p': 2.0,
                                           'pdc_production_tau_p': 20.0,
                                           'pdc_production_compressibility': 1e-4})
    for name in ('assessment.mdp', 'extension.mdp'):
        written = parsed((inputs_dir(run) / name).read_text())
        assert (written['nstlist'], written['ref-t'], written['tau-t']) == ('80', '320', '2'), name
        assert (float(written['ref-p']), float(written['tau-p']),
                float(written['compressibility'])) == (2.0, 20.0, 1e-4), name
    # The equilibration legs keep the reviewed numbers: the production set is not run-wide.
    for name in ('nvt.mdp', 'npt.mdp'):
        written = parsed((inputs_dir(run) / name).read_text())
        assert (written['nstlist'], written['ref-t'], written['tau-t']) == ('40', '300', '1'), name


def test_an_unset_timestep_keeps_the_reviewed_profiles_own_number(tmp_path):
    """(a) Nothing named: every leg writes its profile's dt, and the steps its ps duration is at that dt."""
    run = prepared_run(tmp_path, settings={'nvt_ps': 500, 'npt_ps': 4500, 'assessment_ns': 100})
    settings = settings_of(run)
    manifest = json.loads((run / 'manifest.json').read_text())

    assert not {pdc_adapter.NVT_TIMESTEP, pdc_adapter.NPT_TIMESTEP, pdc_adapter.ASSESSMENT_TIMESTEP,
                pdc_adapter.EXTENSION_TIMESTEP} & set(settings)
    nvt = parsed((inputs_dir(run) / 'nvt.mdp').read_text())
    npt = parsed((inputs_dir(run) / 'npt.mdp').read_text())
    assessment = parsed((inputs_dir(run) / 'assessment.mdp').read_text())
    extension = parsed((inputs_dir(run) / 'extension.mdp').read_text())
    assert float(nvt['dt']) == dt('pdc-nvt-v1') == 0.005
    assert int(nvt['nsteps']) == round(500 / 0.005)
    assert float(npt['dt']) == 0.005 and int(npt['nsteps']) == round(4500 / 0.005)
    assert float(assessment['dt']) == dt('pdc-assessment-v1') == 0.02
    assert int(assessment['nsteps']) == round(100_000 / 0.02)
    # The extension's own file states its own duration at the reviewed production dt, not the assessment's step count.
    assert float(extension['dt']) == 0.02 and int(extension['nsteps']) == round(900_000 / 0.02)
    assert manifest['equilibration_steps'] == {'minimisation': 200000, 'nvt': 100000, 'npt': 900000}
    assert manifest['assessment_steps'] == 5_000_000


def test_an_equilibration_timestep_moves_the_nvt_and_npt_legs_only(tmp_path):
    """(b) The retired equilibration setting is translated; it rewrites NVT/NPT dt, never production."""
    run = prepared_run(tmp_path, settings={'pdc_equil_dt_fs': 10, 'nvt_ps': 500, 'npt_ps': 4500,
                                           'assessment_ns': 100})
    settings = settings_of(run)
    manifest = json.loads((run / 'manifest.json').read_text())
    nvt = parsed((inputs_dir(run) / 'nvt.mdp').read_text())
    npt = parsed((inputs_dir(run) / 'npt.mdp').read_text())

    assert 'pdc_equil_dt_fs' not in settings
    assert (settings['pdc_nvt_dt_fs'], settings['pdc_npt_dt_fs']) == (10, 10)
    assert (manifest['settings']['pdc_nvt_dt_fs'], manifest['settings']['pdc_npt_dt_fs']) == (10, 10)
    assert float(nvt['dt']) == 0.01 and int(nvt['nsteps']) == round(500 / 0.01)
    assert float(npt['dt']) == 0.01 and int(npt['nsteps']) == round(4500 / 0.01)
    assert manifest['equilibration_steps'] == {'minimisation': 200000, 'nvt': 50000, 'npt': 450000}
    for name in ('assessment.mdp', 'extension.mdp'):
        production = parsed((inputs_dir(run) / name).read_text())
        assert float(production['dt']) == dt('pdc-assessment-v1') == 0.02, name
    assert manifest['assessment_steps'] == round(100_000 / 0.02)


def test_each_equilibration_leg_can_carry_its_own_timestep(tmp_path):
    """NVT and NPT are separate settings, so one leg can integrate finer than the other."""
    run = prepared_run(tmp_path, settings={'pdc_nvt_dt_fs': 2, 'pdc_npt_dt_fs': 10,
                                           'nvt_ps': 500, 'npt_ps': 4500})
    nvt = parsed((inputs_dir(run) / 'nvt.mdp').read_text())
    npt = parsed((inputs_dir(run) / 'npt.mdp').read_text())

    assert float(nvt['dt']) == 0.002 and int(nvt['nsteps']) == round(500 / 0.002)
    assert float(npt['dt']) == 0.01 and int(npt['nsteps']) == round(4500 / 0.01)


def test_a_production_timestep_moves_the_production_legs_only(tmp_path):
    """(c) The retired production setting rewrites assessment/extension dt and their own step counts."""
    run = prepared_run(tmp_path, settings={'pdc_production_dt_fs': 10, 'nvt_ps': 500, 'npt_ps': 4500,
                                           'assessment_ns': 100, 'extension_ns': 900})
    manifest = json.loads((run / 'manifest.json').read_text())
    assessment = parsed((inputs_dir(run) / 'assessment.mdp').read_text())
    extension = parsed((inputs_dir(run) / 'extension.mdp').read_text())

    assert 'pdc_production_dt_fs' not in manifest['settings']
    assert (manifest['settings']['pdc_assessment_dt_fs'],
            manifest['settings']['pdc_extension_dt_fs']) == (10, 10)
    assert float(assessment['dt']) == 0.01
    assert int(assessment['nsteps']) == round(100_000 / 0.01) == 10_000_000
    assert float(extension['dt']) == 0.01
    # The extension's own duration at its own dt, not the assessment's step count: 900 ns, not 100.
    assert int(extension['nsteps']) == round(900_000 / 0.01) == 90_000_000
    assert manifest['assessment_steps'] == 10_000_000
    for name, profile, ps in (('nvt.mdp', 'pdc-nvt-v1', 500), ('npt.mdp', 'pdc-npt-v1', 4500)):
        leg = parsed((inputs_dir(run) / name).read_text())
        assert float(leg['dt']) == dt(profile) == 0.005, name
        assert int(leg['nsteps']) == round(ps / 0.005), name
    assert manifest['equilibration_steps'] == {'minimisation': 200000, 'nvt': 100000, 'npt': 900000}


def test_a_production_timestep_converts_the_folded_duration_when_removal_is_off(tmp_path):
    """The removal-off assessment folds both durations, and the override converts the folded ps in one place."""
    run = prepared_run(tmp_path, settings={'remove_out_of_micelle': False, 'pdc_assessment_dt_fs': 10,
                                           'assessment_ns': 100, 'extension_ns': 900})
    assessment = parsed((inputs_dir(run) / 'assessment.mdp').read_text())

    assert float(assessment['dt']) == 0.01
    assert int(assessment['nsteps']) == round(1_000_000 / 0.01) == 100_000_000


def test_no_prepared_mdp_is_a_copied_template(tmp_path):
    """Each file begins with the writer's own header naming its profile, which no copied template could."""
    run = prepared_run(tmp_path)

    for name, profile in EXPECTED.items():
        text = (inputs_dir(run) / name).read_text()
        assert text.startswith(f'; {profile}: reviewed physics profile'), name



# --- the transient POSRES window and the minimisation/NPT tunables -------------------------------------------------

#: The legs whose files must never carry the POSRES define: the window belongs to minimisation and NPT only, and the
#: production/restart files are the reviewed physics the run is not allowed to reach.
UNRESTRAINED = ('nvt.mdp', 'assessment.mdp', 'extension.mdp', 'minimization.mdp', 'equilibration.mdp')


def manifest_profile(run, name: str) -> str:
    return json.loads((run / 'manifest.json').read_text())['mdp_profiles'][name]


def test_unstated_settings_write_the_restraint_window_only_where_it_acts(tmp_path):
    """(a) Nothing named: the reviewed MDPs, plus the default window in minimisation and NPT and nowhere else."""
    run = prepared_run(tmp_path)

    minimisation = parsed((inputs_dir(run) / 'minimisation.mdp').read_text())
    npt = parsed((inputs_dir(run) / 'npt.mdp').read_text())
    assert minimisation['define'] == '-DPOSRES'
    assert npt['define'] == '-DPOSRES' and npt['refcoord-scaling'] == 'com'
    for name in UNRESTRAINED:
        written = parsed((inputs_dir(run) / name).read_text())
        # The restart minimisation keeps the CG template's own -DFLEXIBLE; the POSRES define is what must not reach
        # any of these files, and refcoord-scaling belongs to the NPT leg alone.
        assert written.get('define') != '-DPOSRES', name
        assert 'refcoord-scaling' not in written, name


def test_switching_a_legs_restraint_window_off_leaves_only_that_leg_unrestrained(tmp_path):
    """Each leg's choice is its own switch: two legs off renders their reviewed files with no define at all."""
    run = prepared_run(tmp_path, settings={'pdc_posres_min': 'no', 'pdc_posres_npt': 'no'})
    settings = settings_of(run)

    assert (settings['pdc_posres_min'], settings['pdc_posres_nvt'],
            settings['pdc_posres_npt']) == ('no', 'no', 'no')
    for name in ('minimisation.mdp', 'nvt.mdp', 'npt.mdp'):
        written = parsed((inputs_dir(run) / name).read_text())
        assert 'define' not in written, name
    assert 'refcoord-scaling' not in parsed((inputs_dir(run) / 'npt.mdp').read_text())
    assert manifest_profile(run, 'minimisation.mdp') == 'pdc-minimisation-v1'


def test_one_leg_can_hold_the_window_while_its_neighbours_do_not(tmp_path):
    """The NVT leg is the one the reference protocol leaves free; asking for it there restrains that leg alone."""
    run = prepared_run(tmp_path, settings={'pdc_posres_min': 'no', 'pdc_posres_nvt': 'yes',
                                           'pdc_posres_npt': 'no'})
    nvt = parsed((inputs_dir(run) / 'nvt.mdp').read_text())

    assert nvt['define'] == '-DPOSRES'
    # No barostat in this leg, so nothing can move the reference coordinates it restrains against.
    assert 'refcoord-scaling' not in nvt
    for name in ('minimisation.mdp', 'npt.mdp'):
        assert 'define' not in parsed((inputs_dir(run) / name).read_text()), name


def test_the_retired_single_choice_still_means_minimisation_and_npt(tmp_path):
    """A form saved before the split sends one yes/no; it is translated, and the record carries one answer."""
    run = prepared_run(tmp_path, settings={'pdc_restrain_protein': 'yes'})
    settings = settings_of(run)

    assert 'pdc_restrain_protein' not in settings
    assert (settings['pdc_posres_min'], settings['pdc_posres_nvt'],
            settings['pdc_posres_npt']) == ('yes', 'no', 'yes')
    assert parsed((inputs_dir(run) / 'nvt.mdp').read_text()).get('define') != '-DPOSRES'

    off = prepared_run(tmp_path / 'off', settings={'pdc_restrain_protein': 'no'})
    for name in ('minimisation.mdp', 'npt.mdp'):
        assert 'define' not in parsed((inputs_dir(off) / name).read_text()), name


def test_a_minimisation_tunable_reaches_only_the_minimisation_leg(tmp_path):
    """(b) emtol/emstep are the minimisation's own; every other file keeps the reviewed numbers."""
    run = prepared_run(tmp_path, settings={'pdc_minimisation_emtol': 250, 'pdc_minimisation_emstep': 0.002})
    settings = settings_of(run)
    minimisation = parsed((inputs_dir(run) / 'minimisation.mdp').read_text())
    npt = parsed((inputs_dir(run) / 'npt.mdp').read_text())

    assert settings['pdc_minimisation_emtol'] == 250 and settings['pdc_minimisation_emstep'] == 0.002
    assert minimisation['emtol'] == '250' and minimisation['emstep'] == '0.002'
    for other in ('nvt.mdp', 'npt.mdp', 'assessment.mdp', 'extension.mdp'):
        written = parsed((inputs_dir(run) / other).read_text())
        assert 'emtol' not in written and 'emstep' not in written, other
    assert npt['pcoupl'] == 'c-rescale', 'the NPT leg keeps its own barostat'


def test_an_npt_barostat_override_reaches_only_the_npt_leg(tmp_path):
    """(b) The equilibration barostat is the NPT leg's; production keeps its reviewed Parrinello-Rahman trio."""
    run = prepared_run(tmp_path, settings={'pdc_npt_pcoupl': 'berendsen', 'pdc_npt_pcoupltype': 'semiisotropic',
                                           'pdc_npt_ref_p': 2.5, 'pdc_npt_tau_p': 8.0,
                                           'pdc_npt_compressibility': 1e-4})
    settings = settings_of(run)
    npt = parsed((inputs_dir(run) / 'npt.mdp').read_text())

    assert (settings['pdc_npt_pcoupl'], settings['pdc_npt_pcoupltype']) == ('berendsen', 'semiisotropic')
    assert (npt['pcoupl'], npt['pcoupltype'], npt['ref-p']) == ('berendsen', 'semiisotropic', '2.5 2.5')
    assert float(npt['tau-p']) == 8.0 and npt['compressibility'] == '0.0001 0.0001'
    for name in ('assessment.mdp', 'extension.mdp'):
        production = parsed((inputs_dir(run) / name).read_text())
        assert (production['pcoupl'], production['pcoupltype']) == ('parrinello-rahman', 'isotropic'), name
        assert float(production['ref-p']) == 1.0 and float(production['tau-p']) == 12.0, name
        assert float(production['compressibility']) == 4.5e-5, name
    assert parsed((inputs_dir(run) / 'minimisation.mdp').read_text())['nsteps'] == '200000'


def test_unknown_barostat_choices_and_out_of_range_tunables_are_refused_by_name():
    """(c) The form's two selects and the three numbers are the adapter's vocabulary, so a typo is its own refusal."""
    with pytest.raises(ValueError, match='pdc_npt_pcoupl must be one of no, berendsen, parrinello-rahman, c-rescale'):
        pdc_adapter.normalize_settings({'pdc_npt_pcoupl': 'andersen'})
    with pytest.raises(ValueError, match='pdc_npt_pcoupltype must be one of'):
        pdc_adapter.normalize_settings({'pdc_npt_pcoupltype': 'rhombic'})
    for setting, low, high in (('pdc_minimisation_emtol', 0.1, 10000), ('pdc_minimisation_emstep', 0.0001, 0.01),
                               ('pdc_npt_ref_p', 0.1, 100), ('pdc_npt_tau_p', 0.1, 100),
                               ('pdc_npt_compressibility', 0.0, 1.0)):
        below = low / 10 if low else -1.0
        for value in (below, high * 10):
            with pytest.raises(ValueError, match=rf'{setting} must be between'):
                pdc_adapter.normalize_settings({setting: value})


def test_the_restraint_choices_are_advertised_per_leg_and_default_to_the_reference_window():
    """(a) One choice per leg, kept by the route, defaulting to minimisation + NPT and validated by name."""
    for leg, setting in pdc_adapter.POSRES_SETTINGS.items():
        assert pdc_adapter.CHOICE_SPECS[setting][1] == ('yes', 'no'), leg
        assert setting in pdc_adapter.PROTOCOL.choice_specs(), leg
        with pytest.raises(ValueError, match=rf'{setting} must be one of yes, no'):
            pdc_adapter.normalize_settings({setting: 'maybe'})
    assert (pdc_adapter.DEFAULTS['pdc_posres_min'], pdc_adapter.DEFAULTS['pdc_posres_nvt'],
            pdc_adapter.DEFAULTS['pdc_posres_npt']) == ('yes', 'no', 'yes')



def test_an_empty_micelle_writes_no_restraint_window(tmp_path):
    """There is no protein block to activate, so no leg's window acts even though the defaults ask for two."""
    run = prepared_run(tmp_path, protein=None)
    settings = settings_of(run)

    assert (settings['pdc_posres_min'], settings['pdc_posres_npt']) == ('yes', 'yes')
    for name in ('minimisation.mdp', 'nvt.mdp', 'npt.mdp'):
        assert 'define' not in parsed((inputs_dir(run) / name).read_text()), name
