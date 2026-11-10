"""The Run view's Analysis card: a run's own figures, the controls that queue them, and its analysis checklist.

The card moved here from the Runs page's **Analysis graphs** panel, so what this file pins is the move rather than the
viewer's mechanics: a monitor draws *its own* run's figures, a second monitor draws its own, a run with none says so
instead of showing an empty box, and the three queue buttons post the routes the Runs card used to post. The figure
viewer's zoom and tabs are the same component, exercised through this card.

Every run, figure and answer is built by this test in its own workspace; the analyses and figures routes are stubbed
where the test is about what the card asks for, and real where it is about what it draws.
"""
import re
import time

from playwright.sync_api import expect

A_RUN = 'abcdef123456'
B_RUN = 'abcdef123457'
WORKSPACE = 'detergent-validation'

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="400" height="200">'
       '<circle cx="200" cy="100" r="90" fill="blue"/></svg>')


def seed(dashboard, *, overview=False):
    """Two completed CG runs, each with its own figures, and no analysis tasks behind them.

    `overview` gives the first run a published `trajectory-overview` figure under the analysis tree the figures route
    reads, so a test can tell the disabled placeholder from the real tab.
    """
    owner = dashboard.coordinator
    rows = {A_RUN: ('alpha', 'beta'), B_RUN: ('gamma',)}
    for run_id, names in rows.items():
        owner.database().insert({'id': run_id, 'run_type': 'cg', 'label': f'Figure run {run_id[-1]}',
                                 'detergent': 'DDM', 'method': 'fast_forward', 'status': 'completed',
                                 'stage': 'complete', 'created': owner.now(), 'analyses': []})
        directory = owner.RUNS / run_id
        directory.mkdir(parents=True, exist_ok=True)
        for name in names:
            (directory / f'{name}.svg').write_text(SVG)
    (owner.RUNS / A_RUN / 'surface-comparison.html').write_text(
        '<!doctype html><title>Surface comparison</title><h1>Interactive figure</h1>')
    if overview:
        output = owner.RUNS / A_RUN / 'analyses/trajectory-overview/signature/attempt/output/key'
        output.mkdir(parents=True)
        (output / 'trajectory-overview.svg').write_text(SVG)


def plots(page, side='A'):
    return page.locator(f'#run-view-analysis-plots-{side}')


def note(page, side='A'):
    return page.locator(f'#run-view-analysis-note-{side}')


def tasks(page, side='A'):
    return page.locator(f'#run-view-analysis-tasks-{side}')


def tick(page, item):
    """The box's tick is a CSS pseudo-element, so `none` is an unticked box and a quoted string is the drawn tick."""
    return item.locator('.check').evaluate("el => getComputedStyle(el, '::after').content")


def open_view(page, live_page, run_id=A_RUN, tabs=4):
    """The Run view with `run_id` in monitor A; the second monitor picks the other run by itself.

    The tab count includes the disabled `trajectory overview` placeholder: three real figures plus the pending one.
    """
    page.goto(f'{live_page.base_url}/{WORKSPACE}/run-view?run={run_id}')
    expect(page.locator('#runview')).to_be_visible()
    expect(plots(page).locator('[role=tab]')).to_have_count(tabs)
    return page


def test_a_monitor_draws_its_own_runs_figures(dashboard, live_page):
    seed(dashboard)
    page, errors = live_page

    open_view(page, live_page)

    expect(note(page)).to_contain_text('3 figures')
    expect(plots(page).locator('.figure-media')).to_have_count(1)
    expect(plots(page).get_by_role('tab', name='alpha', exact=True)).to_have_attribute('aria-selected', 'true')
    plots(page).get_by_role('tab', name='surface comparison', exact=True).click()
    expect(plots(page).locator('iframe.figure-media')).to_have_attribute('sandbox', 'allow-scripts')
    plots(page).get_by_role('tab', name='beta', exact=True).click()
    plots(page).get_by_role('button', name='Zoom in', exact=True).click()
    expect(plots(page).locator('.figure-zoom-level')).to_have_text('125%')
    assert errors == [], errors


