"""Runs layout and inline resources, against an isolated dashboard database."""
import re

from dashboard import files
from playwright.sync_api import expect

from tests.harness import browser


def test_a_run_recorded_under_the_old_stage_name_keeps_its_short_label(dashboard, live_page):
    """21 runs say `trajectory mapping (ff_map)` -- the name this stage had when it called that tool.

    Their abbreviation has to survive the rename: a timeline that fell back to printing the whole recorded name would
    show those runs differently from every run after them, for a change they had nothing to do with. The recorded
    words stay recorded, which is why the step's own description still carries them.
    """
    runs = dashboard.coordinator.RUNS
    job_id = '00000000000a'
    recorded = ['AA reference', 'trajectory mapping (ff_map)', 'CG topology (ff_inter)']
    dashboard.coordinator.database().replace([{
        'id': job_id, 'label': 'Recorded under the old stage name', 'detergent': 'DDM', 'method': 'fast_forward',
        'status': 'completed', 'stage': 'complete', 'created': '2026-09-16T10:00:00+00:00',
        'started_at': '2026-09-16T10:00:00+00:00', 'layout_version': 2}])
    directory = runs / job_id
    (directory / 'logs').mkdir(parents=True)
    files.atomic_json(directory / 'manifest.json',
                      {'stage_plan': recorded,
                       'stages': [{'name': name, 'status': 'completed'} for name in recorded]})

    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/runs')

    step = page.locator(f'.job[data-id="{job_id}"] .timeline-step').nth(1)
    expect(step.locator('.timeline-label')).to_have_text('Map')
    expect(step).to_have_attribute('aria-label', 'trajectory mapping (ff_map): completed')
    assert errors == [], errors


def test_the_renamed_stage_reads_the_same_under_both_spellings(dashboard, live_page):
    """Stage 3 is `CG parameterization` now; every run already on disk records `CG topology (ff_inter)`.

    A rename that showed those runs as a long recorded string, or as nothing, would make history read differently
    from the runs after it for a change it had nothing to do with. So both spellings map to the one abbreviation the
    stage has always shown, and the recorded words stay recorded -- unrewritten, and still on the step's own
    description, which is the tooltip a reader gets and the label a screen reader announces.
    """
    runs = dashboard.coordinator.RUNS
    recorded = {'00000000000b': 'CG topology (ff_inter)', '00000000000c': 'CG parameterization'}
    dashboard.coordinator.database().replace([
        {'id': job_id, 'label': f'Recorded as {name}', 'detergent': 'DDM', 'method': 'fast_forward',
         'status': 'completed', 'stage': 'complete', 'created': '2026-09-16T10:00:00+00:00',
         'started_at': '2026-09-16T10:00:00+00:00', 'layout_version': 2}
        for job_id, name in recorded.items()])
    for job_id, name in recorded.items():
        directory = runs / job_id
        (directory / 'logs').mkdir(parents=True)
        plan = ['AA reference', 'trajectory mapping', name]
        files.atomic_json(directory / 'manifest.json',
                          {'stage_plan': plan, 'stages': [{'name': step, 'status': 'completed'} for step in plan]})

    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/runs')

    old = page.locator('.job[data-id="00000000000b"] .timeline-step').nth(2)
    new = page.locator('.job[data-id="00000000000c"] .timeline-step').nth(2)
    # One abbreviation for both spellings: the run recorded under the old name shows the label the new name gets.
    expect(old.locator('.timeline-label')).to_have_text('Fit')
    expect(new.locator('.timeline-label')).to_have_text('Fit')
    # The recorded name is not rewritten and is not lost: it is the step's own description.
    expect(old).to_have_attribute('aria-label', 'CG topology (ff_inter): completed')
    expect(old).to_have_attribute('title', 'CG topology (ff_inter): completed')
    expect(new).to_have_attribute('aria-label', 'CG parameterization: completed')
    assert errors == [], errors


