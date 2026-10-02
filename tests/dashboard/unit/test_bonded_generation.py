
from pathlib import Path

import pytest

from dashboard.models.bonded import generation as bonded_generation


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


def _mapping_four_beads():
    return {
        'name': 'four',
        'beads': [
            {'name': 'A', 'size': 'R', 'type': 'C1', 'atoms': [1]},
            {'name': 'B', 'size': 'R', 'type': 'C2', 'atoms': [2]},
            {'name': 'C', 'size': 'R', 'type': 'C3', 'atoms': [3]},
            {'name': 'D', 'size': 'R', 'type': 'C4', 'atoms': [4]},
        ],
        'rings': [],
        'connections': [['A', 'B'], ['B', 'C'], ['C', 'D']],
        'schema_version': 2,
    }


def _structure_four_beads():
    return {
        'atoms': [
            {'id': 1, 'name': 'C1', 'heavy': True, 'xyz': [0.0, 0.0, 0.0]},
            {'id': 2, 'name': 'C2', 'heavy': True, 'xyz': [0.47, 0.0, 0.0]},
            {'id': 3, 'name': 'C3', 'heavy': True, 'xyz': [0.94, 0.1, 0.0]},
            {'id': 4, 'name': 'C4', 'heavy': True, 'xyz': [1.41, 0.1, 0.1]},
        ],
        'bonds': [[1, 2], [2, 3], [3, 4]],
    }


def _itp_with_angle(angle, force):
    return '\n'.join([
        '[ atoms ]',
        '1 C1 1 REF B1 1 0 72',
        '2 C2 1 REF B2 2 0 72',
        '3 C3 1 REF B3 3 0 72',
        '[ angles ]', f'1 2 3 2 {angle} {force}',
    ])


def _itp(atoms, bonds):
    return '\n'.join([
        '[ moleculetype ]', 'REF 1', '', '[ atoms ]',
        *[f'{index} {bead_type} 1 REF B{index} {index} 0 72' for index, bead_type in atoms],
        '', '[ bonds ]', *bonds, '',
    ])


def _itp_with_terms():
    return '\n'.join([
        '[ moleculetype ]', 'REF 1', '', '[ atoms ]',
        '1 C1 1 REF B1 1 0 72',
        '2 C2 1 REF B2 2 0 72',
        '3 C3 1 REF B3 3 0 72',
        '4 C4 1 REF B4 4 0 72',
        '', '[ bonds ]', '1 2 1 0.47 1250',
        '', '[ angles ]', '1 2 3 2 150 50',
        '', '[ dihedrals ]', '1 2 3 4 1 110 8 1',
        '',
    ])


def test_reference_index_records_sources_and_deterministic_pair_selection(tmp_path):
    root = tmp_path / 'references'
    root.mkdir()
    (root / 'a.itp').write_text(_itp([(1, 'C1'), (2, 'C1')], ['1 2 1 0.47 1250\n']))
    (root / 'b.itp').write_text(_itp([(1, 'C1'), (2, 'C1')], ['1 2 1 0.47 1250\n']))
    (root / 'c.itp').write_text(_itp([(1, 'C1'), (2, 'C1')], ['1 2 1 0.40 900\n']))

    index = bonded_generation.reference_bond_index(tmp_path)

    assert index['version'] == 2
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


def test_reference_index_normalizes_angles_and_dihedrals(tmp_path):
    root = tmp_path / 'references'
    root.mkdir()
    (root / 'ddm.itp').write_text(_itp_with_terms())

    index = bonded_generation.reference_bond_index(tmp_path)

    assert index['version'] == 2
    assert index['angles']['C1|C2|C3'][0]['parameters'] == [150.0, 50.0]
    assert index['dihedrals']['C1|C2|C3|C4'][0]['parameters'] == [110.0, 8.0, 1.0]
    assert index['angles']['C1|C2|C3'][0]['references'][0]['line'] > 0


def test_reference_index_reports_nonfinite_and_short_rows(tmp_path):
    root = tmp_path / 'references'
    root.mkdir()
    (root / 'bad.itp').write_text(
        '[ atoms ]\n1 C1\n2 C2\n3 C3\n'
        '[ angles ]\n1 2 3 2 nan 50\n1 2 3 2 150\n'
    )

    index = bonded_generation.reference_bond_index(tmp_path)

    assert index['angles'] == {}
    assert index['diagnostics']


def test_reference_index_prefers_specific_reference_rank(tmp_path):
    generic = tmp_path / 'references' / 'generic'
    specific = tmp_path / 'references' / 'MAD Database' / 'DDM'
    generic.mkdir(parents=True)
    specific.mkdir(parents=True)
    text = _itp([(1, 'C1'), (2, 'C1')], ['1 2 1 0.47 1250\n'])
    (generic / 'martini.itp').write_text(text.replace('0.47 1250', '0.30 5000'))
    (specific / 'DDM.itp').write_text(text)

    index = bonded_generation.reference_bond_index(tmp_path)

    assert index['bonds']['C1|C1'][0]['parameters'] == [0.47, 1250.0]
    assert index['bonds']['C1|C1'][0]['source_rank'] > index['bonds']['C1|C1'][1]['source_rank']


