"""Runs layout and inline resources, against an isolated dashboard database."""
from playwright.sync_api import expect

from dashboard import files


def test_runs_views_checkpoints_and_inline_console(dashboard, live_page):
    runs = dashboard.coordinator.RUNS
    stages = ['AA reference', 'trajectory mapping (ff_map)', 'CG topology (ff_inter)', 'CG simulation', 'CG assessment (ff_assess)', 'SASA analysis']
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
    url = f'{live_page.base_url}/#runs'
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
