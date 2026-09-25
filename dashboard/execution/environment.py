"""Shared tool environment, MDP editing and prepared-run layout helpers.

Pure filesystem/process utilities used by every execution adapter. No adapter-
specific data lives here so that any-molecule workflows can reuse them.
"""
import os
import subprocess
from functools import lru_cache
from pathlib import Path

from .. import paths
from . import tools

ROOT = paths.DEFAULT.project_root
TUTORIAL_TEMPLATE = ROOT / "resources/templates/small_mols_fast_forward"
AA_TEMPLATE = TUTORIAL_TEMPLATE / "1_AA_reference"
FORCE_FIELD = AA_TEMPLATE / "charmm36-jul2022.ff"


def environment():
    env = os.environ.copy()
    env['PATH'] = tools.search_path()
    env['MPLBACKEND'] = 'Agg'
    env['OMP_NUM_THREADS'] = '8'
    return env


#: The keys a manifest records for a stage environment, in the order they are written.
RECORDED_KEYS = ('PATH', 'MPLBACKEND', 'OMP_NUM_THREADS')


def stage_environment(extras=None):
    """The environment a stage runs in.

    The composed PATH (Task 2.7) plus the two fixed settings. One function so a manifest
    cannot record a different environment from the one the stage ran with, and so `extras`
    has one place to be merged.
    """
    env = environment()
    return {**{key: env[key] for key in RECORDED_KEYS}, **(extras or {})}


def recorded_environment(extras=None):
    """The subset of the stage environment a manifest records."""
    return {key: value for key, value in stage_environment(extras).items() if key in RECORDED_KEYS}


@lru_cache(maxsize=8)
def probe_tool(executable):
    try:
        proc = subprocess.run(
            [executable, '-h' if Path(executable).name == 'gmx' else '--help'],
            env=environment(), capture_output=True, text=True, timeout=30,
        )
        return proc.returncode == 0, ('Executable and imports checked' if proc.returncode == 0
                                       else (proc.stderr or proc.stdout)[-1500:])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)


def update_mdp(path, changes):
    lines = path.read_text().splitlines()
    normalized = lambda x: x.strip().lower().replace('_', '-')
    changes = {normalized(k): str(v) for k, v in changes.items()}
    seen = set()
    for i, line in enumerate(lines):
        key = normalized(line.split('=', 1)[0])
        if key in changes:
            lines[i] = f'{key} = {changes[key]}'
            seen.add(key)
    lines.extend(f'{k} = {v}' for k, v in changes.items() if k not in seen)
    path.write_text('\n'.join(lines) + '\n')


def execution_root(run_dir):
    if run_dir.is_symlink() or (run_dir/'stages').is_symlink():
        raise ValueError('Execution directories must not be symbolic links')
    return run_dir / 'stages' if (run_dir / 'stages').is_dir() else run_dir