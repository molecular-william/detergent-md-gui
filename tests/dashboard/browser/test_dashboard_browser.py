"""Browser acceptance test. Requires installed Playwright + Chromium."""
import json

from playwright.sync_api import expect

from dashboard.models import mappings


def test_tab_switch_preserves_form_and_mapping_edits(dashboard, live_page):
    candidate = mappings.save_draft(mappings.automatic_candidate(mappings.molecule(), 'DDM'))
    job = {'id': '123456abcdef', 'detergent': 'DDM', 'method': 'fast_forward', 'status': 'failed', 'stage': 'AA reference', 'created': dashboard.coordinator.now(), 'error': 'Missing mapping'}
    dashboard.coordinator.database().replace([job])
    page, errors = live_page
    page.clock.install()
    page.goto(live_page.base_url)
    expect(page.locator('.job-title')).to_contain_text('DDM')
    page.locator('.job summary').nth(1).click()
    page.get_by_role('tab', name='New run', exact=True).click()
    page.locator('[name=label]').fill('My unsent run')
    page.locator('#method').select_option('bartender')
    dashboard.coordinator.database().update(job['id'], error='Updated failure explanation')
    page.get_by_role('tab', name='Runs', exact=True).click()
    expect(page.locator('.job-error')).to_have_text('Updated failure explanation')
    page.get_by_role('tab', name='New run', exact=True).click()
    expect(page.locator('[name=label]')).to_have_value('My unsent run')
    expect(page.locator('#method')).to_have_value('bartender')
    expect(page.locator('.job').first.locator('details').filter(has_text='Commands')).to_have_attribute('open', '')
    page.get_by_role('tab', name='Bead Assignment', exact=True).click()
    expect(page.locator('#mapping-editor-status')).to_contain_text('loaded')
    page.locator('#generate-automatic').click()
    page.locator('#mapping-bead-rows tr').first.wait_for(timeout=30000)
    expect(page.locator('#mapping-bead-rows tr')).not_to_have_count(0)
    page.locator('#mapping-editor-name').fill('My edited mapping')
    duplicate_atoms = ' '.join(map(str, candidate['beads'][0]['atoms'] + [candidate['beads'][1]['atoms'][0]]))
    page.locator('#mapping-bead-rows input[aria-label$=" atoms"]').first.fill(duplicate_atoms)
    page.clock.fast_forward(500)
    expect(page.locator('#mapping-validation-issues')).to_contain_text('Repeated atom assignments')
    page.get_by_role('tab', name='Runs', exact=True).click()
    expect(page.locator('.job').first.locator('details').filter(has_text='Commands')).to_have_attribute('open', '')
    page.get_by_role('tab', name='Bead Assignment', exact=True).click()
    expect(page.locator('#mapping-editor-name')).to_have_value('My edited mapping')
    assert errors == []


def test_clone_resume_and_analysis_controls(dashboard, live_page):
    from dashboard import files
    jobs = [{'id': f'{i:012x}', 'label': f'Run {i}', 'detergent': 'DDM', 'method': 'fast_forward', 'profile': 'draft-smoke', 'status': 'completed', 'created': dashboard.coordinator.now(), 'settings': {'temperature_k': 310}} for i in range(22)]
    dashboard.coordinator.database().replace(jobs)
    for job in jobs:
        run = dashboard.coordinator.run_path(job); run.mkdir(parents=True)
        files.atomic_json(run/'manifest.json', {'stages': [], 'input_snapshot_sha256': {'input.txt': 'hash'}})
        (run/'result.gro').write_text('artifact')
    newest = jobs[-1]
    worker = dashboard.coordinator.Worker(); dashboard.coordinator.ANALYSIS_WORKERS[(newest['id'], 'task')] = worker
    dashboard.coordinator.database().update(newest['id'], analyses=[{'id': 'task', 'kind': 'stability', 'status': 'running', 'directory': 'analyses/stability/test'}])
    page, errors = live_page
    page.goto(live_page.base_url)
    first = page.locator('.job').first
    first.locator('.job-analysis summary').click()
    first.get_by_role('button', name='Cancel analysis', exact=True).click()
    expect(first.locator('.analysis-tasks')).to_contain_text('cancelling')
    assert worker.cancel.is_set(); dashboard.coordinator.ANALYSIS_WORKERS.clear()
    first.locator('.job-clone').click()
    expect(page.locator('#new')).to_be_visible()
    expect(page.locator('[name=temperature_k]')).to_have_value('310')
    expect(page.locator('[name=clone_of]')).to_have_value(newest['id'])
    page.get_by_role('tab', name='Runs', exact=True).click()
    expect(first.locator('.resume-stage')).to_have_value('AA reference')
    assert errors == []


