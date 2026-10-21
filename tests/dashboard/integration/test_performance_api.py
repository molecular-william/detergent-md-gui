"""Compact views preserve details while avoiding repeated calculations/scans."""
import json
from unittest.mock import patch

from dashboard import files
from dashboard.models import mappings
from tests.dashboard.support import physical_mapping


def test_mapping_summary_and_cache_follow_content_changes(dashboard):
    saved = mappings.save_draft(physical_mapping())
    client = dashboard.client
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


def test_compact_runs_preserve_checkpoints_and_full_detail(dashboard):
    job = {'id': '123456abcdef', 'status': 'completed', 'detergent': 'DDM',
           'mapping_snapshot': {'large': 'x'*10000}}
    dashboard.coordinator.database().insert(job)
    run = dashboard.coordinator.run_path(job); run.mkdir(parents=True)
    files.atomic_json(run/'manifest.json', {'stages': [{'name': 'AA reference', 'status': 'completed',
                      'command': ['gmx'], 'outputs_sha256': {'a': 'abc'}, 'ended_at': 'now'}]})
    client = dashboard.client
    response = client.get('/api/jobs?page=1&view=summary')
    summary = response.json['jobs'][0]
    assert 'mapping_snapshot' not in summary
    assert summary['stages'][0] == {'name': 'AA reference', 'status': 'completed', 'ended_at': 'now'}
    detail = client.get('/api/jobs/'+job['id']).json
    assert detail['mapping_snapshot'] == job['mapping_snapshot']
    assert detail['stages'][0]['command'] == ['gmx']
    assert client.get('/api/jobs?page=1&view=summary', headers={'If-None-Match': response.headers['ETag']}).status_code == 304


def test_figures_use_index_and_explicit_refresh(dashboard):
    job = {'id': '123456abcdef', 'status': 'completed'}; dashboard.coordinator.database().insert(job)
    run = dashboard.coordinator.run_path(job); run.mkdir(parents=True)
    (run/'figure.svg').write_text('<svg/>'); (run/'data.txt').write_text('data')
    client = dashboard.client
    first = client.get('/api/jobs/'+job['id']+'/figures').json
    assert [x['path'] for x in first['artifacts']] == ['figure.svg']
    from dashboard.analysis.runs import observability
    with patch.object(observability, 'artifacts', side_effect=AssertionError('rescanned')):
        assert client.get('/api/jobs/'+job['id']+'/figures').status_code == 200
    (run/'new.png').write_bytes(b'png')
    assert len(client.get('/api/jobs/'+job['id']+'/figures?refresh=1').json['artifacts']) == 2


def test_the_figure_list_holds_one_set_per_analysis_not_one_per_attempt(dashboard):
    """A run's figures are the newest set of each analysis, with the superseded ones counted rather than listed.

    Measured on this workspace's own sucrose CG run before the rule: 38 images, 33 of them the same three snapshot
    SVGs from eleven attempts of one analysis, so the file a reader wanted was buried among its own earlier selves.
    """
    job = {'id': '654321fedcba', 'status': 'completed'}
    dashboard.coordinator.database().insert(job)
    run = dashboard.coordinator.run_path(job)
    import os
    for signature, epoch in (('aaaa', 1_700_000_000), ('bbbb', 1_700_100_000)):
        directory = run / f'analyses/snapshots/{signature}/1111/output/2222/snapshots'
        directory.mkdir(parents=True, exist_ok=True)
        for name in ('CG-first.svg', 'CG-middle.svg'):
            (directory / name).write_text('<svg/>')
            # The stamps are the whole test: both sets are written in the same instant, and without distinct times
            # the rule has nothing to choose on -- which is how this test first passed for the wrong set.
            os.utime(directory / name, (epoch, epoch))
    assessment = run / 'stages/5_assessment'
    assessment.mkdir(parents=True, exist_ok=True)
    (assessment / 'score_matrix_LIG1.png').write_bytes(b'png')

    answer = dashboard.client.get(f'/api/jobs/{job["id"]}/figures?refresh=1').json

    paths = [entry['path'] for entry in answer['artifacts']]
    assert paths == ['analyses/snapshots/bbbb/1111/output/2222/snapshots/CG-first.svg',
                     'analyses/snapshots/bbbb/1111/output/2222/snapshots/CG-middle.svg',
                     'stages/5_assessment/score_matrix_LIG1.png'], paths
    assert answer['superseded'] == 1, 'the superseded set is counted, not silently dropped'


def test_display_storage_cache_does_not_cache_admission(dashboard):
    client = dashboard.client
    with patch.object(dashboard.coordinator, 'storage_report', return_value={'run_bytes': 123}) as report:
        assert client.get('/api/storage').json['run_bytes'] == 123
        client.get('/api/storage'); assert report.call_count == 1
        client.get('/api/storage?refresh=1'); assert report.call_count == 2
        dashboard.coordinator.storage_report(); assert report.call_count == 3
