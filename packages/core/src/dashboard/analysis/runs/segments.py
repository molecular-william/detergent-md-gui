"""The trajectory a run offers, as ordered **segments** rather than one file.

A single-molecule run has one trajectory. A protein-detergent run has several, because its system is rebuilt mid-run: the
removal path takes detergents out of the micelle and re-solvates what is left, so the atom count changes and the legs on
either side of that boundary are not the same system. Measured on `00b9ae6db23f`:

    System preparation        1_system/system.gro                     2,248 atoms, no trajectory (the dry build)
    minimisation -> NVT ->    2_minimisation, 3_nvt, 4_npt,            11,708 atoms, one system: these four
      NPT -> CG assessment     2_assessment/prod                        concatenate cleanly
    CG extension              eq.xtc, prod/run.xtc                     10,427 atoms: detergents removed
    final assessment          a copy of the extension's trajectory      never a segment of its own

So "merge the stages" has a precise answer: legs with the same atom count and order merge, and a boundary is where the
count changes. This module reports that structure -- `group` is the merge unit -- instead of pretending one file can hold
the whole run, and it drops a trajectory that is byte-for-byte another segment's copy (`5_assessment` re-declares the
extension's) so a film does not play the same nanometres twice.

Nothing here opens a trajectory: `frames` is not claimed, because counting frames in a compressed xtc means walking the
whole file (43 s for 2.6 GB through `gmx check`). The panels read frame times from the loaded file, which is where the
viewer already has them.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import layout

#: `{run type: (root) -> [segment dicts]}` and the directories that mark a run of that type on disk, registered by a
#: feature. The engine answers a single-molecule run itself.
_SEGMENTERS: dict[str, object] = {}
_MARKERS: list[tuple[str, tuple[str, ...]]] = []


def register(segmenters=None, markers=()):
    """Add a feature's segmenter and the directories that identify its runs when the record names no type."""
    _SEGMENTERS.update(segmenters or {})
    for run_type, names in markers:
        _MARKERS.append((run_type, tuple(names)))


SNIFF = 65536


def atoms(structure: Path) -> int | None:
    """The atom count a `.gro` states on its own second line, or `None` when the file is not a gro."""
    try:
        with structure.open() as handle:
            handle.readline()
            line = handle.readline().strip()
    except OSError:
        return None
    return int(line) if line.isdigit() else None


def identity(path: Path) -> str:
    """What makes two trajectories the same *content*, cheaply: size, first 64 KiB and last 64 KiB.

    A copy is a different file with a different mtime, so neither name nor timestamp answers "did I already show this?".
    Hashing the ends is what a re-declared trajectory fails -- and a genuinely different trajectory cannot pass it without
    agreeing on its size to the byte.
    """
    size = path.stat().st_size
    digest = hashlib.sha256(str(size).encode())
    with path.open('rb') as handle:
        digest.update(handle.read(SNIFF))
        if size > SNIFF:
            handle.seek(max(SNIFF, size - SNIFF))
            digest.update(handle.read(SNIFF))
    return digest.hexdigest()


def present(root: Path, relative: str) -> Path | None:
    """A path as the execution root spells it: at the root, or under `stages/` (see `layout`)."""
    for spelling in layout._spellings(Path(root), Path(relative)):
        if spelling.is_file():
            return spelling
    return None


def relative(root: Path, path: Path) -> str:
    """The run-relative spelling of a resolved path, which is what the artifact route takes.

    `stages/` is tried first: a run on disk keeps its stages under it, and a path under `stages/` would otherwise be
    reported with that prefix -- which the artifact route resolves against the run root and would not find.
    """
    root = Path(root)
    for base in (root / layout.STAGES, root):
        try:
            return path.relative_to(base).as_posix()
        except ValueError:
            continue
    return path.as_posix()


def _manifest(root: Path) -> dict:
    """The run's manifest, from the directory a reader was handed or from the run above its `stages/`."""
    root = Path(root)
    candidates = [root / 'manifest.json']
    if root.name == layout.STAGES:
        candidates.append(root.parent / 'manifest.json')
    for path in candidates:
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    return {}


def skipped_stages(root: Path) -> dict:
    """The stages the run's own prepare decided will not run, as `{stage name: reason}`.

    A skipped stage writes no directory and no `skip.json`, so the manifest's `skipped_stages` is the only place it
    is recorded. A reader that ignored it would show the stage as missing -- which is a different fact from "the
    run decided not to do this, because ...".
    """
    skipped = _manifest(root).get('skipped_stages')
    return {str(name): str(reason) for name, reason in skipped.items()} if isinstance(skipped, dict) else {}


def single(root: Path) -> list[dict]:
    """A single-molecule run's one trajectory, in the same shape so a panel has one reader."""
    try:
        trajectory, structure, role = layout.frame_source(root)
    except layout.NoTrajectory:
        return []
    return [{'name': role, 'role': role, 'structure': relative(Path(root), structure),
             'trajectory': relative(Path(root), trajectory), 'atoms': atoms(structure), 'group': 1}]


def segments(root: Path, run_type: str | None = None) -> dict:
    """What a run offers to play: `{'run_type', 'segments', 'why'}`, with `why` stating an absence rather than raising."""
    from ... import features

    features.ensure()
    root = Path(root)
    segmenter, kind = None, run_type
    if run_type in _SEGMENTERS:
        segmenter = _SEGMENTERS[run_type]
    else:
        for candidate, names in _MARKERS:
            if any((base / name).is_dir() for base in (root, root / layout.STAGES) for name in names):
                segmenter, kind = _SEGMENTERS[candidate], candidate
                break
    found = segmenter(root) if segmenter is not None else single(root)
    answer = {'run_type': kind or 'unknown', 'segments': found}
    playable = [entry for entry in found if entry.get('trajectory') and 'duplicate_of' not in entry]
    if not playable:
        answer['why'] = ('this run offers no trajectory to play: its stages hold no .xtc'
                         if found else 'this run offers no trajectory to play: no stage directory holds one')
    else:
        answer['why'] = None
        boundaries = [(entry['name'], previous['name'], previous.get('atoms'), entry.get('atoms'))
                      for previous, entry in zip(playable, playable[1:]) if entry['group'] != previous['group']]
        if boundaries:
            answer['boundaries'] = [{'at': name, 'after': after, 'atoms_from': before_atoms, 'atoms_to': atoms}
                                    for name, after, before_atoms, atoms in boundaries]
    return answer
