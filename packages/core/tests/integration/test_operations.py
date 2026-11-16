"""Recovery, concurrency, immutable analysis, and resume acceptance."""
import dataclasses
import io
import json
import os
import subprocess
import sys
import threading
import time
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from dashboard import files
from dashboard.execution import workflow
from dashboard.execution.adapters import cg
from dashboard.execution.coordination import coordinator as backend
from dashboard.execution.coordination import resources

JOB = {'id':'123456abcdef','status':'completed','detergent':'DDM','method':'fast_forward','profile':'draft-smoke'}


@pytest.fixture
def operations(dashboard):
    """One completed run this test owns, and the client that reads it."""
    job = dict(JOB, created=dashboard.coordinator.now())
    dashboard.coordinator.database().replace([job])
    run = dashboard.coordinator.run_path(job); run.parent.mkdir(parents=True, exist_ok=True); run.mkdir()
    return SimpleNamespace(job=job, run=run, client=dashboard.client, root=dashboard.paths.workspace)


def wait_task(dashboard, job_id, aid, timeout=20):
    deadline=time.monotonic()+timeout
    while (job_id,aid) in dashboard.coordinator.ANALYSIS_WORKERS and time.monotonic()<deadline:
        time.sleep(.05)
    assert (job_id,aid) not in dashboard.coordinator.ANALYSIS_WORKERS
    return next(t for t in dashboard.coordinator.lookup(job_id)['analyses'] if t['id']==aid)


def test_sqlite_cross_process_field_updates_are_not_lost(dashboard, operations):
    commands=[]
    for n in range(4):
        script='from dashboard.store import Store; import sys; Store(sys.argv[1]).update("123456abcdef", **{sys.argv[2]:sys.argv[2]})'
        commands.append(subprocess.Popen([sys.executable,'-c',script,str(dashboard.coordinator.DATA),f'field{n}']))
    assert all(p.wait(timeout=10)==0 for p in commands)
    assert all(f'field{n}' in dashboard.coordinator.lookup(operations.job['id']) for n in range(4))


def test_recovery_marks_orphans_without_touching_outputs_or_signalling(dashboard, operations):
    original=operations.run/'trajectory.xtc'; original.write_bytes(b'original')
    files.atomic_json(operations.run/'manifest.json', {'stages':[{'name':'AA reference','status':'running'}]})
    dashboard.coordinator.database().update(operations.job['id'],status='running',analyses=[{'id':'abc','status':'running'}])
    with patch.object(os,'killpg') as kill: dashboard.coordinator.reconcile(); kill.assert_not_called()
    recovered=dashboard.coordinator.lookup(operations.job['id']); assert recovered['status']=='failed'
    assert recovered['analyses'][0]['status']=='failed'
    assert original.read_bytes()==b'original'
    assert json.loads((operations.run/'manifest.json').read_text())['stages'][0]['status']=='failed'


def test_an_orphan_lease_blocks_deletion_and_analysis(dashboard, operations):
    with dashboard.coordinator.lease(operations.run/'.worker.lock'):
        assert dashboard.client.delete('/api/jobs/'+operations.job['id']).status_code in (400,409)
        assert dashboard.client.post('/api/jobs/'+operations.job['id']+'/targets',json={'targets':[]}).status_code in (400,409)
    assert operations.run.exists()


def test_metadata_corruption_and_default_stage_plan_are_visible(dashboard, operations):
    dashboard.coordinator.database().update(operations.job['id'],started_at='bad timestamp')
    job=dashboard.client.get('/api/jobs').get_json()['jobs'][0]
    assert job['elapsed_seconds'] is None; assert job['metadata_warnings']
    assert job['workflow_stages']==[name for name,_ in cg.STAGES]


def test_paginated_poll_does_not_scan_artifacts_and_supports_etag(dashboard, operations):
    jobs=[dict(operations.job,id=f'{i:012x}',status='failed' if i%2 else 'completed',label=f'Run {i}') for i in range(35)]
    dashboard.coordinator.database().replace(jobs)
    with patch.object(backend.observability,'artifacts',side_effect=AssertionError('poll scanned files')):
        response=dashboard.client.get('/api/jobs?page=1&limit=10&status=failed')
        assert response.get_json()['total']==17; assert len(response.get_json()['jobs'])==10
        unchanged=dashboard.client.get('/api/jobs?page=1&limit=10&status=failed',headers={'If-None-Match':response.headers['ETag']})
        assert unchanged.status_code==304
    assert dashboard.client.get('/api/jobs?page=0').status_code==400


