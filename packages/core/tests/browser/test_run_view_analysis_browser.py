"""The Run view's Analysis card: a run's own figures, the controls that queue them, and its task lines.

The card moved here from the Runs page's **Analysis graphs** panel, so what this file pins is the move rather than the
viewer's mechanics: a monitor draws *its own* run's figures, a second monitor draws its own, a run with none says so
instead of showing an empty box, and the three queue buttons post the routes the Runs card used to post. The figure
viewer's zoom and tabs are the same component, exercised through this card.

Every run, figure and answer is built by this test in its own workspace; the analyses and figures routes are stubbed
where the test is about what the card asks for, and real where it is about what it draws.
"""
import re

from playwright.sync_api import expect

A_RUN = 'abcdef123456'
B_RUN = 'abcdef123457'
WORKSPACE = 'detergent-validation'

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="400" height="200">'
       '<circle cx="200" cy="100" r="90" fill="blue"/></svg>')


def seed(dashboard):
    """Two completed CG runs, each with its own figures, and no analysis tasks behind them."""
    owner = dashboard.coordinator
    rows = {A_RUN: ('alpha', 'beta'), B_RUN: ('gamma',)}
    for run_id, names in rows.items():
        owner.database().insert({'id': run_id, 'run_type': 'aa_cg', 'label': f'Figure run {run_id[-1]}',
                                 'detergent': 'DDM', 'method': 'fast_forward', 'status': 'completed',
                                 'stage': 'complete', 'created': owner.now(), 'analyses': []})
        directory = owner.RUNS / run_id
        directory.mkdir(parents=True, exist_ok=True)
        for name in names:
            (directory / f'{name}.svg').write_text(SVG)
    (owner.RUNS / A_RUN / 'surface-comparison.html').write_text(
        '<!doctype html><title>Surface comparison</title><h1>Interactive figure</h1>')


def plots(page, side='A'):
    return page.locator(f'#run-view-analysis-plots-{side}')


def note(page, side='A'):
    return page.locator(f'#run-view-analysis-note-{side}')


def open_view(page, live_page, run_id=A_RUN, figures=3):
    """The Run view with `run_id` in monitor A; the second monitor picks the other run by itself."""
    page.goto(f'{live_page.base_url}/{WORKSPACE}/run-view?run={run_id}')
    expect(page.locator('#runview')).to_be_visible()
    expect(plots(page).locator('[role=tab]')).to_have_count(figures)
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
        {'id': A_RUN, 'run_type': 'aa_cg', 'label': 'Bare run', 'detergent': 'DDM', 'method': 'fast_forward',
         'status': 'completed', 'stage': 'complete', 'created': dashboard.coordinator.now(), 'analyses': []})
    (dashboard.coordinator.RUNS / A_RUN).mkdir(parents=True, exist_ok=True)
    page, errors = live_page

    page.goto(f'{live_page.base_url}/{WORKSPACE}/run-view?run={A_RUN}')
    expect(page.locator('#runview')).to_be_visible()

    expect(note(page)).to_contain_text('No analysis graphs yet')
    expect(plots(page).locator('.figure-empty')).to_be_visible()
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
    """The task list moved with the card: its progress, its log link and its cancel are read where the figures are."""
    seed(dashboard)
    page, errors = live_page
    cancelled = []

    state = {'tasks': [{'id': 'task-9', 'kind': 'stability', 'status': 'running',
                        'directory': 'analyses/stability/test'}]}

    def analyses(route):
        route.fulfill(json=state['tasks'])

    def cancel(route):
        cancelled.append(route.request.method)
        state['tasks'][0]['status'] = 'cancelling'
        route.fulfill(json={'id': 'task-9', 'status': 'cancelling'})

    page.route(re.compile(rf'/api/jobs/{A_RUN}/analyses$'), analyses)
    page.route(re.compile(rf'/api/jobs/{A_RUN}/analyses/task-9/cancel$'), cancel)
    open_view(page, live_page)
    card = page.locator('.run-view-analysis').first
    expect(card).to_contain_text('stability · running')
    card.get_by_role('button', name='Cancel analysis', exact=True).click()

    expect(page.locator('#run-view-analysis-tasks-A')).to_contain_text('cancelling')
    assert cancelled == ['POST'], 'the card drew a cancel that asked nothing'
    assert errors == [], errors
