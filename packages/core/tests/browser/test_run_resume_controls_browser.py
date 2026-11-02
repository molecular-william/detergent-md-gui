"""The Runs table's two resume doors, told apart by the body they POST.

`Resume` (`.job-continue`) continues the stage that stopped from its own checkpoint and appends to the same
trajectory, so it sends `{}`. The stage picker (`.resume-control`) restarts from a stage's inputs, so it sends
`{stage}`. Both go to `POST /api/jobs/<id>/resume`; what the server does with either body is pinned by the route's
own tests, and here the answer is routed so no run is touched.

The jobs list is routed too: `can_continue` is the server view's field, and this page's job is to honour it --
including its absence, which reads as false so the page works before the view grows the field.
"""
import json
import re

from playwright.sync_api import expect

from tests.harness import browser

CONTINUABLE = '0000000000a1'
NO_CHECKPOINT = '0000000000a2'
UNSTATED = '0000000000a3'


def job(job_id, **overrides):
    record = {
        'id': job_id, 'label': f'Run {job_id}', 'detergent': 'DDM', 'method': 'fast_forward',
        'status': 'failed', 'stage': 'CG simulation', 'run_type': 'aa_cg',
        'created': '2026-11-02T09:00:00+00:00', 'started_at': '2026-11-02T09:00:00+00:00',
        'layout_version': 2, 'can_cancel': False, 'can_retry': True, 'can_delete': True,
        'resume_stages': ['02_system', '03_npt'], 'stages': [], 'workflow_stages': [],
        'analyses': [], 'elapsed_seconds': 60, 'revision': 1,
    }
    return record | overrides


def serve_jobs(page, records):
    """Answer the Runs table's list; `records` is read at answer time, so a later call can report a new state."""
    page.route(re.compile(r'/api/jobs\?\S*$'), lambda route: route.fulfill(
        json={'jobs': records(), 'total': len(records()), 'page': 1, 'limit': 20}))


def capture_post(page, pattern, on_answer=None):
    """Route one resume request, recording its method and JSON body, then answering it."""
    asked = []

    def record(route):
        asked.append({'method': route.request.method,
                      'body': json.loads(route.request.post_data or 'null')})
        if on_answer is not None:
            on_answer()
        route.fulfill(json={'ok': True})

    page.route(pattern, record)
    return asked


def open_runs(page, base_url):
    browser.open_panel(page, base_url, '/detergent-validation/runs',
                       ready=lambda page: expect(page.locator('#jobs > tbody.job').first).to_be_visible())


def test_resume_is_offered_only_for_a_run_that_can_continue(dashboard, live_page):
    """Three failed runs: one with a checkpoint to continue from, one whose stage left none, and one whose view says
    nothing at all. Only the first offers Resume; an absent `can_continue` is not permission."""
    page, errors = live_page
    records = [job(CONTINUABLE, can_continue=True), job(NO_CHECKPOINT, can_continue=False), job(UNSTATED)]
    serve_jobs(page, lambda: records)
    open_runs(page, live_page.base_url)

    expect(page.locator(f'.job[data-id="{CONTINUABLE}"] .job-continue')).to_be_visible()
    expect(page.locator(f'.job[data-id="{NO_CHECKPOINT}"] .job-continue')).to_be_hidden()
    expect(page.locator(f'.job[data-id="{UNSTATED}"] .job-continue')).to_be_hidden()
    assert errors == [], errors


def test_resume_posts_an_empty_body_and_refreshes_the_table(dashboard, live_page):
    """`Resume` continues in place: no stage is named, and the notice says what it does with the trajectory."""
    page, errors = live_page
    state = {'records': [job(CONTINUABLE, can_continue=True, status='failed')]}
    serve_jobs(page, lambda: state['records'])

    # The answer to Resume moves the run on, so a refreshed table is visible as the card's new status.
    def resumed():
        state['records'] = [job(CONTINUABLE, can_continue=True, status='running')]

    asked = capture_post(page, re.compile(rf'/api/jobs/{CONTINUABLE}/resume$'), on_answer=resumed)
    open_runs(page, live_page.base_url)
    card = page.locator(f'.job[data-id="{CONTINUABLE}"]')

    card.locator('.job-continue').click()

    expect(page.locator('#notice')).to_contain_text('checkpoint')
    expect(page.locator('#notice')).to_contain_text('appends')
    expect(card.locator('.job-status')).to_have_text('running')
    assert asked == [{'method': 'POST', 'body': {}}], f'Resume must send an empty body: {asked}'
    assert errors == [], errors


def test_restart_posts_the_stage_named_in_the_picker(dashboard, live_page):
    """The picker still restarts from the chosen stage, so the body names it."""
    page, errors = live_page
    serve_jobs(page, lambda: [job(CONTINUABLE, can_continue=True)])
    asked = capture_post(page, re.compile(rf'/api/jobs/{CONTINUABLE}/resume$'))
    open_runs(page, live_page.base_url)
    card = page.locator(f'.job[data-id="{CONTINUABLE}"]')

    card.locator('.resume-stage').select_option('02_system')
    card.locator('.job-resume').click()

    expect(page.locator('#notice')).to_contain_text('Run resumed')
    assert asked == [{'method': 'POST', 'body': {'stage': '02_system'}}], asked
    assert errors == [], errors


def test_delete_still_sends_delete(dashboard, live_page):
    """Resume sits beside Delete and must not have changed what Delete does."""
    page, errors = live_page
    serve_jobs(page, lambda: [job(CONTINUABLE)])
    asked = []
    page.route(re.compile(rf'/api/jobs/{CONTINUABLE}$'), lambda route: (
        asked.append({'method': route.request.method, 'url': route.request.url}),
        route.fulfill(json={'deleted': True}))[1])
    open_runs(page, live_page.base_url)
    page.once('dialog', lambda dialog: dialog.accept())

    page.locator(f'.job[data-id="{CONTINUABLE}"] .job-delete').click()

    expect(page.locator('#notice')).to_have_text('Run deleted.')
    assert asked == [{'method': 'DELETE', 'url': f'{live_page.base_url}/api/jobs/{CONTINUABLE}'}], asked
    assert errors == [], errors