def test_delete_mapping_removes_the_saved_candidate(dashboard, live_page):
    """Delete mapping acts on the edited candidate; Save in-place overwrites instead of adding one.

    This test was skipped for a while with the reason that the filter does not list a candidate saved directly
    through the store. That was true, and the reason named the fix: save through the page instead. The filter is
    filled from the server's catalogue for *this molecule's snapshot*, and the page's own save appends the option it
    just created -- a candidate written straight into the store is scoped differently and appears in neither list.

    The recogniser is answered from the test rather than waited on, for the reason the sibling test records: it runs
    in the server, so under load the rows arrive after the assertion has given up. What this test is about is which
    button is enabled when, not how fast the recogniser is.
    """
    page, errors = live_page
    page.on('dialog', lambda dialog: dialog.accept())
    page.goto(f'{live_page.base_url}/detergent-validation/bead-assignment')
    page.get_by_role('tab', name='Bead Assignment', exact=True).click()
    page.route('**/api/mappings/automatic/preview',
               lambda route: route.fulfill(status=200, content_type='application/json',
                                           body=json.dumps({'available': True,
                                                            'candidate': mappings.automatic_candidate(
                                                                mappings.molecule(), 'DDM')})))

    select = page.locator('#mapping-candidate-filter')
    # The editor wires its controls when the panel mounts, and the rows follow the *editor*, not the click: a click
    # that lands before the mount produces no rows at all, which is how this test failed after 16 s under two workers
    # while passing in 8 s alone. Wait for the readiness line its sibling test waits on. The recogniser is already
    # answered from the test above, so what is left to wait for is the panel being ready -- and a longer timeout is
    # not what was missing.
    expect(page.locator('#mapping-editor-status')).to_contain_text('loaded')
    # A fresh workspace has one option and no saved candidate: the placeholder. Nothing to delete yet.
    expect(select.locator('option')).to_have_count(1)
    expect(page.locator('#delete-mapping')).to_be_disabled(), 'a local draft has nothing to delete'

    page.locator('#generate-automatic').click()
    page.locator('#mapping-bead-rows tr').first.wait_for(timeout=15000)
    page.locator('#save-mapping-editor').click()

    expect(select.locator('option')).to_have_count(2)
    saved_file = select.input_value()
    option = select.locator(f'option[value="{saved_file}"]')
    expect(option).to_have_count(1)

    # Selecting it is what the operator does; the assertion below depends on the change handler having run.
    select.select_option(saved_file)
    expect(page.locator('#delete-mapping')).to_be_enabled()
    expect(page.locator('#save-mapping-inplace')).to_be_enabled()

    page.locator('#save-mapping-inplace').click()
    # One candidate before and after: an in-place save must not mint a second file.
    expect(select.locator('option')).to_have_count(2)
    expect(option).to_have_count(1)

    page.locator('#delete-mapping').click()
    expect(option).to_have_count(0)
    expect(select.locator('option')).to_have_count(1)
    assert errors == []


def test_the_candidate_warning_line_stays_hidden_when_nothing_needs_correcting(live_page):
    """The warning element exists for every candidate and only shows when the candidate carries one."""
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/bead-assignment')
    expect(page.locator('#mapping-editor-warnings')).to_have_count(1)
    expect(page.locator('#mapping-editor-warnings')).to_be_hidden()
    page.locator('#generate-automatic').click()
    expect(page.locator('#mapping-editor-warnings')).to_be_hidden()
    assert errors == []


