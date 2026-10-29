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
from dashboard.execution.adapters import pdc
from tests.dashboard.pdc_fixtures import molecule_tree

TEMPLATE = {
    'name': 'DDM',
    'residue': 'DDM',
    'coordinates': 'results/MMFF/lig1.pdb',
    'topology': 'results/MMFF/lig1.itp',
    'beads': [{'name': 'DDM', 'type': 'registered-template'}],
}




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
    assert manifest['layout_version'] == 3
    assert (run / 'stages' / '02_system').is_dir()
    assert (run / 'inputs' / pdc.SETTINGS_NAME).is_file()
    assert (run / 'inputs' / 'inputs.json').is_file()
    assert manifest['input_snapshot_sha256']
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
