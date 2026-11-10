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
import time

import pytest
from playwright.sync_api import expect

from tests.harness import browser

#: One run of the engine's own type (read in the validation workspace) and one of the feature's (protein-detergent):
#: the block is shared code, and both are driven through it.
ENGINE_RUN = 'ef0000ef0001'
COMPLEX_RUN = 'fc0000fc0002'
RUN_TYPES = {ENGINE_RUN: 'cg', COMPLEX_RUN: 'pdc'}
#: The structure each run holds under its own stage tree, so the canvas has a picture for the block to hide.
STRUCTURES = {ENGINE_RUN: 'stages/2_mapping/mapped.gro', COMPLEX_RUN: 'stages/1_system/system.gro'}
WORKSPACES = {ENGINE_RUN: 'detergent-validation', COMPLEX_RUN: 'protein-detergent'}

#: The two playable trajectories of the answer: an earlier system and the run's latest. The third segment is a copy of
#: the second's trajectory, which is why the block must not offer it twice.
EARLIER = 'stages/02_minimisation/prod/run.xtc'
LATEST = 'stages/04_nvt/prod/run.xtc'

BEADS = ('B01', 'B02', 'B03', 'B04', 'B05', 'B06', 'B07', 'B08')
#: The run's own mapping: eight beads, their export names, their size classes and the fragments they make up. The
#: fragments are the `fragment:<letter>` options of the group select, and the beads each one names.
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
    """A multi-model PDB with one `CONECT` block after the models: the shape `structures.series_pdb` writes.

    This viewer keeps one bond store for the whole structure -- measured: a block after the last `ENDMDL` loads the
    same two bonds between the same pairs as a block inside every model -- so the writer states them once.
    """
    lines = []
    for model in range(1, models + 1):
        lines.append(f'MODEL     {model:4d}')
        for index, (x, y, z) in enumerate(MAPPED_NM[:3], 1):
            lines.append(f'ATOM  {index:5d} {BEADS[index - 1]:>4} LIG A   1    '
                         + ''.join(f'{value + 0.05 * model:8.3f}' for value in (x, y, z))
                         + '  1.00  0.00           C')
        lines.append('ENDMDL')
    lines.append('CONECT    1    2')
    return '\n'.join(lines + ['END']) + '\n'


def segments_answer(run_id):
    """What `/api/jobs/<id>/trajectory` answers: two playable systems and a copy of the latest one."""
    structure = STRUCTURES[run_id]
    return {'id': run_id, 'run_type': RUN_TYPES[run_id], 'why': None, 'boundaries': [], 'segments': [
        {'name': 'Minimisation', 'structure': structure, 'trajectory': EARLIER, 'atoms': 8, 'group': 1,
         'identity': 'earlier-copy', 'frames': 1000, 'time_ns': 99.5},
        {'name': 'CG extension MD', 'structure': structure, 'trajectory': LATEST, 'atoms': 8, 'group': 2,
         'identity': 'latest-copy', 'frames': 45001, 'time_ns': 900.0},
        {'name': 'Final assessment', 'structure': structure, 'trajectory': LATEST, 'atoms': 8,
         'duplicate_of': 'CG extension MD', 'frames': 45001, 'time_ns': 900.0},
    ]}


def default_arguments(run_id):
    """The arguments the block must default to for the run's latest system: `beads` for a coarse trajectory, raw."""
    return {'trajectory': LATEST, 'structure': STRUCTURES[run_id], 'start_ns': None, 'end_ns': None,
            'interval_ns': None, 'atoms': 'beads', 'pbc': 'none', 'boxcenter': 'tric', 'center': False,
            'fit': 'none', 'group': None}


def legacy_arguments(run_id):
    """An attempt built before ns per frame and the view options: a frame step, an assembly, a protein fit."""
    return {'trajectory': LATEST, 'structure': STRUCTURES[run_id], 'start_ns': None, 'end_ns': None,
            'stride': 10, 'fit': 'protein', 'fragment': None, 'atoms': 'beads', 'assembled': True}


def series_task(run_id, args, attempt='a1', *, status='completed'):
    """One `frame-series` attempt as `/analyses` reports it, with the two files a completed one published."""
    directory = f'analyses/frame-series/signature-{attempt}/{attempt}'
    task = {'id': f'task-{attempt}', 'kind': 'frame-series', 'signature': f'signature-{attempt}',
            'payload': args, 'status': status, 'created_at': '2026-10-20T10:00:00+00:00', 'directory': directory}
    return finish(task) if status == 'completed' else task