def test_the_two_monitors_hold_their_own_runs_figures_and_state(dashboard, live_page):
    """Each monitor is its own run: the tabs, the chosen figure and the zoom do not leak across the pair."""
    seed(dashboard)
    page, errors = live_page

    open_view(page, live_page)
    expect(plots(page, 'B').get_by_role('tab', name='gamma', exact=True)).to_be_visible()
    plots(page).get_by_role('tab', name='beta', exact=True).click()
    plots(page, 'B').get_by_role('button', name='Zoom in', exact=True).click()

    expect(plots(page).locator('.figure-source')).to_have_text('beta.svg')
    expect(plots(page, 'B').locator('.figure-source')).to_have_text('gamma.svg')
    expect(plots(page, 'B').locator('.figure-zoom-level')).to_have_text('125%')
    assert errors == [], errors


def test_a_run_with_no_figures_says_so_instead_of_drawing_an_empty_box(dashboard, live_page):
    dashboard.coordinator.database().insert(
        {'id': A_RUN, 'run_type': 'cg', 'label': 'Bare run', 'detergent': 'DDM', 'method': 'fast_forward',
         'status': 'completed', 'stage': 'complete', 'created': dashboard.coordinator.now(), 'analyses': []})
    (dashboard.coordinator.RUNS / A_RUN).mkdir(parents=True, exist_ok=True)
    page, errors = live_page

    page.goto(f'{live_page.base_url}/{WORKSPACE}/run-view?run={A_RUN}')
    expect(page.locator('#runview')).to_be_visible()

    expect(note(page)).to_contain_text('No analysis graphs yet')
    expect(plots(page).locator('.figure-empty')).to_be_visible()
    pending = plots(page).get_by_role('tab', name='trajectory overview', exact=True)
    expect(pending).to_be_visible()
    expect(pending).to_be_disabled()
    assert errors == [], errors


def test_the_trajectory_overview_tab_is_present_and_disabled_before_it_is_calculated(dashboard, live_page):
    """The tab row says what the run can produce before it has produced it. The pending tab is first, cannot be
    selected, and leaves the first real figure selected."""
    seed(dashboard)
    page, errors = live_page

    open_view(page, live_page)

    pending = plots(page).get_by_role('tab', name='trajectory overview', exact=True)
    expect(pending).to_be_visible()
    expect(pending).to_be_disabled()
    expect(pending).to_have_attribute('aria-disabled', 'true')
    expect(plots(page).get_by_role('tab', name='alpha', exact=True)).to_have_attribute('aria-selected', 'true')
    assert errors == [], errors


def test_a_published_overview_is_a_real_tab_and_the_placeholder_is_gone(dashboard, live_page):
    seed(dashboard, overview=True)
    page, errors = live_page

    open_view(page, live_page)

    tab = plots(page).get_by_role('tab', name='trajectory overview', exact=True)
    expect(tab).to_be_enabled()
    expect(plots(page).locator('.figure-tab-pending')).to_have_count(0)
    assert errors == [], errors


def test_the_recompute_button_posts_its_route_and_reports_what_follows(dashboard, live_page):
    """The button is the only way a person can ask a finished run for the analyses its code has moved past."""
    seed(dashboard)
    page, errors = live_page
    asked = []

    def recompute(route):
        asked.append(route.request.method)
        route.fulfill(json={'queued': ['abc123'], 'owed': ['bonded-cross-check']})

    page.route(re.compile(rf'/api/jobs/{A_RUN}/analyses/recompute$'), recompute)
    open_view(page, live_page)
    button = page.get_by_role('button', name='Recompute', exact=True).first
    expect(button).to_be_enabled()
    button.click()

    expect(note(page)).to_contain_text('1 analysis queued, 1 to follow')
    assert asked == ['POST'], 'the panel drew a control that asked nothing'
    assert errors == [], errors


def test_the_trajectory_overview_button_queues_one_first_look(dashboard, live_page):
    seed(dashboard)
    page, errors = live_page
    asked = []

    def overview(route):
        asked.append(route.request.method)
        route.fulfill(status=202, json={'id': 'task-1', 'status': 'queued'})

    page.route(re.compile(rf'/api/jobs/{A_RUN}/trajectory-overview$'), overview)
    open_view(page, live_page)
    button = page.locator('#run-view-analysis-overview-A')
    expect(button).to_be_visible()
    button.click()

    expect(note(page)).to_contain_text('Trajectory overview queued')
    assert asked == ['POST']
    assert errors == [], errors


