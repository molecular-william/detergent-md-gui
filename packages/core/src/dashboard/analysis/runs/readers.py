"""The file readers every analysis over a run shares.

One work tree is read by more than one analysis: the frame stride, the staged trajectory and the structure beside
it, the run manifest and the average-free XVG columns were each re-derived by a feature before this module. The
readers live here so the rule -- and the errors a caller reports -- is stated once, and a feature imports it instead
of restating it.
"""
from __future__ import annotations

import json
import math
from array import array
from pathlib import Path

import numpy as np

#: The most frames one analysis samples. A 900 ns CG leg writes 45,000 frames; 200 keeps a pass short while still
#: showing the shape of the series.
MAX_FRAMES = 200

#: The structure names a stage writes beside its trajectory, preferred in this order. A leg may also leave an
#: equilibrium gro; `run.gro` is the one its production leg wrote.
PREFERRED_STRUCTURES = ('run.gro', 'system.gro')


class MissingTrajectory(LookupError):
    """The work tree stages no trajectory a reader could open."""


class MissingStructure(LookupError):
    """The chosen trajectory has no structure beside it; `trajectory` is the file the reader looked beside."""

    def __init__(self, trajectory: Path):
        self.trajectory = trajectory
        super().__init__(f'no structure beside {trajectory}')


def xvg_columns(path):
    """One XVG file's column labels, time column and data columns, in the file's own order.

    `gmx energy` writes its columns in the energy file's own term order, not in the order they were selected -- a
    request for Temperature, Pressure, Potential came back as Potential, Temperature, Pressure -- so a reader that
    trusted the request order would label every curve with the term next to it. A column without a legend is named
    positionally rather than dropped.

    The data block is parsed by numpy, not by a Python loop: an all-term EDR XVG is up to ~100,000 rows by 46 columns
    (measured 59 MB from a 62 MB `.edr`), and the per-line float conversion cost 1.33 s of a 7.5 s energy read. A
    ragged or malformed file falls back to that per-line reader, which is the authority on what a row means.
    """
    table = _xvg_table(path)
    if table is None:
        labels, times, columns = _xvg_columns_slow(path)
    else:
        labels = _xvg_legends(path)
        times, columns = _xvg_columns(table)
    # A hand-written XVG may carry data without legends; name those columns positionally rather than dropping them.
    while len(labels) < len(columns):
        labels.append(f'column{len(labels) + 2}')
    return labels, times, columns


def _xvg_legends(path):
    """Every `@ s ... legend "name"` line above the data block's first row, in file order.

    Legends stand above the data in every XVG GROMACS writes, so this stops at the first row: reading a 59 MB data
    block twice to collect a few dozen names is the one cost the fast path must not reintroduce. A file that puts a
    legend below the data is outside that contract; its columns are named positionally rather than guessed at.
    """
    labels = []
    with Path(path).open() as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            if line.startswith('@ s') and 'legend' in line:
                labels.append(line.split('legend', 1)[1].strip().strip('"'))
                continue
            if not line.startswith(('#', '@')):
                break
    return labels


def _xvg_table(path):
    """The numeric block as one float array, or `None` when numpy refuses it and the per-line reader must answer.

    The rows are filtered by their first character rather than handed `comments=`, because an XVG's comments are
    `#` and `@` and `np.loadtxt` takes one comment character; `comments=None` then means every row that reaches it is
    data. A file whose rows disagree on their column count raises `ValueError`, which is the fallback's call.
    """
    try:
        with Path(path).open() as handle:
            rows = (line for line in handle if line.strip() and line[:1] not in ('#', '@'))
            table = np.loadtxt(rows, dtype=float, ndmin=2, comments=None)
    except (ValueError, OSError):
        return None
    if table.size == 0 or table.ndim != 2 or table.shape[1] < 2:
        return None
    return table


def _xvg_columns(table):
    """`(times, columns)` as `array('d')`s from the parsed table; a column without a legend keeps its position."""
    times = array('d', table[:, 0])
    columns = [array('d', table[:, index]) for index in range(1, table.shape[1])]
    return times, columns


def _xvg_columns_slow(path):
    """The per-line reader: the same table, one Python float per cell, for a file numpy will not take.

    A malformed row is skipped and a row shorter than the first one's column count is skipped rather than indexed
    past its end, so a hand-written XVG with a short line still reads.
    """
    labels, times, columns = [], array('d'), []
    with Path(path).open() as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith(('#', '@')):
                if line.startswith('@ s') and 'legend' in line:
                    labels.append(line.split('legend', 1)[1].strip().strip('"'))
                continue
            try:
                values = [float(value) for value in line.split()]
            except ValueError:
                continue
            if len(values) < 2:
                continue
            if not columns:
                columns = [array('d') for _ in range(len(values) - 1)]
            if len(values) < len(columns) + 1:
                continue
            times.append(values[0])
            for index, column in enumerate(columns):
                column.append(values[index + 1])
    while len(labels) < len(columns):
        labels.append(f'column{len(labels) + 2}')
    return labels, times, columns



def frame_stride(frames_in_file, max_frames=MAX_FRAMES) -> int:
    """One frame in every `stride`, at most `max_frames` frames; a file with no frames is refused."""
    frames_in_file = int(frames_in_file)
    if frames_in_file < 1:
        raise ValueError('a trajectory with no frames has nothing to sample')
    return max(1, math.ceil(frames_in_file / int(max_frames)))


def minimum_image(delta, box):
    """Fold a displacement into the periodic cell: the shortest vector between two equivalent positions."""
    return delta - np.round(delta / box) * box


def chosen_trajectory(work, *, exclude=()):
    """The largest staged `.xtc` and the structure beside it, or the named refusal.

    `exclude` names files the work tree holds that are not the leg's own trajectory -- a sample a previous pass
    wrote, for instance. `MissingTrajectory` is raised when no candidate exists, `MissingStructure` when the
    chosen one has no `.gro` beside it; callers translate each into the vocabulary they report in.
    """
    excluded = set(exclude)
    work = Path(work)
    found = [path for path in work.rglob('*.xtc') if path.is_file() and path.name not in excluded]
    if not found:
        raise MissingTrajectory(f'{work} stages no trajectory')
    trajectory = max(found, key=lambda path: (path.stat().st_size, str(path)))
    directory = trajectory.parent
    structures_found = sorted(path for path in directory.glob('*.gro') if path.is_file())
    if not structures_found:
        raise MissingStructure(trajectory)
    preferred = [path for path in structures_found if path.name in PREFERRED_STRUCTURES]
    return trajectory, (preferred or structures_found)[0]


def run_manifest(root: Path) -> dict:
    """The run's manifest, from the directory a reader was handed or from the run above its `stages/`."""
    root = Path(root)
    candidates = [root / 'manifest.json']
    if root.name == 'stages':
        candidates.append(root.parent / 'manifest.json')
    for path in candidates:
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    return {}
