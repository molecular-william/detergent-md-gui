"""What a run reads, recorded by reference rather than by copy.

A run directory used to hold a copy of everything it read: the force-field tree, the Martini ITPs, the molecule
files, its MDPs. The copy made a run's `inputs/` look self-contained, and it cost hundreds of megabytes per run for
bytes that are published, immutable and already hashed by the manifest.

This module is the replacement record. An entry names a file or a directory that already existed when the run was
prepared -- `published` in the repository, `store` in a workspace store, `run-output` in another run -- by its root,
relative path and digest. The digest is the tamper seal, not the identity: the path and label say what the file is,
and `verify` says whether it is still that file. A file the run's own `prepare` synthesized is written by value into
`inputs/` and discovered here as a `generated` entry.

Every entry has the same shape so a reader never asks which kind it is before it can print it:

    {"role", "label", "kind", "root", "path", "sha256", "bytes"}   # files
    {"…", "files"}                                                 # directories

`write` puts the record in `inputs/inputs.json` and returns the entries; the manifest's
`input_snapshot_sha256` is the digest of that whole document, so a record that was edited after the fact is
detected before a stage is allowed to run.
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import files, paths

INPUTS_DIRECTORY = 'inputs'
RECORD_NAME = 'inputs.json'
KINDS = ('published', 'store', 'run-output', 'generated')
ROOTS = ('repo', 'workspace', 'run', 'runs', 'absolute')


def _relative(path, root):
    """`path` as POSIX relative to `root`, refusing a path that is not under it."""
    root = Path(root).resolve()
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f'{path} is not under {root}') from exc


def _entry(*, role, label, kind, root, path, sha256, size, files=None):
    if kind not in KINDS:
        raise ValueError(f'unknown input kind: {kind!r}')
    if root not in ROOTS:
        raise ValueError(f'unknown input root: {root!r}')
    if not role or not label:
        raise ValueError('an input entry needs a role and a label')
    digest = str(sha256)
    if len(digest) != 64 or any(character not in '0123456789abcdef' for character in digest):
        raise ValueError(f'an input digest must be lowercase sha256: {sha256!r}')
    entry = {'role': str(role), 'label': str(label), 'kind': kind, 'root': root,
             'path': str(path), 'sha256': digest, 'bytes': int(size)}
    if files is not None:
        entry['files'] = int(files)
    return entry


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
    return _entry(role=role, label=label, kind='published', root='repo', path=_relative(source, root),
                  sha256=files.sha256(source), size=source.stat().st_size)


def published_tree(role, path, *, label, repo_root=None):
    """A directory the repository owns, recorded by the digest of its own file-hash map."""
    root = _base('repo', repo_root=repo_root)
    directory = root / str(path)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError(f'a published tree is not a regular directory: {directory}')
    digests = files.hashes(directory)
    if not digests:
        raise ValueError(f'a published tree is empty: {directory}')
    return _entry(role=role, label=label, kind='published', root='repo', path=_relative(directory, root),
                  sha256=files.json_sha256(digests), size=sum((directory / name).stat().st_size for name in digests),
                  files=len(digests))


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
                      path=source.resolve().as_posix(), sha256=files.sha256(source),
                      size=source.stat().st_size)
    return _entry(role=role, label=label, kind='published', root='workspace', path=entry_path,
                  sha256=files.sha256(source), size=source.stat().st_size)


def store(role, path, *, label, workspace_root=None):
    """A file in a workspace store: a saved mapping, a parameterization record."""
    root = _base('workspace', workspace_root=workspace_root)
    source = root / str(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError(f'a stored input is not a regular file: {source}')
    return _entry(role=role, label=label, kind='store', root='workspace', path=_relative(source, root),
                  sha256=files.sha256(source), size=source.stat().st_size)


def absolute(role, path, *, label):
    """A file outside every configured root, recorded by its absolute path (an imported protein)."""
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError(f'an absolute input is not a regular file: {source}')
    return _entry(role=role, label=label, kind='store', root='absolute', path=source.resolve().as_posix(),
                  sha256=files.sha256(source), size=source.stat().st_size)


def run_output(role, run_id, path, *, label, runs_root=None, sha256=None):
    """A file another run published, like an AA reference. The bytes are never copied."""
    root = _base('run', runs_root=runs_root)
    source = root / str(run_id) / str(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError(f'a referenced run output is not a regular file: {source}')
    return _entry(role=role, label=label, kind='run-output', root='runs', path=_relative(source, root),
                  sha256=sha256 or files.sha256(source), size=source.stat().st_size)


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
                              root='run', path=relative, sha256=files.sha256(path), size=path.stat().st_size))
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


def digest(entries):
    """The manifest's `input_snapshot_sha256`: one digest over the whole record."""
    return files.json_sha256({'inputs': list(entries)})


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
    """Measure one entry against its record, naming what changed."""
    path = resolve(entry, run_dir=run_dir, repo_root=repo_root, workspace_root=workspace_root, runs_root=runs_root)
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


def verify_manifest(run_dir, manifest):
    """Verify what a manifest recorded, for a legacy run and for a record written by `write`.

    A manifest without `inputs` is a run prepared before this record existed: its provenance is the digest of the
    old `inputs/` directory, and a run type that recorded neither (pdc) has nothing to verify -- which is what it
    always said.
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
    if files.json_sha256(document) != manifest.get('input_snapshot_sha256'):
        raise ValueError(f'{RECORD_NAME} does not match the recorded input snapshot digest')
    for entry in recorded:
        verify_entry(entry, run_dir=run_dir)
    return recorded