def test_a_running_task_is_listed_with_a_cancel_and_the_cancel_posts(dashboard, live_page):
    """The checklist moved with the card: a running analysis shows its progress, offers Cancel, and cancelling
    disables that button rather than leaving a second request on the table."""
    seed(dashboard)
    page, errors = live_page
    cancelled = []

    state = {'tasks': [{'id': 'task-9', 'kind': 'stability', 'status': 'running', 'progress': 'reading pairs',
                        'directory': 'analyses/stability/test'}]}

    def analyses(route):
        route.fulfill(json=state['tasks'])

    def cancel(route):
        cancelled.append(route.request.method)
        state['tasks'][0]['status'] = 'cancelling'
        route.fulfill(json={'id': 'task-9', 'status': 'cancelling'})

    page.route(re.compile(rf'/api/jobs/{A_RUN}/analyses(?:\?.*)?$'), analyses)
    page.route(re.compile(rf'/api/jobs/{A_RUN}/analyses/task-9/cancel$'), cancel)
    open_view(page, live_page)

    listing = tasks(page)
    expect(listing.locator('li[data-status="running"]')).to_have_count(1)
    expect(listing).to_contain_text('stability · running')
    expect(listing.locator('.check-progress')).to_have_text('reading pairs')
    expect(listing.get_by_role('button', name='Cancel analysis', exact=True)).to_be_enabled()
    listing.get_by_role('button', name='Cancel analysis', exact=True).click()

    expect(listing.locator('li[data-status="cancelling"]')).to_have_count(1)
    expect(listing.get_by_role('button', name='Cancel analysis', exact=True)).to_be_disabled()
    assert cancelled == ['POST'], 'the card drew a cancel that asked nothing'
    assert errors == [], errors


def test_the_task_list_keeps_one_row_per_kind_and_shows_the_latest_error(dashboard, live_page):
    """The run keeps every attempt; the checklist shows the current state. The failed row's reason is the last line
    of that attempt's own log, not the command line the coordinator recorded, and there is no Log link to open."""
    seed(dashboard)
    page, errors = live_page
    state = {'tasks': [
        {'id': 'old', 'kind': 'bonded-cross-check', 'status': 'failed', 'error': 'Command old',
         'directory': 'analyses/bonded-cross-check/signature/old',
         'created_at': '2026-11-05T00:00:00+00:00'},
        {'id': 'new', 'kind': 'bonded-cross-check', 'status': 'failed', 'error': 'Command new',
         'directory': 'analyses/bonded-cross-check/signature/new',
         'created_at': '2026-11-06T00:00:00+00:00'},
        {'id': 'series', 'kind': 'frame-series', 'status': 'completed',
         'created_at': '2026-11-06T01:00:00+00:00'},
    ]}

    page.route(re.compile(rf'/api/jobs/{A_RUN}/analyses(?:\?.*)?$'), lambda route: route.fulfill(json=state['tasks']))

    def console(route):
        body = 'old reason\n' if '/old/' in route.request.url else \
            'warning\nValueError: LMNG_ff_inter.itp:47: a bond needs 5 fields, found 2\n'
        route.fulfill(body=body, content_type='text/plain')

    page.route(re.compile(rf'/api/jobs/{A_RUN}/artifacts/.*console\.log.*'), console)
    open_view(page, live_page)

    listing = tasks(page)
    failed = listing.locator('li[data-status="failed"]')
    completed = listing.locator('li[data-status="completed"]')
    expect(listing.locator('li')).to_have_count(2)
    expect(failed).to_have_count(1)
    expect(completed).to_have_count(1)
    expect(failed).to_contain_text('bonded-cross-check · failed')
    expect(failed.locator('.check-why')).to_have_text('ValueError: LMNG_ff_inter.itp:47: a bond needs 5 fields, found 2')
    expect(listing).not_to_contain_text('Command old')
    expect(listing).not_to_contain_text('Command new')
    expect(listing).not_to_contain_text('old reason')
    assert tick(page, failed) == 'none', 'a failed analysis is ticked'
    assert tick(page, completed) != 'none', 'a completed analysis has no tick'
    expect(listing.locator('a.task-log')).to_have_count(0)
    assert errors == [], errors


