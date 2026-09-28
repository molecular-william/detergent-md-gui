"""A sugar whose ring the templates do not cover still gets a candidate, with a warning.

The paper's general rules: ring beads named A, B, C from the anomeric carbon, the ether oxygen in the last
bead, roughly four heavy atoms per bead, and a massless TC4 site per ring. Types come from the same rules
the templates use, and where a fragment matches none of them the candidate says so instead of presenting a
guess as a result.
"""
import pytest

from dashboard import paths
from dashboard.models.mappings import context as mapping_context
from dashboard.models.sugars import candidate, recognition

MOLECULES = paths.DEFAULT.project_root / 'molecules'


def synthetic(elements, bonds):
    atoms = [{'id': index, 'element': element, 'heavy': True}
             for index, element in enumerate(elements, 1)]
    return {'atoms': atoms, 'bonds': [list(bond) for bond in bonds]}


def ribofuranose_like():
    """A five ring whose anomeric carbon carries a hydroxyl but no hydroxymethyl."""
    return synthetic(['O', 'C', 'C', 'C', 'C', 'O', 'O', 'O', 'C', 'O'],
                     [(1, 2), (2, 3), (3, 4), (4, 5), (5, 1), (2, 6), (3, 7), (4, 8), (5, 9), (9, 10)])


def deoxy_hexopyranose_like():
    """A six ring with one carbon carrying no oxygen, which the hexopyranose template requires."""
    return synthetic(['O', 'C', 'C', 'C', 'C', 'C', 'O', 'O', 'O', 'C', 'O'],
                     [(1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 1),
                      (2, 7), (3, 8), (4, 9), (6, 10), (10, 11)])


def build(structure, name='Draft'):
    return candidate(structure, name)


@pytest.fixture(scope='module')
def furanose():
    structure = ribofuranose_like()
    return structure, build(structure, 'Ribose')


@pytest.fixture(scope='module')
def deoxy():
    structure = deoxy_hexopyranose_like()
    return structure, build(structure, 'Fucose')


def heavy_atoms(structure):
    return {atom['id'] for atom in structure['atoms'] if atom.get('heavy')}


def test_the_templates_claim_neither_ring():
    assert recognition.identify_hexoses(ribofuranose_like()) == []
    assert recognition.identify_furanoses(ribofuranose_like()) == []
    assert recognition.identify_hexoses(deoxy_hexopyranose_like()) == []
    assert [ring['claimed'] for ring in recognition.identify_rings(ribofuranose_like())] == [False]
    assert [ring['claimed'] for ring in recognition.identify_rings(deoxy_hexopyranose_like())] == [False]


def test_a_candidate_is_still_produced(furanose, deoxy):
    assert furanose[1] is not None
    assert deoxy[1] is not None


def test_the_ring_beads_are_lettered_from_the_anomeric_carbon(furanose, deoxy):
    for _structure, data in (furanose, deoxy):
        letters = [bead['letter'] for bead in data['beads'] if not bead.get('virtual_site')]
        assert letters == list('ABC'[:len(letters)]), letters
        assert [bead['residue'] for bead in data['beads']] == [1] * len(data['beads'])


def test_the_ether_oxygen_sits_in_the_last_ring_bead(deoxy):
    """The paper puts the ether oxygen in the C-bead; the last bead is the C-bead of a three-bead ring."""
    _structure, data = deoxy
    ring = data['rings'][0]
    last = [bead for bead in data['beads'] if bead['name'] == ring['beads'][-1]][0]
    assert 1 in last['atoms'], 'the ring oxygen is atom 1'
    assert ring['beads'][-1].endswith('C')


def test_every_ring_atom_lands_in_exactly_one_bead(furanose, deoxy):
    for structure, data in (furanose, deoxy):
        claimed = [atom for bead in data['beads'] for atom in bead['atoms']]
        assert len(claimed) == len(set(claimed)), 'no atom may be in two beads'
        assert heavy_atoms(structure) <= set(claimed), 'no heavy atom may be left out'


def test_each_ring_has_a_tc4_site_built_from_its_own_beads(furanose, deoxy):
    for _structure, data in (furanose, deoxy):
        sites = [bead for bead in data['beads'] if bead.get('virtual_site')]
        assert len(sites) == 1
        assert sites[0]['type'] == 'TC4' and sites[0]['size'] == 'T'
        assert sites[0]['virtual_site']['parents'] == data['rings'][0]['beads']


def test_the_candidate_warns_that_the_types_may_need_correction(furanose, deoxy):
    for _structure, data in (furanose, deoxy):
        assert any('not covered by the templates' in limitation and 'manual correction' in limitation
                   for limitation in data['limitations']), data['limitations']
        assert any('not covered by the templates' in warning for warning in data['warnings']), data['warnings']


def test_a_molecule_the_templates_cover_is_unchanged():
    """Sucrose still provides exactly its two reference residues and no such warning."""
    structure = mapping_context.as_structure(mapping_context.build_context(MOLECULES, 'Sucrose'))
    data = candidate(structure, 'Sucrose')
    assert len(data['beads']) == 8
    assert not any('not covered by the templates' in limitation for limitation in data['limitations'])
    assert data['warnings'] == []
