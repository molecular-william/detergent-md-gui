"""The encapsulation endpoint the new-run panel calls: the numbers, the method and the caveat.

The route's job is to be honest about what it can and cannot size. A protein whose structure states no membrane has
no slab, so it is refused with a reason rather than given a default; a detergent with no saved mapping has no head
bead size class, so it too is refused. The structure and the mapping are built here -- a hand-made PDB imported
through the real import path, and a hand-made mapping -- so nothing touches the developer's workspace.
"""
from __future__ import annotations

import json
import math

import pytest

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


def _import(dashboard, monkeypatch, pdbid, text):
    monkeypatch.setitem(dashboard.app.config, 'PDC_FETCHER', lambda url, body=text: body.encode())
    return dashboard.client.post('/api/pdc/proteins/import', json={'pdbid': pdbid})


def _mapping(dashboard, molecule_id='DDM', beads=None, name='mapping_candidate_fixture.json'):
    directory = dashboard.paths.mapping_drafts
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(json.dumps({
        'schema_version': 3, 'molecule_id': molecule_id, 'name': 'a test detergent mapping',
        'beads': beads if beads is not None else [
            {'name': 'TAIL1', 'type': 'C1', 'size': 'R', 'atoms': [1]},
            {'name': 'TAIL2', 'type': 'C1', 'size': 'R', 'atoms': [2]},
            {'name': 'S1A', 'type': 'SP1r', 'size': 'S', 'atoms': [3]},
            {'name': 'S1VS', 'type': 'TC4', 'size': 'T', 'atoms': [],
             'virtual_site': {'function': 1, 'parents': ['TAIL2', 'S1A']}},
        ],
        'connections': [['TAIL1', 'TAIL2'], ['TAIL2', 'S1A']],
        'provenance': {'origin': 'manual', 'algorithm': None, 'references': []},
        'status': 'candidate-unvalidated', 'martini_version': '3'}))
    return name


def _url(entry, molecule_id='DDM', aggregation_number=150):
    return f'/api/pdc/proteins/{entry}/encapsulation?molecule_id={molecule_id}&aggregation_number={aggregation_number}'


def test_the_estimate_comes_back_with_its_numbers_its_method_and_its_caveat(dashboard, monkeypatch):
    _import(dashboard, monkeypatch, '1qj8', MEMBRANE)
    _mapping(dashboard)

    response = dashboard.client.get(_url('1qj8'))

    assert response.status_code == 200, response.get_data(as_text=True)
    body = response.get_json()
    assert body['apolar_area_nm2'] == pytest.approx(2 * CARBON_SPHERE)
    assert body['head_radius_nm'] == 0.230, 'the head bead is the small sugar bead the mapping records'
    assert body['head_area_nm2'] == pytest.approx(math.pi * 0.230 ** 2)
    assert body['needed'] == pytest.approx(2 * CARBON_SPHERE / (math.pi * 0.230 ** 2))
    assert body['requested'] == 150
    assert body['fraction'] == pytest.approx(150 / body['needed'])
    assert 'Shrake-Rupley' in body['method'] and 'largest head bead' in body['method']
    assert 'flat surface' in body['caveat'] and 'roughly the right order' in body['caveat']


def test_the_route_s_method_says_apolar_parented_modified_residues_are_folded_in(dashboard, monkeypatch):
    """The route returns the prose beside the number; that prose must state the modified-residue folding so a reader
    of the panel is told what the arithmetic did."""
    _import(dashboard, monkeypatch, '1qj8', MEMBRANE)
    _mapping(dashboard)

    method = dashboard.client.get(_url('1qj8')).get_json()['method']

    assert 'modified residue' in method
    assert 'apolar parent' in method
    assert 'MSE' in method


def test_the_slab_the_route_uses_is_the_thickness_the_protein_states(dashboard, monkeypatch):
    """Two structures, two stated thicknesses, two areas -- the slab is read, not assumed."""
    _import(dashboard, monkeypatch, '1qj8', MEMBRANE)
    _import(dashboard, monkeypatch, '2abc', THIN)
    _mapping(dashboard)

    wide = dashboard.client.get(_url('1qj8')).get_json()
    narrow = dashboard.client.get(_url('2abc')).get_json()

    assert wide['apolar_area_nm2'] == pytest.approx(2 * CARBON_SPHERE)
    assert narrow['apolar_area_nm2'] == pytest.approx(CARBON_SPHERE)
    assert narrow['slab']['half_thickness_nm'] == 0.2


