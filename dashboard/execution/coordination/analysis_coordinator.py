"""Analysis task lifecycle owned separately from simulation coordination."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import threading
import uuid
from pathlib import Path

from dashboard import files, paths
from dashboard.analysis import worker as analysis

from ...analysis.runs import observability, refinement, surfaces
from ...analysis.validation import geometry as carbohydrate_geometry
from ...analysis.validation import osmotic as osmotic_pressure
from ...analysis.validation import report as carbohydrate_validation
from ...analysis.validation import targets
from ...analysis.validation import transfer as transfer_free_energy
from ...models import sugars as carbohydrates
from .. import workflow
from ..environment import recorded_environment
from . import resources
from .errors import CapacityFull, InvalidRequest, RunBusy, RunNotFound


class AnalysisCoordinator:
    def __init__(self, owner):
        self.owner = owner

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
        if kind == 'snapshots' and payload.get('stage', '1_AA-reference') != '1_AA-reference':
            raise InvalidRequest('Only AA snapshots are supported')
        with owner.JOBS_LOCK:
            job = owner.lookup(jid)
            if job['status'] not in ('completed', 'failed', 'cancelled') or jid in owner.WORKERS:
                raise RunBusy('Analysis requires a stopped run')
            source_root = workflow.execution_root(owner.run_path(job))
            source_entries = analysis.source_entries(source_root, kind)
            fingerprint = [(relative, files.sha256(path)) for relative, path in source_entries.items()]
            code_files = (Path(analysis.__file__), Path(observability.__file__), Path(targets.__file__),
                          Path(refinement.__file__), Path(surfaces.__file__), Path(carbohydrates.__file__),
                          Path(carbohydrate_validation.__file__), Path(carbohydrate_geometry.__file__),
                          Path(transfer_free_energy.__file__), Path(osmotic_pressure.__file__))
            signature = hashlib.sha256(json.dumps(
                [kind, payload, fingerprint,
                 self.dependencies(job) if kind == 'refinement-score' else {},
                 [(path.name, files.sha256(path)) for path in code_files]],
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
            try:
                worker.run_dir = owner.run_path(job)
                worker.lease_file = owner.lease(owner.run_path(job) / '.worker.lock')
                attempt.mkdir(parents=True, exist_ok=False)
                environment = workflow.environment()
                command = [shutil.which('python', path=environment['PATH']) or sys.executable,
                           '-m', 'dashboard.analysis', str(attempt / 'request.json')]
                request = {'run': str(owner.run_path(job).resolve()), 'kind': task['kind'],
                           'payload': task['payload'], 'code_signature': task['signature'],
                           'dependencies': self.dependencies(job)}
                files.atomic_json(attempt / 'request.json', request)
                self.update(jid, aid, status='running', started_at=owner.now(), command=command,
                            environment=recorded_environment(),
                            log=task['directory'] + '/console.log')
                with (attempt / 'console.log').open('w') as output:
                    worker.execute(command, cwd=paths.PACKAGE_ROOT.parent, env=environment,
                                   stdout=output, stderr=subprocess.STDOUT)
                result = json.loads((attempt / 'result.json').read_text())
                outputs = [str((attempt / result.get('output_directory', 'output') / relative).relative_to(owner.run_path(job)))
                           for relative in result['outputs_sha256']]
                self.update(jid, aid, status='completed', ended_at=owner.now(), exit_code=0,
                            outputs=outputs, **result)
            except Exception as exc:
                self.update(jid, aid, status='cancelled' if isinstance(exc, workflow.Cancelled) else 'failed',
                            ended_at=owner.now(), error=str(exc), exit_code=getattr(exc, 'returncode', None))
            finally:
                try:
                    owner.artifact_index(owner.lookup(jid), refresh=True)
                finally:
                    if worker.lease_file:
                        worker.lease_file.close()
                    with owner.JOBS_LOCK:
                        owner.ANALYSIS_WORKERS.pop((jid, aid), None)
