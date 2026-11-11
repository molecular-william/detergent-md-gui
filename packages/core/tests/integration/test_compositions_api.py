import json

from dashboard import files


def composition_payload(**overrides):
    payload = {'head_fragment_id': 'builtin:martini-sugars-v2:GLC', 'tail_recipe_id': 'linear-c1',
               'carbon_count': 12, 'head_endpoint': {'bead': 'C'}, 'tail_endpoint': {'bead': 'C01'},
               'linkage_profile_id': 'sugar-alkyl-ether-ddm-transfer', 'display_name': 'Glucose C12'}
    payload.update(overrides)
    return payload


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


def test_a_saved_composition_is_a_named_model_linked_to_its_head(dashboard):
    """The record carries its own molecule id, the saved name and the AA molecule its head came from."""
    response = dashboard.client.post('/api/compositions', json=composition_payload(
        molecule_name='GLC-C12', head_molecule_id='Trehalose'))
    assert response.status_code == 201, response.data
    record = response.json
    assert record['molecule_id'] == record['id']
    assert record['molecule_name'] == 'GLC-C12' and record['name'] == 'GLC-C12'
    assert record['head_molecule_id'] == 'Trehalose'
    assert record['status'] == 'candidate-unvalidated' and record['scientifically_validated'] is False

    row = next(item for item in dashboard.client.get('/api/cg-models').json['models']
               if item['kind'] == 'composition' and item['id'] == record['id'])
    assert row['molecule_id'] == record['id'] and row['molecule_name'] == 'GLC-C12'
    assert row['head_molecule_id'] == 'Trehalose' and row['status'] == 'candidate-unvalidated'
    # The parameterization is derived, never fitted, and says so.
    parameterization = row['parameterization']
    assert parameterization['kind'] == 'composition' and parameterization['revision'] == 0
    assert parameterization['engine'] == 'composition-derivation'
    assert parameterization['source'] == 'recipe+reference'
    assert parameterization['head_molecule_id'] == 'Trehalose'
    assert parameterization['topology']['beads'] > 0 and parameterization['topology']['terms']['bonds'] > 0
    assert len(parameterization['topology']['sha256']) == 64


def test_the_detail_route_exposes_the_derived_parameterization(dashboard):
    saved = dashboard.client.post('/api/compositions', json=composition_payload(molecule_name='GLC-C12'))
    detail = dashboard.client.get(f"/api/cg-models/composition/{saved.json['id']}")
    assert detail.status_code == 200, detail.data
    body = detail.json
    assert body['composition_id'] == saved.json['id'] and body['molecule_id'] == saved.json['id']
    assert body['molecule_name'] == 'GLC-C12' and body['head_molecule_id'] is None
    assert body['status'] == 'candidate-unvalidated'
    assert body['parameterization']['source'] == 'recipe-only'
    assert body['parameterization']['coordinates']['path'].endswith('composition.gro')
    # The counts come from the composition's own topology, so a reader need not parse it.
    itp_text = (dashboard.paths.workspace / 'compositions' / saved.json['id'] / 'composition.itp').read_text()
    atoms = [line for line in itp_text.split('[ atoms ]', 1)[1].split('[', 1)[0].splitlines()
             if line.strip() and not line.strip().startswith(';')]
    assert body['parameterization']['topology']['beads'] == len(atoms)


def test_the_new_fields_are_validated(dashboard):
    client = dashboard.client
    missing = client.post('/api/compositions', json=composition_payload(head_molecule_id='NoSuchMolecule'))
    assert missing.status_code == 400 and 'catalogue' in missing.get_data(as_text=True)

    traversal = client.post('/api/compositions', json=composition_payload(head_molecule_id='../DDM'))
    assert traversal.status_code == 400

    too_long = client.post('/api/compositions', json=composition_payload(molecule_name='x' * 161))
    assert too_long.status_code == 400 and 'molecule_name' in too_long.get_data(as_text=True)

    # An absent name keeps the composition's existing name rather than failing or saving an empty one.
    unnamed = client.post('/api/compositions', json=composition_payload(molecule_name='   '))
    assert unnamed.status_code == 201 and unnamed.json['molecule_name'] == 'Glucose C12'


def test_the_identity_still_excludes_the_display_text(dashboard):
    """Saving the same fragments under a different name is the same composition: the duplicate rule is unchanged."""
    client = dashboard.client
    assert client.post('/api/compositions', json=composition_payload()).status_code == 201
    duplicate = client.post('/api/compositions', json=composition_payload(molecule_name='another name'))
    assert duplicate.status_code == 409 and 'already exists' in duplicate.get_data(as_text=True)


def test_an_old_record_without_the_new_fields_stays_readable(dashboard):
    """Records saved before the fields existed are read with defaults, not refused."""
    root = dashboard.paths.workspace / 'compositions' / '0123456789abcdef'
    root.mkdir(parents=True)
    for name in ('composition.gro', 'composition.itp', 'mapping.json', 'bonded-state.json'):
        (root / name).write_text('placeholder')
    record = {'id': '0123456789abcdef', 'kind': 'composition', 'name': 'old model',
              'created_at': files.now_iso(), 'identity': 'identity', 'snapshot_hash': 'snapshot',
              'status': 'candidate-unvalidated', 'scientifically_validated': False,
              'artifact_root': str(root), 'snapshot': {'mapping': {'residue_name': 'GLC'}}}
    (dashboard.paths.workspace / 'compositions' / '0123456789abcdef.json').write_text(json.dumps(record))

    detail = dashboard.client.get('/api/cg-models/composition/0123456789abcdef')
    assert detail.status_code == 200, detail.data
    assert detail.json['molecule_id'] == '0123456789abcdef'
    assert detail.json['molecule_name'] == 'old model'
    assert detail.json['head_molecule_id'] is None
    assert detail.json['parameterization']['source'] == 'recipe-only'
    row = next(item for item in dashboard.client.get('/api/cg-models').json['models']
               if item['kind'] == 'composition' and item['id'] == '0123456789abcdef')
    assert row['molecule_name'] == 'old model'