def test_runs_views_checkpoints_and_stage_settings(dashboard, live_page):
    runs = dashboard.coordinator.RUNS
    stages = ['AA reference', 'trajectory mapping', 'CG topology (ff_inter)', 'CG simulation', 'CG assessment (ff_assess)', 'SASA analysis']
    jobs = [{'id': f'{i:012x}', 'label': label, 'detergent': 'DDM', 'method': 'fast_forward',
             'status': status, 'stage': stage, 'created': '2026-09-16T10:00:00+00:00',
             'started_at': '2026-09-16T10:00:00+00:00', 'layout_version': 2}
            for i, (label, status, stage) in enumerate([
                ('Completed control', 'completed', 'complete'), ('Active screening', 'running', stages[3]),
                ('Failed fit with a deliberately long descriptive run label', 'failed', stages[2])], 1)]
    dashboard.coordinator.database().replace(jobs)
    for job in jobs:
        directory = runs/job['id']; (directory/'logs').mkdir(parents=True)
        states = ['completed'] * 6 if job['status'] == 'completed' else ['reused', 'completed', 'completed', 'running', 'pending', 'pending'] if job['status'] == 'running' else ['completed', 'completed', 'failed', 'pending', 'pending', 'pending']
        files.atomic_json(directory/'manifest.json', {'stage_plan': stages, 'stages': [{'name': name, 'status': status} for name, status in zip(stages, states)]})
    settings = {'id': '000000000001', 'stage_settings': {'groups': [{
        'stage': 'AA minimization', 'label': 'AA minimization', 'fields': [
            {'key': 'aa_minimization_steps', 'label': 'Maximum steps', 'value': 20000},
            {'key': 'aa_emtol', 'label': 'Force tolerance', 'value': 1000, 'unit': 'kJ/mol/nm'}]}],
        'segments': None, 'total_steps': None}}
    page, errors = live_page
    page.route(re.compile(r'/api/jobs/000000000001$'), lambda route: route.fulfill(json=settings))
    url = f'{live_page.base_url}/detergent-validation/runs'
    page.goto(url)
    expect(page).to_have_title('Detergent MD · Laboratory')
    expect(page.locator('#jobs > tbody.job')).to_have_count(3)
    expect(page.locator('#jobs > thead')).to_contain_text('Molecule')
    expect(page.locator('.job-compare,.job-snapshots,#compare-runs')).to_have_count(0)
    # The three per-run disclosures and their console pane are gone; Stage settings is the one that remains.
    expect(page.locator('.job-artifacts,.job-records,.job-console,#console-panel')).to_have_count(0)
    complete = page.locator('.job[data-id="000000000001"]')
    active = page.locator('.job[data-id="000000000002"]')
    failed = page.locator('.job[data-id="000000000003"]')
    expect(complete.locator('.timeline-step[data-status=completed]')).to_have_count(6)
    expect(active.locator('[aria-current=step]')).to_have_attribute('aria-label','CG simulation: running')
    expect(active.locator('.timeline-step[data-status=reused]')).to_have_count(1)
    expect(failed.locator('.timeline-step[data-status=failed]')).to_have_count(1)
    assert active.locator('.workflow-timeline').bounding_box()['x'] > active.locator('.job-title').bounding_box()['x']
    # One list, no layout control: Dense is the table itself now, so there is nothing to switch to and nothing to
    # remember. The old storage key is simply ignored rather than migrated.
    expect(page.locator('[data-run-view]')).to_have_count(0)
    expect(page.locator('#runs')).not_to_have_attribute('data-view', re.compile('table|grouped|dense'))
    # The analysis panel is gone from this card: its figures, queue buttons and task list are the Run view's
    # Analysis card, drawn beside the run they belong to. `test_run_view_analysis_browser.py` drives that card.
    expect(complete.locator('.job-analysis')).to_have_count(0)
    # Expanding the row draws the values the run recorded, grouped by the stage that recorded them.
    complete.locator('.job-stage-settings > summary').click()
    host = complete.locator('.stage-settings-host')
    expect(host.locator('h4')).to_have_text('AA minimization')
    expect(host).to_contain_text('Maximum steps')
    expect(host).to_contain_text('20000')
    expect(host).to_contain_text('Force tolerance')
    expect(host).to_contain_text('1000 kJ/mol/nm')
    # A poll while the disclosure is open re-renders it from the same keyed answer rather than clearing it.
    page.evaluate('refreshJobs()')
    expect(host).to_contain_text('Maximum steps')
    page.set_viewport_size({'width':390, 'height':844})
    # The table itself scrolls inside its frame; the page must not gain a horizontal scrollbar because of it.
    browser.assert_no_horizontal_scroll(page)
    assert not errors, errors


