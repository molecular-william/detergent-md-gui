"""The pdc run type as the application sees it: a registered protocol, and a dispatch that reaches the builder.

`pdc.py` carried the catalogue, the settings and the six-stage contract and was registered nowhere: `adapter_for`
raised `Unknown run type: pdc`, so the API could not list a pdc run's stages and `prepare_run` would have gone to
`cg.prepare`, which demands a molecule snapshot a PDC build does not have. These tests pin the registration, the
contract's shape, what readiness says, and that a pdc job's prepared manifest carries the pdc stages.

They build their own molecule tree; nothing here reads the developer's `molecules/`.
"""
from __future__ import annotations

import json

import pytest
from dashboard.execution import protocol
from detergent_pdc.execution.adapters import pdc

from tests.harness.pdc_fixtures import TEMPLATE, molecule_tree, prepared_run, settings_of

pytestmark = pytest.mark.usefixtures('gpu_host')




def test_the_run_type_is_registered():
    assert protocol.adapter_for('pdc').name == 'pdc'


def test_an_unknown_run_type_still_raises():
    with pytest.raises(ValueError, match='Unknown run type'):
        protocol.adapter_for('protein_detergent')


def test_the_contract_publishes_the_plan_as_pairs():
    plan, inputs, outputs = protocol.adapter_for('pdc').stage_contract({})

    assert plan == [[stage.name, stage.relative] for stage in pdc.STAGES]
    assert list(inputs)[0] == pdc.STAGES[0].name and inputs[pdc.STAGES[0].name] == list(pdc.STAGES[0].inputs)
    assert outputs[pdc.STAGES[-1].name] == list(pdc.STAGES[-1].outputs)


def test_the_stage_records_and_the_defaults_are_the_adapters_own():
    adapter = protocol.adapter_for('pdc')

    assert [stage.relative for stage in adapter.stages({})] == [stage.relative for stage in pdc.STAGES]
    assert adapter.stage_defaults() == pdc.DEFAULTS
    assert adapter.settings_specs() == pdc.SETTING_SPECS


def test_normalize_settings_speaks_the_builders_spelling():
    adapter = protocol.adapter_for('pdc')

    numbers = adapter.normalize_settings({'pdc_seed': 4242, 'pdc_extension_ns': 300})

    assert numbers['seed'] == 4242 and numbers['extension_ns'] == 300
    assert numbers['aggregation_number'] == pdc.DEFAULTS['aggregation_number']


def test_a_pdc_setting_is_held_to_the_bounds_the_adapter_publishes():
    """The specs used to be decoration: any advertised key was copied, any other dropped.

    A negative duration reached GROMACS as `nsteps = -...` three stages into a build, and a typo became a default with
    no word -- where aa, cg and osmotic all raise for both. One reader now enforces the bounds it publishes.
    """
    adapter = protocol.adapter_for('pdc')

    for supplied, message in [({'pdc_assessment_ns': -5}, 'assessment_ns must be between 1 and 100000'),
                              ({'aggregation_number': 10 ** 9}, 'aggregation_number must be between 1 and 1000'),
                              ({'salt_molar': 99}, 'salt_molar must be between 0.0 and 5.0'),
                              ({'bogus_key': 1}, 'Unknown PDC setting: bogus_key'),
                              ({'pdc_npt_ps': 'abc'}, 'npt_ps must be numeric'),
                              ({'pdc_seed': 4.5}, 'seed must be an integer'),
                              ({'pdc_nvt_dt_fs': 0.4}, 'pdc_nvt_dt_fs must be between 0.5 and 20'),
                              ({'pdc_npt_dt_fs': 25}, 'pdc_npt_dt_fs must be between 0.5 and 20'),
                              ({'pdc_assessment_dt_fs': 60}, 'pdc_assessment_dt_fs must be between 0.5 and 50'),
                              ({'pdc_extension_dt_fs': 0.4}, 'pdc_extension_dt_fs must be between 0.5 and 50'),
                              ({'backmap': 'yes'}, 'backmap must be one of True, False')]:
        with pytest.raises(ValueError) as refused:
            adapter.normalize_settings(supplied)
        assert message in str(refused.value), (supplied, str(refused.value))


