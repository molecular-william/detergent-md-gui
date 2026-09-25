"""One collection response shape, whichever request form is used.

/api/jobs answered a bare array without `?page` and an object with it, and
/api/jobs/<id>/artifacts did the same, so every client carried a defensive branch -- the
dashboard's own `Array.isArray(jobs) ? jobs : []` was one -- and a caller that forgot it
read a job list as an object and silently saw nothing.
"""


def seed(dashboard, count=3):
    jobs = [{'id': f'{index:012x}', 'status': 'completed', 'label': f'Run {index}', 'detergent': 'DDM',
             'created': f'2026-09-2{index}T00:00:00+00:00'} for index in range(count)]
    dashboard.coordinator.database().replace(jobs)
    return jobs


def test_the_job_collection_answers_one_shape(dashboard):
    seed(dashboard)
    client = dashboard.client
    for query in ('', '?page=1', '?view=summary'):
        payload = client.get('/api/jobs' + query).get_json()
        assert set(payload) == {'jobs', 'total', 'page', 'limit'}, query
        assert payload['page'] == 1 and payload['limit'] == 20, query
        assert payload['total'] == 3 and len(payload['jobs']) == 3, query


def test_the_job_collection_keeps_its_order_and_the_revision_field(dashboard):
    seed(dashboard)
    client = dashboard.client
    plain = [job['id'] for job in client.get('/api/jobs').get_json()['jobs']]
    paged = [job['id'] for job in client.get('/api/jobs?page=1&limit=20').get_json()['jobs']]
    assert plain == paged, 'the request form does not change the answer'
    assert all('revision' in job for job in client.get('/api/jobs').get_json()['jobs'])


def test_the_artifact_collection_answers_one_shape(dashboard):
    job = seed(dashboard, 1)[0]
    run_dir = dashboard.coordinator.RUNS / job['id']; run_dir.mkdir(parents=True)
    (run_dir / 'manifest.json').write_text('{}')
    (run_dir / 'result.gro').write_text('coordinates')
    client = dashboard.client
    for query in ('', '?page=1'):
        payload = client.get(f'/api/jobs/{job["id"]}/artifacts' + query).get_json()
        assert set(payload) == {'artifacts', 'total', 'page', 'limit'}, query
        assert payload['total'] == 2 and [item['path'] for item in payload['artifacts']] == ['manifest.json', 'result.gro']