def test_a_running_stage_reports_the_leg_it_is_in_and_how_far_through(dashboard, live_page):
    """A three-leg script stage has no single GROMACS ETA; the bar counts its legs and the step within the current one.

    `cg_simulation.sh` runs minimisation, equilibration and production in a row, so for two thirds of its life the
    ETA speaks about a leg that is not the stage. The bar is computed from the stage's own log -- legs announced by
    `gmx mdrun -deffnm`, each leg's length from the mdp `grompp` built it from -- and this test drives that whole
    path: a record, a manifest, a stage log and its mdps, then the card the browser draws from them.
    """
    runs = dashboard.coordinator.RUNS
    job_id = '00000000000d'
    dashboard.coordinator.database().replace([{
        'id': job_id, 'label': 'Running the CG simulation', 'detergent': 'DDM', 'method': 'fast_forward',
        'status': 'running', 'stage': 'CG simulation', 'created': '2026-10-20T12:00:00+00:00',
        'started_at': '2026-10-20T12:00:00+00:00', 'layout_version': 2, 'run_type': 'cg'}])
    directory = runs / job_id
    stage = directory / 'stages' / '4_CG_sim'
    (stage / 'inputs').mkdir(parents=True)
    (directory / 'logs').mkdir(parents=True)
    for name, steps in (('minimization', 500), ('eq', 10000), ('md', 400)):
        (stage / 'inputs' / f'{name}.mdp').write_text(f'nsteps = {steps}\n')
    log = ('+ gmx grompp -f inputs/minimization.mdp -p system.top -c solvated.gro -o min.tpr\n'
           '+ gmx mdrun -deffnm min -ntomp 8\nstarting mdrun \'DDM\'\nstep 0\nstep 500, done\n'
           '+ gmx grompp -f inputs/eq.mdp -p system.top -c min.gro -o eq.tpr\n'
           '+ gmx mdrun -deffnm eq -ntomp 8\nstarting mdrun \'DDM\'\nstep 0\nstep 10000, done\n'
           '+ gmx grompp -f inputs/md.mdp -p system.top -c eq.gro -o md.tpr\n'
           '+ gmx mdrun -deffnm md -ntomp 8\nstarting mdrun \'DDM\'\nstep 0\n'
           'step 100\rstep 200, remaining wall clock time: 5 s\r')
    (directory / 'logs' / '4_CG_sim.log').write_text(log)
    files.atomic_json(directory / 'manifest.json', {
        'stage_plan': [['AA reference', '1_AA-reference/aa_reference.sh'],
                       ['trajectory mapping', '2_mapping/map_trajectory.sh'],
                       ['CG parameterization', '3_initial_CG/use_parameterization.sh'],
                       ['CG simulation', '4_CG_sim/cg_simulation.sh'],
                       ['CG assessment (ff_assess)', '5_assessment/assess.sh']],
        'stages': [{'name': 'AA reference', 'status': 'reused'},
                   {'name': 'trajectory mapping', 'status': 'completed'},
                   {'name': 'CG parameterization', 'status': 'completed'},
                   {'name': 'CG simulation', 'status': 'running',
                    'log': str(directory / 'logs' / '4_CG_sim.log')}]})

    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/runs')

    bar = page.locator(f'.job[data-id="{job_id}"] .job-progress')
    expect(bar).to_be_visible()
    # The CG run's four work stages; the simulation is the third and is 83% through its own leg chain.
    expect(bar).to_have_class(re.compile('segmented'))
    expect(bar.locator('.job-progress-seg')).to_have_count(4)
    current = bar.locator('.job-progress-seg').nth(2)
    expect(current).to_have_class(re.compile('current'))
    assert current.evaluate("el => el.style.getPropertyValue('--fill')") == '83%'
    # Two completed stages plus 83% of the third, over the four.
    expect(bar).to_have_attribute('aria-valuenow', '71')
    expect(bar).to_have_attribute('aria-valuetext', 'Simulation 83%')
    expect(page.locator(f'.job[data-id="{job_id}"] .job-progress-text')).to_contain_text('leg 3 of 3')
    assert errors == [], errors


#: One pdc run's work-stage segments: equal width, with the micelle assessment planned away.
PDC_SEGMENTS = [
    {'stage': 'Energy minimisation', 'label': 'Minimisation', 'kind': 'min', 'steps': None, 'fraction': 0.125},
    {'stage': 'NVT equilibration', 'label': 'NVT equilibration', 'kind': 'nvt', 'steps': None, 'fraction': 0.125},
    {'stage': 'NPT equilibration', 'label': 'NPT equilibration', 'kind': 'npt', 'steps': None, 'fraction': 0.125},
    {'stage': 'CG assessment MD', 'label': 'CG assessment MD', 'kind': 'equilibration', 'steps': None, 'fraction': 0.125},
    {'stage': 'Micelle assessment', 'label': 'Micelle assessment', 'kind': 'assessment', 'steps': None,
     'fraction': 0.125, 'skipped': True},
    {'stage': 'CG extension MD', 'label': 'CG extension MD', 'kind': 'production', 'steps': None, 'fraction': 0.125},
    {'stage': 'Final assessment', 'label': 'Final assessment', 'kind': 'assessment', 'steps': None, 'fraction': 0.125},
    {'stage': 'Back-mapping (CG2AT2)', 'label': 'Back-mapping', 'kind': 'backmap', 'steps': None, 'fraction': 0.125},
]


