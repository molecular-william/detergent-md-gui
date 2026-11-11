"""A fixture run tree for the conformation library: a completed, protein-free pdc run with a real tiny trajectory.

The library's tests need a pdc run that states a detergent model and a production trajectory, and they need it under
`tmp_path`: never the developer's workspace, and never a whole 2 GB trajectory to read. This file holds the
construction -- the DDM mapping's own eleven beads and connectivity, the run tree, and an `.xtc` written with
MDAnalysis -- so a test varies only what it means (the status, the residue, the mapping digest, a broken molecule, a
non-finite one) and keeps its own assertions.

The geometry is the reference mapping's, in nanometres, and the connectivity is what the itp the build writes states:
`[ bonds ]`, the ring `[ constraints ]` and the `[ virtual_sitesn ]` parents. A molecule is placed so that one copy
crosses the periodic boundary, which is the case the extraction's `make_whole` exists for.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import MDAnalysis as mda
import numpy as np
from detergent_pdc.conformations.sources import GEOMETRY, MANIFEST, TOPOLOGY

RESIDUE = 'DDM'
MAPPING_SHA256 = 'c7cf9780a818045cb11c6fbe964def96d20721fef06551756104b24c6b96728f'
#: The reference DDM mapping's own beads, in the mapping's order, as `(name, type, position in nm)`.
BEADS = (
    ('S1A', 'SP1r', (0.168, -0.00475, -0.24475)),
    ('S1B', 'SP1r', (0.2665, -0.30275, -0.25125)),
    ('S1C', 'SP1r', (0.16975, -0.2635, 0.0245)),
    ('S1VS', 'TC4', (0.201417, -0.190333, -0.157167)),
    ('S2A', 'SN6', (0.328, -0.558667, -0.309667)),
    ('S2B', 'SP4r', (0.27875, -0.8025, -0.18825)),
    ('S2C', 'SP1r', (0.39475, -0.66825, 0.045)),
    ('S2VS', 'TC4', (0.333833, -0.676472, -0.150972)),
    ('TAIL1', 'C1', (-0.56225, 0.70975, 0.45525)),
    ('TAIL2', 'C1', (-0.41125, 0.464, 0.174)),
    ('TAIL3', 'C1', (-0.0545, 0.29475, -0.03225)),
)
#: One molecule's connectivity, 1-based into `BEADS`, exactly as the build's itp states it.
BONDS = ((1, 11), (2, 5), (9, 10), (10, 11))
CONSTRAINTS = ((1, 2), (1, 3), (2, 3), (5, 6), (5, 7), (6, 7))
VIRTUAL_SITES = ((4, (1, 2, 3)), (8, (5, 6, 7)))
#: The stage the assessment leg writes, the one `detergent_pdc.segments` names `CG assessment MD`.
STAGE = '06_assessment'
#: The fixture box's edge in nm: molecule 0 crosses a face of it, so making it whole is the extraction's job.
BOX_NM = 6.0


def beads_for(residue=RESIDUE):
    """The mapping's beads in a geometry document's shape: name, type, position, residue, virtual-site flag."""
    virtual = {site for site, _parents in VIRTUAL_SITES}
    return [{'name': name, 'type': kind, 'position': list(position), 'residue': residue,
             'virtual_site': index + 1 in virtual}
            for index, (name, kind, position) in enumerate(BEADS)]


def itp_text(residue=RESIDUE, overrides=None):
    """A moleculetype stating the atoms, the bonds, the ring constraints and the virtual sites the geometry has.

    A `funct 1` bond or constraint states the geometry's own pair length, so the fixture is self-consistent with the
    trajectory it writes. `overrides` replaces one pair's stated length (`{(first, second): length}`, 1-based), which
    is how a test moves the reference away from the geometry.
    """
    stated = {**pair_lengths(), **(overrides or {})}
    lines = ['[ moleculetype ]', f'{residue} 1', '', '[ atoms ]']
    for index, (name, kind, _position) in enumerate(BEADS, start=1):
        lines.append(f' {index:2d} {kind} 1 {residue} {name} {index} 0.0 54.0')
    lines += ['', '[ bonds ]']
    lines += [f' {first} {second} 1 {stated[(first, second)]:.4f} 2000.0' for first, second in BONDS]
    lines += ['', '[ constraints ]']
    lines += [f' {first} {second} 1 {stated[(first, second)]:.4f}' for first, second in CONSTRAINTS]
    lines += ['', '[ virtual_sitesn ]']
    lines += [f' {site} 1 {" ".join(str(parent) for parent in parents)}' for site, parents in VIRTUAL_SITES]
    return '\n'.join(lines) + '\n'


def pair_lengths():
    """Each bonded pair's own length in the fixture geometry, in nm, 1-based as the itp spells the pairs."""
    points = np.asarray([position for _name, _kind, position in BEADS], dtype=float)
    return {(first, second): float(np.linalg.norm(points[first - 1] - points[second - 1]))
            for first, second in (*BONDS, *CONSTRAINTS)}


