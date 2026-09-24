from dashboard.app import default_coordinator as web


def composition_payload():
    return {'head_fragment_id': 'builtin:martini-sugars-v2:GLC', 'tail_recipe_id': 'linear-c1',
            'carbon_count': 12, 'head_endpoint': {'bead': 'C'}, 'tail_endpoint': {'bead': 'C01'},
            'linkage_profile_id': 'sugar-alkyl-ether-ddm-transfer', 'display_name': 'Glucose C12'}


def test_catalog_exposes_reference_sugars_and_recipes():
    response = web.app.test_client().get('/api/compositions/catalog')
    assert response.status_code == 200
    assert {'GLC', 'LAC', 'TREH'} <= {item['id'] for item in response.json['sugars']}
    assert {item['id'] for item in response.json['tail_recipes']} == {'linear-c1', 'linear-c1-terminal'}


def test_preview_save_and_duplicate_identity():
    client = web.app.test_client()
    response = client.post('/api/compositions/preview', json=composition_payload())
    assert response.status_code == 200
    saved = client.post('/api/compositions', json=composition_payload())
    assert saved.status_code == 201
    duplicate = client.post('/api/compositions', json=composition_payload())
    assert duplicate.status_code == 409
    rows = client.get('/api/cg-models?view=summary').json['models']
    assert any(row['kind'] == 'composition' and row['id'] == saved.json['id'] for row in rows)
