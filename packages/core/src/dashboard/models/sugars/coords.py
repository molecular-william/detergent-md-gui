"""Sugar-first mapping candidate, coordinate construction and CG edge topology."""
import itertools

from .identification import identify
from .recognition import graph, identify_furanoses, identify_hexoses, identify_rings

RING_LETTERS = 'ABCDEFGH'


def ring_carbon_order(adjacency, atoms, ring):
    """The ring's carbons in walk order, starting from the anomeric carbon.

    The paper's naming puts the anomeric carbon in the A-bead and the ether oxygen in the C-bead, so the
    walk has to start at the anomeric carbon. That is the ring carbon bonded to the ring oxygen which also
    carries an exocyclic oxygen; a ring without one (a carbocycle, or substitution that hides it) falls back
    to the carbon bonded to the ring oxygen and then to the lowest-numbered carbon, so the order is always
    defined rather than guessed at silently.
    """
    carbons = [atom for atom in ring['atoms'] if atoms[atom]['element'] == 'C']
    oxygen = ring['oxygen']
    anomeric = None
    if oxygen is not None:
        neighbours = sorted(adjacency[oxygen] & ring['atoms'])
        with_oxygen = [atom for atom in neighbours
                       if any(atoms[other]['element'] == 'O'
                              for other in adjacency[atom] - ring['atoms'])]
        anomeric = with_oxygen[0] if len(with_oxygen) == 1 else (neighbours[0] if neighbours else None)
    order = [anomeric if anomeric is not None else min(carbons)]
    previous = oxygen
    while len(order) < len(carbons):
        following = sorted((adjacency[order[-1]] & ring['atoms']) - {previous, oxygen})
        if not following: break
        previous, current = order[-1], following[0]
        if current in order: break
        order.append(current)
    return order + sorted(set(carbons) - set(order))


def generic_ring_beads(atoms, adjacency, ring, residue_number):
    """Beads for a ring the templates do not cover, following the paper's general rules.

    The paper names ring beads A, B and C with the anomeric carbon in A and the ether oxygen in C, maps
    about four heavy atoms per bead, and gives every ring a massless TC4 site. This walks the ring from its
    anomeric carbon, takes the carbons two at a time, gives each ring carbon's exocyclic atoms to its own
    bead, and puts the ring oxygen in the bead holding its non-anomeric neighbour -- the rule the templates
    already use. Types come from the same chemistry rules the templates use; a fragment those rules do not
    describe is typed by size and polarity instead, and the caller carries a warning, because the reference
    has no verified type for it. Returns the beads and that warning.
    """
    order = ring_carbon_order(adjacency, atoms, ring)
    groups = [set(pair) for pair in (order[index:index + 2] for index in range(0, len(order), 2))]
    if ring['oxygen'] is not None:
        neighbours = adjacency[ring['oxygen']] & ring['atoms']
        anchor = next((atom for atom in order[1:] if atom in neighbours), None)
        anchor = anchor if anchor is not None else next((atom for atom in order if atom in neighbours), None)
        next((group for group in groups if anchor in group), groups[-1]).add(ring['oxygen'])
    for group in groups:
        for carbon in list(group):
            group.update(other for other in adjacency[carbon] - ring['atoms']
                         if atoms[other]['element'] in ('C', 'O'))
        # An exocyclic carbon keeps its own oxygens, the way the templates keep a CH2OH's O with its carbon.
        for carbon in [item for item in list(group)
                       if atoms[item]['element'] == 'C' and item not in ring['atoms']]:
            group.update(other for other in adjacency[carbon] if atoms[other]['element'] == 'O')
    beads = []
    for letter, group in zip(RING_LETTERS, groups):
        size = 'R' if len(group) >= 5 else 'T' if len(group) <= 2 else 'S'
        hydroxyls = [item for item in group if atoms[item]['element'] == 'O' and len(adjacency[item]) == 1]
        oxygens = [item for item in group if atoms[item]['element'] == 'O']
        if len(group) == 4 and len(hydroxyls) == 2: kind = 'SP4r'
        elif len(group) == 4 and len(oxygens) == 2: kind = 'SP1r'
        elif len(group) == 3 and len(oxygens) == 1: kind = 'SN6'
        else:
            apolar = all(atoms[item]['element'] == 'C' for item in group)
            kind = ('' if size == 'R' else size) + ('C1' if apolar else 'P1')
        beads.append({'name': f'R{residue_number}{letter}', 'letter': letter, 'size': size, 'type': kind,
                      'atoms': sorted(group), 'residue': residue_number,
                      'fragment': f'unvalidated-ring-{letter}'})
    beads.append({'name': f'R{residue_number}VS', 'letter': 'VS', 'size': 'T', 'type': 'TC4', 'atoms': [],
                  'residue': residue_number,
                  'virtual_site': {'parents': [bead['name'] for bead in beads], 'function': 1}})
    warning = (f'a {ring["ring_size"]}-membered ring of {len(ring["atoms"])} heavy atoms is not covered by the '
               f'templates; it is mapped with the general fragment rules as residue {residue_number} and the '
               f'types may need manual correction')
    return beads, warning


