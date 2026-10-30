"""The Run view's trajectory block: a published frames series plays on the canvas, and a build with chosen
arguments replaces it.

The block is engine code mounted in every workspace, so the core assertions run in two: the engine's own run type
read in the validation workspace, and a feature's run type read in the protein-detergent one. Everything else here is
one monitor's own state -- which attempt it shows, what it sends, and what it refuses to download.

The laziness is the point of half of these tests. A series is roughly 0.9 MB a model for an 11,708-atom system, so the
PDB is fetched when the reader presses Play and never on mount; `frames.json` is small and is what the summary and the
time readout are read from. The requests are recorded rather than assumed, and the assertions are on them.

Every run, file and answer is built by this test in its own workspace. `/trajectory`, `/analyses` and the two
artifacts are stubbed because the frame-series analysis is a server behaviour with its own tests; what is under test
here is what the panel asks for and what it does with the answer.
"""
import json
import re

import pytest
from playwright.sync_api import expect

from tests.harness import browser

#: One run of the engine's own type (read in the validation workspace) and one of the feature's (protein-detergent):
#: the block is shared code, and both are driven through it.
ENGINE_RUN = 'ef0000ef0001'
COMPLEX_RUN = 'fc0000fc0002'
RUN_TYPES = {ENGINE_RUN: 'aa_cg', COMPLEX_RUN: 'pdc'}
#: The structure each run holds under its own stage tree, so the canvas has a picture for the block to hide.
STRUCTURES = {ENGINE_RUN: 'stages/2_mapping/mapped.gro', COMPLEX_RUN: 'stages/1_system/system.gro'}
WORKSPACES = {ENGINE_RUN: 'detergent-validation', COMPLEX_RUN: 'protein-detergent'}

#: The two playable trajectories of the answer: an earlier system and the run's latest. The third segment is a copy of
#: the second's trajectory, which is why the block must not offer it twice.
EARLIER = 'stages/02_minimisation/prod/run.xtc'
LATEST = 'stages/04_nvt/prod/run.xtc'

BEADS = ('B01', 'B02', 'B03', 'B04', 'B05', 'B06', 'B07', 'B08')
#: The run's own mapping: eight beads, their export names, their size classes and the fragments they make up. The
#: fragments are what the fit's `beads` option and its fragment select are built from.
MODEL_JSON = {'name': 'fixture mapping', 'status': 'candidate-unvalidated', 'beads': [
    {'name': f'S{index}', 'export_name': name, 'size': 'S' if name in BEADS[:3] or name in BEADS[4:7] else 'T',
     'letter': 'A' if name in BEADS[:3] else 'B'}
    for index, name in enumerate(BEADS, 1)]}
MAPPED_NM = ((1.069, 1.486, 0.935), (1.226, 1.382, 1.177), (1.034, 1.180, 1.111), (1.109, 1.349, 1.074),
             (1.369, 1.334, 1.403), (1.436, 1.083, 1.494), (1.151, 1.058, 1.521), (1.318, 1.158, 1.473))


def mapped_gro():
    """The run's own mapped model: eight beads, coordinates only -- a `.gro` carries no bond records."""
    rows = ['Written by MDAnalysis', '    8']
    for index, (name, xyz) in enumerate(zip(BEADS, MAPPED_NM), 1):
        rows.append(f'{1:5d}{"LIG1":<5}{name:>5}{index:5d}' + ''.join(f'{value:8.3f}' for value in xyz))
    rows.append('   2.48092   2.48092   2.48092')
    return '\n'.join(rows) + '\n'


