"""Rebuild a pdc run's derived whole-system trajectory from its raw mdrun output.

The stage scripts convert `prod/run.xtc` into `prod/whole.xtc` once, with `gmx trjconv -pbc mol -center`, because a
raw frame shows molecules broken at the periodic boundary and the analyses and the Run view read the converted file.
That file is derived, never a simulation output: `run.xtc` is what mdrun wrote and is never written here. A reader
deciding what to keep on disk can therefore rebuild the derived file smaller (`-dt`, `-ndec`) at any time, and a
failed rebuild leaves the previous file byte-identical because the conversion lands in a temporary name first.

The job is a thread rather than a queued analysis: the analysis worker copies every source into its work directory,
which for a 2 GiB trajectory is a copy this job exists to avoid. A process restart loses the thread; the state file
and the temp-file replacement make that outcome one failed attempt, not a damaged run.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path

from dashboard import files
from dashboard.analysis.runs import trajectory_header
from dashboard.execution import tools
from detergent_pdc import layout as pdc_layout

#: The stage that holds the latest system first: the extension replays the assessment's system after a rebuild.
STAGES = ('extension', 'assessment')
RAW = 'prod/run.xtc'
TPR = 'prod/run.tpr'
GRO = 'run.gro'
TARGET = 'prod/whole.xtc'
SIDECAR = 'whole.xtc.json'
STATE_DIRECTORY = 'analyses/whole-trajectory'
#: The panel's default: one frame per 100 ps at 0.01 nm, measured on a live 1.6 GiB file as roughly a sixth of the
#: staged file's size and enough for the overview's sampled frames and the Run view's 10 ns sampling.
DEFAULT_DT_PS = 100
DEFAULT_DECIMALS = 2
#: Only the values a reader can choose, and the ones whose xtc cost was measured (3 decimals is the default).
DECIMALS = (1, 2, 3)

_RUNNING: dict[str, dict] = {}
_LOCK = threading.Lock()


def _state_path(run_dir):
    return Path(run_dir) / STATE_DIRECTORY / 'state.json'


def read_state(run_dir):
    try:
        data = json.loads(_state_path(run_dir).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(run_dir, state):
    files.atomic_json(_state_path(run_dir), state)


def locate(run_dir):
    """`(stage, raw, tpr)`: the latest stage holding a raw production trajectory and its run input.

    The extension is asked before the assessment because it is the system a run publishes; a run whose removal path
    was off writes only the assessment. A run with neither is refused rather than guessed at.
    """
    run_dir = Path(run_dir)
    for stage in STAGES:
        for base in (run_dir / 'stages', run_dir):
            for name in pdc_layout.STAGE_DIRECTORIES[stage]:
                prod = base / name / 'prod'
                raw, tpr = prod / 'run.xtc', prod / 'run.tpr'
                if raw.is_file() and tpr.is_file():
                    return stage, raw, tpr
    raise ValueError('this run holds no prod/run.xtc with its prod/run.tpr: there is no raw trajectory to convert')


def command(gmx, raw, tpr, target, *, dt_ps=DEFAULT_DT_PS, decimals=DEFAULT_DECIMALS):
    """The one `gmx trjconv` call, with the PBC treatment the analyses read and the size choices applied."""
    argv = [str(gmx), 'trjconv', '-f', str(raw), '-s', str(tpr), '-pbc', 'mol', '-center',
            '-ndec', str(int(decimals))]
    if dt_ps:
        argv += ['-dt', f'{float(dt_ps):g}']
    return argv + ['-o', str(target)]


def _measure(path, structure=None):
    """`(bytes, frames, cadence_ps)` for a trajectory file; frames and cadence are None when the header cannot say."""
    path = Path(path)
    if not path.is_file():
        return None
    frames = cadence = None
    if structure is not None and Path(structure).is_file():
        header = trajectory_header.read(structure, path)
        if header and header.get('frames'):
            frames = int(header['frames'])
            span = header.get('time_ns')
            cadence = round(span * 1000.0 / (frames - 1), 6) if span and frames > 1 else None
    return {'path': str(path), 'bytes': path.stat().st_size, 'frames': frames, 'cadence_ps': cadence}


def describe(run_dir):
    """What the panel states: the raw file, the derived one, the last rebuild's options and a live state."""
    run_dir = Path(run_dir)
    state = read_state(run_dir)
    if state.get('status') == 'running' and str(run_dir) not in _RUNNING:
        # A status file outlives the process that wrote it. Without its thread in this process it is not running
        # any more, and the temporary file's replacement never happened, so the previous file is still there.
        state = {**state, 'status': 'failed', 'error': 'interrupted by a dashboard restart'}
    answer = {'run': str(run_dir), 'defaults': {'dt_ps': DEFAULT_DT_PS, 'decimals': DEFAULT_DECIMALS},
              'decimals': list(DECIMALS), 'state': state, 'raw': None, 'whole': None,
              'sidecar': None, 'stage': None, 'error': None}
    try:
        stage, raw, tpr = locate(run_dir)
    except ValueError as error:
        answer['error'] = str(error)
        return answer
    structure = raw.parent / GRO
    answer.update({'stage': stage, 'raw': _measure(raw, structure),
                   'whole': _measure(raw.parent / 'whole.xtc', structure)})
    sidecar = raw.parent / 'whole.xtc.json'
    try:
        answer['sidecar'] = json.loads(sidecar.read_text()) if sidecar.is_file() else None
    except (OSError, ValueError):
        answer['sidecar'] = None
    return answer