def test_reference_index_excludes_explicit_atomistic_tree(tmp_path):
    path = tmp_path / 'references' / 'M3-Small-Molecules' / 'models' / 'AA'
    path.mkdir(parents=True)
    (path / 'atomistic.itp').write_text(_itp(
        [(1, 'CT'), (2, 'CT')], ['1 2 1 0.15 200000\n']))

    index = bonded_generation.reference_bond_index(tmp_path)

    assert not index['bonds']
    assert not index['sources']


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


def test_generate_uses_reference_angles_and_dihedrals(tmp_path):
    root = tmp_path / 'references'
    root.mkdir()
    (root / 'ref.itp').write_text(_itp_with_terms())

    result = bonded_generation.generate(_mapping_four_beads(), _structure_four_beads(), tmp_path)

    angle = next(term for term in result['interactions']
                 if term['kind'] == 'angles' and term['beads'] == ['A', 'B', 'C'])
    assert angle['function'] == '2'
    assert angle['parameters'] == ['150', '50']
    assert angle['provenance']['fallback'] is False
    assert any(term['kind'] == 'dihedrals' for term in result['interactions'])
    assert result['provenance']['algorithm']['version'] == '2'


def test_generate_does_not_invent_dihedrals_without_reference(tmp_path):
    (tmp_path / 'references').mkdir()

    result = bonded_generation.generate(_mapping_four_beads(), _structure_four_beads(), tmp_path)

    assert not any(term['kind'] == 'dihedrals' for term in result['interactions'])


def test_generate_records_ambiguous_reference_signatures(tmp_path):
    root = tmp_path / 'references'
    root.mkdir()
    (root / 'a.itp').write_text(_itp_with_angle(150, 50))
    (root / 'b.itp').write_text(_itp_with_angle(140, 50))

    result = bonded_generation.generate(_mapping_four_beads(), _structure_four_beads(), tmp_path)
    angle = next(term for term in result['interactions']
                 if term['kind'] == 'angles' and term['beads'] == ['A', 'B', 'C'])

    assert angle['provenance']['ambiguity']


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


REPO_ROOT = Path(__file__).resolve().parents[3]


def _triangle():
    """Three beads bonded to each other: a ring, which is where the degenerate dihedral comes from.

    Walking a dihedral from an edge of a ring, the two outside beads can be the *same* bead -- the closure -- and
    `6 5 7 6` is not a dihedral. GROMACS says so: "Duplicate atom index (6) in dihedrals". The DDM draft emitted
    exactly that, beside the proper `2 5 7 6`, and the whole pdc pipeline stopped there.
    """
    mapping = {'name': 'triangle', 'schema_version': 3, 'martini_version': 3,
               'beads': [{'name': name, 'size': 'R', 'type': 'C1', 'atoms': [index]}
                         for index, name in enumerate('ABC', start=1)],
               'rings': [], 'connections': [['A', 'B'], ['B', 'C'], ['A', 'C']]}
    structure = {'atoms': [{'id': 1, 'name': 'C1', 'heavy': True, 'xyz': [0.0, 0.0, 0.0]},
                           {'id': 2, 'name': 'C2', 'heavy': True, 'xyz': [4.7, 0.0, 0.0]},
                           {'id': 3, 'name': 'C3', 'heavy': True, 'xyz': [2.4, 4.1, 0.0]}],
                 'bonds': [[1, 2], [2, 3], [1, 3]]}
    return mapping, structure


def test_a_ring_closure_does_not_yield_a_term_that_names_a_bead_twice(monkeypatch):
    """A reference always matches here, so the enumerator itself is what is under test.

    With the repository's real references and a triangle of one bead type, no dihedral matches and nothing is
    emitted -- which would make this test pass without testing anything. Stubbing the selection puts the enumerator
    in the position the DDM ring put it in, where the two outside beads of an edge on a three-membered ring are the
    same bead.
    """
    def always_select(index, kind, types, mapping_name='', martini_version=None):
        # The shape `_select_reference` really returns, with parameters that fit the section: the validator checks
        # the count per function, and a bond takes two values where a dihedral takes three.
        parameters = [100.0, 25.0] if kind != 'dihedrals' else [0.0, 25.0, 1]
        selected = {'function': '1', 'parameters': parameters, 'count': 1,
                    'references': [{'path': 'test', 'count': 1}], 'path': 'test'}
        return '|'.join(types), selected, []

    monkeypatch.setattr(bonded_generation, '_select_reference', always_select)

    mapping, structure = _triangle()
    result = bonded_generation.generate(mapping, structure, REPO_ROOT)

    degenerate = [term for term in result['interactions']
                  if len(set(term['beads'])) != len(term['beads'])]
    assert not degenerate, f'GROMACS refuses these: {degenerate}'
    assert result['interactions'], 'the triangle should still produce bonds and angles'


def test_a_term_the_caller_wrote_with_a_repeated_bead_is_refused():
    mapping, structure = _triangle()
    terms = [{'kind': 'dihedrals', 'beads': ['A', 'B', 'C', 'A'], 'function': '1', 'parameters': [0.0, 25.0, 1]}]

    with pytest.raises(ValueError, match='distinct beads'):
        bonded_generation.topology_from_terms(mapping, structure, terms)
