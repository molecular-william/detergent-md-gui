"""What the Mapping Validation panel renders, over a comparison the test built itself.

The panel is a reader: it shows the record the analysis published and nothing else. A fixture is therefore
enough to hold its rendering in place — the run selector, card 1's pairs, card 2's terms, card 3's per-bead
chart — without needing a coarse-grained run, which is what the earlier phase's tests were missing when the
panel turned out to be reading an endpoint that answered nothing.
"""
import json

from playwright.sync_api import expect

COMPARISON = {
    'schema_version': 1, 'comparison': 'AA vs CG', 'molecule': 'Sucrose', 'entry': 'SUCR',
    'sections': {'pairs': 'AA vs CG', 'terms': 'AA-mapped vs CG-simulated',
                 'displacement': 'AA vs CG, rigid-body fitted on the beads that own atoms'},
    'pairs': {'counts': {'pairs': 2, 'compared': 2, 'cg_outside_aa_range': 0}, 'rows': [
        {'pair': [[1, 'A'], [1, 'B']], 'compared': True, 'unconstrained': False,
         'aa': {'mean': 0.3155, 'std': 0.0063, 'stderr': 0.0002, 'count': 20001, 'min': 0.29, 'max': 0.34},
         'cg': {'mean': 0.3155, 'std': 0.0004, 'stderr': 0.0, 'count': 20001, 'min': 0.315, 'max': 0.316},
         'delta_pct': 0.0, 'inside_range': True, 'inside_spread': True,
         'reference_nm': 0.3050, 'delta_vs_reference_pct': 3.44},
        {'pair': [[2, 'A'], [2, 'B']], 'compared': True, 'unconstrained': False,
         'aa': {'mean': 0.3160, 'std': 0.0035, 'stderr': 0.0000, 'count': 20001, 'min': 0.30, 'max': 0.33},
         'cg': {'mean': 0.3160, 'std': 0.0004, 'stderr': 0.0, 'count': 20001, 'min': 0.315, 'max': 0.317},
         'delta_pct': 0.0, 'inside_range': True, 'inside_spread': True,
         'reference_nm': 0.3760, 'delta_vs_reference_pct': -15.96}]},
    'terms': [
        {'section': 'bonds', 'atoms': [0, 4], 'beads': '(1,A) - (2,A)', 'compared': True,
         'aa': {'mean': 0.30, 'std': 0.01, 'stderr': 0.0, 'count': 20001, 'min': 0.28, 'max': 0.32},
         'cg': {'mean': 0.30, 'std': 0.01, 'stderr': 0.0, 'count': 20001, 'min': 0.29, 'max': 0.31},
         'delta': -0.0, 'wasserstein': 0.002, 'overlap': 0.886, 'overlap_range': [0.2298, 0.3803]},
        {'section': 'angles', 'atoms': [0, 4, 5], 'beads': '(1,A) - (2,A) - (2,B)', 'compared': True,
         'aa': {'mean': 126.93, 'std': 5.09, 'stderr': 0.1, 'count': 20001, 'min': 100.0, 'max': 146.0},
         'cg': {'mean': 124.30, 'std': 10.46, 'stderr': 0.3, 'count': 20001, 'min': 92.0, 'max': 152.0},
         'delta': -2.63, 'wasserstein': 5.19, 'overlap': 0.622, 'overlap_range': [95.6513, 150.5906]}],
    'displacement': {'comparison': 'AA vs CG, rigid-body fitted on the beads that own atoms',
                     'rmsd_nm': 0.00431, 'max_nm': 0.00723, 'aa_frames': 20001, 'cg_frames': 20001,
                     'fit_beads': [[1, 'A'], [1, 'B']],
                     'per_bead': [{'bead': [1, 'A'], 'displacement_nm': 0.004},
                                  {'bead': [1, 'B'], 'displacement_nm': 0.019},
                                  {'bead': [1, 'VS'], 'displacement_nm': 0.001}]},
    'diagnostic_only': True, 'scientifically_validated': False,
    'interpretation': 'This compares our model with our own atomistic reference.',
}