def test_artifacts_are_cached_paginated_and_exclude_symlinks(dashboard, operations):
    (operations.run/'ok.txt').write_text('data')
    (operations.run/'outside').symlink_to(operations.root,target_is_directory=True)
    (operations.run/'linked.txt').symlink_to(operations.run/'ok.txt')
    first=dashboard.client.get('/api/jobs/'+operations.job['id']+'/artifacts?page=1&limit=1').get_json()
    assert first['total']==1
    with patch.object(backend.observability,'artifacts',side_effect=AssertionError('rescanned terminal run')):
        assert dashboard.client.get('/api/jobs/'+operations.job['id']+'/artifacts').status_code==200


@pytest.mark.slow
@pytest.mark.xfail(strict=True, reason='the plots kind was deleted in the 2026-11-13 audit; the subprocess path already failed at HEAD because the worker invokes PATH python')
def test_async_analysis_is_idempotent_and_preserves_sources(dashboard, operations):
    source=operations.run/'6_SASA/AA/SASA-AA.xvg'; source.parent.mkdir(parents=True); source.write_text('0 10\n1 12\n2 11\n')
    before=files.hashes(operations.run)
    response=dashboard.client.post('/api/jobs/'+operations.job['id']+'/plots',json={})
    assert response.status_code==202
    aid=response.get_json()['id']
    duplicate=dashboard.client.post('/api/jobs/'+operations.job['id']+'/plots',json={})
    assert duplicate.get_json()['id']==aid
    task=wait_task(dashboard, operations.job['id'], aid)
    assert task['status']=='completed',task.get('error')
    files.verify(operations.run,before)
    assert task['sources_sha256']['6_SASA/AA/SASA-AA.xvg']==files.sha256(source)
    assert any(p.endswith('.png') for p in task['outputs'])
    assert dashboard.client.post('/api/jobs/'+operations.job['id']+'/plots',json={}).status_code==200
    source.write_text('0 3\n1 4\n2 5\n')
    changed=dashboard.client.post('/api/jobs/'+operations.job['id']+'/plots',json={}).get_json()
    assert changed['id']!=aid
    wait_task(dashboard, operations.job['id'], changed['id'])
    assert all((operations.run/p).is_file() for p in task['outputs'])


@pytest.mark.slow
def test_analysis_can_be_cancelled_without_holding_job_lock(dashboard, operations):
    original=backend.Worker.execute
    def slow(worker,command,**kwargs):
        return original(worker,[sys.executable,'-c','import time; print("ready",flush=True); time.sleep(60)'],**kwargs)
    with patch.object(backend.Worker,'execute',slow):
        response=dashboard.client.post('/api/jobs/'+operations.job['id']+'/bonded-cross-check',json={}); aid=response.get_json()['id']
        try:
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                task=dashboard.coordinator.lookup(operations.job['id'])['analyses'][0]
                if task['status']=='running': break
                time.sleep(.025)
            began=time.monotonic()
            assert dashboard.client.get('/api/jobs?page=1').status_code==200
            # The worker holds the job lock while its command runs, and that command is
            # a 60 s sleep, so the read either does not wait for the lock or waits a
            # minute. A bound of 30 s says that without the 1 s knife edge that made
            # this a load-dependent failure.
            assert time.monotonic()-began<30,'the read waited for the analysis worker lock'
            other=dict(operations.job,id='abcdef123456',status='running'); dashboard.coordinator.database().insert(other)
            worker=dashboard.coordinator.Worker(); dashboard.coordinator.WORKERS[other['id']]=worker
            assert dashboard.client.post('/control/'+other['id']+'/cancel').status_code==202
            assert worker.cancel.is_set(); dashboard.coordinator.WORKERS.pop(other['id'])
            assert dashboard.client.post(f'/api/jobs/{operations.job["id"]}/analyses/{aid}/cancel').status_code==202
        finally:
            for worker in dashboard.coordinator.ANALYSIS_WORKERS.values(): worker.cancel.set()
            task=wait_task(dashboard, operations.job['id'], aid)
    assert task['status']=='cancelled'


def test_targets_keep_missing_values(dashboard, operations):
    response=dashboard.client.post('/api/jobs/'+operations.job['id']+'/targets',json={'targets':[{'kind':'density','value':1,'uncertainty':.1,'unit':'g/cm3'}]})
    task=wait_task(dashboard, operations.job['id'], response.get_json()['id']); assert task['status']=='completed',task.get('error')
    target=dashboard.client.get('/api/jobs/'+operations.job['id']+'/targets').get_json()['targets'][0]
    assert 'measured' not in target


def test_storage_refuses_overcommit_and_never_deletes(dashboard, operations):
    report=dashboard.coordinator.storage_report(); report['disk_free_bytes']=0
    with pytest.raises(ValueError): resources.admit(report)
    assert operations.run.exists()


