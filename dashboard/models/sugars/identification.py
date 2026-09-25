"""Identify which reference carbohydrate entry a structure's connectivity corresponds to.

Identification is connectivity-based and never perceives stereochemistry: epimers share a connectivity,
a bead partition and a bead-type signature, so what can be said honestly is which *pattern* the graph
has, plus the fact that the residue identity rests on the structure's own chemistry. That is recorded as
`stereochemistry: 'unresolved'` rather than quietly assumed away.

`RING_SIZES` annotates each reference residue with its ring size, read from the reference file's own
residue comments (FRUF and RIBF are furanoses; the aldohexoses, deoxy sugars, uronic acids, N-acetyls and
inositol are six-membered in the bead model). A test asserts the table covers every moleculetype in the
file, so a new reference residue forces an explicit decision here instead of silently matching nothing.
"""
from . import recognition, reference

RING_SIZES = {
    'GLC': (6,), 'MAN': (6,), 'GAL': (6,), 'FRUF': (5,), 'LFUC': (6,), 'LRHA': (6,), 'RIBF': (5,),
    'XYL': (6,), 'INO': (6,), 'GLA': (6,), 'GYN': (6,), 'NMC': (6,),
    'LAC': (6, 6), 'SUCR': (5, 6), 'TREH': (6, 6),
}

FRAGMENTS = 'ABC'


def ring_fragment(slot):
    """The bead letter a ring slot belongs to: the partition pairs slots two at a time."""
    return FRAGMENTS[slot // 2]


def patterns():
    """Each reference entry's fingerprint: its ring sizes and its linkage letters."""
    table = {}
    for name, sizes in RING_SIZES.items():
        signature = reference.signature(reference.entry(name))
        letters = tuple(sorted(tuple(sorted((link['a'][1], link['b'][1]))) for link in signature['links']))
        table[name] = {'sizes': tuple(sorted(sizes)), 'letters': letters, 'residues': tuple(sizes),
                       'signature': signature}
    return table


def rings(structure):
    """Every recognized ring, tagged with its class."""
    found = [dict(record, ring_class='pyranose') for record in recognition.identify_hexoses(structure)]
    found += [dict(record, ring_class='furanose') for record in recognition.identify_furanoses(structure)]
    return found


def sugar_atoms(structure, ring_records):
    """Heavy atoms the recognized rings account for: ring members, fragment carbons, exocyclic oxygens."""
    atoms, adjacency = recognition.graph(structure)
    owned = set()
    for ring in ring_records:
        owned |= ring['atoms'] | set(ring['carbons'])
        for carbon in ring['carbons']:
            owned |= {oxygen for oxygen in adjacency[carbon] if atoms[oxygen]['element'] == 'O'}
    return owned


def links(structure, ring_records):
    """Bridging oxygens joining two different rings, with each carbon's ring index and slot."""
    atoms, adjacency = recognition.graph(structure)
    slot_of = {(index, atom): slot for index, ring in enumerate(ring_records)
               for slot, atom in enumerate(ring['carbons'])}
    found = []
    for atom in sorted(atoms):
        if atoms[atom]['element'] != 'O':
            continue
        owners = [(index, slot_of[(index, carbon)]) for index in range(len(ring_records))
                  for carbon in sorted(adjacency[atom]) if (index, carbon) in slot_of]
        if len(owners) == 2 and owners[0][0] != owners[1][0]:
            found.append({'oxygen': atom, 'carbons': [[index, slot] for index, slot in owners],
                          'letters': [ring_fragment(slot) for _, slot in owners]})
    return found


def _order_records(ring_records, pattern, structure_links):
    """Assign rings to reference residue numbers by ring size, then by linkage letters.

    Where both signals are silent (two same-sized rings linked by the same letter) the input order is
    kept and the basis says so, because connectivity genuinely does not decide it.
    """
    letters_per_ring = {index: None for index in range(len(ring_records))}
    for link in structure_links:
        for index, _slot in link['carbons']:
            letters_per_ring[index] = link['letters'][[item[0] for item in link['carbons']].index(index)]
    pattern_letter = {}
    for link in pattern['signature']['links']:
        pattern_letter[link['a'][0]] = link['a'][1]
        pattern_letter[link['b'][0]] = link['b'][1]

    remaining = list(range(len(ring_records)))
    assigned = []
    basis = 'ring size and linkage letters'
    for number, size in enumerate(pattern['residues'], 1):
        wanted = pattern_letter.get(number)
        match = next((index for index in remaining if ring_records[index]['ring_size'] == size
                      and wanted is not None and letters_per_ring[index] == wanted), None)
        if match is None:
            match = next((index for index in remaining if ring_records[index]['ring_size'] == size), None)
            if wanted is not None:
                basis = 'ring size only'
        remaining.remove(match)
        assigned.append((number, match, ring_records[match]))
    return assigned, basis


def identify(structure):
    """The reference entry whose pattern this structure's connectivity matches, or None without rings."""
    ring_records = rings(structure)
    if not ring_records:
        return None
    sizes = tuple(sorted(ring['ring_size'] for ring in ring_records))
    structure_links = links(structure, ring_records)
    letters = tuple(sorted(tuple(sorted(link['letters'])) for link in structure_links))
    table = patterns()
    candidates = sorted(name for name, pattern in table.items()
                        if pattern['sizes'] == sizes and pattern['letters'] == letters)
    owned = sugar_atoms(structure, ring_records)
    outside = [atom['id'] for atom in structure['atoms']
               if atom.get('heavy') and atom['id'] not in owned]
    if not candidates:
        return {'entry': None, 'unambiguous': False, 'covers_whole_molecule': not outside,
                'outside_atoms': len(outside), 'candidates': [], 'order_basis': None,
                'residues': [], 'link': None, 'stereochemistry': 'unresolved',
                'basis': 'no reference entry has this ring-size and linkage-letter pattern'}
    name = candidates[0]
    pattern = table[name]
    assigned, order_basis = _order_records(ring_records, pattern, structure_links)
    residues = []
    residue_of_ring = {}
    for number, ring_index, ring in assigned:
        residue_of_ring[ring_index] = number
        beads = pattern['signature']['residues'][number]
        residues.append({'number': number, 'ring_size': ring['ring_size'], 'ring_class': ring['ring_class'],
                         'fragments': ''.join(ring_fragment(slot) for slot in range(len(ring['carbons']))),
                         'atoms': sorted(ring['atoms']),
                         'beads': [bead['name'] for bead in beads],
                         'physical_beads': [bead['name'] for bead in beads if not bead['virtual_site']],
                         'types': [bead['type'] for bead in beads if not bead['virtual_site']]})
    # The link is reported in the reference's own currency: residue number and slot, so it can be
    # compared against the reference's inter-residue bond without translating ring indices.
    resolved = []
    for link in structure_links:
        carbons = sorted([residue_of_ring[index], slot] for index, slot in link['carbons'])
        resolved.append({'oxygen': link['oxygen'], 'carbons': carbons,
                         'letters': [ring_fragment(slot) for _number, slot in carbons]})
    resolved.sort(key=lambda item: item['carbons'][0])
    return {'entry': name, 'unambiguous': len(candidates) == 1, 'covers_whole_molecule': not outside,
            'outside_atoms': len(outside), 'candidates': candidates, 'order_basis': order_basis,
            'residues': residues,
            'link': resolved[0] if resolved else None,
            'stereochemistry': 'unresolved',
            'basis': (f'connectivity: {len(ring_records)} rings of size '
                      f'{"+".join(str(size) for size in sizes)}'
                      + (f', linkage letters {"".join(letters[0])}' if letters else ''))}
