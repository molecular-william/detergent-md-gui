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


def test_a_snapshot_interval_longer_than_a_stage_is_not_a_refusal():
    """Unlike the AA half's output interval, this one is not a requirement: a stage that publishes no frame is fine."""
    adapter = protocol.adapter_for('pdc')

    numbers = adapter.normalize_settings({'snapshot_interval_ns': 500, 'pdc_assessment_ns': 10})

    assert numbers['snapshot_interval_ns'] == 500 and numbers['assessment_ns'] == 10


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
    # The pdc build writes its stages at the run root rather than under `stages/`, which is why the analysis layout
    # resolves both spellings. This is the layout a real completed build has -- checked against `8a73fe6448f2`.
    assert (run / '1_system' / 'prepare_system.sh').is_file()
    assert (run / '1_system' / pdc.SETTINGS_NAME).is_file()
    # This test used to run through `workflow.prepare_run`, which copied the stages to `inputs/` and wrote an
    # `input_snapshot_sha256` from them. No pdc run has either: the coordinator has always prepared a pdc build
    # through this protocol, so the copy was a property of a path the application never takes for this run type.
    # What that costs is real and recorded rather than fixed here -- `prepare_resume` verifies a resumed run's
    # `inputs/` against that hash, so a pdc run cannot be resumed. It is a pre-existing gap in the pdc adapter, not
    # something this change introduced, and it is not the CG path this work is about.
    assert not (run / 'inputs').exists(), 'if this starts existing, pdc gained a snapshot and resume can be fixed'
    assert 'input_snapshot_sha256' not in manifest
    assert set(manifest['tools']) == {'gmx', 'martinize2', 'pdb2pqr'}, \
        'the preparer the optional prepare step runs is recorded with the tools the run always resolves'
