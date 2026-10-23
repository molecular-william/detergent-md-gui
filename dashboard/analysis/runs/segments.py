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
from pathlib import Path

from . import layout

#: A protein-detergent run's own stages, in order. `structure` always names the stage's own output, so a picture and a
#: trajectory come from the same system; a stage with no trajectory still has its structure, which is the dry build.
PDC_STAGES = (
    ('System preparation', '1_system/system.gro', None, 'the built system, before solvation'),
    ('Energy minimisation', '2_minimisation/system.gro', ('2_minimisation/system.xtc',), None),
    ('NVT equilibration', '3_nvt/system.gro', ('3_nvt/system.xtc',), None),
    ('NPT equilibration', '4_npt/system.gro', ('4_npt/system.xtc',), None),
    ('CG assessment MD', '2_assessment/prod/run.gro',
     ('2_assessment/prod/whole.xtc', '2_assessment/prod/run.xtc'), 'PBC made whole where the stage wrote one'),
    ('CG extension MD', '4_extension/prod/run.gro',
     ('4_extension/prod/whole.xtc', '4_extension/prod/run.xtc'), 'the system rebuilt after the removal path'),
    # The final assessment reads the extension's own trajectory rather than writing a second one; it is listed so the
    # duplicate rule reports that fact instead of a reader discovering it as a film that plays the same frames twice.
    ('Final assessment', '5_assessment/prod/run.gro',
     ('5_assessment/prod/whole.xtc', '5_assessment/prod/run.xtc'), None),
)

SNIFF = 65536
#: The files that mark a run as protein-detergent rather than single-molecule.
PDC_MARKERS = ('4_extension', '2_assessment', '3_nvt')


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


def first(root: Path, names) -> Path | None:
    for name in names or ():
        found = present(root, name)
        if found is not None:
            return found
    return None


def is_pdc(root: Path) -> bool:
    """Whether a run keeps its stages the protein-detergent way, in either spelling a reader may be handed."""
    root = Path(root)
    return any((base / name).is_dir() for base in (root, root / layout.STAGES) for name in PDC_MARKERS)


def _relative(root: Path, path: Path) -> str:
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


def pdc_segments(root: Path) -> list[dict]:
    """The protein-detergent chain's trajectories, in stage order, with duplicates and merges made explicit."""
    root = Path(root)
    seen: dict[str, str] = {}
    group, previous_atoms = 0, None
    segments = []
    for name, structure_name, trajectory_names, note in PDC_STAGES:
        structure = present(root, structure_name)
        if structure is None:
            continue
        count = atoms(structure)
        trajectory = first(root, trajectory_names)
        entry = {'name': name, 'structure': _relative(root, structure), 'atoms': count,
                 'trajectory': None, 'role': 'pdc', 'group': None}
        if note:
            entry['note'] = note
        if trajectory is not None:
            # Every candidate this stage holds is registered, not only the one chosen to play: the final assessment
            # re-declares the extension's raw `run.xtc` while the extension itself plays its `whole.xtc`, so a rule
            # that compared chosen files would call that pair different and play the same frames twice.
            keys = {}
            for name_option in trajectory_names or ():
                candidate = present(root, name_option)
                if candidate is not None:
                    keys[identity(candidate)] = candidate
            duplicate = next((seen[key] for key in keys if key in seen), None)
            if duplicate is not None:
                entry.update({'duplicate_of': duplicate, 'trajectory': _relative(root, trajectory)})
                entry['note'] = f'not a segment: the same trajectory as {duplicate}'
                segments.append(entry)
                continue
            for key in keys:
                seen.setdefault(key, name)
            # A merge unit is the run of stages whose systems hold the same atoms: a player can concatenate inside one
            # and must switch structure and trajectory at a boundary.
            if count != previous_atoms:
                group += 1
            entry['trajectory'] = _relative(root, trajectory)
            entry['group'] = group
        segments.append(entry)
        previous_atoms = count if trajectory is not None else previous_atoms
    return segments


def single(root: Path) -> list[dict]:
    """A single-molecule run's one trajectory, in the same shape so a panel has one reader."""
    try:
        trajectory, structure, role = layout.frame_source(root)
    except layout.NoTrajectory:
        return []
    return [{'name': role, 'role': role, 'structure': _relative(Path(root), structure),
             'trajectory': _relative(Path(root), trajectory), 'atoms': atoms(structure), 'group': 1}]


def segments(root: Path, run_type: str | None = None) -> dict:
    """What a run offers to play: `{'run_type', 'segments', 'why'}`, with `why` stating an absence rather than raising."""
    root = Path(root)
    pdc = run_type == 'pdc' or is_pdc(root)
    found = pdc_segments(root) if pdc else single(root)
    answer = {'run_type': 'pdc' if pdc else (run_type or 'unknown'), 'segments': found}
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
