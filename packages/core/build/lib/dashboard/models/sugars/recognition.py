"""AA-graph-based pyranose and furanose ring detection.

Chemical numbering is derived from connectivity, never SwissParam index order
or screen orientation. Ring classes without a verified template here (ribose,
deoxy, uronic, N-acetyl, inositol) are rejected rather than guessed at.
"""
import itertools

PAPER = '10.1021/acs.jctc.2c00757'
RADII_NM = {'R': 0.264, 'S': 0.230, 'T': 0.191}


def graph(structure):
    atoms = {a['id']: a for a in structure['atoms'] if a['heavy']}
    adj = {a: set() for a in atoms}
    for a, b in structure['bonds']:
        if a in adj and b in adj:
            adj[a].add(b); adj[b].add(a)
    return atoms, adj


def identify_hexoses(structure):
    """Find isolated O+C5 rings with a C5-CH2OH branch and anomeric exo O.

    Fused/ambiguous rings are rejected instead of receiving a guessed template.
    Stereoidentity remains from the AA source; glycosidic terms must be fitted.
    """
    import networkx as nx
    atoms, adj = graph(structure)
    g = nx.Graph(adj)
    rings = []
    for cycle in nx.minimum_cycle_basis(g):
        if len(cycle) != 6: continue
        oxy = [i for i in cycle if atoms[i]['element'] == 'O']
        if len(oxy) != 1 or any(atoms[i]['element'] not in ('C', 'O') for i in cycle): continue
        members = set(cycle); oxygen = oxy[0]
        if len(adj[oxygen] & members) != 2: continue
        ends = []
        for c in adj[oxygen] & members:
            for branch in adj[c] - members:
                if atoms[branch]['element'] != 'C': continue
                other = adj[branch] - {c}
                if len(other) == 1 and atoms[next(iter(other))]['element'] == 'O':
                    ends.append((c, branch, next(iter(other))))
        if len(ends) != 1: continue
        c5, c6, o6 = ends[0]
        c1 = next(iter((adj[oxygen] & members) - {c5}))
        if not any(atoms[i]['element'] == 'O' for i in adj[c1] - members): continue
        order = [c1]; previous = oxygen
        while order[-1] != c5:
            nxt = (adj[order[-1]] & members) - {previous, oxygen}
            if len(nxt) != 1: break
            previous, current = order[-1], next(iter(nxt))
            if current in order: break
            order.append(current)
        if len(order) != 5: continue
        if any(len(adj[c] - members) != 1 or atoms[next(iter(adj[c] - members))]['element'] != 'O' for c in order[:4]):
            continue  # substituted/deoxy sugar needs an explicit template
        rings.append({'carbons': order + [c6], 'oxygen': oxygen, 'o6': o6,
                      'atoms': members, 'ring_size': 6})
    if any(a['atoms'] & b['atoms'] for a, b in itertools.combinations(rings, 2)):
        raise ValueError('Overlapping sugar rings require a verified fused-ring template')
    # Chemical direction: acceptor (higher connecting carbon) first, then donor.
    def depth(r, seen=None):
        seen = set() if seen is None else seen
        c1 = r['carbons'][0]
        if c1 in seen:
            # A closed linkage. Trehalose's alpha,alpha-1,1 joins its two rings through both anomeric carbons, so the
            # walk arrives back at a ring it has already visited; there is no acceptor end to order against and the
            # two rings are equivalent, so the walk stops rather than refusing the glycan. The sort's remaining keys
            # keep the result deterministic, and every ring whose linkage is genuinely ambiguous -- a fused pair --
            # is refused above by the overlapping-rings guard.
            return 0
        seen = seen | {c1}
        for o in adj[c1] - r['atoms']:
            for other in rings:
                if other is not r and (adj[o] & other['atoms']): return 1 + depth(other, seen)
        return 0
    return sorted(rings, key=lambda r: (depth(r), r['carbons'][0]))


