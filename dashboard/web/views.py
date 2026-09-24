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

VISIBLE_FIELDS = frozenset((
    'id','label','detergent','molecule_name','molecule_id','method','profile',
    'status','stage','created','started_at','ended_at','error',
    'artifact_revision','run_type',
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


def eta(job, stages, *, run_dir, console_log=None) -> dict:
    """GROMACS ETA parsed from the most recent log of the running stage."""
    if job.get('status') != 'running':
        return {}
    current = next((s for s in reversed(stages) if s.get('status') == 'running'), None)
    if not current:
        return {}
    stage_dir = next((Path(rel).parent for name, rel in workflow.stage_definitions(job)[0] if name == current['name']), None)
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
    for candidate in candidates:
        if candidate.is_file():
            found = parse_gromacs_eta(tail(candidate))
            if found:
                return found
    return {}


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
                         'elapsed_seconds': None, 'analyses': []}
    run_dir = Path(run_dir)
    manifest = manifest or {}
    result.update(ownership or {})
    result['analyses'] = analysis_view(job, summary)
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
    for task in result['analyses']:
        if task['status'] == 'running':
            try: task['progress'] = json.loads((run_dir / task['directory'] / 'progress.json').read_text())['phase']
            except (OSError, ValueError): pass
    if summary:
        result['stages'] = [{k: v for k, v in stage.items() if k in STAGE_SUMMARY_FIELDS} for stage in stages]
        result['detail_revision'] = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    return result