def run_tree(workspace, run_id='b920391735dd', *, status='completed', run_type='pdc', protein='',
             residue=RESIDUE, mapping_sha256=MAPPING_SHA256, molecules=4, frames=2, boxed=True,
             broken_molecule=None, omit=()):
    """Write one run tree under `<workspace>/runs/<run_id>` and return its paths and record.

    `omit` names what a caller wants missing or unreadable: `manifest`, `mapping`, `geometry`, `topology` or
    `trajectory`. `broken_molecule` moves one molecule's first bead 0.3 nm off its geometry, which is one of the two
    ways the extraction drops a molecule. The other, a non-finite bead, cannot be written into an `.xtc` -- the
    format's fixed-point compression has no representation for it -- so a test that needs one injects it at
    `extract.candidates`' entry, as a corrupt frame would. `boxed=False` writes a zero box, which is how a trajectory
    with no box reads back.
    """
    workspace = Path(workspace)
    run = workspace / 'runs' / run_id
    inputs = run / 'inputs'
    inputs.mkdir(parents=True, exist_ok=True)
    if 'mapping' not in omit:
        manifest = {'id': run_id, 'status': status, 'run_type': run_type, 'protein': protein,
                    'inputs': [{'role': 'mapping', 'label': 'mapping_candidate.json', 'kind': 'store',
                                'root': 'workspace', 'path': 'mapping_drafts/mapping_candidate.json',
                                'sha256': mapping_sha256, 'bytes': 1}],
                    'skipped_stages': {}}
    else:
        manifest = {'id': run_id, 'status': status, 'run_type': run_type, 'protein': protein,
                    'inputs': [], 'skipped_stages': {}}
    if 'manifest' not in omit:
        (run / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True))
    if 'geometry' not in omit:
        (inputs / GEOMETRY).write_text(json.dumps(
            {'molecule_id': 'lig1', 'residue': residue, 'beads': beads_for(residue)}, indent=2, sort_keys=True))
    if 'topology' not in omit:
        (inputs / TOPOLOGY).write_text(itp_text(residue))
    stage = run / 'stages' / STAGE / 'prod'
    stage.mkdir(parents=True, exist_ok=True)
    write_trajectory(stage / 'run.gro', stage / 'whole.xtc', residue=residue, molecules=molecules, frames=frames,
                     boxed=boxed, broken_molecule=broken_molecule,
                     with_frames='trajectory' not in omit)
    return {'run_id': run_id, 'run': run, 'stage_root': run / 'stages', 'inputs': inputs,
            'structure': stage / 'run.gro', 'trajectory': stage / 'whole.xtc', 'beads': beads_for(residue),
            'manifest': manifest, 'molecules': molecules, 'frames': frames}


def write_trajectory(structure, path, *, residue=RESIDUE, molecules=4, frames=2, boxed=True,
                     broken_molecule=None, with_frames=True):
    """A `.gro` and a real `.xtc` of `molecules` rigid detergent copies, one of them split across the boundary.

    Molecule 0 is placed so its own beads cross the periodic boundary: the trajectory holds the wrapped positions,
    which is what GROMACS writes, so making it whole is the extraction's job and not the fixture's.
    """
    geometry = np.asarray([position for _name, _kind, position in BEADS], dtype=float)
    width = len(geometry)
    universe = mda.Universe.empty(molecules * width, n_residues=molecules,
                                  atom_resindex=np.repeat(np.arange(molecules), width), trajectory=True)
    for attribute in ('names', 'resnames', 'resids'):
        universe.add_TopologyAttr(attribute)
    universe.atoms.names = [name for _index in range(molecules) for name, _kind, _position in BEADS]
    universe.atoms.residues.resnames = [residue] * molecules
    universe.atoms.residues.resids = np.arange(1, molecules + 1)
    box = np.full(3, BOX_NM * 10.0)  # ångström: MDAnalysis' own unit
    positions = np.zeros((molecules * width, 3))
    for molecule in range(molecules):
        start = molecule * width
        turned = geometry @ _rotation(molecule).T
        placed = turned * 10.0 + _base(molecule, BOX_NM) * 10.0
        positions[start:start + width] = placed % box if boxed else placed
    dimensions = [*box, 90.0, 90.0, 90.0] if boxed else [0.0, 0.0, 0.0, 90.0, 90.0, 90.0]
    if broken_molecule is not None:
        positions[broken_molecule * width] += np.array([3.0, 0.0, 0.0])
    universe.atoms.positions = positions
    universe.trajectory.ts.dimensions = dimensions
    universe.atoms.write(str(structure))
    if not with_frames:
        return universe
    with mda.Writer(str(path), universe.atoms.n_atoms) as writer:
        for frame in range(frames):
            frame_positions = positions + np.array([0.0, 0.5 * frame, 0.0])
            universe.atoms.positions = frame_positions % box if boxed else frame_positions
            universe.trajectory.ts.dimensions = dimensions
            universe.trajectory.ts.time = 100.0 * frame  # ps, one written frame per 0.1 ns
            writer.write(universe.atoms)
    return universe


def _rotation(molecule):
    """A deterministic rotation per molecule: the identity for the first, a turn about z for the rest."""
    if molecule == 0:
        return np.eye(3)
    angle = 0.7 * molecule
    cosine, sine = np.cos(angle), np.sin(angle)
    return np.array([[cosine, -sine, 0.0], [sine, cosine, 0.0], [0.0, 0.0, 1.0]])


def _base(molecule, box_nm):
    """A molecule's own place in nm: molecule 0 crosses a box face, the rest sit on a grid away from it."""
    if molecule == 0:
        return np.array([box_nm - 0.2, 1.0, 1.0])
    return np.array([0.6 + 1.4 * (molecule % 3), 0.6 + 1.4 * ((molecule // 3) % 3), 2.4])


def copy_libraries(source, target):
    """Copy every stored library directory from one workspace to another; returns the copied directories.

    A copied directory is how a library moves between workspaces, so the tests use the same operation an operator
    does rather than rebuilding on the far side.
    """
    root = Path(source) / 'conformations'
    copied = []
    for directory in sorted(root.glob('*/*')):
        if not directory.is_dir():
            continue
        destination = Path(target) / 'conformations' / directory.parent.name / directory.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(directory, destination)
        copied.append(destination)
    return copied
