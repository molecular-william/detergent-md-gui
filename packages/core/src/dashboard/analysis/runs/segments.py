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

#: A protein-detergent run's own stages, in order: `(human name, layout stage key, structure path inside the stage,
#: trajectory paths inside the stage, note)`. The stage key is looked up through `layout.PDC_STAGE_DIRECTORIES`, so
#: the numbered directories (`06_assessment`, `07_micelle_assessment`, `08_extension`, `09_final_assessment`,
#: `10_backmap`) and the legacy spellings (`2_assessment`, `3_assessment`, `4_extension`, `5_assessment`,
#: `6_backmap`) both resolve to the band below. `structure` always names the stage's own output, so a picture and a
#: trajectory come from the same system; a stage with no trajectory still has its structure, which is the dry build.
PDC_STAGES = (
    ('System preparation', 'system', 'system.gro', None, 'the built system, before solvation'),
    ('Energy minimisation', 'minimisation', 'system.gro', ('system.xtc',), None),
    ('NVT equilibration', 'nvt', 'system.gro', ('system.xtc',), None),
    ('NPT equilibration', 'npt', 'system.gro', ('system.xtc',), None),
    ('CG assessment MD', 'assessment', 'prod/run.gro',
     ('prod/whole.xtc', 'prod/run.xtc'), 'PBC made whole where the stage wrote one'),
    # The micelle assessment judges the phase's end state and writes the system it would keep; it has no
    # trajectory of its own, so it is a band with a structure and nothing to play.
    ('Micelle assessment', 'micelle_assessment', 'kept.gro', None,
     'the system the assessment would keep; no trajectory of its own'),
    ('CG extension MD', 'extension', 'prod/run.gro',
     ('prod/whole.xtc', 'prod/run.xtc'), 'the system rebuilt after the removal path'),
    # The final assessment reads the extension's own trajectory rather than writing a second one; it is listed so the
    # duplicate rule reports that fact instead of a reader discovering it as a film that plays the same frames twice.
    ('Final assessment', 'final_assessment', 'prod/run.gro',
     ('prod/whole.xtc', 'prod/run.xtc'), None),
    # The back-map converts the coarse-grained complex back to an atomistic one; it holds a structure and no
    # trajectory, so it is a band with nothing to play rather than a stage that went missing.
    ('Back-mapping (CG2AT2)', 'backmap',
     ('FINAL/FINAL/final_cg2at_neutral.pdb', 'FINAL/FINAL/final_cg2at_de_novo.pdb'), None,
     'the atomistic complex converted back from the CG one'),
)

#: The stages the Run view's one timed reel covers, in order: the equilibration legs then the two production stages.
#: The final assessment is excluded because it re-declares the extension's trajectory. The producer samples every
#: stage that actually holds a trajectory and skips the rest (this pipeline's minimisation writes none), so the
#: timeline's span is the run's own rather than a second list copied into another module.
PDC_TIMELINE_STAGES = ('Energy minimisation', 'NVT equilibration', 'NPT equilibration',
                       'CG assessment MD', 'CG extension MD')

SNIFF = 65536
#: The files that mark a run as protein-detergent rather than single-molecule: the numbered layout, then the legacy
#: one. `04_nvt` alone is not a marker -- an AA-only run's numbered stages include `04_nvt` too -- so the markers are
#: directories only a pdc run writes.
PDC_MARKERS = ('08_extension', '06_assessment', '02_system', '03_minimisation', '07_micelle_assessment',
               '09_final_assessment', '10_backmap', '4_extension', '2_assessment', '3_nvt', '1_system')


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


def _stage_path(root: Path, stage: str, names):
    """One file inside a pdc stage, trying every spelling of the stage directory and each candidate name."""
    for name in ((names,) if isinstance(names, str) else names or ()):
        found = layout.pdc_stage_path(root, stage, name)
        if found is not None:
            return found
    return None


def pdc_segments(root: Path) -> list[dict]:
    """The protein-detergent chain's trajectories, in stage order, with duplicates and merges made explicit.

    A stage is looked up through `layout.PDC_STAGE_DIRECTORIES`, so a numbered `07_extension/` and a legacy
    `4_extension/` are the same band. A stage the manifest records as skipped is listed with its reason instead of
    being dropped: it has no directory, and "the run decided not to run this" is not the same as "it is missing".
    """
    root = Path(root)
    skipped = skipped_stages(root)
    seen: dict[str, str] = {}
    group, previous_atoms = 0, None
    segments = []
    for name, stage, structure_name, trajectory_names, note in PDC_STAGES:
        structure = _stage_path(root, stage, structure_name)
        reason = skipped.get(name)
        if structure is None:
            if reason is not None:
                segments.append({'name': name, 'structure': None, 'atoms': None, 'trajectory': None,
                                 'role': 'pdc', 'group': None, 'skipped': reason,
                                 'note': f'skipped: {reason}'})
            continue
        count = atoms(structure)
        trajectory = _stage_path(root, stage, trajectory_names)
        entry = {'name': name, 'structure': _relative(root, structure), 'atoms': count,
                 'trajectory': None, 'role': 'pdc', 'group': None}
        if note:
            entry['note'] = note
        if reason is not None:
            entry['skipped'] = reason
        if trajectory is not None:
            # Every candidate this stage holds is registered, not only the one chosen to play: the final assessment
            # re-declares the extension's raw `run.xtc` while the extension itself plays its `whole.xtc`, so a rule
            # that compared chosen files would call that pair different and play the same frames twice.
            keys = {}
            for name_option in trajectory_names or ():
                candidate = layout.pdc_stage_path(root, stage, name_option)
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
