from dashboard.app import default_coordinator as web
from dashboard.models import mappings


def test_mapping_context_lists_valid_molecule_and_scene(isolated_workspace):
    client = web.app.test_client()
    response = client.get('/api/mappings/context?molecule_id=DDM')
    assert response.status_code == 200
    assert response.json['context']['molecule_id'] == 'DDM'
    assert response.json['scene']['svg'].startswith('<svg')
    assert response.json['context']['atoms']


def test_validation_catalog_exposes_modes_tiers_and_cited_targets(isolated_workspace):
    client = web.app.test_client()
    representations = client.get('/api/mappings/representations')
    assert representations.status_code == 200
    assert {item['id'] for item in representations.json['representations']} == {'tc4', 'physical_only_ring_constrained'}
    assert {item['id'] for item in representations.json['tiers']} == {'setup', 'evidence'}
    targets = client.get('/api/mappings/validation-targets?molecule_id=Maltose')
    assert targets.status_code == 200
    assert targets.json['datasets'][0]['citation']


def test_validation_queue_rejects_unknown_representation(isolated_workspace):
    client = web.app.test_client()
    owner = web
    owner.database().insert({'id': '123456abcdef', 'status': 'completed', 'molecule_id': 'Maltose', 'detergent': 'Maltose'})
    mapping = mappings.automatic_candidate(mappings.molecule(), 'Maltose')
    response = client.post('/api/jobs/123456abcdef/carbohydrate-validation', json={
        'molecule_id': 'Maltose', 'mapping_snapshot': mapping,
        'representation_mode': 'unknown', 'tier': 'setup', 'target_dataset_id': 'maltose-pilot-v1'})
    assert response.status_code == 400


def test_dashboard_contains_validation_controls(isolated_workspace):
    html = web.app.test_client().get('/').get_data(as_text=True)
    assert 'id="validation-representation"' in html
    assert 'id="validation-tier"' in html
    assert 'id="launch-carbohydrate-validation"' in html


def test_automatic_preview_has_no_saved_candidate(isolated_workspace):
    client = web.app.test_client()
    context = client.get('/api/mappings/context?molecule_id=DDM').json['context']
    before = sorted(isolated_workspace.mapping_drafts.glob('*.json'))
    response = client.post('/api/mappings/automatic/preview', json={'molecule_id': 'DDM', 'molecule_snapshot': context['snapshot']})
    assert response.status_code == 200
    assert response.json['available']
    assert sorted(isolated_workspace.mapping_drafts.glob('*.json')) == before


def test_stale_mapping_context_is_rejected(isolated_workspace):
    client = web.app.test_client()
    context = client.get('/api/mappings/context?molecule_id=DDM').json['context']
    response = client.post('/api/mappings/automatic/preview', json={'molecule_id': 'DDM', 'molecule_snapshot': {'snapshot_sha256': 'stale'}})
    assert response.status_code == 409


def test_mapping_validation_reports_duplicate_content_without_matching_name(isolated_workspace):
    client = web.app.test_client()
    context = client.get('/api/mappings/context?molecule_id=DDM').json['context']
    preview = client.post('/api/mappings/automatic/preview', json={
        'molecule_id': 'DDM', 'molecule_snapshot': context['snapshot']}).json['candidate']
    saved = client.post('/api/mappings/drafts', json=preview)
    assert saved.status_code == 201
    renamed = {**saved.json, 'name': 'A different label'}
    result = client.post('/api/mappings/validate', json=renamed)
    assert result.status_code == 200
    assert result.json['duplicate_file'] == saved.json['file']


def test_suggestion_and_ring_site_endpoints(isolated_workspace):
    client = web.app.test_client()
    context = client.get('/api/mappings/context?molecule_id=DDM').json['context']
    suggestion = client.post('/api/mappings/suggest-bead', json={'molecule_id': 'DDM', 'molecule_snapshot': context['snapshot'], 'atom_ids': [1, 2, 3]} )
    assert suggestion.status_code == 200
    assert suggestion.json['suggestions']
    ring = client.post('/api/mappings/ring-site/preview', json={'molecule_id': 'DDM', 'molecule_snapshot': context['snapshot'], 'mapping': {'beads': [{'name': 'A', 'size': 'S', 'atoms': [1]}, {'name': 'B', 'size': 'S', 'atoms': [2]}, {'name': 'C', 'size': 'S', 'atoms': [3]}]}, 'parents': ['A', 'B', 'C']})
    assert ring.status_code == 200
    assert ring.json['bead']['type'] == 'TC4'
