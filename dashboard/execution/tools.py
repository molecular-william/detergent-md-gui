"""Where the declared tools are: config/tools.json first, the inherited PATH second.

One resolver for every tool a stage may invoke. ``config/tools.json`` names the
tools this workspace uses; a declared value may be a path (honoured once it is
verified executable) or a command name (resolved on the search path). A
declaration that cannot be honoured resolves to nothing -- quietly falling back to
a different build of the same tool would turn a run's recorded provenance into a
guess.

Nothing here hard-codes a home directory or a build tree. The search path is the
workspace's own virtualenv bin directory, the directories of declared tools, and
the inherited PATH last.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from .. import paths

# Tool identity in config/tools.json -> the commands that identity answers for.
IDENTITIES = {'gmx': 'gromacs', 'ff_map': 'fast_forward', 'ff_inter': 'fast_forward',
              'ff_assess': 'fast_forward'}
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


def _is_executable(candidate) -> bool:
    path = Path(candidate).expanduser()
    return path.is_file() and os.access(path, os.X_OK)


def _declared_directory(declared: str):
    """The directory a declaration places its tool in, when it can be located."""
    candidate = Path(declared).expanduser()
    if os.sep in declared:
        return candidate.parent if _is_executable(candidate) else None
    resolved = shutil.which(declared)
    return Path(resolved).parent if resolved else None


def search_path() -> str:
    """The PATH for stage subprocesses: this workspace first, no home directory."""
    entries = [str(paths.current().project_root / 'dashboard/.venv/bin')]
    for declared in declared_tools().values():
        directory = _declared_directory(declared)
        if directory is not None:
            entries.append(str(directory))
    inherited = os.environ.get('PATH', '')
    return os.pathsep.join([entry for entry in entries if entry] + ([inherited] if inherited else []))


def _declared_executable(declared: str, search: str):
    """The executable a declaration names: as written when it is a path, else on the path."""
    if os.sep in declared:
        return str(Path(declared).expanduser()) if _is_executable(declared) else None
    return shutil.which(declared, path=search)


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


def declared_tool_checks(config=None):
    """Readiness entries ``(checks, blockers)`` for declarations that cannot be honoured.

    Checks, not blockers: a declaration for a tool the run type never invokes
    (bartender, xtb) is worth seeing but is no reason to refuse a run. The blocker
    for a tool the run does need comes from resolving that command.
    """
    checks = []
    for identity, declared in declared_tools(config).items():
        if os.sep not in declared:
            continue
        ready = _is_executable(declared)
        checks.append({'label': f'Declared tool: {identity}',
                       'path': str(Path(declared).expanduser()),
                       'ready': ready,
                       'detail': 'Declared in config/tools.json' if ready
                                 else f'Declared as {declared} in config/tools.json, which is not an executable file'})
    return checks, []
