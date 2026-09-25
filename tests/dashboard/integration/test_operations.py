import os
from dashboard.execution.coordination import coordinator as backend
"""Recovery, concurrency, immutable analysis, and resume acceptance."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import pytest

from dashboard.app import default_coordinator as web
from dashboard import files
from dashboard.execution import workflow
from dashboard.execution.adapters import cg
from dashboard.execution.coordination import resources
from dashboard import store


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); (self.root/'dashboard/runs').mkdir(parents=True)
        for name,value in [('ROOT',self.root),('DATA',self.root/'dashboard/jobs.sqlite3'),('RUNS',self.root/'dashboard/runs'),('WORKERS',{}),('ANALYSIS_WORKERS',{})]:
            p = patch.object(web,name,value); p.start(); self.addCleanup(p.stop)
        p=patch.dict(web.app.config,DISABLE_COORDINATOR=True); p.start(); self.addCleanup(p.stop)
        self.client=web.app.test_client()
        self.job={'id':'123456abcdef','status':'completed','detergent':'DDM','method':'fast_forward','profile':'draft-smoke','created':web.now()}
        web.database().replace([self.job]); self.run=web.run_path(self.job); self.run.mkdir()

    def wait_task(self, aid, timeout=20):
        deadline=time.monotonic()+timeout
        while (self.job['id'],aid) in web.ANALYSIS_WORKERS and time.monotonic()<deadline:
            time.sleep(.05)
        self.assertNotIn((self.job['id'],aid),web.ANALYSIS_WORKERS)
        return next(t for t in web.lookup(self.job['id'])['analyses'] if t['id']==aid)

    def test_sqlite_cross_process_field_updates_are_not_lost(self):
        commands=[]
        for n in range(4):
            script='from dashboard.store import Store; import sys; Store(sys.argv[1]).update("123456abcdef", **{sys.argv[2]:sys.argv[2]})'
            commands.append(subprocess.Popen([sys.executable,'-c',script,str(web.DATA),f'field{n}']))
        self.assertTrue(all(p.wait(timeout=10)==0 for p in commands))
        self.assertTrue(all(f'field{n}' in web.lookup(self.job['id']) for n in range(4)))

    def test_recovery_marks_orphans_without_touching_outputs_or_signalling(self):
        original=self.run/'trajectory.xtc'; original.write_bytes(b'original')
        files.atomic_json(self.run/'manifest.json', {'stages':[{'name':'AA reference','status':'running'}]})
        web.database().update(self.job['id'],status='running',analyses=[{'id':'abc','status':'running'}])
        with patch.object(os,'killpg') as kill: web.reconcile(); kill.assert_not_called()
        recovered=web.lookup(self.job['id']); self.assertEqual(recovered['status'],'failed')
        self.assertEqual(recovered['analyses'][0]['status'],'failed')
        self.assertEqual(original.read_bytes(),b'original')
        self.assertEqual(json.loads((self.run/'manifest.json').read_text())['stages'][0]['status'],'failed')

    def test_an_orphan_lease_blocks_deletion_and_analysis(self):
        with web.lease(self.run/'.worker.lock'):
            self.assertIn(self.client.delete('/api/jobs/'+self.job['id']).status_code,(400,409))
            self.assertIn(self.client.post('/api/jobs/'+self.job['id']+'/targets',json={'targets':[]}).status_code,(400,409))
        self.assertTrue(self.run.exists())

    def test_metadata_corruption_and_default_stage_plan_are_visible(self):
        web.database().update(self.job['id'],started_at='bad timestamp')
        job=self.client.get('/api/jobs').get_json()['jobs'][0]
        self.assertIsNone(job['elapsed_seconds']); self.assertTrue(job['metadata_warnings'])
        self.assertEqual(job['workflow_stages'],[name for name,_ in cg.STAGES])

    def test_paginated_poll_does_not_scan_artifacts_and_supports_etag(self):
        jobs=[dict(self.job,id=f'{i:012x}',status='failed' if i%2 else 'completed',label=f'Run {i}') for i in range(35)]
        web.database().replace(jobs)
        with patch.object(backend.observability,'artifacts',side_effect=AssertionError('poll scanned files')):
            response=self.client.get('/api/jobs?page=1&limit=10&status=failed')
            self.assertEqual(response.get_json()['total'],17); self.assertEqual(len(response.get_json()['jobs']),10)
            unchanged=self.client.get('/api/jobs?page=1&limit=10&status=failed',headers={'If-None-Match':response.headers['ETag']})
            self.assertEqual(unchanged.status_code,304)
        self.assertEqual(self.client.get('/api/jobs?page=0').status_code,400)

    def test_artifacts_are_cached_paginated_and_exclude_symlinks(self):
        (self.run/'ok.txt').write_text('data')
        (self.run/'outside').symlink_to(self.root,target_is_directory=True)
        (self.run/'linked.txt').symlink_to(self.run/'ok.txt')
        first=self.client.get('/api/jobs/'+self.job['id']+'/artifacts?page=1&limit=1').get_json()
        self.assertEqual(first['total'],1)
        with patch.object(backend.observability,'artifacts',side_effect=AssertionError('rescanned terminal run')):
            self.assertEqual(self.client.get('/api/jobs/'+self.job['id']+'/artifacts').status_code,200)

    @pytest.mark.slow
    def test_async_analysis_is_idempotent_and_preserves_sources(self):
        source=self.run/'6_SASA/AA/SASA-AA.xvg'; source.parent.mkdir(parents=True); source.write_text('0 10\n1 12\n2 11\n')
        before=files.hashes(self.run)
        response=self.client.post('/api/jobs/'+self.job['id']+'/plots',json={})
        self.assertEqual(response.status_code,202)
        aid=response.get_json()['id']
        duplicate=self.client.post('/api/jobs/'+self.job['id']+'/plots',json={})
        self.assertEqual(duplicate.get_json()['id'],aid)
        task=self.wait_task(aid)
        self.assertEqual(task['status'],'completed',task.get('error'))
        files.verify(self.run,before)
        self.assertEqual(task['sources_sha256']['6_SASA/AA/SASA-AA.xvg'],files.sha256(source))
        self.assertTrue(any(p.endswith('.png') for p in task['outputs']))
        self.assertEqual(self.client.post('/api/jobs/'+self.job['id']+'/plots',json={}).status_code,200)
        source.write_text('0 3\n1 4\n2 5\n')
        changed=self.client.post('/api/jobs/'+self.job['id']+'/plots',json={}).get_json()
        self.assertNotEqual(changed['id'],aid)
        self.wait_task(changed['id'])
        self.assertTrue(all((self.run/p).is_file() for p in task['outputs']))

    @pytest.mark.slow
    def test_analysis_can_be_cancelled_without_holding_job_lock(self):
        original=backend.Worker.execute
        def slow(worker,command,**kwargs):
            return original(worker,[sys.executable,'-c','import time; print("ready",flush=True); time.sleep(60)'],**kwargs)
        with patch.object(backend.Worker,'execute',slow):
            response=self.client.post('/api/jobs/'+self.job['id']+'/stability',json={}); aid=response.get_json()['id']
            try:
                deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    task=web.lookup(self.job['id'])['analyses'][0]
                    if task['status']=='running': break
                    time.sleep(.025)
                began=time.monotonic()
                self.assertEqual(self.client.get('/api/jobs?page=1').status_code,200)
                # The worker holds the job lock while its command runs, and that command is
                # a 60 s sleep, so the read either does not wait for the lock or waits a
                # minute. A bound of 30 s says that without the 1 s knife edge that made
                # this a load-dependent failure.
                self.assertLess(time.monotonic()-began,30,'the read waited for the analysis worker lock')
                other=dict(self.job,id='abcdef123456',status='running'); web.database().insert(other)
                worker=web.Worker(); web.WORKERS[other['id']]=worker
                self.assertEqual(self.client.post('/control/'+other['id']+'/cancel').status_code,202)
                self.assertTrue(worker.cancel.is_set()); web.WORKERS.pop(other['id'])
                self.assertEqual(self.client.post(f'/api/jobs/{self.job["id"]}/analyses/{aid}/cancel').status_code,202)
            finally:
                for worker in web.ANALYSIS_WORKERS.values(): worker.cancel.set()
                task=self.wait_task(aid)
        self.assertEqual(task['status'],'cancelled')

    def test_targets_and_comparison_keep_missing_values(self):
        response=self.client.post('/api/jobs/'+self.job['id']+'/targets',json={'targets':[{'kind':'density','value':1,'uncertainty':.1,'unit':'g/cm3'}]})
        task=self.wait_task(response.get_json()['id']); self.assertEqual(task['status'],'completed',task.get('error'))
        target=self.client.get('/api/jobs/'+self.job['id']+'/targets').get_json()['targets'][0]
        self.assertNotIn('measured',target)
        second=dict(self.job,id='abcdef123456'); web.database().insert(second)
        result=self.client.get('/api/compare?ids=123456abcdef,abcdef123456').get_json()
        self.assertEqual(result['runs'][1]['sasa'],{})
        self.assertFalse(result['runs'][0]['scientifically_validated'])

    def test_storage_refuses_overcommit_and_never_deletes(self):
        report=web.storage_report(); report['disk_free_bytes']=0
        with self.assertRaises(ValueError): resources.admit(report)
        self.assertTrue(self.run.exists())

    def test_second_coordinator_is_refused(self):
        with patch.dict(web.app.config,DISABLE_COORDINATOR=False), web.lease(web.DATA.with_suffix('.service.lock')):
            self.assertEqual(self.client.get('/api/jobs?page=1').status_code,409)

    def test_clone_keeps_settings_and_production_gate(self):
        with patch.object(cg,'readiness',return_value={'ready':True}), patch.object(threading.Thread,'start'):
            response=self.client.post('/api/jobs/'+self.job['id']+'/clone',json={'settings':{'temperature_k':310},'label':'new settings'})
            self.assertEqual(response.status_code,201)
            self.assertEqual(response.get_json()['settings']['temperature_k'],310)
            self.assertFalse(response.get_json()['scientifically_validated'])
            self.assertNotEqual(response.get_json()['id'],self.job['id'])
        result=self.client.get('/api/readiness?profile=standard').get_json()
        self.assertFalse(result['scientific_gate']['production_allowed'])

    def test_bad_manifest_does_not_break_job_list(self):
        (self.run/'manifest.json').write_text('[]')
        response=self.client.get('/api/jobs?page=1')
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.get_json()['jobs'][0]['metadata_warnings'])

    def test_complete_log_archive_and_stage_cursor(self):
        import io,zipfile
        web.database().update(self.job['id'],layout_version=2)
        logs=self.run/'logs'; logs.mkdir()
        (logs/'console.log').write_text('summary')
        (logs/'aa.log').write_text('AA output')
        files.atomic_json(self.run/'manifest.json',{'stages':[{'name':'AA reference','log':str(logs/'aa.log')}]})
        response=self.client.get('/api/jobs/'+self.job['id']+'/log?offset=10&source=old')
        self.assertTrue(response.get_json()['reset']); self.assertEqual(response.get_json()['text'],'AA output')
        archive=self.client.get('/api/jobs/'+self.job['id']+'/log?download=1')
        with zipfile.ZipFile(io.BytesIO(archive.data)) as bundle: self.assertEqual(set(bundle.namelist()),{'console.log','aa.log'})
        archive.close()

    @pytest.mark.slow
    def test_new_layout_worker_records_stage_outputs_and_logs(self):
        job=dict(self.job,id='abcdef123456',status='queued',layout_version=2)
        web.database().insert(job)
        def prepare(root,**kwargs):
            stage=root/'stages/mini'; stage.mkdir(parents=True)
            (stage/'run.sh').write_text('echo stage-output; echo result > result.txt')
            files.atomic_json(root/'manifest.json',{'stages':[],'stage_plan':['mini']})
        with patch.object(cg,'readiness',return_value={'ready':True}), patch.object(workflow,'prepare_run',prepare), patch.object(workflow,'stage_definitions',lambda metadata: ([('mini','mini/run.sh')], {}, {'mini':('result.txt',)})):
            web.run_job(job['id'])
        job=web.lookup(job['id']); self.assertEqual(job['status'],'completed',job.get('error'))
        manifest=json.loads((web.run_path(job)/'manifest.json').read_text())
        self.assertTrue(manifest['stages'][0]['outputs_sha256'])
        self.assertIn('stage-output',(web.run_path(job)/'logs/mini.log').read_text())

    def test_observables_parse_bond_atom_columns_and_undirected_paths(self):
        import MDAnalysis as mda
        import numpy as np
        from dashboard.analysis.runs import observability
        mapping=self.run/'2_mapping'; mapping.mkdir()
        topology=self.run/'3_initial_CG'; topology.mkdir()
        u=mda.Universe.empty(4,trajectory=True)
        u.add_TopologyAttr('names',['B01','B02','B03','B04']); u.add_TopologyAttr('resnames',['DDM']); u.add_TopologyAttr('resids',[1])
        u.atoms.positions=np.array([[0,0,0],[1,1,0],[1,0,0],[1,1,1]])
        u.dimensions=[20,20,20,90,90,90]; u.atoms.write(str(mapping/'mapped.gro'))
        with mda.Writer(str(mapping/'mapped.xtc'),n_atoms=4) as writer:
            for i in range(2): u.trajectory.ts.time=i; writer.write(u.atoms)
        (topology/'DDM_initial.itp').write_text('[ bonds ]\n1 3 1 0.4 5000\n3 2 1 0.4 5000\n2 4 1 0.4 5000\n[ angles ]\n1 3 2 1 120 25\n')
        result=observability.unparameterized_observables(self.run)
        self.assertEqual((result['distance_count'],result['angle_count'],result['dihedral_count']),(3,1,1))

    def test_worker_checks_total_quota_even_below_individual_limit(self):
        rule=dict(resources.DEFAULTS, min_free_bytes=1)
        with patch.object(resources,'usage',side_effect=lambda path: rule['max_total_bytes']+1 if path == web.RUNS else 1):
            with self.assertRaisesRegex(ValueError,'total storage quota'):
                resources.check_worker(self.run,web.RUNS,rule)


class ResumeTests(unittest.TestCase):
    pytestmark = pytest.mark.slow

    def test_resume_reuses_verified_stage_and_keeps_old_attempt(self):
        # The resume path records tool versions, so the probe is stubbed: this
        # test is about resume bookkeeping, not about which tools this machine
        # happens to have installed. The stage plan comes from the runner's own
        # seam (stage_definitions), which is what run() iterates.
        with tempfile.TemporaryDirectory() as temp, patch.object(workflow,'stage_definitions',lambda metadata: ([('first','first/run.sh'),('second','second/run.sh')], {}, {'first':('result.txt',),'second':('result.txt',)})), patch.object(cg,'tool_metadata',return_value={'gmx':{'path':'stub'}}):
            root=Path(temp); source=root/'source'; source.mkdir(); stages=source/'stages'; stages.mkdir()
            for name in ('first','second'):
                (stages/name).mkdir(); (stages/name/'run.sh').write_text('echo ran > result.txt\n'+('exit 3\n' if name=='second' else ''))
            import shutil
            shutil.copytree(stages,source/'inputs')
            files.atomic_json(source/'manifest.json',{'stages':[],'input_snapshot_sha256':files.hashes(source/'inputs')})
            with self.assertRaises(subprocess.CalledProcessError): workflow.run(source,source/'console.log')
            before=files.hashes(source)
            destination=root/'resumed'; destination.mkdir()
            workflow.prepare_resume(destination,source,'second')
            self.assertFalse((destination/'stages/second/result.txt').exists())
            (destination/'stages/second/run.sh').write_text('echo fixed > result.txt\n')
            workflow.run(destination,destination/'console.log')
            stages_data=json.loads((destination/'manifest.json').read_text())['stages']
            self.assertEqual([s['status'] for s in stages_data],['reused','completed'])
            files.verify(source,before)
            (source/'stages/first/result.txt').write_text('tampered')
            rejected=root/'rejected'; rejected.mkdir()
            with self.assertRaisesRegex(ValueError,'changed or missing'): workflow.prepare_resume(rejected,source,'second')


if __name__=='__main__': unittest.main()
