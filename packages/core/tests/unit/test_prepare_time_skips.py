"""A stage the run's own prepare will not run leaves nothing on disk and says so in the manifest."""
import json

import pytest
from dashboard.execution import workflow


def test_a_prepare_time_skip_creates_no_directory_and_records_its_reason(tmp_path):
    run = tmp_path / 'run'
    (run / 'logs').mkdir(parents=True)
    (run / 'stages').mkdir()
    (run / 'inputs').mkdir()
    (run / 'inputs/inputs.json').write_text(json.dumps({'inputs': []}))
    (run / 'manifest.json').write_text(json.dumps({
        'run_type': 'aa_only',
        'stage_plan': [['AA solvation', '01_solvation/run.sh']],
        'skipped_stages': {'AA solvation': 'the run asks for no solvation'},
        'inputs': [],
        'stages': [],
    }))

    workflow.run(run, run / 'logs' / 'console.log', stop_after='AA solvation')

    stages = json.loads((run / 'manifest.json').read_text())['stages']
    assert stages[0]['status'] == 'skipped'
    assert stages[0]['reason'] == 'the run asks for no solvation'
    assert stages[0]['command'] == []
    assert not (run / 'stages' / '01_solvation').exists()


def test_a_skipped_stage_already_recorded_is_not_recorded_twice(tmp_path):
    run = tmp_path / 'run'
    (run / 'logs').mkdir(parents=True)
    (run / 'stages').mkdir()
    (run / 'inputs').mkdir()
    (run / 'inputs/inputs.json').write_text(json.dumps({'inputs': []}))
    (run / 'manifest.json').write_text(json.dumps({
        'run_type': 'aa_only',
        'stage_plan': [['AA solvation', '01_solvation/run.sh']],
        'skipped_stages': {'AA solvation': 'nothing to do'},
        'inputs': [],
        'stages': [{'name': 'AA solvation', 'status': 'skipped', 'reason': 'nothing to do'}],
    }))

    workflow.run(run, run / 'logs' / 'console.log', stop_after='AA solvation')

    assert len(json.loads((run / 'manifest.json').read_text())['stages']) == 1


def test_a_manifest_that_names_no_inputs_is_refused(tmp_path):
    """A run prepared before layout 4 has no named inputs; it cannot be verified, so it is refused, not run."""
    run = tmp_path / 'run'
    (run / 'logs').mkdir(parents=True)
    (run / 'stages').mkdir()
    (run / 'manifest.json').write_text(json.dumps({
        'run_type': 'aa_only',
        'stage_plan': [['AA solvation', '01_solvation/run.sh']],
        'stages': [],
    }))

    with pytest.raises(ValueError, match='records no named inputs'):
        workflow.run(run, run / 'logs' / 'console.log')
