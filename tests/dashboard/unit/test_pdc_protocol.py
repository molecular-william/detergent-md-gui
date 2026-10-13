"""The pdc run type as the application sees it: a registered protocol, and a dispatch that reaches the builder.

`pdc.py` carried the catalogue, the settings and the six-stage contract and was registered nowhere: `adapter_for`
raised `Unknown run type: pdc`, so the API could not list a pdc run's stages and `prepare_run` would have gone to
`cg.prepare`, which demands a molecule snapshot a PDC build does not have. These tests pin the registration, the
contract's shape, what readiness says, and that a pdc job's prepared manifest carries the pdc stages.

They build their own molecule tree; nothing here reads the developer's `molecules/`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dashboard.execution import protocol
from dashboard.execution.adapters import pdc

TEMPLATE = {
    'name': 'DDM',
    'residue': 'DDM',
    'coordinates': 'results/MMFF/lig1.pdb',
    'topology': 'results/MMFF/lig1.itp',
    'beads': [{'name': 'DDM', 'type': 'registered-template'}],
}


def molecule_tree(tmp_path: Path, template: dict | None = None) -> Path:
    molecule = tmp_path / 'molecules' / 'DDM'
    (molecule / 'results' / 'MMFF').mkdir(parents=True)
    (molecule / 'results' / 'MMFF' / 'lig1.pdb').write_text('HETATM    1  C1  DDM A   1       0.000   0.000   0.000\n')
    (molecule / 'results' / 'MMFF' / 'lig1.itp').write_text('[ moleculetype ]\nDDM             1\n')
    (molecule / 'micelle_template.json').write_text(json.dumps(TEMPLATE if template is None else template))
    (molecule / 'protein.pdb').write_text('ATOM      1  CA  ALA A   1       0.000   0.000   0.000\n')
    return tmp_path


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
    assert set(manifest['tools']) == {'gmx', 'martinize2'}