def test_a_setting_supplied_under_either_spelling_reaches_the_builder_the_same_way():
    """The alias is a spelling, not a second setting: both forms are bounded, and both land on one key."""
    adapter = protocol.adapter_for('pdc')

    long_form = adapter.normalize_settings({'pdc_seed': 4242, 'pdc_nvt_ps': 0})
    short_form = adapter.normalize_settings({'seed': 4242, 'nvt_ps': 0})

    assert long_form['seed'] == short_form['seed'] == 4242
    assert long_form['nvt_ps'] == short_form['nvt_ps'] == 0
    # `0` is a request for none of that leg rather than a very short one, which is why the bound starts there.
    assert long_form['npt_ps'] == adapter.stage_defaults()['npt_ps']


def test_each_leg_advertises_its_own_timestep_with_the_cg_bounds_and_no_default():
    """The form's four controls must survive the queue's advertised-key filter and start as each profile's own dt."""
    adapter = protocol.adapter_for('pdc')
    specs = adapter.settings_specs()

    assert specs['pdc_nvt_dt_fs'] == ('CG NVT timestep (fs)', 0.5, 20)
    assert specs['pdc_npt_dt_fs'] == ('CG NPT timestep (fs)', 0.5, 20)
    assert specs['pdc_assessment_dt_fs'] == ('CG assessment timestep (fs)', 0.5, 50)
    assert specs['pdc_extension_dt_fs'] == ('CG extension timestep (fs)', 0.5, 50)
    for setting in ('pdc_nvt_dt_fs', 'pdc_npt_dt_fs', 'pdc_assessment_dt_fs', 'pdc_extension_dt_fs'):
        assert setting not in adapter.stage_defaults(), 'unset means the reviewed profile dt'
    # The retired spellings stay advertised so a payload, preset or clone written before the split still validates;
    # a run never renders them, because `_numbers` translates them to the per-leg pair.
    assert specs['pdc_equil_dt_fs'] == ('Equilibration timestep (fs)', 0.5, 20)
    assert specs['pdc_production_dt_fs'] == ('Production timestep (fs)', 0.5, 50)


def test_the_per_leg_physics_settings_are_advertised_with_reviewed_defaults():
    """The form's new physics controls must survive the queue and start at each profile's own number."""
    adapter = protocol.adapter_for('pdc')
    specs = adapter.settings_specs()
    defaults = adapter.stage_defaults()

    expected = {
        'pdc_nvt_nstlist': ('CG NVT neighbour-list rebuild', 1, 10000, 40),
        'pdc_nvt_ref_t': ('CG NVT temperature (K)', 200, 500, 300),
        'pdc_nvt_tau_t': ('CG NVT thermostat coupling (ps)', 0.01, 100, 1.0),
        'pdc_npt_nstlist': ('CG NPT neighbour-list rebuild', 1, 10000, 40),
        'pdc_npt_ref_t': ('CG NPT temperature (K)', 200, 500, 300),
        'pdc_npt_tau_t': ('CG NPT thermostat coupling (ps)', 0.01, 100, 1.0),
        'pdc_production_nstlist': ('CG production neighbour-list rebuild', 1, 10000, 40),
        'pdc_production_ref_t': ('CG production temperature (K)', 200, 500, 300),
        'pdc_production_tau_t': ('CG production thermostat coupling (ps)', 0.01, 100, 1.0),
        'pdc_production_ref_p': ('CG production pressure (bar)', 0.1, 100, 1.0),
        'pdc_production_tau_p': ('CG production barostat coupling (ps)', 0.1, 100, 12.0),
        'pdc_production_compressibility': ('CG production compressibility (bar^-1)', 0, 1, 4.5e-5),
    }
    for setting, (label, low, high, default) in expected.items():
        assert specs[setting] == (label, low, high), setting
        assert defaults[setting] == default, setting
    # The run-wide physics names stay advertised for an old payload, and are no longer written into a new record.
    for setting in ('nstlist', 'ref_t', 'tau_t', 'ref_p', 'tau_p', 'compressibility'):
        assert setting in specs, setting
        assert setting not in defaults, setting


