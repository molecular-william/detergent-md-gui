"""The sugar run's HTTP surface: the defaults it fills and the queue it posts to.

The queue test stubs `create_job` and asserts what the route asked for; what the coordinator does with the record is
the adapter's own suite. No test starts a simulation.
"""
from unittest.mock import patch


def test_the_defaults_are_the_reference_kind_s_own_preset(dashboard):
    r = dashboard.client.get('/api/defaults', query_string={
        'run_type': 'cg', 'parameterization_kind': 'reference'})

    assert r.status_code == 200, r.get_data(as_text=True)
    values = r.json['values']
    assert values['cg_equil_ps'] == 5000.0
    assert values['cg_production_ps'] == 10000.0
    assert values['sugar_entry'] == 'SUCR'
    assert 'aa_nvt_ps' not in values
    assert 'pressure_bar' not in values


def test_the_readiness_route_asks_the_reference_kind(dashboard):
    r = dashboard.client.get('/api/readiness', query_string={
        'run_type': 'cg', 'parameterization_kind': 'reference',
        'molecule_id': 'Sucrose', 'sugar_entry': 'SUCR'})

    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.json['ready'] is True
    assert r.json['molecule']['id'] == 'Sucrose'


def test_the_queue_route_keeps_only_the_sugar_vocabulary(dashboard):
    calls = []

    def fake_create_job(molecule, method, label, **kwargs):
        calls.append({'molecule': molecule, 'method': method, 'label': label, **kwargs})
        return {'id': 'stub00000001', 'label': label, 'run_type': 'cg'}

    with patch.object(dashboard.coordinator, 'create_job', side_effect=fake_create_job):
        r = dashboard.client.post('/', json={
            'run_type': 'cg', 'molecule_id': 'Sucrose',
            'parameterization': {'kind': 'reference', 'sugar_entry': 'SUCR'},
            'cg_production_ps': 10000, 'cg_equil_ps': 5000, 'temperature_k': 310})
    assert r.status_code == 201, r.get_data(as_text=True)
    assert len(calls) == 1
    call = calls[0]
    assert call['run_type'] == 'cg'
    assert call['molecule'] == 'Sucrose'
    assert call['parameterization'] == {'kind': 'reference', 'sugar_entry': 'SUCR'}
    assert call['settings']['cg_production_ps'] == 10000
    assert 'sugar_entry' not in call['settings'], 'the entry rides in the parameterization'
    assert 'method' not in call['settings']
    assert call['method'] is None
