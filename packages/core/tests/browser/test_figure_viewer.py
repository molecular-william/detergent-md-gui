"""Browser proof for the Run view's figure viewer: tabs, zoom, display-only media, and the assessment diagnostics.

The viewer is the same `RunFigureViewer` the Runs page used; the panel it is mounted in is the Run view's Analysis
card, so every selector here is that card's, and the view is opened through the same `?run=` link the Runs table
offers. What the viewer itself does -- a tab per figure, a stored selection and zoom per run, an iframe for the one
interactive figure -- is what this file pins; `test_run_view_analysis_browser.py` pins the card around it.
"""
import json

from dashboard.models import mappings
from dashboard.models.mappings import context as mapping_context
from playwright.sync_api import expect

A_RUN = 'abcdef123456'
B_RUN = 'abcdef123457'
WORKSPACE = 'detergent-validation'

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="400" height="200">'
       '<circle cx="200" cy="100" r="90" fill="blue"/></svg>')
HTML = '<!doctype html><title>Surface comparison</title><h1>Interactive figure</h1>'


def seed(dashboard, *run_ids, figures=True):
    """Completed runs this test owns, with the files each holds. Nothing reads the developer's workspace."""
    runs = dashboard.coordinator.RUNS
    runs.mkdir(parents=True, exist_ok=True)
    context = mapping_context.build_context(dashboard.coordinator.ROOT / 'molecules', 'DDM')
    candidate = mappings.automatic_candidate(mappings.molecule(), 'DDM')
    candidate.update(molecule_id='DDM', molecule_snapshot=context['snapshot'])
    mappings.save_draft(candidate)
    dashboard.coordinator.database().replace([
        {'id': run_id, 'label': f'Figure run {run_id[-1]}', 'detergent': 'DDM', 'method': 'fast_forward',
         'status': 'completed', 'stage': 'complete', 'run_type': 'aa_cg',
         'created': dashboard.coordinator.now()} for run_id in run_ids])
    for run_id in run_ids:
        directory = runs / run_id
        directory.mkdir(parents=True, exist_ok=True)
        if figures:
            for name in ('alpha', 'beta'):
                (directory / f'{name}.svg').write_text(SVG)
            (directory / 'surface-comparison.html').write_text(HTML)
    return runs


def plots(page, side='A'):
    return page.locator(f'#run-view-analysis-plots-{side}')


def open_view(page, live_page, run_id=A_RUN, figures=4):
    page.goto(f'{live_page.base_url}/{WORKSPACE}/run-view?run={run_id}')
    expect(page.locator('#runview')).to_be_visible()
    expect(plots(page).locator('[role=tab]')).to_have_count(figures)
    return page


def test_run_figure_tabs_zoom_and_mapping_display(dashboard, live_page):
    seed(dashboard, A_RUN, B_RUN)
    page, errors = live_page

    open_view(page, live_page)

    expect(plots(page).locator('.figure-media')).to_have_count(1)
    expect(plots(page).get_by_role('tab', name='alpha', exact=True)).to_have_attribute('aria-selected', 'true')
    plots(page).get_by_role('button', name='Zoom in', exact=True).click()
    expect(plots(page).locator('.figure-zoom-level')).to_have_text('125%')
    assert plots(page).locator('.figure-media').evaluate('(el)=>el.getBoundingClientRect().width') \
        > plots(page).locator('.figure-viewport').evaluate('(el)=>el.clientWidth')
    plots(page).get_by_role('tab', name='beta', exact=True).click()
    expect(plots(page).locator('.figure-zoom-level')).to_have_text('100%')
    plots(page).get_by_role('tab', name='beta', exact=True).press('ArrowLeft')
    expect(plots(page).locator('.figure-zoom-level')).to_have_text('125%')
    # The selection and the zoom are remembered per run, so a reload comes back to the figure the reader left on.
    page.reload()
    expect(plots(page).locator('[role=tab]')).to_have_count(4)
    expect(plots(page).locator('.figure-zoom-level')).to_have_text('125%')
    # ArrowLeft from beta selected alpha, whose own 125% zoom was remembered.
    expect(plots(page).locator('.figure-source')).to_have_text('alpha.svg')
    plots(page).get_by_role('button', name='Fit / reset', exact=True).click()
    expect(plots(page).locator('.figure-zoom-level')).to_have_text('100%')
    plots(page).get_by_role('tab', name='surface comparison', exact=True).click()
    expect(plots(page).locator('iframe.figure-media')).to_have_attribute('sandbox', 'allow-scripts')
    expect(plots(page).frame_locator('iframe').get_by_role('heading')).to_have_text('Interactive figure')
    plots(page).get_by_role('button', name='Zoom in', exact=True).click()
    expect(plots(page).locator('.figure-zoom-level')).to_have_text('125%')
    assert '1.25' in plots(page).locator('iframe').evaluate('(el)=>el.style.transform')
    # The card is inside a monitor column, so it must not push the document sideways on a phone.
    page.set_viewport_size({'width': 390, 'height': 844})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    assert errors == [], errors


