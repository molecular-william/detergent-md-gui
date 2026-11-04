"""A trajectory's frame count and its span, read from the file's header and never by walking it.

The Run view states, under the segment picker, how many frames a segment holds and how long it runs. The number has to
come from the trajectory's own header: reading every frame of a 1.7 GB `.xtc` costs about 43 s, and a panel that did
that would make selecting a segment a minute-long wait. The header is cheap -- measured 2026-11-04, a whole
`mda.Universe(structure, trajectory)` on the 45,001-frame extension took 0.045 s and seeking its last frame took
0.001 s -- so it is read per request and cached per process.

Two rules decide the shape:

**The span is last frame time minus first.** `6c36b3c610f3` writes 45,001 frames at 20 ps from 0.0 to 900,000 ps, so
the honest answer is 900 ns, not `frames × dt` (900.02 ns). GROMACS' own total time is the same subtraction.

**A run's stage files are immutable.** MDAnalysis writes its `*_offsets.npz` cache beside the path it is given, so the
trajectory is opened through a symlink in a temporary directory, exactly as the conformation library does. The
structure is only read, so it needs no such treatment.

A file whose header cannot be read answers `None` rather than raising: the route carries `null` and the panel says the
number is not recorded. This module is the route's reader; `analysis/runs/segments.py` describes which segments exist
and opens nothing.
"""

import math
import os
import tempfile
from pathlib import Path

#: One process asks for the same segment repeatedly -- two Run view monitors, a segment switched back and forth --
#: and the header does not change while a run's immutable trajectory sits on disk. The key carries each file's size
#: and modification time, so a replaced file is a new entry rather than a stale answer.
_CACHE: dict[tuple, dict | None] = {}
_CACHE_LIMIT = 32


def read(structure, trajectory) -> dict | None:
    """`{'frames': int, 'time_ns': float | None}`, or `None` when the header cannot be read.

    `frames` is the trajectory's own length. `time_ns` is the last frame's time minus the first, in ns, or `None` when
    the file states no finite time -- a `.pdb` trajectory need not. Neither answer walks a frame.
    """
    trajectory, structure = Path(trajectory), Path(structure) if structure else None
    key = _key(structure, trajectory)
    if key is not None and key in _CACHE:
        return dict(_CACHE[key]) if _CACHE[key] is not None else None
    try:
        answer = _read(structure, trajectory)
    except Exception:  # a header read is best-effort: any failure is "not recorded", never a failed request
        answer = None
    if key is not None:
        if len(_CACHE) >= _CACHE_LIMIT:
            _CACHE.clear()
        _CACHE[key] = answer
        return dict(answer) if answer is not None else None
    return answer


def _key(structure, trajectory):
    """`(path, size, mtime)` for both files, or `None` when either cannot be stated (an absent file is not cached)."""
    try:
        parts = []
        for path in (trajectory, structure):
            if path is None:
                parts.append(None)
                continue
            stat = path.stat()
            parts.append((str(path), stat.st_size, stat.st_mtime_ns))
        return tuple(parts)
    except OSError:
        return None


def _read(structure, trajectory):
    import MDAnalysis as mda

    if structure is None or not trajectory.is_file():
        return None
    with tempfile.TemporaryDirectory(prefix='trajectory-header-') as directory:
        link = Path(directory) / f'trajectory{trajectory.suffix or ".xtc"}'
        os.symlink(trajectory.resolve(), link)
        universe = mda.Universe(str(structure), str(link))
        frames = len(universe.trajectory)
        if frames < 1:
            return None
        universe.trajectory[0]
        first = float(universe.trajectory.ts.time)
        universe.trajectory[frames - 1]
        last = float(universe.trajectory.ts.time)
    if not (math.isfinite(first) and math.isfinite(last)):
        return {'frames': frames, 'time_ns': None}
    return {'frames': frames, 'time_ns': round((last - first) / 1000.0, 6) + 0.0}
