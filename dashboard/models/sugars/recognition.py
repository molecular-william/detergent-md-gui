"""AA-graph-based hexopyranose ring detection.

Chemical numbering is derived from connectivity, never SwissParam index order
or screen orientation. Other sugar classes require their own verified templates.
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
                      'atoms': members})
    if any(a['atoms'] & b['atoms'] for a, b in itertools.combinations(rings, 2)):
        raise ValueError('Overlapping sugar rings require a verified fused-ring template')
    # Chemical direction: acceptor (higher connecting carbon) first, then donor.
    def depth(r, seen=None):
        seen = set() if seen is None else seen
        c1 = r['carbons'][0]
        if c1 in seen: raise ValueError('Cyclic glycan needs explicit linkage ordering')
        seen = seen | {c1}
        for o in adj[c1] - r['atoms']:
            for other in rings:
                if other is not r and (adj[o] & other['atoms']): return 1 + depth(other, seen)
        return 0
    return sorted(rings, key=lambda r: (depth(r), r['carbons'][0]))