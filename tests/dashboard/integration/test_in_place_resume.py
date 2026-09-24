import json
import shutil
from pathlib import Path

import pytest

from dashboard import files
from dashboard.execution import workflow


def _stage_run(root):
    inputs = root / 'inputs'
    stages = root / 'stages'
    for name in ('first', 'second', 'third'):
        for base in (inputs, stages):
            directory = base / name
            directory.mkdir(parents=True)
            (directory / 'run.sh').write_text(f'echo {name}\n')
            (directory / 'run.mdp').write_text(f'{name}\n')
    (stages / 'first' / 'result.txt').write_text('upstream')
    (stages / 'second' / 'result.txt').write_text('partial')
    (stages / 'third' / 'result.txt').write_text('stale downstream')
    plan = (('first', 'first/run.sh'), ('second', 'second/run.sh'), ('third', 'third/run.sh'))
    outputs = {name: ('result.txt',) for name, _ in plan}
    entries = []
    for name, relative in plan[:2]:
        directory = stages / Path(relative).parent
        entries.append({'name': name, 'status': 'completed', 'outputs': ['result.txt'],
                        'outputs_sha256': files.hashes(directory)})
    metadata = {'id': '123456abcdef', 'run_type': 'aa_only', 'layout_version': 2,
                'stages': entries, 'input_snapshot_sha256': files.hashes(inputs),
                'status': 'failed', 'stage_plan': [name for name, _ in plan]}
    files.atomic_json(root / 'manifest.json', metadata)
    return plan, outputs


def test_in_place_preparation_keeps_current_stage_files(tmp_path, monkeypatch):
    plan, outputs = _stage_run(tmp_path)
    monkeypatch.setattr(workflow, 'stage_definitions', lambda metadata: (plan, {}, outputs))

    prepared = workflow.prepare_resume_in_place(tmp_path, 'second')

    assert prepared['resume_count'] == 1
    assert [stage['name'] for stage in prepared['stages']] == ['first']
    assert (tmp_path / 'stages/first/result.txt').read_text() == 'upstream'
    assert (tmp_path / 'stages/second/result.txt').read_text() == 'partial'
    assert (tmp_path / 'stages/third/result.txt').read_text() == 'stale downstream'
    assert (tmp_path / 'stages/second/run.sh').read_text() == 'echo second\n'
    history = tmp_path / 'resume_history/0001'
    assert (history / 'manifest.before.json').is_file()
    assert not (history / 'stages').exists()
    assert not (tmp_path / 'resume_journal.json').exists()


def test_in_place_preparation_ignores_changed_inputs_and_outputs(tmp_path, monkeypatch):
    plan, outputs = _stage_run(tmp_path)
    monkeypatch.setattr(workflow, 'stage_definitions', lambda metadata: (plan, {}, outputs))
    manifest_before = (tmp_path / 'manifest.json').read_bytes()
    (tmp_path / 'inputs/second/run.sh').write_text('changed input')
    (tmp_path / 'stages/first/result.txt').write_text('tampered')

    prepared = workflow.prepare_resume_in_place(tmp_path, 'second')

    assert prepared['status'] == 'queued'
    assert (tmp_path / 'manifest.json').read_bytes() != manifest_before
    assert (tmp_path / 'stages/second/result.txt').read_text() == 'partial'