def test_an_aa_run_keeps_its_step_widths_and_a_pdc_run_draws_its_work_stages(dashboard, live_page):
    """AA segments are the server's step arithmetic; a pdc run's are its work stages, equal width.

    The list payload carries `stage_segments` and the current progress. Widths are the payload's fractions, not a
    second calculation in the browser, so a segment cannot disagree with the steps behind it. A skipped work stage is
    hatched and never reads as current.
    """
    aa = {
        'id': '0000000000aa', 'label': 'AA run', 'detergent': 'DDM', 'method': 'gromacs', 'run_type': 'aa_only',
        'status': 'running', 'stage': 'AA NVT equilibration', 'created': '2026-11-16T10:00:00+00:00',
        'progress': {'stage': 'AA NVT equilibration', 'leg': 'nvt', 'leg_index': 1, 'legs': 1,
                     'percent': 50, 'steps': 500, 'step': 250},
        'stage_segments': [
            {'stage': 'AA minimization', 'label': 'Minimization', 'kind': 'min', 'steps': 20000, 'fraction': 0.2},
            {'stage': 'AA NVT equilibration', 'label': 'NVT equilibration', 'kind': 'nvt', 'steps': 10000, 'fraction': 0.3},
            {'stage': 'AA NPT equilibration', 'label': 'NPT equilibration', 'kind': 'npt', 'steps': 10000, 'fraction': 0.3},
            {'stage': 'AA NPT production', 'label': 'NPT production', 'kind': 'production', 'steps': 20000, 'fraction': 0.2},
        ],
    }
    pdc = {
        'id': '0000000000bb', 'label': 'pdc run', 'detergent': 'DDM', 'method': 'gromacs', 'run_type': 'pdc',
        'status': 'running', 'stage': 'NPT equilibration', 'created': '2026-11-16T10:00:00+00:00',
        'progress': {'stage': 'NPT equilibration', 'leg': 'npt', 'leg_index': 1, 'legs': 1,
                     'percent': 60, 'steps': 500000, 'step': 300000},
        'stage_segments': PDC_SEGMENTS,
    }
    page, errors = live_page
    page.route(re.compile(r'/api/jobs\?'),
               lambda route: route.fulfill(json={'jobs': [aa, pdc], 'total': 2, 'page': 1, 'limit': 20}))
    page.goto(f'{live_page.base_url}/detergent-validation/runs')

    bar = page.locator('.job[data-id="0000000000aa"] .job-progress')
    expect(bar).to_have_class(re.compile('segmented'))
    segments = bar.locator('.job-progress-seg')
    expect(segments).to_have_count(4)
    assert segments.evaluate_all('(els) => els.map(el => el.style.width)') == [
        '20%', '30%', '30%', '20%'], 'the widths are the payload fractions'
    assert segments.evaluate_all('(els) => els.map(el => el.dataset.kind)') == [
        'min', 'nvt', 'npt', 'production']
    expect(segments.nth(0)).to_have_class(re.compile('done'))
    expect(segments.nth(1)).to_have_class(re.compile('current'))
    expect(segments.nth(2)).to_have_class(re.compile('future'))
    expect(bar).to_have_attribute('aria-valuenow', '35')

    work = page.locator('.job[data-id="0000000000bb"] .job-progress')
    expect(work).to_have_class(re.compile('segmented'))
    steps = work.locator('.job-progress-seg')
    expect(steps).to_have_count(8)
    assert steps.evaluate_all('(els) => els.map(el => el.style.width)') == ['12.5%'] * 8, \
        'equal width: these stages have no comparable step count'
    assert steps.evaluate_all('(els) => els.map(el => el.dataset.kind)') == [
        'min', 'nvt', 'npt', 'equilibration', 'assessment', 'production', 'assessment', 'backmap']
    expect(steps.nth(0)).to_have_class(re.compile('done'))
    expect(steps.nth(2)).to_have_class(re.compile('current'))
    expect(steps.nth(3)).to_have_class(re.compile('future'))
    expect(steps.nth(4)).to_have_class(re.compile('skipped'))
    expect(work).to_have_attribute('aria-valuenow', '33')
    expect(work).to_have_attribute('aria-valuetext', 'NPT equilibration 60%')
    assert errors == [], errors


def test_a_work_stage_with_no_percent_sweeps_rather_than_filling(dashboard, live_page):
    """A stage with no step count has no percent: its segment sweeps and the bar reads nothing completed."""
    minimisation = {
        'id': '0000000000cc', 'label': 'pdc run', 'detergent': 'DDM', 'method': 'gromacs', 'run_type': 'pdc',
        'status': 'running', 'stage': 'Energy minimisation', 'created': '2026-11-16T10:00:00+00:00',
        'progress': {'stage': 'Energy minimisation', 'leg': 'min', 'leg_index': 1, 'legs': 1, 'percent': None},
        'stage_segments': PDC_SEGMENTS,
    }
    page, errors = live_page
    page.route(re.compile(r'/api/jobs\?'),
               lambda route: route.fulfill(json={'jobs': [minimisation], 'total': 1, 'page': 1, 'limit': 20}))
    page.goto(f'{live_page.base_url}/detergent-validation/runs')

    bar = page.locator('.job[data-id="0000000000cc"] .job-progress')
    expect(bar.locator('.job-progress-seg')).to_have_count(8)
    expect(bar.locator('.job-progress-seg').nth(0)).to_have_class(re.compile('unknown'))
    expect(bar).to_have_attribute('aria-valuenow', '0')
    expect(bar).to_have_attribute('aria-valuetext', 'Minimisation running')
    assert errors == [], errors


