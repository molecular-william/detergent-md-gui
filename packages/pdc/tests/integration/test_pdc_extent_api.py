"""The extent endpoint the Membrane protein card reads: dimensions and the initial box, from coordinates alone.

The route's job is to answer with the build's own numbers and to refuse a request it cannot answer honestly. The
structures are imported through the real import path into the test's own workspace, so nothing touches the
developer's files; the expected boxes are computed by calling `pdc_box` itself, which is the point -- the route must
not keep a second copy of the rule.
"""
from __future__ import annotations

from detergent_pdc.execution.adapters import pdc_box

# One chain, four atoms, in Angstroms as a PDB writes them: 0..3.0 nm in x, 0..2.0 nm in y and 0..4.0 nm in z.
NO_MEMBRANE = (
    'ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\n'
    'ATOM      2  CA  ALA A   2      30.000  20.000  40.000  1.00  0.00           C\n'
    'END\n')
# The same coordinates, but the file states a 1.0 nm half-thickness: the membrane rule answers it.
MEMBRANE = ('REMARK      1/2 of bilayer thickness:   10.0\n' + NO_MEMBRANE)
POINTS_NM = [[0.0, 0.0, 0.0], [3.0, 2.0, 4.0]]

# Two subunits 10 nm apart, so the whole-file extent is not the subunit's: each is 1.0 nm wide in x.
ASSEMBLY = (
    'ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\n'
    'ATOM      2  CA  ALA A   2      10.000   0.000   0.000  1.00  0.00           C\n'
    'ATOM      3  CA  LEU B   1     100.000   0.000   0.000  1.00  0.00           C\n'
    'ATOM      4  CA  LEU B   2     110.000   0.000   0.000  1.00  0.00           C\n'
    'END\n')


def _import(dashboard, monkeypatch, pdbid, text):
    """Put a hand-made structure in the catalogue through the route the panel uses."""
    monkeypatch.setitem(dashboard.app.config, 'PDC_FETCHER', lambda url, body=text: body.encode())
    response = dashboard.client.post('/api/pdc/proteins/import', json={'pdbid': pdbid})
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.get_json()


def _extent(dashboard, entry, query=''):
    return dashboard.client.get(f'/api/pdc/proteins/{entry}/extent{query}')


def test_a_structure_that_states_no_membrane_gets_the_initial_box_rule(dashboard, monkeypatch):
    _import(dashboard, monkeypatch, '1qj8', NO_MEMBRANE)

    response = _extent(dashboard, '1qj8')

    assert response.status_code == 200, response.get_data(as_text=True)
    body = response.get_json()
    assert body['protein'] == '1qj8'
    assert body['dimensions_nm'] == {'x': 3.0, 'y': 2.0, 'z': 4.0}
    assert body['initial_box_nm'] == pdc_box.initial_box(POINTS_NM, margin_nm=2.0, initial_z_nm=6.0)
    assert (body['auto_initial_x_nm'], body['auto_initial_y_nm']) == \
        tuple(round(value, 3) for value in pdc_box.auto_initial_xy(POINTS_NM, margin_nm=2.0))
    assert body['auto_initial_z_nm'] == round(pdc_box.auto_initial_z(POINTS_NM, margin_nm=2.0), 3)
    assert body['rule'] == 'initial'
    assert body['half_thickness_nm'] is None
    assert body['chains'] is None


def test_a_structure_that_states_a_membrane_gets_the_membrane_box_rule(dashboard, monkeypatch):
    record = _import(dashboard, monkeypatch, '2abc', MEMBRANE)
    assert record['half_thickness_nm'] == 1.0, 'the fixture states a 1.0 nm half-thickness'

    body = _extent(dashboard, '2abc').get_json()

    assert body['rule'] == 'membrane'
    assert body['half_thickness_nm'] == 1.0
    assert body['dimensions_nm'] == {'x': 3.0, 'y': 2.0, 'z': 4.0}
    assert body['initial_box_nm'] == pdc_box.membrane_box(POINTS_NM, half_thickness_nm=1.0, margin_nm=2.0)
    assert body['auto_initial_z_nm'] == round(pdc_box.auto_initial_z(POINTS_NM, half_thickness_nm=1.0,
                                                                     margin_nm=2.0), 3)


def test_the_auto_initial_z_is_the_same_whatever_z_the_caller_asked_for(dashboard, monkeypatch):
    """Auto is a measurement, so it cannot depend on the value it is about to replace."""
    _import(dashboard, monkeypatch, '1qj8', NO_MEMBRANE)

    default = _extent(dashboard, '1qj8').get_json()['auto_initial_z_nm']
    requested = _extent(dashboard, '1qj8', '?initial_z_nm=40.0').get_json()['auto_initial_z_nm']

    assert default == requested == round(pdc_box.auto_initial_z(POINTS_NM, margin_nm=2.0), 3)


