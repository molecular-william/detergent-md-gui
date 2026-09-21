"""Compact views preserve details while avoiding repeated calculations/scans."""
import json
from unittest.mock import patch
from dashboard.app import default_coordinator as web
from dashboard.models import mappings, bonded_states
from dashboard import files
from tests.dashboard.fixtures import physical_mapping


def test_mapping_summary_and_cache_follow_content_changes():
    saved = mappings.save_draft(physical_mapping())
    client = web.app.test_client()
    with patch.object(mappings, 'validate', wraps=mappings.validate) as validate:
        first = client.get('/api/mappings?view=summary').json
        second = client.get('/api/mappings?view=summary').json
        assert first == second
        assert validate.call_count <= 1
    row = first['candidates'][0]
    assert row['file'] == saved['file'] and 'beads' not in row
    assert 'molecule' not in first and 'bead_types' not in first
    path = mappings.storage_root()/saved['file']
    data = json.loads(path.read_text()); data['beads'][0]['atoms'] = []
    path.write_text(json.dumps(data))
    changed = client.get('/api/mappings?view=summary').json['candidates'][0]
    assert changed['sha256'] != row['sha256']
    assert changed['validation'] != row['validation']
    assert 'beads' in client.get('/api/mappings/'+saved['file']).json
    assert 'bead_types' in client.get('/api/mappings/context').json


def test_bonded_summary_omits_topology_and_history():
    state = bonded_states.create(physical_mapping(), 'state', topology='large topology')
    client = web.app.test_client()
    row = client.get('/api/bonded-states?view=summary').json['states'][0]
    assert row['state_id'] == state['state_id']
    assert 'revisions' not in row and 'topology' not in row['current']
    assert client.get('/api/bonded-states/'+state['state_id']).json['current']['topology'] == 'large topology'


def test_bonded_patch_modes_and_stale_revision_conflict():
    mapping = physical_mapping()
    state = bonded_states.create(mapping, 'state', topology='[ moleculetype ]\n[ atoms ]', status='complete')
    client = web.app.test_client()
    copy = client.patch('/api/bonded-states/'+state['state_id'], json={
        'patch': {'name': 'copy'}, 'expected_revision': 1,
    })
    assert copy.status_code == 200
    assert copy.json['state_id'] != state['state_id']
    revised = client.patch('/api/bonded-states/'+state['state_id'], json={
        'patch': {'name': 'revision 2'}, 'expected_revision': 1, 'in_place': True,
    })
    assert revised.status_code == 200
    assert revised.json['state_id'] == state['state_id']
    assert revised.json['revision'] == 2
    stale = client.patch('/api/bonded-states/'+state['state_id'], json={
        'patch': {'name': 'stale'}, 'expected_revision': 1, 'in_place': True,
    })
    assert stale.status_code == 409


def test_compact_runs_preserve_checkpoints_and_full_detail():
    job = {'id': '123456abcdef', 'status': 'completed', 'detergent': 'DDM',
           'mapping_snapshot': {'large': 'x'*10000}}
    web.database().insert(job)
    run = web.run_path(job); run.mkdir(parents=True)
    files.atomic_json(run/'manifest.json', {'stages': [{'name': 'AA reference', 'status': 'completed',
                      'command': ['gmx'], 'outputs_sha256': {'a': 'abc'}, 'ended_at': 'now'}]})
    client = web.app.test_client()
    response = client.get('/api/jobs?page=1&view=summary')
    summary = response.json['jobs'][0]
    assert 'mapping_snapshot' not in summary
    assert summary['stages'][0] == {'name': 'AA reference', 'status': 'completed', 'ended_at': 'now'}
    detail = client.get('/api/jobs/'+job['id']).json
    assert detail['mapping_snapshot'] == job['mapping_snapshot']
    assert detail['stages'][0]['command'] == ['gmx']
    assert client.get('/api/jobs?page=1&view=summary', headers={'If-None-Match': response.headers['ETag']}).status_code == 304


def test_figures_use_index_and_explicit_refresh():
    job = {'id': '123456abcdef', 'status': 'completed'}; web.database().insert(job)
    run = web.run_path(job); run.mkdir(parents=True)
    (run/'figure.svg').write_text('<svg/>'); (run/'data.txt').write_text('data')
    client = web.app.test_client()
    first = client.get('/api/jobs/'+job['id']+'/figures').json
    assert [x['path'] for x in first['artifacts']] == ['figure.svg']
    from dashboard.analysis import observability
    with patch.object(observability, 'artifacts', side_effect=AssertionError('rescanned')):
        assert client.get('/api/jobs/'+job['id']+'/figures').status_code == 200
    (run/'new.png').write_bytes(b'png')
    assert len(client.get('/api/jobs/'+job['id']+'/figures?refresh=1').json['artifacts']) == 2


def test_display_storage_cache_does_not_cache_admission():
    client = web.app.test_client()
    with patch.object(web, 'storage_report', return_value={'run_bytes': 123}) as report:
        assert client.get('/api/storage').json['run_bytes'] == 123
        client.get('/api/storage'); assert report.call_count == 1
        client.get('/api/storage?refresh=1'); assert report.call_count == 2
        web.storage_report(); assert report.call_count == 3
