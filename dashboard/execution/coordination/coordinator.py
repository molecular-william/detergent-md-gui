"""Application-owned execution coordination and persistent job lifecycle."""
import fcntl
import json
import re
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone
from functools import wraps

from dashboard import files, store

from ...analysis.runs import observability
from ...analysis.runs import references as aa_references
from ...models import compositions, mappings
from ...models.bonded import states as bonded_states
from ...models.mappings import context as mapping_context
from ...models.molecules import aa as aa_molecules
from ...web import views
from .. import protocol, workflow
from ..adapters import aa, cg
from . import admission, resources, temporary
from .analysis_coordinator import AnalysisCoordinator
from .attempt import attempt as managed_attempt
from .errors import CapacityFull, DependencyRetained, InvalidRequest, InvalidRunId, RunBusy, RunConflict, RunNotFound, SourceUnavailable
from .manifest import ManifestCache
from .manifest import stage_log_path as resolve_stage_log
from .worker import Worker


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
        """The one timestamp format the records carry; every stage and record uses it."""
        return datetime.now(timezone.utc).isoformat()


    def database(self):
        """The store this coordinator writes through: the runs directory decides where it lives."""
        return store.Store(self.DATA)


    def lookup(self, jid):
        """The record for a run, or RunNotFound: an unknown run is a domain failure here."""
        job = self.database().get(jid)
        if job is None: raise RunNotFound('Unknown run')
        return job


    def resume_in_place(self, jid, stage):
        """Queue an in-place resume on the existing job and run directory."""
        with self.JOBS_LOCK:
            job = self.lookup(jid)
            if job.get('status') not in ('failed', 'cancelled', 'completed') or jid in self.WORKERS:
                raise RunBusy('Run must be stopped before it can be resumed')
            if any(key[0] == jid for key in list(self.ANALYSIS_WORKERS)) or any(
                    task.get('status') in ('queued', 'running', 'cancelling') for task in job.get('analyses', [])):
                raise RunBusy('Active analyses must finish before the run can be resumed')
            if self.externally_busy(job):
                raise RunBusy('An external worker still holds this run')
            if any(other.get('reference_run_id') == jid or other.get('resume_of') == jid
                   for other in self.database().all() if other.get('id') != jid):
                raise DependencyRetained('The run has retained consumers; resume the consumers or clone this run')
            if len(self.WORKERS) + sum(self.externally_busy(item) for item in self.database().all()) >= self.limits()['max_concurrent_runs']:
                raise CapacityFull('Simulation capacity is busy; wait for a run to stop')
            try:
                resources.check_worker(self.run_path(job), self.RUNS, self.limits())
            except (OSError, ValueError) as exc:
                raise RunBusy(str(exc))
            path = self.run_path(job)
            try:
                lease = self.lease(path / '.worker.lock')
            except ValueError as exc:
                raise RunBusy(str(exc))
            try:
                if stage not in workflow.resumable_stages(path):
                    raise RunConflict('Cannot resume that stage; choose a completed-stage boundary')
                try:
                    prepared = workflow.prepare_resume_in_place(path, stage, analyses=job.get('analyses', []), finalize=False)
                except (OSError, ValueError, KeyError) as exc:
                    raise RunConflict(str(exc))
                try:
                    updated = self.database().update(jid, status='queued', stage='queued', started_at=None, ended_at=None,
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
                self.database().update(jid, status='failed', stage='queued', error=str(exc), ended_at=self.now())
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
        for job in self.database().all():
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
            if updates: self.database().update(job['id'], **updates)


    def ensure_service(self):
        if self.app.config.get('DISABLE_COORDINATOR'): return
        key = str(self.DATA.resolve())
        with self.JOBS_LOCK:
            if key not in self.SERVICES:
                try: self.SERVICES[key] = self.lease(self.DATA.with_suffix('.service.lock'))
                except ValueError: raise RunBusy('Another dashboard process owns this database; use one coordinator process')
                self.reconcile()
                temporary.cleanup(self.database().all(), self.RUNS, self.database())
            self.schedule_waiting()


    def limits(self):
        return resources.policy(self.ROOT/'config/dashboard.json')


    def storage_report(self):
        return resources.report(self.RUNS, self.database().all(), self.limits())


    def artifact_index(self, job, refresh=False):
        entries, updated = self.database().artifacts(job['id'])
        if entries is None or refresh or (job['status'] in ('running','cancelling') and time.time()-updated > 15):
            entries = observability.artifacts(self.run_path(job))
            self.database().artifacts(job['id'], entries)
            self.database().update(job['id'], artifact_revision=time.time())
        return entries


    def run_path(self, job):
        # Never use arbitrary manifest/log paths supplied by a client or old metadata.
        if not re.fullmatch(r'[a-f0-9]{12}', job['id']):
            raise InvalidRunId('Invalid run ID')
        path = self.RUNS / job['id']
        if path.is_symlink(): raise RunConflict('Run directories must not be symbolic links')
        return path


    def log_path(self, job):
        return self.run_path(job)/'logs/console.log' if job.get('layout_version') == 2 else self.DATA.parent / f'{self.run_path(job).name}.log'


    def stage_log_path(self, job, recorded):
        """Resolve captured log provenance within this run after workspace moves."""
        return resolve_stage_log(self.run_path(job), recorded=recorded)


    def tail(self, path, limit=65536):
        return views.tail(path, limit)


    def parse_gromacs_eta(self, text):
        return views.parse_gromacs_eta(text)


    def ownership(self, job):
        """can_cancel / can_retry / can_delete for a run one of this instance's workers holds.

        The view takes these flags as an argument; only the coordinator knows which of
        its workers is holding a run.
        """
        return views.ownership_flags(job, active=job['id'] in self.WORKERS,
                                     analysis_active=any(key[0] == job['id'] for key in list(self.ANALYSIS_WORKERS)))


    def public_job(self, job, summary=False):
        """The browser's view of a run.

        The routes assemble this directly through dashboard/web/views.py now; this stays
        as the coordinator's own answer to the same question until the last callers go.
        """
        run_dir = self.run_path(job) if views.usable_run_id(job) else None
        if run_dir is None:
            return views.run_view(job, summary=summary)
        return views.run_view(job, run_dir=run_dir,
                              manifest=self.MANIFEST_CACHE.read(run_dir / 'manifest.json'),
                              ownership=self.ownership(job), busy=self.externally_busy(job),
                              console_log=self.log_path(job), summary=summary)


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
        created = False
        record = {'status': 'failed', 'error': None}

        def write_job(rec, **fields):
            """How this site writes: the entry transition goes to the database at once.

            The terminal status stays local, because the exit hook below must be able to override it
            from `worker.limit_error` before anything is written. A terminal write here would land
            before that override and record the wrong thing for a run the worker killed.
            """
            if fields.get('status') == 'running':
                self.database().update(jid, **fields)
            rec.update(fields)

        def finish_job(rec):
            """The one terminal write: the manifest, then the job row, then the artifact index."""
            status, error = rec['status'], rec['error']
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
                self.database().update(jid,status=status,stage='complete' if status=='completed' else self.lookup(jid).get('stage','input'),ended_at=self.now(),error=error,
                           reference_eligible=bool(status=='completed' and job.get('run_type')=='aa_only'))
                self.artifact_index(self.lookup(jid), refresh=True)
            finally:
                if worker.lease_file: worker.lease_file.close()
                with self.JOBS_LOCK: self.WORKERS.pop(jid, None)
                self.schedule_waiting()
            rec['status'], rec['error'] = status, error

        try:
            with managed_attempt(record, update=write_job,
                                 running={'stage': 'input', 'started_at': self.now(),
                                          'log': str(log.relative_to(self.DATA.parent))},
                                 on_exit=finish_job):
                if worker.cancel.is_set():
                    raise workflow.Cancelled('Cancelled by user')
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
                if resuming:
                    readiness = {'ready': True}
                else:
                    readiness = protocol.adapter_for(job.get('run_type') or 'aa_cg').readiness({
                        'molecule_id': job.get('molecule_id') or job.get('detergent'),
                        'molecule_root': self.ROOT / 'molecules', 'method': job.get('method'),
                        'profile': job.get('profile', 'standard'), 'mapping_candidate': job.get('mapping_snapshot'),
                        'composition_id': job.get('composition_id'), 'root': self.ROOT,
                        'protein': job.get('protein'), 'template': job.get('template'),
                        'settings': job.get('settings') or {},
                        'solute_root': (job.get('settings') or {}).get('solute_root'),
                        'project_root': str(self.ROOT)})
                if not readiness['ready']:
                    raise ValueError('; '.join(readiness['blockers']))
                source_id = None if in_place else (job.get('resume_of') or job.get('reference_run_id'))
                source_lease = self.lease(self.RUNS/source_id/'.worker.lock') if source_id else None
                try:
                    if job.get('resume_of'):
                        workflow.prepare_resume(work, self.RUNS/job['resume_of'], job['resume_from'])
                    elif not in_place and (aa_only or composition_only):
                        protocol.adapter_for(job.get('run_type')).prepare(
                            work, {'molecule_root': self.ROOT/'molecules', 'molecule_snapshot': job.get('molecule_snapshot'),
                                   'composition_id': job.get('composition_id'), 'settings': job.get('settings')})
                    elif not in_place and job.get('run_type') == 'pdc':
                        # The pdc adapter writes its own six stages; the CG kwargs below describe a molecule.
                        protocol.adapter_for('pdc').prepare(
                            work, {'protein': job.get('protein'), 'template': job.get('template'),
                                   'mapping_candidate': job.get('mapping_candidate') or job.get('mapping_snapshot'),
                                   'settings': job.get('settings'), 'project_root': str(self.ROOT)})
                    elif not in_place and job.get('run_type') == 'osmotic':
                        # An osmotic condition writes its own single stage; the CG kwargs below describe a molecule
                        # and would filter the settings down to keys this run type does not use -- dropping the
                        # molality, which is the one setting that makes a series a series.
                        protocol.adapter_for('osmotic').prepare(
                            work, {'settings': job.get('settings') or {},
                                   'mapping_snapshot': job.get('mapping_snapshot'),
                                   'molecule_id': job.get('molecule_id'),
                                   'molecule_root': self.ROOT / 'molecules'})
                    elif not in_place:
                        # The same door the four branches above use. The run type's own prepare now owns the stage
                        # directory, the `inputs/` copy and the manifest, and applies its own settings dialect -- the
                        # coordinator used to filter the settings and assemble the arguments before calling into the
                        # orchestrator, which put a run type's vocabulary in the queue.
                        protocol.adapter_for(protocol.run_type_of(job)).prepare(work, {
                            'detergent': job['detergent'], 'profile': job.get('profile', 'standard'),
                            'settings': job.get('settings') or {},
                            'mapping_candidate': job.get('mapping_snapshot'),
                            'bonded_state_snapshot': job.get('bonded_state_snapshot'),
                            'bonded_intent': job.get('bonded_intent', 'fit_and_simulate'),
                            'molecule_snapshot': job.get('molecule_snapshot'),
                            'molecule_root': self.ROOT / 'molecules',
                            **({'shared_reference': job['shared_reference'], 'reference_root': self.RUNS}
                               if job.get('shared_reference') else {})})
                finally:
                    if source_lease: source_lease.close()
                prepared = json.loads((work/'manifest.json').read_text())
                if job.get('molecule_snapshot'):
                    if aa_only:files.verify(workflow.execution_root(work)/'common/molecule',job['molecule_snapshot']['sha256'])
                    elif job.get('run_type') == 'aa_cg' and not job.get('shared_reference'):
                        # Only a CG run consumes an AA reference. A protein-detergent build names the detergent's
                        # molecule for provenance, and demanding a reference for it refused every pdc job.
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
                    self.database().update(jid, stage=name, command=' '.join(entry['command']))
                workflow.run(work, log, execute=worker.execute, on_stage=stage_changed, stop_after='CG topology (ff_inter)' if job.get('bonded_intent') == 'fit_only' else None)
                if aa_only:aa_references.verify(work,molecule_snapshot=job['molecule_snapshot'])
                if job.get('bonded_intent') == 'fit_only' and job.get('mapping_snapshot'):
                    topology = workflow.execution_root(work) / f"3_initial_CG/{prepared.get('cg_names', {}).get('final_itp', 'DDM.itp')}"
                    state = bonded_states.create(job['mapping_snapshot'], f"Fit from {jid}", 'fast-forward-fit', {'run_id': jid}, topology.read_text(), 'complete')
                    self.database().update(jid, bonded_state_id=state['state_id'], bonded_state_revision=state['revision'], bonded_state_snapshot=state['current'])
        except Exception as exc:
            # The lifecycle has already recorded the failure; the run log line is this site's own.
            if created:
                with log.open('a') as fp:
                    fp.write(f'\nRun failed: {exc}\n')


    def create_job(self, detergent, method, label='', retry_of=None, profile='standard', settings=None, reference_run_id=None, resume_of=None, resume_from=None, mapping_candidate=None, mapping_snapshot=None, bonded_state_id=None, bonded_intent='fit_and_simulate', temporary_validation=False, molecule_id=None, molecule_snapshot=None, run_type=None, composition_id=None, protein=None, template=None):
        try:
            admission.validate_run_type({'run_type': run_type, 'composition_id': composition_id,
                                         'molecule_id': molecule_id, 'molecule_snapshot': molecule_snapshot,
                                         'reference_run_id': reference_run_id, 'mapping_candidate': mapping_candidate,
                                         'mapping_snapshot': mapping_snapshot, 'bonded_state_id': bonded_state_id,
                                         'method': method,
                                         'bonded_intent': None if bonded_intent in (None, 'fit_and_simulate') else bonded_intent,
                                         **(settings or {})})
        except ValueError as exc:
            raise InvalidRequest(str(exc))
        if run_type == 'cg_composition':
            try:
                record = compositions.get(composition_id)
                from ..adapters.composition import readiness as composition_readiness
                ready = composition_readiness(composition_id, self.ROOT)
                if not ready['ready']: raise RunConflict('; '.join(ready['blockers']))
            except (ValueError, OSError, KeyError, FileNotFoundError) as exc: raise RunNotFound(str(exc))
            job = {'id': uuid.uuid4().hex[:12], 'detergent': record.get('name', composition_id),
                   'method': 'gromacs', 'label': str(label)[:160], 'status': 'queued', 'stage': 'queued',
                   'created': self.now(), 'retry_of': retry_of, 'profile': profile,
                   'settings': settings or {}, 'scientifically_validated': False,
                   'composition_id': composition_id, 'composition_snapshot_sha256': record['snapshot_hash'],
                   'run_type': run_type, 'workflow_version': 'cg-composition-v1', 'layout_version': 2,
                   'stage_plan': ['CG simulation', 'CG assessment', 'CG SASA'], 'resume_of': resume_of,
                   'resume_from': resume_from}
            return self.admit_jobs([job], job)
        if run_type=='aa_only':
            if molecule_snapshot and not resume_of:
                try:aa_molecules.verify_selection(self.ROOT/'molecules',molecule_snapshot)
                except (OSError,ValueError) as exc:raise RunConflict(str(exc))
            job=self.aa_job_record(molecule_id or detergent,label,settings,molecule_snapshot if resume_of else None,profile)
            job.update(retry_of=retry_of,resume_of=resume_of,resume_from=resume_from)
            return self.admit_jobs([job],job)
        shared=run_type=='aa_cg'
        if shared:molecule_id=molecule_id or detergent
        if molecule_id is not None:
            try:
                aa_molecules.validate_id(molecule_id)
            except ValueError as exc: raise InvalidRequest(str(exc))
            try:
                selected = molecule_snapshot if resume_of and molecule_snapshot else aa_molecules.selection(self.ROOT/'molecules', molecule_id)
                if molecule_snapshot and not resume_of and selected != molecule_snapshot:
                    raise ValueError('Molecule files changed; clone with a fresh selection instead')
                molecule_snapshot = selected if not resume_of else molecule_snapshot
            except (OSError, ValueError) as exc: raise RunConflict(str(exc))
        if method not in self.ALLOWED_METHODS:
            raise InvalidRequest('Unsupported method')
        if mapping_snapshot is not None:
            mapping_snapshot = cg.draft_model.load(mapping_snapshot, molecule_root=self.ROOT / 'molecules')
        elif mapping_candidate:
            if not isinstance(mapping_candidate, str): raise InvalidRequest('Mapping candidate must be a saved filename')
            try:
                context = (mapping_context.build_context(self.ROOT / 'molecules', molecule_snapshot['id'])
                           if molecule_snapshot else None)
                mapping_snapshot = cg.draft_model.load(
                    mappings.get(mapping_candidate, context=context),
                    molecule_root=self.ROOT / 'molecules',
                )
            except FileNotFoundError: raise InvalidRequest('Selected mapping is unavailable; refresh the candidate list')
        bonded_snapshot = None
        if bonded_state_id:
            try: bonded_snapshot = bonded_states.get(bonded_state_id)
            except (KeyError, OSError, ValueError): raise InvalidRequest('Selected bonded state is unavailable')
            if mapping_snapshot is None or not bonded_states.belongs_to(bonded_snapshot, mapping_snapshot):
                raise RunConflict('Bonded state does not belong to the selected mapping')
            if bonded_snapshot.get('current',{}).get('status') != 'complete': raise RunConflict('Selected bonded state is incomplete; fit it before reuse')
        if bonded_intent == 'reuse_state' and bonded_snapshot is None:
            raise RunConflict('Reuse state intent requires a complete bonded state')
        settings = protocol.adapter_for(run_type or 'aa_cg').normalize_settings(settings, profile)
        reference_snapshot=None
        if reference_run_id and shared:
            try:
                _,reference_snapshot=aa_references.resolve(self.RUNS,reference_run_id,molecule_snapshot=molecule_snapshot,settings=settings)
                if self.lookup(reference_run_id).get('status')!='completed':raise ValueError('AA source must be completed')
            except (OSError,ValueError) as exc:raise SourceUnavailable(str(exc))
        elif reference_run_id:
            raise SourceUnavailable('CG runs require a shared AA reference')
        if (run_type or 'aa_cg') == 'pdc':
            # A protein-detergent build's inputs are a protein and a detergent template rather than a molecule, so
            # it is checked by its own adapter; asking the CG adapter about it is how a pdc job used to be refused.
            ready = protocol.adapter_for('pdc').readiness({'protein': protein, 'template': template,
                                                           'project_root': str(self.ROOT)})
        else:
            ready = cg.readiness(molecule_id or detergent, method, profile, mapping_snapshot, molecule_root=self.ROOT / 'molecules')
        if not ready['ready']:
            raise RunConflict('; '.join(ready['blockers']))
        job = {'id': uuid.uuid4().hex[:12], 'detergent': detergent, 'method': method, 'label': str(label)[:160],
               'status': 'queued', 'stage': 'queued', 'created': self.now(), 'retry_of': retry_of, 'profile': profile, 'settings': settings, 'reference_run_id': reference_run_id, 'scientifically_validated': False, 'temporary_validation': bool(temporary_validation), 'bonded_intent': bonded_intent}
        # The run type has to be on the record before the worker starts: everything downstream -- readiness, the
        # stage plan, which adapter writes the run -- is chosen by it, and a job that only carries a method is read
        # as a CG run by the adapter that answers about methods.
        job['run_type'] = run_type or 'aa_cg'
        if protein is not None:
            job['protein'] = protein
        if template is not None:
            job['template'] = template
        if mapping_snapshot is not None:
            job.update(mapping_candidate=mapping_snapshot.get('file'), mapping_snapshot=mapping_snapshot)
        if bonded_snapshot is not None:
            job.update(bonded_state_id=bonded_state_id, bonded_state_revision=bonded_snapshot.get('revision'), bonded_state_snapshot=bonded_snapshot.get('current'))
        if molecule_snapshot is not None:
            job.update(molecule_id=molecule_snapshot['id'], molecule_snapshot=molecule_snapshot)
        job.update(layout_version=2, resume_of=resume_of, resume_from=resume_from)
        # The stage plan and the workflow version belong to the run's own type. Stamping every job that reaches here
        # as a CG run is why a protein-detergent job was answered by the CG adapter's readiness check -- which knows
        # only the methods it fits -- and refused as "not connected to an executable workflow".
        if job['run_type'] == 'aa_cg':
            job.update(workflow_version='aa-cg-v2', stage_plan=[name for name, _ in cg.STAGES])
        else:
            job.update(workflow_version=f"{job['run_type']}-v1",
                       stage_plan=[stage.name for stage in protocol.adapter_for(job['run_type']).stages({})])
        if shared:
            if reference_snapshot:
                job['shared_reference']={'source_run_id':reference_run_id,'sha256':reference_snapshot['sha256']}
                return self.admit_jobs([job],job)
            if resume_of:raise SourceUnavailable('Shared CG resume requires its AA reference source')
            # The AA source is an aa_only run, so its settings are the ones an aa_only run accepts -- asked of the
            # run type rather than read off the AA adapter, which is the same answer without the coupling.
            aa_settings = {key: value for key, value in settings.items()
                           if key in protocol.adapter_for('aa_only').settings_specs()}
            parent=self.aa_job_record(molecule_id,(str(label)+' · AA source').strip(),aa_settings,profile=profile)
            job.update(status='waiting',stage='Waiting for AA reference',reference_run_id=parent['id'])
            return self.admit_jobs([parent,job],parent,result=job)
        worker = self.Worker()
        with self.JOBS_LOCK:
            if len(self.WORKERS)+sum(self.externally_busy(j) for j in self.database().all()) >= self.limits()['max_concurrent_runs']: raise CapacityFull('Simulation capacity is busy; wait for a run to stop')
            source_id = resume_of or reference_run_id
            required = 2*resources.usage(self.RUNS/source_id) if source_id else 0
            if required > self.limits()['max_run_bytes']: raise CapacityFull('Source copies exceed the per-run storage limit')
            resources.admit(self.storage_report(), len(self.WORKERS)+len(self.ANALYSIS_WORKERS), required)
            self.database().insert(job)
            self.WORKERS[job['id']] = worker
            threading.Thread(target=self.run_job, args=(job['id'], worker), daemon=True).start()
        return job


    def aa_job_record(self, molecule_id,label,settings,snapshot=None,profile='standard'):
        try:
            aa_molecules.validate_id(molecule_id)
            selected=snapshot or aa_molecules.selection(self.ROOT/'molecules',molecule_id,run_type='aa_only')
            settings=aa.normalize_settings(settings,profile)
            if not snapshot:
                ready=aa.readiness(self.ROOT/'molecules',molecule_id)
                if not ready['ready']:raise ValueError('; '.join(ready['blockers']))
        except (ValueError,OSError) as exc:raise RunConflict(str(exc))
        return {'id':uuid.uuid4().hex[:12],'detergent':molecule_id,'molecule_id':molecule_id,'molecule_snapshot':selected,
                'method':'gromacs','run_type':'aa_only','workflow_version':aa.VERSION,'protocol_version':aa.VERSION,
                'stage_plan':[name for name,_ in aa.STAGES],'label':str(label)[:160],
                'status':'queued','stage':'queued','created':self.now(),'settings':settings,'profile':profile,
                'layout_version':2,'scientifically_validated':False,'reference_eligible':False}


    def admit_jobs(self, records,first,result=None):
        with self.JOBS_LOCK:
            if len(self.WORKERS)+sum(self.externally_busy(j) for j in self.database().all())>=self.limits()['max_concurrent_runs']:raise CapacityFull('Simulation capacity is busy; wait for a run to stop')
            copies=[]
            for job in records:
                required=2*resources.usage(self.RUNS/job['resume_of']) if job.get('resume_of') else 0
                if required>self.limits()['max_run_bytes']:raise CapacityFull('Source copies exceed the per-run storage limit')
                copies.append(required)
            resources.admit(self.storage_report(),len(self.WORKERS)+len(self.ANALYSIS_WORKERS)+len(records)-1,sum(copies))
            self.database().insert_many(records)
            worker=self.Worker();self.WORKERS[first['id']]=worker
            threading.Thread(target=self.run_job,args=(first['id'],worker),daemon=True).start()
        return result or first


    def schedule_waiting(self):
        """One fixed dependency: CG waits for its AA source without a worker slot."""
        with self.JOBS_LOCK:
            for job in reversed(self.database().all()):
                if job.get('status')!='waiting':continue
                source=self.database().get(job['reference_run_id'])
                if not source or source['status'] in ('failed','blocked','cancelled'):
                    self.database().update(job['id'],status='cancelled' if source and source['status']=='cancelled' else 'blocked',
                               ended_at=self.now(),error='AA source did not complete; clone with a new source',stage='AA source unavailable')
                    continue
                if source['status']!='completed':continue
                if len(self.WORKERS)+sum(self.externally_busy(j) for j in self.database().all())>=self.limits()['max_concurrent_runs']:continue
                try:
                    _,reference=aa_references.resolve(self.RUNS,source['id'],molecule_snapshot=job['molecule_snapshot'],settings=job['settings'])
                    resources.admit(self.storage_report(),len(self.WORKERS)+len(self.ANALYSIS_WORKERS))
                except (ValueError,OSError) as exc:
                    self.database().update(job['id'],status='blocked',error=str(exc),ended_at=self.now());continue
                self.database().update(job['id'],status='queued',stage='queued',shared_reference={'source_run_id':source['id'],'sha256':reference['sha256']})
                worker=self.Worker();self.WORKERS[job['id']]=worker
                threading.Thread(target=self.run_job,args=(job['id'],worker),daemon=True).start()


    def manifest_data(self, job):
        """The run's manifest, read through the run's own path and the shared cache."""
        return self.MANIFEST_CACHE.read(self.run_path(job)/'manifest.json')





    def delete_job(self, jid):
        with self.JOBS_LOCK:
            job = self.lookup(jid)
            if job['status'] not in ('completed', 'failed', 'cancelled','blocked'):
                raise RunConflict('Only completed, failed, or cancelled runs can be deleted')
            if jid in self.WORKERS or any(key[0] == jid for key in list(self.ANALYSIS_WORKERS)):
                raise RunBusy('This run still has an active worker')
            # Keep the record visible if filesystem cleanup fails, so deletion can be retried.
            run_dir = self.run_path(job)
            log = self.log_path(job)
            if run_dir.is_symlink():
                raise RunConflict('Refusing to delete a run directory that is a symbolic link')
            def cleanup():
                if run_dir.exists():
                    with self.lease(run_dir/'.worker.lock'):
                        shutil.rmtree(run_dir)
                log.unlink(missing_ok=True)
            try:
                self.database().delete_with_cleanup(jid, cleanup)
            except (OSError, ValueError) as exc:
                raise RunConflict(f'Run cleanup failed; the run record is retained for retry: {exc}')
        return jid


    def cancel_job(self, jid):
        with self.JOBS_LOCK:
            job = self.lookup(jid)
            if job['status']=='waiting':
                self.database().update(jid,status='cancelled',ended_at=self.now(),error='Cancelled while waiting for AA source')
                return self.lookup(jid), 202
            if job['status'] in ('cancelled', 'cancelling'):
                return job, 200
            worker = self.WORKERS.get(jid)
            if worker is None or job['status'] not in ('queued', 'running'):
                raise RunBusy('This server does not own an active worker for this run')
            # Persist the request before acknowledgement by the worker.
            self.database().update(jid, status='cancelling')
            worker.cancel.set()
            return self.lookup(jid), 202