def test_the_selectors_sit_above_the_diagram_side_by_side(live_page):
    """Both comboboxes, and the selection controls, moved into the diagram's column above the drawing.

    Measured rather than asserted from markup: a layout change is only real if the boxes moved.
    """
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/bead-assignment')
    page.get_by_role('tab', name='Bead Assignment', exact=True).click()
    expect(page.locator('#mapping-editor-overlay3d')).to_be_visible()

    molecule = page.locator('#mapping-molecule').bounding_box()
    candidate = page.locator('#mapping-candidate-filter').bounding_box()
    count = page.locator('#mapping-selection-count').bounding_box()
    group = page.locator('#group-into-bead').bounding_box()
    diagram = page.locator('#mapping-editor-overlay3d').bounding_box()

    assert abs(molecule['y'] - candidate['y']) < 4, 'the two comboboxes share a row'
    assert molecule['x'] < candidate['x'], 'Molecule then Candidate, left to right'
    assert molecule['width'] <= 0.55 * diagram['width'], 'and each is narrower than the column'
    for label, box in (('molecule', molecule), ('candidate', candidate),
                       ('count', count), ('Group into bead', group)):
        assert box['y'] < diagram['y'], f'{label} sits above the diagram'
    # The count and its buttons share the row; the button box starts a little higher because of its
    # padding, so compare with a tolerance rather than ordering their tops.
    assert abs(count['y'] - group['y']) < 24, 'the count and its buttons share a row'
    assert errors == []


def test_mapping_editor_clear_all_removes_local_assignments(live_page):
    page = live_page.page
    page.goto(f'{live_page.base_url}/detergent-validation/bead-assignment')
    page.get_by_role('tab', name='Bead Assignment', exact=True).click()
    # The recogniser runs in the server and is this tier's only load-sensitive step: 60 s covered moderate
    # contention, and under two workers it still timed out while passing in 4 s in isolation. The comment that used
    # to sit here proposed answering the call from the test instead of waiting longer, and that is what this does --
    # the candidate is the same one the recogniser would return, computed in Python through the same code path the
    # server uses, so the editor receives what it would have received without the wait. What the test is about is
    # that *Clear all* empties the editor, not that the recogniser is fast.
    candidate = mappings.automatic_candidate(mappings.molecule(), 'DDM')
    page.route('**/api/mappings/automatic/preview',
               lambda route: route.fulfill(status=200, content_type='application/json',
                                           body=json.dumps({'available': True, 'candidate': candidate})))
    # The editor wires its controls when the panel mounts, so a click that lands first is a click into nothing and
    # the rows it would have produced never appear. Wait for the readiness line its sibling test also waits on rather
    # than for the rows: under two workers this was the tier's one failing test at HEAD as well, and a longer timeout
    # is not what is missing.
    expect(page.locator('#mapping-editor-status')).to_contain_text('loaded')
    page.locator('#generate-automatic').click()
    page.locator('#mapping-bead-rows tr').first.wait_for(timeout=15000)
    expect(page.locator('#mapping-bead-rows tr')).not_to_have_count(0)
    page.on('dialog', lambda dialog: dialog.accept())
    page.locator('#clear-all-mapping').click()
    expect(page.locator('#mapping-bead-rows tr')).to_have_count(0)
    page.unroute('**/api/mappings/automatic/preview')


def test_mapping_editor_disables_save_for_an_identical_saved_mapping(live_page):
    page = live_page.page
    page.goto(f'{live_page.base_url}/detergent-validation/bead-assignment')
    page.get_by_role('tab', name='Bead Assignment', exact=True).click()
    expect(page.locator('#mapping-editor-status')).to_contain_text('loaded')
    page.locator('#generate-automatic').click()
    page.locator('#mapping-bead-rows tr').first.wait_for(timeout=30000)
    expect(page.locator('#mapping-bead-rows tr')).not_to_have_count(0)
    expect(page.locator('#save-mapping-editor')).to_be_enabled()
    page.locator('#save-mapping-editor').click()
    expect(page.locator('#save-mapping-editor')).to_be_disabled()