def test_the_margin_and_initial_z_the_caller_sends_reach_the_box(dashboard, monkeypatch):
    _import(dashboard, monkeypatch, '3def', NO_MEMBRANE)

    body = _extent(dashboard, '3def', '?margin_nm=1.5&initial_z_nm=8.0').get_json()

    assert body['dimensions_nm'] == {'x': 3.0, 'y': 2.0, 'z': 4.0}, 'the protein is unchanged by the box settings'
    assert body['initial_box_nm'] == pdc_box.initial_box(POINTS_NM, margin_nm=1.5, initial_z_nm=8.0)


def test_the_stated_initial_xy_is_the_cells_exact_dimension_and_the_auto_answer_is_the_derived_one(
        dashboard, monkeypatch):
    """A stated x/y is the cell the panel shows; Auto's suggested x/y stay the derived footprint.

    The protein spans 3 x 2 nm, so a 2 nm margin derives 7 x 6 nm. A stated 1 nm cannot hold the protein and is
    refused with the number it needs; a stated 20 x 25 is the caller's cell -- while
    `auto_initial_x_nm`/`auto_initial_y_nm` stay 7 and 6, because the button fills the values it is about to replace.
    """
    _import(dashboard, monkeypatch, '1qj8', NO_MEMBRANE)

    refused = _extent(dashboard, '1qj8', '?initial_x_nm=1.0&initial_y_nm=1.0')
    stated = _extent(dashboard, '1qj8', '?initial_x_nm=20.0&initial_y_nm=25.0').get_json()

    assert refused.status_code == 400
    assert 'stated x box (1 nm) is smaller than this system needs (7 nm)' in refused.get_json()['error']
    assert stated['initial_box_nm'][:2] == [20.0, 25.0]
    assert (stated['auto_initial_x_nm'], stated['auto_initial_y_nm']) == (7.0, 6.0)


def test_a_stated_initial_xy_that_is_not_a_positive_number_is_refused_naming_it(dashboard, monkeypatch):
    _import(dashboard, monkeypatch, '1qj8', NO_MEMBRANE)

    for name in ('initial_x_nm', 'initial_y_nm'):
        for bad in ('lots', '0', '-1', 'nan', 'inf'):
            response = _extent(dashboard, '1qj8', f'?{name}={bad}')
            assert response.status_code == 400, (name, bad)
            assert name in response.get_json()['error'], (name, bad)


def test_chains_narrows_the_dimensions_to_the_selected_subunit(dashboard, monkeypatch):
    _import(dashboard, monkeypatch, '1at9', ASSEMBLY)

    whole = _extent(dashboard, '1at9').get_json()
    one = _extent(dashboard, '1at9', '?chains=A').get_json()

    assert whole['dimensions_nm'] == {'x': 11.0, 'y': 0.0, 'z': 0.0}
    assert whole['chains'] is None
    assert one['chains'] == ['A']
    assert one['dimensions_nm'] == {'x': 1.0, 'y': 0.0, 'z': 0.0}
    assert one['initial_box_nm'][0] == pdc_box.initial_box([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])[0]


def test_an_unknown_protein_entry_is_a_404(dashboard):
    assert _extent(dashboard, 'nosuch').status_code == 404


def test_a_margin_that_is_not_a_positive_number_is_refused_naming_it(dashboard, monkeypatch):
    _import(dashboard, monkeypatch, '1qj8', NO_MEMBRANE)

    for bad in ('lots', '0', '-1', 'nan', 'inf'):
        response = _extent(dashboard, '1qj8', f'?margin_nm={bad}')
        assert response.status_code == 400, bad
        assert 'margin_nm' in response.get_json()['error'], bad


def test_an_initial_z_that_is_not_a_positive_number_is_refused_naming_it(dashboard, monkeypatch):
    _import(dashboard, monkeypatch, '1qj8', NO_MEMBRANE)

    for bad in ('lots', '0', '-1', 'nan', 'inf'):
        response = _extent(dashboard, '1qj8', f'?initial_z_nm={bad}')
        assert response.status_code == 400, bad
        assert 'initial_z_nm' in response.get_json()['error'], bad


def test_a_chain_the_file_does_not_have_is_refused_with_the_available_chains(dashboard, monkeypatch):
    _import(dashboard, monkeypatch, '1at9', ASSEMBLY)

    response = _extent(dashboard, '1at9', '?chains=A,Z')

    assert response.status_code == 400
    error = response.get_json()['error']
    assert 'Z' in error and 'no chain' in error.lower(), error
    assert 'A' in error and 'B' in error, 'the refusal names the chains the file does have'
