"""Analysis task lifecycle owned separately from simulation coordination."""
from __future__ import annotations

import functools
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from dashboard import files, paths
from dashboard.analysis import kinds
from dashboard.analysis import worker as analysis
from dashboard.analysis.runs import figures, layout

#: What a checkout answers when neither the deployment nor `git describe` can name its code.
UNKNOWN_CODE_VERSION = 'unknown'


def _describe_code():
    """What this checkout's code is, in the deployment's own words or in git's."""
    configured = os.environ.get('DASHBOARD_CODE_VERSION', '').strip()
    if configured:
        return configured
    try:
        described = subprocess.run(('git', 'describe', '--always', '--dirty'), cwd=paths.PROJECT_ROOT,
                                   capture_output=True, text=True, timeout=10, check=True)
    except (OSError, subprocess.SubprocessError):
        return UNKNOWN_CODE_VERSION
    return described.stdout.strip() or UNKNOWN_CODE_VERSION


@functools.lru_cache(maxsize=1)
def code_version():
    """The string that says which code an attempt was built by, cached for the life of the process.

    A source's bytes no longer decide anything, so a change to the analysis *code* is stated by the deployment that
    ships it rather than by walking every module file and hashing it. `DASHBOARD_CODE_VERSION` is that statement; a
    checkout that sets none answers with `git describe --always --dirty`, and a copy with no git answers
    `UNKNOWN_CODE_VERSION`. Cached because reading git per queued analysis would run a subprocess for a fact about
    the checkout that cannot change under a running dashboard.
    """
    return _describe_code()


def identity(kind, payload, sources, run, dependencies=None):
    """What makes two analysis requests one attempt: its kind, payload, source names, run name and the code version.

    No bytes are read and no digest is written. `sources` contributes its keys -- the names a kind resolves its files
    by -- so a file replaced in place is the same input to the same analysis while a source that moves is a new one.
    `run` is the run's own name, so an attempt is never reused by a copy of its run. `dependencies` names the files
    a kind re-reads from another analysis, and their names change when that analysis publishes a newer set, so a
    refinement-score re-runs against a newer diagnostic without hashing it.
    """
    return files.canonical_json({
        'kind': kind, 'payload': payload, 'run': str(run),
        'sources': sorted(str(name) for name in sources),
        'dependencies': sorted(f'{name} {path}' for name, path in (dependencies or {}).items()),
        'code': code_version(),
    })


