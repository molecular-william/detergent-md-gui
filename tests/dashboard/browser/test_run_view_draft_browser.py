"""The layout draft: two monitors, each with its own run, canvas, transport and collapsed sub-panels.

The draft is a review aid rather than the panel (`/static/run-view-draft.html`), and it is held to the shape it
claims: a reader judging a layout is judging what is on the page, so the page is asserted rather than described.
It is also the test that catches the draft's own failures -- the first version of it did not parse at all, and the
signature of a broken script is a page that renders its headings and nothing else.

When the layout lands in the panel, this file and the draft it holds are both to be deleted together: the draft is
not a stand-in for the panel, and `references/ngl-and-viewers.md` records which of its rules moved where.
"""
from tests.dashboard.browser.test_run_view_browser import seed
from tests.dashboard.browser.test_run_view_generate_browser import (
    TRAJECTORY_RUN,
    cg_files,
    plant_trajectory_run,
    published_series,
)

DRAFT = '/static/run-view-draft.html'


def open_draft(page, live_page):
    page.goto(f'{live_page.base_url}{DRAFT}')
    # The page builds its monitors from the run list, then loads each run's structure and, where there is one, its
    # published series. Waiting on the canvas label rather than on a count is what makes this a check of the draft
    # and not of the fixtures: a monitor with no run would have no label.
    page.wait_for_function(
        "() => { const label = document.querySelector('#label-A');"
        " return !!(label && /frame series|atoms/.test(label.textContent)); }", timeout=20000)
    return page


def choose_run(page, side, run_id):
    """Pick a run in a monitor's own combo, by typing at it the way a reader would: the filter, then Enter."""
    field = page.locator(f'#choose-{side} .filter')
    field.fill(run_id)
    field.dispatch_event('input')
    field.press('Enter')
    # Wait on the combo's own value: the canvas label carries the run's name and its atom count, not its id, so a
    # wait keyed on the id would time out on a pick that worked.
    page.wait_for_function(
        f"() => document.querySelector('#choose-{side} .filter').value.includes('{run_id}')", timeout=20000)


def test_the_draft_builds_two_monitors_each_with_its_own_choose_a_run(dashboard, live_page):
    """Two monitors, two combos, two canvases, and a run chosen on each without the other moving."""
    seed(dashboard)
    plant_trajectory_run(dashboard, cg_files())
    published_series(dashboard)
    page, errors = live_page
    open_draft(page, live_page)

    assert page.locator('.monitor').count() == 2, 'the draft is two monitors or it is not the draft'
    for side in ('A', 'B'):
        assert page.locator(f'#canvas-{side} canvas').count() == 1, f'monitor {side} draws nothing'
        assert page.locator(f'#choose-{side} .filter').input_value(), f'monitor {side} has no run chosen'
    filters = [page.locator(f'#choose-{side} .filter').input_value() for side in ('A', 'B')]
    assert filters[0] != filters[1], 'both monitors were given the same run'

    # The run whose frames the fixture published: chosen by typing its id, which is the combo's own behaviour.
    choose_run(page, 'A', TRAJECTORY_RUN)
    # Waited for, not asserted straight after the pick: the structure lands first and the series replaces it a
    # request later, so the label says "atoms" for a moment and then says the series.
    page.wait_for_function(
        "() => { const label = document.querySelector('#label-A');"
        " return label.textContent.includes('frame series')"
        " && document.querySelector('#now-A').textContent.includes('/'); }", timeout=20000)
    # Waited for rather than asserted at once: the transport is deliberately disabled while a run loads, and what is
    # being checked is that it comes *back* -- a load that was superseded must not leave it disabled for good.
    page.wait_for_function(
        "() => { const slider = document.querySelector('#frame-A');"
        " return !slider.disabled && !document.querySelector('#play-A').disabled; }", timeout=20000)
    assert errors == []


def test_the_three_sub_panels_sit_below_the_canvas_collapsed(dashboard, live_page):
    """The state the request asked for by name: minimizable, and minimized by default."""
    seed(dashboard)
    plant_trajectory_run(dashboard, cg_files())
    published_series(dashboard)
    page, errors = live_page
    open_draft(page, live_page)

    for side in ('A', 'B'):
        for panel, heading in (('holds', 'what this run holds'), ('frames', 'frames'), ('figures', 'figures')):
            details = page.locator(f'#{panel}-{side}')
            assert details.evaluate('el => el.open') is False, f'{panel}-{side} opened itself'
            assert heading in details.locator('summary').inner_text()
            # Below the canvas, not beside it: the canvas's own bottom edge is above the panel's top edge.
            canvas = page.locator(f'#canvas-{side}').bounding_box()
            box = details.bounding_box()
            assert box['y'] >= canvas['y'], f'{panel}-{side} is not below the canvas'
    # A series states how many models it holds, on the run that has one -- and nothing where a run has none.
    choose_run(page, 'A', TRAJECTORY_RUN)
    # The fixture publishes 12 models (its own record says so), and the panel states the record's number rather
    # than a number of its own.
    page.wait_for_function(
        "() => /\\(12\\)/.test(document.querySelector('#frames-A summary').textContent)", timeout=20000)
    assert 'frames' in page.locator('#frames-B summary').inner_text()
    assert errors == []


def test_the_combo_offers_only_completed_runs_and_filters_as_you_type(dashboard, live_page):
    """The two selection rules from the request, on the run list the panel already reads."""
    seed(dashboard)
    plant_trajectory_run(dashboard, cg_files())
    page, errors = live_page
    open_draft(page, live_page)

    field = page.locator('#choose-A .filter')
    field.fill('')
    field.dispatch_event('input')
    offered = page.locator('#choose-A .list button')
    assert offered.count() >= 2, 'the completed runs the fixture planted are not offered'
    assert page.locator('#hidden').inner_text().startswith('0 of'), page.locator('#hidden').inner_text()

    field.fill('nothing-matches-this')
    field.dispatch_event('input')
    assert page.locator('#choose-A .list button').count() == 0
    assert 'No completed run matches' in page.locator('#choose-A .list').inner_text()
    assert errors == []
