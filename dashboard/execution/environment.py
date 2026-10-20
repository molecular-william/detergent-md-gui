"""Shared tool environment, MDP editing and prepared-run layout helpers.

Pure filesystem/process utilities used by every execution adapter. No adapter-
specific data lives here so that any-molecule workflows can reuse them.
"""
import os
import subprocess
import sys
from pathlib import Path

from .. import paths
from . import tools

ROOT = paths.DEFAULT.project_root
TUTORIAL_TEMPLATE = ROOT / "resources/templates/small_mols_fast_forward"
AA_TEMPLATE = TUTORIAL_TEMPLATE / "1_AA_reference"
FORCE_FIELD = AA_TEMPLATE / "charmm36-jul2022.ff"


#: Variables through which a caller redirects the interpreter of the process it starts. Dropped
#: from every environment here: a tool is measured, and run, in its own install or not at all.
INHERITED_INTERPRETER_VARIABLES = ('PYTHONPATH', 'PYTHONHOME')


def environment():
    """The environment a stage and a readiness probe run in.

    *Not* the caller's environment with a PATH in front of it: the two variables below point a
    child process's *interpreter* at somebody else's install, and a wrapper -- an agent runtime, an
    IDE, a launcher script -- sets them for its own reasons. Measured 2026-10-16 with the agent
    runtime's `python3.14` site-packages injected that way:

        ff_inter --help  -> rc=1, ImportError: cannot import name '_imaging' from 'PIL'
                            (.../python3.14/site-packages/PIL/__init__.py)

    with `ff_inter`, `fast_forward` and matplotlib all imported from the project's own python3.12
    site-packages: the right interpreter reading a foreign search path. Following it makes a
    readiness answer a statement about whoever started the dashboard -- and the same environment is
    what a stage runs with, so a run that passed readiness would have died in the same place.
    """
    env = os.environ.copy()
    env['PATH'] = tools.search_path()
    env['MPLBACKEND'] = 'Agg'
    env['OMP_NUM_THREADS'] = '8'
    for name in INHERITED_INTERPRETER_VARIABLES:
        env.pop(name, None)
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


def script_interpreter(executable):
    """The interpreter an executable's first line names, or None when it names none.

    Evidence, not a name: `ff_inter` is a python console script whose first line is `#!<venv
    python>`; `gmx` is a compiled binary with no first line to read. Read raw and never raise -- a
    file that cannot be read is probed as itself, and the answer says what happened.
    """
    try:
        with open(executable, 'rb') as handle:
            first_line = handle.readline(256).decode('utf-8', 'replace').strip()
    except OSError:
        return None
    if not first_line.startswith('#!'):
        return None
    words = first_line[2:].split()
    if words and Path(words[0]).name == 'env':
        words = words[1:]
    return words[0] if words else None


def probe_command(executable):
    """The command a readiness probe runs: a python script under this interpreter, else as itself.

    A console script's shebang names an interpreter by absolute path, written when its venv was
    built; when that interpreter is gone -- a moved checkout, a copied venv -- `exec` fails with
    ENOENT *naming the script*, a message about the wrong file that says nothing about the tool. The
    dashboard is already running the right interpreter (`sys.executable`, the venv python whose
    site-packages the tool's own install sits beside), so a python script is handed to it, and a
    compiled binary -- which has no interpreter to substitute -- is run as itself.
    """
    help_flag = '-h' if Path(executable).name == 'gmx' else '--help'
    interpreter = script_interpreter(executable)
    if interpreter is not None and Path(interpreter).name.startswith('python'):
        return [sys.executable, executable, help_flag]
    return [executable, help_flag]


def failure_detail(proc):
    """Why a probe failed: its exit status, and the first line of output that names an error.

    Not the tail of stderr, which is what this used to report: a traceback puts its most specific
    and least useful line last. Measured -- the unready `ff_inter` line showed the path of a PIL
    `__init__.py` deep inside the dump, while `ImportError: cannot import name '_imaging'` was the
    line that said what was wrong and never appeared.
    """
    lines = [line.strip() for line in (proc.stderr or proc.stdout).splitlines() if line.strip()]
    error = next((line for line in lines if 'error' in line.lower()), lines[0] if lines else '')
    return f'exited {proc.returncode}: {error}' if error else f'exited {proc.returncode} with no output'


#: How many executable identities one process remembers. A readiness answer is cheap to take again
#: and expensive to hold wrongly; 32 is more tools than any workflow resolves, so a clear at the
#: bound -- rather than evicting the oldest -- can only cost a re-probe.
PROBE_CACHE_LIMIT = 32

#: `(str(path), st_mtime_ns, st_size)` -> `(ready, detail)`.
PROBE_ANSWERS = {}


def clear_probe_cache():
    """Forget every remembered probe answer.

    Tests build executables and rewrite them; an operator who has just repaired a tool may want the
    next readiness request to say nothing about the one they replaced.
    """
    PROBE_ANSWERS.clear()


def probe_identity(executable):
    """The identity of the file a probe would run: its path, its mtime and its size.

    `None` when the path does not stat, which is the point: an absence is a fact about this moment,
    and a tool installed a minute later must be measured rather than answered from it.
    """
    try:
        status = os.stat(executable)
    except OSError:
        return None
    return str(executable), status.st_mtime_ns, status.st_size


def probe_tool(executable):
    """`(ready, detail)` for an executable, measured now and remembered against the file measured.

    Not `lru_cache` on the path string, which is what this was: that answer belonged to the
    *process*, so a tool repaired, upgraded or swapped under a running dashboard kept the verdict
    from its first probe until somebody restarted it -- and readiness is exactly the answer a user
    goes to after changing something. Measured 2026-10-20: one cold probe of `gmx -h` is 0.9-1.3 s
    and an unchanged executable answered from here is 0.00 s, so the identity key is what makes the
    second affordable without the first being a lie.

    A concurrent caller may measure the same unchanged file twice; both write the same answer.
    """
    identity = probe_identity(executable)
    if identity is not None and identity in PROBE_ANSWERS:
        return PROBE_ANSWERS[identity]
    try:
        proc = subprocess.run(
            probe_command(executable),
            env=environment(), capture_output=True, text=True, timeout=30,
        )
        answer = (proc.returncode == 0, ('Executable and imports checked' if proc.returncode == 0
                                         else failure_detail(proc)))
    except (OSError, subprocess.TimeoutExpired) as exc:
        answer = (False, str(exc))
    if identity is not None:
        if len(PROBE_ANSWERS) >= PROBE_CACHE_LIMIT:
            PROBE_ANSWERS.clear()
        PROBE_ANSWERS[identity] = answer
    return answer


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