def _ordered_rings(structure, found):
    """Recognized rings in the order the reference's residues place them.

    The reference's bead letters and its own bond list are expressed in its residue order, so a structure
    that is unambiguously identified as a whole reference entry is numbered that way. Anything else keeps
    the recognizers' order, so no candidate outside a reference match changes because of this.
    """
    rings = identify_hexoses(structure) + identify_furanoses(structure)
    if not (found and found.get('entry') and found.get('unambiguous') and found.get('covers_whole_molecule')):
        return rings
    by_atoms = {frozenset(ring['atoms']): ring for ring in rings}
    ordered = [by_atoms.get(frozenset(residue['atoms'])) for residue in found['residues']]
    if None in ordered or len(ordered) != len(rings):
        return rings
    return ordered


def components(adjacency, nodes):
    """The connected components of a node set, lowest id first."""
    parts, remaining = [], set(nodes)
    while remaining:
        seed = min(remaining)
        part = {seed}; frontier = [seed]
        while frontier:
            node = frontier.pop()
            for neighbour in sorted(adjacency[node] & remaining):
                if neighbour not in part:
                    part.add(neighbour); frontier.append(neighbour)
        remaining -= part
        parts.append(part)
    return parts


def _walk(adjacency, component):
    """Component atoms in connectivity order, starting from an endpoint when one exists."""
    if len(component) == 1:
        return [next(iter(component))]
    endpoints = sorted(node for node in component if len(adjacency[node] & component) <= 1)
    order = [endpoints[0] if endpoints else min(component)]
    seen = {order[0]}
    while len(order) < len(component):
        following = sorted((adjacency[order[-1]] & component) - seen)
        if not following: break
        order.append(following[0]); seen.add(following[0])
    return order + sorted(component - seen)