def series_pdb(models=3):
    """A multi-model PDB with one `CONECT` record per model: the shape `structures.series_pdb` writes.

    The parser that reads it is the one this build has: a file without `MODEL` records is one frame, and a file
    without `CONECT` would be drawn by a distance guess over three atoms.
    """
    lines = []
    for model in range(1, models + 1):
        lines.append(f'MODEL     {model:4d}')
        for index, (x, y, z) in enumerate(MAPPED_NM[:3], 1):
            lines.append(f'ATOM  {index:5d} {BEADS[index - 1]:>4} LIG A   1    '
                         + ''.join(f'{value + 0.05 * model:8.3f}' for value in (x, y, z))
                         + '  1.00  0.00           C')
        lines.append('CONECT    1    2')
        lines.append('ENDMDL')
    return '\n'.join(lines + ['END']) + '\n'


def segments_answer(run_id):
    """What `/api/jobs/<id>/trajectory` answers: two playable systems and a copy of the latest one."""
    structure = STRUCTURES[run_id]
    return {'id': run_id, 'run_type': RUN_TYPES[run_id], 'why': None, 'boundaries': [], 'segments': [
        {'name': 'Minimisation', 'structure': structure, 'trajectory': EARLIER, 'atoms': 8, 'group': 1,
         'identity': 'earlier-copy'},
        {'name': 'CG extension MD', 'structure': structure, 'trajectory': LATEST, 'atoms': 8, 'group': 2,
         'identity': 'latest-copy'},
        {'name': 'Final assessment', 'structure': structure, 'trajectory': LATEST, 'atoms': 8,
         'duplicate_of': 'CG extension MD'},
    ]}


def default_arguments(run_id):
    """The arguments the block must default to for the run's latest system: `beads` for a coarse trajectory."""
    return {'trajectory': LATEST, 'structure': STRUCTURES[run_id], 'start_ns': None, 'end_ns': None, 'stride': None,
            'fit': 'none', 'fragment': None, 'atoms': 'beads', 'assembled': False}


def series_task(run_id, args, attempt='a1', *, status='completed'):
    """One `frame-series` attempt as `/analyses` reports it, with the two files a completed one published."""
    directory = f'analyses/frame-series/signature-{attempt}/{attempt}'
    task = {'id': f'task-{attempt}', 'kind': 'frame-series', 'signature': f'signature-{attempt}',
            'payload': args, 'status': status, 'created_at': '2026-10-20T10:00:00+00:00', 'directory': directory}
    return finish(task) if status == 'completed' else task


def finish(task):
    """A settled attempt's outputs, at the one place the worker writes them."""
    task['status'] = 'completed'
    task['outputs'] = [f"{task['directory']}/outputs/run-frames.pdb", f"{task['directory']}/outputs/frames.json"]
    return task


def frames_json(run_id, *, identity='latest-copy', times=(0.0, 0.5, 1.0), size=2_400_000):
    """`frames.json` as the producer writes it: the times, the counts and the identities a stale check compares."""
    return {'args': {}, 'models': len(times), 'atoms': 3, 'times_ns': list(times),
            'indices': [index * 50 for index in range(len(times))], 'trajectory': LATEST,
            'structure': STRUCTURES[run_id], 'trajectory_identity': identity,
            'structure_identity': 'structure-copy', 'cadence_ns': 0.5, 'fit': 'none', 'assembled': False,
            'bytes': size}


def attempt_of(url):
    """The attempt a stubbed artifact URL names: the one path segment that is `a1`/`a2`."""
    found = re.search(r'/artifacts/(?:.*/)?(a\d+)/', url)
    return found.group(1) if found else 'a1'


def run_record(run_id, label):
    return {'id': run_id, 'run_type': RUN_TYPES[run_id], 'label': label, 'molecule_name': label.split()[0],
            'detergent': 'DDM', 'method': 'fast_forward', 'status': 'completed', 'stage': 'complete',
            'created': '2026-10-20T10:00:00+00:00'}


def seed(dashboard):
    """The two runs, built here -- nothing reads the developer's workspace."""
    owner = dashboard.coordinator
    for run_id, label in ((ENGINE_RUN, 'Maltose CG trajectory'), (COMPLEX_RUN, 'Complex trajectory')):
        owner.database().insert(run_record(run_id, label))
        for path, text in ((STRUCTURES[run_id], mapped_gro()),
                           ('stages/2_mapping/model.json', json.dumps(MODEL_JSON, indent=2))):
            target = owner.RUNS / run_id / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)


