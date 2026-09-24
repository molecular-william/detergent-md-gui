"""Seed a clearly identified, uncalibrated DDM model for execution tests."""
import itertools
import json
import math
from pathlib import Path
from .. import paths
from . import carbohydrates, mappings
from .mappings.context import as_structure, build_context

CANDIDATE = mappings.SOURCE / 'mapping_candidate_smoke.json'


def _structure_for(data, molecule_root=None):
    """Resolve the AA graph bound to a mapping, or the legacy DDM graph."""
    if data.get('schema_version') != 3:
        return mappings.molecule()
    molecule_id = data.get('molecule_id')
    if not isinstance(molecule_id, str) or not molecule_id:
        raise ValueError('schema 3 mappings require molecule_id')
    root = Path(molecule_root) if molecule_root is not None else paths.current().project_root / 'molecules'
    context = build_context(root, molecule_id)
    if data.get('molecule_snapshot') != context['snapshot']:
        raise ValueError('Molecule sources changed; reload the mapping workspace')
    return as_structure(context)


def load(data=None, *, molecule_root=None):
    selected = data is not None
    data = json.loads(json.dumps(data)) if selected else json.loads(CANDIDATE.read_text())
    validation = mappings.validate(data, structure=_structure_for(data, molecule_root))
    # Bead-size and nominal-representation checks describe Martini's coarse
    # mass convention. They are useful review warnings, but do not make a
    # structurally complete mapping unrunnable (for example, removing ring
    # virtual sites changes the nominal count by design). Missing, duplicate,
    # disconnected, unknown, hydrogen, and topology-consistency issues remain
    # execution blockers.
    advisory = {'size', 'mismatch'}
    blockers = [x['message'] for x in validation['issues']
                if x['code'] not in advisory and (selected or x['code'] != 'size')]
    force_field = mappings.ROOT / 'resources/templates/small_mols_fast_forward/3_initial_CG/martini_v3.0.0.itp'
    section = ''
    types = set()
    for line in force_field.read_text().splitlines():
        raw = line.split(';', 1)[0].strip()
        if raw.startswith('['): section = raw.strip('[] ')
        elif section == 'atomtypes' and raw: types.add(raw.split()[0])
    for bead in data['beads']:
        if bead.get('type') not in types:
            blockers.append(f'{bead["name"]}: assign a supported Martini bead type before running')
        elif data.get('schema_version') == 2:
            size = bead['type'][0] if bead['type'][0] in ('S','T') else 'R'
            if bead['size'] != size: blockers.append(f'{bead["name"]}: size disagrees with the complete Martini type {bead["type"]}')
    if blockers:
        raise ValueError('Draft mapping: ' + '; '.join(blockers))
    return data


def initial_topology(data, *, molecule_root=None, residue_name=None):
    """Infer bonded connectivity from the AA bond graph, never from bead indices."""
    structure = _structure_for(data, molecule_root)
    residue_name = residue_name or data.get('molecule_id') or 'DDM'
    if data.get('rings'):
        return carbohydrates.topology(data, structure, residue_name=residue_name)
    beads = data['beads']
    atoms = {a['id']: a for a in structure['atoms']}
    owner = {a: i for i, bead in enumerate(beads, 1) for a in bead['atoms']}
    edges = sorted({tuple(sorted((owner[a], owner[b]))) for a, b in structure['bonds']
                    if a in owner and b in owner and owner[a] != owner[b]})
    if data.get('connections'):
        names = {b['name']:i for i,b in enumerate(beads,1)}
        edges = sorted(tuple(sorted(names[n] for n in pair)) for pair in data['connections'])
    xyz = {i: [sum(atoms[a]['xyz'][d] for a in b['atoms']) / len(b['atoms']) / 10
               for d in range(3)] for i, b in enumerate(beads, 1)}
    lines = ['; DRAFT SMOKE TEST ONLY: bead types uncalibrated; bonded guesses replaced by ff_inter.',
             '; Bond lengths / angle centers from SwissParam COG. Initial k: 5000 bonds, 25 angles.',
             '[ moleculetype ]', f'{residue_name} 1', '', '[ atoms ]']
    for i, bead in enumerate(beads, 1):
        mass = {'R': 72, 'S': 54, 'T': 36}[bead['size']]
        lines.append(f'{i} {bead["type"]} 1 {residue_name} B{i:02d} {i} 0 {mass}')
    adjacency = {i: set() for i in xyz}
    lines += ['', '[ bonds ]']
    for a, b in edges:
        adjacency[a].add(b); adjacency[b].add(a)
        length = math.dist(xyz[a], xyz[b])
        lines.append(f'{a} {b} 1 {length:.5f} 5000 ; B{a:02d}_B{b:02d}')
    lines += ['', '[ angles ]']
    for b, neighbors in adjacency.items():
        for a, c in itertools.combinations(sorted(neighbors), 2):
            u = [x-y for x,y in zip(xyz[a],xyz[b])]
            v = [x-y for x,y in zip(xyz[c],xyz[b])]
            cos = sum(x*y for x,y in zip(u,v)) / math.sqrt(sum(x*x for x in u)*sum(x*x for x in v))
            angle = math.degrees(math.acos(max(-1, min(1, cos))))
            lines.append(f'{a} {b} {c} 1 {angle:.4f} 25 ; B{a:02d}_B{b:02d}_B{c:02d}')
    return '\n'.join(lines) + '\n'