def publish(dashboard, jid, comparison=None):
    """Leave behind what `analysis.worker` leaves behind for a completed comparison."""
    runs = dashboard.coordinator.RUNS; runs.mkdir(parents=True, exist_ok=True)
    dashboard.coordinator.database().replace([
        {'id': jid, 'label': 'Sucrose CG consumer', 'detergent': 'Sucrose', 'method': 'fast_forward',
         'run_type': 'aa_cg', 'profile': 'draft-smoke-reference', 'reference_run_id': '03875cf39790',
         'molecule_id': 'Sucrose', 'status': 'completed', 'stage': 'complete',
         'created': dashboard.coordinator.now()}])
    attempt = runs / jid / 'analyses/mapping-consistency/hash/attempt1'
    output = attempt / 'output/abc123/analysis'
    output.mkdir(parents=True)
    (output / 'mapping_consistency.json').write_text(json.dumps(comparison or COMPARISON))
    (attempt / 'result.json').write_text(json.dumps(
        {'result': {'artifact': 'analysis/mapping_consistency.json', 'comparison': 'AA vs CG'},
         'output_directory': 'output/abc123', 'wall_seconds': 13.3}))
    return attempt


def test_the_panel_shows_the_published_comparison_including_the_shape_card(dashboard, live_page):
    publish(dashboard, 'aa11bb22cc33')
    page, errors = live_page
    page.goto(f'{live_page.base_url}/#validation')

    expect(page.locator('#validation-run option')).to_have_count(1)
    page.wait_for_function("() => document.querySelectorAll('#validation-pair-rows tr').length === 2", timeout=30000)
    # Two different statements side by side, and the panel keeps them apart: the pair sits inside our own
    # observed range, and is 16% away from the published entry, which is carried as context and not as a verdict.
    row = page.evaluate("() => [...document.querySelectorAll('#validation-pair-rows tr')][1].textContent")
    assert 'inside the AA range' in row, row
    assert '(-16.0% context)' in row, row
    assert page.evaluate("() => document.querySelectorAll('#validation-term-rows tr').length") == 2
    assert page.evaluate("() => document.querySelector('#validation-pairs-badge').textContent") == \
        '0 of 2 pairs outside the AA observed range'

    # Card 3: the per-bead chart, in picometres, with the fitted beads distinguished from the rest.
    page.wait_for_function("() => { const host = document.querySelector('#validation-shape-plot');"
                           " return host && host.data && host.data.length === 1; }", timeout=30000)
    chart = page.evaluate("""() => { const host = document.querySelector('#validation-shape-plot');
      return {y: host.data[0].y, x: host.data[0].x, colors: host.data[0].marker.color}; }""")
    assert chart['x'] == ['(1,A)', '(1,B)', '(1,VS)']
    assert [round(value, 2) for value in chart['y']] == [4.0, 19.0, 1.0], 'nanometres shown as picometres'
    assert chart['colors'][0] == '#2455b0' and chart['colors'][1] == '#2455b0', 'the fitted beads are filled'
    assert chart['colors'][2] == '#b9c6d8', 'a bead the fit did not use is shown, and shown differently'
    assert 'rmsd 0.0043 nm' in page.locator('#validation-shape-detail').text_content()
    assert errors == []


def test_a_completed_coarse_grained_run_offers_the_panel_from_its_card(dashboard, live_page):
    """The run card's line: it opens the panel with that run already selected."""
    publish(dashboard, 'bb22cc33dd44')
    page, errors = live_page
    page.goto(live_page.base_url)
    page.wait_for_function("() => document.querySelectorAll('.job').length === 1", timeout=30000)

    page.locator('.job-validate').click()

    expect(page.locator('#tab-validation')).to_have_attribute('aria-selected', 'true')
    expect(page.locator('#validation-run')).to_have_value('bb22cc33dd44')
    page.wait_for_function("() => document.querySelectorAll('#validation-pair-rows tr').length === 2", timeout=30000)
    assert errors == []


def test_an_atomistic_only_run_does_not_offer_it(dashboard, live_page):
    publish(dashboard, 'cc33dd44ee55')
    database = dashboard.coordinator.database()
    database.replace([{**database.all()[0], 'run_type': 'aa_only'}])
    page, errors = live_page
    page.goto(live_page.base_url)
    page.wait_for_function("() => document.querySelectorAll('.job').length === 1", timeout=30000)

    assert page.locator('.job-validate').is_hidden(), 'there is no comparison to read from an atomistic-only run'
    assert errors == []


def test_a_run_with_no_published_comparison_says_so_in_the_panel(dashboard, live_page):
    publish(dashboard, 'dd44ee55ff66')
    (dashboard.coordinator.RUNS / 'dd44ee55ff66/analyses/mapping-consistency/hash/attempt1/result.json').unlink()
    page, errors = live_page
    page.goto(f'{live_page.base_url}/#validation')

    expect(page.locator('#validation-message')).to_be_visible(timeout=30000)
    expect(page.locator('#validation-message')).to_contain_text('No AA vs CG comparison')
    assert page.evaluate("() => document.querySelector('#validation-shape-plot').data === undefined")
    assert errors == []
