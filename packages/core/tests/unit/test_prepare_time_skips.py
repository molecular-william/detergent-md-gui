"""A stage the run's own prepare will not run leaves nothing on disk and says so in the manifest."""
import json

from dashboard.execution import workflow


def test_a_prepare_time_skip_creates_no_directory_and_records_its_reason(tmp_path):
    run = tmp_path / 'run'
    (run / 'logs').mkdir(parents=True)
    (run / 'stages').mkdir()
    (run / 'manifest.json').write_text(json.dumps({
        'run_type': 'aa_only',
        'stage_plan': [['AA solvation', '01_solvation/run.sh']],
        'skipped_stages': {'AA solvation': 'the run asks for no solvation'},
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
    (run / 'manifest.json').write_text(json.dumps({
        'run_type': 'aa_only',
        'stage_plan': [['AA solvation', '01_solvation/run.sh']],
        'skipped_stages': {'AA solvation': 'nothing to do'},
        'stages': [{'name': 'AA solvation', 'status': 'skipped', 'reason': 'nothing to do'}],
    }))

    workflow.run(run, run / 'logs' / 'console.log', stop_after='AA solvation')

    assert len(json.loads((run / 'manifest.json').read_text())['stages']) == 1
