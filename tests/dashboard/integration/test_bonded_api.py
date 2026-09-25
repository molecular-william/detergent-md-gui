from copy import deepcopy

from dashboard.models.bonded import states as bonded_states
from tests.dashboard.support import physical_mapping


def test_automatic_bonded_draft_is_nonpersistent_and_snapshot_bound(dashboard):
    mapping = physical_mapping()
    client = dashboard.client

    response = client.post('/api/bonded-states/automatic', json={'mapping': mapping})

    assert response.status_code == 200
    payload = response.json
    assert payload['topology']
    assert payload['interactions']
    assert payload['provenance']['algorithm']['version'] == '2'
    assert bonded_states.all_states() == []

    changed = deepcopy(mapping)
    changed['beads'][0]['atoms'] = []
    assert client.post('/api/bonded-states/automatic', json={'mapping': changed}).status_code == 400


def test_term_state_creation_and_save_as_new_function_edit(dashboard):
    mapping = physical_mapping()
    first, second = [bead['name'] for bead in mapping['beads'][:2]]
    client = dashboard.client
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


def test_plotly_asset_is_local_and_fixed_path(dashboard):
    response = dashboard.client.get('/api/assets/plotly.min.js')

    assert response.status_code == 200
    assert response.mimetype == 'application/javascript'
    assert response.data.startswith(b'/*!') or b'Plotly' in response.data[:1000]


def test_a_bonded_state_from_another_mapping_is_refused(dashboard):
    """Reusing a fitted state with the wrong mapping would assemble another molecule's topology.

    The refusal is RunConflict, which the error table answers as 409. It is the check that keeps a
    fitted state attached to the mapping it was fitted for.

    The second mapping differs in *chemistry* (a renamed bead, which changes the bead names written
    into the ITP) rather than only in the candidate's name, so this stays a refusal whichever
    identity the compatibility check uses -- see the name-in-hash open item in DDM_CALIBRATION.
    """
    client = dashboard.client
    mapping = physical_mapping()
    saved = client.post('/api/mappings/drafts', json=mapping).json
    other = deepcopy(mapping)
    other['beads'][0]['name'] = 'ZZZ'
    other_saved = client.post('/api/mappings/drafts', json=other).json
    assert other_saved['file'] != saved['file'], 'the two saved candidates must be distinct'

    first, second = [bead['name'] for bead in mapping['beads'][:2]]
    state = client.post('/api/bonded-states', json={
        'mapping': mapping,
        'name': 'Fitted for the first mapping',
        'interactions': [{'kind': 'bonds', 'beads': [first, second], 'function': 1,
                          'parameters': ['0.30', '100']}],
    }).json
    assert state['current']['status'] == 'complete'

    refused = client.post('/', json={
        'method': 'fast_forward', 'molecule_id': 'DDM', 'mapping_candidate': other_saved['file'],
        'bonded_state_id': state['state_id'], 'bonded_intent': 'reuse_state',
    })

    assert refused.status_code == 409, refused.json
    assert 'does not belong to the selected mapping' in refused.json['error']
