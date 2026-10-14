"""The run-type filter on `GET /api/jobs`, and what it does to the callers that already use that endpoint.

The endpoint pages at 20 and caps `limit` at 100, and it had no way to ask for one run type. The run-view panel
needs one -- a workspace that shows a series' runs should not have to page every run in the repository and filter
in the browser, which would also make `total` a count of rows the caller did not ask for.

Three properties, and the third is the one worth the file:

* **absent `run_type` changes nothing.** The three existing callers (`runs.js`'s refresh, `mapping-validation.js`
  and `pdc.js`, each at `?limit=100`) send no such parameter and must get byte-identical answers. That is asserted
  against the store's own `page`, which is the thing they used to go through.
* **a named run type narrows the whole list, not the fetched page.** `total`, `page` and `limit` describe the
  narrowed list, so paging walks the filtered sequence.
* **a name the registry does not have is a 400 that says what it does have**, rather than an empty page -- which
  reads as "none of those exist" and is the same answer a working filter would give for a run type nobody has run.
"""
JOBS = '/api/jobs'


def _job(owner, run_id, run_type, *, status='completed', created=None, det='DDM', label=None):
    """One run record in the fixture's own database, with `run_type` optional so the legacy shape is testable."""
    job = {'id': run_id, 'label': label or f'{det} run', 'detergent': det, 'method': 'fast_forward',
           'status': status, 'stage': 'complete', 'created': created or owner.now(),
           'profile': 'standard', 'layout_version': 2}
    if run_type is not None:
        job['run_type'] = run_type
    owner.database().insert(job)
    return job


def _seed(owner):
    """Five runs across three run types, plus one record with no run type at all (the legacy combined job).

    `created` is written explicitly rather than taken from the clock: the list is ordered newest first, and a test
    about *which* rows a filter returns must not also be a test about how fast the fixture ran.
    """
    _job(owner, 'aaa000000001', 'aa_only', created='2026-10-01T00:00:01+00:00', label='oldest')
    _job(owner, 'bbb000000001', 'osmotic', created='2026-10-01T00:00:02+00:00', label='osmotic first')
    _job(owner, 'ccc000000001', 'aa_cg', status='failed', created='2026-10-01T00:00:03+00:00')
    _job(owner, 'ddd000000001', 'osmotic', created='2026-10-01T00:00:04+00:00', label='osmotic second')
    _job(owner, 'eee000000001', None, created='2026-10-01T00:00:05+00:00', label='legacy, no run type')


def _get(dashboard, query=''):
    with dashboard.client as c:
        response = c.get(JOBS + query)
    return response


def test_no_run_type_is_the_list_the_store_would_have_returned(dashboard):
    """The callers that send nothing keep the answer `Store.page` gives them, row for row."""
    _seed(dashboard.coordinator)

    body = _get(dashboard, '?limit=100').get_json()
    rows, total = dashboard.coordinator.database().page(1, 100)

    assert total == 5
    assert [job['id'] for job in body['jobs']] == [job['id'] for job, _ in rows]
    assert [job['id'] for job in body['jobs']] == ['eee000000001', 'ddd000000001', 'ccc000000001',
                                                   'bbb000000001', 'aaa000000001'], 'newest first'


def test_naming_a_run_type_returns_only_that_type_with_a_total_to_match(dashboard):
    owner = dashboard.coordinator
    _seed(owner)

    body = _get(dashboard, '?limit=100&run_type=osmotic').get_json()

    assert [job['id'] for job in body['jobs']] == ['ddd000000001', 'bbb000000001']
    assert body['total'] == 2, 'the total is the narrowed list, not the repository'
    assert body['limit'] == 100 and body['page'] == 1
    # And it is exactly the unfiltered list narrowed: the filter must not have a different idea of the order.
    everything = _get(dashboard, '?limit=100').get_json()['jobs']
    assert [job['id'] for job in body['jobs']] == \
           [job['id'] for job in everything if job.get('run_type') == 'osmotic']


def test_paging_walks_the_narrowed_sequence(dashboard):
    """Two pages of one row each are the filtered list in order, and `total` does not move between them."""
    _seed(dashboard.coordinator)

    first = _get(dashboard, '?limit=1&run_type=osmotic').get_json()
    second = _get(dashboard, '?limit=1&page=2&run_type=osmotic').get_json()

    assert [job['id'] for job in first['jobs']] == ['ddd000000001']
    assert [job['id'] for job in second['jobs']] == ['bbb000000001']
    assert first['total'] == second['total'] == 2


def test_a_record_with_no_run_type_is_the_historical_combined_job(dashboard):
    """`protocol.run_type_of` reads an absent run type as `aa_cg`, and the filter agrees rather than reporting it
    as a job of no type that no filter can reach."""
    _seed(dashboard.coordinator)

    body = _get(dashboard, '?limit=100&run_type=aa_cg').get_json()

    assert [job['id'] for job in body['jobs']] == ['eee000000001', 'ccc000000001']
    assert body['total'] == 2


def test_the_run_type_and_the_status_filters_compose(dashboard):
    _seed(dashboard.coordinator)

    body = _get(dashboard, '?limit=100&run_type=aa_cg&status=failed').get_json()

    assert [job['id'] for job in body['jobs']] == ['ccc000000001']
    assert body['total'] == 1


def test_a_run_type_the_registry_does_not_have_is_refused_and_the_refusal_names_the_vocabulary(dashboard):
    """A 400, not an empty page: an empty page is what a *working* filter says for a type nobody has run."""
    _seed(dashboard.coordinator)

    response = _get(dashboard, '?run_type=osmotik')

    assert response.status_code == 400, response.get_data(as_text=True)
    text = response.get_data(as_text=True)
    assert 'Unknown run type' in text and 'osmotic' in text and 'aa_cg' in text, text


def test_the_etag_belongs_to_the_answer_the_caller_asked_for(dashboard):
    """A conditional request must not be answered 304 from another filter's body."""
    _seed(dashboard.coordinator)

    everything = _get(dashboard, '?limit=100')
    filtered = _get(dashboard, '?limit=100&run_type=osmotic')

    assert everything.headers['ETag'] != filtered.headers['ETag']
    again = _get(dashboard, '?limit=100&run_type=osmotic')
    assert again.headers['ETag'] == filtered.headers['ETag']


# --- what the panel does with it -------------------------------------------------------------------------------

def test_the_osmotic_panel_can_ask_for_the_series_runs_alone(dashboard):
    """The run-view half of the filter: one request, one run type, and the count the caller asked for."""
    from dashboard.web.routes import runs as runs_route

    _seed(dashboard.coordinator)
    rows, total = runs_route.pages_of_runs(dashboard.coordinator, 1, 100, '', '', 'osmotic')

    assert total == 2 and len(rows) == 2
    assert all(job.get('run_type') == 'osmotic' for job, _ in rows)
    # The unfiltered path is the store's own answer, unchanged: no clause, no narrowing, all five rows.
    unfiltered, everyone = runs_route.pages_of_runs(dashboard.coordinator, 1, 100)
    assert everyone == 5 and len(unfiltered) == 5
