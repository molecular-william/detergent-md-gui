"""Local disk admission limits and reporting; no automatic deletion."""
import json
import os
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

#: `max_concurrent_runs` is the ceiling per GPU, not across the host: the device is the resource two simulations
#: contend for, so a run on a free GPU starts beside one on a busy GPU. A host that reports no device answers as
#: device 0, which keeps its runs one at a time.
DEFAULTS = {'max_concurrent_runs': 1, 'max_concurrent_analyses': 2,
            'min_free_bytes': 1073741824, 'max_run_bytes': 21474836480,
            'max_total_bytes': 107374182400, 'reserve_per_job_bytes': 1073741824,
            'retention_days': 90}

#: Keys the same config file may carry that are not limits. `gpus` answers the host probe: "auto" asks it, "none"
#: says this host has no device (see `execution/devices.py:gpu_policy`). They are validated here so a file carrying
#: one is a process config, not an unknown key; `policy()` still answers only the limits, so a reader of a run's
#: limits never sees a device policy among them.
NON_LIMITS = {'gpus': ('auto', 'none')}


def policy(path):
    result = dict(DEFAULTS)
    if Path(path).is_file():
        data = json.loads(Path(path).read_text())
        if not isinstance(data, dict) or set(data)-set(result)-set(NON_LIMITS): raise ValueError('Unknown dashboard resource policy')
        for key, allowed in NON_LIMITS.items():
            if key in data and data[key] not in allowed:
                raise ValueError(f'{key} must be one of {", ".join(allowed)}')
        result.update({key: value for key, value in data.items() if key in result})
    if any(type(v) is not int or v <= 0 for v in result.values()): raise ValueError('Resource limits must be positive integers')
    if result['max_concurrent_runs']*8 > (__import__('os').cpu_count() or 1): raise ValueError('Per-GPU run concurrency exceeds available CPU threads (8 per run)')
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


#: Every live worker checks the quota on its 5 s tick, and walking the whole runs root is the expensive part of that
#: check (tens of milliseconds on a multi-gigabyte tree). The worker's own run is still measured every tick; only the
#: root total is reused, so a breach stops the worker at most one TTL late while a normal tick walks one tree.
USAGE_TTL_SECONDS = 10.0

#: One coordinator has one runs root. A small ceiling keeps a caller that asks about many directories from growing
#: the cache without bound.
_USAGE_CACHE_SIZE = 8
_usage_cache = {}
_usage_lock = threading.Lock()


def cached_usage(root, ttl=USAGE_TTL_SECONDS):
    """`usage(root)` served from a bounded TTL cache, walking at most once per window.

    The lock is held across the walk so two workers checking at the same moment do one stat pass rather than racing
    to repeat it. `usage()` stays the pure measurement; this is the worker's observation, and a stale answer cannot
    admit a run -- `check_worker` still stops a worker whose last observation breached a limit.
    """
    key = str(Path(root).resolve())
    with _usage_lock:
        cached = _usage_cache.get(key)
        if cached is not None and cached[0] > time.monotonic():
            return cached[1]
        value = usage(root)
        if key not in _usage_cache and len(_usage_cache) >= _USAGE_CACHE_SIZE:
            del _usage_cache[next(iter(_usage_cache))]
        _usage_cache[key] = (time.monotonic() + ttl, value)
        return value


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
    return {'disk_free_bytes': disk.free, 'run_bytes': used, 'limits': limits, 'retention_candidates': candidates}


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
    run_bytes = usage(run_dir)
    if run_bytes > limits['max_run_bytes']:
        raise ValueError('Worker stopped: per-run storage limit reached')
    # `runs_root` contains `run_dir`, so this walk covers the run's own bytes too; the run is measured once above for
    # its per-run limit and the root once per TTL for the total, rather than walking the run twice every tick.
    if cached_usage(runs_root) > limits['max_total_bytes']:
        raise ValueError('Worker stopped: total storage quota reached')
