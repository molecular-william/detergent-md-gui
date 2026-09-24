"""Map physical COGs plus ring virtual sites; keep raw and expanded frames separate.

The COG helpers are inlined rather than imported from the dashboard package so
the run-local script remains a self-contained two-file artifact (it still needs
only its own directory and the shared AA reference directory).
"""
import itertools
import json
import os
from pathlib import Path
import numpy as np
import MDAnalysis as mda


def coordinates(data, positions, atom_ids=None, scaled=False):
    ids = atom_ids if atom_ids is not None else range(1, len(positions) + 1)
    lookup = dict(zip(ids, positions))
    beads = data['beads']; names = {b['name']: i for i, b in enumerate(beads)}
    xyz = np.zeros((len(beads), 3))
    for i, b in enumerate(beads):
        if not b.get('virtual_site'):
            xyz[i] = np.mean([lookup[a] for a in b['atoms']], axis=0)
    raw = xyz.copy()
    if scaled:
        for r in data.get('rings', []):
            idx = [names[n] for n in r['beads']]; center = raw[idx].mean(axis=0)
            xyz[idx] = center + r['scale'] * (raw[idx] - center)
    if scaled and data.get('connections'):
        components = [[names[n] for n in r['beads']] for r in data.get('rings', [])]
        grouped = {i for group in components for i in group}
        components += [[i] for i, b in enumerate(beads) if i not in grouped and not b.get('virtual_site')]
        comp = {i: ci for ci, group in enumerate(components) for i in group}
        links = {ci: [] for ci in range(len(components))}
        for a, b in data['connections']:
            i, j = names[a], names[b]
            if comp[i] != comp[j]:
                links[comp[i]].append((comp[j], i, j)); links[comp[j]].append((comp[i], j, i))
        seen = set()
        def place(ci, parent=None):
            seen.add(ci)
            for other, i, j in links[ci]:
                if other == parent: continue
                if other in seen: raise ValueError('Cyclic inter-ring links need constrained coordinate reconstruction')
                delta = xyz[i] + raw[j] - raw[i] - xyz[j]
                xyz[components[other]] += delta
                place(other, ci)
        for ci in links:
            if ci not in seen: place(ci)
    for i, b in enumerate(beads):
        if b.get('virtual_site'):
            xyz[i] = xyz[[names[n] for n in b['virtual_site']['parents']]].mean(axis=0)
    return xyz


def ring_pairs(data):
    names = {b['name']: i + 1 for i, b in enumerate(data['beads'])}
    return {tuple(sorted((names[a], names[b]))): r['scale']
            for r in data.get('rings', []) for a, b in itertools.combinations(r['beads'], 2)}


model = json.loads(Path('model.json').read_text())
aa_source = Path(os.environ.get('AA_REFERENCE_DIR', '../1_AA-reference/prod'))
aa = mda.Universe(str(aa_source / 'lig.gro'), str(aa_source / 'lig.xtc'))
names = [b['export_name'] for b in model['beads']]
cg = mda.Universe.empty(len(names), n_residues=1, atom_resindex=np.zeros(len(names), dtype=int), trajectory=True)
cg_resname = os.environ.get('MOLECULE_TYPE', 'DDM')
cg.add_TopologyAttr('names', names); cg.add_TopologyAttr('resnames', [cg_resname]); cg.add_TopologyAttr('resids', [1])
for file in ('mapped.xtc', 'mapped.gro', 'mapped_scaled.xtc', 'mapped_scaled.gro', 'ring_targets.json'):
    if Path(file).exists(): raise FileExistsError(file)
sums = {pair: 0.0 for pair in ring_pairs(model)}
previous = None
with mda.Writer('mapped.xtc', n_atoms=len(names)) as writer, mda.Writer('mapped_scaled.xtc', n_atoms=len(names)) as scaled_writer:
    for index, frame in enumerate(aa.trajectory):
        if previous is not None and frame.time <= previous: raise ValueError('AA times must increase')
        previous = frame.time
        raw = coordinates(model, frame.positions)
        if not np.isfinite(raw).all(): raise ValueError('Nonfinite mapped coordinates')
        cg.atoms.positions = raw; cg.dimensions = frame.dimensions
        cg.trajectory.ts.time = frame.time
        writer.write(cg.atoms)
        if index == 0: cg.atoms.write('mapped.gro')
        for a, b in sums: sums[(a, b)] += np.linalg.norm(raw[a - 1] - raw[b - 1]) / 10
        cg.atoms.positions = coordinates(model, frame.positions, scaled=True)
        scaled_writer.write(cg.atoms)
        if index == 0: cg.atoms.write('mapped_scaled.gro')
frames = len(aa.trajectory)
Path('ring_targets.json').write_text(json.dumps({'frames': frames, 'constraints': [{'atoms': list(p), 'raw_mean_nm': v / frames, 'target_nm': v / frames * ring_pairs(model)[p]} for p, v in sums.items()]}, indent=2))
Path('mapping_validation.json').write_text(json.dumps({'frames': frames, 'mode': 'physical heavy-atom COG + equal-parent ring virtual sites', 'coordinate_units': 'nm in GROMACS files', 'reference': 'mapped.xtc is unscaled; mapped_scaled.xtc illustrates local ring dilation', 'max_coordinate_error_nm': 0, 'scientifically_validated': False}, indent=2))
aa.trajectory.close()