def answer_analyses(route, state):
    """One `/analyses` read. The promotion is what a real worker does between two polls, done deterministically."""
    if state['promote'] and not state['hold']:
        for task in state['tasks']:
            if task['status'] in ('queued', 'running'):
                finish(task)
        state['promote'] = False
    route.fulfill(json=state['tasks'])


def answer_post(route, state):
    """A build accepted: the attempt joins the run's list as `queued`, and the next read settles it."""
    body = route.request.post_data_json
    state['posted'].append(body)
    task = series_task(state['run_id'], body, 'a2', status='queued')
    state['tasks'].append(task)
    state['promote'] = True
    route.fulfill(status=202, json=task)


def install(page, state):
    """Every answer the block reads, from the one record this test owns."""
    run_id = state['run_id']

    def frame_file(route):
        route.fulfill(content_type='application/json', body=json.dumps(state['frames'][attempt_of(route.request.url)]))

    page.route(re.compile(rf'/api/jobs/{run_id}/trajectory$'), lambda route: route.fulfill(json=state['answer']))
    page.route(re.compile(rf'/api/jobs/{run_id}/analyses$'), lambda route: answer_analyses(route, state))
    page.route(re.compile(rf'/api/jobs/{run_id}/frame-series$'), lambda route: answer_post(route, state))
    page.route(re.compile(rf'/api/jobs/{run_id}/artifacts/.*/frames\.json'), frame_file)
    page.route(re.compile(rf'/api/jobs/{run_id}/artifacts/.*/run-frames\.pdb'),
               lambda route: route.fulfill(content_type='text/plain', body=state['pdb']))
    page.route(re.compile(rf'/api/jobs/{run_id}/artifacts/.*/console\.log'),
               lambda route: route.fulfill(content_type='text/plain', body=state['log']))


def open_panel(page, live_page, workspace, run_id):
    def ready(page):
        expect(page.locator('#runview')).to_be_visible()
        page.locator('#run-view-segments-details-A').evaluate('el => { el.open = true; }')

    return browser.open_panel(page, live_page.base_url, f'/{workspace}/run-view?run={run_id}', ready=ready)


def open_run(dashboard, live_page, run_id, *, identity='latest-copy', tasks=None, why=None, log='', hold=False):
    """The run, its stubbed answers and the record of what the block asked for."""
    seed(dashboard)
    page, errors = live_page
    # The build poll is the one thing this panel would otherwise wait two seconds for; the seam is the same one
    # `bonded-parameterization.js` carries for its own poll.
    page.add_init_script('window.__runViewPollMs = 25')
    answer = segments_answer(run_id)
    if why is not None:
        answer = {'id': run_id, 'run_type': RUN_TYPES[run_id], 'why': why, 'segments': []}
    state = {
        'run_id': run_id, 'answer': answer,
        'tasks': list(tasks) if tasks is not None else [series_task(run_id, default_arguments(run_id))],
        'requests': [], 'posted': [], 'promote': False, 'hold': hold, 'log': log,
        'frames': {'a1': frames_json(run_id, identity=identity),
                   'a2': frames_json(run_id, identity=identity, times=(0.0, 1.0, 2.0, 3.0, 4.0), size=3_100_000)},
        'pdb': series_pdb(),
    }
    page.on('request', lambda request: state['requests'].append(request.url))
    install(page, state)
    open_panel(page, live_page, WORKSPACES[run_id], run_id)
    return page, errors, state


def series(page):
    return page.locator('#run-view-series-A')


def time_line(page):
    return page.locator('#run-view-time-A')