@pytest.fixture
def resume_service(tmp_path, monkeypatch):
    from dashboard.app import create_app
    from dashboard.paths import Paths
    from dashboard.execution.adapters import aa
    app = create_app(Paths(workspace=tmp_path), {'TESTING': True, 'DISABLE_COORDINATOR': True})
    owner = app.extensions['dashboard_coordinator']
    job = {'id': '123456abcdef', 'status': 'failed', 'run_type': 'aa_only',
           'layout_version': 2, 'created': '2026-09-20T00:00:00+00:00',
           'label': 'Original run', 'method': 'gromacs', 'detergent': 'DDM',
           'stage': 'second', 'error': 'interrupted', 'ended_at': '2026-09-21T00:00:00+00:00',
           'molecule_snapshot': None}
    root = owner.run_path(job)
    plan, outputs = _stage_run(root)
    # The real subprocess executes only selected/downstream stages. Upstream
    # data and current stage files stay in place, so launchers must tolerate
    # existing scratch directories.
    for base in ('inputs', 'stages'):
        (root/base/'second/run.sh').write_text('test -f ../first/result.txt\nmkdir -p prod\necho resumed > result.txt\n')
        (root/base/'third/run.sh').write_text('cat ../second/result.txt > result.txt\n')
    (root/'stages/second/prod').mkdir()
    (root/'stages/second/prod/partial.xtc').write_text('old trajectory')
    (root/'logs').mkdir()
    (root/'logs/console.log').write_text('original console')
    metadata = json.loads((root/'manifest.json').read_text())
    metadata['input_snapshot_sha256'] = files.hashes(root/'inputs')
    files.atomic_json(root/'manifest.json', metadata)
    owner.database().insert(job)
    monkeypatch.setattr(workflow, 'stage_definitions', lambda metadata: (plan, {}, outputs))
    monkeypatch.setattr(aa, 'tool_metadata', lambda: {'gmx': {'path': 'fixture'}})
    # Admission stays real; execute its worker explicitly to assert persisted state.
    monkeypatch.setattr('threading.Thread.start', lambda self: None)
    yield app.test_client(), owner, root, job
    for worker in owner.WORKERS.values():
        if worker.lease_file: worker.lease_file.close()
    owner.WORKERS.clear()
    owner.ANALYSIS_WORKERS.clear()


def test_resume_queues_same_id_and_worker_completes_without_repreparing(resume_service, monkeypatch):
    from dashboard.analysis import aa_references
    client, owner, root, job = resume_service
    upstream = files.hashes(root/'stages/first')
    inputs = files.hashes(root/'inputs')
    response = client.post('/api/jobs/123456abcdef/resume', json={'stage': 'second'})
    assert response.status_code == 200, response.json
    assert response.json['id'] == job['id']
    assert response.json['created'] == job['created']
    assert response.json['label'] == job['label']
    assert response.json['status'] == 'queued'
    assert response.json['error'] is None and response.json['ended_at'] is None
    assert len(owner.load()) == 1
    assert client.post('/api/jobs/123456abcdef/resume', json={'stage': 'second'}).status_code == 409
    worker = owner.WORKERS[job['id']]
    assert worker is not None
    monkeypatch.setattr(aa_references, 'verify', lambda *a, **k: {})
    owner.run_job(job['id'], worker)
    manifest = json.loads((root/'manifest.json').read_text())
    assert owner.lookup(job['id'])['status'] == 'completed', (manifest.get('error'), list((root/'logs').rglob('*')))
    assert (root/'stages/third/result.txt').read_text() == 'resumed\n'
    assert files.hashes(root/'stages/first') == upstream
    assert files.hashes(root/'inputs') == inputs
    assert (root/'stages/second/prod/partial.xtc').read_text() == 'old trajectory'
    assert (root/'logs/console.log').read_text().startswith('original console')
    assert (root/'logs/resume-0001/second.log').is_file()
    # Repeated Resume still updates this row, not its old historical source.
    response = client.post('/api/jobs/123456abcdef/resume', json={'stage': 'third'})
    assert response.status_code == 200
    assert response.json['resume_count'] == 2
    assert len(response.json['resume_history']) == 2
    assert len(owner.load()) == 1


def test_database_update_failure_rolls_back_prepared_resume(resume_service, monkeypatch):
    client, owner, root, job = resume_service
    before = files.hashes(root)
    manifest_before = (root / 'manifest.json').read_bytes()

    def fail_update(*args, **kwargs):
        raise OSError('injected database failure')

    monkeypatch.setattr(owner, 'update_job', fail_update)
    with pytest.raises(OSError, match='injected database failure'):
        owner.resume_in_place(job['id'], 'second')

    assert owner.lookup(job['id']) == job
    assert files.hashes(root) == before
    assert (root / 'manifest.json').read_bytes() == manifest_before
    assert not (root / 'resume_journal.json').exists()
    assert not owner.WORKERS


def test_resume_uses_current_stage_files_without_checksum_gate(resume_service):
    client, owner, root, job = resume_service
    current_script = '#!/bin/bash\ncustom-current-stage-launcher\n'
    (root / 'inputs/second/run.sh').write_text('changed-input-launcher\n')
    (root / 'stages/first/result.txt').write_text('changed-upstream-output')
    (root / 'stages/second/run.sh').write_text(current_script)

    response = client.post('/api/jobs/123456abcdef/resume', json={'stage': 'second'})

    assert response.status_code == 200, response.json
    assert (root / 'stages/second/run.sh').read_text() == current_script
    assert (root / 'stages/first/result.txt').read_text() == 'changed-upstream-output'
    assert (root / 'resume_history/0001/manifest.before.json').is_file()
    assert not (root / 'resume_history/0001/stages').exists()


