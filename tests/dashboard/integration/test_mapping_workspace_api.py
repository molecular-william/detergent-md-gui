from dashboard.app import default_coordinator as web


def test_mapping_context_lists_valid_molecule_and_scene(isolated_workspace):
    client = web.app.test_client()
    response = client.get('/api/mappings/context?molecule_id=DDM')
    assert response.status_code == 200
    assert response.json['context']['molecule_id'] == 'DDM'
    assert response.json['scene']['svg'].startswith('<svg')
    assert response.json['context']['atoms']


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


def test_suggestion_and_ring_site_endpoints(isolated_workspace):
    client = web.app.test_client()
    context = client.get('/api/mappings/context?molecule_id=DDM').json['context']
    suggestion = client.post('/api/mappings/suggest-bead', json={'molecule_id': 'DDM', 'molecule_snapshot': context['snapshot'], 'atom_ids': [1, 2, 3]} )
    assert suggestion.status_code == 200
    assert suggestion.json['suggestions']
    ring = client.post('/api/mappings/ring-site/preview', json={'molecule_id': 'DDM', 'molecule_snapshot': context['snapshot'], 'mapping': {'beads': [{'name': 'A', 'size': 'S', 'atoms': [1]}, {'name': 'B', 'size': 'S', 'atoms': [2]}, {'name': 'C', 'size': 'S', 'atoms': [3]}]}, 'parents': ['A', 'B', 'C']})
    assert ring.status_code == 200
    assert ring.json['bead']['type'] == 'TC4'