def measured(page):
    """What the viewer holds: the structure component, the series component and the frame on screen.

    Read back off the stage rather than off the panel's own fields, the way the rest of this tier measures a picture:
    a component hidden by the block and a component removed by it look the same in any state the panel reports.
    """
    return page.locator('#run-view-viewer-A').evaluate("""el => {
      const stage = el.runViewStage;
      const components = stage ? stage.compList : [];
      const series = components.find(component => component.trajList && component.trajList.length);
      return {
        count: components.length,
        structure: components[0] ? {
          atoms: components[0].structure.atomCount,
          visible: components[0].parameters.visible,
        } : null,
        frames: series ? series.trajList[0].trajectory.frameCount : 0,
        frame: series ? series.trajList[0].trajectory.currentFrame : null,
      };
    }""")


# ----------------------------------------------------------------------------------------------------------- mount


def test_mount_shows_the_published_series_and_downloads_no_frames(dashboard, live_page):
    """A matching build is summarised from `frames.json`; the PDB -- the large half -- is not fetched on mount."""
    page, errors, state = open_run(dashboard, live_page, ENGINE_RUN)

    expect(series(page)).to_contain_text('CG extension MD')
    expect(series(page)).to_contain_text('3 models')
    expect(page.locator('#run-view-play-A')).to_be_enabled()
    assert any(url.endswith('/frames.json?inline=1') for url in state['requests']), \
        'the summary is read from frames.json, which is small'
    assert not any('run-frames.pdb' in url for url in state['requests']), \
        'the frames series was downloaded on mount; it is fetched on Play'
    # The run's latest system is the default: the last playable entry, and not the copy of its trajectory.
    expect(page.locator('#run-view-segment-A option')).to_have_count(2)
    expect(page.locator('#run-view-segment-A')).to_have_value('1')
    assert errors == [], errors


def test_a_run_with_nothing_to_play_prints_the_endpoints_own_why(dashboard, live_page):
    """The endpoint's sentence is the panel's sentence: a run with no trajectory is a state, not an empty control."""
    page, errors, state = open_run(dashboard, live_page, ENGINE_RUN, why='this run offers no trajectory to play')

    expect(page.locator('#run-view-trajectory-note-A')).to_contain_text('offers no trajectory to play')
    expect(page.locator('#run-view-play-A')).to_be_disabled()
    expect(page.locator('#run-view-segment-A')).to_be_disabled()
    assert errors == [], errors


# ---------------------------------------------------------------------------------------------------------- playback


def test_play_advances_the_model_and_the_time_then_pause_stops_it(dashboard, live_page):
    """Frame, model index and `t` all move together, off the times `frames.json` states."""
    page, errors, state = open_run(dashboard, live_page, ENGINE_RUN)
    expect(series(page)).to_contain_text('3 models')

    page.locator('#run-view-loop-A').check()
    page.locator('#run-view-play-A').click()
    expect(page.locator('#run-view-play-A')).to_have_text('Pause')
    page.wait_for_function(
        "() => document.querySelector('#run-view-time-A').textContent.includes('model 2/3')", timeout=30000)
    expect(time_line(page)).to_contain_text('t = 0.5 ns')

    drawn = measured(page)
    assert drawn['count'] == 2, 'the series is a component of its own beside the structure'
    assert drawn['frames'] == 3, drawn
    assert drawn['structure']['atoms'] == 8, 'the structure component is kept, not replaced'
    assert drawn['structure']['visible'] is False, 'the structure is still drawn over the series'

    page.locator('#run-view-play-A').click()
    expect(page.locator('#run-view-play-A')).to_have_text('Play')
    stopped = time_line(page).inner_text()
    stopped_frame = measured(page)['frame']
    page.wait_for_timeout(400)
    assert time_line(page).inner_text() == stopped, f'playback kept running after Pause: {stopped}'
    assert measured(page)['frame'] == stopped_frame, 'the frame moved while the block said it was paused'

    # The slider is a control, not a readout: the keyboard moves it to the first frame and one further.
    page.locator('#run-view-frame-A').focus()
    page.keyboard.press('Home')
    expect(time_line(page)).to_contain_text('model 1/3')
    page.keyboard.press('ArrowRight')
    expect(time_line(page)).to_contain_text('model 2/3')
    expect(time_line(page)).to_contain_text('t = 0.5 ns')
    page.locator('#run-view-step-back-A').click()
    expect(time_line(page)).to_contain_text('model 1/3')
    page.locator('#run-view-step-forward-A').click()
    expect(time_line(page)).to_contain_text('model 2/3')
    assert errors == [], errors


