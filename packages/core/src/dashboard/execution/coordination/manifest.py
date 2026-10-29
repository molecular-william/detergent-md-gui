"""Bounded manifest reads and run-contained stage log resolution."""
from __future__ import annotations

import json
from collections import OrderedDict
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


def stage_log_path(run_dir: Path, *, name: str | None = None, recorded: str | None = None,
                   resume_count=None) -> Path | None:
    """The one place a stage log's location is encoded and decoded.

    Writing: ``name`` is the stage's own directory, and ``resume_count`` puts a
    resumed attempt in ``logs/resume-NNNN/`` beside the earlier attempts.

    Reading: ``recorded`` is what the manifest holds. An absolute path is anchored
    on the run (so a moved workspace still resolves its own logs), and a path that
    leaves the run, is a symlink, or is not a file resolves to None rather than to
    something else's log.
    """
    run_dir = Path(run_dir)
    if recorded is None:
        if name is None:
            return None
        directory = run_dir / 'logs'
        if resume_count:
            directory = directory / f'resume-{int(resume_count):04d}'
        return directory / f'{Path(name).name}.log'
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
