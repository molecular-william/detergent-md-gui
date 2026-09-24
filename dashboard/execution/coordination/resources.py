"""Local disk admission limits and reporting; no automatic deletion."""
from pathlib import Path
import json
import shutil
import os
from datetime import datetime, timezone
from ... import files

DEFAULTS = {'max_concurrent_runs': 1, 'max_concurrent_analyses': 2,
            'min_free_bytes': 1073741824, 'max_run_bytes': 21474836480,
            'max_total_bytes': 107374182400, 'reserve_per_job_bytes': 1073741824,
            'retention_days': 90}


def policy(path):
    result = dict(DEFAULTS)
    if Path(path).is_file():
        data = json.loads(Path(path).read_text())
        if not isinstance(data, dict) or set(data)-set(result): raise ValueError('Unknown dashboard resource policy')
        result.update(data)
    if any(type(v) is not int or v <= 0 for v in result.values()): raise ValueError('Resource limits must be positive integers')
    if result['max_concurrent_runs']*8 > (__import__('os').cpu_count() or 1): raise ValueError('Run concurrency exceeds available CPU threads (8 per run)')
    return result


def usage(root):
    total = 0
    if Path(root).is_symlink(): return 0
    for directory,dirs,names in os.walk(root,followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(directory)/d).is_symlink()]
        for name in names:
            path = Path(directory)/name
            try:
                if not path.is_symlink() and path.is_file(): total += path.stat().st_size
            except FileNotFoundError: pass
    return total


def report(root, jobs, limits):
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    disk = shutil.disk_usage(root)
    used = usage(root)
    candidates = []
    for job in jobs:
        try: age = (datetime.now(timezone.utc)-datetime.fromisoformat(job.get('ended_at',''))).total_seconds()/86400
        except (ValueError, TypeError): continue
        if age >= limits['retention_days'] and job.get('status') in ('completed','failed','cancelled'):
            candidates.append({'id': job['id'], 'age_days': int(age)})
    return {'disk_free_bytes': disk.free, 'run_bytes': used, 'limits': limits, 'retention_candidates': candidates,
            'retention_policy': 'Keep all data until explicitly deleted; age is a review suggestion.'}


def admit(report, reservations=0, required=None):
    limits = report['limits']
    reserve = (reservations+1)*limits['reserve_per_job_bytes'] + (required or 0)
    if report['disk_free_bytes']-reserve < limits['min_free_bytes']:
        raise ValueError('Insufficient free disk after job reservations')
    if report['run_bytes']+reserve > limits['max_total_bytes']:
        raise ValueError('Run storage quota would be exceeded')


def check_worker(run_dir, runs_root, limits):
    if shutil.disk_usage(run_dir).free < limits['min_free_bytes']:
        raise ValueError('Worker stopped: disk headroom limit reached')
    if usage(run_dir) > limits['max_run_bytes']:
        raise ValueError('Worker stopped: per-run storage limit reached')
    if usage(runs_root) > limits['max_total_bytes']:
        raise ValueError('Worker stopped: total storage quota reached')
