"""GROMACS ITP generation for the paper sugar architecture.

Constraints/angles/dihedrals are seeded from COG geometry and later refined by
FF_inter. Links between rings stay unscaled so that AA fitting sees the true
intergroup separation.
"""
import itertools

from .coords import coordinates, physical_edges, ring_pairs
from .reference import entry as reference_entry
from .reference import signature as reference_signature
from .units import angstrom_factor


def linkage_seed(data):
    """The reference's own inter-residue bond for the entry this candidate follows, if there is one.

    The stiffness is the part worth adopting: it is what sets how freely two sugar units move against each
    other, and the reference encodes it per disaccharide -- 6200 for sucrose, 9000 for trehalose, 11250 for
    lactose -- where this writer would otherwise give every linkage the same 5000, the sugar-to-alkyl link
    and the bonds along a detergent tail included.

    The length stays derived from the mapped geometry, exactly as the ring constraints are, because a
    published length paired with local coordinates would start a run by pulling the system onto someone
    else's structure. The reference's length is recorded beside it in the topology and reported by
    parameter_delta, so the comparison is visible without being silently imposed.
    """
    record = data.get('reference') or {}
    name = record.get('entry')
    # Coverage does not matter here: a sugar carrying a chain still has a reference-matched linkage between
    # its two rings, and that bond is the one the paper fixes a stiffness for. Which edges count as the
    # linkage is decided by linkage_edge, in the reference's own currency.
    if not name or not record.get('unambiguous'):
        return None
    try:
        links = reference_signature(reference_entry(name))['links']
    except KeyError:
        return None
    if len(links) != 1 or links[0].get('force') is None:
        return None
    link = links[0]
    return {'entry': name, 'force': link['force'], 'length': link['length'],
            'ends': frozenset((tuple(link['a']), tuple(link['b'])))}


def linkage_edge(beads, seed, a, b):
    """True when this edge is the reference's inter-residue bond, in the reference's own currency."""
    if not seed:
        return False

    def currency(index):
        bead = beads[index - 1]
        if bead.get('virtual_site'):
            return None
        return (bead.get('residue', 1), bead.get('letter') or bead['name'])

    first, second = currency(a), currency(b)
    if not first or not second or first[0] == second[0]:
        return False
    return frozenset((first, second)) == seed['ends']


def topology(data, structure, *, residue_name='DDM', representation_mode=None):
    import numpy as np
    from MDAnalysis.lib.distances import calc_angles, calc_dihedrals
    representation_mode = representation_mode or data.get('representation_mode') or 'tc4'
    if representation_mode not in ('tc4', 'physical_only_ring_constrained'):
        raise ValueError(f'Unknown carbohydrate representation: {representation_mode}')
    beads = data['beads']; names = {b['name']:i+1 for i,b in enumerate(beads)}
    xyz = coordinates(data, [a['xyz'] for a in structure['atoms']], [a['id'] for a in structure['atoms']],
                      representation_mode=representation_mode) * angstrom_factor(structure)
    pairs = ring_pairs(data)
    if data.get('connections'):
        edges = sorted(set(tuple(sorted((names[a], names[b]))) for a,b in data['connections']) | set(pairs))
    else:
        edges = sorted(set(physical_edges(data, structure)) | set(pairs))
    adj = {i:set() for i,b in enumerate(beads,1) if not b.get('virtual_site')}
    ring_of = {names[n]:ri for ri,r in enumerate(data['rings']) for n in r['beads']}
    lines = ['; Carbohydrate paper architecture; linkage parameters are AA-fit hypotheses.',
             '; Ring constraints: mean raw AA COG distances x 1.15; links remain unscaled.',
             '[ moleculetype ]', f'{residue_name} 1', '', '[ atoms ]']
    for i,b in enumerate(beads,1):
        mass = 0 if b.get('virtual_site') else {'R':72,'S':54,'T':36}[b['size']]
        # The reference names its beads A/B/C/VS within each residue, so a two-residue model reads like
        # the published entry instead of one residue numbered B01..B08. Leftover fragments are not
        # reference residues and keep a positional name.
        lines.append(f'{i} {b["type"]} {b.get("residue",1)} {residue_name} {b.get("letter") or f"B{i:02d}"} '
                     f'{i} {b.get("charge",0)} {mass}')
    lines += ['', '[ constraints ]']
    for (a,b),scale in pairs.items():
        # No inline comment: bundled FF retains uncommented constraints unchanged.
        lines.append(f'{a} {b} 1 {np.linalg.norm(xyz[a-1]-xyz[b-1])*scale:.6f}')
    lines += ['', '[ bonds ]']
    seed = linkage_seed(data)
    for a,b in edges:
        adj[a].add(b); adj[b].add(a)
        if (a,b) not in pairs:
            length = np.linalg.norm(xyz[a-1]-xyz[b-1])
            if linkage_edge(beads, seed, a, b):
                lines.append(f'{a} {b} 1 {length:.6f} {seed["force"]} ; linkage of {seed["entry"]}: '
                             f'reference force {seed["force"]}, reference length {seed["length"]:.3f} nm, '
                             f'length derived here')
            else:
                lines.append(f'{a} {b} 1 {length:.6f} 5000 ; B{a:02d}_B{b:02d}')
    lines += ['', '[ angles ]']
    for b, neighbors in adj.items():
        for a,c in itertools.combinations(sorted(neighbors),2):
            if a in ring_of and ring_of.get(a) == ring_of.get(b) == ring_of.get(c): continue
            angle = np.degrees(calc_angles(xyz[a-1],xyz[b-1],xyz[c-1]))
            lines.append(f'{a} {b} {c} 1 {angle:.5f} 25 ; B{a:02d}_B{b:02d}_B{c:02d}')
    links = [(a,b) for a,b in edges if a in ring_of and b in ring_of and ring_of[a]!=ring_of[b]]
    dihedrals = []
    for a,b in links:
        left = sorted(x for x in adj[a] if ring_of.get(x)==ring_of[a])
        right = sorted(x for x in adj[b] if ring_of.get(x)==ring_of[b])
        dihedrals.append((left[0],a,b,right[0]))
    # Extra orientation torsion for three connected repeat units (also branches).
    for middle in range(len(data['rings'])):
        spokes = [(a,b) if ring_of[b]==middle else (b,a) for a,b in links if middle in (ring_of[a],ring_of[b])]
        for (outer1,center1),(outer2,center2) in itertools.combinations(spokes,2):
            if ring_of[outer1] == ring_of[outer2]: continue
            if center1 == center2:
                center2 = next(names[n] for n in data['rings'][middle]['beads'] if names[n]!=center1)
            dihedrals.append((outer1,center1,center2,outer2))
    lines += ['', '[ dihedrals ]']
    for a,b,c,d in dihedrals:
        phi = np.degrees(calc_dihedrals(xyz[a-1],xyz[b-1],xyz[c-1],xyz[d-1]))
        lines.append(f'{a} {b} {c} {d} 1 {phi:.5f} 5 1 ; B{a:02d}_B{b:02d}_B{c:02d}_B{d:02d}')
    sites = [(i, b) for i, b in enumerate(beads, 1) if b.get('virtual_site')]
    if representation_mode == 'tc4' and sites:
        lines += ['', '[ virtual_sitesn ]']
        for i, b in sites:
            lines.append(f'{i} 1 ' + ' '.join(str(names[n]) for n in b['virtual_site']['parents']))
        lines += ['', '[ exclusions ]']
        for i, b in sites:
            lines.append(f'{i} ' + ' '.join(str(names[n]) for n in b['virtual_site']['parents']))
    return '\n'.join(lines)+'\n'
