"""Browser proof for run-specific figure selection, zoom, and display-only beads."""
import json

from dashboard.models import mappings
from dashboard.models.mappings import context as mapping_context
from playwright.sync_api import expect


def test_run_figure_tabs_zoom_and_mapping_display(dashboard, live_page):
    runs = dashboard.coordinator.RUNS; runs.mkdir(parents=True, exist_ok=True)
    context = mapping_context.build_context(dashboard.coordinator.ROOT / 'molecules', 'DDM')
    candidate = mappings.automatic_candidate(mappings.molecule(), 'DDM')
    candidate.update(molecule_id='DDM', molecule_snapshot=context['snapshot'])
    mappings.save_draft(candidate)
    jobs=[{'id':jid,'label':f'Figure run {i}','detergent':'DDM','method':'fast_forward','status':'completed','stage':'complete','created':dashboard.coordinator.now()} for i,jid in enumerate(('abcdef123456','abcdef123457'))]
    dashboard.coordinator.database().replace(jobs)
    for job in jobs:
        directory=runs/job['id'];directory.mkdir()
        for name in ('alpha','beta'):
            (directory/(name+'.svg')).write_text('<svg xmlns="http://www.w3.org/2000/svg" width="400" height="200"><circle cx="200" cy="100" r="90" fill="blue"/></svg>')
        (directory/'surface-comparison.html').write_text('<!doctype html><title>Surface comparison</title><h1>Interactive figure</h1>')
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/runs')
    first=page.locator('.job[data-id=abcdef123456]');second=page.locator('.job[data-id=abcdef123457]')
    first.locator('.job-analysis summary').click()
    expect(first.locator('.figure-tabs [role=tab]')).to_have_count(3,timeout=15000)
    expect(first.locator('.figure-media')).to_have_count(1)
    expect(first.get_by_role('tab',name='alpha',exact=True)).to_have_attribute('aria-selected','true')
    first.get_by_role('button',name='Zoom in',exact=True).click()
    expect(first.locator('.figure-zoom-level')).to_have_text('125%')
    assert first.locator('.figure-media').evaluate('(el)=>el.getBoundingClientRect().width')>first.locator('.figure-viewport').evaluate('(el)=>el.clientWidth')
    first.get_by_role('tab',name='beta',exact=True).click()
    expect(first.locator('.figure-zoom-level')).to_have_text('100%')
    first.get_by_role('tab',name='beta',exact=True).press('ArrowLeft')
    expect(first.locator('.figure-zoom-level')).to_have_text('125%')
    # Refresh must preserve the DOM node, selection and viewport scroll.
    first.locator('.figure-media').evaluate('(el)=>window.originalFigure=el')
    first.locator('.figure-viewport').evaluate('(el)=>el.scrollLeft=40')
    first.locator('.job-analysis summary').click()
    with page.expect_response(lambda response: '/api/jobs/abcdef123456/figures?refresh=1' in response.url) as refreshed_figures:
        first.locator('.job-analysis summary').click()
    refreshed_figures.value.finished()
    assert first.locator('.figure-media').evaluate('(el)=>el===window.originalFigure')
    assert first.locator('.figure-viewport').evaluate('(el)=>el.scrollLeft')==40
    second.locator('.job-analysis summary').click()
    expect(second.locator('.figure-zoom-level')).to_have_text('100%')
    # Workspace navigation must ignore the nested figure tabs.
    page.get_by_role('tab',name='New run',exact=True).click();expect(page.locator('#new')).to_be_visible()
    page.get_by_role('tab',name='Runs',exact=True).click();expect(first.locator('.figure-zoom-level')).to_have_text('125%')
    page.reload();first=page.locator('.job[data-id=abcdef123456]')
    expect(first.locator('.figure-zoom-level')).to_have_text('125%')
    first.get_by_role('button',name='Fit / reset',exact=True).click();expect(first.locator('.figure-zoom-level')).to_have_text('100%')
    first.get_by_role('tab',name='surface comparison',exact=True).click()
    expect(first.locator('iframe.figure-media')).to_have_attribute('sandbox','allow-scripts')
    expect(first.frame_locator('iframe').get_by_role('heading')).to_have_text('Interactive figure')
    first.get_by_role('button',name='Zoom in',exact=True).click();expect(first.locator('.figure-zoom-level')).to_have_text('125%')
    assert '1.25' in first.locator('iframe').evaluate('(el)=>el.style.transform')
    page.get_by_role('tab',name='Bead Assignment',exact=True).click()
    editor=page.locator('#mappings')
    expect(editor.locator('#mapping-editor-name')).to_be_visible()
    editor.locator('#mapping-bead-rows tr').first.wait_for(timeout=30000)
    expect(editor.locator('#mapping-bead-rows tr')).not_to_have_count(0)
    expect(editor.locator('#save-mapping-editor')).to_be_disabled()
    expect(editor.locator('button', has_text='Export JSON')).to_have_count(0)
    expect(editor.locator('button', has_text='Download diagram')).to_have_count(0)
    page.locator('#tab-bonded').click()
    # The panel produces a parameterization now, and the old per-state "Fit bonded parameters" entry point must
    # never come back -- nor the reference-free draft button that used to sit beside the fit.
    expect(page.get_by_role('button', name='Fit this model')).to_be_visible()
    expect(page.get_by_role('button', name='Generate reference-informed draft')).to_have_count(0)
    expect(page.get_by_role('button', name='Fit bonded parameters')).to_have_count(0)
    page.get_by_role('tab',name='Bead Assignment',exact=True).click()
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.get_by_role('tab',name='Runs',exact=True).click()
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    assert errors==[]


