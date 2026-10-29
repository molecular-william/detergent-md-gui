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

from pathlib import Path

from .. import files


def record(scripts, *, root):
    """`{stage name: repository path}` -> the manifest's `stage_scripts` record."""
    records = {}
    for name, path in scripts.items():
        source = Path(path)
        if not source.is_absolute():
            source = Path(root) / source
        if source.is_symlink() or not source.is_file():
            raise ValueError(f'stage script for {name} is not a regular file: {source}')
        try:
            relative = source.resolve().relative_to(Path(root).resolve()).as_posix()
        except ValueError as exc:
            raise ValueError(f'stage script for {name} is outside the repository: {source}') from exc
        records[name] = {'path': relative, 'sha256': files.sha256(source)}
    return records


def verify_one(name, declared, *, root):
    """Re-hash one recorded script, naming the stage and the file when it changed."""
    path = Path(root) / declared['path']
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