def test_the_retired_run_wide_physics_translates_onto_the_production_names():
    """Old payloads and presets still name the run-wide physics; it now means the shared production set."""
    adapter = protocol.adapter_for('pdc')
    retired = {'nstlist': 80, 'ref_t': 320, 'tau_t': 2.0, 'ref_p': 2.0, 'tau_p': 20.0,
               'compressibility': 1e-4}

    numbers = adapter.normalize_settings(dict(retired))

    assert {setting: numbers[f'pdc_production_{setting}'] for setting in retired} == retired
    assert not retired.keys() & numbers.keys(), 'a recorded run cannot carry two answers to one question'
    # A supplied production number wins over the retired spelling, and the retired key is still dropped.
    mixed = adapter.normalize_settings({'ref_t': 320, 'pdc_production_ref_t': 310})
    assert mixed['pdc_production_ref_t'] == 310 and 'ref_t' not in mixed


def test_an_old_payload_still_prepares_and_records_only_the_per_leg_names(tmp_path):
    run = prepared_run(tmp_path, settings={'ref_t': 310, 'nstlist': 80})
    record = json.loads((run / 'manifest.json').read_text())['settings']

    assert record['pdc_production_ref_t'] == 310 and record['pdc_production_nstlist'] == 80
    assert 'ref_t' not in record and 'nstlist' not in record
    assert settings_of(run)['pdc_production_ref_t'] == 310


def test_mdrun_update_is_advertised_kept_and_reaches_the_flag_builder():
    """The pdc manifest's settings are what `workflow` hands `aa.mdrun_command_flags`, so one builder decides."""
    from dashboard.execution.adapters import aa

    label, options = pdc.CHOICE_SPECS['mdrun_update']
    assert (label, options) == ('Update and constraints', ('auto', 'cpu', 'gpu'))
    assert pdc.DEFAULTS['mdrun_update'] == 'auto'
    assert 'mdrun_update' in dict(pdc.PROTOCOL.choice_specs())

    numbers = pdc.PROTOCOL.normalize_settings({'mdrun_update': 'cpu'})
    assert numbers['mdrun_update'] == 'cpu'
    _, flags = aa.mdrun_command_flags(numbers, 'equilibration', 'mpi', pme=False)
    assert '-update cpu' in flags, 'the run setting must reach mdrun, not just the record'


def test_the_equilibration_profiles_mark_their_physics_as_the_runs_own():
    from dashboard.execution.mdp import PROFILES

    for version in ('pdc-nvt-v1', 'pdc-npt-v1'):
        variable = PROFILES[version].variable
        for key in ('nstlist', 'ref-t', 'tau-t'):
            assert key in variable, (version, key)



    """One old equilibration dt means both equilibration legs; one old production dt means both production legs."""
    adapter = protocol.adapter_for('pdc')
    legs = ('pdc_nvt_dt_fs', 'pdc_npt_dt_fs', 'pdc_assessment_dt_fs', 'pdc_extension_dt_fs')

    retired = adapter.normalize_settings({'pdc_equil_dt_fs': 7.5, 'pdc_production_dt_fs': 25})
    supplied = adapter.normalize_settings({'pdc_nvt_dt_fs': 7.5, 'pdc_npt_dt_fs': 7.5,
                                           'pdc_assessment_dt_fs': 25, 'pdc_extension_dt_fs': 25})

    assert {key: retired[key] for key in legs} == {key: supplied[key] for key in legs} == {
        'pdc_nvt_dt_fs': 7.5, 'pdc_npt_dt_fs': 7.5,
        'pdc_assessment_dt_fs': 25, 'pdc_extension_dt_fs': 25}
    assert 'pdc_equil_dt_fs' not in retired and 'pdc_production_dt_fs' not in retired, \
        'the record cannot carry two answers to one question'


