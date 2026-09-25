from dashboard.models import mappings


def test_mapping_context_lists_valid_molecule_and_scene(dashboard):
    client = dashboard.client
    response = client.get('/api/mappings/context?molecule_id=DDM')
    assert response.status_code == 200
    assert response.json['context']['molecule_id'] == 'DDM'
    assert response.json['scene']['svg'].startswith('<svg')
    assert response.json['context']['atoms']


def test_validation_catalog_exposes_modes_tiers_and_cited_targets(dashboard):
    client = dashboard.client
    representations = client.get('/api/mappings/representations')
    assert representations.status_code == 200
    assert {item['id'] for item in representations.json['representations']} == {'tc4', 'physical_only_ring_constrained'}
    assert {item['id'] for item in representations.json['tiers']} == {'setup', 'evidence'}
    targets = client.get('/api/mappings/validation-targets?molecule_id=Maltose')
    assert targets.status_code == 200
    assert targets.json['datasets'][0]['citation']
    sucrose = client.get('/api/mappings/validation-targets?molecule_id=Sucrose')
    assert sucrose.status_code == 200
    assert sucrose.json['datasets'][0]['id'] == 'sucrose-martini3-paper-v1'


def test_validation_queue_rejects_unknown_representation(dashboard):
    client = dashboard.client
    owner = dashboard.coordinator
    owner.database().insert({'id': '123456abcdef', 'status': 'completed', 'molecule_id': 'Maltose', 'detergent': 'Maltose'})
    mapping = mappings.automatic_candidate(mappings.molecule(), 'Maltose')
    response = client.post('/api/jobs/123456abcdef/carbohydrate-validation', json={
        'molecule_id': 'Maltose', 'mapping_snapshot': mapping,
        'representation_mode': 'unknown', 'tier': 'setup', 'target_dataset_id': 'maltose-pilot-v1'})
    assert response.status_code == 400


def test_dashboard_contains_validation_controls(dashboard):
    html = dashboard.client.get('/').get_data(as_text=True)
    assert 'id="validation-representation"' in html
    assert 'id="validation-tier"' in html
    assert 'id="launch-carbohydrate-validation"' in html


def test_automatic_preview_has_no_saved_candidate(dashboard):
    client = dashboard.client
    context = client.get('/api/mappings/context?molecule_id=DDM').json['context']
    before = sorted(dashboard.paths.mapping_drafts.glob('*.json'))
    response = client.post('/api/mappings/automatic/preview', json={'molecule_id': 'DDM', 'molecule_snapshot': context['snapshot']})
    assert response.status_code == 200
    assert response.json['available']
    assert sorted(dashboard.paths.mapping_drafts.glob('*.json')) == before


def test_stale_mapping_context_is_rejected(dashboard):
    client = dashboard.client
    context = client.get('/api/mappings/context?molecule_id=DDM').json['context']
    response = client.post('/api/mappings/automatic/preview', json={'molecule_id': 'DDM', 'molecule_snapshot': {'snapshot_sha256': 'stale'}})
    assert response.status_code == 409


def test_mapping_validation_reports_duplicate_content_without_matching_name(dashboard):
    client = dashboard.client
    context = client.get('/api/mappings/context?molecule_id=DDM').json['context']
    preview = client.post('/api/mappings/automatic/preview', json={
        'molecule_id': 'DDM', 'molecule_snapshot': context['snapshot']}).json['candidate']
    saved = client.post('/api/mappings/drafts', json=preview)
    assert saved.status_code == 201
    renamed = {**saved.json, 'name': 'A different label'}
    result = client.post('/api/mappings/validate', json=renamed)
    assert result.status_code == 200
    assert result.json['duplicate_file'] == saved.json['file']


def test_suggestion_and_ring_site_endpoints(dashboard):
    client = dashboard.client
    context = client.get('/api/mappings/context?molecule_id=DDM').json['context']
    suggestion = client.post('/api/mappings/suggest-bead', json={'molecule_id': 'DDM', 'molecule_snapshot': context['snapshot'], 'atom_ids': [1, 2, 3]} )
    assert suggestion.status_code == 200
    assert suggestion.json['suggestions']
    ring = client.post('/api/mappings/ring-site/preview', json={'molecule_id': 'DDM', 'molecule_snapshot': context['snapshot'], 'mapping': {'beads': [{'name': 'A', 'size': 'S', 'atoms': [1]}, {'name': 'B', 'size': 'S', 'atoms': [2]}, {'name': 'C', 'size': 'S', 'atoms': [3]}]}, 'parents': ['A', 'B', 'C']})
    assert ring.status_code == 200
    assert ring.json['bead']['type'] == 'TC4'


def test_the_draft_delete_route_defers_to_the_store(dashboard):
    """The store's validator decides what may be unlinked, not a route-level pattern.

    A name that escapes the drafts root comes back as a refusal either way -- Werkzeug may
    not even route an encoded slash to this endpoint -- so the assertion is that nothing
    outside the root is touched, and the store-level refusal is pinned in
    tests/dashboard/unit/test_draft_storage_layout.py.
    """
    from urllib.parse import quote
    client = dashboard.client
    root = mappings.storage_root(); root.mkdir(parents=True, exist_ok=True)
    outside = root.parent / 'outside.json'; outside.write_text('outside')
    draft = root / 'mapping_candidate_route.json'; draft.write_text('{}')
    assert client.delete('/api/mappings/drafts/mapping_candidate_route.json').status_code == 200
    assert not draft.exists()
    assert client.delete('/api/mappings/drafts/mapping_candidate_route.json').status_code == 404
    refused = client.delete('/api/mappings/drafts/' + quote('../outside.json', safe=''))
    assert refused.status_code in (400, 404)
    assert outside.read_text() == 'outside'
