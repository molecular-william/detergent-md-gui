"""What the browser is shown about a run: a view built from plain inputs.

The coordinator owns a run's lifecycle. Which fields a run presents, where its logs are
and what the ETA read from them says are view concerns, so they live here as functions
of the record, the run's directory, its manifest and the ownership flags -- testable
without a Flask app, and with nothing inside that can abort a request.

Two of the inputs exist because the view must not reach for them itself: ``ownership``
(the coordinator knows which of its workers holds a run) and ``console_log`` (the
console log lives outside the run directory in the pre-2.0 layout).
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from ..execution import workflow
from ..execution.adapters import cg
from ..execution.coordination.manifest import stage_log_path as resolve_stage_log
from . import progress as stage_progress

VISIBLE_FIELDS = frozenset((
    'id','label','detergent','molecule_name','molecule_id','method','profile',
    'status','stage','created','started_at','ended_at','error',
    'artifact_revision','run_type','execution_kind',
))
HIDDEN_FIELDS = frozenset((
    'pid','gromacs_eta','gromacs_remaining_seconds','eta_minutes','stage_estimate_minutes',
))
ANALYSIS_SUMMARY_FIELDS = frozenset((
    'id','kind','status','created_at','started_at','ended_at','error','directory',
))
STAGE_SUMMARY_FIELDS = frozenset(('name','status','started_at','ended_at'))
RUN_ID = re.compile(r'[a-f0-9]{12}')
UNREPAIRABLE = 'Invalid persisted run ID; repair the metadata before using this record'


def usable_run_id(job) -> bool:
    """Whether a record's id can address a run directory at all."""
    return isinstance(job.get('id'), str) and bool(RUN_ID.fullmatch(job['id']))


def tail(path, limit=65536) -> str:
    """The end of a log file, or nothing when it is not there."""
    path = Path(path)
    if not path.is_file():
        return ''
    with path.open('rb') as fp:
        fp.seek(max(0, path.stat().st_size - limit))
        return fp.read(limit).decode('utf-8', errors='replace')


def parse_gromacs_eta(text) -> dict:
    """The estimate GROMACS reported after its latest mdrun start/end marker."""
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


def ownership_flags(job, *, active=False, analysis_active=False) -> dict:
    """can_cancel / can_retry / can_delete for a run, given who holds it locally."""
    return {
        'can_cancel': (active and job['status'] in ('queued','running')) or job['status'] == 'waiting',
        'can_retry': job['status'] == 'failed',
        'can_delete': job['status'] in ('completed','failed','cancelled','blocked') and not active and not analysis_active,
    }


def analysis_view(job, summary) -> list:
    """Public analysis records; summary drops the heavy 'outputs' list."""
    keys = ANALYSIS_SUMMARY_FIELDS if summary else ANALYSIS_SUMMARY_FIELDS | {'outputs'}
    return [{k: v for k, v in task.items() if k in keys} for task in job.get('analyses', [])]


def consistency_summary(job):
    """The integers a run card states about its comparison, or `None` when there is nothing to state.

    Projected from the summary the analysis published into the job record -- the same counts card 1 of the panel
    badges -- rather than exposing the analyses' `result` wholesale: a card needs two numbers, and the same field on
    a surfaces analysis weighs 3.5 kB of commands and checksums. Only a `completed` attempt answers and the newest
    one wins, because a count from an attempt that did not finish is not something a card may state.
    """
    for task in reversed(job.get('analyses') or []):
        if task.get('kind') != 'mapping-consistency' or task.get('status') != 'completed':
            continue
        pairs = (task.get('result') or {}).get('pairs')
        if not isinstance(pairs, dict) or not isinstance(pairs.get('pairs'), int):
            return None
        return {'pairs': pairs['pairs'], 'compared': pairs.get('compared'),
                'outside': pairs.get('cg_outside_aa_range') or 0}
    return None


def elapsed(job):
    """(elapsed_seconds, warnings); (None, []) when the record has no started_at."""
    start = job.get('started_at')
    if not start:
        return None, []
    try:
        began = datetime.fromisoformat(start)
        ended = datetime.fromisoformat(job['ended_at']) if job.get('ended_at') else datetime.now(began.tzinfo)
        return max(0, (ended - began).total_seconds()), []
    except (ValueError, TypeError):
        return None, ['Invalid persisted timestamp; elapsed time unavailable']


def stage_view(job, manifest):
    """(stages, workflow_stages) with defensive type checks."""
    stages = manifest.get('stages', []) if manifest else []
    if not isinstance(stages, list) or any(not isinstance(stage, dict) for stage in stages):
        stages = []
    workflow_stages = manifest.get('stage_plan') or job.get('stage_plan') or [name for name, _ in cg.STAGES]
    return stages, workflow_stages