def test_one_post_api_compositions_registration(dashboard):
    """Two handlers answered POST /api/compositions and Werkzeug matched the first.

    The reachable one is `composition_create_api`, which passes the workspace root and maps a
    duplicate name to 409. The loser was unreachable code that differed from it: it called
    compositions.create without a root and reported every ValueError as 400, so the endpoint a
    reader found in the file was the endpoint a request reached.
    """
    from dashboard.web.routes import catalog

    rules = [rule for rule in dashboard.app.url_map.iter_rules()
             if str(rule) == '/api/compositions' and 'POST' in rule.methods]
    assert len(rules) == 1, [rule.endpoint for rule in rules]
    assert rules[0].endpoint == 'catalog.composition_create_api'
    assert not hasattr(catalog, 'composition_create'), 'the unreachable handler is still defined'


def test_readiness_answers_a_composition_through_its_own_model(dashboard):
    """The route used to send every `molecule_id` to the atomistic catalogue.

    A composition's molecule is the saved CG model, so the readiness question must reach the composition adapter --
    which reads its artifacts and the binding -- rather than being refused as a folder that is not there.
    """
    saved = dashboard.client.post('/api/compositions', json=composition_payload(molecule_name='GLC-C12'))
    query = {'run_type': 'cg', 'molecule_id': saved.json['id'],
             'parameterization': json.dumps({'kind': 'composition', 'composition_id': saved.json['id']})}
    answer = dashboard.client.get('/api/readiness', query_string=query)
    assert answer.status_code == 200, answer.data
    labels = {check['label'] for check in answer.json['checks']}
    assert 'composition.gro' in labels and 'Molecule' not in labels
    assert not any('catalogue' in blocker for blocker in answer.json['blockers']), answer.json['blockers']

    wrong = dashboard.client.get('/api/readiness', query_string={
        **query, 'molecule_id': 'DDM'})
    assert wrong.status_code == 200
    assert wrong.json['ready'] is False
    assert any(f'belongs to {saved.json["id"]}' in blocker for blocker in wrong.json['blockers'])


#: One flexible bond edit: the linkage keeps its length and gets a softer force.
OVERRIDE = [{'section': 'bonds', 'beads': ['C', 'C01'], 'function': 1, 'parameters': [0.47, 3000]}]


def test_a_saved_edit_is_a_revision_the_catalogue_and_a_run_read(dashboard):
    """The composition's current parameterization is what the rows, the detail and the run all name."""
    client = dashboard.client
    saved = client.post('/api/compositions', json=composition_payload(molecule_name='GLC-C12'))
    composition_id = saved.json['id']

    view = client.get(f'/api/compositions/{composition_id}/parameterizations')
    assert view.status_code == 200, view.data
    assert view.json['current'] == 0 and view.json['edited'] is False
    assert view.json['ranges']['bonds']['1'][1]['label'] == 'force (kJ mol^-1 nm^-2)'

    edit = client.post(f'/api/compositions/{composition_id}/parameterizations',
                       json={'expected_revision': 0, 'overrides': OVERRIDE})
    assert edit.status_code == 201, edit.data
    assert edit.json['revision'] == 1 and edit.json['base'] == 'derived-revision-0'
    assert len(edit.json['topology_sha256']) == 64

    stale = client.post(f'/api/compositions/{composition_id}/parameterizations',
                        json={'expected_revision': 0, 'overrides': OVERRIDE})
    assert stale.status_code == 409 and 'changed' in stale.get_data(as_text=True)
    refused = client.post(f'/api/compositions/{composition_id}/parameterizations',
                          json={'expected_revision': 1, 'overrides': [
                              {'section': 'bonds', 'beads': ['A', 'VS'], 'function': 1,
                               'parameters': [0.47, 3000]}]})
    assert refused.status_code == 400, refused.data

    row = next(item for item in client.get('/api/cg-models').json['models']
               if item['kind'] == 'composition' and item['id'] == composition_id)
    assert row['parameterization']['revision'] == 1 and row['parameterization']['base'] == 'edited'
    detail = client.get(f'/api/cg-models/composition/{composition_id}').json
    assert detail['parameterization']['revision'] == 1
    view = client.get(f'/api/compositions/{composition_id}/parameterizations').json
    assert view['current'] == 1 and view['edited'] is True
    assert [term['source'] for term in view['terms'] if term['source'] == 'manual']


def test_readiness_refuses_a_composition_revision_the_record_does_not_hold(dashboard):
    saved = dashboard.client.post('/api/compositions', json=composition_payload(molecule_name='GLC-C12'))
    composition_id = saved.json['id']
    query = {'run_type': 'cg', 'molecule_id': composition_id, 'detergent': composition_id,
             'parameterization': json.dumps({'kind': 'composition', 'composition_id': composition_id,
                                             'composition_revision': 9})}
    answer = dashboard.client.get('/api/readiness', query_string=query)
    assert answer.status_code == 200, answer.data
    assert answer.json['ready'] is False
    assert 'Unknown composition parameterization revision' in answer.json['blockers'][0]