# -------------------------------------------------------------------------------------------------------- the build


def test_submit_sends_the_nine_key_body_for_the_chosen_controls(dashboard, live_page):
    """The form's values, exactly: the server validates this body, so a key in the wrong place is a refusal."""
    page, errors, state = open_run(dashboard, live_page, ENGINE_RUN)
    expect(series(page)).to_contain_text('3 models')

    page.locator('#run-view-build-A').click()
    page.wait_for_function(
        """() => [...document.querySelectorAll('#run-view-form-fit-A option')].some(option => option.value === 'beads')""",
        timeout=30000)
    expect(page.locator('#run-view-form-fragment-A option').first).to_contain_text('A — B01, B02, B03')

    page.locator('#run-view-form-atoms-A').select_option('ca')
    page.locator('#run-view-form-fit-A').select_option('beads')
    page.locator('#run-view-form-fragment-A').select_option('B')
    page.locator('#run-view-form-start-A').fill('1.5')
    page.locator('#run-view-form-end-A').fill('12')
    page.locator('#run-view-form-stride-A').fill('10')
    page.locator('#run-view-form-assembled-A').check()
    page.locator('#run-view-submit-A').click()

    expect(series(page)).to_contain_text('CA atoms only')
    expect(series(page)).to_contain_text('aligned on fragment B')
    expect(series(page)).to_contain_text('every 10th frame')
    assert state['posted'] == [{'trajectory': LATEST, 'structure': STRUCTURES[ENGINE_RUN], 'start_ns': 1.5,
                                'end_ns': 12, 'stride': 10, 'fit': 'beads', 'fragment': 'B', 'atoms': 'ca',
                                'assembled': True}], state['posted']
    assert errors == [], errors


def test_a_completed_build_swaps_the_series_and_the_first_attempt_stays(dashboard, live_page):
    """A new attempt is fetched and shown; changing the arguments back shows the first one again, still there."""
    page, errors, state = open_run(dashboard, live_page, ENGINE_RUN)
    expect(series(page)).to_contain_text('3 models')

    page.locator('#run-view-build-A').click()
    page.locator('#run-view-form-atoms-A').select_option('ca')
    page.locator('#run-view-submit-A').click()

    expect(series(page)).to_contain_text('5 models')
    expect(series(page)).to_contain_text('CA atoms only')
    assert any('/a2/outputs/frames.json?inline=1' in url for url in state['requests']), \
        'the new attempt\'s own frames.json is what was read'
    assert not any('run-frames.pdb' in url for url in state['requests']), \
        'the new series was downloaded before Play was pressed'

    # The first attempt is still in the answer, and the form still finds it.
    page.locator('#run-view-form-atoms-A').select_option('beads')
    expect(series(page)).to_contain_text('3 models')
    expect(series(page)).to_contain_text('beads only')
    assert [task['status'] for task in state['tasks']] == ['completed', 'completed'], state['tasks']
    assert errors == [], errors


def test_a_build_still_in_flight_waits_instead_of_queuing_a_second(dashboard, live_page):
    """A matching attempt that is queued or running disables Play and the submit: the button waits for it."""
    queued = series_task(ENGINE_RUN, default_arguments(ENGINE_RUN), 'a1', status='queued')
    page, errors, state = open_run(dashboard, live_page, ENGINE_RUN, tasks=[queued], hold=True)

    expect(page.locator('#run-view-trajectory-note-A')).to_contain_text('Building frames from CG extension MD')
    expect(page.locator('#run-view-play-A')).to_be_disabled()
    page.locator('#run-view-build-A').click()
    expect(page.locator('#run-view-submit-A')).to_be_disabled()
    expect(page.locator('#run-view-form-note-A')).to_contain_text('queued')
    assert not state['posted'], 'a second attempt was queued for a build the run is already running'
    assert errors == [], errors