def test_stating_a_per_leg_timestep_drops_the_retired_keys_without_inventing_the_others():
    """A caller that states new keys states its own; the retired pair is not allowed to fill in the missing legs."""
    adapter = protocol.adapter_for('pdc')

    numbers = adapter.normalize_settings({'pdc_nvt_dt_fs': 10, 'pdc_equil_dt_fs': 20,
                                          'pdc_production_dt_fs': 30})

    assert numbers['pdc_nvt_dt_fs'] == 10
    for setting in ('pdc_npt_dt_fs', 'pdc_assessment_dt_fs', 'pdc_extension_dt_fs',
                    'pdc_equil_dt_fs', 'pdc_production_dt_fs'):
        assert setting not in numbers, setting


def test_a_timestep_that_leaves_a_leg_at_no_step_is_refused_by_name():
    """A dt coarser than a requested leg would ask mdrun for nothing; the refusal names that leg's own setting."""
    adapter = protocol.adapter_for('pdc')

    with pytest.raises(ValueError, match='pdc_nvt_dt_fs = 20 fs leaves the NVT equilibration at 0 steps'):
        adapter.normalize_settings({'pdc_nvt_ps': 0.01, 'pdc_nvt_dt_fs': 20})
    with pytest.raises(ValueError, match='pdc_npt_dt_fs = 20 fs leaves the NPT equilibration at 0 steps'):
        adapter.normalize_settings({'pdc_npt_ps': 0.01, 'pdc_npt_dt_fs': 20})
    # The assessment's duration floor is 1 ns and its coarsest step 50 fs, so a 0-step assessment is unreachable
    # from the form; the guard is told so directly.
    with pytest.raises(ValueError, match='pdc_assessment_dt_fs = 50 fs leaves the CG assessment MD at 0 steps'):
        pdc._refuse_a_zero_step_leg({'assessment_ns': 0.00001, 'pdc_assessment_dt_fs': 50})
    # The zero-duration leg is a skip request rather than a zero-step run, so the same timestep is not refused alone.
    assert adapter.normalize_settings({'pdc_nvt_ps': 0, 'pdc_nvt_dt_fs': 20})['pdc_nvt_dt_fs'] == 20


def test_the_extension_timestep_is_guarded_only_when_that_stage_will_run():
    """The form's 1 ns floor never rounds to 0 steps, so the guard is pinned where it lives.

    With removal off the extension stage is skipped and its duration is folded into the assessment leg, so the
    extension's own timestep has no leg to leave empty.
    """
    with pytest.raises(ValueError, match='pdc_extension_dt_fs = 50 fs leaves the CG extension MD at 0 steps'):
        pdc._refuse_a_zero_step_leg({'extension_ns': 0.00001, 'pdc_extension_dt_fs': 50})
    pdc._refuse_a_zero_step_leg({'extension_ns': 0.00001, 'pdc_extension_dt_fs': 50,
                                 'remove_out_of_micelle': False})


def test_prepare_refuses_the_timestep_that_would_run_no_step(tmp_path):
    """The guard is in the one normalizer `prepare` reads, so the run is refused before a stage is written."""
    with pytest.raises(ValueError, match='pdc_nvt_dt_fs'):
        prepared_run(tmp_path, settings={'nvt_ps': 0.01, 'pdc_nvt_dt_fs': 20})


def test_the_production_output_cadence_is_a_run_setting():
    """The production legs take their cadences from the run; the retired snapshot cadence is no longer a setting."""
    adapter = protocol.adapter_for('pdc')

    numbers = adapter.normalize_settings({'nstlog': 250, 'nstenergy': 50, 'nstxtcout': 500})

    assert (numbers['nstlog'], numbers['nstenergy'], numbers['nstxtcout']) == (250, 50, 500)
    with pytest.raises(ValueError, match='Unknown PDC setting'):
        adapter.normalize_settings({'snapshot_interval_ns': 500})


