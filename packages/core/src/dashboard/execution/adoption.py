"""Register a run directory that arrived without its job row.

A run is two things -- `runs/<id>/` and the row that lists it -- and the dashboard reads the row: the Runs list pages
the store, and every panel resolves a run through `Coordinator.lookup`. `cli.import_run` moves both together when the
sender's workspace is at hand. This is the other half of that transfer: a directory copied in by hand (`cp -r`, a zip,
a colleague's checkout) has its manifest but no row, and this module builds the row from what the directory already
records.

The directory is authoritative for its own provenance; only the display fields the manifest never wrote (`label`,
`created`, `method`, `profile`) are derived, and an adopted record is marked `adopted_at` so it is never mistaken for
a row this workspace created. The copy is verified against this checkout before the row lands: `run_inputs` for the
shared inputs, and -- for a completed AA-only run -- `references.verify` for technical reference eligibility. A
reference source that is not on this machine is a warning (the run's own artifacts are still hashed run-relative); a
source that is present and changed refuses the adoption.

The receiving workspace needs the same tracked inputs the run was prepared from (`molecules/`, the force-field
templates, config). A directory whose inputs do not verify is refused by name rather than registered half-readable.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .. import paths
from ..store import Store
from . import run_inputs
from .coordination import errors

RUN_ID = re.compile(r'[a-f0-9]{12}')
#: A pasted run is a finished one. A directory whose manifest says it is still running cannot be adopted: no worker
#: owns it, so registering it would show a live run this server cannot stop.
TERMINAL = ('completed', 'failed', 'cancelled', 'blocked')
#: Analysis attempts the run's own directories record, and the statuses an adopted task may keep. An attempt that
#: stopped in one of the others was interrupted; the same sentence `reconcile` uses is written for it.
ANALYSIS_TERMINAL = ('completed', 'failed', 'skipped', 'cancelled')
ANALYSIS_INTERRUPTED = 'Dashboard restarted during analysis; retry creates a new attempt.'


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _analyses(run):
    """The run's own analysis attempts, from the manifest each attempt directory carries.

    The task list is part of the job row, and a directory-only copy would otherwise show the Run view's analysis
    checklist as empty. Each `analyses/<kind>/<signature>/<id>/manifest.json` is the task record the coordinator
    wrote; a task that was left queued/running by the sender is adopted as failed, because no worker here owns it.
    """
    tasks = {}
    for manifest in sorted((run / 'analyses').glob('*/*/*/manifest.json')):
        try:
            task = json.loads(manifest.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(task, dict) or not task.get('id') or not task.get('kind'):
            continue
        if task.get('status') not in ANALYSIS_TERMINAL:
            task = dict(task, status='failed', error=ANALYSIS_INTERRUPTED, ended_at=task.get('ended_at') or _now())
        tasks.setdefault(task['id'], task)
    return sorted(tasks.values(), key=lambda task: task.get('created_at') or '')


def _record(run, manifest):
    """The job row a manifest can rebuild, with every field this workspace can prove."""
    run_id = run.name
    status = manifest.get('status')
    if status not in TERMINAL:
        raise ValueError(f'run {run_id} is {status!r} in its manifest; only a stopped run can be adopted')
    if manifest.get('id') not in (None, run_id):
        raise ValueError(f'run {run_id} names a different id in its manifest: {manifest.get("id")!r}')
    molecule = manifest.get('molecule_id')
    created = (manifest.get('created') or manifest.get('started_at')
               or manifest.get('prepared_at') or manifest.get('ended_at') or _now())
    job = {
        'id': run_id,
        'run_type': manifest.get('run_type'),
        'status': status,
        'stage': 'complete' if status == 'completed' else None,
        'layout_version': manifest.get('layout_version') or 2,
        'molecule_id': molecule,
        'molecule_snapshot': manifest.get('molecule_snapshot'),
        'settings': manifest.get('settings') or {},
        'workflow_version': manifest.get('workflow_version'),
        'stage_plan': manifest.get('stage_plan') or [],
        'label': manifest.get('label') or f'{molecule or manifest.get("run_type") or "run"} · imported',
        'created': created,
        'ended_at': manifest.get('ended_at'),
        'error': manifest.get('error'),
        'method': manifest.get('method'),
        'profile': manifest.get('profile'),
        'detergent': manifest.get('detergent') or molecule,
        'analyses': _analyses(run),
        'adopted_at': _now(),
        'reference_eligible': False,
    }
    for key in ('reference_run_id', 'shared_reference', 'parameterization', 'composition_id', 'protein', 'template'):
        if manifest.get(key) is not None:
            job[key] = manifest[key]
    return job


def _reference(run, job):
    """Whether this copy may be offered as an AA reference here, and the provenance it could not re-check."""
    from ..analysis.runs import references
    if job['run_type'] != 'aa_only' or job['status'] != 'completed':
        return False, []
    try:
        data = references.verify(run)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        return False, [f'not offered as an AA reference: {error}']
    return True, list(data.get('warnings') or [])


def unregistered(selected=None):
    """The run directories in this workspace that no job row lists, newest manifest first.

    A directory whose manifest cannot be read or names a run that is not stopped is skipped: this is a listing a
    reader acts on, not a repair pass.
    """
    selected = selected or paths.current()
    rows = {job['id'] for job in Store(selected.database).all()}
    found = []
    for manifest_path in sorted(Path(selected.runs).glob('*/manifest.json')):
        run = manifest_path.parent
        if run.is_symlink() or not RUN_ID.fullmatch(run.name) or run.name in rows:
            continue
        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(manifest, dict) or manifest.get('status') not in TERMINAL:
            continue
        found.append({'id': run.name, 'run_type': manifest.get('run_type'), 'status': manifest.get('status'),
                      'molecule_id': manifest.get('molecule_id'), 'label': manifest.get('label')})
    return found


def build(selected, run_id):
    """The row this directory would become, plus the report a dry run prints. Nothing is written."""
    selected = selected or paths.current()
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise errors.InvalidRunId('A run id is twelve lowercase hexadecimal characters')
    run = Path(selected.runs) / run_id
    if run.is_symlink() or not run.is_dir():
        raise errors.RunNotFound(f'no run directory {run_id} in {selected.workspace}')
    manifest_path = run / 'manifest.json'
    if not manifest_path.is_file():
        raise errors.RunNotFound(f'run {run_id} has no manifest beside it: {run}')
    if Store(selected.database).get(run_id) is not None:
        raise errors.RunConflict(f'run {run_id} is already registered in this workspace')
    manifest = json.loads(manifest_path.read_text())
    if not isinstance(manifest, dict):
        raise ValueError(f'run {run_id} has a manifest that is not an object')
    with paths.use(selected):
        run_inputs.verify_manifest(run, manifest)
        job = _record(run, manifest)
        reference, warnings = _reference(run, job)
    job['reference_eligible'] = reference
    source = job.get('reference_run_id')
    if source and Store(selected.database).get(source) is None:
        raise errors.SourceUnavailable(f'run {run_id} consumes AA source {source}, which is not registered here; '
                                       f'adopt {source} first')
    report = {'run': run_id, 'run_type': job['run_type'], 'status': job['status'],
              'molecule_id': job['molecule_id'], 'label': job['label'],
              'reference_eligible': reference, 'analyses': len(job['analyses']),
              'warnings': warnings, 'applied': False}
    return job, report


def adopt(selected, run_id, *, apply=False):
    """Register one pasted run directory, or report what registering it would do."""
    job, report = build(selected, run_id)
    if not apply:
        return report
    try:
        Store((selected or paths.current()).database).insert(job)
    except ValueError as error:
        raise errors.RunConflict(f'run {run_id} was not registered: {error}') from error
    report['applied'] = True
    return report
