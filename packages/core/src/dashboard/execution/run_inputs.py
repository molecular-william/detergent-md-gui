"""What a run reads, recorded by name rather than by copy or digest.

A run directory used to hold a copy of everything it read: the force-field tree, the Martini ITPs, the molecule
files, its MDPs. The copy made a run's `inputs/` look self-contained, and it cost hundreds of megabytes per run for
bytes that are published, immutable and already hashed by the manifest.

This module is the replacement record. An entry names a file or a directory that already existed when the run was
prepared -- `published` in the repository, `store` in a workspace store, `run-output` in another run -- by its root
and relative path. The path is the identity: `verify` says whether the named file is still there, under the root it
was recorded against, and refuses a symlink or a path that escapes. A file the run's own `prepare` synthesized is
written by value into `inputs/` and discovered here as a `generated` entry.

Every entry has the same shape so a reader never asks which kind it is before it can print it:

    {"role", "label", "kind", "root", "path"}

`write` puts the record in `inputs/inputs.json` and returns the entries. A manifest written from it is layout 4 and
carries no `input_snapshot_sha256`: the record is a list of names, not a change-detection digest, and a change to a
referenced file no longer refuses a run. A layout-2 or layout-3 manifest is verified exactly as it was -- by the digest
of its `inputs/` directory, and by the digest each entry recorded -- so an old run keeps its own claim.
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import files, paths

INPUTS_DIRECTORY = 'inputs'
RECORD_NAME = 'inputs.json'
KINDS = ('published', 'store', 'run-output', 'generated')
ROOTS = ('repo', 'workspace', 'run', 'runs', 'absolute')
#: The layout in which an entry is a name: no digest, and the manifest carries no input snapshot.
LAYOUT = 4


def _relative(path, root):
    """`path` as POSIX relative to `root`, refusing a path that is not under it."""
    root = Path(root).resolve()
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f'{path} is not under {root}') from exc


def _entry(*, role, label, kind, root, path):
    if kind not in KINDS:
        raise ValueError(f'unknown input kind: {kind!r}')
    if root not in ROOTS:
        raise ValueError(f'unknown input root: {root!r}')
    if not role or not label:
        raise ValueError('an input entry needs a role and a label')
    return {'role': str(role), 'label': str(label), 'kind': kind, 'root': root, 'path': str(path)}


def _base(root, *, run_dir=None, repo_root=None, workspace_root=None, runs_root=None):
    if root == 'absolute':
        return Path('/')
    if root == 'repo':
        return Path(repo_root or paths.current().project_root)
    if root == 'workspace':
        return Path(workspace_root or paths.current().workspace)
    if root == 'run':
        if run_dir is None:
            raise ValueError('resolving a generated input needs the run directory')
        return Path(run_dir)
    if root == 'runs':
        return Path(runs_root or paths.current().runs)
    raise ValueError(f'unknown input root: {root!r}')


def published(role, path, *, label, repo_root=None):
    """A file the repository owns: force field, Martini ITP, template, packaged molecule file."""
    root = _base('repo', repo_root=repo_root)
    source = root / str(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError(f'a published input is not a regular file: {source}')
    return _entry(role=role, label=label, kind='published', root='repo', path=_relative(source, root))


def published_tree(role, path, *, label, repo_root=None):
    """A directory the repository owns. Its presence and identity are the name; its files are not hashed."""
    root = _base('repo', repo_root=repo_root)
    directory = root / str(path)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError(f'a published tree is not a regular directory: {directory}')
    if not any(directory.iterdir()):
        raise ValueError(f'a published tree is empty: {directory}')
    return _entry(role=role, label=label, kind='published', root='repo', path=_relative(directory, root))


def installed(role, path, *, label, workspace_root=None):
    """A file the workspace installed from the repository, read by every run where it lies.

    The Martini 3 set is the case: `prepare` installs it under `martini3/` (see `dashboard.martini3`) and every run
    reads the installed bytes instead of copying them. Recorded workspace-relative so a moved workspace still
    verifies it; a caller whose install lives elsewhere (a test with `DASHBOARD_MARTINI3`) records it absolutely,
    because it has no workspace-relative spelling.
    """
    base = _base('workspace', workspace_root=workspace_root)
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError(f'an installed input is not a regular file: {source}')
    try:
        entry_path = _relative(source, base)
    except ValueError:
        return _entry(role=role, label=label, kind='published', root='absolute',
                      path=source.resolve().as_posix())
    return _entry(role=role, label=label, kind='published', root='workspace', path=entry_path)


def store(role, path, *, label, workspace_root=None):
    """A file in a workspace store: a saved mapping, a parameterization record."""
    root = _base('workspace', workspace_root=workspace_root)
    source = root / str(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError(f'a stored input is not a regular file: {source}')
    return _entry(role=role, label=label, kind='store', root='workspace', path=_relative(source, root))


def absolute(role, path, *, label):
    """A file outside every configured root, recorded by its absolute path (an imported protein)."""
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError(f'an absolute input is not a regular file: {source}')
    return _entry(role=role, label=label, kind='store', root='absolute', path=source.resolve().as_posix())


def generated_entries(run_dir):
    """Every file `prepare` wrote into `inputs/`, which is where generated data lives."""
    run_dir = Path(run_dir)
    inputs = run_dir / INPUTS_DIRECTORY
    entries = []
    for path in files.safe_files(inputs):
        relative = path.relative_to(run_dir).as_posix()
        if relative == f'{INPUTS_DIRECTORY}/{RECORD_NAME}':
            continue
        entries.append(_entry(role='generated', label=path.relative_to(inputs).as_posix(), kind='generated',
                              root='run', path=relative))
    return entries


def write(run_dir, references=()):
    """Write the record and return its entries. `references` are the inputs that already existed."""
    run_dir = Path(run_dir)
    entries = [*references, *generated_entries(run_dir)]
    seen = set()
    for entry in entries:
        key = (entry['root'], entry['path'], entry['role'])
        if key in seen:
            raise ValueError(f'an input is recorded twice: {entry["root"]}:{entry["path"]} as {entry["role"]}')
        seen.add(key)
    inputs = run_dir / INPUTS_DIRECTORY
    if not inputs.is_dir():
        raise ValueError(f'a run has no {INPUTS_DIRECTORY}/ directory to record: {run_dir}')
    files.atomic_json(inputs / RECORD_NAME, {'inputs': entries})
    return entries


def resolve(entry, *, run_dir=None, repo_root=None, workspace_root=None, runs_root=None):
    """The path an entry names, refusing a symlink and a path that escapes its root."""
    base = _base(entry['root'], run_dir=run_dir, repo_root=repo_root, workspace_root=workspace_root,
                 runs_root=runs_root).resolve()
    named = base / entry['path']
    if named.is_symlink():
        raise ValueError(f'input {entry["role"]} is a symbolic link: {named}')
    path = named.resolve()
    if not path.is_relative_to(base):
        raise ValueError(f'input {entry["role"]} escapes its root: {entry["path"]}')
    return path


def verify_entry(entry, *, run_dir=None, repo_root=None, workspace_root=None, runs_root=None):
    """Resolve one entry against its root, naming what is missing.

    A layout-3 entry also carries a `sha256`; that one is measured exactly as it always was, so an old manifest
    keeps its claim. A named entry is verified by being the file (or directory) its root says it is.
    """
    path = resolve(entry, run_dir=run_dir, repo_root=repo_root, workspace_root=workspace_root, runs_root=runs_root)
    if 'sha256' in entry:
        if entry.get('files') is not None:
            if not path.is_dir():
                raise ValueError(f'input {entry["role"]} is missing: {path}')
            measured = files.json_sha256(files.hashes(path))
        else:
            if not path.is_file():
                raise ValueError(f'input {entry["role"]} is missing: {path}')
            measured = files.sha256(path)
        if measured != entry['sha256']:
            raise ValueError(f'input {entry["role"]} changed since this run was prepared: {path}')
        return path
    if not path.exists():
        raise ValueError(f'input {entry["role"]} is missing: {path}')
    return path


def verify_manifest(run_dir, manifest):
    """Verify what a manifest recorded, for a legacy run and for a record written by `write`.

    A manifest without `inputs` is a run prepared before this record existed: its provenance is the digest of the
    old `inputs/` directory, and a run type that recorded neither (pdc) has nothing to verify -- which is what it
    always said. Layout 2 and layout 3 are verified by their recorded digests; layout 4 is verified by resolving each
    name, because its entries carry no digest and its manifest no input snapshot.
    """
    run_dir = Path(run_dir)
    recorded = manifest.get('inputs')
    if recorded is None:
        expected = manifest.get('input_snapshot_sha256')
        if expected:
            files.verify(run_dir / INPUTS_DIRECTORY, expected)
        return None
    document = json.loads((run_dir / INPUTS_DIRECTORY / RECORD_NAME).read_text())
    if document.get('inputs') != recorded:
        raise ValueError(f'{RECORD_NAME} does not match the manifest record')
    if (manifest.get('layout_version') or 0) < LAYOUT:
        if files.json_sha256(document) != manifest.get('input_snapshot_sha256'):
            raise ValueError(f'{RECORD_NAME} does not match the recorded input snapshot digest')
    for entry in recorded:
        verify_entry(entry, run_dir=run_dir)
    return recorded
