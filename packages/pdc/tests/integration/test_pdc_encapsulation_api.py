"""The encapsulation endpoint the new-run panel calls: the numbers, the method and the caveat.

The route's job is to be honest about what it can and cannot size. A protein whose structure states no membrane has
no slab, so it is refused with a reason rather than given a default; a detergent with no saved mapping has no free-end
tail bead, so it too is refused. The structure and the mapping are built here -- a hand-made PDB imported through the
real import path, and a hand-made mapping -- so nothing touches the developer's workspace.
"""
from __future__ import annotations

import math

import pytest

from tests.harness.pdc_fixtures import mapping_candidate

# Three atoms far enough apart (0.9 nm between the two carbons, with probe-inflated radii of 0.366 nm) that each
# contributes exactly its own sphere area: the route's area is known by construction, not by a fixture's history.
MEMBRANE = ('REMARK      1/2 of bilayer thickness:   10.0\n'
            'ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\n'
            'ATOM      2  CA  ALA A   2       0.000   0.000   9.000  1.00  0.00           C\n'
            'ATOM      3  NZ  LYS A   3       0.000   0.000  30.000  1.00  0.00           N\n'
            'END\n')
# The same structure, thinner membrane: half-thickness 0.2 nm holds only the first atom.
THIN = MEMBRANE.replace('10.0', '2.0')
# A structure that states nothing about a membrane: the importer records no half-thickness for it.
ANNOTATION_FREE = MEMBRANE.replace('REMARK      1/2 of bilayer thickness:   10.0\n', '')

CARBON_SPHERE = 4 * math.pi * (0.175 + 0.191) ** 2      # one CA, as an isolated sphere, nm^2
# The fixture mapping's one free-end tail bead is TAIL1, an R bead: 2 * pi * 0.264^2 nm^2.
COVERAGE = 2 * math.pi * 0.264 ** 2


def _import(dashboard, monkeypatch, pdbid, text):
    monkeypatch.setitem(dashboard.app.config, 'PDC_FETCHER', lambda url, body=text: body.encode())
    return dashboard.client.post('/api/pdc/proteins/import', json={'pdbid': pdbid})


def _url(entry, molecule_id='DDM', aggregation_number=150, mapping=None):
    url = f'/api/pdc/proteins/{entry}/encapsulation?molecule_id={molecule_id}&aggregation_number={aggregation_number}'
    return url if mapping is None else url + f'&mapping={mapping}'


def test_the_estimate_comes_back_with_its_numbers_its_method_and_its_caveat(dashboard, monkeypatch):
    _import(dashboard, monkeypatch, '1qj8', MEMBRANE)
    mapping_candidate(dashboard)

    response = dashboard.client.get(_url('1qj8'))

    assert response.status_code == 200, response.get_data(as_text=True)
    body = response.get_json()
    assert body['apolar_area_nm2'] == pytest.approx(2 * CARBON_SPHERE)
    assert body['coverage_area_nm2'] == pytest.approx(COVERAGE), \
        'the free-end tail bead is the fixture mapping\u2019s one R-bead leaf'
    assert body['coverage_radii_nm'] == [0.264] and body['tail_ends'] == 1
    assert body['needed'] == pytest.approx(2 * CARBON_SPHERE / COVERAGE)
    assert body['requested'] == 150
    assert body['fraction'] == pytest.approx(150 / body['needed'])
    assert 'Shrake-Rupley' in body['method'] and 'free-end tail bead' in body['method']
    assert 'flat surface' in body['caveat'] and 'roughly the right order' in body['caveat']
    # The panel's bubble reads the short form; the long method travels beside it, so the two never have to agree on a
    # single string and shortening what is displayed does not delete what the route states.
    assert 'free-end tail bead' in body['method_summary'] and 'No simulation' in body['method_summary']
    assert body['method_summary'] != body['method']
    assert 'head_radius_nm' not in body and 'head_area_nm2' not in body


