"""Where the declared tools are: config/tools.json first, the inherited PATH second.

One resolver for every tool a stage may invoke. ``config/tools.json`` names the
tools this workspace uses; a declared value may be a path (honoured once it is
verified executable) or a command name (resolved on the search path). A
declaration that cannot be honoured resolves to nothing -- quietly falling back to
a different build of the same tool would turn a run's recorded provenance into a
guess.

Nothing here hard-codes a home directory or a build tree. The search path is the
bin directory of the interpreter running the dashboard, the directories of declared
tools, and the inherited PATH last.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .. import files, paths

# Tool identity in config/tools.json -> the commands that identity answers for.
IDENTITIES = {'gmx': 'gromacs', 'ff_map': 'fast_forward', 'ff_inter': 'fast_forward',
              'ff_assess': 'fast_forward'}
# Declarations that name a tool the run types resolve, in the order they are reported.
# Other keys in the same file describe where a tool came from and which revision it
# should be at -- provenance, not something to resolve or put on PATH.
TOOL_KEYS = ('gromacs', 'fast_forward', 'bartender', 'xtb', 'plumed')
# Declarations that answer for more than one command: the declared entry point
# locates the others, which sit beside it in the same install. A one-to-one
# identity (gromacs, whose command is gmx) is not a family.
FAMILIES = {'fast_forward'}


def config_file(config=None) -> Path:
    """The declaration this workspace uses, unless a caller names another."""
    return Path(config) if config is not None else paths.current().project_root / 'config/tools.json'


def declared_tools(config=None) -> dict:
    """The parsed declaration, or an empty mapping when there is no config file."""
    source = config_file(config)
    if not source.is_file():
        return {}
    payload = json.loads(source.read_text())
    if not isinstance(payload, dict) or not all(isinstance(value, str) for value in payload.values()):
        raise ValueError(f'Unknown tool configuration: {source}')
    return payload


def declared(key: str, config=None) -> str:
    """One declaration by key: a tool location, or a statement about a tool's source."""
    return declared_tools(config).get(key, '')


def declared_path(value: str) -> Path:
    """A declared path as a path, anchored on the workspace when it is relative.

    A declaration has to mean one thing wherever the process was started, so a
    relative value is read from the project root rather than from the current directory.
    """
    path = Path(value).expanduser()
    return path if path.is_absolute() else paths.current().project_root / path


def tool_declarations(config=None) -> dict:
    """Only the declarations that name a tool, in a stable order."""
    declared_all = declared_tools(config)
    return {key: declared_all[key] for key in TOOL_KEYS if declared_all.get(key)}


def vendor_state(tree) -> dict:
    """The revision and cleanliness of a source tree, or {} when it cannot be read.

    Read-only, and quiet on failure: a tree that is not a checkout, or a machine
    without git, has no revision to report -- which is not an error to raise here.
    """
    try:
        commit = subprocess.run(['git', '-C', str(tree), 'rev-parse', 'HEAD'],
                                capture_output=True, text=True, timeout=30, check=True)
        status = subprocess.run(['git', '-C', str(tree), 'status', '--porcelain'],
                                capture_output=True, text=True, timeout=30, check=True)
    except (OSError, subprocess.SubprocessError):
        return {}
    return {'commit': commit.stdout.strip(), 'dirty': bool(status.stdout.strip())}


def declared_provenance(config=None) -> dict:
    """Where a declared source is, which revision it should be at, and which it is at.

    A run records this alongside its tool report: the version output of an entry point
    says nothing about the source that produced it, and the vendor tree is not part of
    this checkout, so the revision is the only durable statement about the build.
    """
    source = declared('fast_forward_source', config)
    if not source:
        return {}
    tree = declared_path(source)
    return {'path': str(tree), 'declared_commit': declared('fast_forward_commit', config), **vendor_state(tree)}


def _is_executable(candidate) -> bool:
    path = Path(candidate).expanduser()
    return path.is_file() and os.access(path, os.X_OK)


def _declared_directory(declared_value: str) -> Path | None:
    """The directory a declaration places a tool in, if it can be located."""
    if os.sep in declared_value:
        path = declared_path(declared_value)
        return path.parent if _is_executable(path) else None
    resolved = shutil.which(declared_value)
    return Path(resolved).parent if resolved else None


def search_path() -> str:
    """The PATH for stage subprocesses: the running interpreter's bin first, never a home directory."""
    entries = [str(Path(sys.executable).parent)]
    for declared_value in tool_declarations().values():
        directory = _declared_directory(declared_value)
        if directory is not None:
            entries.append(str(directory))
    inherited = os.environ.get('PATH', '')
    return os.pathsep.join([entry for entry in entries if entry] + ([inherited] if inherited else []))


