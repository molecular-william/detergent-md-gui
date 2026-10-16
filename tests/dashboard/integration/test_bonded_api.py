from copy import deepcopy

import pytest

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


def test_the_selector_lists_a_renamed_candidates_states(dashboard):
    """The browser sends both hashes; the chemistry one is what survives a rename.

    This is the user-visible half of the identity fix: the server already judged compatibility by
    chemistry, but the state list filtered on the candidate hash alone, so renaming a saved candidate
    hid the states fitted for it.
    """
    from dashboard.models import mappings
    client = dashboard.client
    mapping = physical_mapping()
    state = client.post('/api/bonded-states', json={
        'mapping': mapping, 'name': 'Fitted', 'interactions': [
            {'kind': 'bonds', 'beads': [bead['name'] for bead in mapping['beads'][:2]],
             'function': 1, 'parameters': ['0.30', '100']}],
    }).json
    content = mappings.content_identity(mapping)

    listed = client.get('/api/bonded-states', query_string={'view': 'summary', 'content_hash': content})

    assert [s['state_id'] for s in listed.json['states']] == [state['state_id']]
    other = client.get('/api/bonded-states', query_string={'view': 'summary', 'content_hash': '0' * 64})
    assert other.json['states'] == [], 'a different chemistry lists nothing'


def test_plotly_asset_is_local_and_fixed_path(dashboard):
    response = dashboard.client.get('/api/assets/plotly.min.js')

    assert response.status_code == 200
    assert response.mimetype == 'application/javascript'
    assert response.data.startswith(b'/*!') or b'Plotly' in response.data[:1000]


def test_a_run_can_no_longer_be_handed_a_bonded_state(dashboard, monkeypatch):
    """D1: fitting is the run type's own, so a run record carries no state and no workflow.

    This replaces the admission that refused a state fitted for another mapping -- 409, "does not belong to the
    selected mapping". The two controls are gone from the run contract, so a payload that still names them is not
    read (the door below no longer takes the arguments at all) and the record it produces names neither. The
    compatibility checks themselves stay where they are tested: `models/bonded` still compares a state with the
    mapping it was fitted for, for the workspace that fits and compares states.
    """
    from dashboard.execution.adapters import aa, cg
    from dashboard.execution.coordination import coordinator as backend

    monkeypatch.setattr(backend.threading.Thread, 'start', lambda self: None)
    monkeypatch.setattr(cg, 'readiness', lambda *args, **kwargs: {'ready': True})
    monkeypatch.setattr(aa, 'readiness', lambda *args, **kwargs: {'ready': True, 'checks': [], 'blockers': []})

    with dashboard.app.test_request_context():
        job = dashboard.coordinator.create_job(
            'DDM', 'fast_forward', profile='draft-smoke', run_type='aa_cg', molecule_id='DDM',
            mapping_snapshot=physical_mapping())

    for retired in ('bonded_state_id', 'bonded_state_snapshot', 'bonded_state_revision', 'bonded_intent'):
        assert retired not in job, f'{retired} is a per-run bonded choice; the run type fits its own (D1)'
    with pytest.raises(TypeError, match='bonded_state_id'):
        dashboard.coordinator.create_job('DDM', 'fast_forward', run_type='aa_cg', molecule_id='DDM',
                                         bonded_state_id='x')
