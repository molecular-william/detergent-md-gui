"""The complex panel's own door to a run: its list arms the viewer, not only the test hook.

D4 of the audit: `setRun` had no production caller, so the system viewer was reachable only through
`window.pdcSetRun` -- a hook that exists for tests. A panel a reader cannot arm is not a panel, and the difference
between the defect and its fix is exactly which control this test uses: the list the panel fills itself.

The list is also asked to be the right list. The endpoint carries every run type, and a sugar run is not a complex's,
so a panel that offered it would be offering the wrong thing under the right heading.
"""
import re

from playwright.sync_api import expect

from . import panels

PDB = ('REMARK 950 TEST\n'
       'HETATM    1 B01  PRO A   1       0.000   0.000   0.000  1.00  0.00           C\n'
       'HETATM    2 DD0  DET A   1       1.000   0.000   0.000  1.00  0.00           C\n'
       'END\n')

# One complex and one molecule-only run, because the filter is half of what the control has to get right.
JOBS = {'jobs': [
    {'id': 'pdcfixture', 'run_type': 'pdc', 'molecule_id': 'DDM', 'status': 'completed'},
    {'id': 'sugarfixture', 'run_type': 'aa_cg', 'molecule_id': 'sucrose', 'status': 'completed'},
], 'total': 2, 'page': 1, 'limit': 100}


def serve(page, jobs=None):
    """Answer the list and the two endpoints behind it, so the panel is armed by something real."""
    # The three structure routes are Playwright globs and stay globs; only the JSON answer goes through the fixture.
    panels.serve_json(page, re.compile(r'/api/jobs'), JOBS if jobs is None else jobs)
    page.route('**/api/pdc/*/system.pdb', lambda route: route.fulfill(body=PDB, content_type='text/plain'))


def test_the_panel_lists_its_own_runs_and_the_list_arms_the_viewer(dashboard, live_page):
    page, errors = live_page
    serve(page)
    page.goto(f'{live_page.base_url}/protein-detergent/complexes')

    select = page.locator('#pdc-run')
    expect(select).to_be_visible(timeout=30000)
    # A placeholder and the one complex run -- and nothing of the sugar run, which is a different panel's subject.
    expect(select.locator('option')).to_have_count(2, timeout=30000)
    expect(select.locator('option').nth(1)).to_contain_text('pdcfixture')
    assert 'sugarfixture' not in select.inner_html()

    # The panel's own control, not `window.pdcSetRun`: this is the line D4 was about.
    select.select_option('pdcfixture')

    expect(page.locator('#pdc-view-basis')).to_contain_text('beads from the built system', timeout=30000)
    assert errors == []


def test_choosing_no_run_returns_the_panel_to_its_empty_state(dashboard, live_page):
    """The empty state is a state, not a blank: the viewer says what would appear there."""
    page, errors = live_page
    serve(page)
    page.goto(f'{live_page.base_url}/protein-detergent/complexes')

    select = page.locator('#pdc-run')
    expect(select.locator('option')).to_have_count(2, timeout=30000)
    select.select_option('pdcfixture')
    expect(page.locator('#pdc-view-basis')).to_contain_text('beads from the built system', timeout=30000)

    select.select_option('')
    expect(page.locator('#pdc-view-basis')).to_contain_text('appears here once a build has run')
    assert errors == []


def test_a_workspace_with_no_complex_run_says_so_instead_of_offering_an_empty_list(dashboard, live_page):
    page, errors = live_page
    serve(page, jobs={'jobs': [JOBS['jobs'][1]], 'total': 1, 'page': 1, 'limit': 100})
    page.goto(f'{live_page.base_url}/protein-detergent/complexes')

    select = page.locator('#pdc-run')
    expect(select.locator('option')).to_have_count(1, timeout=30000)
    expect(select.locator('option').first).to_have_text('No complex run yet')
    assert select.is_disabled()
    assert errors == []
