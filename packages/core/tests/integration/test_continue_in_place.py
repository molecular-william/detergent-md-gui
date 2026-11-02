"""Resume without a stage continues the stopped stage in place, through the route the Runs table calls.

The run tree is a fixture: one completed stage, the stage that stopped with a checkpoint already on disk, and one
downstream stage that must not inherit the continuation. `threading.Thread.start` is stubbed so the worker the
coordinator queues is executed explicitly, which is how the queued state and the stage it actually runs can both be
asserted.
"""
import json
from types import SimpleNamespace

import pytest
from dashboard import files
from dashboard.execution import workflow


def _plan():
    return tuple(SimpleNamespace(name=name, relative=f'{name}/run.sh', checkpoint='run.cpt',
                                 resumes_in_place=False)
                 for name in ('first', 'second', 'third'))


def _tree(root):
    plan = _plan()
    for item in plan:
        for base in (root / 'inputs', root / 'stages'):
            directory = base / item.name
            directory.mkdir(parents=True)
            (directory / 'run.sh').write_text(f'echo {item.name}\n')
    (root / 'stages/first/result.txt').write_text('upstream')
    (root / 'stages/second/result.txt').write_text('partial')
    (root / 'stages/second/run.sh').write_text(
        'test -f ../first/result.txt\n'
        'mkdir -p prod\n'
        'printf \'%s\' "${MDRUN_CONTINUE:-none}" > continue.txt\n'
        'echo resumed > result.txt\n')
    (root / 'stages/third/run.sh').write_text(
        'cat ../second/result.txt > result.txt\n'
        'printf \'%s\' "${MDRUN_CONTINUE:-none}" > continue.txt\n')
    checkpoint = root / 'stages/second/run.cpt'
    checkpoint.write_text('checkpoint')
    (root / 'stages/second/prod').mkdir()
    (root / 'stages/second/prod/partial.xtc').write_text('old trajectory')
    (root / 'logs').mkdir()
    (root / 'logs/console.log').write_text('original console')
    metadata = {'id': '123456abcdef', 'run_type': 'aa_only', 'layout_version': 2, 'status': 'failed',
                'stage_plan': [item.name for item in plan],
                'stages': [{'name': 'first', 'status': 'completed'}],
                'input_snapshot_sha256': files.hashes(root / 'inputs')}
    files.atomic_json(root / 'manifest.json', metadata)
    return plan, checkpoint


@pytest.fixture
def continue_service(tmp_path, monkeypatch):
    from dashboard.analysis.runs import references as aa_references
    from dashboard.app import create_app
    from dashboard.execution.adapters import aa
    from dashboard.paths import Paths
    app = create_app(Paths(workspace=tmp_path), {'TESTING': True, 'DISABLE_COORDINATOR': True})
    owner = app.extensions['dashboard_coordinator']
    job = {'id': '123456abcdef', 'status': 'failed', 'run_type': 'aa_only',
           'layout_version': 2, 'created': '2026-09-20T00:00:00+00:00',
           'label': 'Original run', 'method': 'gromacs', 'detergent': 'DDM',
           'stage': 'second', 'error': 'interrupted', 'ended_at': '2026-09-21T00:00:00+00:00',
           'molecule_snapshot': None}
    root = owner.run_path(job)
    plan, checkpoint = _tree(root)
    owner.database().insert(job)
    pairs = tuple((item.name, item.relative) for item in plan)
    monkeypatch.setattr(workflow, 'plan_for', lambda metadata: plan)
    monkeypatch.setattr(workflow, 'stage_definitions', lambda metadata: (pairs, {}, {}))
    monkeypatch.setattr(aa, 'tool_metadata', lambda: {'gmx': {'path': 'fixture'}})
    monkeypatch.setattr(aa_references, 'verify', lambda *arguments, **keywords: {})
    monkeypatch.setattr('threading.Thread.start', lambda self: None)
    yield app.test_client(), owner, root, job, checkpoint
    for worker in owner.WORKERS.values():
        if worker.lease_file: worker.lease_file.close()
    owner.WORKERS.clear()
    owner.ANALYSIS_WORKERS.clear()


def test_continue_keeps_the_stage_and_its_files_and_truncates_the_manifest(continue_service):
    client, owner, root, job, checkpoint = continue_service

    response = client.post('/api/jobs/123456abcdef/resume', json={})

    assert response.status_code == 200, response.json
    assert response.json['status'] == 'queued'
    assert response.json['can_continue'] is False
    assert response.json['created'] == job['created']
    manifest = json.loads((root / 'manifest.json').read_text())
    assert manifest['resume_mode'] == 'continue'
    assert manifest['continue_stage'] == 'second'
    assert manifest['continue_checkpoint'] == 'run.cpt'
    assert manifest['resume_in_place'] is True
    assert [entry['name'] for entry in manifest['stages']] == ['first']
    assert checkpoint.read_text() == 'checkpoint'
    assert (root / 'stages/second/prod/partial.xtc').read_text() == 'old trajectory'
    assert (root / 'stages/second/result.txt').read_text() == 'partial'
    assert not (root / 'resume_history').exists()
    assert len(owner.database().all()) == 1


def test_the_continued_stage_is_run_with_the_checkpoint_and_the_run_completes(continue_service):
    client, owner, root, job, checkpoint = continue_service
    assert client.post('/api/jobs/123456abcdef/resume', json={}).status_code == 200

    owner.run_job(job['id'], owner.WORKERS[job['id']])

    assert owner.lookup(job['id'])['status'] == 'completed'
    assert (root / 'stages/second/continue.txt').read_text() == str(checkpoint.absolute())
    # A later stage re-runs normally and inherits no continuation.
    assert (root / 'stages/third/continue.txt').read_text() == 'none'
    manifest = json.loads((root / 'manifest.json').read_text())
    assert 'continue_stage' not in manifest and 'continue_checkpoint' not in manifest


def test_continue_refuses_a_run_that_is_not_failed_or_cancelled(continue_service, monkeypatch):
    client, owner, root, job, checkpoint = continue_service
    for status in ('completed', 'running'):
        owner.database().update(job['id'], status=status)
        response = client.post('/api/jobs/123456abcdef/resume', json={})
        assert response.status_code == 409, (status, response.json)
        assert 'stopped' in response.json['error']
        assert not owner.WORKERS


def test_continue_refuses_a_stage_with_no_checkpoint_naming_it(continue_service):
    client, owner, root, job, checkpoint = continue_service
    checkpoint.unlink()
    before = files.hashes(root)

    response = client.post('/api/jobs/123456abcdef/resume', json={})

    assert response.status_code == 409, response.json
    assert 'second' in response.json['error'] and 'checkpoint' in response.json['error']
    assert owner.lookup(job['id']) == job
    assert files.hashes(root) == before


def test_the_resume_route_dispatches_on_the_presence_of_stage(continue_service, monkeypatch):
    client, owner, root, job, checkpoint = continue_service
    calls = []
    monkeypatch.setattr(owner, 'continue_in_place', lambda jid: calls.append(('continue', jid)) or job)
    monkeypatch.setattr(owner, 'resume_in_place',
                        lambda jid, stage: calls.append(('restart', jid, stage)) or job)

    assert client.post('/api/jobs/123456abcdef/resume', json={}).status_code == 200
    assert client.post('/api/jobs/123456abcdef/resume', json={'stage': 'second'}).status_code == 200

    assert calls == [('continue', '123456abcdef'), ('restart', '123456abcdef', 'second')]
