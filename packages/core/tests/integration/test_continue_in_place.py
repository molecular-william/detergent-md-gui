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
from dashboard.execution import run_inputs, workflow


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
    metadata = {'id': '123456abcdef', 'run_type': 'aa_only', 'layout_version': 4, 'status': 'failed',
                'stage_plan': [item.name for item in plan],
                'stages': [{'name': 'first', 'status': 'completed'}],
                'inputs': run_inputs.write(root)}
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


def _release_queued(owner, jid):
    """Drop the queued attempt's worker and row so the next failure can be simulated, as the lease would."""
    worker = owner.WORKERS.pop(jid, None)
    if worker is not None and worker.lease_file:
        worker.lease_file.close()
    owner.database().update(jid, status='failed', stage='second')


def test_a_failed_resumable_run_is_continued_automatically_three_times(continue_service):
    """The failure hook's allowance: three automatic continues, then the run is left for a person."""
    client, owner, root, job, checkpoint = continue_service

    for attempt in (1, 2, 3):
        owner._auto_resume(job['id'], {'status': 'failed'})
        row = owner.lookup(job['id'])
        assert row['status'] == 'queued', row
        assert row['auto_resume_count'] == attempt
        assert row['resume_from'] == 'second', 'the continued stage travels on the row'
        assert json.loads((root/'manifest.json').read_text())['resume_mode'] == 'continue'
        assert row['settings']['gpu_sharing'] == 'queue', 'an automatic resume is never shared'
        _release_queued(owner, job['id'])

    # The fourth failure gets no fourth attempt: the row is already failed and stays that way.
    owner._auto_resume(job['id'], {'status': 'failed'})
    row = owner.lookup(job['id'])
    assert row['status'] == 'failed'
    assert row['auto_resume_count'] == 3
    assert job['id'] not in owner.WORKERS


def test_auto_resume_skips_a_run_with_no_checkpoint(continue_service):
    """Resume-able means what the Resume button means: a stopped stage with a checkpoint on disk."""
    client, owner, root, job, checkpoint = continue_service
    checkpoint.unlink()

    owner._auto_resume(job['id'], {'status': 'failed'})

    row = owner.lookup(job['id'])
    assert row['status'] == 'failed'
    assert not row.get('auto_resume_count')
    assert job['id'] not in owner.WORKERS


def test_only_a_failed_status_is_continued_automatically(continue_service):
    """A cancelled run is the person's decision, not a failure to retry."""
    client, owner, root, job, checkpoint = continue_service

    owner._auto_resume(job['id'], {'status': 'cancelled'})

    assert owner.lookup(job['id'])['status'] == 'failed'
    assert not owner.lookup(job['id']).get('auto_resume_count')


def test_a_failure_in_the_worker_continues_the_run_without_a_person(continue_service):
    """The hook is in the failed attempt itself: the stage fails, and the row is queued again by itself."""
    client, owner, root, job, checkpoint = continue_service
    assert client.post('/api/jobs/123456abcdef/resume', json={}).status_code == 200
    (root / 'stages/second/run.sh').write_text('exit 7\n')

    owner.run_job(job['id'], owner.WORKERS[job['id']])

    row = owner.lookup(job['id'])
    assert row['status'] == 'queued', (row.get('error'), row)
    assert row['auto_resume_count'] == 1
    assert row['resume_from'] == 'second'
    assert json.loads((root/'manifest.json').read_text())['resume_mode'] == 'continue'
    assert job['id'] in owner.WORKERS
