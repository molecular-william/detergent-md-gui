"""Sugar-first mapping candidate, coordinate construction and CG edge topology."""
import itertools

from .recognition import graph, identify_hexoses


def candidate(structure, name):
    atoms, adj = graph(structure)
    sugars = identify_hexoses(structure)
    if not sugars: return None
    # Each exocyclic O belongs to the higher chemical carbon index; e.g. C4
    # rather than donor C1. A sugar-alkyl ether remains in the sugar A fragment.
    position = {c: (ri, k+1) for ri, r in enumerate(sugars) for k, c in enumerate(r['carbons'])}
    oxygen_owner = {}
    for o in atoms:
        if atoms[o]['element'] != 'O' or any(o == r['oxygen'] for r in sugars): continue
        neighbors = [c for c in adj[o] if c in position]
        if neighbors:
            oxygen_owner[o] = max(neighbors, key=lambda c: (position[c][1], position[c][0]))
    beads, ring_records, assigned = [], [], set()
    for ri, r in enumerate(sugars, 1):
        c1,c2,c3,c4,c5,c6 = r['carbons']
        fragments = [{c1,c2}, {c3,c4}, {c5,c6,r['oxygen']}]
        for fragment in fragments:
            fragment.update(o for o,c in oxygen_owner.items() if c in fragment)
        names = []
        for letter, group in zip('ABC', fragments):
            n = f'S{ri}{letter}'; names.append(n)
            oxy = [i for i in group if atoms[i]['element'] == 'O']
            hydroxyls = [o for o in oxy if len(adj[o]) == 1]
            if letter == 'C': typ = 'SP1r'
            elif len(group) == 4 and len(hydroxyls) == 2: typ = 'SP4r'
            elif len(group) == 4 and len(oxy) == 2: typ = 'SP1r'
            elif len(group) == 3 and len(oxy) == 1: typ = 'SN6'
            else: raise ValueError(f'Unsupported carbohydrate fragment {n}; review substitution chemistry')
            beads.append({'name':n,'size':'S','type':typ,'atoms':sorted(group),
                          'fragment':'hexopyranose-'+letter, 'residue':ri})
            assigned |= group
        vs = f'S{ri}VS'
        beads.append({'name':vs,'size':'T','type':'TC4','atoms':[],
                      'virtual_site':{'parents':names,'function':1},'residue':ri})
        ring_records.append({'beads':names,'virtual_site':vs,'carbons':r['carbons'],
                             'ring_oxygen':r['oxygen'],'scale':1.15})
    # Remaining components are handled only after sugar/linker ownership is fixed.
    remaining = set(atoms) - assigned
    while remaining:
        endpoints = [a for a in remaining if len(adj[a] & remaining) <= 1]
        seed = min(endpoints or remaining)
        group = {seed}; remaining.remove(seed)
        while len(group) < 4:
            frontier = set().union(*(adj[a] for a in group)) & remaining
            if not frontier: break
            nxt = min(frontier); group.add(nxt); remaining.remove(nxt)
        size = 'R' if len(group) >= 4 else 'S' if len(group) == 3 else 'T'
        apolar = all(atoms[a]['element'] == 'C' for a in group)
        typ = ('' if size == 'R' else size) + ('C1' if apolar else 'P1')
        beads.append({'name':f'TAIL{sum(b["name"].startswith("TAIL") for b in beads)+1}',
                      'size':size,'type':typ,'atoms':sorted(group)})
    connections = [[beads[a-1]['name'],beads[b-1]['name']] for a,b in physical_edges({'beads':beads}, structure)]
    return {'name':f'{name} carbohydrate paper draft', 'beads':beads,'rings':ring_records,
            'connections':connections,'schema_version':2,'source_structure':structure.get('source',''),
            'status':'candidate-unvalidated','martini_version':'3',
            'algorithm':'Recognized hexopyranose rings; canonical C1→C6 fragments; diols first; higher-carbon bridge ownership; sugar first, then remaining graph.',
            'provenance':{'paper_doi':'10.1021/acs.jctc.2c00757','sugar_topology':'references/martini_v3.0.0_sugars_v2.itp'},
            'limitations':['Hexopyranose template only; other sugars use the generic draft fallback',
                            'Glycosidic stereochemistry and sugar–alkyl linkage require AA bonded fitting',
                            'SP1r sugar–alkyl ether assignment is a transferability hypothesis; validate partitioning']}


def coordinates(data, positions, atom_ids=None, scaled=False, representation_mode=None):
    """COG of physical groups then equal-weight parent COG for virtual sites.

    Units follow positions. Dilate each ring then translate connected rigid
    groups to retain the original inter-group vectors. Cyclic links need a
    separate constrained reconstruction and are rejected.
    """
    import numpy as np
    representation_mode = representation_mode or data.get('representation_mode') or 'tc4'
    if representation_mode not in ('tc4', 'physical_only_ring_constrained'):
        raise ValueError(f'Unknown carbohydrate representation: {representation_mode}')
    ids = atom_ids if atom_ids is not None else range(1,len(positions)+1)
    lookup = dict(zip(ids, positions))
    beads = data['beads']; names = {b['name']:i for i,b in enumerate(beads)}
    xyz = np.zeros((len(beads),3))
    for i,b in enumerate(beads):
        if not b.get('virtual_site'):
            xyz[i] = np.mean([lookup[a] for a in b['atoms']], axis=0)
    raw = xyz.copy()
    if scaled:
        for r in data.get('rings',[]):
            idx = [names[n] for n in r['beads']]; center = raw[idx].mean(axis=0)
            xyz[idx] = center + r['scale']*(raw[idx]-center)
    if scaled and data.get('connections'):
        components = [[names[n] for n in r['beads']] for r in data.get('rings',[])]
        grouped = {i for group in components for i in group}
        components += [[i] for i,b in enumerate(beads) if i not in grouped and not b.get('virtual_site')]
        comp = {i:ci for ci,group in enumerate(components) for i in group}
        links = {ci:[] for ci in range(len(components))}
        for a,b in data['connections']:
            i,j=names[a],names[b]
            if comp[i]!=comp[j]:
                links[comp[i]].append((comp[j],i,j));links[comp[j]].append((comp[i],j,i))
        seen=set()
        def place(ci, parent=None):
            seen.add(ci)
            for other,i,j in links[ci]:
                if other==parent: continue
                # The AA graph can produce redundant links between already
                # placed components.  The first path supplies a stable
                # rigid placement; later links remain available to topology
                # generation but must not trigger a second placement.
                if other in seen: continue
                delta=xyz[i]+raw[j]-raw[i]-xyz[j]
                xyz[components[other]] += delta
                place(other,ci)
        for ci in links:
            if ci not in seen: place(ci)
    for i,b in enumerate(beads):
        if representation_mode == 'tc4' and b.get('virtual_site'):
            xyz[i] = xyz[[names[n] for n in b['virtual_site']['parents']]].mean(axis=0)
    return xyz


def ring_pairs(data):
    names = {b['name']:i+1 for i,b in enumerate(data['beads'])}
    return {tuple(sorted((names[a],names[b]))):r['scale'] for r in data.get('rings',[]) for a,b in itertools.combinations(r['beads'],2)}


def physical_edges(data, structure):
    owner = {a:i+1 for i,b in enumerate(data['beads']) for a in b['atoms']}
    return sorted({tuple(sorted((owner[a],owner[b]))) for a,b in structure['bonds']
                   if a in owner and b in owner and owner[a] != owner[b]})
