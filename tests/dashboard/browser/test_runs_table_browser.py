"""Runs layout and inline resources, against an isolated dashboard database."""
from playwright.sync_api import expect

from dashboard import files


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


def test_runs_views_checkpoints_and_inline_console(dashboard, live_page):
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
        (directory/'logs/console.log').write_text(''.join(f"{job['label']} line {i}\n" for i in range(100)))
        states = ['completed'] * 6 if job['status'] == 'completed' else ['reused', 'completed', 'completed', 'running', 'pending', 'pending'] if job['status'] == 'running' else ['completed', 'completed', 'failed', 'pending', 'pending', 'pending']
        files.atomic_json(directory/'manifest.json', {'stage_plan': stages, 'stages': [{'name': name, 'status': status} for name, status in zip(stages, states)]})
        (directory/'result.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="400" height="200"><rect width="400" height="200" fill="#edf3ff"/><text x="30" y="100">Reference comparison</text></svg>')
    page, errors = live_page
    url = f'{live_page.base_url}/detergent-validation/runs'
    page.goto(url)
    expect(page).to_have_title('Detergent MD · Laboratory')
    expect(page.locator('#jobs > tbody.job')).to_have_count(3)
    expect(page.locator('#jobs > thead')).to_contain_text('Molecule')
    expect(page.locator('.job-compare,.job-snapshots,#compare-runs')).to_have_count(0)
    expect(page.locator('#console-panel')).not_to_be_visible()
    complete = page.locator('.job[data-id="000000000001"]')
    active = page.locator('.job[data-id="000000000002"]')
    failed = page.locator('.job[data-id="000000000003"]')
    expect(complete.locator('.timeline-step[data-status=completed]')).to_have_count(6)
    expect(active.locator('[aria-current=step]')).to_have_attribute('aria-label','CG simulation: running')
    expect(active.locator('.timeline-step[data-status=reused]')).to_have_count(1)
    expect(failed.locator('.timeline-step[data-status=failed]')).to_have_count(1)
    assert active.locator('.workflow-timeline').bounding_box()['x'] > active.locator('.job-title').bounding_box()['x']
    for view in ('table', 'dense', 'grouped'):
        page.locator(f'[data-run-view={view}]').click()
        expect(page.locator('#runs')).to_have_attribute('data-view', view)
        for button in page.locator('[data-run-view]').all():
            expect(button).to_be_visible()
            assert button.evaluate('(el)=>getComputedStyle(el).color!==getComputedStyle(el).backgroundColor')
        page.screenshot(path=f'/tmp/detergent-runs-{view}.png', full_page=True)
    page.locator('[data-run-view=table]').click()
    complete.locator('.job-artifacts > summary').click()
    expect(complete.locator('.artifact-list')).to_contain_text('result.svg')
    complete.locator('.job-records > summary').click()
    expect(complete.locator('.job-stages')).to_contain_text('AA reference')
    complete.locator('.job-analysis > summary').click()
    expect(complete.locator('.figure-media')).to_be_visible()
    complete.locator('.job-console > summary').click()
    expect(complete.locator('#console-output')).to_contain_text('Completed control line 99')
    page.locator('#pause-console').click()
    log = runs/jobs[0]['id']/'logs/console.log'
    with log.open('a') as out: out.write('added while paused\n')
    page.evaluate('refreshConsole()')
    expect(page.locator('#console-output')).not_to_contain_text('added while paused')
    page.locator('#pause-console').click(); page.evaluate('refreshConsole()')
    expect(page.locator('#console-output')).to_contain_text('added while paused')
    page.locator('#copy-console').click()
    expect(page.locator('#console-status')).to_have_text('Visible log copied')
    with page.expect_download() as download: page.locator('#download-console').click()
    assert download.value.suggested_filename.endswith('.zip')
    active.locator('.job-console > summary').click()
    expect(active.locator('#console-output')).to_contain_text('Active screening line 99')
    expect(complete.locator('.job-console')).not_to_have_attribute('open','')
    page.evaluate('refreshJobs()')
    expect(active.locator('#console-output')).to_contain_text('Active screening line 99')
    page.locator('[data-run-view=dense]').click(); page.reload()
    expect(page.locator('#runs')).to_have_attribute('data-view', 'dense')
    expect(active.locator('#console-output')).to_contain_text('Active screening line 99')
    page.screenshot(path='/tmp/detergent-runs-expanded.png', full_page=True)
    # Filtering the current console out must park the viewer, not destroy it.
    page.locator('#run-search').fill('Completed control')
    expect(page.locator('.job')).to_have_count(1)
    expect(page.locator('#console-parking #console-panel')).to_have_count(1)
    page.locator('#run-search').fill('')
    expect(page.locator('.job')).to_have_count(3)
    active.locator('.job-console > summary').click() if not active.locator('.job-console').evaluate('(el)=>el.open') else None
    expect(active.locator('#console-output')).to_contain_text('Active screening line 99')
    page.set_viewport_size({'width':390, 'height':844})
    for view in ('table','dense','grouped'):
        page.locator(f'[data-run-view={view}]').click()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path='/tmp/detergent-runs-mobile.png', full_page=True)
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
        'started_at': '2026-10-20T12:00:00+00:00', 'layout_version': 2, 'run_type': 'aa_cg'}])
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
    # Two legs done and half of the third: 83% of the stage, said in the bar and in its text.
    expect(bar).to_have_attribute('aria-valuenow', '83')
    expect(bar).to_have_attribute('aria-valuetext', 'CG simulation · md 200/400 · 83%')
    expect(page.locator(f'.job[data-id="{job_id}"] .job-progress-text')).to_contain_text('leg 3 of 3')
    assert '83%' in bar.locator('.job-progress-fill').get_attribute('style'), \
        bar.locator('.job-progress-fill').get_attribute('style')
    assert errors == [], errors