def _balanced(order):
    """Split a component into ceil(n/4) groups as equal in size as possible."""
    count = max(1, -(-len(order) // 4))
    base, extra = divmod(len(order), count)
    groups, start = [], 0
    for index in range(count):
        size = base + (1 if index < extra else 0)
        groups.append(order[start:start + size]); start += size
    return groups


def _arms(adjacency, component, vertex):
    """The arms leaving a branch atom: (the atom bonded to it, every atom of that arm)."""
    rest = component - {vertex}
    arms = []
    for root in sorted(adjacency[vertex] & rest):
        if any(root in arm for _root, arm in arms): continue
        arm = {root}; frontier = [root]
        while frontier:
            node = frontier.pop()
            for other in sorted(adjacency[node] & rest):
                if other not in arm:
                    arm.add(other); frontier.append(other)
        arms.append((root, arm))
    return arms


def _chunks(adjacency, component):
    """One connected component as connected chunks of at most four heavy atoms.

    A chain is cut into balanced contiguous pieces, the way it always was. A branch is never crossed:
    at a heavy-degree three or four atom the vertex closes one bead with the atom bonded to it in each
    of its shortest, equally long arms -- its symmetric arms -- and every longer arm is partitioned as
    a chain of its own. Walking a branch one neighbour at a time and slicing that walk is what put
    LMNG's two headgroup linkers and a chain end in one bead: the walk reached the end of one arm, left
    the other arms for last, and the balanced cut then ran over the concatenation, so the bead's atoms
    were not one connected group.
    """
    edges = sum(len(adjacency[node] & component) for node in component) // 2
    branches = sorted(node for node in component if len(adjacency[node] & component) >= 3)
    if edges >= len(component) or not branches:
        # A ring the templates did not cover stays a draft the caller notes; a plain chain is cut into
        # contiguous pieces of equal size.
        return _balanced(_walk(adjacency, component))
    vertex = branches[0]
    arms = _arms(adjacency, component, vertex)
    shortest = min(len(arm) for _root, arm in arms)
    bead = {vertex}
    for root, arm in arms:
        if len(arm) == shortest and len(bead) < 4:
            bead.add(root)
    chunks = [bead]
    for part in components(adjacency, component - bead):
        chunks.extend(_chunks(adjacency, part))
    return chunks


def fragment_bead(atoms, group, prefix, number):
    """One bead outside the rings: its name, size and type from the atoms it actually holds."""
    size = 'R' if len(group) >= 4 else 'S' if len(group) == 3 else 'T'
    apolar = all(atoms[node]['element'] == 'C' for node in group)
    return {'name': f'{prefix}{number}', 'size': size,
            'type': ('' if size == 'R' else size) + ('C1' if apolar else 'P1'),
            'atoms': sorted(group)}


def remainder_beads(atoms, adjacency, assigned):
    """Beads for the heavy atoms no ring claimed, named for the chemistry they actually carry.

    A pure-carbon acyclic component is an alkyl TAIL, a component carrying a heteroatom is a LINK, a
    component containing a ring is a RING the templates did not cover, and a single isolated atom is
    reported as itself. Each component is divided into as few beads as the four-heavy-atom convention
    allows, never across a branch (`_chunks`) and balanced within a chain, so a chain never ends in a
    one-atom bead -- which is what produced a lone oxygen named TAIL3 for sucrose. Returns the beads
    and the notes the candidate must carry, because a RING here is an admission rather than a result.
    """
    beads, notes, counts = [], [], {}
    for component in components(adjacency, set(atoms) - set(assigned)):
        edges = sum(len(adjacency[node] & component) for node in component) // 2
        prefix = ('RING' if edges >= len(component)
                  else 'LINK' if any(atoms[node]['element'] != 'C' for node in component) else 'TAIL')
        for group in _chunks(adjacency, component):
            counts[prefix] = counts.get(prefix, 0) + 1
            beads.append(fragment_bead(atoms, group, prefix, counts[prefix]))
        if prefix == 'RING':
            notes.append(f'{len(component)} heavy atoms form a ring the templates do not cover; it is '
                         f'drafted as {prefix}{counts[prefix]} and needs a verified template')
        elif len(component) == 1:
            notes.append(f'a single heavy atom is not a fragment: {prefix}{counts[prefix]} holds atom '
                         f'{sorted(component)[0]} alone and needs review')
    return beads, notes


def ring_layer(structure, name):
    """The beads for the rings this structure carries, and the heavy atoms they claim.

    A recognized pyranose or furanose is mapped by the paper's fragments, in the reference's residue
    order; a ring no template covers is mapped by the general rules and the layer carries a warning.
    None when the structure has no ring at all. This is the one ring layer: the automatic candidate
    adds the remainder to it, and the spectral algorithm keeps it as the rings' authority and
    partitions only the atoms it did not claim.
    """
    atoms, adj = graph(structure)
    found = identify(structure)
    sugars = _ordered_rings(structure, found)
    unclaimed = [ring for ring in identify_rings(structure) if not ring['claimed']]
    if not sugars and not unclaimed: return None
    # Each exocyclic O belongs to the higher chemical carbon index; e.g. C4
    # rather than donor C1. A sugar-alkyl ether remains in the sugar A fragment.
    # A 1,1 linkage ties at C1, and the published TREH entry puts the bridging oxygen on the *first* residue (its
    # glycosidic bead is SP1r, its connecting linker SN6): the tie goes to the lower ring, so a symmetric trehalose
    # reproduces the reference's bead types instead of swapping them.
    position = {c: (ri, k+1) for ri, r in enumerate(sugars) for k, c in enumerate(r['carbons'])}
    oxygen_owner = {}
    for o in atoms:
        if atoms[o]['element'] != 'O' or any(o == r['oxygen'] for r in sugars): continue
        neighbors = [c for c in adj[o] if c in position]
        if neighbors:
            oxygen_owner[o] = max(neighbors, key=lambda c: (position[c][1], -position[c][0]))
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
                          'fragment':'hexopyranose-'+letter, 'residue':ri, 'letter':letter})
            assigned |= group
        vs = f'S{ri}VS'
        beads.append({'name':vs,'size':'T','type':'TC4','atoms':[],
                      'virtual_site':{'parents':names,'function':1},'residue':ri,'letter':'VS'})
        ring_records.append({'beads':names,'virtual_site':vs,'carbons':r['carbons'],
                             'ring_oxygen':r['oxygen'],'scale':1.15})
    # Rings the templates do not cover are still mapped, by the paper's general rules, and the candidate
    # carries a warning rather than leaving those atoms to the remainder chunker.
    warnings = []
    residue_number = len(sugars)
    for ring in unclaimed:
        residue_number += 1
        ring_beads, warning = generic_ring_beads(atoms, adj, ring, residue_number)
        beads.extend(ring_beads)
        assigned |= {atom for bead in ring_beads for atom in bead['atoms']}
        ring_records.append({'beads': [bead['name'] for bead in ring_beads if not bead.get('virtual_site')],
                             'virtual_site': ring_beads[-1]['name'], 'carbons': ring['carbons'],
                             'ring_oxygen': ring['oxygen'], 'scale': 1.15})
        warnings.append(warning)
    reference_record = None if not found else {
        'entry': found['entry'], 'stereochemistry': found['stereochemistry'],
        'unambiguous': found['unambiguous'], 'order_basis': found['order_basis'],
        'covers_whole_molecule': found['covers_whole_molecule'],
        'outside_atoms': found['outside_atoms'], 'basis': found['basis']}
    return {'beads': beads, 'rings': ring_records, 'assigned': assigned,
            'warnings': warnings, 'reference': reference_record}


