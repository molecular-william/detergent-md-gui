"""Deleting one stored conformation library through the panel's own route.

A stored library is a pinned input, so the route requires a browser confirm and refuses a key that is not the store's
16-hex form; a key the store does not hold is a missing file, not a bad request. The library built here is the real
one: a completed, protein-free pdc run under the test workspace, resolved from the same mapping digest a run records.
"""
from __future__ import annotations

import json
from pathlib import Path

from dashboard import files
from detergent_pdc import conformations

from tests.harness import conformation_fixtures
from tests.harness.pdc_fixtures import library_mapping

MAPPING = 'mapping_candidate_delete.json'
SOURCE_RUN = 'b920391735dd'


def save_mapping(workspace):
    """The saved mapping a source run records by digest, written where the store reads candidates."""
    directory = Path(workspace) / 'mapping_drafts'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / MAPPING
    path.write_text(json.dumps(library_mapping()))
    return path


def stored_library(dashboard, *, size=2, run_id=SOURCE_RUN):
    """One verified library in the test workspace, built from a run that names its mapping's digest."""
    mapping = save_mapping(dashboard.paths.workspace)
    conformation_fixtures.run_tree(dashboard.paths.workspace, run_id=run_id,
                                   mapping_sha256=files.sha256(mapping))
    return conformations.resolve(dashboard.paths.workspace, {'runs': [run_id], 'size': size, 'seed': 0})


def delete_route(key):
    return f'/api/pdc/conformations/libraries/{key}'


def test_deleting_a_library_removes_only_that_directory(dashboard):
    first = stored_library(dashboard, size=2)
    second = stored_library(dashboard, size=1)
    assert first.key != second.key

    response = dashboard.client.delete(delete_route(first.key), json={'confirm': True})

    assert response.status_code == 200, response.data
    assert response.json == {'deleted': first.key, 'residue': 'DDM', 'path': str(first.path)}
    assert not first.path.parent.exists()
    assert second.path.parent.is_dir(), 'a sibling library is another detergent shape and stays'
    listed = dashboard.client.get('/api/pdc/conformations/libraries').get_json()['libraries']
    assert [entry['key'] for entry in listed] == [second.key]


def test_a_deletion_needs_confirmation(dashboard):
    library = stored_library(dashboard)

    for body in ({}, {'confirm': False}, {'confirm': 'yes'}, {'other': True}):
        response = dashboard.client.delete(delete_route(library.key), json=body)
        assert response.status_code == 400, body
        assert 'confirmation' in response.json['error']
    assert dashboard.client.delete(delete_route(library.key)).status_code == 400
    assert library.path.is_file(), 'a refused delete removed nothing'


def test_a_key_that_is_not_the_stores_form_is_a_400(dashboard):
    stored_library(dashboard)

    for bad in ('not-a-key', '0' * 15, '0' * 17, 'g' * 16, 'ABC'):
        response = dashboard.client.delete(delete_route(bad), json={'confirm': True})
        assert response.status_code == 400, bad
        assert '16 hexadecimal' in response.json['error']


def test_an_unknown_key_is_a_404(dashboard):
    stored_library(dashboard)

    response = dashboard.client.delete(delete_route('0' * 16), json={'confirm': True})

    assert response.status_code == 404
    assert '0' * 16 in response.json['error']
