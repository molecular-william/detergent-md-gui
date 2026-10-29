"""`GET /api/run/devices`: the host's GPUs and what is already on each, in the shape the panel reads.

The panel does not probe the host and does not decide anything about a device -- it renders this answer. So the
route is one seam with two halves: `devices` is what the host reports (a list, empty when it reports none) and
`in_use` is `{index: compute process count}` for the devices that have one now. Both are stubbed here: no test may
need a GPU, and what this file judges is the shape the browser is handed.
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
    assert response.get_json() == {'devices': DEVICES, 'in_use': {'1': 2}}


def test_a_host_with_no_devices_is_an_answer_not_an_error(dashboard, monkeypatch):
    monkeypatch.setattr(devices, 'detect', lambda *arguments, **keywords: [])
    monkeypatch.setattr(devices, 'in_use', lambda *arguments, **keywords: {})
    with dashboard.client as client:
        response = client.get('/api/run/devices')
    assert response.status_code == 200
    assert response.get_json() == {'devices': [], 'in_use': {}}


def test_the_route_does_not_pretend_to_validate(dashboard, monkeypatch):
    """An index the host does not have is not this route's verdict: the refusal belongs at prepare."""
    monkeypatch.setattr(devices, 'detect', lambda *arguments, **keywords: DEVICES)
    monkeypatch.setattr(devices, 'in_use', lambda *arguments, **keywords: {})
    with dashboard.client as client:
        answer = client.get('/api/run/devices?mdrun_gpu=9')
    assert answer.status_code == 200 and answer.get_json()['devices'] == DEVICES
