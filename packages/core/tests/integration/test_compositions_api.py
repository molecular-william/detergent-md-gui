def composition_payload():
    return {'head_fragment_id': 'builtin:martini-sugars-v2:GLC', 'tail_recipe_id': 'linear-c1',
            'carbon_count': 12, 'head_endpoint': {'bead': 'C'}, 'tail_endpoint': {'bead': 'C01'},
            'linkage_profile_id': 'sugar-alkyl-ether-ddm-transfer', 'display_name': 'Glucose C12'}


def test_catalog_exposes_reference_sugars_and_recipes(dashboard):
    response = dashboard.client.get('/api/compositions/catalog')
    assert response.status_code == 200
    assert {'GLC', 'LAC', 'TREH'} <= {item['id'] for item in response.json['sugars']}
    assert {item['id'] for item in response.json['tail_recipes']} == {'linear-c1', 'linear-c1-terminal'}


def test_preview_save_and_duplicate_identity(dashboard):
    client = dashboard.client
    response = client.post('/api/compositions/preview', json=composition_payload())
    assert response.status_code == 200
    saved = client.post('/api/compositions', json=composition_payload())
    assert saved.status_code == 201
    duplicate = client.post('/api/compositions', json=composition_payload())
    assert duplicate.status_code == 409
    rows = client.get('/api/cg-models?view=summary').json['models']
    assert any(row['kind'] == 'composition' and row['id'] == saved.json['id'] for row in rows)


def test_one_post_api_compositions_registration(dashboard):
    """Two handlers answered POST /api/compositions and Werkzeug matched the first.

    The reachable one is `composition_create_api`, which passes the workspace root and maps a
    duplicate name to 409. The loser was unreachable code that differed from it: it called
    compositions.create without a root and reported every ValueError as 400, so the endpoint a
    reader found in the file was not the endpoint a request reached.
    """
    from dashboard.web.routes import catalog

    rules = [rule for rule in dashboard.app.url_map.iter_rules()
             if str(rule) == '/api/compositions' and 'POST' in rule.methods]
    assert len(rules) == 1, [rule.endpoint for rule in rules]
    assert rules[0].endpoint == 'catalog.composition_create_api'
    assert not hasattr(catalog, 'composition_create'), 'the unreachable handler is still defined'
