"""Application-owned execution coordination and persistent job lifecycle."""
from datetime import datetime, timezone
from pathlib import Path
import json
import hashlib
import re
import shutil
import threading
import time
import uuid
import fcntl
from flask import abort
from dashboard import files, store, paths
from ..adapters import aa
from .. import workflow
from . import resources, temporary
from ...models.molecules import aa as aa_molecules
from ...models import mappings, compositions
from ...models.bonded import states as bonded_states
from ...models.mappings import context as mapping_context
from dashboard.analysis import aa_references, observability
from functools import wraps
from .worker import Worker
from .analysis_coordinator import AnalysisCoordinator
from .manifest import ManifestCache, stage_log_path as resolve_stage_log


_VISIBLE_FIELDS = frozenset((
    'id','label','detergent','molecule_name','molecule_id','method','profile',
    'status','stage','created','started_at','ended_at','error',
    'artifact_revision','run_type',
))
_HIDDEN_FIELDS = frozenset((
    'pid','gromacs_eta','gromacs_remaining_seconds','eta_minutes','stage_estimate_minutes',
))
_ANALYSIS_SUMMARY_FIELDS = frozenset((
    'id','kind','status','created_at','started_at','ended_at','error','directory',
))
_STAGE_SUMMARY_FIELDS = frozenset(('name','status','started_at','ended_at'))


def application_context(function):
    @wraps(function)
    def invoke(self, *args, **kwargs):
        with self.app.app_context():
            return function(self, *args, **kwargs)
    return invoke