def test_the_route_s_method_says_apolar_parented_modified_residues_are_folded_in(dashboard, monkeypatch):
    """The route returns the prose beside the number; that prose must state the modified-residue folding so a reader
    of the panel is told what the arithmetic did."""
    _import(dashboard, monkeypatch, '1qj8', MEMBRANE)
    mapping_candidate(dashboard)

    method = dashboard.client.get(_url('1qj8')).get_json()['method']

    assert 'modified residue' in method
    assert 'apolar parent' in method
    assert 'MSE' in method


def test_the_slab_the_route_uses_is_the_thickness_the_protein_states(dashboard, monkeypatch):
    """Two structures, two stated thicknesses, two areas -- the slab is read, not assumed."""
    _import(dashboard, monkeypatch, '1qj8', MEMBRANE)
    _import(dashboard, monkeypatch, '2abc', THIN)
    mapping_candidate(dashboard)

    wide = dashboard.client.get(_url('1qj8')).get_json()
    narrow = dashboard.client.get(_url('2abc')).get_json()

    assert wide['apolar_area_nm2'] == pytest.approx(2 * CARBON_SPHERE)
    assert narrow['apolar_area_nm2'] == pytest.approx(CARBON_SPHERE)
    assert narrow['slab']['half_thickness_nm'] == 0.2


def test_a_protein_that_states_no_membrane_is_refused_with_a_reason(dashboard, monkeypatch):
    """The plan's acceptance: no membrane annotation means no slab, and a made-up slab is worse than a refusal."""
    _import(dashboard, monkeypatch, '3def', ANNOTATION_FREE)
    mapping_candidate(dashboard)

    response = dashboard.client.get(_url('3def'))

    assert response.status_code == 400
    assert 'membrane' in response.get_json()['error']
    assert 'slab' in response.get_json()['error']


def test_a_detergent_with_no_saved_mapping_is_refused_with_a_reason(dashboard, monkeypatch):
    _import(dashboard, monkeypatch, '1qj8', MEMBRANE)

    response = dashboard.client.get(_url('1qj8', molecule_id='NOTMAPPED'))

    assert response.status_code == 400
    assert 'NOTMAPPED' in response.get_json()['error']
    assert 'mapping' in response.get_json()['error']


def test_a_mapping_whose_tail_has_no_free_end_is_refused_with_a_reason(dashboard, monkeypatch):
    """A ring of tail beads has no leaf, so there is no hemisphere to sum and no coverage area to divide by."""
    _import(dashboard, monkeypatch, '1qj8', MEMBRANE)
    tail = [{'name': name, 'type': 'C1', 'size': 'R', 'atoms': [index]}
            for index, name in enumerate(('TAIL1', 'TAIL2', 'TAIL3'), start=1)]
    mapping_candidate(dashboard, beads=tail,
                      connections=[['TAIL1', 'TAIL2'], ['TAIL2', 'TAIL3'], ['TAIL3', 'TAIL1']])

    response = dashboard.client.get(_url('1qj8'))

    assert response.status_code == 400
    assert 'free-end tail' in response.get_json()['error']


def test_a_mapping_that_states_no_connections_is_refused_with_a_reason(dashboard, monkeypatch):
    """With no connectivity the route cannot say which tail bead is an end, so it refuses rather than guessing."""
    _import(dashboard, monkeypatch, '1qj8', MEMBRANE)
    mapping_candidate(dashboard, connections=[])

    response = dashboard.client.get(_url('1qj8'))

    assert response.status_code == 400
    assert 'connections' in response.get_json()['error']


def test_saved_mappings_that_disagree_about_the_coverage_area_are_refused(dashboard, monkeypatch):
    """Two saved mappings, two coverage areas: the route refuses rather than picking one silently."""
    _import(dashboard, monkeypatch, '1qj8', MEMBRANE)
    mapping_candidate(dashboard)
    mapping_candidate(dashboard, name='mapping_candidate_second.json',
                      beads=[{'name': 'TAIL1', 'type': 'SC1', 'size': 'S', 'atoms': [1]},
                             {'name': 'HEAD', 'type': 'P1', 'size': 'R', 'atoms': [2]}],
                      connections=[['TAIL1', 'HEAD']])

    response = dashboard.client.get(_url('1qj8'))

    assert response.status_code == 400
    error = response.get_json()['error']
    assert 'disagree' in error and '0.438' in error and '0.332' in error, error


