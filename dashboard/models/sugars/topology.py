"""GROMACS ITP generation for the paper sugar architecture.

Constraints/angles/dihedrals are seeded from COG geometry and later refined by
FF_inter. Links between rings stay unscaled so that AA fitting sees the true
intergroup separation.
"""
import itertools

from .coords import coordinates, physical_edges, ring_pairs
from .units import angstrom_factor


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
    for a,b in edges:
        adj[a].add(b); adj[b].add(a)
        if (a,b) not in pairs:
            lines.append(f'{a} {b} 1 {np.linalg.norm(xyz[a-1]-xyz[b-1]):.6f} 5000 ; B{a:02d}_B{b:02d}')
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
