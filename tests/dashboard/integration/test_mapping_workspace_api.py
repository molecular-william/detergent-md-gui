from dashboard.models import mappings


def test_mapping_context_lists_valid_molecule_and_scene(dashboard):
    client = dashboard.client
    response = client.get('/api/mappings/context?molecule_id=DDM')
    assert response.status_code == 200
    assert response.json['context']['molecule_id'] == 'DDM'
    assert response.json['scene']['svg'].startswith('<svg')
    assert response.json['context']['atoms']


def test_the_overlay_serves_the_molecule_and_the_beads_being_edited(dashboard):
    """The 3D view's payload: a PDB whose serials are mapping atom ids, and a sphere per bead.

    The beads travel with the request because a local draft has beads too, and the assignment being edited is what
    the view must show. The claim worth testing is the one the picture makes: each sphere sits at the mean of the
    atoms its bead names, in angstroms, over the same atoms the PDB writes.
    """
    client = dashboard.client
    context = client.get('/api/mappings/context?molecule_id=DDM').json['context']
    heavy = [atom for atom in context['atoms'] if atom['heavy']]
    serials = {atom['id'] for atom in heavy}
    first, second = heavy[0]['id'], heavy[1]['id']

    response = client.post('/api/mappings/overlay3d', json={
        'molecule_id': 'DDM', 'beads': [{'name': 'B01', 'size': 'S', 'type': 'C1', 'atoms': [first, second]}]})
    assert response.status_code == 200
    pdb, spheres = response.json['pdb'], response.json['spheres']
    assert pdb.count('HETATM') == len(heavy)
    assert pdb.count('CONECT') == sum(1 for bond in context['bonds']
                                      if {bond['a'], bond['b']} <= serials)
    written = [int(row[6:11]) for row in pdb.splitlines() if row.startswith('HETATM')]
    assert first in written and second in written

    assert len(spheres) == 1
    expected = [round(sum(atom['xyz'][axis] for atom in (heavy[0], heavy[1])) / 2 * 10, 4) for axis in range(3)]
    assert spheres[0]['centre'] == expected, spheres[0]
    assert spheres[0]['radius'] >= 2.30, spheres[0]


def test_the_overlay_refuses_a_bead_list_that_is_not_a_list_and_an_unknown_molecule(dashboard):
    """Both refusals follow the workspace's own convention: a bad request is a 400.

    query_context answers an unknown molecule with 400, and the app turns any escaping ValueError into 400 too, so
    matching that is one behaviour instead of two for the same condition. A missing molecule is refused rather than
    defaulted, because the overlay cannot know which structure it was asked to draw.
    """
    client = dashboard.client
    assert client.post('/api/mappings/overlay3d', json={'molecule_id': 'DDM', 'beads': 'nope'}).status_code == 400
    assert client.post('/api/mappings/overlay3d', json={'molecule_id': 'nowhere'}).status_code == 400
    assert client.post('/api/mappings/overlay3d', json={'beads': []}).status_code == 400


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


def test_an_in_place_save_overwrites_its_candidate(dashboard):
    """In-place keeps the file; a save as new always mints another one.

    The two differ in a way a user notices: an in-place edit changes the mapping the fitted states were
    measured against, so the UI warns before offering it.
    """
    client = dashboard.client
    from dashboard.models import mappings
    candidate = mappings.automatic_candidate(mappings.molecule(), 'DDM')
    candidate['name'] = 'In-place'
    first = client.post('/api/mappings/drafts', json=candidate).json

    updated = client.post('/api/mappings/drafts', json={**candidate, 'name': 'In-place renamed',
                                                         'file': first['file'], 'in_place': True})

    assert updated.status_code == 201
    assert updated.json['file'] == first['file'], 'the same file, not a new one'
    listed = client.get('/api/mappings?view=summary').json['candidates']
    assert [c['file'] for c in listed] == [first['file']], 'no second candidate appeared'

    refused = client.post('/api/mappings/drafts', json={
        'name': 'Nowhere', 'beads': [{'name': 'B01'}], 'in_place': True})
    assert refused.status_code == 400, refused.json
    assert len(client.get('/api/mappings?view=summary').json['candidates']) == 1


def test_dashboard_no_longer_carries_the_validation_controls(dashboard):
    """The carbohydrate validation section was removed from CG Bead Assignment.

    The analysis itself is unchanged -- the endpoints and the worker tests above still exercise it --
    so this pins the UI removal rather than the feature: no control, and no placeholder left behind.
    """
    html = dashboard.client.get('/').get_data(as_text=True)
    for removed in ('validation-representation', 'validation-tier', 'validation-target',
                    'validation-source-run', 'launch-carbohydrate-validation',
                    'carbohydrate-validation-reports'):
        assert f'id="{removed}"' not in html, removed
    assert 'Carbohydrate validation' not in html

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
    # A well-formed snapshot carrying the wrong hash: the refusal has to be about staleness,
    # not about a payload the endpoint could reject as malformed.
    stale = {**context['snapshot'], 'snapshot_sha256': 'stale'}
    response = client.post('/api/mappings/automatic/preview', json={'molecule_id': 'DDM', 'molecule_snapshot': stale})
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