def running_stage(job, stages):
    """(the stage this run is in, the directory its script ran in) or (None, None)."""
    if job.get('status') != 'running':
        return None, None
    current = next((s for s in reversed(stages) if s.get('status') == 'running'), None)
    if not current:
        return None, None
    stage_dir = next((Path(rel).parent for name, rel in workflow.stage_definitions(job)[0] if name == current['name']), None)
    return current, stage_dir


def stage_log_candidates(job, current, stage_dir, *, run_dir, console_log=None) -> list:
    """Every file that could hold the running stage's log, most specific first.

    A stage's recorded `log` is not proof of what is in it. Prepare records the run's console log against a stage
    that has not started yet, and `run()` replaces it with the stage's own `logs/<stage>.log` -- so a run prepared
    one way and executed another records a file that exists and carries none of GROMACS' output. Existence cannot
    choose between them; the callers below pick by what the file says.
    """
    attempt = None
    if job.get('resume_in_place') and job.get('resume_count'):
        try:
            attempt = int(job['resume_count']) or None
        except (TypeError, ValueError):
            attempt = None
    candidates = []
    if current.get('log'):
        recorded = resolve_stage_log(run_dir, recorded=current['log'])
        if recorded is not None:
            candidates.append(recorded)
    if stage_dir:
        encoded = resolve_stage_log(run_dir, name=stage_dir.name, resume_count=attempt)
        if encoded is not None:
            candidates.append(encoded)
    if not attempt and console_log is not None:
        # The recorded path first, then the location this run would have written. While
        # resuming, the console log is not a fallback: its tail belongs to the attempt
        # being resumed from, so an ETA read from it would report progress not yet made.
        candidates.append(Path(console_log))
    return candidates


def stage_log_file(job, current, stage_dir, *, run_dir, console_log=None):
    """The first recorded or discoverable log file for the running stage, or None.

    What the console tail reads: the file the writer named, whether or not GROMACS ever wrote to it. Progress and
    the ETA ask a different question and go through `stage_log_candidates` instead.
    """
    for candidate in stage_log_candidates(job, current, stage_dir, run_dir=run_dir, console_log=console_log):
        if candidate.is_file():
            return candidate
    return None


def stage_log(job, current, stage_dir, *, run_dir, console_log=None) -> str:
    """The end of the running stage's log, or '' when no candidate file holds it."""
    path = stage_log_file(job, current, stage_dir, run_dir=run_dir, console_log=console_log)
    return tail(path) if path is not None else ''


def eta(job, stages, *, run_dir, console_log=None) -> dict:
    """GROMACS ETA parsed from the first log of the running stage that carries one.

    Same reason as `progress`: the recorded file exists on every stage and on a run prepared differently from how it
    was executed it is the console log, whose GROMACS block belongs to whichever stage last wrote there -- or to none.
    """
    current, stage_dir = running_stage(job, stages)
    if current is None:
        return {}
    for path in stage_log_candidates(job, current, stage_dir, run_dir=run_dir, console_log=console_log):
        if not path.is_file():
            continue
        found = parse_gromacs_eta(tail(path))
        if found:
            return found
    return {}


def progress(job, stages, *, run_dir, console_log=None) -> dict:
    """How far the running stage has got: its legs and the step within the current one.

    `eta` answers "when will this leg finish"; this answers "how much of the stage is done", which is the question a
    three-leg script (`cg_simulation.sh`: min, eq, md) leaves unanswered for two thirds of its life.
    """
    current, stage_dir = running_stage(job, stages)
    if current is None:
        return {}
    # `stage_dir` is the workflow's own relative path (`4_CG_sim`); the mdps the log names are relative to it, so the
    # reading needs the directory, not the relative name.
    # Stage scripts and the mdps their logs name live under `stages/`; `stage_dir` is the workflow's own relative name.
    directory = None
    if stage_dir is not None:
        directory = Path(stage_dir) if Path(stage_dir).is_absolute() else Path(run_dir) / 'stages' / stage_dir
    # The file, not a tail: leg markers stand at the start of legs, which on a long production is megabytes from the end.
    # And the *content* chooses: a recorded console log exists on every stage and states no legs, so trusting the first
    # file that opens is what left this bar empty on a run whose own `logs/4_CG_sim.log` said 93%.
    name = current.get('name') or ''
    for path in stage_log_candidates(job, current, stage_dir, run_dir=run_dir, console_log=console_log):
        reading = stage_progress.progress_from_file(name, directory, path)
        if reading.get('legs'):
            return reading
    return {}


