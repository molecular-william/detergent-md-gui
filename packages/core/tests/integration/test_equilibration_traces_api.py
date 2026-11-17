"""The equilibration-traces route: unknown run, not published yet, and the published record.

The producer is pinned by `unit/test_equilibration_traces.py`; this file pins the seam the Diagnostics panel reads,
including the answer a still-running run gets instead of a request the queue route would refuse.
"""
import json

JID = '123456abcdef'


def seed(dashboard, status='completed'):
    coordinator = dashboard.coordinator
    job = {'id': JID, 'label': 'Traces', 'detergent': 'DDM', 'method': 'pdc', 'profile': 'default',
           'status': status, 'stage': 'complete', 'run_type': 'pdc', 'created': coordinator.now(),
           'analyses': [], 'settings': {}}
    coordinator.database().replace([job])
    run = coordinator.RUNS / JID
    run.mkdir(parents=True, exist_ok=True)
    (run / 'manifest.json').write_text(json.dumps({'run_type': 'pdc', 'status': status, 'stages': [],
                                                   'settings': {}}))
    return coordinator, run


RECORD = {
    'legs': {'nvt': {'x': [0.0, 1000.0], 'x_unit': 'time_ps', 'duration_ps': 1000.0,
                      'source': '04_nvt/run.edr',
                      'terms': {'Temperature': {'values': [300.0, 301.0], 'mean': 300.5}}}},
    'terms': ['Potential', 'Temperature', 'Pressure'],
    'targets': {'Temperature': 300.0},
    'gmx_version': 'GROMACS version: 2026.3',
}


def publish(run, record=RECORD, name='0001-20260101'):
    """One attempt's result record and published file, the way the worker leaves them."""
    attempt = run / 'analyses' / 'equilibration-traces' / name
    output = attempt / 'output' / 'key'
    output.mkdir(parents=True, exist_ok=True)
    (attempt / 'result.json').write_text(json.dumps({'output_directory': 'output/key'}))
    (output / 'equilibration-traces.json').write_text(json.dumps(record))


def test_an_unknown_run_is_a_404(dashboard):
    assert dashboard.client.get('/api/jobs/not-a-run/equilibration-traces').status_code == 404


def test_before_an_attempt_the_route_says_whether_the_run_stopped(dashboard):
    _, run = seed(dashboard)

    answer = dashboard.client.get(f'/api/jobs/{JID}/equilibration-traces').get_json()
    assert answer == {'published': False, 'run_stopped': True}, 'a completed run can be analysed'

    seed(dashboard, status='running')
    answer = dashboard.client.get(f'/api/jobs/{JID}/equilibration-traces').get_json()
    assert answer == {'published': False, 'run_stopped': False}, 'a running run is readable, not analysed'
    assert not (run / 'analyses').exists(), 'no attempt was published for a running run'


def test_the_published_record_answers(dashboard):
    _, run = seed(dashboard)
    publish(run)

    response = dashboard.client.get(f'/api/jobs/{JID}/equilibration-traces')

    assert response.status_code == 200
    body = response.get_json()
    assert body['published'] is True
    assert body['legs'] == RECORD['legs']
    assert body['terms'] == RECORD['terms']
    assert body['targets'] == {'Temperature': 300.0}
    assert body['gmx_version'] == 'GROMACS version: 2026.3'


def test_the_newest_attempt_that_still_stands_is_the_answer(dashboard):
    _, run = seed(dashboard)
    publish(run)
    newer = {'legs': {'npt': {'x': [0.0], 'x_unit': 'time_ps', 'duration_ps': 0.0,
                               'source': '05_npt/run.edr',
                               'terms': {'Pressure': {'values': [1.0], 'mean': 1.0}}}}}
    publish(run, record=newer, name='0002-20260102')

    body = dashboard.client.get(f'/api/jobs/{JID}/equilibration-traces').get_json()

    assert body['published'] is True
    assert set(body['legs']) == {'npt'}, 'the newest attempt answered, not the previous one'
