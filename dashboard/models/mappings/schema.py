"""Mapping document schema, size constants and stable identity.

Pure functions; no filesystem access. Structural validation is separated from
graph-based validation in mapping_graph.py. automatic_candidate takes an
explicit structure so no molecule is privileged.
"""
from copy import deepcopy
import hashlib
import json

from .. import bonded

SIZES = {'R': 4, 'S': 3, 'T': 2}
LABELS = {'d', 'a', 'e', 'v'}


def mapping_identity(mapping):
    """Return stable identity for bead assignments and bonded connectivity."""
    payload = {key: mapping.get(key) for key in ('name', 'beads', 'rings', 'connections')}
    if mapping.get('schema_version') == 3:
        payload.update(identity_version=3, molecule_id=mapping.get('molecule_id'),
                       molecule_snapshot=mapping.get('molecule_snapshot'))
    if 'representation_mode' in mapping:
        payload['representation_mode'] = mapping.get('representation_mode')
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def mapping_content_identity(mapping):
    """Return the mapping identity without the user-facing candidate name."""
    return mapping_identity({**mapping, 'name': ''})


def check_schema(data, *, allow_empty=False, representation_mode=None):
    representation_mode = representation_mode or data.get('representation_mode')
    if not isinstance(data, dict) or not isinstance(data.get('name'), str) or not 1 <= len(data['name'].strip()) <= 160:
        raise ValueError('Give this candidate a name (1–160 characters)')
    beads = data.get('beads')
    minimum = 0 if allow_empty else 1
    if not isinstance(beads, list) or not minimum <= len(beads) <= 100:
        raise ValueError(f'A candidate must contain {minimum}–100 bead groups')
    for bead in beads:
        if not isinstance(bead, dict) or not isinstance(bead.get('name'), str) or not 1 <= len(bead['name']) <= 40:
            raise ValueError('Every bead needs a name (1–40 characters)')
        if bead.get('size') not in SIZES:
            raise ValueError('Bead size must be R, S or T')
        if bead.get('label') not in (None, '') and bead.get('label') not in LABELS:
            raise ValueError('Bead label must be d, a, e or v')
        if not isinstance(bead.get('atoms'), list) or len(bead['atoms']) > 200 or any(type(x) is not int or x < 1 for x in bead['atoms']):
            raise ValueError('Atom assignments must be lists of positive integer indices')
        if 'virtual_site' in bead:
            site = bead['virtual_site']
            if not isinstance(site, dict) or site.get('function') != 1 or bead['atoms']:
                raise ValueError('Virtual sites require function 1 and no exclusive AA atoms')
            parents = site.get('parents')
            if not isinstance(parents, list) or len(parents) != 3 or any(not isinstance(p, str) for p in parents) or len(set(parents)) != 3:
                raise ValueError('A ring virtual site needs three distinct parent bead names')
            physical = {b.get('name') for b in beads if not b.get('virtual_site')}
            if not set(parents) <= physical:
                raise ValueError('Virtual site parent is missing or is itself virtual')
            if bead.get('type') != 'TC4' or bead['size'] != 'T':
                raise ValueError('Carbohydrate ring interaction sites must be tiny TC4')
    connections = data.get('connections', [])
    physical = {b['name'] for b in beads if not b.get('virtual_site')}
    if not isinstance(connections,list) or len(connections)>300: raise ValueError('Invalid CG connections')
    for pair in connections:
        if not isinstance(pair,list) or len(pair)!=2 or any(not isinstance(n,str) or n not in physical for n in pair) or pair[0]==pair[1]:
            raise ValueError('CG connections must name two distinct massive beads')
    rings = data.get('rings', [])
    if not isinstance(rings, list) or len(rings) > 30: raise ValueError('Invalid sugar ring definitions')
    used = set(); byname = {b['name']:b for b in beads}
    for ring in rings:
        if not isinstance(ring, dict): raise ValueError('Invalid sugar ring')
        parents = ring.get('beads')
        if not isinstance(parents, list) or len(parents) != 3 or any(not isinstance(p,str) for p in parents) or len(set(parents)) != 3:
            raise ValueError('A sugar ring needs three distinct bead names')
        if not set(parents) <= byname.keys() or used & set(parents): raise ValueError('Missing or overlapping sugar ring beads')
        if any(byname[p].get('virtual_site') for p in parents): raise ValueError('Ring vertices must be massive beads')
        used.update(parents)
        site_name = ring.get('virtual_site')
        site = byname.get(site_name, {})
        if representation_mode == 'physical_only_ring_constrained':
            if site_name is not None: raise ValueError('Physical-only ring definitions cannot reference virtual sites')
        elif site.get('virtual_site',{}).get('parents') != parents:
            raise ValueError('Ring virtual site parents disagree with its ring')
        if type(ring.get('scale')) not in (int,float) or ring['scale'] != 1.15: raise ValueError('Paper ring distance scale must be 1.15')
    bonded.validate(data)