def next_attempt(root, kind, tasks):
    """`analyses/<kind>/<NNNN>-<YYYYMMDD>` for this run's next attempt of `kind`.

    NNNN is monotonic per run and kind and is never reused: the records and the directories on disk are both read, so
    a number is not minted over an attempt whose record was dropped. A legacy `<signature>` tree holds no number and
    leaves the count at zero. Callers hold `JOBS_LOCK`, so two queued attempts of one run cannot race for the number.
    """
    last = 0
    for task in tasks:
        if task.get('kind') == kind:
            match = figures.SEQUENCE.fullmatch(Path(str(task.get('directory') or '')).name)
            if match:
                last = max(last, int(match.group(1)))
    directory = Path(root) / 'analyses' / kind
    if directory.is_dir():
        for path in directory.iterdir():
            match = figures.SEQUENCE.fullmatch(path.name)
            if match:
                last = max(last, int(match.group(1)))
    # UTC, like every other timestamp the records carry: the date is part of a directory name, so two machines
    # reading one workspace must not disagree about which day an attempt belongs to.
    day = time.strftime('%Y%m%d', time.gmtime())
    return f'analyses/{kind}/{last + 1:04d}-{day}'

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
        weakened for it, and a run whose worker never lets go simply gets none of its own analyses, which is where
        it started.

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
        return self.drain(jid, automatic=True)['queued']

    def drain(self, jid, automatic=False):
        """Queue the owed kinds the run does not already hold, and say which are still waiting.

        `automatic` marks the completion/chain path rather than a person's Recompute. Automatic queueing must not
        replace a manual payload with the kind's default one: a hand-chosen payload has a different identity, so an
        identity-only queue would mint a second attempt beside it and the newer one would win. An automatic pass
        therefore treats any completed or skipped task of the kind as current. A person's Recompute still goes
        through the identity check, so a moved source, an edited payload or a changed code version can be re-run on
        request.
        

        `queue` takes one analysis at a time for a run: it refuses a second with `RunBusy` while the first holds the
        worker, which is what keeps a person's cancel meaningful. Asking for the whole list at once therefore queued
        exactly one kind and silently dropped the rest -- an `aa_cg` run owing `bonded-cross-check` and
        `dihedral-fit` queued the first and never reached the second, and `HANDOFF` recorded the other as "queued by
        nobody" when it was queued and immediately refused.

        So draining stops at the first refusal and is called again when an analysis finishes, which is how the list
        is worked through with nobody pressing anything. `owed` is what a person is told about: the kinds this pass
        could not start, either because one is already active or because the queue is full.
        """
        queued, owed = [], []
        # `automatic_analyses` is the one place the two facets of the kind table are read together -- the kinds every
        # run owes its reader, and the run type's own -- so the queueing path asks it rather than restating half of
        # it. Restating it is how `dihedral-fit` and `bonded-cross-check` came to be declared for AA-to-CG runs and
        # queued by nobody.
        for kind in self.owner.automatic_analyses(jid):
            try:
                task, status = self.queue(jid, kind, {}, automatic=automatic)
            except RunBusy:
                # One is active. The rest follow when it finishes, from `finish` below.
                owed.append(kind)
                owed.extend(self._rest_owed(jid, kind))
                break
            except (CapacityFull, RunNotFound, OSError, ValueError):
                owed.append(kind)
                continue
            # 200 means this exact analysis is already here, computed from these sources by this code: nothing was
            # queued and nothing is owed. That is what makes pressing recompute twice cheap and honest.
            if status == 202:
                queued.append(task['id'])
        return {'queued': queued, 'owed': owed}

    def _rest_owed(self, jid, after):
        """The kinds listed after `after`, so a refusal reports the whole remainder rather than one name."""
        kinds = list(self.owner.automatic_analyses(jid))
        return kinds[kinds.index(after) + 1:] if after in kinds else []

    def chain(self, jid, aid):
        """Start the run's next owed kind after a settled attempt, and nothing after a failed or cancelled one.

        A failure leaves the kind not-current by identity, so draining from here would queue it again in the same
        breath and a run whose producer cannot succeed would spin. A failed attempt waits for a person: the panel's
        recompute asks for it, and `drain` offers it again.
        """
        settled = next((task['status'] for task in self.owner.lookup(jid).get('analyses', [])
                        if task['id'] == aid), None)
        if settled in ('completed', 'skipped'):
            return self.drain(jid, automatic=True)
        return {'queued': [], 'owed': []}


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

    def queue(self, jid, kind, payload, *, automatic=False):
        owner = self.owner
        if not kinds.known(kind):
            raise RunNotFound('Unknown analysis')
        if not isinstance(payload, dict):
            raise InvalidRequest('Expected an object')
        with owner.JOBS_LOCK:
            job = owner.lookup(jid)
            if job['status'] not in ('completed', 'failed', 'cancelled') or jid in owner.WORKERS:
                raise RunBusy('Analysis requires a stopped run')
            source_root = layout.stage_root(owner.run_path(job))
            source_entries = analysis.source_entries(source_root, kind, payload)
            # The identity is the names this kind resolves its files by, its payload and the code version -- no
            # digest of a source or of the code. A file replaced in place is the same input; a moved source, an edited
            # payload or a different deployment is a new one.
            wanted = identity(kind, payload, source_entries, job['id'],
                              self.dependencies(job) if kind == 'refinement-score' else {})
            tasks = job.get('analyses', [])
            stable = analysis.TABLE[kind].stable_directory
            record = None
            if stable is not None:
                # One record per run for this kind: a build replaces the published series and reuses this record, so
                # the analyses list holds the current build rather than one row -- and one directory -- per request.
                # Attempt records written before the kind became stable are left alone; the panel falls back to them.
                record = next((task for task in reversed(tasks)
                               if task.get('kind') == kind and task.get('stable')), None)
                if record is not None and record['status'] in ('queued', 'running'):
                    return record, 202
                if record is not None and record.get('identity') == wanted \
                        and record['status'] in ('completed', 'skipped'):
                    # The same arguments over the same sources are the same series: nothing is rebuilt.
                    return record, 200
            else:
                for task in reversed(tasks):
                    if automatic and task.get('kind') == kind and task['status'] in ('queued', 'running', 'completed',
                                                                                     'skipped'):
                        return task, 200 if task['status'] in ('completed', 'skipped') else 202
                    if task.get('identity') == wanted and task['status'] in ('queued', 'running', 'completed',
                                                                             'skipped'):
                        # A skip is an answer, not an absence: the same sources and code will skip again. Reusing it
                        # is what stops a run whose producer cannot succeed from re-queueing itself every twenty
                        # seconds forever. A moved source, an edited payload or a changed code version is a new
                        # identity, so a later attempt is still allowed; a person's Recompute asks through the same
                        # door and gets the same answer while nothing has changed.
                        return task, 200 if task['status'] in ('completed', 'skipped') else 202
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
            if stable is not None:
                if record is None:
                    record = {'id': uuid.uuid4().hex[:12], 'kind': kind, 'stable': True}
                    tasks.append(record)
                # The previous build's `outputs` stay on the record: a rebuild that fails before publishing leaves the
                # old series on disk, and the panel can still play it while the record says what went wrong.
                record.update(identity=wanted, payload=payload, status='queued', created_at=owner.now(),
                              directory=stable)
                record.pop('error', None)
                record.pop('ended_at', None)
                task = record
            else:
                aid = uuid.uuid4().hex[:12]
                task = {'id': aid, 'kind': kind, 'identity': wanted, 'payload': payload,
                        'status': 'queued', 'created_at': owner.now(),
                        'directory': next_attempt(owner.run_path(job), kind, tasks)}
                tasks.append(task)
            aid = task['id']
            owner.database().update(jid, analyses=tasks)
            worker = owner.Worker()
            owner.ANALYSIS_WORKERS[(jid, aid)] = worker
            threading.Thread(target=self.run, args=(jid, aid, worker), daemon=True).start()
        return task, 202

    #: How long a worker waits for the run's own lock before the record says the run was held. A finished run's
    #: analyses are queued as its worker lets go, and `externally_busy` takes that same lock for microseconds while
    #: it probes: a single attempt is a race this worker loses once and then never recovers from.
    CLAIM_SECONDS = 5.0

    def _claim(self, owner, path):
        """The run's lock, waiting out a transient holder rather than dying on it."""
        deadline = time.monotonic() + self.CLAIM_SECONDS
        while True:
            try:
                return owner.lease(path)
            except ValueError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.05)

    def run(self, jid, aid, worker):
        owner = self.owner
        with owner.app.app_context():
            job = owner.lookup(jid)
            task = next(task for task in job['analyses'] if task['id'] == aid)
            attempt = owner.run_path(job) / task['directory']
            stable = analysis.TABLE[task['kind']].stable_directory is not None
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
                    # One analysis per run at a time, so the run's next owed kind starts here rather than at queueing
                    # time, where the second ask would be refused.
                    try:
                        self.chain(jid, aid)
                    except Exception:
                        pass

            worker.run_dir = owner.run_path(job)
            request = {'run': str(owner.run_path(job).resolve()), 'kind': task['kind'],
                        'payload': task['payload'], 'dependencies': self.dependencies(job)}
            # Everything that can fail is inside the managed region, the run's own lock included. A claim lost while
            # the run's worker was letting go killed this thread before its record was written (run 0c5f5738089c):
            # the attempt stayed `queued`/`cancelling`, its slot was never given back, and every later analysis of
            # that run answered "already active" until the dashboard restarted. So the claim waits, and a refusal is
            # recorded like any other failure of this attempt.
            try:
                with managed_attempt(None, update=write,
                                     running={'started_at': owner.now(),
                                              'environment': recorded_environment(),
                                              'log': task['directory'] + '/console.log'},
                                     on_exit=finish):
                    worker.lease_file = self._claim(owner, owner.run_path(job) / '.worker.lock')
                    environment = workflow.environment()
                    command = [shutil.which('python', path=environment['PATH']) or sys.executable,
                               '-m', 'dashboard.analysis', str(attempt / 'request.json')]
                    write(None, command=command)
                    attempt.mkdir(parents=True, exist_ok=stable)
                    files.atomic_json(attempt / 'request.json', request)
                    with (attempt / 'console.log').open('w') as output:
                        try:
                            worker.execute(command, cwd=paths.current().project_root, env=environment,
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
