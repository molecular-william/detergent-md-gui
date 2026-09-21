"""Seed a clearly identified, uncalibrated DDM model for execution tests."""
import itertools
import json
import math
from pathlib import Path
from . import mappings, carbohydrates

CANDIDATE = mappings.SOURCE / 'mapping_candidate_smoke.json'


def load(data=None):
    selected = data is not None
    data = json.loads(json.dumps(data)) if selected else json.loads(CANDIDATE.read_text())
    validation = mappings.validate(data)
    blockers = [x['message'] for x in validation['issues'] if selected or x['code'] != 'size']
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


def initial_topology(data):
    """Infer bonded connectivity from the AA bond graph, never from bead indices."""
    structure = mappings.molecule()
    if data.get('rings'):
        return carbohydrates.topology(data, structure)
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
             '[ moleculetype ]', 'DDM 1', '', '[ atoms ]']
    for i, bead in enumerate(beads, 1):
        mass = {'R': 72, 'S': 54, 'T': 36}[bead['size']]
        lines.append(f'{i} {bead["type"]} 1 DDM B{i:02d} {i} 0 {mass}')
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