def new_draft(context, name='New mapping'):
    """Create an empty molecule-bound editor document without persistence."""
    return {'schema_version': 3, 'molecule_id': context['molecule_id'],
            'molecule_snapshot': deepcopy(context['snapshot']), 'name': name,
            'beads': [], 'rings': [], 'connections': [],
            'provenance': {'origin': 'manual', 'algorithm': None, 'references': []},
            'status': 'candidate-unvalidated', 'martini_version': '3'}


def automatic_candidate(structure, molecule_name):
    """Build a graph-local starting mapping for any supported molecule.

    The sugar-first fragment path runs when the structure matches a recognized
    hexopyranose; otherwise a connected-graph fallback groups heavy atoms into
    R/S/T beads sized by atomic count. Bead chemistry requires calibration
    regardless of which path runs.
    """
    if not isinstance(structure, dict) or not structure.get('atoms'):
        raise ValueError('automatic_candidate requires an explicit molecule structure')
    if not isinstance(molecule_name, str) or not molecule_name.strip():
        raise ValueError('automatic_candidate requires a molecule name')
    # Deferred import keeps the schema module independent for pure callers.
    from .. import carbohydrates
    heavy = [a['id'] for a in structure['atoms'] if a['heavy']]
    sugar = carbohydrates.candidate(structure, molecule_name)
    if sugar is not None:
        return sugar
    adj = {a: set() for a in heavy}
    for a, b in structure['bonds']:
        if a in adj and b in adj:
            adj[a].add(b); adj[b].add(a)
    unassigned = set(heavy); groups = []
    while unassigned:
        seed = min(unassigned); group = {seed}; unassigned.remove(seed)
        frontier = set(adj[seed]) & unassigned
        while frontier and len(group) < 4:
            atom = min(frontier); frontier.discard(atom)
            if atom not in unassigned: continue
            group.add(atom); unassigned.remove(atom)
            frontier |= (adj[atom] & unassigned)
        unassigned -= group; groups.append(sorted(group))
    atoms_by_id = {a['id']: a for a in structure['atoms']}
    beads = []
    for i, atoms in enumerate(groups, 1):
        size = 'R' if len(atoms) >= 4 else ('S' if len(atoms) >= 3 else 'T')
        oxy = sum(atoms_by_id[a]['name'].upper().startswith('O') for a in atoms)
        bead_type = 'P1' if oxy >= 2 else ('P2' if oxy == 1 else 'C1')
        beads.append({'name': f'BEAD{i:02d}', 'size': size, 'type': ('' if size == 'R' else size) + bead_type, 'atoms': atoms})
    return {'name': f'{molecule_name} generic graph draft', 'beads': beads,
            'status': 'candidate-unvalidated', 'martini_version': '3',
            'source_structure': structure.get('source', ''),
            'algorithm': 'Generic connected graph fallback; no verified sugar template matched; bead chemistry requires calibration'}
