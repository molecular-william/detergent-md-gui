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


def test_the_job_collection_answers_the_summary_unless_the_whole_record_is_asked_for(dashboard):
    """Measured before this: 100 runs were 434 kB, and the panels reading the list used 24 kB of it.

    The list is what three panels fetch to fill a `<select>`; the run view fetches one record through
    `/api/jobs/<id>` when it needs the rest. So the default is the projection and `view=full` is the opt-in.
    """
    job = seed(dashboard, 1)[0]
    job.update({'run_type': 'aa_only', 'settings': {'aa_production_ps': 5000},
                'analyses': [{'id': 'a1', 'kind': 'sasa', 'status': 'completed', 'outputs': ['big', 'list']}]})
    dashboard.coordinator.database().replace([job])

    summary = dashboard.client.get('/api/jobs').get_json()['jobs'][0]
    full = dashboard.client.get('/api/jobs?view=full').get_json()['jobs'][0]

    assert {'id', 'status', 'label', 'run_type', 'revision'} <= set(summary)
    # `detail_revision` is the summary's own addition: it is what the client sends back to ask whether the detail it
    # holds is still current, so it need not exist in a full record.
    assert set(summary) - {'detail_revision'} <= set(full), \
        'the summary is a projection of the same record, not a different one'
    assert 'settings' not in summary and 'settings' in full
    assert 'outputs' not in summary['analyses'][0] and 'outputs' in full['analyses'][0]


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
