"""The Model pane's surface route: two meshes from a mapping, with no run and no GROMACS.

The route is a read of the molecule folder plus the mapping's bead list, so the fixtures are the repository's own DDM
molecule and a hand-written bead list. The numbers asserted are the published size-class radii and the caps the route
states; nothing here measures a trajectory or runs a tool.
"""
from __future__ import annotations

import math

import pytest
from detergent_validation.analysis.runs import mapped_surface

SURFACES = '/api/bonded-surfaces'

#: Two atom-bearing beads, one virtual site (which names no atom of its own) and one bead with no atoms at all.
BEADS = [
    {'name': 'B01', 'size': 'R', 'type': 'C1', 'atoms': [1, 2]},
    {'name': 'B02', 'size': 'S', 'type': 'SN6', 'atoms': [3]},
    {'name': 'VS', 'size': 'T', 'type': 'TC4', 'atoms': [],
     'virtual_site': {'function': 1, 'parents': ['B01', 'B02']}},
    {'name': 'EMPTY', 'size': 'T', 'type': 'TC4', 'atoms': []},
]


def _finite(vertices):
    return bool(vertices) and all(math.isfinite(value) for vertex in vertices for value in vertex)


def _rounded(vertices):
    return all(value == round(value, 5) for vertex in vertices for value in vertex)


def test_the_two_surfaces_come_back_non_empty_and_finite(dashboard):
    response = dashboard.client.post(SURFACES, json={'molecule_id': 'DDM', 'beads': BEADS})

    assert response.status_code == 200, response.get_data(as_text=True)
    body = response.get_json()
    assert body['probe_nm'] == pytest.approx(0.191)
    assert body['spacing_nm'] >= mapped_surface.DEFAULT_SPACING_NM
    for side in ('aa', 'cg'):
        assert _finite(body[side]['vertices']), side
        assert body[side]['faces'], side
        assert _rounded(body[side]['vertices']), side
    assert body['aa']['atom_count'] > 0
    assert body['cg']['bead_count'] == 2


def test_cg_beads_carry_the_published_size_class_radius_and_a_centred_atom_mean(dashboard):
    body = dashboard.client.post(SURFACES, json={'molecule_id': 'DDM', 'beads': BEADS}).get_json()

    assert [bead['name'] for bead in body['cg']['beads']] == ['B01', 'B02']
    assert [bead['size'] for bead in body['cg']['beads']] == ['R', 'S']
    assert [bead['radius_nm'] for bead in body['cg']['beads']] == [0.264, 0.230]
    for bead in body['cg']['beads']:
        assert len(bead['centre_nm']) == 3
        assert all(math.isfinite(value) for value in bead['centre_nm'])


def test_a_virtual_site_and_an_empty_bead_own_no_sphere(dashboard):
    body = dashboard.client.post(SURFACES, json={'molecule_id': 'DDM', 'beads': BEADS}).get_json()

    names = [bead['name'] for bead in body['cg']['beads']]
    assert 'VS' not in names and 'EMPTY' not in names
    assert body['cg']['bead_count'] == 2


def test_a_missing_molecule_is_a_400(dashboard):
    response = dashboard.client.post(SURFACES, json={'molecule_id': 'NoSuchMolecule', 'beads': []})

    assert response.status_code == 400


def test_a_bead_list_that_is_not_a_list_is_a_400(dashboard):
    response = dashboard.client.post(SURFACES, json={'molecule_id': 'DDM', 'beads': {}})

    assert response.status_code == 400


def test_an_oversized_bead_list_is_a_400_naming_the_cap(dashboard):
    response = dashboard.client.post(SURFACES, json={'molecule_id': 'DDM',
                                                     'beads': [{} for _ in range(mapped_surface.MAX_BEADS + 1)]})

    assert response.status_code == 400
    assert str(mapped_surface.MAX_BEADS) in response.get_data(as_text=True)


def test_a_ring_scale_dilates_the_cg_ring_and_leaves_the_aa_mesh_alone(dashboard):
    """The CG ring is drawn at the ring scale the table states; an atom is not stretched by a constraint target."""
    plain = dashboard.client.post(SURFACES, json={'molecule_id': 'DDM', 'beads': BEADS}).get_json()
    scaled = dashboard.client.post(SURFACES, json={
        'molecule_id': 'DDM', 'beads': BEADS, 'rings': [{'beads': ['B01', 'B02'], 'scale': 2.0}]}).get_json()

    def centres(body):
        return {bead['name']: bead['centre_nm'] for bead in body['cg']['beads']}

    assert math.dist(centres(scaled)['B01'], centres(scaled)['B02']) == pytest.approx(
        2 * math.dist(centres(plain)['B01'], centres(plain)['B02']), rel=1e-4)
    assert scaled['aa']['vertices'] == plain['aa']['vertices'], 'a ring scale is not an atomistic fact'
    assert scaled['cg']['rings'] == [{'beads': ['B01', 'B02'], 'scale': 2.0}]


def test_a_scaled_ring_carries_its_connected_parts_so_the_mapped_links_hold(dashboard):
    """Dilating a ring would lengthen every link out of it; the placement shifts the other parts back, as a run's do."""
    beads = [*BEADS, {'name': 'TAIL', 'size': 'S', 'type': 'C1', 'atoms': [4]}]
    connections = [['B01', 'TAIL']]
    plain = dashboard.client.post(SURFACES, json={
        'molecule_id': 'DDM', 'beads': beads, 'connections': connections}).get_json()
    scaled = dashboard.client.post(SURFACES, json={
        'molecule_id': 'DDM', 'beads': beads, 'connections': connections,
        'rings': [{'beads': ['B01', 'B02'], 'scale': 2.0}]}).get_json()

    def length(body, first, second):
        centres = {bead['name']: bead['centre_nm'] for bead in body['cg']['beads']}
        return math.dist(centres[first], centres[second])

    assert length(scaled, 'B01', 'B02') == pytest.approx(2 * length(plain, 'B01', 'B02'), rel=1e-4)
    assert length(scaled, 'B01', 'TAIL') == pytest.approx(length(plain, 'B01', 'TAIL'), rel=1e-4)


def test_a_malformed_ring_or_connection_is_a_400(dashboard):
    for extra in ({'rings': [{'beads': ['B01'], 'scale': 1.1}]},
                  {'rings': [{'beads': ['B01', 'B02'], 'scale': -1}]},
                  {'rings': [{'beads': ['B01', 'B02'], 'scale': True}]},
                  {'connections': [['B01']]}):
        response = dashboard.client.post(SURFACES, json={'molecule_id': 'DDM', 'beads': BEADS, **extra})
        assert response.status_code == 400, extra

