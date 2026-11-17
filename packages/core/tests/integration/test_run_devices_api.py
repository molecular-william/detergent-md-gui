"""`GET /api/run/devices`: the host's GPUs and what is already on each, in the shape the panel reads.

The panel does not probe the host and does not decide anything about a device -- it renders this answer. So the
route is one seam: `devices` is what the host reports (a list, empty when it reports none), `in_use` is
`{index: compute process count}` for the devices that have one now, and `active` is the coordinator's own
`{index: [run ids]}` -- which is what the New run form asks before offering to share a busy device. The first two
are stubbed here: no test may need a GPU, and what this file judges is the shape the browser is handed.
"""
from dashboard.execution import devices

DEVICES = [{'index': 0, 'name': 'NVIDIA GeForce RTX 4090', 'memory_mib': 24564, 'uuid': 'GPU-aaaa'},
           {'index': 1, 'name': 'NVIDIA A100-SXM4-40GB', 'memory_mib': 40960, 'uuid': 'GPU-bbbb'}]


def test_the_route_answers_the_devices_and_the_processes_on_them(dashboard, monkeypatch):
    monkeypatch.setattr(devices, 'detect', lambda *arguments, **keywords: DEVICES)
    monkeypatch.setattr(devices, 'in_use', lambda *arguments, **keywords: {1: 2})
    with dashboard.client as client:
        response = client.get('/api/run/devices')
    assert response.status_code == 200
    assert response.get_json() == {'devices': DEVICES, 'in_use': {'1': 2}, 'active': {}}


def test_a_host_with_no_devices_is_an_answer_not_an_error(dashboard, monkeypatch):
    monkeypatch.setattr(devices, 'detect', lambda *arguments, **keywords: [])
    monkeypatch.setattr(devices, 'in_use', lambda *arguments, **keywords: {})
    with dashboard.client as client:
        response = client.get('/api/run/devices')
    assert response.status_code == 200
    assert response.get_json() == {'devices': [], 'in_use': {}, 'active': {}}


def test_active_names_the_device_a_running_run_holds(dashboard, monkeypatch):
    """`active` is the dashboard's own claim, not NVML's: `in_use` is empty before mdrun starts.

    The form disables Share on a device with no active run, so this answer has to name the run's device even
    when the host reports no compute process yet.
    """
    owner = dashboard.coordinator
    owner.database().insert({'id': 'aaaaaaaaaaaa', 'label': 'a run', 'status': 'running',
                             'stage': 'input', 'settings': {'mdrun_gpu': 1},
                             'created': owner.now()})
    owner.WORKERS['aaaaaaaaaaaa'] = owner.Worker()
    monkeypatch.setattr(devices, 'detect', lambda *arguments, **keywords: DEVICES)
    monkeypatch.setattr(devices, 'in_use', lambda *arguments, **keywords: {})
    with dashboard.client as client:
        answer = client.get('/api/run/devices').get_json()
    assert answer['active'] == {'1': ['aaaaaaaaaaaa']}
    assert answer['devices'] == DEVICES and answer['in_use'] == {}


def test_the_route_does_not_pretend_to_validate(dashboard, monkeypatch):
    """An index the host does not have is not this route's verdict: the refusal belongs at prepare."""
    monkeypatch.setattr(devices, 'detect', lambda *arguments, **keywords: DEVICES)
    monkeypatch.setattr(devices, 'in_use', lambda *arguments, **keywords: {})
    with dashboard.client as client:
        answer = client.get('/api/run/devices?mdrun_gpu=9')
    assert answer.status_code == 200 and answer.get_json()['devices'] == DEVICES
