"""The code a run executes, recorded by repository path and digest.

A run used to hold a copy of every stage script. The copy made a run look self-contained, and it meant an old run
re-executed the code of its own day -- but the same helper also lived in the repository, so there were two copies to
fix and two answers to "what ran".

This module records the repository file instead: one path and one digest per stage, written into the manifest at
prepare time. The executor runs the repository file with the stage directory as the working directory, and verifies
the digest before the stage starts. A changed helper refuses the stage by name, which is the honest answer: the run
can no longer claim to be running the code it recorded.
"""
from __future__ import annotations

import importlib
from pathlib import Path

from .. import files, paths

#: A run records the code it executes by repository path, spelled `dashboard/<rest>` since before the package moved
#: to `packages/core/src/dashboard`. The spelling stays the record's -- an installed distribution has no checkout to
#: name -- and the path is resolved against the package here, once, instead of in every adapter.
_DECLARED_PREFIX = 'dashboard/'

#: `(recorded prefix, distribution, prefix inside that package)` for code a feature took over. A prepared run records
#: the spelling of its day; the file is looked for where its distribution keeps it now. Nothing rewrites a manifest --
#: the digest is what proves the same bytes moved.
_FEATURE_PREFIXES: list[tuple[str, str, str]] = []


def register_prefixes(entries) -> None:
    """Let a feature answer for recorded paths whose files now live in its distribution."""
    for recorded, distribution, inside in entries:
        _FEATURE_PREFIXES.append((recorded, distribution, inside))


def _feature_file(text):
    """The file a moved recorded path names, or None when no registered feature holds it."""
    for recorded, distribution, inside in _FEATURE_PREFIXES:
        if not text.startswith(recorded):
            continue
        package = importlib.import_module(distribution)
        candidate = Path(package.__file__).resolve().parent / inside / text[len(recorded):]
        if candidate.is_file():
            return candidate
    return None


def code_path(declared, *, root):
    """The file a recorded code path names: in this package, in a feature that moved it, or under the data root."""
    text = str(declared)
    moved = _feature_file(text)
    if moved is not None:
        return moved
    if text.startswith(_DECLARED_PREFIX):
        return paths.PACKAGE_ROOT / text[len(_DECLARED_PREFIX):]
    source = Path(text)
    return source if source.is_absolute() else Path(root) / source


def record(scripts, *, root):
    """`{stage name: repository path}` -> the manifest's `stage_scripts` record."""
    records = {}
    for name, path in scripts.items():
        source = code_path(path, root=root)
        if source.is_symlink() or not source.is_file():
            raise ValueError(f'stage script for {name} is not a regular file: {source}')
        text = str(path)
        if text.startswith(_DECLARED_PREFIX):
            # The declaration is the record's spelling; it names a file in this package, not in the checkout. Runs
            # prepared before the package moved recorded the same spelling, so their digests keep verifying.
            relative = text
        else:
            try:
                relative = source.resolve().relative_to(Path(root).resolve()).as_posix()
            except ValueError as exc:
                raise ValueError(f'stage script for {name} is outside the repository: {source}') from exc
        records[name] = {'path': relative, 'sha256': files.sha256(source)}
    return records


def verify_one(name, declared, *, root):
    """Re-hash one recorded script, naming the stage and the file when it changed."""
    path = code_path(declared['path'], root=root)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'the stage script for {name} is missing: {path}')
    measured = files.sha256(path)
    if measured != declared['sha256']:
        raise ValueError(f'the stage script for {name} changed since this run was prepared: {path} '
                         f'(recorded {declared["sha256"]}, found {measured})')
    return path


def script_for(manifest, name, fallback, *, root):
    """The script a stage runs: the recorded repository file, or its own copy in a legacy run."""
    declared = (manifest.get('stage_scripts') or {}).get(name)
    if declared is None:
        return Path(fallback)
    return verify_one(name, declared, root=root)
