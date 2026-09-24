"""Graph-based structural validation, reuse gate and ring-site preview."""
from collections import Counter

from .. import carbohydrates
from .context import as_structure
from ..packaged_ddm_source import molecule
from .schema import SIZES, check_schema


def validate(data, structure=None, *, context=None, allow_partial=False):
    check_schema(data, allow_empty=allow_partial)
    structure = structure or (as_structure(context) if context is not None else molecule())
    heavy = {a['id'] for a in structure['atoms'] if a['heavy']}
    known = {a['id'] for a in structure['atoms']}
    counts = Counter(a for b in data['beads'] for a in b['atoms'])
    issues = []
    def issue(code, message, bead=None):
        issues.append({'code': code, 'message': message, 'bead': bead})
    for code, ids, title in [
        ('missing', sorted(heavy - counts.keys()), 'Missing heavy atoms'),
        ('duplicate', sorted(a for a, n in counts.items() if n > 1), 'Repeated atom assignments'),
        ('unknown', sorted(counts.keys() - known), 'Unknown atom indices'),
        ('hydrogen', sorted((counts.keys() & known) - heavy), 'Hydrogens must be excluded'),
    ]:
        if ids:
            issue(code, f'{title}: {", ".join(map(str, ids))}')
    for i,b in enumerate(data['beads']):
        if b.get('virtual_site') and not any(r['virtual_site']==b['name'] for r in data.get('rings',[])):
            issue('virtual_ring',f'{b["name"]}: ring interaction site requires a matching three-bead ring definition',i)
    names = Counter(b['name'] for b in data['beads'])
    for name, count in names.items():
        if count > 1:
            issue('name', f'Duplicate bead name: {name}')
    adjacency = {a: set() for a in known}
    for a, b in structure['bonds']:
        adjacency[a].add(b); adjacency[b].add(a)
    for i, bead in enumerate(data['beads']):
        if bead.get('virtual_site'): continue
        ids = set(bead['atoms']) & heavy
        sugar_bead = any(bead['name'] in r['beads'] for r in data.get('rings', []))
        allowed = {3,4} if sugar_bead and bead['size'] == 'S' else {SIZES[bead['size']]}
        if len(ids) not in allowed:
            issue('size', f'{bead["name"]}: {len(ids)} heavy atoms; {bead["size"]} defaults to {SIZES[bead["size"]]}. Any shape/branching exception needs justification.', i)
        if not ids:
            issue('empty', f'{bead["name"]}: empty heavy-atom group', i)
        else:
            seen = {next(iter(ids))}; pending = list(seen)
            while pending:
                for neighbor in adjacency[pending.pop()] & ids - seen:
                    seen.add(neighbor); pending.append(neighbor)
            if seen != ids:
                issue('disconnected', f'{bead["name"]}: atoms do not form a connected group in the SwissParam bond graph', i)
    if 'connections' in data:
        edges = {frozenset(pair) for pair in data['connections']}
        physical = {b['name'] for b in data['beads'] if not b.get('virtual_site')}
        seen = {next(iter(physical))} if physical else set()
        while True:
            expanded = seen | set().union(*(edge for edge in edges if edge & seen))
            if expanded == seen: break
            seen = expanded
        if seen != physical or len(edges)!=len(data['connections']):
            issue('connections','Manual CG connectivity must connect all massive beads without duplicate edges')
        for ring in data.get('rings',[]):
            if any(frozenset((a,b)) not in edges for a in ring['beads'] for b in ring['beads'] if a!=b):
                issue('connections','Manual connectivity must retain every paper ring constraint')
    if data.get('rings'):
        recognized = carbohydrates.candidate(structure, 'validation')
        groups = {frozenset(b['atoms']) for b in (recognized or {}).get('beads',[]) if not b.get('virtual_site')}
        for i, b in enumerate(data['beads']):
            if any(b['name'] in r['beads'] for r in data['rings']) and frozenset(b['atoms']) not in groups:
                issue('sugar_fragment', f'{b["name"]}: assignments no longer match a recognized canonical sugar fragment', i)
    edges = {frozenset(p) for p in data.get('connections',[])} or {frozenset((data['beads'][a-1]['name'],data['beads'][b-1]['name'])) for a,b in carbohydrates.physical_edges(data,structure)}
    for term in data.get('bonded_overrides',[]):
        if any(frozenset(p) not in edges for p in zip(term['beads'],term['beads'][1:])):
            issue('connections','Bonded override must follow the saved CG connectivity')
    represented = sum(SIZES[b['size']] for b in data['beads'])
    mismatch = represented - len(heavy)
    if abs(mismatch) > len(heavy) / 10:
        issue('mismatch', f'Nominal representation is {represented} atoms for {len(heavy)} heavy atoms (difference {mismatch:+}); exceeds ±1 per 10 atoms.')
    centers = []
    atom_lookup = {a['id']:a for a in structure['atoms']}
    for bead in data['beads']:
        pts = [atom_lookup[a]['xyz'] for a in bead['atoms'] if a in atom_lookup]
        if pts:
            centers.append(([sum(p[d] for p in pts)/len(pts) for d in range(3)], bead['size']))
    radii = {size:radius*10 for size,radius in carbohydrates.RADII_NM.items()}
    overlap = 0.0; pairs = 0
    for i, (a, sa) in enumerate(centers):
        for b, sb in centers[i+1:]:
            dist = sum((a[d]-b[d])**2 for d in (0,1))**0.5
            threshold = radii[sa] + radii[sb]
            if dist < threshold:
                overlap += (threshold-dist)/threshold; pairs += 1
    crowding = overlap / max(1, len(centers)*(len(centers)-1)/2)
    # Size and nominal-count findings are review advisories. They describe
    # coarse-graining conventions, while the remaining findings indicate an
    # incomplete or unsafe graph that must block downstream artifacts.
    advisory_codes = {'size', 'mismatch'}
    hard_issues = [item for item in issues if item['code'] not in advisory_codes]
    hard_codes = {'duplicate', 'unknown', 'hydrogen', 'name', 'virtual_ring'}
    return {'issues': issues, 'covered': len(counts.keys() & heavy), 'heavy_atoms': len(heavy),
            'bead_count': len(data['beads']), 'virtual_sites': sum(bool(b.get('virtual_site')) for b in data['beads']), 'represented_atoms': represented, 'mismatch': mismatch,
            'overlap_pairs': pairs, 'overlap_crowding': round(crowding, 4),
            'checks_passed': not issues, 'scientifically_validated': False,
            'can_save': not any(item['code'] in hard_codes for item in issues),
            'can_approve': not issues, 'can_export': not hard_issues,
            'can_reuse': not hard_issues}