def test_analysis_display_preserves_missing_values_and_metadata(dashboard, live_page):
    runs = dashboard.coordinator.RUNS; runs.mkdir(parents=True, exist_ok=True)
    job = {'id': 'abcdef123458', 'label': 'Metadata run', 'detergent': 'DDM', 'method': 'fast_forward', 'status': 'completed', 'stage': 'complete', 'created': dashboard.coordinator.now()}
    dashboard.coordinator.database().replace([job])
    directory = runs / job['id']; directory.mkdir()
    assessment = directory / '5_assessment'; assessment.mkdir()
    (assessment / 'distance_diagnostics.json').write_text(json.dumps({'pairs': [
        {'beads': ['B01', 'B02'], 'kind': 'physical', 'wasserstein_nm': {'raw_AA': 0, 'ring_expanded_AA': None}}
    ]}))
    metadata = directory / 'analysis' / 'plots'; metadata.mkdir(parents=True)
    (metadata / 'score.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"/>')
    (metadata / 'analysis-metadata.json').write_text(json.dumps({'title': 'Wasserstein distance', 'units_or_direction': 'nm; lower is better', 'legacy': False}))
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/runs')
    first = page.locator('.job').first
    first.locator('.job-analysis summary').click()
    expect(first.locator('.figure-caption')).to_contain_text('Wasserstein distance')
    expect(first.locator('.figure-caption')).to_contain_text('nm; lower is better')
    expect(first.locator('.distance-pair-table')).to_contain_text('0.000 nm')
    expect(first.locator('.distance-pair-table')).to_contain_text('n/a')
    assert errors == []


def test_an_unclassified_diagnostic_artifact_says_so(dashboard, live_page):
    """A file written before per-pair `kind` must not have its pairs guessed into categories.

    The renderer used to default an unknown kind to 'Physical bead' and infer from a /VS$/ name test,
    which moved constrained pairs into the population that counts as evidence about the mapping. It
    now says unclassified and why, and the response's `legacy` flag is what tells it so.
    """
    from dashboard.execution import workflow
    runs = dashboard.coordinator.RUNS; runs.mkdir(parents=True, exist_ok=True)
    job = {'id': 'abcdef123459', 'label': 'Legacy diagnostics', 'detergent': 'DDM',
           'method': 'fast_forward', 'status': 'completed', 'stage': 'complete',
           'created': dashboard.coordinator.now()}
    dashboard.coordinator.database().replace([job])
    (runs / job['id'] / 'stages').mkdir(parents=True, exist_ok=True)
    assessment = workflow.stage_root(runs / job['id']) / '5_assessment'; assessment.mkdir(parents=True)
    (assessment / 'distance_diagnostics.json').write_text(json.dumps({'pairs': [
        {'beads': ['B01', 'B02'], 'wasserstein_nm': {'raw_AA': 0.2, 'ring_expanded_AA': 0.3}}]}))
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/runs')
    first = page.locator('.job').first
    first.locator('.job-analysis summary').click()
    expect(first.locator('.distance-diagnostic')).to_contain_text('per-pair classification')
    expect(first.locator('.distance-pair-table')).to_contain_text('Unclassified (legacy artifact)')
    assert errors == []
