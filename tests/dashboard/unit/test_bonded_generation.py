import json

import pytest

from dashboard.models import bonded_generation


def _mapping(*, virtual=False):
    beads = [
        {'name': 'A', 'size': 'R', 'type': 'C1', 'atoms': [1]},
        {'name': 'B', 'size': 'R', 'type': 'C1', 'atoms': [2]},
        {'name': 'C', 'size': 'R', 'type': 'C2', 'atoms': [3]},
    ]
    if virtual:
        beads.append({'name': 'VS', 'size': 'T', 'type': 'TC4', 'atoms': [],
                      'virtual_site': {'function': 1, 'parents': ['A', 'B', 'C']}})
    return {'name': 'test', 'beads': beads, 'rings': [],
            'connections': [['A', 'B'], ['B', 'C']], 'schema_version': 2}


def _structure():
    return {
        'atoms': [
            {'id': 1, 'name': 'C1', 'heavy': True, 'xyz': [0.0, 0.0, 0.0]},
            {'id': 2, 'name': 'C2', 'heavy': True, 'xyz': [4.7, 0.0, 0.0]},
            {'id': 3, 'name': 'C3', 'heavy': True, 'xyz': [9.4, 0.0, 0.0]},
        ],
        'bonds': [[1, 2], [2, 3]],
    }


def _itp(atoms, bonds):
    return '\n'.join([
        '[ moleculetype ]', 'REF 1', '', '[ atoms ]',
        *[f'{index} {bead_type} 1 REF B{index} {index} 0 72' for index, bead_type in atoms],
        '', '[ bonds ]', *bonds, '',
    ])


def test_reference_index_records_sources_and_deterministic_pair_selection(tmp_path):
    root = tmp_path / 'references'
    root.mkdir()
    (root / 'a.itp').write_text(_itp([(1, 'C1'), (2, 'C1')], ['1 2 1 0.47 1250\n']))
    (root / 'b.itp').write_text(_itp([(1, 'C1'), (2, 'C1')], ['1 2 1 0.47 1250\n']))
    (root / 'c.itp').write_text(_itp([(1, 'C1'), (2, 'C1')], ['1 2 1 0.40 900\n']))

    index = bonded_generation.reference_bond_index(tmp_path)

    assert index['version'] == 1
    assert index['bonds']['C1|C1'][0]['parameters'] == [0.47, 1250.0]
    assert len(index['bonds']['C1|C1']) == 2
    assert {source['path'] for source in index['sources']} == {
        'references/a.itp', 'references/b.itp', 'references/c.itp'
    }
    assert index['index_sha256'] == bonded_generation.reference_bond_index(tmp_path)['index_sha256']


def test_malformed_reference_is_diagnostic_and_does_not_abort(tmp_path):
    root = tmp_path / 'references'
    root.mkdir()
    (root / 'bad.itp').write_text('[ atoms ]\nnot an atom row\n')

    index = bonded_generation.reference_bond_index(tmp_path)

    assert index['bonds'] == {}
    assert index['diagnostics']


def test_generate_uses_reference_bonds_and_geometry_fallback(tmp_path):
    root = tmp_path / 'references'
    root.mkdir()
    (root / 'ref.itp').write_text(_itp(
        [(1, 'C1'), (2, 'C1')], ['1 2 1 0.47 1250\n']))

    result = bonded_generation.generate(_mapping(), _structure(), tmp_path)

    bonds = [term for term in result['interactions'] if term['kind'] == 'bonds']
    assert bonds[0]['beads'] == ['A', 'B']
    assert bonds[0]['parameters'] == ['0.47', '1250']
    assert bonds[0]['provenance']['fallback'] is False
    assert bonds[1]['beads'] == ['B', 'C']
    assert bonds[1]['parameters'][0] == '0.47'
    assert bonds[1]['provenance']['fallback'] is True
    assert any('no exact reference bond' in item.lower() for item in result['diagnostics'])
    assert '[ atoms ]' in result['topology']
    assert '[ angles ]' in result['topology']
    assert len([term for term in result['interactions'] if term['kind'] == 'angles']) == 1


def test_topology_from_terms_rejects_duplicate_pairs_and_keeps_virtual_site(tmp_path):
    mapping = _mapping(virtual=True)
    terms = [{
        'kind': 'bonds', 'beads': ['A', 'B'], 'function': '1',
        'parameters': ['0.47', '1250'],
    }]
    topology = bonded_generation.topology_from_terms(mapping, _structure(), terms, title='Draft')
    assert '[ virtual_sitesn ]' in topology
    assert '4 1 1 2 3' in topology

    with pytest.raises(ValueError, match='Duplicate'):
        bonded_generation.topology_from_terms(mapping, _structure(), terms + [{**terms[0]}], title='Draft')
