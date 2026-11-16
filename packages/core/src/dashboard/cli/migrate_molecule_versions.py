"""Move every unversioned molecule folder into `molecules/<id>/v1/` and stamp its version.

A molecule used to live as `molecules/<id>/` itself. It now lives as `molecules/<id>/<version>/`, where
`metadata.version` names the version and a selection names that pair; the unversioned shape is retired, so a plain
folder is refused by `aa_molecules.resolve`. This migration leaves every reader one shape.

What it does, per molecule folder and only with `--apply`:

* every entry of a plain `molecules/<id>/` is renamed into a new `molecules/<id>/v1/`; each entry is one atomic
  rename, and a folder that is a symlink or already holds a `v1` is refused without being touched.
* its `metadata.json` gains `version: 'v1'` and keeps every other field. When the folder has none, the catalogue's
  own reader generates it (the same record a selection would generate), stamped with the version.
* a folder that already states a version directory is left alone as `unchanged`, so a second `--apply` is a no-op.

The ledger is `<root>/.named-migration/versions.json`; `--rollback` moves every entry back, removes a metadata file
the migration generated and restores the `version` field (or its absence) one that existed had. A dry run is the
default. Every migrated folder is verified through `aa_molecules.inspect(root, id)`, which must state version
`v1`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from dashboard import files, paths
from dashboard.models.molecules import aa

TOOL = 'dashboard.cli.migrate_molecule_versions'
VERSION = 1
#: The one version this migration writes: the plain folder was the molecule's only, unversioned content.
VERSION_NAME = 'v1'
#: The ledger `--apply` writes and `--rollback` reads, under the molecule root it migrated.
BACKUP = Path('.named-migration') / 'versions.json'
#: What may name a molecule folder; a file or a dot directory beside them is not one.
FOLDER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}')
_MISSING = object()


def _read_metadata(path):
    """The object at `path`, or `None` when it is absent; a file that is not an object is refused."""
    if not path.exists() and not path.is_symlink():
        return None
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f'{path.name}: expected an object')
    return value


def _folders(root):
    """The molecule folders under a root, in name order."""
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        return []
    return [path for path in sorted(root.iterdir())
            if path.is_dir() and FOLDER.fullmatch(path.name)]


def _entry(molecule_id, folder):
    """What this folder's migration would be, or why it will not be touched. Reads only."""
    entry = {'id': molecule_id, 'folder': str(folder), 'version': VERSION_NAME,
             'status': 'unchanged', 'why': None, 'entries': []}
    if folder.is_symlink():
        return {**entry, 'status': 'refused', 'why': 'the molecule folder is a symbolic link'}
    versions = aa.versions(folder.parent, molecule_id)
    if versions:
        return {**entry, 'why': f'already states version {versions[-1]}'}
    target = folder / VERSION_NAME
    if target.exists() or target.is_symlink():
        return {**entry, 'status': 'refused',
                'why': f'molecules/{molecule_id}/{VERSION_NAME} already exists'}
    try:
        _read_metadata(folder / 'metadata.json')
    except (OSError, ValueError) as error:
        return {**entry, 'status': 'refused', 'why': f'metadata.json is unreadable: {error}'}
    entry['entries'] = sorted(path.name for path in folder.iterdir())
    entry['status'] = 'move'
    return entry


def plan(root):
    """What the migration would move under this molecule root. Reads only."""
    return [_entry(folder.name, folder) for folder in _folders(root)]


def _stamp_metadata(root, molecule_id, folder):
    """Stamp `version` on the folder's metadata, generating it first when the folder has none.

    Returns what rollback needs: whether the file existed and, if it did, the version it stated (or `None` when it
    stated none). Everything else in the record is kept.
    """
    path = folder / 'metadata.json'
    existed = path.exists()
    if not existed:
        # The catalogue's own reader writes the same metadata a selection would, version included.
        aa.inspect(root, molecule_id, version=VERSION_NAME, generate_metadata=True)
        if not path.is_file():
            raise ValueError(f'molecules/{molecule_id}: metadata.json could not be generated')
        return {'existed': False, 'had_version': False, 'version': None}
    original = path.read_text()
    record = _read_metadata(path)
    old = record.get('version', _MISSING)
    if old != VERSION_NAME:
        record['version'] = VERSION_NAME
        files.atomic_json(path, record)
    # The original text travels in the ledger: rollback puts back the file it found, byte for byte.
    return {'existed': True, 'had_version': old is not _MISSING,
            'version': None if old is _MISSING else old, 'original': original}


def _write_ledger(root, done):
    """Write the backup for the folders that did move; a second `--apply` with nothing to do writes none."""
    if done:
        files.atomic_json(root / BACKUP, {'tool': TOOL, 'version': VERSION,
                                          'created_at': files.now_iso(), 'molecules': done})