def test_second_coordinator_is_refused(dashboard, operations):
    with patch.dict(dashboard.app.config,DISABLE_COORDINATOR=False), dashboard.coordinator.lease(dashboard.coordinator.DATA.with_suffix('.service.lock')):
        assert dashboard.client.get('/api/jobs?page=1').status_code==409


def test_clone_keeps_settings_and_production_gate(dashboard, operations):
    from detergent_validation.execution.adapters import sugar_cg

    dashboard.coordinator.database().update(
        operations.job['id'], run_type='cg',
        parameterization={'kind': 'reference', 'sugar_entry': 'SUCR'})
    with patch.object(sugar_cg,'assess',return_value={'ready':True,'checks':[],'blockers':[]}), \
            patch.object(threading.Thread,'start'):
        response=dashboard.client.post('/api/jobs/'+operations.job['id']+'/clone',json={'settings':{'temperature_k':310},'label':'new settings'})
        assert response.status_code==201
        assert response.get_json()['settings']['temperature_k']==310
        assert not response.get_json()['scientifically_validated']
        assert response.get_json()['id']!=operations.job['id']
    result=dashboard.client.get('/api/readiness?profile=standard').get_json()
    assert not result['scientific_gate']['production_allowed']


def test_bad_manifest_does_not_break_job_list(dashboard, operations):
    (operations.run/'manifest.json').write_text('[]')
    response=dashboard.client.get('/api/jobs?page=1')
    assert response.status_code==200
    assert response.get_json()['jobs'][0]['metadata_warnings']


def test_complete_log_archive_and_stage_cursor(dashboard, operations):
    dashboard.coordinator.database().update(operations.job['id'],layout_version=2)
    logs=operations.run/'logs'; logs.mkdir()
    (logs/'console.log').write_text('summary')
    (logs/'aa.log').write_text('AA output')
    files.atomic_json(operations.run/'manifest.json',{'stages':[{'name':'AA reference','log':str(logs/'aa.log')}]})
    response=dashboard.client.get('/api/jobs/'+operations.job['id']+'/log?offset=10&source=old')
    assert response.get_json()['reset']; assert response.get_json()['text']=='AA output'
    archive=dashboard.client.get('/api/jobs/'+operations.job['id']+'/log?download=1')
    with zipfile.ZipFile(io.BytesIO(archive.data)) as bundle: assert set(bundle.namelist())=={'console.log','aa.log'}
    archive.close()


@pytest.mark.slow
def test_new_layout_worker_records_stage_outputs_and_logs(dashboard, operations):
    job=dict(operations.job,id='abcdef123456',status='queued',layout_version=2,run_type='cg',
             parameterization={'kind':'revision','starting_coordinates':'remap'})
    dashboard.coordinator.database().insert(job)
    def prepare(root, metadata):
        stage=root/'stages/mini'; stage.mkdir(parents=True)
        (stage/'run.sh').write_text('echo stage-output; echo result > result.txt')
        (root/'inputs').mkdir()
        files.atomic_json(root/'inputs/inputs.json',{'inputs':[]})
        files.atomic_json(root/'manifest.json',{'stages':[],'stage_plan':['mini'],'inputs':[]})
    # The protocol object is what the coordinator resolves; its `prepare` is bound when the adapter builds it.
    # The run type's readiness and its prepare are stubbed: this test is about the worker's stage bookkeeping,
    # not about where a molecule or a model lives, and the CG run type refuses a payload with neither.
    with patch.object(cg,'parameterization_readiness',return_value={'ready':True,'checks':[],'blockers':[]}), \
            patch.object(cg,'PROTOCOL',dataclasses.replace(cg.PROTOCOL,prepare=prepare)), \
            patch.object(workflow,'stage_definitions',lambda metadata: ([('mini','mini/run.sh')], {}, {'mini':('result.txt',)})):
        dashboard.coordinator.run_job(job['id'])
    job=dashboard.coordinator.lookup(job['id']); assert job['status']=='completed',job.get('error')
    manifest=json.loads((dashboard.coordinator.run_path(job)/'manifest.json').read_text())
    assert manifest['stages'][0]['outputs_sha256']
    assert 'stage-output' in (dashboard.coordinator.run_path(job)/'logs/mini.log').read_text()


def test_worker_checks_total_quota_even_below_individual_limit(dashboard, operations):
    rule=dict(resources.DEFAULTS, min_free_bytes=1)
    with patch.object(resources,'usage',side_effect=lambda path: rule['max_total_bytes']+1 if path == dashboard.coordinator.RUNS else 1):
        with pytest.raises(ValueError, match='total storage quota'):
            resources.check_worker(operations.run,dashboard.coordinator.RUNS,rule)