def rebuild(run_dir, *, dt_ps=DEFAULT_DT_PS, decimals=DEFAULT_DECIMALS):
    """Convert `run.xtc` into `whole.xtc` once, synchronously, and answer the state that was written.

    The panel's POST runs this in a thread; a test or an operator calls it directly. A failure is recorded in the
    state file and never raised, because the panel's record is the report and the previous file is still there.
    """
    run_dir = Path(run_dir)
    stage, raw, tpr = locate(run_dir)
    target = raw.parent / 'whole.xtc'
    started = files.now_iso()
    state = {'status': 'running', 'stage': stage, 'dt_ps': float(dt_ps), 'decimals': int(decimals),
             'started_at': started, 'before_bytes': target.stat().st_size if target.is_file() else 0}
    # `gmx trjconv` chooses the output format from the suffix, so the temporary file keeps `.xtc` (a `.tmp` output
    # is refused and leaves nothing behind -- measured on the first live rebuild).
    temporary = target.with_name(f'.{target.stem}.{os.getpid()}.tmp.xtc')
    try:
        gmx = tools.tool_path('gmx')
        if not gmx:
            raise ValueError('gmx does not resolve on this host, so the trajectory cannot be converted')
        state['command'] = command(gmx, raw, tpr, temporary, dt_ps=dt_ps, decimals=decimals)
        state['gmx'] = gmx
        _write_state(run_dir, state)
        completed = subprocess.run(state['command'], cwd=str(target.parent), capture_output=True, text=True,
                                   input='System\nSystem\n', timeout=3600)
        (Path(run_dir) / STATE_DIRECTORY / 'console.log').write_text(completed.stdout + completed.stderr)
        if completed.returncode:
            raise RuntimeError(f'gmx trjconv refused the conversion (exit {completed.returncode}): '
                               + (completed.stderr.strip().splitlines() or ['no message'])[-1])
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise RuntimeError('gmx trjconv wrote no trajectory')
        os.replace(temporary, target)
        after = _measure(target, raw.parent / GRO)
        record = {'built_at': files.now_iso(), 'source': {'path': str(raw), 'bytes': raw.stat().st_size,
                                                          'sha256': files.sha256(raw)},
                  'options': {'pbc': 'mol -center', 'dt_ps': dt_ps, 'decimals': decimals},
                  'bytes': after['bytes'], 'frames': after['frames'], 'cadence_ps': after['cadence_ps'],
                  'gmx': gmx, 'command': state['command']}
        files.atomic_json(target.parent / SIDECAR, record)
        completed_state = {'status': 'completed', 'stage': stage, 'dt_ps': float(dt_ps), 'decimals': int(decimals),
                           'started_at': started, 'finished_at': files.now_iso(),
                           'before_bytes': state['before_bytes'], 'after_bytes': after['bytes'],
                           'frames': after['frames'], 'cadence_ps': after['cadence_ps']}
        _write_state(run_dir, completed_state)
        return completed_state
    except Exception as error:  # the state file is the record; the panel shows the reason and the target is untouched
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        failed_state = {**state, 'status': 'failed', 'finished_at': files.now_iso(), 'error': str(error)}
        _write_state(run_dir, failed_state)
        return failed_state


def start(run_dir, *, dt_ps=DEFAULT_DT_PS, decimals=DEFAULT_DECIMALS):
    """Begin a rebuild in this process, or refuse when one is already running for the run."""
    run_dir = Path(run_dir)
    if int(decimals) not in DECIMALS:
        raise ValueError('decimals must be one of ' + ', '.join(str(value) for value in DECIMALS))
    try:
        dt = float(dt_ps)
    except (TypeError, ValueError):
        raise ValueError('dt_ps must be a number of picoseconds') from None
    if not 0 < dt <= 1_000_000:
        raise ValueError('dt_ps must be between 0 and 1,000,000 ps')
    locate(run_dir)  # refuse here, with its sentence, rather than inside the thread
    with _LOCK:
        if str(run_dir) in _RUNNING:
            raise ValueError('a rebuild of this run is already running')
        started = files.now_iso()
        _RUNNING[str(run_dir)] = {'started_at': started}
        def job():
            try:
                rebuild(run_dir, dt_ps=dt, decimals=int(decimals))
            finally:
                with _LOCK:
                    _RUNNING.pop(str(run_dir), None)
        thread = threading.Thread(target=job, name=f'whole-trajectory-{run_dir.name}', daemon=True)
        thread.start()
    return {'status': 'running', 'dt_ps': dt, 'decimals': int(decimals), 'started_at': started}