def require_usable(data, context, *, operation):
    if data.get('schema_version') == 3:
        if data.get('molecule_id') != context.get('molecule_id') or data.get('molecule_snapshot') != context.get('snapshot'):
            raise ValueError('Mapping belongs to a different molecule source snapshot')
    result = validate(data, context=context, allow_partial=bool(data.get('schema_version') == 3))
    gate = {'approve': 'can_approve', 'export': 'can_export', 'reuse': 'can_reuse'}.get(operation)
    if gate is None:
        raise ValueError('Unknown mapping operation')
    if not result[gate]:
        raise ValueError('Mapping is incomplete or structurally invalid: ' + '; '.join(item['message'] for item in result['issues']))
    return result


def ring_site_preview(data, context, parents):
    """Propose a massless TC4 site for three physical beads."""
    if not isinstance(parents, list) or len(parents) != 3 or len(set(parents)) != 3:
        raise ValueError('Select three distinct parent beads')
    byname = {bead.get('name'): bead for bead in data.get('beads', [])}
    selected = []
    for name in parents:
        bead = byname.get(name)
        if not bead or bead.get('virtual_site') or not bead.get('atoms'):
            raise ValueError('Ring interaction parents must be nonempty physical beads')
        selected.append(bead)
    used = {bead.get('name') for bead in data.get('beads', [])}
    number = len(data.get('beads', [])) + 1
    site_name = f'VS{number}'
    while site_name in used:
        number += 1; site_name = f'VS{number}'
    physical_edges = {frozenset((edge['a'], edge['b'])) for edge in context.get('bonds', [])}
    atom_ids = set().union(*(set(bead['atoms']) for bead in selected))
    induced_edges = [edge for edge in physical_edges if edge <= atom_ids]
    ring_like = len(induced_edges) >= len(atom_ids) if atom_ids else False
    verified_ring = next((ring for ring in data.get('rings', [])
                          if set(ring.get('beads', [])) == set(parents)), None)
    warnings = []
    if not ring_like and verified_ring is None:
        warnings.append({'code': 'not_ring_like', 'message': 'Selected bead parents do not enclose a detected AA graph cycle.'})
    proposal = {'name': site_name, 'size': 'T', 'type': 'TC4', 'atoms': [],
                'virtual_site': {'function': 1, 'parents': list(parents)}}
    return {'bead': proposal, 'ring': verified_ring, 'warnings': warnings}
