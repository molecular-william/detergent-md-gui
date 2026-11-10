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


def test_the_preview_returns_a_ready_trehalose_run(dashboard):
    """Trehalose's published atom 8 residue column is the file's anomaly; its parents are residue 2, and the
    reference reader now takes a site's residue from them. The preview is a run, not a blocker."""
    r = dashboard.client.get(PREVIEW, query_string={'molecule_id': 'Trehalose', 'sugar_entry': 'TREH'})

    assert r.status_code == 200
    body = r.json
    assert body['ready'] is True
    assert body['conforms'] is True
    assert body['blockers'] == []
    assert body['sugar_entry'] == 'TREH'


def test_the_preview_returns_a_ready_glucose_run_and_states_the_gal_ambiguity(dashboard):
    """Glucose's layout identifies `GAL` because the aldohexoses share one four-bead pattern; `GLC` and `GAL` are
    that mapping under different published lengths, so the molecule's own entry is a ready run and the preview says
    in its limitations that the identity, not the layout, chose."""
    r = dashboard.client.get(PREVIEW, query_string={'molecule_id': 'Glucose', 'sugar_entry': 'GLC'})

    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.json
    assert body['ready'] is True
    assert body['conforms'] is True
    assert body['blockers'] == []
    assert body['sugar_entry'] == 'GLC'
    assert any('GLC' in line and 'GAL' in line for line in body['limitations']), body['limitations']


def test_the_preview_returns_a_ready_lactose_run(dashboard):
    r = dashboard.client.get(PREVIEW, query_string={'molecule_id': 'Lactose', 'sugar_entry': 'LAC'})

    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.json['ready'] is True
    assert r.json['conforms'] is True
    assert r.json['blockers'] == []


def test_the_preview_refuses_an_unknown_entry(dashboard):
    r = dashboard.client.get(PREVIEW, query_string={'molecule_id': 'Sucrose', 'sugar_entry': 'GAL'})

    assert r.status_code == 400
    assert 'SUCR' in r.get_data(as_text=True)


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
