"""The three ways a run is created, held to one contract.

Queue, retry and clone used to pass different arguments to `create_job`, and the difference was not a
decoration: `admission.validate_run_type` requires `composition_id` for a `cg_composition` run, so retrying or
cloning one answered 400, and a cloned complex run lost the `protein` and `template` it was built from -- a
different system that happens to share a run type.

These tests do not build those runs. They read what each route hands `create_job`, because that is the seam the
drift was in: a stubbed `create_job` records the call, and a source record states the fields a real one would.
"""
import pytest


def record(**fields):
    """A stored job row, shaped the way the coordinator stores one."""
    base = {'id': 'ab12cd34ef56', 'label': 'a run', 'detergent': 'DDM', 'method': 'bartender',
            'status': 'failed', 'stage': 'complete', 'run_type': 'pdc', 'profile': 'standard',
            'settings': {'pdc_assessment_ns': 100}, 'created': '2026-10-21T02:00:00+00:00'}
    base.update(fields)
    return base


@pytest.fixture
def created(dashboard, monkeypatch):
    """`create_job`, recorded instead of run. Returns the list of calls."""
    calls = []

    def fake(job_or_detergent, method=None, label='', **kwargs):
        calls.append({'detergent': job_or_detergent, 'method': method, 'label': label, **kwargs})
        # Enough of a job row for the route to answer with; no run directory exists, which the view reports.
        return {'id': 'ffeeddccbbaa', 'label': label, 'detergent': job_or_detergent, 'method': method,
                'status': 'queued', 'stage': 'queued', 'run_type': kwargs.get('run_type'),
                'created': '2026-10-21T03:00:00+00:00'}

    monkeypatch.setattr(dashboard.coordinator, 'create_job', fake)
    return calls


def test_cloning_a_composition_run_keeps_the_composition_it_is_a_clone_of(dashboard, created):
    """The 400 this prevents: admission refuses a `cg_composition` payload with no `composition_id`."""
    dashboard.coordinator.database().insert(record(id='ab12cd34ef56', run_type='cg_composition',
                                                   composition_id='composition_ddm_belt', method='bartender'))

    response = dashboard.client.post('/api/jobs/ab12cd34ef56/clone', json={'label': 'the clone'})

    assert response.status_code == 201, response.data
    assert len(created) == 1
    assert created[0]['composition_id'] == 'composition_ddm_belt'
    assert created[0]['run_type'] == 'cg_composition'


def test_a_clone_carries_what_a_complex_run_is_built_from(dashboard, created):
    """`protein` and `template` are not settings: without them the clone builds whatever the defaults name."""
    dashboard.coordinator.database().insert(record(id='ab12cd34ef56', run_type='pdc', protein='1AT9',
                                                   template='templates/ddm_belt.json'))

    response = dashboard.client.post('/api/jobs/ab12cd34ef56/clone', json={})

    assert response.status_code == 201, response.data
    assert created[0]['protein'] == '1AT9'
    assert created[0]['template'] == 'templates/ddm_belt.json'


def test_a_retry_carries_the_fields_the_failed_run_was_built_from(dashboard, created):
    """A retry rebuilds the same run. Losing `protein` there rebuilds a different system under the same label."""
    dashboard.coordinator.database().insert(record(id='ab12cd34ef56', run_type='pdc', protein='1AT9',
                                                   template='templates/ddm_belt.json'))

    response = dashboard.client.post('/retry/ab12cd34ef56', json={})

    assert response.status_code == 201, response.data
    call = created[0]
    assert call['protein'] == '1AT9' and call['template'] == 'templates/ddm_belt.json'
    assert call['retry_of'] == 'ab12cd34ef56'
    assert call['run_type'] == 'pdc'


def test_a_retry_of_a_composition_run_keeps_its_composition(dashboard, created):
    """The same drift on the retry path, which answers 400 without it."""
    dashboard.coordinator.database().insert(record(id='ab12cd34ef56', run_type='cg_composition',
                                                   composition_id='composition_ddm_belt'))

    response = dashboard.client.post('/retry/ab12cd34ef56', json={})

    assert response.status_code == 201, response.data
    assert created[0]['composition_id'] == 'composition_ddm_belt'
