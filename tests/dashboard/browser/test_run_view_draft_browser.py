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
    queue_stub,
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


def test_each_monitor_holds_one_thing_however_many_runs_are_picked(dashboard, live_page):
    """The frozen first frame a reader reported: an earlier series stayed on the canvas under the newer one.

    NGL keeps one component list per stage, so "one thing on the canvas" is a claim about `compList.length` after a
    second pick -- which is exactly how it was reported, as a snapshot that stayed put while the play button ran.
    """
    seed(dashboard)
    plant_trajectory_run(dashboard, cg_files())
    published_series(dashboard)
    page, errors = live_page
    open_draft(page, live_page)

    choose_run(page, 'A', TRAJECTORY_RUN)
    page.wait_for_function(
        "() => (document.querySelector('.monitor[data-side=A]').runViewStage?.compList?.length || 0) > 0",
        timeout=20000)
    choose_run(page, 'B', TRAJECTORY_RUN)
    page.wait_for_function(
        "() => document.querySelector('#label-B').textContent.includes('frame series')", timeout=20000)

    counts = page.evaluate("""() => ['A', 'B'].map(side =>
        document.querySelector(`.monitor[data-side=${side}]`).runViewStage.compList.length)""")
    assert counts == [1, 1], f'a monitor is holding more than one thing: {counts}'
    assert errors == []


def test_the_figure_list_shows_each_published_figure_once(dashboard, live_page):
    """Two attempts of one analysis are one picture, not two rows with the same name.

    The defect read as "CG-first.svg repeated six times": an analysis publishes its figures again every time it runs,
    and a listing that takes every artifact (or expands each artifact's own file list) multiplies them again.
    """
    import os

    seed(dashboard)
    plant_trajectory_run(dashboard, cg_files())
    run = dashboard.coordinator.RUNS / TRAJECTORY_RUN
    for signature, epoch in (('aaaa', 1_700_000_000), ('bbbb', 1_700_100_000)):
        directory = run / f'analyses/snapshots/{signature}/1111/output/2222/snapshots'
        directory.mkdir(parents=True, exist_ok=True)
        for name in ('CG-first.svg', 'CG-middle.svg', 'CG-last.svg'):
            (directory / name).write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
            os.utime(directory / name, (epoch, epoch))
    (run / 'stages/5_assessment').mkdir(parents=True, exist_ok=True)
    (run / 'stages/5_assessment/score_matrix_LIG1.png').write_bytes(b'png')

    page, errors = live_page
    open_draft(page, live_page)
    choose_run(page, 'A', TRAJECTORY_RUN)
    page.wait_for_function(
        "() => /\\(4\\)/.test(document.querySelector('#figures-A summary').textContent)", timeout=20000)

    page.locator('#figures-A').evaluate('el => { el.open = true; }')
    names = page.locator('#figures-A .body tbody tr td:first-child code').all_inner_texts()
    assert names == ['CG-first.svg', 'CG-last.svg', 'CG-middle.svg', 'score_matrix_LIG1.png'], names
    assert len(names) == len(set(names)), f'the same figure is listed twice: {names}'
    assert page.locator('#figures-A .body').inner_text().count('superseded') == 1, \
        'the set that was replaced is counted rather than dropped in silence'
    assert errors == []


def test_the_frames_panel_regenerates_at_the_cadence_and_the_fit_it_is_given(dashboard, live_page):
    """The control the reader asked for: a cadence of their own, and a fit on the whole molecule.

    The payload is asserted rather than the picture, because this is the part a draft can get wrong with nothing to
    show for it: `interval_ns` is the frame rate, `align` is the fit on every bead, and an empty body would mean
    the producer's own default spread.
    """
    import json as jsonlib

    seed(dashboard)
    plant_trajectory_run(dashboard, cg_files())
    published_series(dashboard)
    page, errors = live_page
    open_draft(page, live_page)
    choose_run(page, 'A', TRAJECTORY_RUN)
    page.wait_for_function(
        "() => /\\(12\\)/.test(document.querySelector('#frames-A summary').textContent)", timeout=20000)

    page.locator('#frames-A').evaluate('el => { el.open = true; }')
    assert page.locator('#gen-A').inner_text().strip() == 'Regenerate trajectory', \
        'a published series is replaced, and the button says which act this is'
    page.locator('#cad-A').fill('3')
    page.locator('#fit-A').check()

    sent = []
    queue_stub(page, sent)
    page.locator('#gen-A').click()
    page.wait_for_function("() => document.querySelector('#gennote-A').textContent.includes('Sampling')")

    assert len(sent) == 1, f'the control sent {len(sent)} requests'
    assert sent[0].method == 'POST' and sent[0].url.endswith(f'/api/jobs/{TRAJECTORY_RUN}/snapshots')
    assert jsonlib.loads(sent[0].post_data) == {'interval_ns': 3, 'align': True}, sent[0].post_data
    assert errors == []
