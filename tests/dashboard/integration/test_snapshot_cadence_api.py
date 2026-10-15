"""The one payload that changes what an analysis writes, checked before it is queued.

Every other kind's payload is a filter over inputs it already has; `snapshots`' cadence decides which frames end up
in the file the run view plays. A cadence that names nothing -- zero, negative, past the ceiling, or not a number --
is a 400 the reader can act on rather than a failure inside a worker they have to go and read, so the check lives on
the route and this is what holds it there. A cadence that is usable is passed through as the number it will be used
as, and the queue's own payload record is what proves it.

The analysis is never run here: the coordinator's `run` stands in for the worker, the way the default-analyses tests
do it, because what is under test is the door.
"""
import pytest

JID = '123456abcdef'


@pytest.fixture
def queued(dashboard, monkeypatch):
    """A completed run holding a trajectory, with the worker replaced by something that records the request."""
    coordinator = dashboard.coordinator
    job = {'id': JID, 'label': 'Frames', 'detergent': 'DDM', 'method': 'fast_forward', 'profile': 'draft-smoke',
           'status': 'completed', 'stage': 'complete', 'created': coordinator.now(), 'analyses': []}
    coordinator.database().replace([job])
    (coordinator.RUNS / JID).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(coordinator.analysis_coordinator, 'run', lambda *args: None)
    return dashboard


def test_a_cadence_that_means_nothing_is_refused_with_its_reason(queued):
    for cadence, reason in ((0, 'between 0 and 1000'), (-1, 'between 0 and 1000'), (2000, 'between 0 and 1000'),
                            ('soon', 'number of nanoseconds')):
        response = queued.client.post(f'/api/jobs/{JID}/snapshots', json={'interval_ns': cadence})

        assert response.status_code == 400, f'{cadence!r} was queued'
        assert reason in response.get_json()['error'], response.get_json()


def test_a_usable_cadence_is_queued_as_the_number_it_will_be_used_as(queued):
    response = queued.client.post(f'/api/jobs/{JID}/snapshots', json={'interval_ns': '2.5'})

    assert response.status_code == 202, response.get_json()
    assert response.get_json()['payload'] == {'interval_ns': 2.5}


def test_an_empty_payload_is_still_the_default_spread(queued):
    """The control posts `{}` when the field is blank: that has always been the even spread and stays it."""
    response = queued.client.post(f'/api/jobs/{JID}/snapshots', json={})

    assert response.status_code == 202, response.get_json()
    assert response.get_json()['payload'] == {}
