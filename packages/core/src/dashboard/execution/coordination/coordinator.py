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

from ... import features
from ...analysis import kinds
from ...analysis.runs import observability
from ...analysis.runs import references as aa_references
from ...models import mappings
from ...models.mappings import context as mapping_context
from ...models.molecules import aa as aa_molecules
from ...web import views
from .. import devices, protocol, run_inputs, workflow
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


def generated_label(molecule, run_type, settings=None, profile='standard'):
    """`[molecule]-[AA|CG]-[length]ns-[YYYYMMDD]`: the label an unnamed run is given.

    The New run panel suggests the same string while its label field is untouched (`new-run.js`), so a caller
    that posts none gets what the form would have shown. Length is the total simulated time: the AA half's
    NVT + NPT + production, the CG half's equilibration + production. A composition run configures no
    duration, so its label carries no length segment rather than a false `0ns`.
    """
    name = re.sub(r'\s+', '-', str(molecule or '').strip()) or 'run'
    tag = 'AA' if run_type == 'aa_only' else 'CG'
    try:
        values = protocol.adapter_for(run_type or 'aa_cg').normalize_settings(settings, profile)
    except ValueError:
        # The run's own normalization refuses these settings a moment later; the label must not be the thing
        # that changes the refusal, so it is derived from what can be read and the length is left out.
        values = settings if isinstance(settings, dict) else {}
    total = simulated_nanoseconds(run_type, values)
    tail = '-'.join([tag] + ([f'{total:g}ns'] if total is not None else [])
                    + [datetime.now().strftime('%Y%m%d')])
    # The cap trims the molecule's name, never the tail: a cut date or run-type tag would stop naming the run.
    return f'{name[:max(1, 160 - len(tail) - 1)]}-{tail}'


def simulated_nanoseconds(run_type, settings):
    """The total simulated length a run's settings state, in ns rounded to 0.1; `None` when they state none."""
    keys = (('aa_nvt_ps', 'aa_npt_ps', 'aa_production_ps') if run_type == 'aa_only'
            else ('cg_equil_ps', 'cg_production_ps'))
    try:
        ps = sum(float(settings[key]) for key in keys)
    except (KeyError, TypeError, ValueError):
        return None
    return round(ps / 1000, 1) if ps > 0 else None


