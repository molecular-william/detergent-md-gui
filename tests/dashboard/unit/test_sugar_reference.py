"""The parsed reference carbohydrate topology.

The reference file is the oracle for mapping fidelity, so these tests pin the values the later
conformance checks depend on, and pin the file itself against the provenance record.
"""
import hashlib
import json

from dashboard.models.sugars import reference


def test_the_reference_file_matches_its_pinned_provenance():
    digest = hashlib.sha256(reference.reference_path().read_bytes()).hexdigest()
    provenance = json.loads(reference.provenance_path().read_text())
    assert digest == provenance['sha256']
    assert reference.entry('SUCR')['name'] == 'SUCR'


def test_every_moleculetype_in_the_file_is_parsed():
    entries = reference.entries()
    assert set(entries) == {
        'GLC', 'MAN', 'GAL', 'FRUF', 'LFUC', 'LRHA', 'RIBF', 'XYL', 'INO', 'GLA', 'GYN', 'NMC',
        'LAC', 'SUCR', 'TREH',
    }


def test_sucrose_carries_two_residues_of_three_beads_and_one_site():
    entry = reference.entry('SUCR')
    assert [atom['name'] for atom in entry['atoms']] == ['A', 'B', 'C', 'VS', 'A', 'B', 'C', 'VS']
    assert [atom['type'] for atom in entry['atoms']] == ['SP1r', 'SP4r', 'SP1r', 'TC4',
                                                        'SN6', 'SP4r', 'SP1r', 'TC4']
    assert [atom['residue'] for atom in entry['atoms']] == [1, 1, 1, 1, 2, 2, 2, 2]
    assert [atom['mass'] for atom in entry['atoms']] == [54.0, 54.0, 54.0, 0.0, 54.0, 54.0, 54.0, 0.0]


def test_the_sucrose_linkage_is_a_bond_between_the_two_glycosidic_beads():
    entry = reference.entry('SUCR')
    linkage = [bond for bond in entry['bonds']
               if reference.residue_of(entry, bond['i']) != reference.residue_of(entry, bond['j'])]
    assert len(linkage) == 1
    bond = linkage[0]
    assert (bond['i'], bond['j']) == (1, 5)
    assert bond['length'] == 0.369
    assert bond['force'] == 6200.0


def test_sucrose_ring_constraints_are_read_from_both_residues():
    entry = reference.entry('SUCR')
    lengths = {(item['i'], item['j']): item['length'] for item in entry['constraints']}
    assert lengths == {(1, 2): 0.305, (1, 3): 0.385, (2, 3): 0.336,
                       (5, 6): 0.376, (5, 7): 0.468, (6, 7): 0.359}


def test_a_monosaccharide_constraint_set_is_read_verbatim():
    entry = reference.entry('GLC')
    assert [item['length'] for item in entry['constraints']] == [0.380, 0.470, 0.396]
    assert [(item['i'], item['j']) for item in entry['constraints']] == [(1, 2), (1, 3), (2, 3)]


def test_virtual_sites_name_their_own_residues_parents():
    entry = reference.entry('SUCR')
    assert [(item['site'], item['parents']) for item in entry['virtual_sitesn']] == [(4, [1, 2, 3]),
                                                                                    (8, [5, 6, 7])]
    assert reference.entry('GLC')['virtual_sitesn'] == [{'site': 4, 'function': 1, 'parents': [1, 2, 3]}]


def test_the_const_guarded_branch_is_parsed_separately_and_not_mixed_in():
    """NMC is the only entry with `#ifndef CONST`/`#ifdef CONST`. CONST is undefined here, so the
    bonds are live and the guarded constraints must not appear among the entry's constraints."""
    entry = reference.entry('NMC')
    assert {(item['i'], item['j']) for item in entry['bonds']} == {(2, 5), (3, 6)}
    assert {(item['i'], item['j']) for item in entry['constraints']} == {(1, 2), (1, 3), (2, 3)}
    assert {(item['i'], item['j']) for item in entry['guarded']['constraints']} == {(2, 5), (3, 6)}


def test_the_signature_reports_residues_and_inter_residue_links():
    signature = reference.signature(reference.entry('SUCR'))
    assert [bead['name'] for bead in signature['residues'][1]] == ['A', 'B', 'C', 'VS']
    assert [bead['type'] for bead in signature['residues'][2]] == ['SN6', 'SP4r', 'SP1r', 'TC4']
    assert signature['links'] == [{'a': [1, 'A'], 'b': [2, 'A'], 'length': 0.369, 'force': 6200.0}]
    assert signature['residues'][1][3]['virtual_site'] is True


def test_an_unknown_moleculetype_is_refused_by_name():
    try:
        reference.entry('NOPE')
    except KeyError as error:
        assert 'NOPE' in str(error)
    else:
        raise AssertionError('an unknown moleculetype must raise')