def identify_rings(structure):
    """Every five- or six-membered C/O ring, whether or not a template claims it.

    The two templates above skip rings whose substitution they do not understand. This reports what is
    actually there so a caller can map it with the paper's general rules instead of dropping it into the
    remainder chunker, and marks each ring `claimed` so the templates keep priority where they apply.
    """
    import networkx as nx
    atoms, adj = graph(structure)
    g = nx.Graph(adj)
    claimed = {frozenset(ring['atoms']) for ring in identify_hexoses(structure)}
    claimed |= {frozenset(ring['atoms']) for ring in identify_furanoses(structure)}
    found = []
    for cycle in nx.minimum_cycle_basis(g):
        if len(cycle) not in (5, 6): continue
        if any(atoms[i]['element'] not in ('C', 'O') for i in cycle): continue
        oxy = [i for i in cycle if atoms[i]['element'] == 'O']
        if len(oxy) > 1: continue
        members = set(cycle)
        if oxy and len(adj[oxy[0]] & members) != 2: continue
        found.append({'atoms': members, 'oxygen': oxy[0] if oxy else None, 'ring_size': len(cycle),
                      'carbons': [atom for atom in cycle if atoms[atom]['element'] == 'C'],
                      'claimed': frozenset(members) in claimed})
    return found


def hydroxymethyl(adjacency, atoms, ring, carbon):
    """The exocyclic hydroxymethyl carbon attached to a ring carbon, if it has one."""
    for candidate in sorted(adjacency[carbon] - ring):
        if atoms[candidate]['element'] != 'C':
            continue
        if any(atoms[other]['element'] == 'O' for other in adjacency[candidate]):
            return candidate
    return None


def identify_furanoses(structure):
    """Find O+C4 furanose rings that carry a hydroxymethyl on the anomeric carbon.

    Slots follow the fragment convention the pyranose template established, so the partition code stays
    shared: `carbons[0:2]` become the A fragment, `[2:4]` B, and `[4:6]` C together with the ring
    oxygen. A pyranose fills them with C1,C2 / C3,C4 / C5,C6. A ketofuranose's anomeric carbon is C2, so
    slot 0 is its exocyclic hydroxymethyl C1, slot 1 is C2, and the C pair is C5 with its C6. Chemical
    numbering therefore differs between the two ring sizes; fragment order does not.

    Rings whose anomeric carbon carries no hydroxymethyl (ribofuranose and its relatives) are skipped
    rather than guessed at: they need their own verified template.
    """
    import networkx as nx
    atoms, adj = graph(structure)
    g = nx.Graph(adj)
    rings = []
    for cycle in nx.minimum_cycle_basis(g):
        if len(cycle) != 5: continue
        oxy = [i for i in cycle if atoms[i]['element'] == 'O']
        if len(oxy) != 1 or any(atoms[i]['element'] not in ('C', 'O') for i in cycle): continue
        members = set(cycle); oxygen = oxy[0]
        if len(adj[oxygen] & members) != 2: continue
        neighbours = sorted(adj[oxygen] & members)
        anomeric_candidates = [c for c in neighbours
                               if any(atoms[o]['element'] == 'O' for o in adj[c] - members)]
        if len(anomeric_candidates) != 1: continue
        anomeric = anomeric_candidates[0]
        other = next(c for c in neighbours if c != anomeric)
        first = hydroxymethyl(adj, atoms, members, anomeric)
        last = hydroxymethyl(adj, atoms, members, other)
        if first is None or last is None: continue
        order = [anomeric]; previous = oxygen
        while order[-1] != other:
            following = (adj[order[-1]] & members) - {previous, oxygen}
            if len(following) != 1: break
            previous, current = order[-1], next(iter(following))
            if current in order: break
            order.append(current)
        if len(order) != 4: continue
        rings.append({'carbons': [first] + order + [last], 'oxygen': oxygen,
                      'o6': next(o for o in adj[last] if atoms[o]['element'] == 'O'),
                      'atoms': members, 'ring_size': 5})
    if any(a['atoms'] & b['atoms'] for a, b in itertools.combinations(rings, 2)):
        raise ValueError('Overlapping sugar rings require a verified fused-ring template')
    return rings
