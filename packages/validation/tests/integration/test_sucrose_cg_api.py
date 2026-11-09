"""The sugar run's HTTP surface: the preview the form reads, the defaults it fills, and the queue it posts to.

The queue test stubs `create_job` and asserts what the route asked for; what the coordinator does with the record is
the adapter's own suite. No test starts a simulation.
"""
from unittest.mock import patch

PREVIEW = '/api/sugar-cg/preview'


def test_the_preview_returns_the_published_signature_and_the_candidate(dashboard):
    r = dashboard.client.get(PREVIEW, query_string={'molecule_id': 'Sucrose', 'sugar_entry': 'SUCR'})

    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.json
    assert body['ready'] is True
    assert body['conforms'] is True
    assert body['topology_source'] == 'published-reference'
    assert body['reference']['sha256'] == '4d29956a77d936cfdad10e8bbdf201cebdaa24a2f5f50688988a1c7bb9ebfc50'
    assert [bead['name'] for bead in body['beads']] == [f'B{index:02d}' for index in range(1, 9)]
    assert body['signature']['residues']['1'][0]['type'] == 'SP1r'


def test_the_preview_returns_the_trehalose_blocker_instead_of_a_run(dashboard):
    r = dashboard.client.get(PREVIEW, query_string={'molecule_id': 'Trehalose', 'sugar_entry': 'TREH'})

    assert r.status_code == 200
    body = r.json
    assert body['ready'] is False
    assert body['conforms'] is False
    assert any('do not match the reference' in blocker for blocker in body['blockers'])


def test_the_preview_refuses_an_unknown_entry(dashboard):
    r = dashboard.client.get(PREVIEW, query_string={'molecule_id': 'Sucrose', 'sugar_entry': 'LAC'})

    assert r.status_code == 400
    assert 'SUCR' in r.get_data(as_text=True)


def test_the_defaults_are_the_sugar_run_s_own_preset(dashboard):
    r = dashboard.client.get('/api/defaults', query_string={'run_type': 'sugar_cg'})

    assert r.status_code == 200, r.get_data(as_text=True)
    values = r.json['values']
    assert values['cg_equil_ps'] == 5000.0
    assert values['cg_production_ps'] == 10000.0
    assert values['sugar_entry'] == 'SUCR'
    assert 'aa_nvt_ps' not in values
    assert 'pressure_bar' not in values


def test_the_readiness_route_asks_the_sugar_run_type(dashboard):
    r = dashboard.client.get('/api/readiness', query_string={
        'run_type': 'sugar_cg', 'molecule_id': 'Sucrose', 'sugar_entry': 'SUCR'})

    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.json['ready'] is True
    assert r.json['molecule']['id'] == 'Sucrose'


def test_the_queue_route_keeps_only_the_sugar_vocabulary(dashboard):
    calls = []

    def fake_create_job(molecule, method, label, **kwargs):
        calls.append({'molecule': molecule, 'method': method, 'label': label, **kwargs})
        return {'id': 'stub00000001', 'label': label, 'run_type': 'sugar_cg'}

    with patch.object(dashboard.coordinator, 'create_job', side_effect=fake_create_job):
        r = dashboard.client.post('/', json={
            'run_type': 'sugar_cg', 'molecule_id': 'Sucrose', 'sugar_entry': 'SUCR',
            'cg_production_ps': 10000, 'cg_equil_ps': 5000, 'temperature_k': 310})
    assert r.status_code == 201, r.get_data(as_text=True)
    assert len(calls) == 1
    call = calls[0]
    assert call['run_type'] == 'sugar_cg'
    assert call['molecule'] == 'Sucrose'
    assert call['settings']['sugar_entry'] == 'SUCR'
    assert call['settings']['cg_production_ps'] == 10000
    assert 'method' not in call['settings']
    assert call['method'] is None
