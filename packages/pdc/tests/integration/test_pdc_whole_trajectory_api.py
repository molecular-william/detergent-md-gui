"""The Run view's whole-trajectory endpoints: describe the two files, queue one rebuild.

The rebuild itself is `test_pdc_whole_trajectory.py`; this file pins the HTTP contract the panel reads and posts, and
that only a pdc run -- the run type whose stage writes `whole.xtc` -- is served.
"""
from __future__ import annotations

from detergent_pdc.execution import rebuild_whole

JOB = '0000000000ab'


def written_run(dashboard, job_id=JOB, *, stage='06_assessment', raw=b'raw trajectory'):
    """A pdc run whose stage holds the raw production trajectory and its run input."""
    prod = dashboard.coordinator.RUNS / job_id / 'stages' / stage / 'prod'
    prod.mkdir(parents=True)
    (prod / 'run.xtc').write_bytes(raw)
    (prod / 'run.tpr').write_bytes(b'tpr')
    (prod / 'run.gro').write_text('gro')


def insert_job(dashboard, job_id=JOB, *, run_type='pdc'):
    dashboard.coordinator.database().insert({'id': job_id, 'run_type': run_type, 'status': 'completed',
                                             'stage': 'complete', 'molecule_id': 'DDM',
                                             'created': '2026-11-05T00:00:00+00:00'})


def test_the_get_route_states_the_raw_and_derived_files(dashboard):
    insert_job(dashboard)
    written_run(dashboard)

    answer = dashboard.client.get(f'/api/pdc/{JOB}/whole-trajectory').get_json()

    assert answer['stage'] == 'assessment'
    assert answer['raw']['bytes'] == len(b'raw trajectory')
    assert answer['whole'] is None
    assert answer['defaults'] == {'dt_ps': 100, 'decimals': 2}
    assert answer['decimals'] == [1, 2, 3]
    assert answer['state'] == {}


def test_the_post_route_queues_the_chosen_numbers(dashboard, monkeypatch):
    insert_job(dashboard)
    written_run(dashboard)
    seen = {}

    def start(run_dir, *, dt_ps=None, decimals=None):
        seen.update({'run': str(run_dir), 'dt_ps': dt_ps, 'decimals': decimals})
        return {'status': 'running', 'dt_ps': dt_ps, 'decimals': decimals, 'started_at': 'now'}

    monkeypatch.setattr(rebuild_whole, 'start', start)

    response = dashboard.client.post(f'/api/pdc/{JOB}/whole-trajectory', json={'dt_ps': 100, 'decimals': 2})

    assert response.status_code == 202, response.get_data(as_text=True)
    assert seen['dt_ps'] == 100 and seen['decimals'] == 2
    assert seen['run'].endswith(JOB)
    assert response.get_json()['state']['status'] == 'running'


def test_the_post_route_defaults_to_compact(dashboard, monkeypatch):
    insert_job(dashboard)
    written_run(dashboard)
    seen = {}
    monkeypatch.setattr(rebuild_whole, 'start', lambda run_dir, **numbers: seen.update(numbers) or {'status': 'running'})

    response = dashboard.client.post(f'/api/pdc/{JOB}/whole-trajectory', json={})

    assert response.status_code == 202
    assert seen == {'dt_ps': 100, 'decimals': 2}


def test_an_impossible_choice_is_refused_with_its_reason(dashboard):
    insert_job(dashboard)
    written_run(dashboard)

    assert dashboard.client.post(f'/api/pdc/{JOB}/whole-trajectory', json={'decimals': 4}).status_code == 400
    assert dashboard.client.post(f'/api/pdc/{JOB}/whole-trajectory', json={'dt_ps': 0}).status_code == 400


def test_only_a_pdc_run_is_served(dashboard):
    insert_job(dashboard, run_type='aa_only')
    written_run(dashboard)

    assert dashboard.client.get(f'/api/pdc/{JOB}/whole-trajectory').status_code == 400
    assert dashboard.client.get('/api/pdc/000000000000/whole-trajectory').status_code == 404