def test_a_named_mapping_is_the_one_the_estimate_sizes(dashboard, monkeypatch):
    """The form's selected mapping decides the area: two saved candidates may disagree and the chosen one is used.

    A molecule's saved drafts can differ about a tail bead's size class (LMNG's end beads are R in one revision and
    S in another). With no mapping named the route refuses to pick; with one named -- the model the run will build
    from -- that mapping's own free-end beads are what is summed.
    """
    _import(dashboard, monkeypatch, '1qj8', MEMBRANE)
    mapping_candidate(dashboard)
    second = 'mapping_candidate_second.json'
    mapping_candidate(dashboard, name=second,
                      beads=[{'name': 'TAIL1', 'type': 'SC1', 'size': 'S', 'atoms': [1]},
                             {'name': 'HEAD', 'type': 'P1', 'size': 'R', 'atoms': [2]}],
                      connections=[['TAIL1', 'HEAD']])

    assert dashboard.client.get(_url('1qj8')).status_code == 400, 'unnamed, the disagreement is stated'
    chosen = dashboard.client.get(_url('1qj8', mapping=second))

    assert chosen.status_code == 200, chosen.get_data(as_text=True)
    body = chosen.get_json()
    assert body['mappings'] == [second]
    assert body['coverage_radii_nm'] == [0.230] and body['tail_ends'] == 1
    assert body['coverage_area_nm2'] == pytest.approx(2 * math.pi * 0.230 ** 2)


def test_a_named_mapping_the_molecule_does_not_hold_is_refused(dashboard, monkeypatch):
    _import(dashboard, monkeypatch, '1qj8', MEMBRANE)
    mapping_candidate(dashboard)

    response = dashboard.client.get(_url('1qj8', mapping='mapping_candidate_missing.json'))

    assert response.status_code == 400
    error = response.get_json()['error']
    assert 'mapping_candidate_missing.json' in error and 'no saved mapping' in error


def test_an_unknown_protein_entry_is_a_404(dashboard, monkeypatch):
    mapping_candidate(dashboard)

    assert dashboard.client.get(_url('nosuch')).status_code == 404


def test_a_request_without_a_detergent_or_a_count_is_refused(dashboard, monkeypatch):
    _import(dashboard, monkeypatch, '1qj8', MEMBRANE)
    mapping_candidate(dashboard)

    assert dashboard.client.get('/api/pdc/proteins/1qj8/encapsulation').status_code == 400
    assert dashboard.client.get(_url('1qj8', aggregation_number=0)).status_code == 400
    assert dashboard.client.get(_url('1qj8', aggregation_number='lots')).status_code == 400


def test_the_entry_can_be_addressed_by_the_catalogue_id_a_panel_sends(dashboard, monkeypatch):
    """The panel sends the option's value, which is the entry's id -- a path.

    A path is not a natural URL segment: an absolute id loses its leading slash on the way through the URL, so the
    spelling that reaches the route is the id without it. The catalogue's own name resolves too, which the other
    tests use.
    """
    _import(dashboard, monkeypatch, '1qj8', MEMBRANE)
    mapping_candidate(dashboard)
    entry = next(item for item in dashboard.client.get('/api/pdc/catalog').get_json()['proteins']
                 if item['name'] == '1qj8')
    assert entry['id'].startswith('/'), 'an imported structure lives outside the repository, so its id is absolute'

    response = dashboard.client.get(_url(entry['id'].lstrip('/')))

    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json()['atoms'] == 3
    assert response.get_json()['protein']['id'] == entry['id']


# --- the chain selection: an assembly can be sized as the object that will be simulated ---------------------------

