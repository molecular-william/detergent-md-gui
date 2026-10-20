"""Analysis task lifecycle owned separately from simulation coordination."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from dashboard import files, paths
from dashboard.analysis import worker as analysis

#: The packages whose content decides an analysis result: the analysis code itself and the model code it reads.
CODE_ROOTS = ('analysis', 'models')


def code_fingerprint_files():
    """`(relative name, path)` for every file that decides an analysis result, in a stable order.

    A hand-written list of module files stood here and had quietly fallen behind: `bonded_terms`, `consistency`,
    `mapping_consistency`, `layout` and `sugar_ensemble` were not in it, so fixing the overlap metric changed no
    signature at all — re-queuing the same analysis returned the completed task, and the panel went on showing
    numbers the code on disk would no longer produce. This walks the packages instead, so the list cannot drift
    from the code it describes, and names each file relative to `dashboard/` because two modules can share a
    basename.
    """
    root = Path(analysis.__file__).resolve().parent.parent
    return [(str(path.relative_to(root)), path)
            for package in CODE_ROOTS
            for path in sorted((root / package).rglob('*.py'))]

from .. import workflow
from ..environment import recorded_environment
from . import resources
from .attempt import attempt as managed_attempt
from .errors import CapacityFull, InvalidRequest, RunBusy, RunNotFound


class AnalysisCoordinator:
    def __init__(self, owner):
        self.owner = owner
        workflow.on_run_completed(self.run_completed)

    def run_completed(self, run_dir):
        """A run's stages have finished: queue the kinds it runs for itself, without anyone asking.

        The notification arrives from the run's own worker thread, which is still holding the run while the
        coordinator's `finish_job` writes the terminal status and releases its lease -- and `queue` refuses a run
        that is still held, on purpose, for a request that arrives from outside. So the queueing is handed to a
        short-lived thread that waits for the run to be free and then goes through that same door: no guard is
        weakened for it, and a run whose worker never lets go simply gets no frames, which is where it started.

        A notification naming a run of another store is not this coordinator's business -- the coordinator that owns
        it was notified too -- and is answered with nothing rather than an error.
        """
        run_dir = Path(run_dir)
        if run_dir.resolve().parent != Path(self.owner.RUNS).resolve():
            return []
        threading.Thread(target=self.queue_run_analyses_when_free, args=(run_dir.name,), daemon=True).start()
        return []

    def queue_run_analyses_when_free(self, jid, timeout=30.0):
        """Queue a finished run's own analyses, once the run's worker has let go of it."""
        deadline = time.monotonic() + timeout
        while True:
            job = self.owner.database().get(jid)
            if job is None:
                return []
            with self.owner.JOBS_LOCK:
                held = jid in self.owner.WORKERS
            if not held and job.get('status') in ('completed', 'failed', 'cancelled') and not self.owner.externally_busy(job):
                return self.queue_defaults(jid)
            if time.monotonic() >= deadline:
                return []
            time.sleep(.05)

    def queue_defaults(self, jid):
        """Queue every kind a run runs for itself.

        Best-effort on purpose: this is the run's own bookkeeping rather than a request someone is waiting on, so a
        queue that is busy (a person's analysis is already running) or full leaves the run exactly as it was, and so
        does a run whose sources the kind cannot be resolved from at all -- a consumer whose reference run is gone,
        or a record that names no layout this kind reads. Nothing is invented for those: a person asking for the
        kind by name still gets the resolver's own refusal, which names every path it looked for.
        """
        queued = []
        # `automatic_analyses` is the one place the two facets of the kind table are read together -- the kinds every
        # run owes its reader, and the run type's own -- so the queueing path asks it rather than restating half of
        # it. Restating it is how `dihedral-fit` and `bonded-cross-check` came to be declared for AA-to-CG runs and
        # queued by nobody.
        for kind in self.owner.automatic_analyses(jid):
            try:
                task, _ = self.queue(jid, kind, {})
            except (CapacityFull, RunBusy, RunNotFound, OSError, ValueError):
                continue
            queued.append(task['id'])
        return queued

    def dependencies(self, job):
        result = {}
        for task in job.get('analyses', []):
            if task.get('status') != 'completed':
                continue
            for relative in task.get('outputs', []):
                name = Path(relative).name
                if name in ('numerical_stability.json', 'experimental_targets.json'):
                    result[name] = relative
        return result

    def update(self, jid, aid, **fields):
        owner = self.owner
        with owner.JOBS_LOCK:
            tasks = owner.lookup(jid).get('analyses', [])
            task = next(task for task in tasks if task['id'] == aid)
            task.update(fields)
            owner.database().update(jid, analyses=tasks)
            attempt = owner.run_path(owner.lookup(jid)) / task['directory']
            if attempt.is_dir():
                files.atomic_json(attempt / 'manifest.json', task)
            return task

    def cancel(self, jid, aid):
        owner = self.owner
        with owner.JOBS_LOCK:
            worker = owner.ANALYSIS_WORKERS.get((jid, aid))
            if worker is None:
                raise RunBusy('Analysis has no owned active worker')
            task = self.update(jid, aid, status='cancelling')
            worker.cancel.set()
        return task

    def queue(self, jid, kind, payload):
        owner = self.owner
        if kind not in analysis.KINDS:
            raise RunNotFound('Unknown analysis')
        if not isinstance(payload, dict):
            raise InvalidRequest('Expected an object')
        with owner.JOBS_LOCK:
            job = owner.lookup(jid)
            if job['status'] not in ('completed', 'failed', 'cancelled') or jid in owner.WORKERS:
                raise RunBusy('Analysis requires a stopped run')
            source_root = workflow.execution_root(owner.run_path(job))
            source_entries = analysis.source_entries(source_root, kind)
            fingerprint = [(relative, files.sha256(path)) for relative, path in source_entries.items()]
            code_files = code_fingerprint_files()
            signature = hashlib.sha256(json.dumps(
                [kind, payload, fingerprint,
                 self.dependencies(job) if kind == 'refinement-score' else {},
                 [(name, files.sha256(path)) for name, path in code_files]],
                sort_keys=True).encode()).hexdigest()
            tasks = job.get('analyses', [])
            for task in reversed(tasks):
                if task.get('signature') == signature and task['status'] in ('queued', 'running', 'completed'):
                    return task, 200 if task['status'] == 'completed' else 202
            if any(key[0] == jid for key in list(owner.ANALYSIS_WORKERS)):
                raise RunBusy('An analysis is already active for this run')
            if len(owner.ANALYSIS_WORKERS) + sum(owner.externally_busy(item) for item in owner.database().all()) >= owner.limits()['max_concurrent_analyses']:
                raise CapacityFull('Analysis capacity is busy')
            with owner.lease(owner.run_path(job) / '.worker.lock'):
                pass
            copied_bytes = sum(path.stat().st_size for path in source_entries.values())
            if resources.usage(owner.run_path(job)) + copied_bytes > owner.limits()['max_run_bytes']:
                raise CapacityFull('Analysis workspace exceeds the per-run storage limit')
            resources.admit(owner.storage_report(), len(owner.WORKERS) + len(owner.ANALYSIS_WORKERS), copied_bytes)
            aid = uuid.uuid4().hex[:12]
            task = {'id': aid, 'kind': kind, 'signature': signature, 'payload': payload,
                    'status': 'queued', 'created_at': owner.now(),
                    'directory': f'analyses/{kind}/{signature}/{aid}'}
            tasks.append(task)
            owner.database().update(jid, analyses=tasks)
            worker = owner.Worker()
            owner.ANALYSIS_WORKERS[(jid, aid)] = worker
            threading.Thread(target=self.run, args=(jid, aid, worker), daemon=True).start()
        return task, 202

    def run(self, jid, aid, worker):
        owner = self.owner
        with owner.app.app_context():
            job = owner.lookup(jid)
            task = next(task for task in job['analyses'] if task['id'] == aid)
            attempt = owner.run_path(job) / task['directory']
            extras = {}

            def write(_record, **fields):
                """How this site writes: straight onto the analysis record.

                The values the success transition carries -- exit code, outputs and the analysis
                result -- are computed by the body, so it leaves them in `extras` for this to merge.
                `ended_at` belongs to every terminal status, as it always did.
                """
                if fields.get('status') in ('completed', 'failed', 'cancelled', 'skipped'):
                    fields.setdefault('ended_at', owner.now())
                self.update(jid, aid, **fields, **extras)

            def finish(_record):
                try:
                    owner.artifact_index(owner.lookup(jid), refresh=True)
                finally:
                    if worker.lease_file:
                        worker.lease_file.close()
                    with owner.JOBS_LOCK:
                        owner.ANALYSIS_WORKERS.pop((jid, aid), None)

            worker.run_dir = owner.run_path(job)
            worker.lease_file = owner.lease(owner.run_path(job) / '.worker.lock')
            environment = workflow.environment()
            command = [shutil.which('python', path=environment['PATH']) or sys.executable,
                        '-m', 'dashboard.analysis', str(attempt / 'request.json')]
            request = {'run': str(owner.run_path(job).resolve()), 'kind': task['kind'],
                        'payload': task['payload'], 'code_signature': task['signature'],
                        'dependencies': self.dependencies(job)}
            # The attempt directory and the request file are prepared inside the managed region, so a
            # failure there is recorded as a failure of this attempt rather than escaping unrecorded.
            # That moves the running write ahead of the preparation; the terminal state is unchanged.
            try:
                with managed_attempt(None, update=write,
                                     running={'started_at': owner.now(), 'command': command,
                                              'environment': recorded_environment(),
                                              'log': task['directory'] + '/console.log'},
                                     on_exit=finish):
                    attempt.mkdir(parents=True, exist_ok=False)
                    files.atomic_json(attempt / 'request.json', request)
                    with (attempt / 'console.log').open('w') as output:
                        try:
                            worker.execute(command, cwd=paths.PACKAGE_ROOT.parent, env=environment,
                                           stdout=output, stderr=subprocess.STDOUT)
                        except subprocess.CalledProcessError as failure:
                            if failure.returncode != workflow.SKIPPED_EXIT_CODE:
                                raise
                            # The kind had nothing to do. The contract is the stage contract: exit 4 with the
                            # reason in `skip.json` beside the request, and the producer's own words are the
                            # message. `attempt` records `skipped` from it and does not re-raise, so nothing here
                            # fails -- neither this attempt nor the run it belongs to.
                            raise workflow.Skipped(workflow.skip_reason(attempt, task['kind'])) from None
                    result = json.loads((attempt / 'result.json').read_text())
                    outputs = [str((attempt / result.get('output_directory', 'output') / relative).relative_to(owner.run_path(job)))
                               for relative in result['outputs_sha256']]
                    extras.update(exit_code=0, outputs=outputs, **result)
            except Exception:
                # managed_attempt re-raises so its caller can decide what happens next. This caller is
                # a worker thread whose record already carries the failure; letting it escape would
                # only print a traceback from a thread nobody is watching, which is not what this
                # site did before and not what it should start doing.
                pass
