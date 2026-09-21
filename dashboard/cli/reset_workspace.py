"""Reset only generated state in one dashboard workspace."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import shutil

from .. import files

TARGETS = (
    'runs', 'jobs.sqlite3', 'jobs.sqlite3-wal', 'jobs.sqlite3-shm',
    'mapping_drafts', 'bonded_states', 'model_registry', 'compositions',
)
RUNTIME_DIRECTORIES = ('runs', 'mapping_drafts', 'bonded_states', 'model_registry', 'compositions')


def _assert_unlocked(path: Path) -> None:
    lock = path / 'jobs.service.lock'
    if not lock.exists():
        return
    if lock.is_symlink() or not lock.is_file():
        raise ValueError('Service lock must be a regular file')
    with lock.open('r+') as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('Dashboard coordinator is active') from exc
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def reset_workspace(workspace: Path, *, confirm: bool, now=None) -> dict:
    workspace = Path(workspace).expanduser()
    if not workspace.is_absolute():
        raise ValueError('Workspace must be an absolute path')
    if workspace.is_symlink():
        raise ValueError('Workspace must not be a symbolic link')
    if not confirm:
        raise ValueError('Pass --confirm to reset generated workspace state')
    workspace.mkdir(parents=True, exist_ok=True)
    _assert_unlocked(workspace)
    deleted = []
    for relative in TARGETS:
        path = workspace / relative
        if path.is_symlink():
            raise ValueError(f'Refusing to remove symbolic link: {relative}')
        if not path.exists():
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        deleted.append(relative)
    for relative in RUNTIME_DIRECTORIES:
        (workspace / relative).mkdir(parents=True, exist_ok=True)
    record = {
        'timestamp': (now or (lambda: datetime.now(timezone.utc).isoformat()))(),
        'intent': 'fresh workspace reset',
        'workspace': str(workspace),
        'deleted': deleted,
        'recreated': list(RUNTIME_DIRECTORIES),
    }
    files.atomic_json(workspace / 'reset-record.json', record)
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description='Reset generated dashboard state')
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--confirm', action='store_true')
    args = parser.parse_args(argv)
    print(json.dumps(reset_workspace(args.workspace, confirm=args.confirm), indent=2))


if __name__ == '__main__':
    main()