def gpu_name(manifest, job=None):
    """The mdrun device a run used, by the name the host reported for it, or None when it recorded none.

    Read from the manifest, not from the form that asked for it: a prepared run records every device the host
    had (`environment.devices`) and each stage records the index, name and UUID it ran on
    (`resource_usage.gpu`). A run prepared before this setting existed records no device and therefore shows
    no name; a run on a host that reported none records its index with an empty name, which is the honest
    answer rather than the driver's guess.
    """
    settings = manifest.get('settings')
    if not isinstance(settings, dict):
        settings = (job or {}).get('settings')
    index = settings.get('mdrun_gpu', 0) if isinstance(settings, dict) else 0
    try:
        choice = int(0 if index in (None, '') else index)
    except (TypeError, ValueError):
        return None
    environment = manifest.get('environment')
    for device in (environment.get('devices') if isinstance(environment, dict) else None) or []:
        if isinstance(device, dict) and device.get('index') == choice and device.get('name'):
            return device['name']
    for stage in reversed(manifest.get('stages') or []):
        usage = stage.get('resource_usage') if isinstance(stage, dict) else None
        device = usage.get('gpu') if isinstance(usage, dict) else None
        if isinstance(device, dict) and device.get('index') == choice and device.get('name'):
            return device['name']
    return None


def run_view(job, *, run_dir=None, manifest=None, ownership=None, busy=False, console_log=None, summary=False) -> dict:
    """One run as the browser sees it.

    ``run_dir`` is None when the record's id cannot address a directory: the view then
    reports the record as unrepairable instead of raising, which is the one thing a view
    can do that a request handler cannot.
    """
    result = {k: v for k, v in job.items()
              if k not in HIDDEN_FIELDS and (not summary or k in VISIBLE_FIELDS)}
    result['metadata_warnings'] = []
    if run_dir is None or not usable_run_id(job):
        return result | {'status': 'failed', 'error': UNREPAIRABLE, 'can_cancel': False,
                         'can_delete': False, 'can_retry': False, 'stages': [],
                         'workflow_stages': [name for name, _ in cg.STAGES],
                         'elapsed_seconds': None, 'analyses': [], 'consistency': None}
    run_dir = Path(run_dir)
    manifest = manifest or {}
    result.update(ownership or {})
    result['gpu_name'] = gpu_name(manifest, job)
    result['analyses'] = analysis_view(job, summary)
    result['consistency'] = consistency_summary(job)
    if result.get('execution_kind') == 'screening-stub':
        # A stub must not be read as a completed simulation anywhere it is displayed.
        result['execution_note'] = 'screening stub — no MD executed'
    stages, workflow_stages = stage_view(job, manifest)
    result['stages'] = stages
    result['workflow_stages'] = workflow_stages
    result['resume_stages'] = (workflow.resumable_stages(run_dir, metadata=manifest)
                              if job.get('status') in ('failed','cancelled','completed') else [])
    if busy:
        result['can_delete'] = False
        result['resume_stages'] = []
        result['metadata_warnings'].append('An external worker still holds this run; reuse and deletion are blocked until it exits')
    if (run_dir / 'manifest.json').is_file() and not manifest:
        result['metadata_warnings'].append('Manifest is unreadable; inspect the original artifact')
    seconds, warnings = elapsed(job)
    result['elapsed_seconds'] = seconds
    result['metadata_warnings'].extend(warnings)
    result.update(eta(job, stages, run_dir=run_dir, console_log=console_log))
    result['progress'] = progress(job, stages, run_dir=run_dir, console_log=console_log)
    for task in result['analyses']:
        # `directory` is written by the worker for every attempt, but a record that lacks it must cost the runs list
        # a progress line rather than a 500: this view's one promise is to report instead of raising.
        if task['status'] == 'running' and task.get('directory'):
            try: task['progress'] = json.loads((run_dir / task['directory'] / 'progress.json').read_text())['phase']
            except (OSError, ValueError): pass
    if summary:
        # A skipped stage's reason travels with the summary: it is the stage's own sentence about work it did not do,
        # and a run that completes without a score is exactly where a reader needs it. A failed stage's error is already
        # at run level, so the whitelist stays the whitelist.
        result['stages'] = [{k: v for k, v in stage.items() if k in STAGE_SUMMARY_FIELDS}
                            | ({'error': stage['error']} if stage.get('status') == 'skipped' and stage.get('error') else {})
                            for stage in stages]
        result['detail_revision'] = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    return result