def test_a_skipped_stage_shows_why_it_had_nothing_to_do(dashboard, live_page):
    """A run can complete without a score, and the stage that skipped is where the reason belongs.

    `ff_assess` scores against the AA reference's histograms; a BARTENDER model records none and its own analysis is
    unbuilt (D6a), so the assessment exits 4 with its reason in `skip.json`, the run carries on, and the step carries
    that sentence. A bare dash would leave the reader inventing a cause.
    """
    runs = dashboard.coordinator.RUNS
    job_id = '00000000000e'
    reason = ('BARTENDER measured no reference histograms when this model was fitted, and its own analysis is not'
              ' built yet')
    dashboard.coordinator.database().replace([{
        'id': job_id, 'label': 'A bartender model, simulated', 'detergent': 'DDM', 'method': 'bartender',
        'status': 'completed', 'stage': 'complete', 'created': '2026-10-21T02:00:00+00:00',
        'started_at': '2026-10-21T02:00:00+00:00', 'layout_version': 2, 'run_type': 'cg'}])
    directory = runs / job_id
    (directory / 'logs').mkdir(parents=True)
    plan = ['AA reference', 'trajectory mapping', 'CG parameterization', 'CG simulation',
            'CG assessment (ff_assess)']
    # A manifest's `stage_plan` holds names -- the pairs are the job record's own spelling of the same plan.
    files.atomic_json(directory / 'manifest.json', {
        'stage_plan': plan,
        'stages': [{'name': name, 'status': 'completed'} for name in plan[:4]] +
                  [{'name': plan[4], 'status': 'skipped', 'error': reason}]})

    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/runs')

    step = page.locator(f'.job[data-id="{job_id}"] .timeline-step').nth(4)
    expect(step.locator('.timeline-dot')).to_have_text('–')
    assert reason in step.get_attribute('aria-label'), step.get_attribute('aria-label')
    assert reason in step.get_attribute('title')
    assert errors == [], errors




def test_a_run_card_states_how_much_of_it_is_trajectory(dashboard, live_page):
    """The number that informs deletion is on the card itself, so a reader does not have to open the run.

    Seeded as a sparse file: the card reads the file's size, and a browser test should not pay for the bytes.
    """
    runs = dashboard.coordinator.RUNS
    job_id = '00000000000d'
    dashboard.coordinator.database().replace([{
        'id': job_id, 'label': 'A run worth deleting', 'detergent': 'DDM', 'method': 'fast_forward',
        'status': 'completed', 'stage': 'complete', 'created': '2026-09-16T10:00:00+00:00',
        'started_at': '2026-09-16T10:00:00+00:00', 'layout_version': 2}])
    target = runs / job_id / 'stages/04_nvt/prod'
    target.mkdir(parents=True)
    with open(target / 'run.xtc', 'wb') as handle:
        handle.truncate(int(2.5 * 1024 ** 3))
    (runs / job_id / 'logs').mkdir()
    (runs / job_id / 'logs/04_nvt.log').write_text(
        'Performance:     2124.666        0.011        0.163            9.259\n')

    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/runs')

    meta = page.locator(f'.job[data-id="{job_id}"] .job-meta')
    expect(meta).to_contain_text('2.5 GB of trajectories')
    expect(meta).to_contain_text('2124.7 ns/day')
    assert errors == [], errors


def test_view_run_sits_with_the_run_sections_rather_than_beside_the_title(dashboard, live_page):
    """The card's doors share one row: View run first, then the run's Stage settings.

    The link used to sit in the summary cell beside the title, which read as an ornament on the heading rather than
    as the door to the run's own panel; it keeps the deep link and the same card scope, so the handler needs no move.
    """
    runs = dashboard.coordinator.RUNS
    job_id = '00000000000e'
    dashboard.coordinator.database().replace([{
        'id': job_id, 'label': 'A run to open', 'detergent': 'DDM', 'method': 'fast_forward',
        'status': 'completed', 'stage': 'complete', 'created': '2026-09-16T10:00:00+00:00',
        'started_at': '2026-09-16T10:00:00+00:00', 'layout_version': 2}])
    (runs / job_id / 'logs').mkdir(parents=True)

    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/runs')

    card = page.locator(f'.job[data-id="{job_id}"]')
    link = card.locator('.run-resources .job-view-run')
    expect(link).to_have_text('View run')
    expect(link).to_have_attribute('href', f'/detergent-validation/run-view?run={job_id}')
    assert card.locator('.run-summary .job-view-run').count() == 0, 'the link is still riding the title'
    door = link.bounding_box()
    settings = card.locator('.run-resources .job-stage-settings > summary').bounding_box()
    assert abs(door['y'] - settings['y']) < 8, f'View run is not on the Stage settings row: {door} vs {settings}'
    assert door['x'] < settings['x'], 'View run is the first door, left of the sections'
    assert errors == [], errors