def test_a_build_handed_the_whole_record_ignores_what_is_not_a_setting():
    """`settings_from` reads the record `prepare` receives: a label and a protein are not numbers it has an opinion on."""
    numbers = pdc.settings_from({'label': 'DDM belt', 'protein': '1AT9', 'template': 't.json',
                                 'pdc_assessment_ns': 50, 'aggregation_number': 80})

    assert numbers['assessment_ns'] == 50 and numbers['aggregation_number'] == 80
    assert 'label' not in numbers and 'protein' not in numbers


def test_readiness_names_what_a_build_is_missing(tmp_path):
    adapter = protocol.adapter_for('pdc')
    molecule_tree(tmp_path, template={**TEMPLATE, 'beads': []})

    answer = adapter.readiness({'project_root': str(tmp_path)})
    assert answer['ready'] is False
    assert any('none selected' in blocker for blocker in answer['blockers'])

    named = adapter.readiness({'protein': 'molecules/DDM/protein.pdb', 'template': 'molecules/DDM/missing.json',
                               'project_root': str(tmp_path)})
    assert any('not a file' in blocker for blocker in named['blockers'])

    refused = adapter.readiness({'protein': 'molecules/DDM/protein.pdb',
                                 'template': 'molecules/DDM/micelle_template.json',
                                 'project_root': str(tmp_path)})
    assert any('no beads' in blocker for blocker in refused['blockers']), 'the template validator is the verdict'
    assert {check['label'] for check in refused['checks']} >= {'Protein', 'Detergent template', 'Template files'}


def test_a_pdc_job_is_prepared_by_the_pdc_builder(tmp_path):
    """The dispatch, end to end: the pdc protocol writes a run whose manifest names the pdc stages."""
    molecule_tree(tmp_path)
    run = tmp_path / 'run'
    run.mkdir()

    protocol.adapter_for('pdc').prepare(run, {
        'protein': 'molecules/DDM/protein.pdb',
        'template': 'molecules/DDM/micelle_template.json',
        'settings': {'seed': 20260930, 'aggregation_number': 8},
        'project_root': str(tmp_path)})

    manifest = json.loads((run / 'manifest.json').read_text())
    assert manifest['run_type'] == 'pdc'
    assert manifest['stage_plan'] == [[stage.name, stage.relative] for stage in pdc.STAGES]
    # One layout: `stages/` holds one directory per running stage, `inputs/` the data prepare synthesized and the
    # record of what the run reads. There is no stage directory at the run root any more.
    assert manifest['layout_version'] == 4
    assert (run / 'stages' / '02_system').is_dir()
    assert (run / 'inputs' / pdc.SETTINGS_NAME).is_file()
    assert (run / 'inputs' / 'inputs.json').is_file()
    assert 'input_snapshot_sha256' not in manifest, 'a named record carries no change-detection digest'
    assert not (run / '1_system').exists(), 'the old run-root stage directory is gone'
    assert set(manifest['tools']) == {'gmx', 'martinize2', 'pdb2pqr'}, \
        'the preparer the optional prepare step runs is recorded with the tools the run always resolves'


def test_removal_is_a_choice_with_a_true_default_and_a_strict_boolean():
    adapter = protocol.adapter_for('pdc')

    assert adapter.stage_defaults()['remove_out_of_micelle'] is True
    assert adapter.normalize_settings({})['remove_out_of_micelle'] is True
    assert adapter.normalize_settings({'remove_out_of_micelle': False})['remove_out_of_micelle'] is False
    with pytest.raises(ValueError, match='remove_out_of_micelle must be one of True, False'):
        adapter.normalize_settings({'remove_out_of_micelle': 'no'})