def _declared_executable(declared_value: str, search: str):
    """The executable a declaration names: as written when it is a path, else on the path."""
    if os.sep in declared_value:
        path = declared_path(declared_value)
        return str(path) if _is_executable(path) else None
    return shutil.which(declared_value, path=search)


def tool_path(command: str, config=None, path=None):
    """Resolve a command to an executable, or None when it cannot be resolved.

    A declared path is honoured as written: if it is not an executable file the
    answer is None, never a substitute found elsewhere. When the identity declares
    one entry point of a family (Fast_Forward declares ff_map and installs three
    commands), the rest resolve beside the declared one.
    """
    search = path if path is not None else search_path()
    identity = IDENTITIES.get(command, command)
    declared = declared_tools(config).get(identity, '')
    if not declared:
        return shutil.which(command, path=search)
    located = _declared_executable(declared, search)
    if located is None:
        return None
    if identity not in FAMILIES or Path(located).name == command:
        return located
    sibling = Path(located).parent / command
    return str(sibling) if _is_executable(sibling) else None


def plumed_environment(config=None, environ=None) -> dict:
    """The environment PLUMED needs in order to load, or {} when the declaration cannot supply it.

    GROMACS here is built *with* PLUMED support but PLUMED is **not compiled into it**: `gmx mdrun -plumed` loads a
    kernel at run time, and with none on the machine it stops with "You are trying to use plumed, but it is not
    available. Check your PLUMED_KERNEL environment variable." The declared entry point locates it -- the kernel sits
    in `lib/` beside the `bin/` of the same installation -- and that installation's `lib` directory goes on
    `LD_LIBRARY_PATH` *after* the inherited one, because the kernel's own dependencies (GSL, a BLAS) live there and
    nothing here should shadow a system library. Measured: handing `LD_LIBRARY_PATH` every conda package directory
    on this machine, to satisfy a kernel whose dependencies were not linked into an environment, kills MPI's own
    startup with "MPI_Init_thread" -- a worse failure than the one it fixes.

    An explicitly set `PLUMED_KERNEL` wins: this supplies what the declaration implies, it does not overrule the
    operator. A declaration that cannot be honoured contributes nothing, which is this module's rule everywhere
    else -- and the run then fails inside mdrun, saying exactly what is missing, rather than here saying nothing.
    """
    environ = os.environ if environ is None else environ
    kernel = environ.get('PLUMED_KERNEL', '')
    if not kernel:
        located = tool_path('plumed', config) if declared('plumed', config) else None
        if located is None:
            return {}
        candidates = sorted((Path(located).parent.parent / 'lib').glob('libplumedKernel.so*'))
        if not candidates:
            return {}
        kernel = str(candidates[0])
    inherited = environ.get('LD_LIBRARY_PATH', '')
    libs = [str(Path(kernel).parent)]
    return {'PLUMED_KERNEL': kernel,
            'LD_LIBRARY_PATH': os.pathsep.join(libs + ([inherited] if inherited else []))}


def record_versions(*commands, env=None, missing=None, version=True):
    """Resolve each command and record its path and digest, plus `--version` output when asked.

    `commands` entries are a command name or a `(name, args)` pair. A tool that cannot be resolved raises
    `missing(name)` when a caller supplies one, and `FileNotFoundError` otherwise.
    """
    recorded = {}
    for entry in commands:
        name, args = entry if isinstance(entry, tuple) else (entry, ('--version',))
        executable = tool_path(name)
        if not executable:
            if missing is not None:
                raise missing(name)
            raise FileNotFoundError(f'Missing tool: {name}')
        if version:
            result = subprocess.run([executable, *args], env=env, capture_output=True, text=True,
                                    check=True, timeout=30)
            recorded[name] = {'path': executable, 'version_output': result.stdout,
                              'sha256': files.sha256(executable)}
        else:
            recorded[name] = {'path': executable, 'sha256': files.sha256(executable)}
    return recorded


def declared_tool_checks(config=None):
    """Readiness entries ``(checks, blockers)`` for declarations that cannot be honoured.

    Checks, not blockers: a declaration for a tool the run type never invokes
    (bartender, xtb) is worth seeing but is no reason to refuse a run. The blocker
    for a tool the run does need comes from resolving that command.
    """
    checks = []
    for identity, declaration in tool_declarations(config).items():
        if os.sep not in declaration:
            continue
        path = declared_path(declaration)
        ready = _is_executable(path)
        checks.append({'label': f'Declared tool: {identity}',
                       'path': str(path),
                       'ready': ready,
                       'detail': 'Declared in config/tools.json' if ready
                                 else f'Declared as {declaration} in config/tools.json, which is not an executable file'})
    return checks, []
