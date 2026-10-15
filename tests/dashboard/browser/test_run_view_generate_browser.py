"""The generate control: the one thing the transport row can do when it has no frames to play.

The row plays what the `snapshots` analysis published, and a run that has never run it has nothing -- so the control
that queues that analysis sits at the end of the row, on the right of the slider. Four things are held here, every
one of them read back off the page or off the file the panel wrote:

1. Where the run holds a trajectory and has published no series, the control is offered, enabled, and its title names
   the analysis it would run and the file it would sample.
2. Where the run wrote no trajectory, it is drawn disabled with its reason -- the convention the transport itself
   follows (a hidden control teaches nothing).
3. Clicking it sends exactly one `POST /api/jobs/<run>/snapshots`. The analysis is *stubbed*, never queued against a
   live coordinator: a control that writes is not clicked to see what it does, and the assertion is the request the
   client sent.
4. When the stubbed task reports `completed` and the attempt's record is on disk, the panel re-reads the run and the
   row plays the published series -- the whole loop, with the frame count read off the viewer's own trajectory.

The stubbed task list is also what proves the panel does not *assume* a completion: the note follows the record's
status, and a task that reports `failed` names the failure instead of spinning.
"""
import json

from playwright.sync_api import expect

from tests.dashboard.browser.test_run_view_browser import (
    CG_RUN,
    FRAMES_RUN,
    MEASURE,
    MODEL_JSON,
    bead_pdb,
    frames_pdb,
    job,
    json_text,
    mapped_gro,
    moleculetype,
    open_panel,
    plant,
    published_snapshots,
    seed,
    wait_for_component,
)

#: A coarse-grained run that holds a trajectory and has published no frames -- the state the control exists for. It is
#: planted by this file rather than added to the shared seed, whose run counts several tests assert.
TRAJECTORY_RUN = 'ab00ab000008'
#: The run's own coarse-grained trajectory, where the `snapshots` kind reads it from.
TRAJECTORY = 'stages/4_CG_sim/md.xtc'


def cg_files(trajectory=True):
    """The shape a CG run has, plus its own trajectory: what the control's first question is asked about.

    The trajectory's bytes do not matter here. The panel asks whether the run holds one and the analysis that would
    parse it is stubbed, so a placeholder is honest -- and a fixture that carried a real `.xtc` would be a second
    copy of what the analysis's own tests already hold.
    """
    files = {'stages/2_mapping/mapped.gro': mapped_gro(),
             'stages/2_mapping/model.json': json_text(MODEL_JSON),
             'stages/3_initial_CG/LIG1.itp': moleculetype(),
             'stages/3_initial_CG/LIG1.pdb': bead_pdb(),
             'stages/4_CG_sim/md.gro': mapped_gro()}
    if trajectory:
        files[TRAJECTORY] = 'a trajectory this test never parses\n'
    return files


def plant_trajectory_run(dashboard, files):
    plant(dashboard, TRAJECTORY_RUN,
          job(TRAJECTORY_RUN, 'aa_cg', 'Mannitol CG, a trajectory and no frames', '2026-10-06T10:00:00+00:00'), files)


def queue_stub(page, sent, status='queued'):
    """Answer the queue route without reaching the coordinator, recording what the client asked for."""
    def handler(route, request):
        sent.append(request)
        route.fulfill(status=202, content_type='application/json',
                      body=json_text({'id': 'snap-fixture', 'kind': 'snapshots', 'status': status,
                                      'directory': 'analyses/snapshots/1a2b3c4d/5e6f7a8b'}))
    page.route('**/api/jobs/*/snapshots', handler)


def tasks_stub(page, status):
    """Answer the task list the way the record would, so the poll reads a status rather than guessing one."""
    page.route('**/api/jobs/*/analyses',
               lambda route, request: route.fulfill(
                   status=200, content_type='application/json',
                   body=json_text([{'id': 'snap-fixture', 'kind': 'snapshots', 'status': status,
                                    'directory': 'analyses/snapshots/1a2b3c4d/5e6f7a8b'}])))


def published_the_series(dashboard):
    """Write the attempt a completed `snapshots` analysis would have left, after the click rather than before it."""
    for path, text in published_snapshots({'CG-frames.pdb': frames_pdb(), 'CG-first.pdb': bead_pdb(),
                                           'CG-middle.pdb': bead_pdb(), 'CG-last.pdb': bead_pdb()}).items():
        target = dashboard.coordinator.RUNS / TRAJECTORY_RUN / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)