def test_the_run_list_stops_asking_while_hidden_and_refreshes_once_on_return(dashboard, live_page):
    """A hidden tab makes no run-list requests; coming back runs the same poll, so the progress line is not stale.

    Counted from the route rather than from a flag: a poll that keeps running behind a hidden tab is a request a
    reader cannot see the result of. The one request on return is the visibility listener's own `poll`, and with
    the seam at 500 ms a second request inside 200 ms would be a duplicate listener.
    """
    page, errors = live_page
    page.add_init_script('window.__runsPollMs = 500')
    hits = []
    page.route(re.compile(r'/api/jobs\?'),
               lambda route: (hits.append(route.request.url),
                              route.fulfill(json={'jobs': [], 'page': 1, 'total': 0, 'limit': 20}))[-1])
    page.goto(f'{live_page.base_url}/detergent-validation/runs')
    expect(page.locator('#runs')).to_be_visible()

    deadline = 10
    for _ in range(deadline * 20):
        if len(hits) >= 2:
            break
        page.wait_for_timeout(50)
    assert len(hits) >= 2, f'the run list never polled: {len(hits)}'

    page.evaluate("""() => {
      Object.defineProperty(document, 'hidden', {configurable: true, get: () => true});
      document.dispatchEvent(new Event('visibilitychange', {bubbles: true}));
    }""")
    page.wait_for_timeout(2000)          # four cadences at the seam, plus the one already pending
    settled = len(hits)
    page.wait_for_timeout(700)
    assert len(hits) == settled, f'the run list polled {len(hits) - settled} times with the tab hidden'

    page.evaluate("""() => {
      Object.defineProperty(document, 'hidden', {configurable: true, get: () => false});
      document.dispatchEvent(new Event('visibilitychange', {bubbles: true}));
    }""")
    for _ in range(20):
        if len(hits) > settled:
            break
        page.wait_for_timeout(25)
    assert len(hits) == settled + 1, f'the return caused {len(hits) - settled} requests, not one'
    page.wait_for_timeout(200)           # less than one 500 ms cadence
    assert len(hits) == settled + 1, 'the return refreshed twice'
    expect(page.locator('#connection')).to_contain_text('Updated')
    assert errors == [], errors


# --- the filter boxes -----------------------------------------------------------------------------------------

def _filter_jobs():
    """Four runs, one per facet the boxes offer, in a fixed order (`created` is written, not taken from the clock)."""
    return [
        {'id': 'f00000000001', 'label': 'aa only reference', 'detergent': 'DDM', 'method': 'gromacs',
         'status': 'completed', 'run_type': 'aa_only', 'stage': 'complete', 'created': '2026-10-01T10:00:00+00:00'},
        {'id': 'f00000000002', 'label': 'fitted CG run', 'detergent': 'DDM', 'method': 'fast_forward',
         'status': 'completed', 'run_type': 'cg', 'stage': 'complete', 'created': '2026-10-02T10:00:00+00:00'},
        {'id': 'f00000000003', 'label': 'second fitted run', 'detergent': 'LMNG', 'method': 'bartender',
         'status': 'failed', 'run_type': 'cg', 'stage': 'complete', 'created': '2026-10-03T10:00:00+00:00'},
        {'id': 'f00000000004', 'label': 'protein-detergent run', 'detergent': 'LMNG', 'method': 'gromacs',
         'status': 'completed', 'run_type': 'pdc', 'stage': 'complete', 'created': '2026-10-04T10:00:00+00:00'}]