def test_analysis_display_preserves_missing_values_and_metadata(dashboard, live_page):
    runs = seed(dashboard, A_RUN, figures=False)
    assessment = runs / A_RUN / '5_assessment'
    assessment.mkdir()
    (assessment / 'distance_diagnostics.json').write_text(json.dumps({'pairs': [
        {'beads': ['B01', 'B02'], 'kind': 'physical', 'wasserstein_nm': {'raw_AA': 0, 'ring_expanded_AA': None}}
    ]}))
    metadata = runs / A_RUN / 'analysis' / 'plots'
    metadata.mkdir(parents=True)
    (metadata / 'score.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"/>')
    (metadata / 'analysis-metadata.json').write_text(json.dumps(
        {'title': 'Wasserstein distance', 'units_or_direction': 'nm; lower is better', 'legacy': False}))
    page, errors = live_page

    open_view(page, live_page, figures=2)

    expect(plots(page).locator('.figure-caption')).to_contain_text('Wasserstein distance')
    expect(plots(page).locator('.figure-caption')).to_contain_text('nm; lower is better')
    expect(page.locator('#run-view-analysis-diagnostics-A .distance-pair-table')).to_contain_text('0.000 nm')
    expect(page.locator('#run-view-analysis-diagnostics-A .distance-pair-table')).to_contain_text('n/a')
    assert errors == []


def test_the_diagnostics_box_shows_the_group_split_and_hides_the_legend_by_default(dashboard, live_page):
    """The run's numbers stay visible; the one-time explanation is a closed disclosure. The within-ring and
    between-ring/tail means are what the aggregate hides, and the pair table says which group a pair belongs to."""
    from dashboard.execution import workflow
    runs = seed(dashboard, A_RUN, figures=False)
    (runs / A_RUN / 'stages').mkdir(parents=True, exist_ok=True)
    assessment = workflow.stage_root(runs / A_RUN) / '5_assessment'
    assessment.mkdir(parents=True)
    (assessment / 'distance_diagnostics_stratified.json').write_text(json.dumps({
        'pairs': [
            {'beads': ['B01', 'B02'], 'kind': 'physical', 'group': 'within_ring',
             'wasserstein_nm': {'raw_AA': 0.03, 'ring_expanded_AA': 0.01}},
            {'beads': ['B02', 'B03'], 'kind': 'physical', 'group': 'between_rings_and_tail',
             'wasserstein_nm': {'raw_AA': 0.09, 'ring_expanded_AA': 0.1}},
            {'beads': ['B03', 'B04'], 'kind': 'constrained_physical', 'group': 'within_ring',
             'wasserstein_nm': {'raw_AA': 0.04, 'ring_expanded_AA': 0.012}},
            {'beads': ['B04', 'B05'], 'kind': 'virtual_site_diagnostic', 'group': 'between_rings_and_tail',
             'wasserstein_nm': {'raw_AA': 0.08, 'ring_expanded_AA': 0.1}},
        ],
        'stratified_means_nm': {
            'physical': {'raw_AA': 0.06, 'ring_expanded_AA': 0.055},
            'constrained_physical': {'raw_AA': 0.04, 'ring_expanded_AA': 0.012},
            'virtual_site_diagnostic': {'raw_AA': 0.08, 'ring_expanded_AA': 0.1}},
        'group_means_nm': {
            'within_ring': {'raw_AA': 0.035, 'ring_expanded_AA': 0.011},
            'between_rings_and_tail': {'raw_AA': 0.085, 'ring_expanded_AA': 0.1}},
        'pair_counts': {'physical': 2, 'constrained_physical': 1, 'virtual_site_diagnostic': 1},
    }))
    page, errors = live_page

    open_view(page, live_page, figures=1)

    diagnostics = page.locator('#run-view-analysis-diagnostics-A')
    box = diagnostics.locator('.distance-diagnostic')
    expect(box).to_contain_text('Lower is closer')
    expect(box).to_contain_text('4 pairs: 2 physical, 1 constrained, 1 virtual-site')
    expect(box).to_contain_text('Within-ring · expanded ring: 0.011 nm')
    expect(box).to_contain_text('Between rings/tail · expanded ring: 0.100 nm')

    help_details = box.locator('details.distance-diagnostic-help')
    assert help_details.evaluate('el => el.open') is False
    expect(help_details.locator('summary')).to_have_text('How to read this')
    help_details.locator('summary').click()
    expect(help_details).to_contain_text('Do not optimize them as ordinary bonded distances')

    table = box.locator('.distance-pair-table table')
    expect(table.locator('thead')).to_contain_text('Group')
    expect(table).to_contain_text('Within-ring')
    expect(table).to_contain_text('Between rings/tail')
    assert errors == []


def test_an_unclassified_diagnostic_artifact_says_so(dashboard, live_page):
    """A file written before per-pair `kind` must not have its pairs guessed into categories.

    The renderer used to default an unknown kind to 'Physical bead' and infer from a /VS$/ name test,
    which moved constrained pairs into the population that counts as evidence about the mapping. It
    now says unclassified and why, and the response's `legacy` flag is what tells it so.
    """
    from dashboard.execution import workflow
    runs = seed(dashboard, A_RUN, figures=False)
    (runs / A_RUN / 'stages').mkdir(parents=True, exist_ok=True)
    assessment = workflow.stage_root(runs / A_RUN) / '5_assessment'
    assessment.mkdir(parents=True)
    (assessment / 'distance_diagnostics.json').write_text(json.dumps({'pairs': [
        {'beads': ['B01', 'B02'], 'wasserstein_nm': {'raw_AA': 0.2, 'ring_expanded_AA': 0.3}}]}))
    page, errors = live_page

    open_view(page, live_page, figures=1)

    diagnostics = page.locator('#run-view-analysis-diagnostics-A')
    expect(diagnostics.locator('.distance-diagnostic')).to_contain_text('per-pair classification')
    expect(diagnostics.locator('.distance-pair-table')).to_contain_text('Unclassified (legacy artifact)')
    assert errors == []