# Two subunits, each two apolar atoms inside a 1.0 nm slab and 0.9 nm apart, and the two subunits 10 nm apart so
# neither occludes the other: the areas are additive and known by construction.
ASSEMBLY = (
    'REMARK      1/2 of bilayer thickness:   10.0\n'
    'ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\n'
    'ATOM      2  CA  ALA A   2       0.000   0.000   9.000  1.00  0.00           C\n'
    'ATOM      3  CA  LEU B   1     100.000   0.000   0.000  1.00  0.00           C\n'
    'ATOM      4  CA  LEU B   2     100.000   0.000   9.000  1.00  0.00           C\n'
    'END\n')


def test_the_route_sizes_only_the_chains_the_caller_selected(dashboard, monkeypatch):
    _import(dashboard, monkeypatch, '1at9', ASSEMBLY)
    mapping_candidate(dashboard)

    whole = dashboard.client.get(_url('1at9')).get_json()
    one = dashboard.client.get(_url('1at9') + '&chains=A').get_json()

    assert whole['atoms'] == 4 and one['atoms'] == 2, 'the other subunit never reaches the surface'
    assert whole['apolar_area_nm2'] == pytest.approx(2 * one['apolar_area_nm2'], rel=1e-4)
    assert one['chains'] == {'selected': ['A'], 'available': ['A', 'B'], 'narrowed': True}
    assert whole['chains'] == {'selected': 'all', 'available': ['A', 'B'], 'narrowed': False}, \
        'an existing caller asks for nothing and keeps the whole file'


def test_a_chain_the_protein_does_not_have_is_refused_with_a_reason(dashboard, monkeypatch):
    _import(dashboard, monkeypatch, '1at9', ASSEMBLY)
    mapping_candidate(dashboard)

    response = dashboard.client.get(_url('1at9') + '&chains=A,Z')

    assert response.status_code == 400
    error = response.get_json()['error']
    assert 'Z' in error and 'no chain' in error.lower(), error


# Like 1AT9: a chain-less placeholder HETATM beside the subunits. The whole-file estimate counts it, so selecting
# every declared chain must be the whole file -- and only a strict subset may drop it. This is the 1AT9 acceptance
# in miniature: A alone is a strict subset and is smaller; A+B is every chain and is the file.
WITH_PLACEHOLDER = (
    'REMARK      1/2 of bilayer thickness:   10.0\n'
    'ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\n'
    'ATOM      2  CA  ALA A   2       0.000   0.000   9.000  1.00  0.00           C\n'
    'ATOM      3  CA  LEU B   1     100.000   0.000   0.000  1.00  0.00           C\n'
    'ATOM      4  CA  LEU B   2     100.000   0.000   9.000  1.00  0.00           C\n'
    'HETATM    5  O   DUM     1      50.000   0.000   0.000  1.00  0.00           O\n'
    'END\n')


def test_naming_every_declared_chain_is_the_whole_file(dashboard, monkeypatch):
    """The panel's default selection is every chain; its estimate must be the whole-file number, unchanged."""
    _import(dashboard, monkeypatch, '1at9', WITH_PLACEHOLDER)
    mapping_candidate(dashboard)

    whole = dashboard.client.get(_url('1at9')).get_json()
    every = dashboard.client.get(_url('1at9') + '&chains=A,B').get_json()
    one = dashboard.client.get(_url('1at9') + '&chains=A').get_json()

    assert every['atoms'] == whole['atoms'] == 5
    assert every['apolar_area_nm2'] == pytest.approx(whole['apolar_area_nm2'])
    assert every['chains']['narrowed'] is False
    assert one['atoms'] == 2 and one['chains']['narrowed'] is True


def test_a_multi_chain_selection_is_a_comma_separated_list_the_route_reads(dashboard, monkeypatch):
    _import(dashboard, monkeypatch, '1at9', ASSEMBLY)
    mapping_candidate(dashboard)

    both = dashboard.client.get(_url('1at9') + '&chains=A,B').get_json()
    single = dashboard.client.get(_url('1at9') + '&chains=B').get_json()

    assert both['atoms'] == 4 and both['chains']['selected'] == ['A', 'B']
    assert both['apolar_area_nm2'] == pytest.approx(single['apolar_area_nm2'] / 0.5, rel=1e-4)