def test_a_mixed_list_draws_each_state_and_ticks_only_the_calculated_analysis(dashboard, live_page):
    """Completed + failed + running in one list: three rows, three data-status values, one tick, one reason and one
    Cancel. The failed row has no Log link, because the reason is the line and the console stays in the artifacts."""
    seed(dashboard)
    page, errors = live_page
    state = {'tasks': [
        {'id': 'done', 'kind': 'frame-series', 'status': 'completed',
         'created_at': '2026-11-06T01:00:00+00:00'},
        {'id': 'bad', 'kind': 'bonded-cross-check', 'status': 'failed',
         'directory': 'analyses/bonded-cross-check/signature/attempt',
         'created_at': '2026-11-06T02:00:00+00:00'},
        {'id': 'busy', 'kind': 'dihedral-fit', 'status': 'running', 'progress': 'reading pairs',
         'created_at': '2026-11-06T03:00:00+00:00'},
    ]}

    page.route(re.compile(rf'/api/jobs/{A_RUN}/analyses(?:\?.*)?$'), lambda route: route.fulfill(json=state['tasks']))
    page.route(re.compile(rf'/api/jobs/{A_RUN}/artifacts/.*console\.log.*'),
               lambda route: route.fulfill(body='warning\nLMNG_ff_inter.itp:47: a bond needs 5 fields, found 2\n',
                                           content_type='text/plain'))
    open_view(page, live_page)

    listing = tasks(page)
    items = listing.locator('li')
    expect(items).to_have_count(3)
    assert [items.nth(index).get_attribute('data-status') for index in range(3)] == \
        ['completed', 'failed', 'running']
    completed, failed, running = items.nth(0), items.nth(1), items.nth(2)
    assert tick(page, completed) != 'none', 'the completed analysis has no tick'
    assert tick(page, failed) == 'none', 'the failed analysis is ticked'
    assert tick(page, running) == 'none', 'the running analysis is ticked'
    expect(failed.locator('.check-why')).to_have_text('LMNG_ff_inter.itp:47: a bond needs 5 fields, found 2')
    expect(failed.locator('a.task-log')).to_have_count(0)
    expect(running.locator('.check-progress')).to_have_text('reading pairs')
    expect(running.get_by_role('button', name='Cancel analysis', exact=True)).to_be_enabled()
    assert errors == [], errors


def test_the_card_stops_polling_while_the_run_view_is_hidden_and_reads_on_return(dashboard, live_page):
    """A card on another panel (or behind a hidden tab) asks nothing; returning runs the same reload the timer would.

    The task line is the progress line, so the resumed answer must overwrite it in the same pass: a paused card that
    came back to its old phase would read as a frozen run. Counting is from the route, not from a flag.
    """
    seed(dashboard)
    page, errors = live_page
    page.add_init_script('window.__runViewPollMs = 300')
    state = {'tasks': [{'id': 'task-7', 'kind': 'stability', 'status': 'running',
                        'directory': 'analyses/stability/test', 'progress': 'phase one',
                        'created_at': '2026-11-09T10:00:00+00:00'}]}
    hits = []

    def analyses(route):
        hits.append(route.request.url)
        route.fulfill(json=state['tasks'])

    page.route(re.compile(rf'/api/jobs/{A_RUN}/analyses(?:\?.*)?$'), analyses)
    open_view(page, live_page)
    expect(tasks(page)).to_contain_text('phase one')

    deadline = time.monotonic() + 10
    while len(hits) < 2 and time.monotonic() < deadline:
        page.wait_for_timeout(50)
    assert len(hits) >= 2, f'the card never polled a running task: {len(hits)}'

    page.evaluate("""() => {
      document.querySelector('#runview').hidden = true;
      document.dispatchEvent(new CustomEvent('dashboard:tab', {detail: {id: 'runs'}}));
    }""")
    page.wait_for_timeout(1500)          # five cadences at the seam, plus the one already pending
    settled = len(hits)
    page.wait_for_timeout(900)
    assert len(hits) == settled, f'the card polled {len(hits) - settled} times with the panel hidden'

    state['tasks'][0]['progress'] = 'phase two'
    page.evaluate("""() => {
      document.querySelector('#runview').hidden = false;
      document.dispatchEvent(new CustomEvent('dashboard:tab', {detail: {id: 'runview'}}));
    }""")
    deadline = time.monotonic() + 2
    while len(hits) == settled and time.monotonic() < deadline:
        page.wait_for_timeout(25)
    assert len(hits) > settled, 'the card did not read immediately on return'
    expect(tasks(page)).to_contain_text('phase two')
    assert errors == [], errors