class Coordinator:
    """One application's jobs, worker ownership, admission and recovery."""

    def __init__(self, app, selected_paths):
        self.app = app
        self.ROOT = selected_paths.project_root
        self.DATA = selected_paths.database
        self.RUNS = selected_paths.runs
        self.UPLOADS = selected_paths.uploads
        self.WORKERS = {}
        self.ANALYSIS_WORKERS = {}
        self.SERVICES = {}
        self.JOBS_LOCK = threading.RLock()
        self.MANIFEST_CACHE = ManifestCache()
        self.analysis_coordinator = AnalysisCoordinator(self)
        self.ALLOWED_METHODS = {'fast_forward', 'bartender'}

    def Worker(self, run_dir=None):
        return Worker(self, run_dir)

    def close(self):
        if self.WORKERS or self.ANALYSIS_WORKERS:
            raise ValueError('Cannot close a coordinator with active workers')
        for lease_file in self.SERVICES.values():
            lease_file.close()
        self.SERVICES.clear()

    def now(self):
        return datetime.now(timezone.utc).isoformat()


    def database(self):
        return store.Store(self.DATA)


    def load(self):
        return self.database().all()


    def save(self, jobs):
        self.database().replace(jobs)


    def lookup(self, jid):
        job = self.database().get(jid)
        if job is None: abort(404, 'Unknown run')
        return job


    def update_job(self, jid, **fields):
        return self.database().update(jid, **fields)


    def resume_in_place(self, jid, stage):
        """Queue an in-place resume on the existing job and run directory."""
        with self.JOBS_LOCK:
            job = self.lookup(jid)
            if job.get('status') not in ('failed', 'cancelled', 'completed') or jid in self.WORKERS:
                abort(409, 'Run must be stopped before it can be resumed')
            if any(key[0] == jid for key in list(self.ANALYSIS_WORKERS)) or any(
                    task.get('status') in ('queued', 'running', 'cancelling') for task in job.get('analyses', [])):
                abort(409, 'Active analyses must finish before the run can be resumed')
            if self.externally_busy(job):
                abort(409, 'An external worker still holds this run')
            if any(other.get('reference_run_id') == jid or other.get('resume_of') == jid
                   for other in self.load() if other.get('id') != jid):
                abort(409, 'The run has retained consumers; resume the consumers or clone this run')
            if len(self.WORKERS) + sum(self.externally_busy(item) for item in self.load()) >= self.limits()['max_concurrent_runs']:
                abort(409, 'Simulation capacity is busy; wait for a run to stop')
            try:
                resources.check_worker(self.run_path(job), self.RUNS, self.limits())
            except (OSError, ValueError) as exc:
                abort(409, str(exc))
            path = self.run_path(job)
            try:
                lease = self.lease(path / '.worker.lock')
            except ValueError as exc:
                abort(409, str(exc))
            try:
                if stage not in workflow.resumable_stages(path):
                    abort(409, 'Cannot resume that stage; choose a completed-stage boundary')
                try:
                    prepared = workflow.prepare_resume_in_place(path, stage, analyses=job.get('analyses', []), finalize=False)
                except (OSError, ValueError, KeyError) as exc:
                    abort(409, str(exc))
                try:
                    updated = self.update_job(jid, status='queued', stage='queued', started_at=None, ended_at=None,
                                              error=None, command=None, resume_count=prepared['resume_count'],
                                              resume_from=stage, resume_requested_at=prepared['resume_requested_at'],
                                              resume_in_place=True, reference_eligible=False,
                                              analyses=prepared.get('analyses', job.get('analyses', [])),
                                              resume_history=prepared.get('resume_history', []))
                except Exception:
                    workflow.recover_resume_journal(path, job)
                    raise
                workflow.recover_resume_journal(path, updated)
                worker = self.Worker()
                self.WORKERS[jid] = worker
            finally:
                lease.close()
            try:
                threading.Thread(target=self.run_job, args=(jid, worker), daemon=True).start()
            except Exception as exc:
                self.WORKERS.pop(jid, None)
                self.update_job(jid, status='failed', stage='queued', error=str(exc), ended_at=self.now())
                raise
            return updated


    def lease(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        fp = path.open('a')
        try: fcntl.flock(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fp.close(); raise ValueError('A worker still holds this run; wait for it to stop before reuse or deletion')
        return fp


    def externally_busy(self, job):
        path = self.run_path(job)/'.worker.lock'
        if job['id'] in self.WORKERS or any(key[0] == job['id'] for key in list(self.ANALYSIS_WORKERS)) or not path.is_file(): return False
        try:
            with self.lease(path): return False
        except ValueError: return True


    def reconcile(self):
        for job in self.load():
            updates = {}
            try:
                workflow.recover_resume_journal(self.run_path(job), job)
            except (OSError, ValueError, KeyError):
                updates.update(status='failed', ended_at=self.now(), error='Resume preparation journal could not be recovered; inspect the run history before retrying.')
            if job.get('status') in ('running','queued','cancelling') and job['id'] not in self.WORKERS:
                updates.update(status='failed', ended_at=self.now(), error='Dashboard restarted before worker completion; inspect logs and resume this run.')
                path = self.run_path(job)/'manifest.json'
                try:
                    with self.lease(self.run_path(job)/'.worker.lock'):
                        data = json.loads(path.read_text())
                        if not isinstance(data,dict): raise ValueError('Manifest must be an object')
                        data.update(updates)
                        for stage in data.get('stages', []):
                            if isinstance(stage,dict) and stage.get('status') == 'running': stage.update(status='failed', ended_at=self.now(), error=updates['error'])
                        files.atomic_json(path, data)
                except (OSError, ValueError): pass
            tasks = job.get('analyses', [])
            for task in tasks:
                if task['status'] in ('queued','running','cancelling') and (job['id'],task['id']) not in self.ANALYSIS_WORKERS:
                    task.update(status='failed', ended_at=self.now(), error='Dashboard restarted during analysis; retry creates a new attempt.')
                    updates['analyses'] = tasks
                    if task.get('directory'):
                        attempt = self.run_path(job)/task['directory']
                        if attempt.is_dir(): files.atomic_json(attempt/'manifest.json',task)
            if updates: self.update_job(job['id'], **updates)


    def ensure_service(self):
        if self.app.config.get('DISABLE_COORDINATOR'): return
        key = str(self.DATA.resolve())
        with self.JOBS_LOCK:
            if key not in self.SERVICES:
                try: self.SERVICES[key] = self.lease(self.DATA.with_suffix('.service.lock'))
                except ValueError: abort(409, 'Another dashboard process owns this database; use one coordinator process')
                self.reconcile()
                temporary.cleanup(self.load(), self.RUNS, self.database().delete, delete_with_cleanup=self.database().delete_with_cleanup)
            self.schedule_waiting()


    def limits(self):
        return resources.policy(self.ROOT/'config/dashboard.json')


    def storage_report(self):
        return resources.report(self.RUNS, self.load(), self.limits())


    def artifact_index(self, job, refresh=False):
        entries, updated = self.database().artifacts(job['id'])
        if entries is None or refresh or (job['status'] in ('running','cancelling') and time.time()-updated > 15):
            entries = observability.artifacts(self.run_path(job))
            self.database().artifacts(job['id'], entries)
            self.update_job(job['id'], artifact_revision=time.time())
        return entries


    def run_path(self, job):
        # Never use arbitrary manifest/log paths supplied by a client or old metadata.
        if not re.fullmatch(r'[a-f0-9]{12}', job['id']):
            abort(404, 'Invalid run ID')
        path = self.RUNS / job['id']
        if path.is_symlink(): abort(409, 'Run directories must not be symbolic links')
        return path


    def log_path(self, job):
        return self.run_path(job)/'logs/console.log' if job.get('layout_version') == 2 else self.DATA.parent / f'{self.run_path(job).name}.log'


    def stage_log_path(self, job, recorded):
        """Resolve captured log provenance within this run after workspace moves."""
        return resolve_stage_log(self.run_path(job), recorded)


    def tail(self, path, limit=65536):
        if not path.is_file():
            return ''
        with path.open('rb') as fp:
            fp.seek(max(0, path.stat().st_size - limit))
            return fp.read(limit).decode('utf-8', errors='replace')


    def parse_gromacs_eta(self, text):
        # Only consider estimates after the latest mdrun start/end marker.
        text = re.split(r'(?:starting mdrun|Finished mdrun)', text, flags=re.I)[-1]
        matches = list(re.finditer(r'remaining wall clock time:\s*([0-9]+(?:\.[0-9]+)?)\s*s|will finish\s+([^\r\n]+)', text, re.I))
        if not matches:
            return {}
        latest = matches[-1]
        data = {'eta_source': 'GROMACS console output'}
        if latest.group(1):
            data['gromacs_remaining_seconds'] = float(latest.group(1))
        else:
            data['gromacs_eta'] = latest.group(2).strip()
        return data


    def _ownership_flags(self, job):
        """Return can_cancel / can_retry / can_delete for a locally owned job.

        External worker ownership is applied separately by public_job.
        """
        active_analysis = any(key[0] == job['id'] for key in list(self.ANALYSIS_WORKERS))
        return {
            'can_cancel': (job['id'] in self.WORKERS and job['status'] in ('queued','running')) or job['status']=='waiting',
            'can_retry': job['status'] == 'failed',
            'can_delete': job['status'] in ('completed','failed','cancelled','blocked') and job['id'] not in self.WORKERS and not active_analysis,
        }


    def _analysis_view(self, job, summary):
        """Public analysis records; summary drops the heavy 'outputs' list."""
        result = []
        for task in job.get('analyses', []):
            if summary:
                result.append({k: v for k, v in task.items() if k in _ANALYSIS_SUMMARY_FIELDS})
            else:
                result.append({k: v for k, v in task.items() if k in _ANALYSIS_SUMMARY_FIELDS or k == 'outputs'})
        return result


    def _elapsed(self, job):
        """Return (elapsed_seconds, warnings); (None, []) when no started_at."""
        start = job.get('started_at')
        if not start:
            return None, []
        try:
            began = datetime.fromisoformat(start)
            ended = datetime.fromisoformat(job['ended_at']) if job.get('ended_at') else datetime.now(began.tzinfo)
            return max(0, (ended - began).total_seconds()), []
        except (ValueError, TypeError):
            return None, ['Invalid persisted timestamp; elapsed time unavailable']


    def _eta(self, job, stages):
        """GROMACS ETA parsed from the most recent log of the running stage."""
        if job['status'] != 'running':
            return {}
        current = next((s for s in reversed(stages) if s.get('status') == 'running'), None)
        if not current:
            return {}
        stage_dir = next((Path(rel).parent for name, rel in workflow.stage_definitions(job)[0] if name == current['name']), None)
        candidates = []
        resume_logs = None
        if job.get('resume_in_place') and job.get('resume_count'):
            try:
                attempt = int(job['resume_count'])
                if attempt > 0:
                    resume_logs = self.run_path(job) / 'logs' / f'resume-{attempt:04d}'
            except (TypeError, ValueError):
                pass
        if current.get('log'):
            recorded = self.stage_log_path(job, current['log'])
            if recorded and (resume_logs is None or recorded.resolve().is_relative_to(resume_logs.resolve())):
                candidates.append(recorded)
        if resume_logs and stage_dir:
            candidates.append(resume_logs / f'{stage_dir.name}.log')
        elif stage_dir:
            candidates.append(self.run_path(job) / 'stages' / stage_dir / f'{stage_dir.name}.log')
            candidates.append(self.run_path(job) / 'logs' / f'{stage_dir.name}.log')
            candidates.append(self.log_path(job))
        elif not resume_logs:
            candidates.append(self.log_path(job))
        for candidate in candidates:
            if candidate.is_file():
                eta = self.parse_gromacs_eta(self.tail(candidate))
                if eta:
                    return eta
        return {}


    def _stage_view(self, job, metadata):
        """Return (stages, workflow_stages) with defensive type checks."""
        stages = metadata.get('stages', []) if metadata else []
        if not isinstance(stages, list) or any(not isinstance(stage, dict) for stage in stages):
            stages = []
        workflow_stages = metadata.get('stage_plan') or job.get('stage_plan') or [name for name, _ in workflow.STAGES]
        return stages, workflow_stages


    def public_job(self, job, summary=False):
        result = {k: v for k, v in job.items()
                  if k not in _HIDDEN_FIELDS and (not summary or k in _VISIBLE_FIELDS)}
        result['metadata_warnings'] = []
        if not isinstance(job.get('id'),str) or not re.fullmatch(r'[a-f0-9]{12}',job['id']):
            return result | {'status':'failed','error':'Invalid persisted run ID; repair the metadata before using this record','can_cancel':False,'can_delete':False,'can_retry':False,'stages':[],'workflow_stages':[name for name,_ in workflow.STAGES],'elapsed_seconds':None,'analyses':[]}
        result.update(self._ownership_flags(job))
        result['analyses'] = self._analysis_view(job, summary)
        manifest = self.run_path(job) / 'manifest.json'
        metadata = self.MANIFEST_CACHE.read(manifest)
        stages, workflow_stages = self._stage_view(job, metadata)
        result['stages'] = stages
        result['workflow_stages'] = workflow_stages
        result['resume_stages'] = workflow.resumable_stages(self.run_path(job), metadata=metadata) if job['status'] in ('failed','cancelled','completed') else []
        if self.externally_busy(job):
            result['can_delete'] = False
            result['resume_stages'] = []
            result['metadata_warnings'].append('An external worker still holds this run; reuse and deletion are blocked until it exits')
        if manifest.is_file() and not metadata:
            result['metadata_warnings'].append('Manifest is unreadable; inspect the original artifact')
        elapsed, warnings = self._elapsed(job)
        result['elapsed_seconds'] = elapsed
        result['metadata_warnings'].extend(warnings)
        result.update(self._eta(job, stages))
        for task in result['analyses']:
            if task['status'] == 'running':
                try: task['progress'] = json.loads((self.run_path(job)/task['directory']/'progress.json').read_text())['phase']
                except (OSError, ValueError): pass
        if summary:
            result['stages'] = [{k:v for k,v in stage.items() if k in _STAGE_SUMMARY_FIELDS} for stage in stages]
            result['detail_revision'] = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()
        return result


    @application_context
    def run_job(self, jid, worker=None):
        worker = worker or self.Worker()
        with self.JOBS_LOCK:
            if jid in self.WORKERS and self.WORKERS[jid] is not worker:
                return
            self.WORKERS[jid] = worker
        job = self.lookup(jid)
        work, log = self.run_path(job), self.log_path(job)
        in_place = bool(job.get('resume_in_place'))
        status, error, created = 'failed', None, False
        try:
            if worker.cancel.is_set():
                raise workflow.Cancelled('Cancelled by user')
            self.update_job(jid, status='running', stage='input', started_at=self.now(), log=str(log.relative_to(self.DATA.parent)))
            if in_place:
                if not work.is_dir(): raise FileNotFoundError(f'Existing run directory is missing: {work}')
                created = True
            else:
                work.mkdir(parents=True, exist_ok=False)
                created = True
            if job.get('layout_version') == 2: (work/'logs').mkdir(exist_ok=True)
            worker.run_dir = work
            worker.lease_file = self.lease(work/'.worker.lock')
            if not in_place:
                files.atomic_json(work/'manifest.json', {'id': jid, 'status': 'running', 'stages': [], **{k:job[k] for k in ('run_type','workflow_version','protocol_version','stage_plan','reference_run_id','shared_reference','molecule_id','molecule_snapshot','composition_id','composition_snapshot_sha256') if k in job}})
            if job.get('molecule_snapshot') and not (job.get('resume_of') or in_place):
                aa_molecules.verify_selection(self.ROOT/'molecules', job['molecule_snapshot'])
            aa_only=job.get('run_type')=='aa_only'
            composition_only=job.get('run_type')=='cg_composition'
            resuming = in_place or bool(job.get('resume_of'))
            if composition_only:
                from ..adapters.composition import readiness as composition_readiness
                readiness = composition_readiness(job['composition_id'], self.ROOT) if not resuming else {'ready': True}
            else:
                readiness = (aa.readiness(self.ROOT/'molecules',job['molecule_id']) if not resuming else {'ready':True}) if aa_only else workflow.readiness(job.get('molecule_id') or job['detergent'], job['method'], job.get('profile', 'standard'), job.get('mapping_snapshot'), molecule_root=self.ROOT / 'molecules')
            if not readiness['ready']:
                raise ValueError('; '.join(readiness['blockers']))
            source_id = None if in_place else (job.get('resume_of') or job.get('reference_run_id'))
            source_lease = self.lease(self.RUNS/source_id/'.worker.lock') if source_id else None
            try:
                if job.get('resume_of'):
                    workflow.prepare_resume(work, self.RUNS/job['resume_of'], job['resume_from'])
                elif not in_place and aa_only:
                    aa.prepare_run(work,self.ROOT/'molecules',job['molecule_snapshot'],job['settings'])
                elif not in_place and composition_only:
                    workflow.prepare_run(work, composition_id=job['composition_id'], settings=job.get('settings'))
                elif not in_place:
                    kwargs=dict(detergent=job['detergent'],profile=job.get('profile','standard'),settings={k:v for k,v in job.get('settings',{}).items() if k in workflow.SETTING_SPECS},mapping_candidate=job.get('mapping_snapshot'),bonded_state_snapshot=job.get('bonded_state_snapshot'),bonded_intent=job.get('bonded_intent','fit_and_simulate'),molecule_snapshot=job.get('molecule_snapshot'),molecule_root=self.ROOT / 'molecules')
                    if job.get('shared_reference'):kwargs.update(shared_reference=job['shared_reference'],reference_root=self.RUNS)
                    workflow.prepare_run(work, **kwargs)
            finally:
                if source_lease: source_lease.close()
            prepared = json.loads((work/'manifest.json').read_text())
            if job.get('molecule_snapshot'):
                if aa_only:files.verify(workflow.execution_root(work)/'common/molecule',job['molecule_snapshot']['sha256'])
                elif not job.get('shared_reference'):
                    raise ValueError('CG run is missing its shared AA reference')
                prepared.update(molecule_id=job['molecule_id'], molecule_snapshot=job['molecule_snapshot'])
            if composition_only:
                prepared.update(composition_id=job['composition_id'], composition_snapshot_sha256=job['composition_snapshot_sha256'])
            prepared.update(id=jid, status='running', started_at=self.now(),run_type=job.get('run_type','aa_cg'),workflow_version=job.get('workflow_version','aa-cg-v2'))
            if job.get('shared_reference'):prepared['settings']=job['settings']
            files.atomic_json(work/'manifest.json', prepared)
            def stage_changed(name, entry):
                if worker.cancel.is_set():
                    raise workflow.Cancelled('Cancelled by user')
                self.update_job(jid, stage=name, command=' '.join(entry['command']))
            workflow.run(work, log, execute=worker.execute, on_stage=stage_changed, stop_after='CG topology (ff_inter)' if job.get('bonded_intent') == 'fit_only' else None)
            if aa_only:aa_references.verify(work,molecule_snapshot=job['molecule_snapshot'])
            if job.get('bonded_intent') == 'fit_only' and job.get('mapping_snapshot'):
                topology = workflow.execution_root(work) / f"3_initial_CG/{prepared.get('cg_names', {}).get('final_itp', 'DDM.itp')}"
                state = bonded_states.create(job['mapping_snapshot'], f"Fit from {jid}", 'fast-forward-fit', {'run_id': jid}, topology.read_text(), 'complete')
                self.update_job(jid, bonded_state_id=state['state_id'], bonded_state_revision=state['revision'], bonded_state_snapshot=state['current'])
            status = 'completed'
        except workflow.Cancelled as exc:
            status, error = 'cancelled', str(exc)
        except Exception as exc:
            error = str(exc)
            if created:
                with log.open('a') as fp:
                    fp.write(f'\nRun failed: {error}\n')
        finally:
            try:
                if worker.cancel.is_set():
                    status, error = ('failed', worker.limit_error) if worker.limit_error else ('cancelled', 'Cancelled by user')
                manifest = work / 'manifest.json'
                if created and manifest.is_file():
                    try:
                        data = json.loads(manifest.read_text())
                        if not isinstance(data,dict): raise ValueError('Manifest must be an object')
                        if job.get('molecule_snapshot'):
                            data.update(molecule_id=job['molecule_id'], molecule_snapshot=job['molecule_snapshot'])
                        data.update(status=status, error=error, ended_at=self.now())
                        files.atomic_json(manifest, data)
                    except (OSError, ValueError) as exc:
                        status,error='failed',f'Manifest finalization failed: {exc}'
                self.update_job(jid,status=status,stage='complete' if status=='completed' else self.lookup(jid).get('stage','input'),ended_at=self.now(),error=error,
                           reference_eligible=bool(status=='completed' and job.get('run_type')=='aa_only'))
                self.artifact_index(self.lookup(jid), refresh=True)
            finally:
                if worker.lease_file: worker.lease_file.close()
                with self.JOBS_LOCK: self.WORKERS.pop(jid, None)
                self.schedule_waiting()


    def create_job(self, detergent, method, label='', retry_of=None, profile='standard', settings=None, reference_run_id=None, resume_of=None, resume_from=None, mapping_candidate=None, mapping_snapshot=None, bonded_state_id=None, bonded_intent='fit_and_simulate', temporary_validation=False, molecule_id=None, molecule_snapshot=None, run_type=None, composition_id=None):
        if run_type == 'cg_composition':
            if not composition_id: abort(400, 'CG composition runs require composition_id')
            if any(value for value in (reference_run_id, molecule_id, molecule_snapshot, mapping_candidate, mapping_snapshot, bonded_state_id)):
                abort(400, 'CG composition runs cannot use AA or ordinary mapping inputs')
            try:
                record = compositions.get(composition_id)
                from ..adapters.composition import readiness as composition_readiness
                ready = composition_readiness(composition_id, self.ROOT)
                if not ready['ready']: abort(409, '; '.join(ready['blockers']))
            except (ValueError, OSError, KeyError, FileNotFoundError) as exc: abort(404, str(exc))
            job = {'id': uuid.uuid4().hex[:12], 'detergent': record.get('name', composition_id),
                   'method': 'gromacs', 'label': str(label)[:160], 'status': 'queued', 'stage': 'queued',
                   'created': self.now(), 'retry_of': retry_of, 'profile': profile,
                   'settings': settings or {}, 'scientifically_validated': False,
                   'composition_id': composition_id, 'composition_snapshot_sha256': record['snapshot_hash'],
                   'run_type': run_type, 'workflow_version': 'cg-composition-v1', 'layout_version': 2,
                   'stage_plan': ['CG simulation', 'CG assessment', 'CG SASA'], 'resume_of': resume_of,
                   'resume_from': resume_from}
            return self.admit_jobs([job], job)
        if run_type not in (None,'aa_only','aa_cg'):abort(400,'Unknown run type')
        if run_type=='aa_only':
            if reference_run_id or mapping_candidate or mapping_snapshot or bonded_state_id:abort(400,'AA-only cannot use CG inputs or an AA source')
            if molecule_snapshot and not resume_of:
                try:aa_molecules.verify_selection(self.ROOT/'molecules',molecule_snapshot)
                except (OSError,ValueError) as exc:abort(409,str(exc))
            job=self.aa_job_record(molecule_id or detergent,label,settings,molecule_snapshot if resume_of else None)
            job.update(retry_of=retry_of,resume_of=resume_of,resume_from=resume_from)
            return self.admit_jobs([job],job)
        shared=run_type=='aa_cg'
        if shared:molecule_id=molecule_id or detergent
        if molecule_id is not None:
            try:
                aa_molecules.validate_id(molecule_id)
            except ValueError as exc: abort(400, str(exc))
            try:
                selected = molecule_snapshot if resume_of and molecule_snapshot else aa_molecules.selection(self.ROOT/'molecules', molecule_id)
                if molecule_snapshot and not resume_of and selected != molecule_snapshot:
                    raise ValueError('Molecule files changed; clone with a fresh selection instead')
                molecule_snapshot = selected if not resume_of else molecule_snapshot
            except (OSError, ValueError) as exc: abort(409, str(exc))
        if method not in self.ALLOWED_METHODS:
            abort(400, 'Unsupported method')
        if mapping_snapshot is not None:
            mapping_snapshot = workflow.draft_model.load(mapping_snapshot, molecule_root=self.ROOT / 'molecules')
        elif mapping_candidate:
            if not isinstance(mapping_candidate, str): abort(400, 'Mapping candidate must be a saved filename')
            try:
                context = (mapping_context.build_context(self.ROOT / 'molecules', molecule_snapshot['id'])
                           if molecule_snapshot else None)
                mapping_snapshot = workflow.draft_model.load(
                    mappings.get(mapping_candidate, context=context),
                    molecule_root=self.ROOT / 'molecules',
                )
            except FileNotFoundError: abort(400, 'Selected mapping is unavailable; refresh the candidate list')
        bonded_snapshot = None
        if bonded_state_id:
            try: bonded_snapshot = bonded_states.get(bonded_state_id)
            except (KeyError, OSError, ValueError): abort(400, 'Selected bonded state is unavailable')
            if mapping_snapshot is None or bonded_snapshot.get('mapping_hash') != mappings.mapping_identity(mapping_snapshot):
                abort(409, 'Bonded state does not belong to the selected mapping')
            if bonded_snapshot.get('current',{}).get('status') != 'complete': abort(409, 'Selected bonded state is incomplete; fit it before reuse')
        if bonded_intent == 'reuse_state' and bonded_snapshot is None:
            abort(409, 'Reuse state intent requires a complete bonded state')
        if shared:
            supplied=settings or {}
            unknown=set(supplied)-set(aa.SETTING_SPECS)-set(workflow.SETTING_SPECS)
            if unknown:abort(400,'Unknown run settings: '+', '.join(sorted(unknown)))
            aa_settings=aa.normalize_settings({k:v for k,v in supplied.items() if k in aa.SETTING_SPECS})
            legacy_settings=workflow.normalize_settings({k:v for k,v in supplied.items() if k in workflow.SETTING_SPECS} | {'aa_equil_ps':aa_settings['aa_nvt_ps']+aa_settings['aa_npt_ps'],'aa_production_ps':aa_settings['aa_production_ps'],'temperature_k':aa_settings['temperature_k'],'output_interval_ps':aa_settings['output_interval_ps']},profile)
            settings=legacy_settings|aa_settings
        else:settings = workflow.normalize_settings(settings, profile)
        reference_snapshot=None
        if reference_run_id and shared:
            try:
                _,reference_snapshot=aa_references.resolve(self.RUNS,reference_run_id,molecule_snapshot=molecule_snapshot,settings=settings)
                if self.lookup(reference_run_id).get('status')!='completed':raise ValueError('AA source must be completed')
            except (OSError,ValueError) as exc:abort(409,str(exc))
        elif reference_run_id:
            abort(409, 'CG runs require a shared AA reference')
        ready = workflow.readiness(molecule_id or detergent, method, profile, mapping_snapshot, molecule_root=self.ROOT / 'molecules')
        if not ready['ready']:
            abort(409, '; '.join(ready['blockers']))
        job = {'id': uuid.uuid4().hex[:12], 'detergent': detergent, 'method': method, 'label': str(label)[:160],
               'status': 'queued', 'stage': 'queued', 'created': self.now(), 'retry_of': retry_of, 'profile': profile, 'settings': settings, 'reference_run_id': reference_run_id, 'scientifically_validated': False, 'temporary_validation': bool(temporary_validation), 'bonded_intent': bonded_intent}
        if mapping_snapshot is not None:
            job.update(mapping_candidate=mapping_snapshot.get('file'), mapping_snapshot=mapping_snapshot)
        if bonded_snapshot is not None:
            job.update(bonded_state_id=bonded_state_id, bonded_state_revision=bonded_snapshot.get('revision'), bonded_state_snapshot=bonded_snapshot.get('current'))
        if molecule_snapshot is not None:
            job.update(molecule_id=molecule_snapshot['id'], molecule_snapshot=molecule_snapshot)
        job.update(layout_version=2, resume_of=resume_of, resume_from=resume_from)
        job.update(run_type='aa_cg',workflow_version='aa-cg-v2',stage_plan=[name for name,_ in workflow.STAGES])
        if shared:
            if reference_snapshot:
                job['shared_reference']={'source_run_id':reference_run_id,'sha256':reference_snapshot['sha256']}
                return self.admit_jobs([job],job)
            if resume_of:abort(409,'Shared CG resume requires its AA reference source')
            parent=self.aa_job_record(molecule_id,(str(label)+' · AA source').strip(),aa_settings)
            job.update(status='waiting',stage='Waiting for AA reference',reference_run_id=parent['id'])
            return self.admit_jobs([parent,job],parent,result=job)
        worker = self.Worker()
        with self.JOBS_LOCK:
            if len(self.WORKERS)+sum(self.externally_busy(j) for j in self.load()) >= self.limits()['max_concurrent_runs']: abort(409, 'Simulation capacity is busy; wait for a run to stop')
            source_id = resume_of or reference_run_id
            required = 2*resources.usage(self.RUNS/source_id) if source_id else 0
            if required > self.limits()['max_run_bytes']: abort(409, 'Source copies exceed the per-run storage limit')
            resources.admit(self.storage_report(), len(self.WORKERS)+len(self.ANALYSIS_WORKERS), required)
            self.database().insert(job)
            self.WORKERS[job['id']] = worker
            threading.Thread(target=self.run_job, args=(job['id'], worker), daemon=True).start()
        return job


    def aa_job_record(self, molecule_id,label,settings,snapshot=None):
        try:
            aa_molecules.validate_id(molecule_id)
            selected=snapshot or aa_molecules.selection(self.ROOT/'molecules',molecule_id,run_type='aa_only')
            settings=aa.normalize_settings(settings)
            if not snapshot:
                ready=aa.readiness(self.ROOT/'molecules',molecule_id)
                if not ready['ready']:raise ValueError('; '.join(ready['blockers']))
        except (ValueError,OSError) as exc:abort(409,str(exc))
        return {'id':uuid.uuid4().hex[:12],'detergent':molecule_id,'molecule_id':molecule_id,'molecule_snapshot':selected,
                'method':'gromacs','run_type':'aa_only','workflow_version':aa.VERSION,'protocol_version':aa.VERSION,
                'stage_plan':[name for name,_ in aa.STAGES],'label':str(label)[:160],
                'status':'queued','stage':'queued','created':self.now(),'settings':settings,'profile':aa.VERSION,
                'layout_version':2,'scientifically_validated':False,'reference_eligible':False}


    def admit_jobs(self, records,first,result=None):
        with self.JOBS_LOCK:
            if len(self.WORKERS)+sum(self.externally_busy(j) for j in self.load())>=self.limits()['max_concurrent_runs']:abort(409,'Simulation capacity is busy; wait for a run to stop')
            copies=[]
            for job in records:
                required=2*resources.usage(self.RUNS/job['resume_of']) if job.get('resume_of') else 0
                if required>self.limits()['max_run_bytes']:abort(409,'Source copies exceed the per-run storage limit')
                copies.append(required)
            resources.admit(self.storage_report(),len(self.WORKERS)+len(self.ANALYSIS_WORKERS)+len(records)-1,sum(copies))
            self.database().insert_many(records)
            worker=self.Worker();self.WORKERS[first['id']]=worker
            threading.Thread(target=self.run_job,args=(first['id'],worker),daemon=True).start()
        return result or first


    def schedule_waiting(self):
        """One fixed dependency: CG waits for its AA source without a worker slot."""
        with self.JOBS_LOCK:
            for job in reversed(self.load()):
                if job.get('status')!='waiting':continue
                source=self.database().get(job['reference_run_id'])
                if not source or source['status'] in ('failed','blocked','cancelled'):
                    self.update_job(job['id'],status='cancelled' if source and source['status']=='cancelled' else 'blocked',
                               ended_at=self.now(),error='AA source did not complete; clone with a new source',stage='AA source unavailable')
                    continue
                if source['status']!='completed':continue
                if len(self.WORKERS)+sum(self.externally_busy(j) for j in self.load())>=self.limits()['max_concurrent_runs']:continue
                try:
                    _,reference=aa_references.resolve(self.RUNS,source['id'],molecule_snapshot=job['molecule_snapshot'],settings=job['settings'])
                    resources.admit(self.storage_report(),len(self.WORKERS)+len(self.ANALYSIS_WORKERS))
                except (ValueError,OSError) as exc:
                    self.update_job(job['id'],status='blocked',error=str(exc),ended_at=self.now());continue
                self.update_job(job['id'],status='queued',stage='queued',shared_reference={'source_run_id':source['id'],'sha256':reference['sha256']})
                worker=self.Worker();self.WORKERS[job['id']]=worker
                threading.Thread(target=self.run_job,args=(job['id'],worker),daemon=True).start()


    def manifest_data(self, job):
        return self.MANIFEST_CACHE.read(self.run_path(job)/'manifest.json')


    def update_analysis(self, jid, aid, **fields):
        return self.analysis_coordinator.update(jid, aid, **fields)


    def analysis_dependencies(self, job):
        return self.analysis_coordinator.dependencies(job)


    @application_context
    def run_analysis(self, jid, aid, worker):
        return self.analysis_coordinator.run(jid, aid, worker)




    def delete_job(self, jid):
        with self.JOBS_LOCK:
            job = self.lookup(jid)
            if job['status'] not in ('completed', 'failed', 'cancelled','blocked'):
                abort(409, 'Only completed, failed, or cancelled runs can be deleted')
            if jid in self.WORKERS or any(key[0] == jid for key in list(self.ANALYSIS_WORKERS)):
                abort(409, 'This run still has an active worker')
            # Keep the record visible if filesystem cleanup fails, so deletion can be retried.
            run_dir = self.run_path(job)
            log = self.log_path(job)
            if run_dir.is_symlink():
                abort(409, 'Refusing to delete a run directory that is a symbolic link')
            def cleanup():
                if run_dir.exists():
                    with self.lease(run_dir/'.worker.lock'):
                        shutil.rmtree(run_dir)
                log.unlink(missing_ok=True)
            try:
                self.database().delete_with_cleanup(jid, cleanup)
            except (OSError, ValueError) as exc:
                abort(409, f'Run cleanup failed; the run record is retained for retry: {exc}')
        return jid


    def cancel_job(self, jid):
        with self.JOBS_LOCK:
            job = self.lookup(jid)
            if job['status']=='waiting':
                self.update_job(jid,status='cancelled',ended_at=self.now(),error='Cancelled while waiting for AA source')
                return self.lookup(jid), 202
            if job['status'] in ('cancelled', 'cancelling'):
                return job, 200
            worker = self.WORKERS.get(jid)
            if worker is None or job['status'] not in ('queued', 'running'):
                abort(409, 'This server does not own an active worker for this run')
            # Persist the request before acknowledgement by the worker.
            self.update_job(jid, status='cancelling')
            worker.cancel.set()
            return self.lookup(jid), 202


    def cancel_analysis(self, jid, aid):
        return self.analysis_coordinator.cancel(jid, aid)


    def queue_analysis(self, jid, kind, payload):
        return self.analysis_coordinator.queue(jid, kind, payload)