def test_the_filter_boxes_narrow_the_request_and_the_poll_keeps_the_narrowing(dashboard, live_page):
    """Ticking a box re-reads the narrowed list at once, and the ten-second poll asks the same narrowed question.

    Asserted on the query string the server received, not only on the rows: a panel that filtered the fetched page
    in the browser would show the right rows and still page a hidden superset of every other run.
    """
    jobs = _filter_jobs()
    for job in jobs:
        job.update(started_at=job['created'], layout_version=2)
    dashboard.coordinator.database().replace(jobs)
    page, errors = live_page
    page.add_init_script('window.__runsPollMs = 400')
    requests = []
    page.on('request', lambda request: requests.append(request.url) if '/api/jobs?' in request.url else None)
    page.goto(f'{live_page.base_url}/detergent-validation/runs')

    def jobs_requests():
        return [url for url in requests if '/api/jobs?' in url]

    expect(page.locator('.job')).to_have_count(4)
    # The boxes come from the server's own vocabulary: a type a feature registers is offered without an engine edit.
    page.locator('#runs-filters > summary').click()
    expect(page.locator('#run-type-filters label')).to_have_count(4)
    expect(page.locator('#run-type-filters')).to_contain_text('Protein-detergent')
    expect(page.locator('#run-method-filters label')).to_have_count(3)

    page.locator('#run-type-filters input[value=cg]').check()
    expect(page.locator('.job')).to_have_count(2)
    assert 'run_type=cg' in jobs_requests()[-1], jobs_requests()[-1]
    expect(page.locator('#runs-filter-count')).to_have_text('1 active')

    # A second box in the same group is "either"; a box in another group narrows further.
    page.locator('#run-type-filters input[value=pdc]').check()
    expect(page.locator('.job')).to_have_count(3)
    latest = jobs_requests()[-1]
    assert 'run_type=cg' in latest and 'run_type=pdc' in latest, latest
    page.locator('#runs-filters input[name=status][value=failed]').check()
    expect(page.locator('.job')).to_have_count(1)
    assert 'status=failed' in jobs_requests()[-1], jobs_requests()[-1]
    expect(page.locator('#runs-filter-count')).to_have_text('3 active')
    expect(page.locator('#runs-filter-summary')).to_contain_text('Run type:')

    # The poll asks the same question: every list read after the tick still carries the narrowing.
    ticked = len(jobs_requests())
    page.wait_for_timeout(1200)
    later = jobs_requests()[ticked:]
    assert later, 'the run list never polled after the tick'
    assert all('run_type=cg' in url and 'status=failed' in url for url in later), later

    # A narrowing survives a reload -- and opens the panel, so the table is never narrowed without saying why.
    page.reload()
    expect(page.locator('.job')).to_have_count(1)
    expect(page.locator('#runs-filters')).to_have_attribute('open', '')
    expect(page.locator('#runs-filter-count')).to_have_text('3 active')
    assert errors == [], errors


def test_clearing_the_filters_restores_every_run_and_the_empty_state_says_what_happened(dashboard, live_page):
    """No runs yet and no runs match are different sentences: "mine are gone" is the wrong thing to read."""
    jobs = _filter_jobs()
    for job in jobs:
        job.update(started_at=job['created'], layout_version=2)
    dashboard.coordinator.database().replace(jobs)
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/runs')
    expect(page.locator('.job')).to_have_count(4)

    page.locator('#runs-filters > summary').click()
    page.locator('#runs-filters input[name=status][value=cancelled]').check()
    expect(page.locator('.job')).to_have_count(0)
    expect(page.locator('#empty-jobs')).to_be_visible()
    expect(page.locator('#empty-jobs')).to_contain_text('No runs match these filters.')
    expect(page.locator('#empty-jobs')).not_to_contain_text('No runs yet')
    page.locator('#empty-jobs button').click()
    expect(page.locator('.job')).to_have_count(4)
    expect(page.locator('#runs-filter-count')).to_be_hidden()
    expect(page.locator('#runs-filter-summary')).to_have_text('Nothing narrowed \u2014 every run is listed')
    for input_ in page.locator('#runs-filters input[type=checkbox]').all():
        assert not input_.is_checked(), 'a box stayed ticked after Clear filters'
    assert errors == [], errors


def test_a_failed_stage_shows_the_error_its_own_log_holds(dashboard, live_page):
    """The card's message is the stage's error block, not the wrapper's "returned non-zero exit status".

    Run `6ed68979edf0` died at CG simulation with `Command '['bash', ...]' returned non-zero exit status 1` on the
    card while its log said, below the grompp stanza, that GROMACS refused PME on the GPU for a reaction-field
    system. The record now carries the log's tail and the card shows it verbatim, so the line a reader can act on
    does not have to be the first one.
    """
    runs = dashboard.coordinator.RUNS
    job_id = '00000000000d'
    failure = ('CG simulation failed (exit 1):\n'
               'Inconsistency in user input:\n'
               'Cannot compute PME interactions on a GPU, because:\n'
               '  PME GPU does not support:\n'
               '    Systems that do not use PME for electrostatics.')
    dashboard.coordinator.database().replace([{
        'id': job_id, 'label': 'A stage that refused its settings', 'detergent': 'Glucose', 'method': 'cg',
        'status': 'failed', 'stage': 'CG simulation', 'created': '2026-11-16T15:20:00+00:00',
        'started_at': '2026-11-16T15:19:00+00:00', 'ended_at': '2026-11-16T15:20:00+00:00',
        'error': failure, 'layout_version': 2}])
    directory = runs / job_id
    (directory / 'logs').mkdir(parents=True)
    files.atomic_json(directory / 'manifest.json',
                      {'stage_plan': ['CG simulation'], 'stages': [{'name': 'CG simulation', 'status': 'failed'}]})

    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/runs')

    block = page.locator(f'.job[data-id="{job_id}"] .job-error')
    expect(block).to_contain_text('CG simulation failed (exit 1):')
    expect(block).to_contain_text('Cannot compute PME interactions on a GPU')
    expect(block).to_contain_text('Systems that do not use PME for electrostatics.')
    assert errors == [], errors

