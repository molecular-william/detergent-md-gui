"""What the atoms no ring claimed are called.

Before this, everything outside a recognized ring was chunked four atoms at a time and called TAIL, so
sucrose's fructose ring and a bridging oxygen were '"tails" -- one of them a single oxygen atom. A name
should describe the chemistry: an alkyl chain is a TAIL, a chain carrying a heteroatom is a LINK, a
component containing a ring is a RING the templates did not cover, and a lone isolated atom is reported
as what it is.
"""


from dashboard import paths
from dashboard.models.mappings import context as mapping_context
from dashboard.models.sugars import candidate, coords

MOLECULES = paths.DEFAULT.project_root / 'molecules'


def graph_of(elements, bonds):
    atoms = {index: {'id': index, 'element': element, 'heavy': True}
             for index, element in enumerate(elements, 1)}
    adjacency = {index: set() for index in atoms}
    for first, second in bonds:
        adjacency[first].add(second)
        adjacency[second].add(first)
    return atoms, adjacency


def linear(elements):
    return graph_of(elements, [(index, index + 1) for index in range(1, len(elements))])


def structure(name):
    return mapping_context.as_structure(mapping_context.build_context(MOLECULES, name))


def test_a_pure_carbon_chain_is_a_tail():
    atoms, adjacency = linear(['C'] * 12)
    beads, notes = coords.remainder_beads(atoms, adjacency, set())
    assert [bead['name'] for bead in beads] == ['TAIL1', 'TAIL2', 'TAIL3']
    assert [len(bead['atoms']) for bead in beads] == [4, 4, 4]
    assert {bead['type'] for bead in beads} == {'C1'}
    assert notes == []


def test_a_thirteen_carbon_chain_ends_in_no_loose_atom():
    """Groups are balanced across the component: four atoms then one would leave a one-atom bead."""
    atoms, adjacency = linear(['C'] * 13)
    beads, _notes = coords.remainder_beads(atoms, adjacency, set())
    assert sorted(len(bead['atoms']) for bead in beads) == [3, 3, 3, 4]
    assert min(len(bead['atoms']) for bead in beads) >= 3


def test_a_chain_carrying_oxygen_is_a_link_not_a_tail():
    atoms, adjacency = linear(['C', 'C', 'C', 'O', 'C', 'C', 'C', 'C'])
    beads, _notes = coords.remainder_beads(atoms, adjacency, set())
    assert [bead['name'] for bead in beads] == ['LINK1', 'LINK2']
    assert not any(bead['name'].startswith('TAIL') for bead in beads)
    assert beads[0]['type'] == 'P1', 'the group carrying the ether oxygen is polar'
    assert beads[1]['type'] == 'C1', 'the all-carbon group of the same linker stays apolar'


def test_a_component_containing_a_ring_is_called_a_ring_and_noted():
    atoms, adjacency = graph_of(['C', 'C', 'C', 'C', 'C', 'O'],
                                [(1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 1)])
    beads, notes = coords.remainder_beads(atoms, adjacency, set())
    assert all(bead['name'].startswith('RING') for bead in beads)
    assert notes and 'ring' in notes[0].lower()


def test_an_isolated_atom_is_reported_rather_than_dropped():
    atoms, adjacency = graph_of(['O'], [])
    beads, notes = coords.remainder_beads(atoms, adjacency, set())
    assert len(beads) == 1
    assert beads[0]['atoms'] == [1]
    assert notes, 'a single-atom bead is an admission, not a normal outcome'


def test_sucrose_has_no_tail_bead_at_all():
    data = candidate(structure('Sucrose'), 'Sucrose')
    assert not any(bead['name'].startswith('TAIL') for bead in data['beads'])
    assert len(data['beads']) == 8, 'two residues of three beads and a site, with nothing left over'


def test_ddm_keeps_a_tail_for_its_dodecyl_chain():
    data = candidate(structure('DDM'), 'DDM')
    tails = [bead for bead in data['beads'] if bead['name'].startswith('TAIL')]
    assert [len(bead['atoms']) for bead in tails] == [4, 4, 4]
    assert sum(len(bead['atoms']) for bead in tails) == 12
