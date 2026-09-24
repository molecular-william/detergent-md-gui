"""Bounded manifest reads and run-contained stage log resolution."""
from __future__ import annotations

from collections import OrderedDict
import json
from pathlib import Path


class ManifestCache:
    def __init__(self, capacity: int = 256):
        self.capacity = capacity
        self._store = OrderedDict()

    def read(self, path: Path) -> dict:
        path = Path(path)
        key = str(path)
        try:
            stat = path.stat()
        except OSError:
            self._store.pop(key, None)
            return {}
        entry = self._store.get(key)
        if entry and entry[:2] == (stat.st_mtime_ns, stat.st_size):
            self._store.move_to_end(key)
            return entry[2]
        try:
            value = json.loads(path.read_text())
            data = value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            data = {}
        self._store[key] = (stat.st_mtime_ns, stat.st_size, data)
        self._store.move_to_end(key)
        while len(self._store) > self.capacity:
            self._store.popitem(last=False)
        return data


def read_manifest(run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    manifest = run_dir / 'manifest.json'
    if manifest.is_symlink() or not manifest.resolve().is_relative_to(run_dir.resolve()):
        return {}
    try:
        value = json.loads(manifest.read_text())
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def stage_log_path(run_dir: Path, recorded: str) -> Path | None:
    run_dir = Path(run_dir)
    path = Path(recorded)
    if path.is_absolute():
        parts = path.parts
        run_id = run_dir.name
        anchors = [index for index in range(len(parts) - 1) if parts[index:index + 2] == ('runs', run_id)]
        if not anchors:
            return None
        path = Path(*parts[anchors[-1] + 2:])
    candidate = run_dir / path
    try:
        contained = candidate.resolve().is_relative_to(run_dir.resolve())
    except OSError:
        return None
    if candidate.is_symlink() or not contained or not candidate.is_file():
        return None
    return candidate
