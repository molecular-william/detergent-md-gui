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

from dashboard.execution.adapters import pdc as pdc_adapter
from dashboard.execution.mdp import PROFILES, render
from tests.dashboard.pdc_fixtures import inputs_dir, prepared_run, settings_of

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


def values(profile: str, settings: dict) -> dict:
    """The run's numbers for one profile, computed the way `prepare` computes them."""
    if profile == 'pdc-minimisation-v1':
        return {'nsteps': int(float(settings['minimisation_steps']))}
    if profile == 'pdc-nvt-v1':
        return {'nsteps': round(int(float(settings['nvt_ps'])) / dt(profile)), 'gen-seed': int(settings['seed'])}
    if profile == 'pdc-npt-v1':
        return {'nsteps': round(int(float(settings['npt_ps'])) / dt(profile))}
    if profile in ('pdc-assessment-v1', 'pdc-extension-v1'):
        numbers = {'nsteps': round(assessment_ns(settings) * 1000 / dt('pdc-assessment-v1'))}
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
                                           'ref_t': 310, 'tau_p': 20.0, 'rvdw': 1.2})

    for name in ('assessment.mdp', 'extension.mdp'):
        written = parsed((inputs_dir(run) / name).read_text())
        assert written['nstlog'] == '250' and written['nstenergy'] == '50'
        assert written['nstxtcout'] == '500' and written['xtc-precision'] == '1000'
        assert written['ref-t'] == '310' and written['tau-p'] == '20' and written['rvdw'] == '1.2'


def test_no_prepared_mdp_is_a_copied_template(tmp_path):
    """Each file begins with the writer's own header naming its profile, which no copied template could."""
    run = prepared_run(tmp_path)

    for name, profile in EXPECTED.items():
        text = (inputs_dir(run) / name).read_text()
        assert text.startswith(f'; {profile}: reviewed physics profile'), name
