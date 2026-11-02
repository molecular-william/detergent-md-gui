"""Turning one source run's production trajectory into whole detergent molecules in their own local frame.

One sequential pass: read the trajectory once, make every detergent molecule whole, drop the ones a frame cannot
support, and give each survivor the frame the library stores. Nothing is kept but the molecules themselves, so an
18000-molecule pool costs a few tens of megabytes rather than a second copy of the trajectory.

Three things are read rather than assumed:

* **which atoms are a molecule**: the residue name the source run's geometry states, grouped by GROMACS' own residue
  number and ordered by the geometry's bead order. A bead the geometry names and the trajectory lacks is a refusal --
  the run is not the molecule the mapping describes.
* **where the molecule is**: a GROMACS trajectory writes each bead in the image it happens to occupy, so a molecule
  can be split across the periodic boundary. The itp's connectivity (bonds, constraints, virtual-site parents) is
  declared in the universe once, and each frame's fragments are made whole with MDAnalysis' own `make_whole`, which
  is the in-process equivalent of `gmx trjconv -pbc mol`.
* **whether the molecule is usable**: a non-finite bead drops it (`non_finite`), and so does a connectivity pair
  whose measured length leaves `[0.8, 1.2]` of the length the run's own topology states for it (`broken`). A pair
  the topology states no length for -- a virtual site's parents, a non-`funct 1` term -- is used for making the
  molecule whole but never measured, because its separation is derived rather than bonded. Those two are the only
  drops, and both are counted for the build record rather than hidden.

The reference length is the run's own `[ bonds ]`/`[ constraints ]` length, not the mapping-derived geometry: a
fitted topology's equilibrium need not equal the geometry's bead-centre distance, so a geometry reference drops
molecules for an ordinary bond fluctuation instead of for corruption. Measured on `b920391735dd`: its itp states
`2-5 = 0.334` while the geometry implies 0.2696, and 51.6% of that bond's samples sat above 1.2 of the geometry
value -- an ensemble filter, not a broken molecule. The system that was simulated is the authority for what its own
frames support.

The local frame is `pdc_placement.detergent_profile`'s: the head end is the head a placement already reads, and the
head-ward axis is the axis a placement already orients. `body_beads` puts the molecule at the origin with that axis
along +z, which is the one rotation `pdc_build.stamp` applies, so a stored entry can be stamped with no new
convention and every bead's z is zero or behind the head.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from detergent_pdc.execution.adapters import pdc_placement

#: The range a connectivity pair's measured length must keep, as a ratio to the geometry's own length.
BOND_RANGE = (0.8, 1.2)
#: MDAnalysis positions are ångström; a mapping's geometry is nanometres, which is the unit the builders use.
ANGSTROM_PER_NM = 10.0
#: Positions are stored to 1e-4 nm and descriptors to 1e-6 nm: the plan's rounding, kept here so two reads of one
#: trajectory produce the same bytes.
POSITION_DECIMALS = 4
DESCRIPTOR_DECIMALS = 6
#: How many frames one build reads. The production trajectory writes a frame every 2 ps -- 50,001 of them for a
#: 100 ns run, 150 detergent molecules each -- so reading them all would build 7.5 M candidates to choose K = 2000
#: from, and the per-molecule work is the whole cost. Sampling 200 frames at the trajectory's own stride is ~30,000
#: candidates, which is what the stratified selection is designed for, and it keeps the whole run's shapes rather
#: than the first few nanoseconds'.
#:
#: The stride -- `max(1, frames // MAX_FRAMES)` -- is recorded with each source, because `frames` alone does not say
#: which frames the pool came from and the document has to let a reader audit the selection. The library key is
#: derived from the run ids and trajectory identities only, so changing this number keeps the key: an existing valid
#: library whose bytes differ is then refused by `library.store` rather than silently replaced under a digest a run
#: may have pinned.
MAX_FRAMES = 200


def candidates(workspace, source):
    """One source run's whole molecules in canonical order, and the counts the build record reports.

    `counts` is `{'kept', 'broken', 'non_finite', 'frames', 'pool', 'stride'}`; `frames` is the number of frames
    the stride sampled, `stride` is that sampling step, and `pool` is every molecule those frames held, so
    `kept + broken + non_finite == pool`. `workspace` is the caller's store root and is not read: a source record
    already holds the resolved paths. The trajectory is opened inside a temporary directory so MDAnalysis' XTC
    offsets cache is created there, not beside the run's immutable stage files.
    """
    mda, make_whole = _mdanalysis()
    with tempfile.TemporaryDirectory(prefix='conformations-') as directory:
        universe, residues, fragments = _universe(mda, source, Path(directory))
        reference = _reference_lengths(source)
        stride = max(1, len(universe.trajectory) // MAX_FRAMES)
        counts = {'kept': 0, 'broken': 0, 'non_finite': 0, 'frames': 0, 'pool': 0, 'stride': stride}
        entries = []
        for timestep in universe.trajectory[::stride]:
            for fragment in fragments:
                # The detergent atoms are the only ones bonded, so each fragment is exactly one molecule.
                make_whole(fragment)
            positions = universe.atoms.positions
            time_ns = float(timestep.time) / 1000.0
            counts['frames'] += 1
            for resid, atoms in residues:
                counts['pool'] += 1
                points = positions[atoms] / ANGSTROM_PER_NM
                if not np.isfinite(points).all():
                    counts['non_finite'] += 1
                    continue
                if _broken(points, reference):
                    counts['broken'] += 1
                    continue
                entry = _entry(source, points, resid, time_ns)
                if entry is None:
                    counts['broken'] += 1
                    continue
                entries.append(entry)
                counts['kept'] += 1
    return entries, counts


def producer():
    """The versions a build record reports; not written into `library.json`, which has no timestamp or version."""
    mda, _make_whole = _mdanalysis()
    return {'numpy': np.__version__, 'mdanalysis': mda.__version__}


def _mdanalysis():
    try:
        import MDAnalysis
        from MDAnalysis.lib.mdamath import make_whole
    except ImportError as error:  # a build needs a trajectory reader; the message says so rather than failing obscurely
        raise RuntimeError('MDAnalysis is not installed; a conformation library cannot read a trajectory') from error
    return MDAnalysis, make_whole


def _universe(mda, source, directory):
    """The run's universe, its detergent residues in bead order, and one fragment per molecule.

    The trajectory is opened through a symlink in `directory`, not where the run keeps it: MDAnalysis writes its XTC
    frame offsets beside the path it is given, and a run's stage directory is immutable. The offsets therefore live
    in the build's own temporary directory, which goes away with the build. The structure is only ever read, so it
    needs no such treatment.

    The connectivity is declared before `fragments` is asked for: a `.gro` carries no bonds, so a molecule would
    otherwise be eleven single-atom fragments and none of them would be made whole.
    """
    structure = Path(source['structure_path']).resolve()
    trajectory = Path(source['trajectory_path'])
    link = Path(directory) / f'trajectory{trajectory.suffix or ".xtc"}'
    try:
        os.symlink(trajectory.resolve(), link)
    except OSError as error:
        raise ValueError(f'run {source["run_id"]}: {trajectory} cannot be linked into a temporary directory: '
                         f'{error}') from error
    try:
        universe = mda.Universe(str(structure), str(link))
    except (OSError, ValueError) as error:
        raise ValueError(f'run {source["run_id"]}: {trajectory} cannot be read: {error}') from error
    if len(universe.trajectory) < 1:
        raise ValueError(f'run {source["run_id"]}: {trajectory} holds no frames')
    universe.trajectory[0]
    if universe.dimensions is None or not (np.asarray(universe.dimensions[:3]) > 0).all():
        raise ValueError(f'run {source["run_id"]}: {trajectory.name} states no box, so a molecule split across the '
                         'periodic boundary cannot be made whole')
    atoms = universe.atoms
    detergent = np.asarray(atoms.resnames) == source['detergent']
    if not detergent.any():
        raise ValueError(f'run {source["run_id"]}: {structure.name} holds no {source["detergent"]} residue')
    residues = _residues(source, universe)
    pairs = [(int(selected[first]), int(selected[second]))
             for _resid, selected in residues for first, second, _length in source['bonds']]
    universe.add_bonds(pairs)
    return universe, residues, atoms[detergent].fragments


def _residues(source, universe):
    """`(resid, atom indices)` per detergent molecule, ascending by residue number, atoms in the geometry's order."""
    atoms = universe.atoms
    names = np.asarray(atoms.names, dtype=object)
    resids = np.asarray(atoms.resids, dtype=int)
    detergent = np.asarray(atoms.resnames, dtype=object) == source['detergent']
    wanted = [bead['name'] for bead in source['beads']]
    residues = []
    for resid in sorted({int(value) for value in resids[detergent]}):
        members = np.flatnonzero(detergent & (resids == resid))
        by_name = {}
        for atom in members:
            name = str(names[atom])
            if name in by_name:
                raise ValueError(f'run {source["run_id"]}: residue {resid} has two atoms named {name!r}')
            by_name[name] = int(atom)
        missing = [name for name in wanted if name not in by_name]
        unexpected = sorted(set(by_name) - set(wanted))
        if missing or unexpected:
            raise ValueError(f'run {source["run_id"]}: residue {resid} does not match its geometry '
                             f'(missing {missing}, unexpected {unexpected})')
        residues.append((resid, np.asarray([by_name[name] for name in wanted], dtype=int)))
    return residues


