"""Small, symlink-safe repository for immutable JSON records."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from .. import files


class JsonRepository:
    def __init__(self, root: Path, pattern: str, validate_id: Callable[[str], str]):
        self.root = Path(root)
        self.pattern = pattern
        self.validate_id = validate_id

    def _root(self) -> Path:
        if self.root.is_symlink():
            raise ValueError('JSON repository root must not be a symbolic link')
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root.resolve()

    def path(self, record_id: str) -> Path:
        value = self.validate_id(record_id)
        root = self._root()
        path = root / self.pattern.format(id=value)
        if not path.resolve().parent.is_relative_to(root):
            raise ValueError('JSON record path escapes repository root')
        if path.is_symlink():
            raise ValueError('JSON records must not be symbolic links')
        return path

    def get(self, record_id: str) -> dict:
        path = self.path(record_id)
        try:
            value = json.loads(path.read_text())
        except FileNotFoundError:
            raise
        except (OSError, ValueError) as exc:
            raise ValueError(f'Invalid JSON record: {record_id}') from exc
        if not isinstance(value, dict):
            raise ValueError(f'JSON record must be an object: {record_id}')
        return value

    def list(self, *, skip_invalid: bool = False) -> list[dict]:
        root = self._root()
        result = []
        for path in sorted(root.glob(self.pattern.format(id='*'))):
            if path.is_symlink() or not path.is_file():
                if skip_invalid:
                    continue
                raise ValueError(f'Invalid JSON record path: {path.name}')
            try:
                value = json.loads(path.read_text())
                if not isinstance(value, dict):
                    raise ValueError('record must be an object')
                result.append(value)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                if not skip_invalid:
                    raise ValueError(f'Invalid JSON record: {path.name}') from exc
        return result

    def write(self, record_id: str, record: dict, *, replace: bool = True) -> dict:
        if not isinstance(record, dict):
            raise ValueError('JSON record must be an object')
        path = self.path(record_id)
        if replace:
            files.atomic_json(path, record)
        else:
            files.write_json_exclusive(path, record)
        return record
