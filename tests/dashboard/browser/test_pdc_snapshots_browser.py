"""The snapshot series in the panel: the strip of moments, the picture, and the numbers of the one being drawn.

The panel is a reader of two endpoints, so a served index and a served PDB are enough to hold its rendering in
place: the labels, the pressed state, and the sentence that ties a picture to the verdict of its own moment. That
sentence is the point of the slice — a gallery whose frames do not say which verdict they belong to is decoration.
"""
from playwright.sync_api import expect

PDB = ('REMARK 950 TEST\n'
       'HETATM    1 B01  PRO A   1       0.000   0.000   0.000  1.00  0.00           C\n'
       'HETATM    2 DD0  DET A   1       1.000   0.000   0.000  1.00  0.00           C\n'
       'END\n')

INDEX = {
    'job_id': 'pdcfixture',
    'snapshots': [
        {'name': 'placement', 'time_ps': None, 'pdb': 'snapshots/placement.pdb', 'stage': '1_system',
         'atoms': 2, 'verdict': None},
        {'name': '2_assessment', 'time_ps': 100000.0, 'pdb': 'snapshots/2_assessment.pdb', 'stage': '2_assessment',
         'atoms': 2, 'verdict': {'verdict': False, 'largest_cluster': 3, 'aggregation_number': 8,
                                 'fraction_of_requested': 0.375, 'protein_contact_count': 0,
                                 'reasons': ['the largest cluster holds 3 of the requested 8 detergents']}},
    ],
}


def serve(page, index=None):
    """Answer the panel's two endpoints without a run behind them."""
    page.route('**/api/pdc/*/snapshots', lambda route: route.fulfill(json=INDEX if index is None else index))
    page.route('**/api/pdc/*/snapshots/**', lambda route: route.fulfill(body=PDB, content_type='text/plain'))
    page.route('**/api/pdc/*/system.pdb', lambda route: route.fulfill(body=PDB, content_type='text/plain'))


def test_the_panel_lists_the_series_and_draws_the_numbers_of_the_moment_it_shows(dashboard, live_page):
    page, errors = live_page
    serve(page)
    page.goto(f'{live_page.base_url}/protein-detergent/complexes')

    page.evaluate("window.pdcSetRun('pdcfixture')")

    buttons = page.locator('#pdc-snapshots button')
    expect(buttons).to_have_count(2, timeout=30000)
    expect(buttons.nth(0)).to_have_text('placement')
    expect(buttons.nth(1)).to_have_text('100 ns')
    # The placement has no verdict, and its own sentence says so rather than leaving a blank.
    assert 'not judged' in buttons.nth(0).get_attribute('title')
    assert 'before dynamics' in buttons.nth(0).get_attribute('title')

    buttons.nth(1).click()

    expect(buttons.nth(1)).to_have_attribute('aria-pressed', 'true')
    expect(page.locator('#pdc-snapshot-basis')).to_contain_text('micelle not formed')
    expect(page.locator('#pdc-snapshot-basis')).to_contain_text('largest cluster 3 of 8')
    expect(page.locator('#pdc-snapshot-basis')).to_contain_text('0 touching the protein')
    assert errors == []


def test_a_run_with_no_snapshots_says_so_instead_of_showing_an_empty_strip(dashboard, live_page):
    page, errors = live_page
    serve(page, index={'job_id': 'pdcfixture', 'snapshots': []})
    page.goto(f'{live_page.base_url}/protein-detergent/complexes')

    page.evaluate("window.pdcSetRun('pdcfixture')")

    expect(page.locator('#pdc-snapshot-basis')).to_have_text('This run has recorded no snapshots yet.',
                                                            timeout=30000)
    expect(page.locator('#pdc-snapshots button')).to_have_count(0)
    assert errors == []
