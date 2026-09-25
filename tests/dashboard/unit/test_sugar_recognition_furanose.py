"""Furanose recognition: the ring class sucrose needs.

Slots follow the fragment convention the pyranose template established, so the partition code needs no
change: [A-first, A-second, B-first, B-second, C-first, C-second], with the ring oxygen joining the C
pair. For a pyranose that is C1,C2,C3,C4,C5,C6; a ketofuranose's anomeric carbon is C2, so its A pair is
the exocyclic hydroxymethyl C1 with C2, and its C pair is C5 with C6. Chemical numbering differs between
ring sizes; fragment order does not.
"""

import pytest

from dashboard import paths
from dashboard.models.mappings import context as mapping_context
from dashboard.models.sugars import recognition

MOLECULES = paths.DEFAULT.project_root / 'molecules'


@pytest.fixture(scope='module')
def sucrose():
    return mapping_context.as_structure(mapping_context.build_context(MOLECULES, 'Sucrose'))


@pytest.fixture(scope='module')
def maltose():
    return mapping_context.as_structure(mapping_context.build_context(MOLECULES, 'Maltose'))


def synthetic(elements, bonds):
    atoms = [{'id': index, 'element': element, 'heavy': True}
             for index, element in enumerate(elements, 1)]
    return {'atoms': atoms, 'bonds': [list(bond) for bond in bonds]}


def ribofuranose_like():
    """A five ring whose anomeric carbon has an exocyclic hydroxyl but no hydroxymethyl.

    Ring: O4-C1-C2-C3-C4-O4. C1 carries O1 only; C4 carries the C5 hydroxymethyl.
    """
    return synthetic(
        ['O', 'C', 'C', 'C', 'C', 'O', 'O', 'O', 'C', 'O'],
        [(1, 2), (2, 3), (3, 4), (4, 5), (5, 1),   # ring
         (2, 6), (3, 7), (4, 8), (5, 9), (9, 10)],  # O1 on C1, O2, O3, C5 on C4, O5 on C5
    )


def test_sucrose_holds_one_pyranose_and_one_furanose(sucrose):
    hexoses = recognition.identify_hexoses(sucrose)
    furanoses = recognition.identify_furanoses(sucrose)
    assert len(hexoses) == 1
    assert len(furanoses) == 1


def test_the_furanose_ring_is_reported_with_its_oxygen_and_size(sucrose):
    atoms, _ = recognition.graph(sucrose)
    record = recognition.identify_furanoses(sucrose)[0]
    assert record['ring_size'] == 5
    assert len(record['atoms']) == 5
    assert record['oxygen'] in record['atoms']
    assert atoms[record['oxygen']]['element'] == 'O'
    assert all(atoms[atom]['element'] in ('C', 'O') for atom in record['atoms'])


def test_the_furanose_slots_follow_the_fragment_convention(sucrose):
    atoms, adjacency = recognition.graph(sucrose)
    record = recognition.identify_furanoses(sucrose)[0]
    carbons = record['carbons']
    ring = record['atoms']
    assert len(carbons) == 6
    assert all(atoms[carbon]['element'] == 'C' for carbon in carbons)

    # Slot 1 is the anomeric carbon: in the ring, bonded to the ring oxygen, carrying an exocyclic O.
    anomeric = carbons[1]
    assert anomeric in ring
    assert record['oxygen'] in adjacency[anomeric]
    assert any(atoms[oxygen]['element'] == 'O' for oxygen in adjacency[anomeric] - ring)

    # Slot 0 is the hydroxymethyl on the anomeric carbon, and it carries the exocyclic O above.
    assert carbons[0] not in ring
    assert carbons[0] in adjacency[anomeric]
    assert any(atoms[oxygen]['element'] == 'O' for oxygen in adjacency[carbons[0]])

    # Slot 4 is the ring carbon bonded to the ring oxygen; slot 5 is its hydroxymethyl.
    assert carbons[4] in ring
    assert record['oxygen'] in adjacency[carbons[4]]
    assert carbons[5] not in ring
    assert carbons[5] in adjacency[carbons[4]]
    assert record['o6'] in adjacency[carbons[5]]


def test_the_five_ring_of_sucrose_is_the_fructose_ring_not_the_glucose_one(sucrose):
    furanose = recognition.identify_furanoses(sucrose)[0]
    hexose = recognition.identify_hexoses(sucrose)[0]
    assert not (furanose['atoms'] & hexose['atoms'])


def test_a_five_ring_without_an_exocyclic_hydroxymethyl_on_its_anomeric_carbon_is_not_claimed():
    structure = ribofuranose_like()
    assert recognition.identify_furanoses(structure) == []
    assert recognition.identify_hexoses(structure) == []


def test_a_claimed_furanose_never_overlaps_a_claimed_pyranose():
    """The overlap refusal that guards fused rings applies across ring classes too."""
    structure = ribofuranose_like()
    assert recognition.identify_furanoses(structure) == []


def test_pyranose_records_state_their_ring_size(maltose):
    records = recognition.identify_hexoses(maltose)
    assert [record['ring_size'] for record in records] == [6, 6]