def _reference_lengths(source):
    """The pairs the run's topology states a length for, with that length: the reference the measured one is held to.

    A fitted topology's b0 is the length the simulation actually keeps, which need not be the mapping-derived
    geometry's bead-centre distance; see the module docstring. Pairs without a stated length are left out, so they
    make the molecule whole and are never measured.
    """
    return [(first, second, length) for first, second, length in source['bonds'] if length is not None]


def _broken(points, reference):
    """Whether any stated connectivity pair's measured length leaves `BOND_RANGE` of the topology's own length."""
    for first, second, length in reference:
        if length <= 1e-9:
            continue
        ratio = float(np.linalg.norm(points[first] - points[second])) / length
        if ratio < BOND_RANGE[0] or ratio > BOND_RANGE[1]:
            return True
    return False


def _entry(source, points, resid, time_ns):
    """One molecule in the library's local frame, rounded the way the document stores it, or `None`."""
    beads = [{'name': bead['name'], 'type': bead['type'], 'position': points[position].tolist()}
             for position, bead in enumerate(source['beads'])]
    profile = pdc_placement.detergent_profile(SimpleNamespace(beads=beads))
    if profile is None:
        return None
    offsets = pdc_placement.body_beads(np.zeros(3), np.array([0.0, 0.0, 1.0]), profile)
    if not np.isfinite(offsets).all():
        return None
    descriptor = _descriptors(offsets)
    return {'beads': [[_round(value, POSITION_DECIMALS) for value in point] for point in offsets],
            'descriptors': [_round(value, DESCRIPTOR_DECIMALS) for value in descriptor],
            'source': {'run': int(source['index']), 'time_ns': _round(time_ns, 6), 'resid': int(resid)}}


def _descriptors(offsets):
    """`length_nm`, `rg_nm`, `reach_nm`, `radial_nm`, in the plan's definitions, from the local-frame beads."""
    axial = offsets[:, 2]
    return [float(-axial.min()),
            float(np.sqrt((offsets * offsets).sum(axis=1).mean())),
            float(np.linalg.norm(offsets, axis=1).max()),
            float(np.hypot(offsets[:, 0], offsets[:, 1]).max())]


def _round(value, places):
    """A float rounded for storage, with negative zero folded to zero so two reads agree byte for byte."""
    return round(float(value), places) + 0.0
