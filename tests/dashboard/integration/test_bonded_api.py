from copy import deepcopy

from dashboard.app import default_coordinator as web
from dashboard.models import bonded_states, mappings
from tests.dashboard.fixtures import physical_mapping


def test_automatic_bonded_draft_is_nonpersistent_and_snapshot_bound():
    mapping = physical_mapping()
    client = web.app.test_client()

    response = client.post('/api/bonded-states/automatic', json={'mapping': mapping})

    assert response.status_code == 200
    payload = response.json
    assert payload['topology']
    assert payload['interactions']
    assert payload['provenance']['algorithm']['version'] == '1'
    assert bonded_states.all_states() == []

    changed = deepcopy(mapping)
    changed['beads'][0]['atoms'] = []
    assert client.post('/api/bonded-states/automatic', json={'mapping': changed}).status_code == 400


def test_term_state_creation_and_save_as_new_function_edit():
    mapping = physical_mapping()
    first, second = [bead['name'] for bead in mapping['beads'][:2]]
    client = web.app.test_client()
    response = client.post('/api/bonded-states', json={
        'mapping': mapping,
        'name': 'Manual terms',
        'interactions': [{'kind': 'bonds', 'beads': [first, second], 'function': 1,
                          'parameters': ['0.30', '100']}],
    })
    assert response.status_code == 201
    state = response.json
    assert state['current']['status'] == 'complete'
    assert '0.3 100' in state['current']['topology']
    source_bytes = (bonded_states.storage_root() / f"{state['state_id']}.json").read_bytes()

    edited = client.patch(f"/api/bonded-states/{state['state_id']}", json={
        'patch': {'name': 'Edited terms', 'interaction_edits': [
            {'id': 'bonds:1', 'function': 1, 'parameters': ['0.33', '1200']}
        ]},
        'expected_revision': state['revision'],
        'in_place': False,
    })
    assert edited.status_code == 200
    assert edited.json['state_id'] != state['state_id']
    assert '0.33 1200' in edited.json['current']['topology']
    assert (bonded_states.storage_root() / f"{state['state_id']}.json").read_bytes() == source_bytes

    stale = client.patch(f"/api/bonded-states/{state['state_id']}", json={
        'patch': {'interaction_edits': [{'id': 'bonds:1', 'function': 1, 'parameters': ['0.31', '1100']}]},
        'expected_revision': 0,
        'in_place': False,
    })
    assert stale.status_code == 409


def test_plotly_asset_is_local_and_fixed_path():
    response = web.app.test_client().get('/api/assets/plotly.min.js')

    assert response.status_code == 200
    assert response.mimetype == 'application/javascript'
    assert response.data.startswith(b'/*!') or b'Plotly' in response.data[:1000]