def test_the_block_fits_a_narrow_window(dashboard, live_page):
    """The block is one column of a two-monitor grid, and the form adds seven controls to it: none may widen the page."""
    page, errors, state = open_run(dashboard, live_page, ENGINE_RUN)
    page.set_viewport_size({'width': 390, 'height': 900})
    page.locator('#run-view-build-A').click()
    expect(page.locator('#run-view-form-atoms-A')).to_be_visible()
    browser.assert_no_horizontal_scroll(page)
    assert errors == [], errors


# ------------------------------------------------------------------------------------------------- failure states


def test_a_series_older_than_the_trajectory_says_so_and_offers_recompute(dashboard, live_page):
    """A built series whose trajectory digest is not the segment's is played, but it is named as an old copy."""
    page, errors, state = open_run(dashboard, live_page, ENGINE_RUN, identity='older-copy')

    expect(series(page)).to_contain_text('older copy of the segment')
    expect(page.locator('#run-view-trajectory-note-A')).to_contain_text('Recompute frames')
    expect(page.locator('#run-view-build-A')).to_be_enabled()
    assert errors == [], errors


def test_a_failed_attempt_shows_its_error_and_the_end_of_its_log(dashboard, live_page):
    """A failed build is the reader's answer: the attempt's error, then the last lines of its own console."""
    failed = series_task(ENGINE_RUN, default_arguments(ENGINE_RUN), 'a1', status='failed')
    failed['error'] = 'the trajectory could not be read'
    log = '\n'.join(['reading the structure', 'reading the trajectory',
                     'the trajectory could not be read: no such file'])
    page, errors, state = open_run(dashboard, live_page, ENGINE_RUN, tasks=[failed], log=log)

    expect(page.locator('#run-view-trajectory-note-A')).to_contain_text('the trajectory could not be read')
    expect(page.locator('#run-view-trajectory-note-A')).to_contain_text('no such file')
    expect(page.locator('#run-view-play-A')).to_be_disabled()
    assert errors == [], errors


# ------------------------------------------------------------------------------------------------- both workspaces


@pytest.mark.parametrize('run_id', [ENGINE_RUN, COMPLEX_RUN], ids=['engine-run-type', 'feature-run-type'])
def test_the_block_plays_and_builds_in_both_workspaces(dashboard, live_page, run_id):
    """The panel is shared code: the same controls, on the engine's own run type and on a feature's."""
    page, errors, state = open_run(dashboard, live_page, run_id)
    expect(series(page)).to_contain_text('CG extension MD')

    page.locator('#run-view-loop-A').check()
    page.locator('#run-view-play-A').click()
    page.wait_for_function(
        "() => document.querySelector('#run-view-time-A').textContent.includes('model 2/3')", timeout=30000)
    page.locator('#run-view-play-A').click()
    expect(page.locator('#run-view-play-A')).to_have_text('Play')
    assert measured(page)['frames'] == 3

    page.locator('#run-view-build-A').click()
    page.locator('#run-view-form-atoms-A').select_option('all')
    page.locator('#run-view-submit-A').click()
    expect(series(page)).to_contain_text('5 models')
    expect(series(page)).to_contain_text('all atoms (water left out)')
    assert state['posted'][-1] == {'trajectory': LATEST, 'structure': STRUCTURES[run_id], 'start_ns': None,
                                   'end_ns': None, 'stride': None, 'fit': 'none', 'fragment': None, 'atoms': 'all',
                                   'assembled': False}, state['posted']
    assert errors == [], errors