def test_a_protein_that_states_no_membrane_is_refused_with_a_reason(dashboard, monkeypatch):
    """The plan's acceptance: no membrane annotation means no slab, and a made-up slab is worse than a refusal."""
    _import(dashboard, monkeypatch, '3def', ANNOTATION_FREE)
    _mapping(dashboard)

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


def test_a_mapping_that_names_no_head_bead_is_refused_with_a_reason(dashboard, monkeypatch):
    """Every physical bead of the aliphatic carbon series: there is no head size class to resolve."""
    _import(dashboard, monkeypatch, '1qj8', MEMBRANE)
    _mapping(dashboard, beads=[{'name': 'TAIL1', 'type': 'C1', 'size': 'R', 'atoms': [1]}])

    response = dashboard.client.get(_url('1qj8'))

    assert response.status_code == 400
    assert 'head' in response.get_json()['error']


def test_saved_mappings_that_disagree_about_the_head_bead_are_refused(dashboard, monkeypatch):
    """Two saved mappings, two head sizes: the route refuses rather than picking one silently."""
    _import(dashboard, monkeypatch, '1qj8', MEMBRANE)
    _mapping(dashboard)
    _mapping(dashboard, name='mapping_candidate_second.json',
             beads=[{'name': 'TAIL1', 'type': 'C1', 'size': 'R', 'atoms': [1]},
                    {'name': 'HEAD', 'type': 'P1', 'size': 'R', 'atoms': [2]}])

    response = dashboard.client.get(_url('1qj8'))

    assert response.status_code == 400
    assert 'disagree' in response.get_json()['error']


def test_an_unknown_protein_entry_is_a_404(dashboard, monkeypatch):
    _mapping(dashboard)

    assert dashboard.client.get(_url('nosuch')).status_code == 404


def test_a_request_without_a_detergent_or_a_count_is_refused(dashboard, monkeypatch):
    _import(dashboard, monkeypatch, '1qj8', MEMBRANE)
    _mapping(dashboard)

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
    _mapping(dashboard)
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
    _mapping(dashboard)

    whole = dashboard.client.get(_url('1at9')).get_json()
    one = dashboard.client.get(_url('1at9') + '&chains=A').get_json()

    assert whole['atoms'] == 4 and one['atoms'] == 2, 'the other subunit never reaches the surface'
    assert whole['apolar_area_nm2'] == pytest.approx(2 * one['apolar_area_nm2'], rel=1e-4)
    assert one['chains'] == {'selected': ['A'], 'available': ['A', 'B'], 'narrowed': True}
    assert whole['chains'] == {'selected': 'all', 'available': ['A', 'B'], 'narrowed': False}, \
        'an existing caller asks for nothing and keeps the whole file'


def test_a_chain_the_protein_does_not_have_is_refused_with_a_reason(dashboard, monkeypatch):
    _import(dashboard, monkeypatch, '1at9', ASSEMBLY)
    _mapping(dashboard)

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
    _mapping(dashboard)

    whole = dashboard.client.get(_url('1at9')).get_json()
    every = dashboard.client.get(_url('1at9') + '&chains=A,B').get_json()
    one = dashboard.client.get(_url('1at9') + '&chains=A').get_json()

    assert every['atoms'] == whole['atoms'] == 5
    assert every['apolar_area_nm2'] == pytest.approx(whole['apolar_area_nm2'])
    assert every['chains']['narrowed'] is False
    assert one['atoms'] == 2 and one['chains']['narrowed'] is True


def test_a_multi_chain_selection_is_a_comma_separated_list_the_route_reads(dashboard, monkeypatch):
    _import(dashboard, monkeypatch, '1at9', ASSEMBLY)
    _mapping(dashboard)

    both = dashboard.client.get(_url('1at9') + '&chains=A,B').get_json()
    single = dashboard.client.get(_url('1at9') + '&chains=B').get_json()

    assert both['atoms'] == 4 and both['chains']['selected'] == ['A', 'B']
    assert both['apolar_area_nm2'] == pytest.approx(single['apolar_area_nm2'] / 0.5, rel=1e-4)
