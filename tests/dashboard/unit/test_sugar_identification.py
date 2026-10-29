"""Which reference entry a structure's connectivity corresponds to.

Identification is connectivity-based. Stereochemistry is never perceived: two residues that differ only
as epimers share a connectivity, a partition and a bead-type signature, so the honest output is "this
pattern" plus an explicit statement that the identity rests on the structure's own chemistry.
"""

import pytest
from dashboard import paths
from dashboard.models.mappings import context as mapping_context
from dashboard.models.sugars import identification, reference

MOLECULES = paths.DEFAULT.project_root / 'molecules'


def structure(name):
    return mapping_context.as_structure(mapping_context.build_context(MOLECULES, name))


@pytest.fixture(scope='module')
def sucrose():
    return structure('Sucrose')


@pytest.fixture(scope='module')
def maltose():
    return structure('Maltose')


@pytest.fixture(scope='module')
def ddm():
    return structure('DDM')


def test_every_reference_entry_is_annotated_with_its_ring_sizes():
    """A new moleculetype in the reference must force an explicit decision here."""
    assert set(identification.RING_SIZES) == set(reference.entries())


def test_sucrose_is_identified_as_the_reference_sucrose_entry(sucrose):
    result = identification.identify(sucrose)
    assert result['entry'] == 'SUCR'
    assert result['unambiguous'] is True
    assert result['covers_whole_molecule'] is True
    assert result['outside_atoms'] == 0
    assert result['stereochemistry'] == 'unresolved'


def test_sucroses_furanose_is_residue_one_and_its_pyranose_residue_two(sucrose):
    result = identification.identify(sucrose)
    assert [residue['ring_size'] for residue in result['residues']] == [5, 6]
    assert [residue['number'] for residue in result['residues']] == [1, 2]
    assert [residue['fragments'] for residue in result['residues']] == ['AABBCC', 'AABBCC']


def test_the_sucrose_linkage_is_anomeric_to_anomeric(sucrose):
    result = identification.identify(sucrose)
    assert result['link']['letters'] == ['A', 'A']
    assert len(result['link']['carbons']) == 2
    assert result['link']['carbons'][0][0] != result['link']['carbons'][1][0]


def test_maltose_matches_the_lactose_pattern(sucrose, maltose):
    result = identification.identify(maltose)
    assert result['entry'] == 'LAC'
    assert result['unambiguous'] is True
    assert result['covers_whole_molecule'] is True
    # The reference's own pairing, not the ring discovery order: LAC links residue 1 bead B to residue 2
    # bead A, and the ring that carries the 4-linked carbon is therefore assigned residue 1.
    assert result['link']['letters'] == ['B', 'A']
    assert [residue['types'] for residue in result['residues']] == [['SP4r', 'SP1r', 'SP1r'],
                                                                   ['SN6', 'SP4r', 'SP1r']]
    assert result['stereochemistry'] == 'unresolved'


def test_a_sugar_with_a_non_sugar_remainder_does_not_claim_the_whole_entry(ddm):
    result = identification.identify(ddm)
    assert result['covers_whole_molecule'] is False
    assert result['outside_atoms'] > 0
    assert result['entry'] is not None, 'the sugar portion still has a best pattern'


def test_a_structure_without_rings_is_not_identified():
    structure_without_rings = {'atoms': [{'id': 1, 'element': 'C', 'heavy': True},
                                         {'id': 2, 'element': 'C', 'heavy': True}],
                               'bonds': [[1, 2]]}
    assert identification.identify(structure_without_rings) is None
