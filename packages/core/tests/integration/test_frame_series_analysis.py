"""Queueing a frame series through the real route: the payload, the signature, the identity, and the refusals.

The producer never runs here: a no-op worker stands in for the subprocess, which is what keeps this fast, and what the
producer does with its frames is pinned in the unit test. What this file pins is the seam the panel uses -- the queue
route's own validation, the payload the attempt records, the signature that makes identical arguments free and changed
arguments or changed trajectory bytes a new attempt, and the identity `/trajectory` now carries so a series can say
which bytes it sampled.
"""
import json

from dashboard.analysis.runs import segments

JID = '123456abcdef'
TRAJECTORY = 'stages/3_nvt/system.xtc'
STRUCTURE = 'stages/3_nvt/system.gro'
PAYLOAD = {'trajectory': TRAJECTORY, 'structure': STRUCTURE, 'stride': 2}


def write(root, relative, text='', size=0):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text else 'x' * size)
    return path


def gro(count):
    """A readable `.gro` whose second line states the atom count the segment reports."""
    row = f'{1:5d}{"DDM":<5s}{"B01":>5s}{1:5d}{0.1:8.3f}{0.2:8.3f}{0.3:8.3f}'
    return 'coarse-grained system\n' + f'{count:5d}\n' + (row + '\n') * count + '   8.00000   8.00000   8.00000\n'


def seed(dashboard):
    """A finished protein-detergent run whose NVT leg offers the pair a frame series is asked for."""
    coordinator = dashboard.coordinator
    job = {'id': JID, 'label': 'Frame series', 'detergent': 'DDM', 'method': 'pdc', 'profile': 'default',
           'status': 'completed', 'stage': 'complete', 'run_type': 'pdc', 'created': coordinator.now(),
           'analyses': []}
    coordinator.database().replace([job])
    run = coordinator.RUNS / JID
    write(run, TRAJECTORY, size=200)
    write(run, STRUCTURE, gro(40))
    write(run, 'stages/1_system/system.gro', gro(40))
    write(run, 'manifest.json', json.dumps({'run_type': 'pdc', 'status': 'completed', 'stages': []}))
    return coordinator, run


def tasks(coordinator):
    return coordinator.lookup(JID).get('analyses', [])


def settle(coordinator):
    """Finish every open attempt and let go of its worker, the way `finish` does after a real subprocess."""
    while True:
        open_tasks = [task for task in tasks(coordinator) if task['status'] in ('queued', 'running')]
        if not open_tasks:
            return
        for task in open_tasks:
            coordinator.analysis_coordinator.update(JID, task['id'], status='completed')
            with coordinator.JOBS_LOCK:
                coordinator.ANALYSIS_WORKERS.pop((JID, task['id']), None)


def test_a_request_queues_one_attempt_and_records_its_payload(dashboard, monkeypatch):
    coordinator, _ = seed(dashboard)
    monkeypatch.setattr(coordinator.analysis_coordinator, 'run', lambda *args: None)

    response = dashboard.client.post(f'/api/jobs/{JID}/frame-series', json=PAYLOAD)

    assert response.status_code == 202, response.get_data(as_text=True)
    recorded = tasks(coordinator)[0]
    assert recorded['kind'] == 'frame-series'
    assert recorded['payload'] == PAYLOAD, 'the arguments the attempt was asked for are not what it records'
    assert response.get_json()['id'] == recorded['id']


def test_the_same_arguments_are_the_same_attempt(dashboard, monkeypatch):
    coordinator, _ = seed(dashboard)
    monkeypatch.setattr(coordinator.analysis_coordinator, 'run', lambda *args: None)
    first = dashboard.client.post(f'/api/jobs/{JID}/frame-series', json=PAYLOAD)
    settle(coordinator)

    again = dashboard.client.post(f'/api/jobs/{JID}/frame-series', json=PAYLOAD)

    assert again.status_code == 200, 'nothing changed, so nothing was recomputed'
    assert again.get_json()['id'] == first.get_json()['id']
    assert len(tasks(coordinator)) == 1


def test_a_changed_argument_is_a_new_attempt(dashboard, monkeypatch):
    coordinator, _ = seed(dashboard)
    monkeypatch.setattr(coordinator.analysis_coordinator, 'run', lambda *args: None)
    first = dashboard.client.post(f'/api/jobs/{JID}/frame-series', json=PAYLOAD)
    settle(coordinator)

    changed = dashboard.client.post(f'/api/jobs/{JID}/frame-series', json=dict(PAYLOAD, stride=5))

    assert changed.status_code == 202
    assert changed.get_json()['id'] != first.get_json()['id']
    assert [task['payload'] for task in tasks(coordinator)] == [PAYLOAD, dict(PAYLOAD, stride=5)]


def test_changed_trajectory_bytes_at_the_same_path_are_a_new_attempt(dashboard, monkeypatch):
    """The chosen trajectory is part of the signature: a replaced file is a different series, not the same one."""
    coordinator, run = seed(dashboard)
    monkeypatch.setattr(coordinator.analysis_coordinator, 'run', lambda *args: None)
    first = dashboard.client.post(f'/api/jobs/{JID}/frame-series', json=PAYLOAD)
    settle(coordinator)
    write(run, TRAJECTORY, size=201)

    again = dashboard.client.post(f'/api/jobs/{JID}/frame-series', json=PAYLOAD)

    assert again.status_code == 202
    assert again.get_json()['id'] != first.get_json()['id']
    assert len(tasks(coordinator)) == 2


def test_an_invalid_payload_is_a_400_and_creates_no_task(dashboard, monkeypatch):
    coordinator, _ = seed(dashboard)
    monkeypatch.setattr(coordinator.analysis_coordinator, 'run', lambda *args: None)

    response = dashboard.client.post(f'/api/jobs/{JID}/frame-series', json={'trajectory': TRAJECTORY})

    assert response.status_code == 400
    assert 'structure' in response.get_json()['error'], response.get_json()
    assert tasks(coordinator) == [], 'a refused payload must create no attempt'


def test_the_trajectory_endpoint_carries_each_segments_identity(dashboard):
    """A series records the identity of the bytes it sampled, so the endpoint has to report the same identity."""
    coordinator, run = seed(dashboard)

    body = dashboard.client.get(f'/api/jobs/{JID}/trajectory').get_json()

    nvt = next(entry for entry in body['segments'] if entry['name'] == 'NVT equilibration')
    assert nvt['trajectory'] == TRAJECTORY
    assert nvt['identity'] == segments.identity(run / TRAJECTORY)
    assert all('identity' in entry for entry in body['segments'] if entry.get('trajectory'))