def connections_for(beads, structure):
    """The CG edges the AA bond graph implies: every bond whose two ends sit in different beads."""
    return [[beads[a-1]['name'],beads[b-1]['name']] for a,b in physical_edges({'beads':beads}, structure)]


def candidate(structure, name):
    layer = ring_layer(structure, name)
    if layer is None: return None
    atoms, adj = graph(structure)
    # Remaining components are handled only after sugar/linker ownership is fixed.
    remaining_beads, remainder_notes = remainder_beads(atoms, adj, layer['assigned'])
    beads = layer['beads'] + remaining_beads
    warnings = layer['warnings']
    return {'name':f'{name} carbohydrate paper draft', 'beads':beads,'rings':layer['rings'],
            'connections':connections_for(beads, structure),'schema_version':2,'source_structure':structure.get('source',''),
            'status':'candidate-unvalidated','martini_version':'3',
            'reference':layer['reference'],
            'algorithm':'Recognized pyranose and furanose rings, numbered in the reference residue order when the connectivity identifies a reference entry; canonical fragment pairs; diols first; higher-carbon bridge ownership; sugar first, then remaining graph.',
            'provenance':{'paper_doi':'10.1021/acs.jctc.2c00757','sugar_topology':'references/martini_v3.0.0_sugars_v2.itp'},
            'limitations':['Templates cover hexopyranoses and hydroxymethyl furanoses; a ring neither claims is mapped with the paper general fragment rules and flagged in these limitations',
                            'Glycosidic stereochemistry and sugar–alkyl linkage require AA bonded fitting',
                            'SP1r sugar–alkyl ether assignment is a transferability hypothesis; validate partitioning'] + remainder_notes + warnings,
            # The per-candidate warnings alone, for the interface to show: a ring no template covers is
            # mapped, but the user has to be told that its types may need correcting.
            'warnings': remainder_notes + warnings}


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


def gro_text(data, xyz, *, residue_name, box_nm=0.0):
    """A `.gro` for the beads at `xyz` (nm), named the way every run names them: `B01..` under one residue.

    The run's topology is written in run layout for the same reason: `gmx grompp` reconciles a topology against a
    structure by atom name, and MDAnalysis treats each residue as a molecule. One residue per molecule is the
    convention the mapping export and the analyses already speak.
    """
    name = str(residue_name or data.get('name') or 'SUG')[:5]
    lines = [f'{name} CG beads mapped from AA coordinates', str(len(data['beads']))]
    for index, (bead, position) in enumerate(zip(data['beads'], xyz), 1):
        atom = f'B{index:02d}'
        lines.append(f'{index:5d}{name:<5}{atom:>5}{index:5d}'
                     f'{float(position[0]):8.3f}{float(position[1]):8.3f}{float(position[2]):8.3f}')
    edge = float(box_nm or 0.0)
    lines.append(f'{edge:10.5f}{edge:10.5f}{edge:10.5f}')
    return '\n'.join(lines) + '\n'


def ring_pairs(data):
    names = {b['name']:i+1 for i,b in enumerate(data['beads'])}
    return {tuple(sorted((names[a],names[b]))):r['scale'] for r in data.get('rings',[]) for a,b in itertools.combinations(r['beads'],2)}


def physical_edges(data, structure):
    owner = {a:i+1 for i,b in enumerate(data['beads']) for a in b['atoms']}
    return sorted({tuple(sorted((owner[a],owner[b]))) for a,b in structure['bonds']
                   if a in owner and b in owner and owner[a] != owner[b]})
