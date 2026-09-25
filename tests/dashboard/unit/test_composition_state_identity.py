"""A composition's state id must resolve in the bonded-state store.

compositions publishes `state_id: 'composition:<id>'` and catalog republishes it as the id a
consumer can fetch. bonded.states.get rejected that shape outright -- ValueError: Invalid
bonded state ID -- so the id the catalog advertised was not retrievable by anything.
"""
import json

from dashboard.models import catalog, compositions, mappings
from dashboard.models.bonded import states as bonded_states


def composition_record(root):
    """A composition's artifact directory and the record that publishes its state id."""
    (root / 'bonded-state.json').write_text(json.dumps({
        'mapping': {'name': 'candidate', 'beads': []},
        'topology': '[ moleculetype ]\n[ atoms ]\n',
        'status': 'complete', 'origin': 'composition-generated'}))
    return {'id': 'abcdef123456', 'kind': 'composition', 'name': 'Composition one',
            'identity': 'identity-sha256', 'artifact_root': str(root),
            'state_id': 'composition:abcdef123456', 'status': 'candidate-unvalidated'}


def test_composition_state_id_resolves_through_the_bonded_store(tmp_path, monkeypatch):
    record = composition_record(tmp_path)
    monkeypatch.setattr(compositions, 'get', lambda cid: record)
    state = bonded_states.get(record['state_id'])
    assert state['mapping']['identity'] == record['identity']
    assert state['state_id'] == record['state_id']
    assert state['current']['status'] == 'complete'


def test_only_a_well_formed_composition_id_is_answered(tmp_path, monkeypatch):
    """A namespaced id is answered for the id it names, and refused for anything else."""
    record = composition_record(tmp_path)
    monkeypatch.setattr(compositions, 'get', lambda cid: record)
    assert bonded_states.get('composition:abcdef123456')['state_id'] == record['state_id']
    for bad in ('composition:', 'composition:NOTHEX', 'composition:../etc', 'abcdef123456'):
        try:
            bonded_states.get(bad)
        except ValueError:
            continue
        raise AssertionError(f'{bad!r} was answered instead of refused')


def test_catalog_only_publishes_resolvable_state_ids(tmp_path, monkeypatch):
    record = composition_record(tmp_path)
    monkeypatch.setattr(compositions, 'all_compositions', lambda: [record])
    monkeypatch.setattr(mappings, 'list_candidates', lambda summary=True: [])
    monkeypatch.setattr(compositions, 'get', lambda cid: record)
    rows = catalog.list_models()
    assert rows and all(row['state_id'] for row in rows), 'the fixture must publish an id'
    for row in rows:
        assert bonded_states.get(row['state_id']), row