def preset_record(value):
    """The `settings_preset` provenance a queue payload may carry, or `None`.

    It is metadata, not a setting: the run records which named preset its form started from, so where its
    numbers came from is readable later. Anything that is not an id/name pair is no record rather than an
    error -- a preset deleted between opening the form and starting the run must not cost the run.
    """
    if not isinstance(value, dict):
        return None
    preset_id, name = value.get('id'), value.get('name')
    if not isinstance(preset_id, str) or not preset_id.strip():
        return None
    caption = name.strip()[:120] if isinstance(name, str) and name.strip() else preset_id.strip()[:64]
    return {'id': preset_id.strip()[:64], 'name': caption}


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
        """Queue an in-place restart from a stage boundary on the existing job and run directory."""
        def prepare(path, analyses):
            if stage not in workflow.resumable_stages(path):
                raise RunConflict('Cannot resume that stage; choose a completed-stage boundary')
            return workflow.prepare_resume_in_place(path, stage, analyses=analyses, finalize=False)
        return self._queue_in_place(jid, ('failed', 'cancelled', 'completed'), prepare)


    def continue_in_place(self, jid):
        """Queue continuing the stopped stage from its checkpoint, keeping its directory and files."""
        def prepare(path, analyses):
            return workflow.prepare_continue_in_place(path, analyses=analyses)
        return self._queue_in_place(jid, ('failed', 'cancelled'), prepare)


    def _queue_in_place(self, jid, statuses, prepare):
        """The one in-place queue path: admission, lease, preparation, then the worker.

        Resume and Continue differ in which statuses they accept and what preparing the run writes; every check
        that admits them -- another worker, an active analysis, a retained consumer, capacity, the quota and the
        filesystem -- is this code, so the two cannot drift apart in what they refuse.
        """
        with self.JOBS_LOCK:
            job = self.lookup(jid)
            if job.get('status') not in statuses or jid in self.WORKERS:
                raise RunBusy('Run must be stopped before it can be resumed')
            if any(key[0] == jid for key in list(self.ANALYSIS_WORKERS)) or any(
                    task.get('status') in ('queued', 'running', 'cancelling') for task in job.get('analyses', [])):
                raise RunBusy('Active analyses must finish before the run can be resumed')
            if self.externally_busy(job):
                raise RunBusy('An external worker still holds this run')
            if any(other.get('reference_run_id') == jid or other.get('resume_of') == jid
                   for other in self.database().all() if other.get('id') != jid):
                raise DependencyRetained('The run has retained consumers; resume the consumers or clone this run')
            self.admit_device(job)
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
                try:
                    prepared = prepare(path, job.get('analyses', []))
                except RunConflict:
                    raise
                except (OSError, ValueError, KeyError) as exc:
                    raise RunConflict(str(exc))
                try:
                    updated = self.database().update(jid, status='queued', stage='queued', started_at=None, ended_at=None,
                                              error=None, command=None, resume_count=prepared['resume_count'],
                                              resume_from=prepared.get('resume_from'), resume_requested_at=prepared.get('resume_requested_at'),
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


    @staticmethod
    def device_of(job):
        """The CUDA ordinal a run's own mdrun names; 0 when its settings name none (every adapter's default)."""
        settings = job.get('settings') if isinstance(job, dict) else None
        try:
            return int((settings if isinstance(settings, dict) else {}).get('mdrun_gpu', 0) or 0)
        except (TypeError, ValueError):
            return 0

    def busy_devices(self):
        """Which device each active run holds: this coordinator's workers, and another process's live leases.

        A worker whose row has gone (a test's stand-in, or a deleted run) is counted on device 0, which is what a
        run that names no device would use anyway: an unreadable claim must not read as a free GPU.
        """
        busy = {}
        for jid in list(self.WORKERS):
            busy.setdefault(self.device_of(self.database().get(jid) or {}), []).append(jid)
        for job in self.database().all():
            if self.externally_busy(job):
                busy.setdefault(self.device_of(job), []).append(job['id'])
        return busy

    def admit_device(self, job):
        """Refuse a run only while its own GPU is at `max_concurrent_runs`; a different GPU starts alongside.

        The device is the one the run's own settings name (`mdrun_gpu`), which is the device its mdrun will use.
        A host that reports no devices answers the same way -- every run names index 0 -- so its runs keep the old
        one-at-a-time behaviour. Callers hold `JOBS_LOCK`, so the look and the registration cannot interleave.
        """
        busy = self.busy_devices().get(self.device_of(job), [])
        if len(busy) >= self.limits()['max_concurrent_runs']:
            # A host with no GPU still answers as one device, but the refusal must not claim a GPU exists there.
            message = ('This GPU is busy. Either wait for the run to stop or choose a free GPU.'
                       if devices.present() else
                       'A simulation is already running on this host. Wait for it to stop before starting another.')
            raise CapacityFull(message)

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
                        'parameterization': job.get('parameterization'),
                        'molecule_snapshot': job.get('molecule_snapshot'), 'runs_root': self.RUNS,
                        'solute_root': (job.get('settings') or {}).get('solute_root'),
                        'project_root': str(self.ROOT)})
                prepare_metadata = features.prepare_for(job.get('run_type'))
                if not readiness['ready']:
                    raise ValueError('; '.join(readiness['blockers']))
                source_id = None if in_place else (job.get('resume_of') or job.get('reference_run_id'))
                source_lease = self.lease(self.RUNS/source_id/'.worker.lock') if source_id else None
                try:
                    if job.get('resume_of'):
                        workflow.prepare_resume(work, self.RUNS/job['resume_of'], job['resume_from'])
                    elif not in_place and prepare_metadata is not None:
                        # A feature's run type states the arguments its own adapter's `prepare` takes; the CG kwargs
                        # below describe a molecule and are not a shape every run type shares.
                        protocol.adapter_for(job.get('run_type')).prepare(work, prepare_metadata(job, self.ROOT))
                    elif not in_place:
                        # The same door the four branches above use. The run type's own prepare now owns the stage
                        # directory, the `inputs/` copy and the manifest, and applies its own settings dialect -- the
                        # coordinator used to filter the settings and assemble the arguments before calling into the
                        # orchestrator, which put a run type's vocabulary in the queue.
                        protocol.adapter_for(protocol.run_type_of(job)).prepare(work, {
                            'detergent': job.get('detergent'), 'profile': job.get('profile', 'standard'),
                            'settings': job.get('settings') or {},
                            'mapping_candidate': job.get('mapping_snapshot'),
                            'molecule_snapshot': job.get('molecule_snapshot'),
                            'molecule_root': self.ROOT / 'molecules',
                            'molecule_id': job.get('molecule_id') or job.get('detergent'),
                            'composition_id': job.get('composition_id'),
                            'parameterization': job.get('parameterization'),
                            'runs_root': self.RUNS,
                            **({'shared_reference': job['shared_reference'], 'reference_root': self.RUNS}
                               if job.get('shared_reference') else {})})
                finally:
                    if source_lease: source_lease.close()
                prepared = json.loads((work/'manifest.json').read_text())
                if job.get('molecule_snapshot'):
                    if aa_only:
                        # A prepared run that names its inputs by reference verifies the record; the legacy layout
                        # has the molecule copy the digest names.
                        if prepared.get('inputs') is not None:
                            run_inputs.verify_manifest(work, prepared)
                        else:
                            files.verify(workflow.stage_root(work)/'common/molecule', job['molecule_snapshot']['sha256'])
                    elif (job.get('run_type') == 'cg'
                          and (job.get('parameterization') or {}).get('kind', 'revision') == 'revision'
                          and not job.get('shared_reference')):
                        # Only a revision-kind CG run consumes an AA reference. A reference or composition run
                        # carries its own coordinates and topology.
                        raise ValueError('CG run is missing its shared AA reference')
                    prepared.update(molecule_id=job['molecule_id'], molecule_snapshot=job['molecule_snapshot'])
                if job.get('composition_id'):
                    prepared.update(composition_id=job['composition_id'])
                    if job.get('composition_snapshot_sha256'):
                        prepared['composition_snapshot_sha256'] = job['composition_snapshot_sha256']
                prepared.update(id=jid, status='running', started_at=self.now(),run_type=job.get('run_type','aa_cg'),workflow_version=job.get('workflow_version','aa-cg-v2'))
                if job.get('shared_reference'):prepared['settings']=job['settings']
                files.atomic_json(work/'manifest.json', prepared)
                def stage_changed(name, entry):
                    if worker.cancel.is_set():
                        raise workflow.Cancelled('Cancelled by user')
                    self.database().update(jid, stage=name, command=' '.join(entry['command']))
                workflow.run(work, log, execute=worker.execute, on_stage=stage_changed)
                # An AA-to-CG run used to be able to stop itself here after the fit ("fit only") and record the
                # topology it produced as a reusable bonded state. Fitting is the run type's own now (D1): the
                # run's fit is its stage 3 record -- `3_initial_CG/{final_itp}`, `*_ff_inter.itp` and
                # `bonded_fit.json` -- and nothing about the fit is a per-run choice, so neither the stop nor the
                # state write has a caller left.
                if aa_only:aa_references.verify(work,molecule_snapshot=job['molecule_snapshot'])
        except Exception as exc:
            # The lifecycle has already recorded the failure; the run log line is this site's own.
            if created:
                with log.open('a') as fp:
                    fp.write(f'\nRun failed: {exc}\n')


    def create_job(self, detergent, method, label='', retry_of=None, profile='standard', settings=None, reference_run_id=None, resume_of=None, resume_from=None, mapping_candidate=None, mapping_snapshot=None, temporary_validation=False, molecule_id=None, molecule_snapshot=None, run_type=None, composition_id=None, protein=None, template=None, settings_preset=None, parameterization=None):
        try:
            admission.validate_run_type({'run_type': run_type, 'composition_id': composition_id,
                                         'molecule_id': molecule_id, 'molecule_snapshot': molecule_snapshot,
                                         'reference_run_id': reference_run_id, 'mapping_candidate': mapping_candidate,
                                         'mapping_snapshot': mapping_snapshot,
                                         'method': method, 'parameterization': parameterization,
                                         **(settings or {})})
        except ValueError as exc:
            raise InvalidRequest(str(exc))
        # An unnamed run gets the panel's own suggestion, derived here so an API caller that posts no label is
        # not left with a run that has none. The settings are the ones the run will use, so the length is the
        # length the manifest will state.
        if not str(label or '').strip():
            label = generated_label(molecule_id or detergent, run_type, settings, profile)
        settings_preset = preset_record(settings_preset)
        if run_type=='aa_only':
            if molecule_snapshot and not resume_of:
                try:aa_molecules.verify_selection(self.ROOT/'molecules',molecule_snapshot)
                except (OSError,ValueError) as exc:raise RunConflict(str(exc))
            job=self.aa_job_record(molecule_id or detergent,label,settings,molecule_snapshot if resume_of else None,profile)
            job.update(retry_of=retry_of,resume_of=resume_of,resume_from=resume_from,settings_preset=settings_preset)
            return self.admit_jobs([job],job)
        # The CG run type's parameterization kind decides whether it consumes a shared AA reference. Only the
        # `revision` kind does: a published reference and a composition carry their own coordinates and topology.
        parameterization = dict(parameterization) if isinstance(parameterization, dict) else {}
        if run_type == 'cg':
            parameterization.setdefault('kind', 'revision')
            if parameterization['kind'] == 'revision':
                parameterization.setdefault('starting_coordinates', 'stored')
                mapping_candidate = (mapping_candidate or parameterization.get('mapping_candidate')
                                     or parameterization.get('mapping'))
                if not parameterization.get('mapping_candidate') and mapping_candidate:
                    parameterization['mapping_candidate'] = mapping_candidate
            if parameterization['kind'] == 'reference':
                # The entry is a choice of the sugar adapter, carried in settings where its readiness reads it.
                settings = {**(settings or {}),
                            'sugar_entry': parameterization.get('sugar_entry') or (settings or {}).get('sugar_entry', 'SUCR')}
            if parameterization['kind'] == 'composition' and not composition_id:
                composition_id = parameterization.get('composition_id')
        shared = run_type == 'cg' and parameterization.get('kind') == 'revision'
        # A composition's molecule is the saved CG model itself, not an `molecules/` folder: its `molecule_id` is the
        # composition record's id, and the composition adapter is what validates the binding. Reading it through the
        # atomistic catalogue would refuse a well-formed composition run as a missing molecule.
        composition_model = run_type == 'cg' and parameterization.get('kind') == 'composition'
        if shared and molecule_id is None:
            molecule_id = detergent
        if molecule_id is not None:
            try:
                aa_molecules.validate_id(molecule_id)
            except ValueError as exc: raise InvalidRequest(str(exc))
            if not composition_model:
                try:
                    selected = molecule_snapshot if resume_of and molecule_snapshot else aa_molecules.selection(self.ROOT/'molecules', molecule_id)
                    if molecule_snapshot and not resume_of and selected != molecule_snapshot:
                        raise ValueError('Molecule files changed; clone with a fresh selection instead')
                    molecule_snapshot = selected if not resume_of else molecule_snapshot
                except (OSError, ValueError) as exc: raise RunConflict(str(exc))
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
        # A run used to be able to name a fitted bonded state and reuse it instead of fitting (`bonded_state_id`
        # with `bonded_intent='reuse_state'`), which is what the three refusals here protected: the state had to
        # exist, had to belong to the selected mapping, and had to be complete. Fitting is a property of the run
        # type rather than a per-run choice (D1), so nothing can be handed to a run any more and there is nothing
        # left to refuse. `models/bonded` keeps the states and their own compatibility checks untouched: they are
        # still fitted, edited and compared in the Bonded workspace.
        adapter = protocol.adapter_for(run_type or 'aa_cg')
        if run_type == 'cg':
            settings = adapter.normalize_settings(settings, profile, parameterization=parameterization)
        else:
            settings = adapter.normalize_settings(settings, profile)
        tweak = features.create_settings_for(run_type or 'aa_cg')
        if tweak is not None:
            settings = tweak(settings, {'protein': protein, 'template': template,
                                        'mapping_snapshot': mapping_snapshot, 'settings': settings})
        reference_snapshot=None
        expected_reference=None
        if shared:
            # The AA reference is the revision's own, never a new AA parent job. The revision records the run it was
            # fitted against and that run's digests, and this verifies both: a revision pointing at a reference that
            # changed under it is refused here rather than three stages in.
            try:
                chosen = cg.chosen_revision(mapping_snapshot, parameterization.get('revision'))
            except KeyError as exc:
                raise InvalidRequest(str(exc)) from None
            recorded_reference = (chosen or {}).get('aa_reference') or {}
            if parameterization.get('revision') is None and chosen is not None:
                parameterization['revision'] = chosen['revision']
            if not recorded_reference.get('run_id'):
                raise SourceUnavailable('The chosen parameterization records no AA reference to reuse')
            reference_run_id = recorded_reference['run_id']
            expected_reference = recorded_reference.get('reference_sha256')
            try:
                _,reference_snapshot=aa_references.resolve(self.RUNS,reference_run_id,expected_reference,
                                                           molecule_snapshot=molecule_snapshot)
                if self.lookup(reference_run_id).get('status')!='completed':raise ValueError('AA source must be completed')
            except (OSError,ValueError) as exc:raise SourceUnavailable(str(exc))
        elif reference_run_id:
            raise SourceUnavailable('CG runs require a shared AA reference')
        question = features.readiness_for(run_type or 'aa_cg')
        if question is not None:
            # A feature's run type is checked by its own adapter: asking the CG adapter about a protein-detergent
            # build is how a pdc job used to be refused.
            ready = question({'protein': protein, 'template': template, 'molecule_id': molecule_id or detergent,
                              'method': method, 'profile': profile, 'mapping_snapshot': mapping_snapshot,
                              'settings': settings or {}, 'molecule_root': self.ROOT / 'molecules',
                              'solute_root': (settings or {}).get('solute_root')}, self.ROOT)
        else:
            ready = adapter.readiness({'molecule_id': molecule_id or detergent, 'method': method,
                                       'profile': profile, 'mapping_candidate': mapping_snapshot,
                                       'molecule_snapshot': molecule_snapshot,
                                       'molecule_root': self.ROOT / 'molecules', 'runs_root': self.RUNS,
                                       'composition_id': composition_id, 'settings': settings or {},
                                       'parameterization': parameterization})
        if not ready['ready']:
            raise RunConflict('; '.join(ready['blockers']))
        job = {'id': uuid.uuid4().hex[:12], 'detergent': detergent, 'method': method, 'label': str(label)[:160],
               'status': 'queued', 'stage': 'queued', 'created': self.now(), 'retry_of': retry_of, 'profile': profile, 'settings': settings, 'reference_run_id': reference_run_id, 'scientifically_validated': False, 'temporary_validation': bool(temporary_validation),
               'settings_preset': settings_preset}
        # What the run will fit is the mapping it was given; no bonded state and no intent ride on the record any
        # more (D1). A run that finds one in an old payload simply ignores it, which is where the retired pair of
        # controls now leads.
        # The run type has to be on the record before the worker starts: everything downstream -- readiness, the
        # stage plan, which adapter writes the run -- is chosen by it, and a job that only carries a method is read
        # as a CG run by the adapter that answers about methods.
        job['run_type'] = run_type or 'aa_cg'
        if run_type == 'cg':
            job['parameterization'] = parameterization
        if protein is not None:
            job['protein'] = protein
        if template is not None:
            job['template'] = template
        if mapping_snapshot is not None:
            job.update(mapping_candidate=mapping_snapshot.get('file'), mapping_snapshot=mapping_snapshot)
        if molecule_snapshot is not None:
            job.update(molecule_id=molecule_snapshot['id'], molecule_snapshot=molecule_snapshot)
        elif composition_model and molecule_id is not None:
            # A composition's molecule is its own record, so there is no snapshot to store beside it; the id is kept
            # so a retry, a clone and the run's own reader name the same model.
            job['molecule_id'] = molecule_id
        job.update(layout_version=2, resume_of=resume_of, resume_from=resume_from)
        # The stage plan and the workflow version belong to the run's own type. Stamping every job that reaches here
        # as a CG run is why a protein-detergent job was answered by the CG adapter's readiness check -- which knows
        # only the methods it fits -- and refused as "not connected to an executable workflow".
        if job['run_type'] == 'cg':
            job.update(workflow_version=f"cg-{parameterization.get('kind', 'revision')}-v1",
                       stage_plan=[stage.name for stage in adapter.stages({'parameterization': parameterization})])
        else:
            job.update(workflow_version=f"{job['run_type']}-v1",
                       stage_plan=[stage.name for stage in protocol.adapter_for(job['run_type']).stages({})])
        if shared:
            # A CG run reuses a published AA reference; it never creates one, so there is no waiting job and no AA
            # parent to admit. The reference was resolved and verified above.
            job['shared_reference']={'source_run_id':reference_run_id,'sha256':reference_snapshot['sha256']}
            return self.admit_jobs([job],job)
        worker = self.Worker()
        with self.JOBS_LOCK:
            self.admit_device(job)
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
                'layout_version':2,'scientifically_validated':False,'reference_eligible':False,'settings_preset':None}


    def admit_jobs(self, records,first,result=None):
        with self.JOBS_LOCK:
            self.admit_device(first)
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
                try:
                    self.admit_device(job)
                except CapacityFull:
                    continue
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


    def automatic_analyses(self, jid):
        """The kinds a run queues for itself when it stops: the universal ones, then its run type's own.

        The automatic kinds are a facet of the kind table rather than a list kept here -- `kinds.for_every_run()`
        is the kind that runs for any run, and `kinds.default_for(run_type)` is the run type's own, which is where
        an AA-to-CG run's `dihedral-fit` and `bonded-cross-check` come from (D5): they read stages 2 and 3 only, so
        they are available the moment the fit is. A run type with no defaults of its own is not a special case --
        the second list is empty and the answer is the first.

        A record that names no run type gets the universal kinds and nothing else: this run type's defaults are not
        every run's, and a record that cannot say what it is does not get to claim them.
        """
        job = self.lookup(jid)
        run_type = job.get('run_type')
        return list(kinds.for_every_run()) + (list(kinds.default_for(run_type)) if run_type else [])





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