@pytest.mark.parametrize('broken', ['symlink', 'invalid_stage'])
def test_bad_resume_does_not_mutate_state(resume_service, broken):
    client, owner, root, job = resume_service
    if broken == 'symlink':
        shutil.rmtree(root/'stages/second')
        (root/'stages/second').symlink_to(root/'inputs/second', target_is_directory=True)
    before = files.hashes(root)
    response = client.post('/api/jobs/123456abcdef/resume', json={'stage': 'unknown' if broken == 'invalid_stage' else 'second'})
    assert response.status_code == 409, response.json
    assert owner.lookup(job['id']) == job
    assert files.hashes(root) == before
    assert not owner.WORKERS


def test_missing_upstream_output_does_not_block_current_file_resume(resume_service):
    client, owner, root, job = resume_service
    (root / 'stages/first/result.txt').unlink()
    response = client.post('/api/jobs/123456abcdef/resume', json={'stage': 'second'})

    assert response.status_code == 200, response.json
    assert owner.lookup(job['id'])['status'] == 'queued'
    assert not (root / 'stages/first/result.txt').exists()


@pytest.mark.parametrize('blocker', ['worker', 'analysis', 'external', 'consumer', 'capacity', 'quota'])
def test_resume_admission_preserves_terminal_run_on_rejection(resume_service, monkeypatch, blocker):
    from dashboard.execution.coordination import resources
    client, owner, root, job = resume_service
    lease = None
    if blocker == 'worker': owner.WORKERS[job['id']] = owner.Worker()
    if blocker == 'analysis': owner.ANALYSIS_WORKERS[(job['id'], 'analysis')] = owner.Worker()
    if blocker == 'external': lease = owner.lease(root/'.worker.lock')
    if blocker == 'consumer': owner.database().insert_many([{'id': '222222222222', 'reference_run_id': job['id'], 'status': 'completed'}])
    if blocker == 'capacity': owner.WORKERS['222222222222'] = owner.Worker()
    if blocker == 'quota': monkeypatch.setattr(owner, 'limits', lambda: dict(resources.DEFAULTS, max_run_bytes=1))
    before = files.hashes(root)
    try:
        response = client.post('/api/jobs/123456abcdef/resume', json={'stage': 'second'})
        assert response.status_code == 409, response.json
        assert owner.lookup(job['id']) == job
        assert files.hashes(root) == before
    finally:
        if lease: lease.close()


def test_resume_supersedes_analysis_but_retains_evidence(resume_service):
    client, owner, root, job = resume_service
    evidence = root/'analyses/old/numerical_stability.json'
    evidence.parent.mkdir(parents=True)
    evidence.write_text('old analysis')
    task = {'id': 'old', 'kind': 'stability', 'status': 'completed', 'directory': 'analyses/old',
            'outputs': ['analyses/old/numerical_stability.json']}
    owner.update_job(job['id'], analyses=[task])
    response = client.post('/api/jobs/123456abcdef/resume', json={'stage': 'second'})
    assert response.status_code == 200, response.json
    updated = owner.lookup(job['id'])
    assert updated['analyses'][0]['status'] == 'superseded'
    assert owner.analysis_dependencies(updated) == {}
    assert evidence.read_text() == 'old analysis'
    assert json.loads((root/'resume_history/0001/job.before.json').read_text())['analyses'] == [task]


def test_reconcile_recovers_leftover_resume_journal(resume_service):
    client, owner, root, job = resume_service
    manifest_before = (root / 'manifest.json').read_bytes()
    archive = root / 'resume_history/0001'
    (archive / 'stages').mkdir(parents=True)
    shutil.move(str(root / 'stages/second'), str(archive / 'stages/second'))
    (archive / 'manifest.before.json').write_bytes(manifest_before)
    files.atomic_json(root / 'resume_journal.json', {
        'status': 'preparing', 'archive': 'resume_history/0001',
        'moved': [{'relative': 'second'}], 'created': [],
    })

    owner.reconcile()

    assert (root / 'stages/second/result.txt').read_text() == 'partial'
    assert (root / 'manifest.json').read_bytes() == manifest_before
    assert not (root / 'resume_journal.json').exists()
    assert not archive.exists()