def test_the_control_is_offered_where_a_trajectory_can_be_sampled(dashboard, live_page):
    """1 and 3: offered with its own explanation, and one POST when it is pressed -- and not a live one."""
    seed(dashboard)
    plant_trajectory_run(dashboard, cg_files())
    page, errors = live_page
    open_panel(page, live_page, run=TRAJECTORY_RUN)
    wait_for_component(page, atoms=8)

    control = page.locator('#run-view-generate')
    expect(control).to_be_visible()
    expect(control).to_be_enabled()
    title = control.get_attribute('title') or ''
    assert 'snapshots analysis' in title, f'the control does not name what it would run: {title!r}'
    assert control.inner_text().strip() == 'Generate trajectory'

    sent = []
    queue_stub(page, sent)
    control.click()
    page.wait_for_function(
        "() => document.querySelector('#run-view-generate-note').textContent.includes('Sampling')")
    assert len(sent) == 1, f'the control sent {len(sent)} requests'
    assert sent[0].method == 'POST', sent[0].method
    assert sent[0].url.endswith(f'/api/jobs/{TRAJECTORY_RUN}/snapshots'), sent[0].url
    assert json.loads(sent[0].post_data or '{}') == {}, sent[0].post_data
    expect(control).to_be_disabled()
    assert errors == []


def test_the_control_is_disabled_with_its_reason_where_the_run_wrote_no_trajectory(dashboard, live_page):
    """2: the shared CG fixture holds no `.xtc`, so the control is drawn and says why it cannot be used."""
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page, run=CG_RUN)
    wait_for_component(page, atoms=8)

    control = page.locator('#run-view-generate')
    expect(control).to_be_visible()
    expect(control).to_be_disabled()
    assert 'no trajectory' in (control.get_attribute('title') or '').lower()
    expect(page.locator('#run-view-generate-note')).to_contain_text('nothing to sample')
    assert errors == []


def test_the_control_is_hidden_where_the_run_already_published_a_series(dashboard, live_page):
    """The row's job where a series exists is to play it; a control offering to build a second one is noise."""
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page, run=FRAMES_RUN)
    wait_for_component(page, atoms=8)

    expect(page.locator('#run-view-generate')).to_be_hidden()
    assert errors == []


def test_the_row_plays_the_series_once_the_queued_analysis_completes(dashboard, live_page):
    """4: the whole loop -- queue, wait, read the record back, re-read the run, play the frames it published."""
    seed(dashboard)
    plant_trajectory_run(dashboard, cg_files())
    page, errors = live_page
    open_panel(page, live_page, run=TRAJECTORY_RUN)
    wait_for_component(page, atoms=8)

    sent = []
    queue_stub(page, sent)
    tasks_stub(page, 'completed')
    page.locator('#run-view-generate').click()
    published_the_series(dashboard)

    # The poll asks every `GENERATE_POLL_MS`, so the wait is the panel's own cadence rather than a fixed sleep.
    page.wait_for_function(
        "() => document.querySelector('#run-view-viewer')?.runViewStage?.compList?.[0]?.trajList?.length > 0",
        timeout=30000)
    measured = page.locator('#run-view-viewer').evaluate(MEASURE)
    assert measured['frames'] == 5, f'the row plays {measured["frames"]} frames of the published series'
    assert measured['models'] == 5, 'and the series the panel drew carries the five models the record names'
    expect(page.locator('#run-view-generate')).to_be_hidden()
    assert len(sent) == 1
    assert errors == []


def test_a_failed_analysis_is_named_rather_than_left_spinning(dashboard, live_page):
    """The record's status is what the note follows: a failure is reported, and the control becomes usable again."""
    seed(dashboard)
    plant_trajectory_run(dashboard, cg_files())
    page, errors = live_page
    open_panel(page, live_page, run=TRAJECTORY_RUN)
    wait_for_component(page, atoms=8)

    sent = []
    queue_stub(page, sent)
    page.route('**/api/jobs/*/analyses',
               lambda route, request: route.fulfill(
                   status=200, content_type='application/json',
                   body=json_text([{'id': 'snap-fixture', 'kind': 'snapshots', 'status': 'failed',
                                    'error': 'no trajectory to sample'}])))
    page.locator('#run-view-generate').click()
    page.wait_for_function(
        "() => document.querySelector('#run-view-generate-note').textContent.includes('failed')", timeout=30000)

    expect(page.locator('#run-view-generate-note')).to_contain_text('no trajectory to sample')
    expect(page.locator('#run-view-generate')).to_be_enabled()
    assert errors == []