def test_the_diagnostics_disclosure_makes_the_traces_and_draws_them(dashboard, live_page):
    """A completed run's row offers its equilibration traces, beside Stage settings and not instead of it.

    The disclosure reads nothing until it is opened; an unpublished run gets one button that queues the analysis, and
    what the attempt publishes is drawn: one chart per term for the leg the record names, the leg's own source file,
    and the target line the run recorded. A CG run writes one equilibration file, so its record is one leg -- the panel
    draws the legs the record names rather than assuming three.
    """
    runs = dashboard.coordinator.RUNS
    job_id = '0000000000d1'
    stages = ['AA reference', 'trajectory mapping', 'CG topology (ff_inter)', 'CG simulation']
    dashboard.coordinator.database().replace([{
        'id': job_id, 'label': 'Completed CG run with one equilibration leg', 'detergent': 'DDM',
        'method': 'fast_forward', 'status': 'completed', 'stage': 'complete',
        'created': '2026-09-16T10:00:00+00:00', 'started_at': '2026-09-16T10:00:00+00:00', 'layout_version': 2}])
    directory = runs / job_id
    (directory / 'logs').mkdir(parents=True)
    files.atomic_json(directory / 'manifest.json',
                      {'stage_plan': stages,
                       'stages': [{'name': name, 'status': 'completed'} for name in stages]})
    record = {'legs': {'npt': {'x': [0.0, 100.0, 200.0], 'x_unit': 'time_ps', 'duration_ps': 200.0,
                                'source': '4_CG_sim/eq.edr',
                                'terms': {'Potential': {'values': [-410000.0, -411000.0, -411500.0],
                                                        'mean': -410833.3},
                                          'Temperature': {'values': [301.0, 299.0, 300.0], 'mean': 300.0},
                                          'Pressure': {'values': [2.0, -1.0, 1.0], 'mean': 0.67}}}},
              'terms': ['Potential', 'Temperature', 'Pressure'],
              'targets': {'Temperature': 300.0, 'Pressure': 1.0},
              'gmx_version': 'GROMACS version: 2026.3'}
    reads = {'get': 0}
    posted = []

    def traces(route):
        if route.request.method == 'POST':
            posted.append(route.request.url)
            route.fulfill(status=202, json={'id': 'task-d1', 'kind': 'equilibration-traces', 'status': 'running'})
            return
        reads['get'] += 1
        # The first read is the unpublished answer the panel offers its button on; every later one is the attempt
        # having published, which is what the panel polls for.
        if reads['get'] == 1:
            route.fulfill(json={'published': False, 'run_stopped': True})
        else:
            route.fulfill(json={**record, 'published': True})

    page, errors = live_page
    page.route(re.compile(rf'/api/jobs/{job_id}/equilibration-traces$'), traces)
    page.goto(f'{live_page.base_url}/detergent-validation/runs')

    card = page.locator(f'.job[data-id="{job_id}"]')
    expect(card.locator('.job-diagnostics')).to_be_visible()
    expect(card.locator('.job-stage-settings')).to_be_visible()
    assert reads['get'] == 0, 'the traces were read before the disclosure was opened'

    card.locator('.job-diagnostics > summary').click()
    button = card.locator('.run-equilibration-empty button')
    expect(button).to_be_visible()
    button.click()
    assert posted and posted[0].endswith(f'/api/jobs/{job_id}/equilibration-traces'), posted

    # Three charts for the one leg the record names, and no leg switch: the record decides how many legs exist.
    expect(card.locator('.run-equilibration-chart.js-plotly-plot')).to_have_count(3, timeout=30000)
    expect(card.locator('.run-equilibration-switch')).to_have_count(0)
    expect(card.locator('.run-equilibration-source')).to_contain_text('4_CG_sim/eq.edr')
    expect(card.locator('.run-equilibration-source')).to_contain_text('200.0 ps')
    # Each chart is announced with the quantity and the leg it came from, not just drawn.
    expect(card.locator('.run-equilibration-panel[data-term=Temperature] .run-equilibration-chart')).to_have_attribute(
        'aria-label', 'Temperature during the NPT leg')
    assert errors == [], errors