def finish(task):
    """A settled attempt's outputs, at the one place the worker writes them.

    The stable record is the run's one stored series: its files sit in its own directory, not in an attempt's
    `outputs/`.
    """
    task['status'] = 'completed'
    nested = '' if task.get('stable') else '/outputs'
    task['outputs'] = [f"{task['directory']}{nested}/run-frames.pdb",
                       f"{task['directory']}{nested}/frames.json"]
    return task


def stable_task(run_id, args, *, status='completed', outputs=True):
    """The run's one stored series, as `/analyses` reports it after the in-place change."""
    task = {'id': 'task-stable', 'kind': 'frame-series', 'stable': True, 'signature': 'signature-stable',
            'payload': args, 'status': status, 'created_at': '2026-10-20T10:00:00+00:00',
            'directory': 'analyses/frame-series'}
    if outputs:
        task['outputs'] = ['analyses/frame-series/run-frames.pdb', 'analyses/frame-series/frames.json']
    return task


def frames_json(run_id, *, identity='latest-copy', times=(0.0, 0.5, 1.0), size=2_400_000):
    """`frames.json` as the producer writes it: the times, the counts and the identities a stale check compares."""
    return {'args': {}, 'models': len(times), 'atoms': 3, 'times_ns': list(times),
            'indices': [index * 50 for index in range(len(times))], 'trajectory': LATEST,
            'structure': STRUCTURES[run_id], 'trajectory_identity': identity,
            'structure_identity': 'structure-copy', 'cadence_ns': 0.5, 'interval_ns': None,
            'view': {'pbc': 'none', 'center': False, 'fit': 'none', 'group': 'solute'}, 'legacy': [],
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
    """A build accepted: the attempt joins the run's list as `queued`, and the next read settles it.

    A run that keeps one stored series reuses its record instead: the same row goes back to `queued` with the new
    arguments, and the previous outputs stay on it until the build settles.
    """
    body = route.request.post_data_json
    state['posted'].append(body)
    stable = next((task for task in state['tasks'] if task.get('stable')), None)
    if stable is not None:
        stable.update(payload=body, status='queued', signature='signature-stable-rebuild')
        state['promote'] = True
        route.fulfill(status=202, json=stable)
        return
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
    page.route(re.compile(rf'/api/jobs/{run_id}/analyses(?:\?.*)?$'), lambda route: answer_analyses(route, state))
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


def open_run(dashboard, live_page, run_id, *, identity='latest-copy', tasks=None, why=None, log='', hold=False,
             recorded=True):
    """The run, its stubbed answers and the record of what the block asked for.

    `recorded` is the trajectory header read: `False` stubs an answer whose `frames`/`time_ns` are null, the state a
    header the server could not read puts the readout in.
    """
    seed(dashboard)
    page, errors = live_page
    # The build poll is the one thing this panel would otherwise wait two seconds for; the seam is the same one
    # `bonded-parameterization.js` carries for its own poll.
    page.add_init_script('window.__runViewPollMs = 25')
    answer = segments_answer(run_id)
    if not recorded:
        for entry in answer['segments']:
            entry['frames'] = None
            entry['time_ns'] = None
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


def segment_line(page, side='A'):
    return page.locator(f'#run-view-segment-meta-{side}')


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


def test_the_segment_line_states_the_selected_segments_frames_and_span(dashboard, live_page):
    """The header's own numbers, last frame minus first: 45,001 frames at 20 ps read 900 ns, not 900.02."""
    page, errors, _state = open_run(dashboard, live_page, ENGINE_RUN)

    expect(segment_line(page)).to_have_text('45,001 frames · 900 ns')
    page.locator('#run-view-segment-A').select_option('0')
    expect(segment_line(page)).to_have_text('1,000 frames · 99.5 ns')
    assert errors == [], errors


def test_a_segment_whose_header_cannot_be_read_says_so(dashboard, live_page):
    """A null answer is printed as not recorded -- never as zero frames, and never as an invented span."""
    page, errors, _state = open_run(dashboard, live_page, ENGINE_RUN, recorded=False)

    expect(segment_line(page)).to_have_text('Frames and time not recorded for this segment.')
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


def test_the_options_control_opens_the_form_and_only_the_submit_queues(dashboard, live_page):
    """One click path: the top control is the form's disclosure, and a queued attempt is the submit's doing alone."""
    page, errors, state = open_run(dashboard, live_page, ENGINE_RUN)
    expect(series(page)).to_contain_text('3 models')
    options = page.locator('#run-view-build-A')
    expect(options).to_have_text('Frame options')
    expect(options).to_have_attribute('aria-expanded', 'false')
    expect(options).to_have_attribute('aria-controls', 'run-view-recompute-A')
    expect(page.locator('#run-view-form-A')).to_be_hidden()

    options.click()
    expect(options).to_have_attribute('aria-expanded', 'true')
    expect(page.locator('#run-view-form-A')).to_be_visible()
    assert not state['posted'], 'the options control queued a build; only the submit may'

    options.click()
    expect(options).to_have_attribute('aria-expanded', 'false')
    expect(page.locator('#run-view-form-A')).to_be_hidden()
    assert not state['posted'], 'closing the options queued a build'

    options.click()
    page.locator('#run-view-submit-A').click()
    expect(series(page)).to_contain_text('5 models')
    assert len(state['posted']) == 1, state['posted']
    assert errors == [], errors


def test_the_submit_label_follows_the_attempt_it_would_build(dashboard, live_page):
    """Build frames for arguments nothing has built; Recompute frames for the attempt already on the stage."""
    page, errors, state = open_run(dashboard, live_page, ENGINE_RUN)
    expect(series(page)).to_contain_text('3 models')
    expect(page.locator('#run-view-submit-A')).to_have_text('Recompute frames')

    page.locator('#run-view-build-A').click()
    page.locator('#run-view-form-atoms-A').select_option('ca')
    expect(series(page)).to_contain_text('No frames have been built')
    expect(page.locator('#run-view-submit-A')).to_have_text('Build frames')

    page.locator('#run-view-submit-A').click()
    expect(series(page)).to_contain_text('5 models')
    expect(page.locator('#run-view-submit-A')).to_have_text('Recompute frames')
    assert errors == [], errors


def test_the_submit_says_build_when_no_attempt_matches(dashboard, live_page):
    """A run with nothing built yet offers one name for the action: Build frames."""
    page, errors, state = open_run(dashboard, live_page, ENGINE_RUN, tasks=[])
    expect(series(page)).to_contain_text('No frames have been built')

    page.locator('#run-view-build-A').click()
    expect(page.locator('#run-view-submit-A')).to_be_enabled()
    expect(page.locator('#run-view-submit-A')).to_have_text('Build frames')
    assert errors == [], errors


def test_submit_sends_the_eleven_key_body_for_the_chosen_controls(dashboard, live_page):
    """The form's values, exactly: the server validates this body, so a key in the wrong place is a refusal."""
    page, errors, state = open_run(dashboard, live_page, ENGINE_RUN)
    expect(series(page)).to_contain_text('3 models')

    page.locator('#run-view-build-A').click()
    page.wait_for_function(
        """() => [...document.querySelectorAll('#run-view-form-group-A option')]
            .some(option => option.value === 'fragment:B')""",
        timeout=30000)
    expect(page.locator('#run-view-form-group-A option[value="fragment:A"]')).to_contain_text('B01, B02, B03')

    page.locator('#run-view-form-atoms-A').select_option('ca')
    page.locator('#run-view-form-interval-A').fill('0.5')
    page.locator('#run-view-form-start-A').fill('1.5')
    page.locator('#run-view-form-end-A').fill('12')
    page.locator('#run-view-form-pbc-A').select_option('mol')
    page.locator('#run-view-form-boxcenter-A').select_option('zero')
    page.locator('#run-view-form-center-A').check()
    page.locator('#run-view-form-fit-A').select_option('rot+trans')
    page.locator('#run-view-form-group-A').select_option('fragment:B')
    page.locator('#run-view-submit-A').click()

    expect(series(page)).to_contain_text('CA atoms only')
    expect(series(page)).to_contain_text('PBC mol')
    expect(series(page)).to_contain_text('centred on fragment B at the zero box centre')
    expect(series(page)).to_contain_text('rotation-and-translation fit on fragment B')
    expect(series(page)).to_contain_text('one model every 0.5 ns')
    assert state['posted'] == [{'trajectory': LATEST, 'structure': STRUCTURES[ENGINE_RUN], 'start_ns': 1.5,
                                'end_ns': 12, 'interval_ns': 0.5, 'atoms': 'ca', 'pbc': 'mol',
                                'boxcenter': 'zero', 'center': True, 'fit': 'rot+trans', 'group': 'fragment:B'}], \
        state['posted']
    assert errors == [], errors


def test_the_form_counts_the_models_and_refuses_one_over_the_cap(dashboard, live_page):
    """The window and interval are applied in the count before queueing: 45,001 frames at 20 ps (900 ns) every
    0.5 ns is 1,801 models, over the 240 cap; 1.5–12 ns every 0.5 ns is 22. The server would refuse the first, so
    the form does too instead of making a failed attempt."""
    page, errors, state = open_run(dashboard, live_page, ENGINE_RUN)
    page.locator('#run-view-build-A').click()
    budget = page.locator('#run-view-form-budget-A')
    submit = page.locator('#run-view-submit-A')

    expect(budget).to_contain_text('120 models')
    page.locator('#run-view-form-interval-A').fill('0.5')
    expect(budget).to_contain_text('1801 models')
    expect(budget).to_contain_text('cap is 240')
    expect(submit).to_be_disabled()

    page.locator('#run-view-form-start-A').fill('1.5')
    page.locator('#run-view-form-end-A').fill('12')
    expect(budget).to_contain_text('22 models')
    expect(budget).not_to_contain_text('cap is')
    expect(submit).to_be_enabled()

    page.locator('#run-view-form-start-A').fill('12')
    page.locator('#run-view-form-end-A').fill('1.5')
    expect(budget).to_contain_text('Start is after End')
    expect(submit).to_be_disabled()
    assert state['posted'] == [], 'the refused request was queued'
    assert errors == [], errors


def test_cluster_and_the_box_centre_are_offered_and_sent(dashboard, live_page):
    """`cluster` is a selectable PBC mode with its tpr caveat, and Box centre names where the box is centred."""
    page, errors, state = open_run(dashboard, live_page, ENGINE_RUN)
    expect(series(page)).to_contain_text('3 models')
    page.locator('#run-view-build-A').click()

    pbc = page.locator('#run-view-form-pbc-A')
    expect(pbc.locator('option')).to_have_count(7)
    expect(pbc.locator('option[value="res"]')).to_contain_text('each residue')
    expect(pbc.locator('option[value="atom"]')).to_contain_text('each atom')
    expect(pbc.locator('option[value="cluster"]')).to_contain_text('centre of mass')
    expect(pbc.locator('option[value="cluster"]')).to_contain_text('.tpr')
    expect(page.locator('#run-view-form-boxcenter-A')).to_have_value('tric')
    expect(page.locator('#run-view-form-boxcenter-A option')).to_have_count(3)
    expect(page.locator('#run-view-form-boxcenter-A option[value="rect"]')).to_contain_text('half the diagonal')
    hint = page.locator('#run-view-recompute-A > p.hint')
    expect(hint).to_contain_text('cluster')
    expect(hint).to_contain_text('.tpr')

    pbc.select_option('cluster')
    page.locator('#run-view-form-boxcenter-A').select_option('rect')
    page.locator('#run-view-form-center-A').check()
    page.locator('#run-view-submit-A').click()

    expect(series(page)).to_contain_text('PBC cluster')
    expect(series(page)).to_contain_text('centred on the solute at the rect box centre')
    posted = state['posted'][0]
    assert posted['pbc'] == 'cluster', posted
    assert posted['boxcenter'] == 'rect', posted
    assert posted['center'] is True, posted
    assert errors == [], errors


def test_a_blank_interval_sends_null_and_asks_the_server_for_auto(dashboard, live_page):
    """A blank ns per frame is `interval_ns: null`, not a zero and not an omitted key: the server reads the one."""
    page, errors, state = open_run(dashboard, live_page, ENGINE_RUN)
    expect(series(page)).to_contain_text('3 models')

    page.locator('#run-view-build-A').click()
    page.locator('#run-view-form-atoms-A').select_option('ca')
    page.locator('#run-view-submit-A').click()

    expect(series(page)).to_contain_text('5 models')
    assert state['posted'] == [dict(default_arguments(ENGINE_RUN), atoms='ca')], state['posted']
    assert errors == [], errors


def test_a_legacy_attempt_is_found_played_and_named_as_a_frame_step(dashboard, live_page):
    """An attempt built with `stride`/`assembled`/`fit: protein` stays playable and is never relabelled as a view.

    Its view is the one the old keys described -- mol, centred, rotation and translation on the protein -- so the
    form that finds it holds those options. Only a blank interval matches: the attempt recorded no interval_ns at all.
    """
    legacy = series_task(ENGINE_RUN, legacy_arguments(ENGINE_RUN), 'a1')
    page, errors, state = open_run(dashboard, live_page, ENGINE_RUN, tasks=[legacy])
    expect(series(page)).to_contain_text('No frames have been built')

    page.locator('#run-view-build-A').click()
    page.locator('#run-view-form-pbc-A').select_option('mol')
    page.locator('#run-view-form-center-A').check()
    page.locator('#run-view-form-fit-A').select_option('rot+trans')
    page.locator('#run-view-form-group-A').select_option('protein')

    expect(series(page)).to_contain_text('3 models')
    expect(series(page)).to_contain_text('one model every 0.5 ns')
    expect(series(page)).to_contain_text('PBC mol')
    expect(series(page)).to_contain_text('centred on the protein')
    expect(series(page)).to_contain_text('rotation-and-translation fit on the protein')
    expect(series(page)).to_contain_text('built with a frame step')
    expect(page.locator('#run-view-submit-A')).to_have_text('Recompute frames')

    page.locator('#run-view-loop-A').check()
    page.locator('#run-view-play-A').click()
    page.wait_for_function(
        "() => document.querySelector('#run-view-time-A').textContent.includes('model 2/3')", timeout=30000)
    assert measured(page)['frames'] == 3

    # An interval the attempt never recorded is not a match: only a blank one is the old attempt's default.
    page.locator('#run-view-form-interval-A').fill('0.5')
    page.locator('#run-view-form-atoms-A').focus()
    expect(series(page)).to_contain_text('No frames have been built')
    assert errors == [], errors


def test_an_attempt_without_a_box_centre_is_still_found_and_played(dashboard, live_page):
    """An attempt written before `boxcenter` existed is the tric default, so the default form finds and plays it."""
    old = dict(default_arguments(ENGINE_RUN))
    old.pop('boxcenter')
    page, errors, state = open_run(dashboard, live_page, ENGINE_RUN, tasks=[series_task(ENGINE_RUN, old)])

    expect(series(page)).to_contain_text('3 models')
    expect(page.locator('#run-view-submit-A')).to_have_text('Recompute frames')

    # The form it was found by holds the normalised default, not a blank select.
    page.locator('#run-view-build-A').click()
    expect(page.locator('#run-view-form-boxcenter-A')).to_have_value('tric')

    page.locator('#run-view-loop-A').check()
    page.locator('#run-view-play-A').click()
    page.wait_for_function(
        "() => document.querySelector('#run-view-time-A').textContent.includes('model 2/3')", timeout=30000)
    assert measured(page)['frames'] == 3
    assert errors == [], errors


def test_the_group_control_shows_only_when_the_centre_or_the_fit_needs_it(dashboard, live_page):
    """Group is hidden for a raw view and offered as soon as Centre or a fit would act on one."""
    page, errors, state = open_run(dashboard, live_page, ENGINE_RUN)
    page.locator('#run-view-build-A').click()
    group = page.locator('#run-view-form-group-A')
    expect(group).to_be_hidden()
    expect(page.locator('#run-view-form-pbc-A')).to_be_visible()

    page.locator('#run-view-form-center-A').check()
    expect(group).to_be_visible()
    page.locator('#run-view-form-center-A').uncheck()
    expect(group).to_be_hidden()

    page.locator('#run-view-form-fit-A').select_option('trans')
    expect(group).to_be_visible()
    page.locator('#run-view-form-fit-A').select_option('none')
    expect(group).to_be_hidden()
    expect(page.locator('#run-view-form-pbc-A option')).to_have_count(7)
    assert errors == [], errors


def test_align_trajectory_holds_every_model_on_the_solute(dashboard, live_page):
    """The old fit-the-frames control, restored: checked, the body is rot+trans on the solute and the picks stand
    disabled; unchecked, the explicit Fit and Group are what it carries."""
    page, errors, state = open_run(dashboard, live_page, ENGINE_RUN)
    expect(series(page)).to_contain_text('3 models')
    page.locator('#run-view-build-A').click()
    align = page.locator('#run-view-form-align-A')
    fit = page.locator('#run-view-form-fit-A')
    group = page.locator('#run-view-form-group-A')
    expect(align).not_to_be_checked()
    expect(fit).to_be_enabled()

    align.check()

    expect(fit).to_be_disabled()
    expect(group).to_be_disabled()
    expect(fit).to_have_value('rot+trans')
    expect(group).to_have_value('solute')
    page.locator('#run-view-submit-A').click()

    expect(series(page)).to_contain_text('rotation-and-translation fit on the solute')
    assert state['posted'][-1]['fit'] == 'rot+trans', state['posted']
    assert state['posted'][-1]['group'] == 'solute', state['posted']

    align.uncheck()

    expect(fit).to_be_enabled()
    expect(group).to_be_enabled()
    fit.select_option('trans')
    group.select_option('protein')
    page.locator('#run-view-submit-A').click()

    expect(series(page)).to_contain_text('translation-only fit on the protein')
    assert state['posted'][-1]['fit'] == 'trans', state['posted']
    assert state['posted'][-1]['group'] == 'protein', state['posted']
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
    expect(page.locator('#run-view-submit-A')).to_have_text('Building frames…')
    expect(page.locator('#run-view-form-note-A')).to_contain_text('queued')
    assert not state['posted'], 'a second attempt was queued for a build the run is already running'
    assert errors == [], errors


def test_the_stored_series_plays_whatever_arguments_the_form_holds(dashboard, live_page):
    """One stored series is Play's one file; the form describes the next build, not a different series to look up."""
    stored = dict(default_arguments(ENGINE_RUN), interval_ns=1.0)
    page, errors, state = open_run(dashboard, live_page, ENGINE_RUN, tasks=[stable_task(ENGINE_RUN, stored)])
    expect(series(page)).to_contain_text('3 models')
    expect(page.locator('#run-view-trajectory-note-A')).to_contain_text('Build replaces the stored series')
    expect(page.locator('#run-view-play-A')).to_be_enabled()

    page.locator('#run-view-play-A').click()
    page.wait_for_function("() => document.querySelector('#run-view-viewer-A').runViewStage.compList.length === 2")
    assert any('/artifacts/analyses/frame-series/run-frames.pdb?inline=1' in url for url in state['requests']), \
        'Play did not fetch the stored series'
    assert errors == [], errors


def test_switching_the_segment_keeps_the_stored_series_and_describes_its_own_build(dashboard, live_page):
    """The run's one series outlives the segment combo, and names the segment it sampled, not the one selected now."""
    page, errors, state = open_run(dashboard, live_page, ENGINE_RUN,
                                   tasks=[stable_task(ENGINE_RUN, default_arguments(ENGINE_RUN))])
    expect(series(page)).to_contain_text('3 models')
    expect(series(page)).to_contain_text('Built from CG extension MD')

    page.locator('#run-view-segment-A').select_option('0')

    expect(series(page)).to_contain_text('3 models')
    expect(series(page)).to_contain_text('Built from CG extension MD')
    expect(series(page)).not_to_contain_text('Minimisation')
    expect(series(page)).not_to_contain_text('older copy')
    expect(page.locator('#run-view-trajectory-note-A')).to_contain_text('selected segment or frame options differ')
    expect(page.locator('#run-view-play-A')).to_be_enabled()
    assert errors == [], errors


def test_a_rebuild_replaces_the_one_file_and_the_block_reads_it(dashboard, live_page):
    """A build with other arguments replaces the stored pair; no second task or attempt is minted for it."""
    page, errors, state = open_run(dashboard, live_page, ENGINE_RUN,
                                   tasks=[stable_task(ENGINE_RUN, default_arguments(ENGINE_RUN))])
    expect(series(page)).to_contain_text('3 models')
    # What the next build publishes: the same path, different content.
    state['frames']['a1'] = frames_json(ENGINE_RUN, times=(0.0, 1.0, 2.0, 3.0, 4.0), size=3_100_000)

    page.locator('#run-view-build-A').click()
    page.locator('#run-view-form-atoms-A').select_option('ca')
    page.locator('#run-view-submit-A').click()

    expect(series(page)).to_contain_text('5 models')
    expect(series(page)).to_contain_text('CA atoms only')
    assert any('/artifacts/analyses/frame-series/frames.json?inline=1' in url for url in state['requests']), \
        'the rebuilt series was not read from its stable path'
    assert len(state['tasks']) == 1, state['tasks']
    assert [task['status'] for task in state['tasks']] == ['completed'], state['tasks']
    page.locator('#run-view-play-A').click()
    page.wait_for_function("() => document.querySelector('#run-view-viewer-A').runViewStage.compList.length === 2")
    assert errors == [], errors


def test_a_failed_rebuild_still_plays_the_stored_series(dashboard, live_page):
    """A rebuild that failed before publishing leaves the last good series on disk and playable."""
    failed = stable_task(ENGINE_RUN, default_arguments(ENGINE_RUN), status='failed')
    failed['error'] = 'the trajectory was replaced mid-build'
    page, errors, state = open_run(dashboard, live_page, ENGINE_RUN, tasks=[failed], log='boom')

    expect(series(page)).to_contain_text('3 models')
    expect(page.locator('#run-view-trajectory-note-A')).to_contain_text('last successful build')
    expect(page.locator('#run-view-play-A')).to_be_enabled()
    assert errors == [], errors


def test_the_block_fits_a_narrow_window(dashboard, live_page):
    """The block is one column of a two-monitor grid, and the form's controls all sit in it: none may widen the page."""
    page, errors, state = open_run(dashboard, live_page, ENGINE_RUN)
    page.set_viewport_size({'width': 390, 'height': 900})
    page.locator('#run-view-build-A').click()
    expect(page.locator('#run-view-form-atoms-A')).to_be_visible()
    browser.assert_no_horizontal_scroll(page)
    assert errors == [], errors


# ------------------------------------------------------------------------------------------------- failure states


def test_a_series_older_than_the_trajectory_says_so_and_points_at_the_options(dashboard, live_page):
    """A built series whose trajectory digest is not the segment's is played, but it is named as an old copy."""
    page, errors, state = open_run(dashboard, live_page, ENGINE_RUN, identity='older-copy')

    expect(series(page)).to_contain_text('older copy of that trajectory')
    note = page.locator('#run-view-trajectory-note-A')
    expect(note).to_contain_text('Frame options')
    expect(note).not_to_contain_text('Recompute frames')
    expect(page.locator('#run-view-build-A')).to_have_text('Frame options')
    expect(page.locator('#run-view-build-A')).to_be_enabled()
    # The submit is the one place that says "Recompute frames", and this series is the attempt it would rebuild.
    expect(page.locator('#run-view-submit-A')).to_have_text('Recompute frames')
    expect(page.get_by_text('Recompute frames', exact=True)).to_have_count(1)
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
    assert state['posted'][-1] == dict(default_arguments(run_id), atoms='all'), state['posted']
    assert errors == [], errors




def test_both_cards_share_one_analyses_request_per_tick(dashboard, live_page):
    """The Analysis card and the Trajectory block poll the same run: one `/analyses` request per tick, not two.

    Both cards ask for the summary view of the same path through `liveApi`, so while one answer is in flight the
    other waits for it. The route is held open on purpose: with a settled answer each caller would start its own
    request, and this test is about the shared in-flight promise, not about a cache (there is none).
    """
    seed(dashboard)
    page, errors = live_page
    page.add_init_script('window.__runViewPollMs = 150')
    run_id = ENGINE_RUN
    tasks = [series_task(run_id, default_arguments(run_id), status='queued')]
    held = []
    page.route(re.compile(rf'/api/jobs/{run_id}/trajectory$'),
               lambda route: route.fulfill(json=segments_answer(run_id)))
    page.route(re.compile(rf'/api/jobs/{run_id}/analyses(?:\?.*)?$'), lambda route: held.append(route))
    open_panel(page, live_page, WORKSPACES[run_id], run_id)

    # The two mount reads share the first answer even though they start it at different times.
    deadline = time.monotonic() + 10
    while not held and time.monotonic() < deadline:
        page.wait_for_timeout(25)
    assert held, 'neither card asked for the run\'s analyses'
    page.wait_for_timeout(600)           # more than one 150 ms cadence
    assert len(held) == 1, f'the second card started its own request: {len(held)}'

    # Release it; both cards settle and arm their own timer. The next tick must again be one request.
    held.pop().fulfill(json=tasks)
    deadline = time.monotonic() + 10
    while not held and time.monotonic() < deadline:
        page.wait_for_timeout(25)
    assert held, 'neither card polled after the answer settled'
    page.wait_for_timeout(1200)          # eight cadences: a second poller would have asked by now
    assert len(held) == 1, f'the tick was requested {len(held)} times, not once'
    for route in held:
        route.fulfill(json=tasks)
    assert errors == [], errors
