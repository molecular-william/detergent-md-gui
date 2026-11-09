"""A panel that is still waiting says so, and stops saying so on every path.

The panel's own loading text is unchanged -- the Runs table still has its "Loading runs…" row. This file pins the
panel-level addition: one `role=status` line as the section's first child, `aria-busy` on the section while the mount
is pending, and both cleared when it settles. Nothing here asserts how long anything takes; each test holds the one
request that decides the answer and asserts the state on either side of it.
"""
import re

from playwright.sync_api import expect

from tests.harness.validation_fixtures import publish


def seed_run(dashboard, job_id, label='A run waiting behind the request'):
    """One completed run, built the way the route builds it, so the list has a row to draw."""
    dashboard.coordinator.database().replace([{
        'id': job_id, 'label': label, 'detergent': 'DDM', 'method': 'fast_forward',
        'status': 'completed', 'stage': 'complete', 'created': '2026-09-16T10:00:00+00:00',
        'started_at': '2026-09-16T10:00:00+00:00', 'layout_version': 2}])
    (dashboard.coordinator.RUNS / job_id / 'logs').mkdir(parents=True)
    return dashboard.coordinator.RUNS / job_id


def hold_first_run_list(page, held):
    """Hold the first `/api/jobs?…` request; every later poll passes through."""
    def handler(route):
        if held:
            route.continue_()
        else:
            held.append(route)
    page.route(re.compile(r'/api/jobs\?'), handler)


def wait_for_held(page, held):
    for _ in range(250):
        if held:
            return
        page.wait_for_timeout(20)
    raise AssertionError('the run-list request was never issued')


def test_the_runs_panel_is_busy_until_the_list_answers(dashboard, live_page):
    job_id = '00000000000a'
    seed_run(dashboard, job_id)
    page, errors = live_page
    held = []
    hold_first_run_list(page, held)

    page.goto(f'{live_page.base_url}/detergent-validation/runs')
    panel = page.locator('#runs')
    expect(panel).to_have_attribute('aria-busy', 'true')
    line = panel.locator('.panel-loading')
    expect(line).to_be_visible()
    expect(line).to_contain_text('Loading this panel')
    wait_for_held(page, held)

    held.pop().continue_()
    expect(panel).to_have_attribute('aria-busy', 'false')
    expect(line).to_have_count(0)
    expect(page.locator(f'.job[data-id="{job_id}"]')).to_have_count(1)
    assert errors == [], errors


def test_the_initially_open_panel_is_busy_on_a_cold_front_door(dashboard, live_page):
    seed_run(dashboard, '00000000000b')
    page, errors = live_page
    held = []
    hold_first_run_list(page, held)

    page.goto(live_page.base_url)
    # Which panel the front door opens is the server's and the registry's answer; read it back rather than assume.
    open_tab = page.locator('nav.subtabs [role=tab][aria-selected="true"][data-tab]')
    expect(open_tab).to_have_count(1)
    panel = page.locator('#' + open_tab.get_attribute('data-tab'))
    expect(panel).to_have_attribute('aria-busy', 'true')
    line = panel.locator('.panel-loading')
    expect(line).to_be_visible()
    expect(line).to_contain_text('Loading')
    wait_for_held(page, held)

    held.pop().continue_()
    expect(panel).to_have_attribute('aria-busy', 'false')
    expect(line).to_have_count(0)
    assert errors == [], errors


def test_a_failed_run_list_clears_the_panel_and_names_the_failure(dashboard, live_page):
    seed_run(dashboard, '00000000000c')
    page, errors = live_page
    held = []
    hold_first_run_list(page, held)

    page.goto(f'{live_page.base_url}/detergent-validation/runs')
    panel = page.locator('#runs')
    expect(panel).to_have_attribute('aria-busy', 'true')
    wait_for_held(page, held)
    held.pop().fulfill(status=500, content_type='application/json', body='{"error": "unavailable"}')

    expect(panel).to_have_attribute('aria-busy', 'false')
    expect(panel.locator('.panel-loading')).to_have_count(0)
    # The panel's own failure line, not the global mount notice: a live list reports a failed poll where it reports
    # every poll, in `#connection`, so the reader learns the list is stale rather than that the panel failed to mount.
    expect(page.locator('#connection')).to_contain_text('Updates unavailable')
    expect(page.locator('#connection')).to_contain_text('Run updates failed (500)')
    assert errors == [], errors


def test_an_analysis_section_says_it_is_reading_while_its_record_is_held(dashboard, live_page):
    """A section reads its own record before it can draw; the pane carries the line until the section writes.

    The section replaces the pane's children with its own markup, so the line must be the pane's, not the section's:
    holding `/mapping-consistency` keeps the section pending and the pane busy, and releasing it lets the section's
    own rows replace the line.
    """
    publish(dashboard, 'aa11bb22cc33')
    page, errors = live_page
    held = []
    state = {'release': False}

    def hold(route):
        record = '/api/jobs/aa11bb22cc33/mapping-consistency'
        if record in route.request.url and not state['release']:
            held.append(route)
        else:
            route.continue_()

    page.route('**/api/jobs/**', hold)
    page.goto(f'{live_page.base_url}/detergent-validation/run-view?run=aa11bb22cc33')
    root = page.locator('#run-view-analysis-A')
    expect(root.locator('.analysis-views button').first).to_be_visible(timeout=30000)
    root.locator('.analysis-views button[data-section="mapping-geometry"]').click()
    pane = root.locator('.analysis-pane[data-section="mapping-geometry"]')

    expect(pane).to_have_attribute('aria-busy', 'true')
    expect(pane.locator('.panel-loading')).to_contain_text('Reading this section')
    assert held, 'the section never asked for its record'
    # Both the map and the section may ask for the same record; releasing only one leaves the section waiting on
    # the other until the fetch's own timeout, which is a different failure from the one under test.
    state['release'] = True
    for route in held:
        route.continue_()

    expect(pane).to_have_attribute('aria-busy', 'false')
    expect(pane.locator('.panel-loading')).to_have_count(0)
    expect(pane.locator('.rvm-measure')).to_have_count(2)
    assert errors == [], errors
