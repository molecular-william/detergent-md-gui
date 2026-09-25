"""Atomic metadata and bounded, symlink-free filesystem operations."""
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def atomic_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as fp:
            json.dump(value, fp, indent=2, allow_nan=False)
            fp.flush(); os.fsync(fp.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


def write_json_exclusive(path, value):
    """Create a JSON file atomically; raise FileExistsError if it already exists.

    Uses os.link so that the create-or-fail test and the publish are the same
    operation. Used by model stores that must never overwrite a prior record.
    """
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as fp:
            json.dump(value, fp, indent=2, allow_nan=False)
            fp.flush(); os.fsync(fp.fileno())
        try:
            os.link(name, path)
        except FileExistsError:
            raise FileExistsError(path) from None
    finally:
        if os.path.exists(name): os.unlink(name)


def now_iso():
    """UTC timestamp string used across manifests, jobs and model stores."""
    return datetime.now(timezone.utc).isoformat()


def json_sha256(value):
    """Deterministic SHA256 of a JSON-serializable value.

    Uses sorted keys and default separators, matching the legacy per-module
    helper used by bonded_states, model_registry and compositions. Compact
    serialization used by mapping identity is deliberately not shared here.
    """
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def stamp(paths):
    """A key that changes when any of these files does: (path, mtime, size) per file.

    The key is what makes a memo content-keyed rather than time-keyed: an unchanged corpus
    is not re-parsed, and a changed one cannot be answered from the old value.
    """
    entries = []
    for path in paths:
        try:
            stat = Path(path).stat()
        except OSError:
            continue
        entries.append((str(path), stat.st_mtime_ns, stat.st_size))
    return tuple(entries)


def memo(store, key, build):
    """One-entry memo keyed on a stamp: rebuild only when the key changes.

    ``store`` is a plain dict the caller owns, so each collaborator keeps its own entry and
    the cache dies with it.
    """
    cached = store.get('entry')
    if cached is not None and cached[0] == key:
        return cached[1]
    value = build()
    store['entry'] = (key, value)
    return value


def safe_files(root):
    root = Path(root)
    if not root.is_dir() or root.is_symlink(): return
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(directory)/d).is_symlink() and not d.startswith('.'))
        for name in sorted(names):
            path = Path(directory)/name
            if not path.is_symlink() and path.is_file() and not name.startswith('.') and not name.endswith(('.tmp', '.lock')):
                yield path


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as fp:
        for block in iter(lambda: fp.read(1024*1024), b''): digest.update(block)
    return digest.hexdigest()


def hashes(root):
    return {str(p.relative_to(root)): sha256(p) for p in safe_files(root)}


def verify(root, expected):
    if Path(root).is_symlink(): raise ValueError('Checksum roots must not be symbolic links')
    root = Path(root).resolve()
    if not expected: raise ValueError('No checksums recorded; clone this legacy run instead')
    for relative, digest in expected.items():
        path = root/relative
        if not path.resolve().is_relative_to(root) or path.is_symlink() or not path.is_file() or sha256(path) != digest:
            raise ValueError(f'Cannot reuse changed or missing artifact: {relative}')