def apply(entries, root):
    """Move every planned folder's entries into its `v1/`, stamp the version, and verify the result.

    Each entry is one atomic rename. A failure part-way through a folder puts back what already moved, so a refused
    folder is left as it was; the folders that did move are in the ledger even when a later one fails.
    """
    root = Path(root)
    done = []
    try:
        for entry in entries:
            if entry['status'] != 'move':
                continue
            molecule_id = entry['id']
            folder, target = root / molecule_id, root / molecule_id / VERSION_NAME
            if target.exists() or target.is_symlink():
                raise ValueError(f'molecules/{molecule_id}/{VERSION_NAME} already exists')
            target.mkdir()
            moved, metadata = [], None
            try:
                for name in entry['entries']:
                    source = folder / name
                    if not source.exists() and not source.is_symlink():
                        raise ValueError(f'molecules/{molecule_id}/{name} disappeared')
                    os.rename(source, target / name)
                    moved.append(name)
                metadata = _stamp_metadata(root, molecule_id, target)
                record = aa.inspect(root, molecule_id)
                if record['version'] != VERSION_NAME:
                    raise ValueError(f'molecules/{molecule_id}: inspect read version '
                                     f'{record["version"]!r}, not {VERSION_NAME!r}')
            except Exception:
                # Undo this folder exactly: a generated metadata is removed, an existing one gets its own bytes back.
                if metadata is None and 'metadata.json' not in entry['entries']:
                    (target / 'metadata.json').unlink(missing_ok=True)
                elif metadata is not None and not metadata.get('existed'):
                    (target / 'metadata.json').unlink(missing_ok=True)
                elif metadata is not None and metadata.get('original') is not None:
                    (target / 'metadata.json').write_text(metadata['original'])
                for name in reversed(moved):
                    os.rename(target / name, folder / name)
                try:
                    target.rmdir()
                except OSError:
                    pass
                raise
            entry.update(applied=True, metadata=metadata)
            done.append({'id': molecule_id, 'version': VERSION_NAME, 'entries': list(entry['entries']),
                         'metadata': metadata})
    except Exception:
        _write_ledger(root, done)
        raise
    _write_ledger(root, done)
    return done


def rollback(root):
    """Undo the moves in the ledger; `None` when it cannot be applied cleanly."""
    root = Path(root)
    ledger = root / BACKUP
    if not ledger.is_file():
        print(f'no backup at {ledger}')
        return None
    backup = json.loads(ledger.read_text())
    records = [record for record in backup.get('molecules') or [] if isinstance(record, dict)]
    missing = [record for record in records if not (root / record['id'] / VERSION_NAME).is_dir()]
    blocked = [record for record in records
               for name in record.get('entries') or []
               if (root / record['id'] / name).exists()]
    for record in missing:
        print(f"missing molecules/{record['id']}/{VERSION_NAME}")
    for record in blocked:
        print(f"refused molecules/{record['id']} already holds one of its entries")
    if missing or blocked:
        return None
    for record in reversed(records):
        folder, target = root / record['id'], root / record['id'] / VERSION_NAME
        metadata = record.get('metadata') or {}
        path = target / 'metadata.json'
        if not metadata.get('existed'):
            if path.exists() or path.is_symlink():
                path.unlink()
        elif metadata.get('original') is not None:
            # The exact text the migration found, so a rollback is the folder that was there.
            path.write_text(metadata['original'])
        elif path.is_file():
            value = _read_metadata(path)
            if metadata.get('had_version'):
                value['version'] = metadata['version']
            else:
                value.pop('version', None)
            files.atomic_json(path, value)
        for name in reversed(record.get('entries') or []):
            os.rename(target / name, folder / name)
        target.rmdir()
    return len(records)


def _line(entries, applied):
    for entry in entries:
        if entry['status'] == 'move':
            print(f'{("moved" if applied else "move")} molecules/{entry["id"]} -> '
                  f'molecules/{entry["id"]}/{VERSION_NAME}')
        elif entry['status'] == 'refused':
            print(f'{entry["id"]} refused: {entry["why"]}')


def summary(entries):
    counts = {'move': 0, 'unchanged': 0, 'refused': 0}
    for entry in entries:
        counts[entry['status']] = counts.get(entry['status'], 0) + 1
    text = f'move={counts["move"]} unchanged={counts["unchanged"]}'
    if counts.get('refused'):
        text += f' refused={counts["refused"]}'
    return text


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Move unversioned molecule folders into molecules/<id>/v1 (dry run by default)')
    parser.add_argument('--root', type=Path, default=None,
                        help='the molecules directory (default: the checkout\'s molecules/)')
    parser.add_argument('--apply', action='store_true',
                        help='perform the moves and stamp the versions (default: report only)')
    parser.add_argument('--rollback', action='store_true',
                        help=f'apply the moves recorded in {BACKUP.as_posix()} in reverse')
    args = parser.parse_args(argv)
    root = args.root if args.root is not None else paths.PROJECT_ROOT / 'molecules'
    if args.rollback:
        undone = rollback(root)
        if undone is None:
            return 1
        print(f'rollback={undone}')
        return 0
    entries = plan(root)
    if args.apply:
        apply(entries, root)
    print(summary(entries))
    _line(entries, args.apply)
    return 1 if any(entry['status'] == 'refused' for entry in entries) else 0


if __name__ == '__main__':
    raise SystemExit(main())
