"""What the Run view Analysis card draws for a mapping's own records, over a comparison the test built itself.

The Mapping Validation tab used to be the reader; its three per-run sections now live in each Run view monitor's
Analysis card. These tests therefore open the run already selected (`?run=`), click the section they are about and
read the same published records the panel read -- pairs and the per-bead chart, the terms and the two cross-checks,
the envelope and the bead overlap -- plus the two states a run can be in: no comparison published, and no comparison
defined for the run type.
"""
import json

from playwright.sync_api import expect

from tests.harness import browser
from tests.harness.validation_fixtures import publish, publish_cross_check, publish_mapping, publish_overlap, publish_surfaces

CARD = '#run-view-analysis-A'
SECOND = '#run-view-analysis-B'


DIHEDRAL_FIT = {
    'molecule': 'DDM', 'criterion': 'bic', 'temperature': 303.15,
    'temperature_source': "the analysis default; the run's own fit temperature was not staged",
    'frames_measured': 20001, 'frames_in_trajectory': 20001,
    'ours_from': '3_initial_CG/DDM_ff_inter.itp', 'ours_provenance': 'the Fast_Forward fit',
    'measured_from': '2_mapping/mapped.xtc',
    'rows': [
        {'beads': ['B01', 'B02', 'B03', 'B04'],
         'ours': {'phase_deg': 180.0, 'force_constant_kj_mol': 3.5, 'multiplicity': 2},
         'fit': {'terms': 3, 'dihedrals': [], 'residual_rms_kj_mol': 0.42,
                 'dominant_multiplicity': 2, 'dominant_force_constant_kj_mol': 2.9},
         'multiplicities_agree': True},
        {'beads': ['B05', 'B06', 'B07', 'B08'],
         'ours': {'phase_deg': 0.0, 'force_constant_kj_mol': 1.2, 'multiplicity': 3},
         'fit': {'terms': 4, 'dihedrals': [], 'residual_rms_kj_mol': 0.31,
                 'dominant_multiplicity': 2, 'dominant_force_constant_kj_mol': 1.05},
         'multiplicities_agree': False},
    ],
    'unmeasured': [{'beads': ['B09', 'B10', 'B11', 'B01'], 'phase_deg': 0.0, 'force_constant': 0.5,
                    'multiplicity': 1,
                    'reason': 'a distribution needs at least two frames to be a distribution'}],
    'disagreements': [['B05', 'B06', 'B07', 'B08']],
    'limitations': ["The fitted phase is in the convention this measurement uses, and the run topology's is GROMACS's.",
                    'A proper dihedral is fitted on its own torsion distribution.'],
    'scientifically_validated': False,
}


def publish_dihedral_fit(dashboard, jid):
    """Leave behind what `analysis.worker` leaves behind for a completed dihedral fit."""
    attempt = dashboard.coordinator.RUNS / jid / 'analyses/dihedral-fit/hash/attempt1'
    output = attempt / 'output/abc123'
    output.mkdir(parents=True)
    (output / 'dihedral-fit.json').write_text(json.dumps(DIHEDRAL_FIT))
    (attempt / 'result.json').write_text(json.dumps(
        {'result': DIHEDRAL_FIT, 'output_directory': 'output/abc123', 'wall_seconds': 12.0}))
    return attempt


def _ff_distribution(shift=0.0):
    return {'x': [0.2, 0.3, 0.4], 'density': [0.5 + shift, 1.0 + shift, 0.25 + shift]}


FF_INTERACTIONS = {
    'schema_version': 1, 'scope': 'bonded-terms', 'available': True, 'source': 'consumed',
    'reference': {'from': 'parameterization store', 'revision': 1, 'engine': 'fast-forward'},
    'simulated': {'from': 'stage 5 ff_assess'},
    'metrics': {'hellinger': 'Fast-Forward distance', 'overlap': 'the dashboard coefficient'},
    'overall': '0.238 ± 0.0208',
    'terms': [
        {'name': 'B01_B02', 'section': 'bonds', 'beads': ['B01', 'B02'],
         'label': '(1,A) - (2,A)', 'unit': 'nm', 'hellinger': 0.180, 'ff_score': 0.170,
         'reference': _ff_distribution(0.1), 'simulated': _ff_distribution()},
        {'name': 'B01_B02_B03', 'section': 'angles', 'beads': ['B01', 'B02', 'B03'],
         'label': '(1,A) - (2,A) - (2,B)', 'unit': 'degrees', 'hellinger': 0.440, 'ff_score': 0.410,
         'reference': {'x': [90, 120, 150], 'density': [0.2, 0.6, 0.2]},
         'simulated': {'x': [90, 120, 150], 'density': [0.3, 0.5, 0.2]}},
        {'name': 'B01_B02_B03_B04', 'section': 'dihedrals', 'beads': ['B01', 'B02', 'B03', 'B04'],
         'label': '(1,A) - (1,B) - (2,A) - (2,B)', 'unit': 'degrees', 'hellinger': 0.210, 'ff_score': 0.190,
         'reference': {'x': [150, 180, 210], 'density': [0.2, 0.7, 0.1]},
         'simulated': {'x': [150, 180, 210], 'density': [0.1, 0.8, 0.1]}},
    ],
    'scientifically_validated': False,
}


def publish_ff(dashboard, jid, record=None):
    """Leave behind what `analysis.worker` leaves behind for a completed ff-interactions analysis."""
    attempt = dashboard.coordinator.RUNS / jid / 'analyses/ff-interactions/hash/attempt1'
    output = attempt / 'output/abc123'
    output.mkdir(parents=True)
    published = record if record is not None else FF_INTERACTIONS
    (output / 'ff-interactions.json').write_text(json.dumps(published))
    (attempt / 'result.json').write_text(json.dumps(
        {'result': published, 'output_directory': 'output/abc123', 'wall_seconds': 0.8}))
    return attempt


# -------------------------------------------------------------------------------------------------- the tabs

def test_the_section_tabs_are_the_registered_sections_in_order(dashboard, live_page):
    """The engine draws Figures first, then the feature's sections in their registered order."""
    publish(dashboard, 'aa11bb22cc33')
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/run-view?run=aa11bb22cc33')
    root = page.locator(CARD)
    expect(root.locator('.analysis-views button').first).to_be_visible(timeout=30000)

    labels = root.locator('.analysis-views button').all_text_contents()
    assert labels == ['Figures', 'Geometry', 'Bonded terms', 'Shape and volume'], labels
    expect(root.locator('.analysis-pane[data-section="figures"]')).to_be_visible()
    expect(root.locator('.analysis-pane[data-section="mapping-geometry"]')).to_be_hidden()
    root.locator('.analysis-views button[data-section="mapping-geometry"]').click()
    expect(root.locator('.analysis-views button[data-section="mapping-geometry"]')).to_have_text('Geometry (2 pairs)')
    assert errors == []


# ----------------------------------------------------------------------------------------------------- geometry

def test_geometry_shows_the_published_pairs_and_the_per_bead_chart(dashboard, live_page):
    publish(dashboard, 'aa11bb22cc33')
    page, errors = live_page
    pane = browser.open_run_section(page, live_page.base_url, 'aa11bb22cc33', 'mapping-geometry')

    expect(pane.locator('.rvm-measure')).to_have_count(2)
    second = pane.locator('.rvm-measure').nth(1).text_content()
    # Two different statements side by side: the pair sits inside our own observed range, and is 16% away from the
    # published entry, which is carried as context and not as a verdict.
    assert 'inside the AA range' in second, second
    assert '(-16.0% context)' in second, second
    expect(pane.locator('.rvm-badge').filter(has_text='0 of 2 pairs outside the AA observed range')).to_have_count(1)

    browser.wait_for_traces(page, f'{CARD} .analysis-pane[data-section="mapping-geometry"] .rvm-chart', 1)
    chart = page.evaluate("""() => { const host = document.querySelector(
      '#run-view-analysis-A .analysis-pane[data-section="mapping-geometry"] .rvm-chart');
      return {y: host.data[0].y, x: host.data[0].x, colors: host.data[0].marker.color}; }""")
    assert chart['x'] == ['(1,A)', '(1,B)', '(1,VS)']
    assert [round(value, 2) for value in chart['y']] == [4.0, 19.0, 1.0], 'nanometres shown as picometres'
    assert chart['colors'][0] == '#2455b0' and chart['colors'][1] == '#2455b0', 'the fitted beads are filled'
    assert chart['colors'][2] == '#b9c6d8', 'a bead the fit did not use is shown, and shown differently'
    assert 'rmsd 0.0043 nm' in ' '.join(pane.text_content().split())
    assert errors == []


def test_a_run_with_no_published_comparison_says_so_in_every_mapping_section(dashboard, live_page):
    publish(dashboard, 'dd44ee55ff66')
    (dashboard.coordinator.RUNS / 'dd44ee55ff66/analyses/mapping-consistency/hash/attempt1/result.json').unlink()
    page, errors = live_page
    pane = browser.open_run_section(page, live_page.base_url, 'dd44ee55ff66', 'mapping-geometry')

    expect(pane.locator('.hint').first).to_contain_text('No AA vs CG comparison', timeout=30000)
    assert page.evaluate("() => !document.querySelector('#run-view-analysis-A "
                         ".analysis-pane[data-section=\"mapping-geometry\"] .rvm-chart')")
    assert errors == []


def test_the_missing_comparison_offers_a_button_that_queues_it(dashboard, live_page):
    """The Analysis card is the only place the comparison can be started; the request names no snapshot."""
    publish(dashboard, 'dd44ee55ff66')
    (dashboard.coordinator.RUNS / 'dd44ee55ff66/analyses/mapping-consistency/hash/attempt1/result.json').unlink()
    page, errors = live_page
    posted = []

    def hold(route):
        if route.request.method == 'POST':
            posted.append(route.request.post_data)
            route.fulfill(status=202, content_type='application/json', body=json.dumps(
                {'id': 'queued1', 'kind': 'mapping-consistency', 'status': 'queued',
                 'created_at': '2026-11-06T00:00:00+00:00'}))
        else:
            route.continue_()

    page.route('**/api/jobs/dd44ee55ff66/mapping-consistency', hold)
    pane = browser.open_run_section(page, live_page.base_url, 'dd44ee55ff66', 'mapping-geometry')

    button = pane.get_by_role('button', name='Calculate the comparison')
    expect(button).to_be_visible(timeout=30000)
    button.click()
    expect(page.locator('#run-view-analysis-note-A')).to_contain_text('Mapping comparison queued.', timeout=30000)
    assert posted == ['{}'], posted
    assert errors == []


def test_every_completed_run_gets_the_card_and_a_run_with_no_comparison_gets_the_reason(dashboard, live_page):
    """An atomistic-only run keeps Figures and the task list, and states why the mapping sections are absent."""
    publish(dashboard, 'cc33dd44ee55')
    database = dashboard.coordinator.database()
    database.replace([{**database.all()[0], 'run_type': 'aa_only'}])
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/run-view?run=cc33dd44ee55')
    root = page.locator(CARD)

    expect(root.locator('.analysis-notice')).to_be_visible(timeout=30000)
    expect(root.locator('.analysis-notice')).to_contain_text('Mapping comparison is not defined for this run')
    expect(root.locator('.analysis-views')).to_be_hidden()
    expect(root.locator('.analysis-pane[data-section="figures"]')).to_be_visible()
    assert errors == []


# ------------------------------------------------------------------------------------------------- bonded terms

def test_bonded_terms_and_the_two_cross_checks_render(dashboard, live_page):
    publish(dashboard, 'bb22cc33dd44')
    publish_cross_check(dashboard, 'bb22cc33dd44')
    publish_dihedral_fit(dashboard, 'bb22cc33dd44')
    page, errors = live_page
    pane = browser.open_run_section(page, live_page.base_url, 'bb22cc33dd44', 'mapping-bonded')

    # Bonds and Angles are one disclosure each, both closed by default, and the Bonded pane counts both.
    bonds = pane.locator('details.rvm-term-group', has_text='Bonds (1)')
    group = pane.locator('details.rvm-term-group', has_text='Angles (1)')
    expect(bonds).to_have_count(1)
    expect(group).to_have_count(1)
    expect(bonds.locator('summary')).to_contain_text('Bonds (1)')
    expect(bonds.locator('.rvm-measure')).to_have_count(1)
    assert 'bond' in bonds.text_content(), bonds.text_content()
    expect(group.locator('summary')).to_contain_text('Angles (1)')
    expect(group.locator('.rvm-measure')).to_have_count(1)
    assert 'angle' in group.text_content(), group.text_content()

    subs = pane.locator('.rvm-sub')
    cross = subs.nth(0)
    expect(cross.locator('.rvm-measure')).to_have_count(3)
    note = ' '.join(cross.locator('.hint').nth(0).text_content().split())
    assert 'the Fast_Forward fit' in note, note
    assert 'Threshold 10000' in note and '303.15 K' in note, note
    assert '1 of 2 terms where the two sides disagree: B01–B02' in note, note
    assert 'Not scientifically validated' in note, note
    rows = cross.locator('.rvm-measure')
    first = rows.nth(0).text_content()
    assert 'B01–B11' in first and '0.431 nm' in first and '2716.9' in first, first
    assert '0.424 nm' in first and '2424.4' in first and 'both springs' in first, first
    assert '-0.0070 nm' in first, first
    second = rows.nth(1).text_content()
    assert 'B01–B02' in second and 'constraint' in second, second
    assert 'we write rigid, the estimate reads a spring' in second, second
    third = rows.nth(2).text_content()
    assert 'not measured' in third and 'spread of zero' in third, third
    assert 'angle' in cross.locator('.hint').nth(1).text_content()

    dihedral = subs.nth(1)
    expect(dihedral.locator('.rvm-measure')).to_have_count(3)
    fit_note = ' '.join(dihedral.locator('.hint').nth(0).text_content().split())
    assert 'multiplicity chosen by BIC' in fit_note, fit_note
    assert '1 of 2 terms where the criterion chooses a different multiplicity' in fit_note, fit_note
    fit_row = dihedral.locator('.rvm-measure').nth(1).text_content()
    assert 'B05–B06–B07–B08' in fit_row and 'we write 3-fold, the criterion chooses 2-fold' in fit_row, fit_row
    assert errors == []


def test_angle_rows_collapse_and_are_present_when_reopened(dashboard, live_page):
    """The Angles group is one disclosure, closed by default; opening it brings back the same rows.

    Bonds is its own closed group, so opening Angles neither folds nor opens the rows it does not own, and the
    group starts closed so the usually-more-numerous angle rows do not bury the terms beside them.
    """
    publish(dashboard, 'bb22cc33dd44')
    page, errors = live_page
    pane = browser.open_run_section(page, live_page.base_url, 'bb22cc33dd44', 'mapping-bonded')

    bonds = pane.locator('details.rvm-term-group', has_text='Bonds (1)')
    group = pane.locator('details.rvm-term-group', has_text='Angles (1)')
    expect(group).to_have_count(1)
    summary = group.locator('summary')
    expect(summary).to_contain_text('Angles (1)')
    expect(group).not_to_have_attribute('open', '')
    expect(group.locator('.rvm-measure')).to_be_hidden()
    assert 'angle' in group.text_content(), group.text_content()
    expect(bonds).not_to_have_attribute('open', '')

    summary.click()
    expect(group).to_have_attribute('open', '')
    expect(group.locator('.rvm-measure')).to_be_visible()
    # The bond row is not in the group: opening angles must not fold the terms it does not own.
    expect(bonds).not_to_have_attribute('open', '')
    expect(bonds.locator('.rvm-measure')).to_be_hidden()

    summary.click()
    expect(group).not_to_have_attribute('open', '')
    expect(group.locator('.rvm-measure')).to_be_hidden()
    assert errors == []


def test_a_focused_angle_opens_its_collapsed_group(dashboard, live_page):
    """A map attention item that names an angle must reveal the row it points at, not select a hidden one."""
    publish(dashboard, 'aa11bb22cc33', comparison=MAP_COMPARISON)
    publish_mapping(dashboard, 'aa11bb22cc33')
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/run-view?run=aa11bb22cc33')
    root = page.locator(CARD)
    expect(root.locator('.analysis-views button').first).to_be_visible(timeout=30000)
    root.locator('.analysis-views button[data-section="mapping-bonded"]').click()
    wait_for_map(page, meta='term')
    host = map_host(page)
    group = root.locator('details.rvm-term-group', has_text='Angles (1)')
    expect(group).not_to_have_attribute('open', '')
    expect(group.locator('.rvm-measure')).to_be_hidden()

    # Weakest first: the dihedral (0.21) leads, the angle (0.44) is the second item and lives in the group.
    host.locator('.rvm-attention li').nth(1).locator('button').click()
    expect(group).to_have_attribute('open', '')
    expect(root.locator('.analysis-pane[data-section="mapping-bonded"] [data-item="term:1"]')) \
        .to_have_attribute('aria-selected', 'true')
    assert errors == []


def test_a_run_with_no_cross_check_or_dihedral_fit_says_so_and_lists_nothing(dashboard, live_page):
    publish(dashboard, 'bb22cc33dd44')
    page, errors = live_page
    pane = browser.open_run_section(page, live_page.base_url, 'bb22cc33dd44', 'mapping-bonded')

    subs = pane.locator('.rvm-sub')
    expect(subs.nth(0).locator('.rvm-measure')).to_have_count(0)
    expect(subs.nth(0).locator('.hint').nth(0)).to_contain_text('queued by hand', timeout=30000)
    expect(subs.nth(1).locator('.rvm-measure')).to_have_count(0)
    expect(subs.nth(1).locator('.hint').nth(0)).to_contain_text('queued by hand')
    assert errors == []


def test_clicking_a_bonded_term_shows_its_ff_distribution_and_both_metrics(dashboard, live_page):
    publish(dashboard, 'aa11bb22cc33', comparison=MAP_COMPARISON)
    publish_mapping(dashboard, 'aa11bb22cc33')
    publish_ff(dashboard, 'aa11bb22cc33')
    page, errors = live_page
    pane = browser.open_run_section(page, live_page.base_url, 'aa11bb22cc33', 'mapping-bonded')

    # Bonds start closed, so the reader opens the group before selecting one of its rows.
    pane.locator('details.rvm-term-group', has_text='Bonds (1)').locator('summary').click()
    row = pane.locator('[data-item="term:0"]')
    row.click()
    panel = pane.locator('[data-ff-panel]')
    expect(panel).to_contain_text('FF Hellinger distance')
    expect(panel).to_contain_text('0.180')
    expect(panel).to_contain_text('FF score')
    expect(panel).to_contain_text('Dashboard overlap coefficient')
    expect(panel).to_contain_text('0.820')
    expect(panel).to_contain_text('consumed · parameterization store')
    expect(row).to_have_attribute('aria-selected', 'true')
    browser.wait_for_traces(page, f'{CARD} .analysis-pane[data-section="mapping-bonded"] .rvm-ff-chart', 2)
    names = panel.locator('.rvm-ff-chart').evaluate('el => el.data.map(trace => trace.name)')
    assert names == ['reference', 'simulated'], names
    # The two metrics are named separately; neither is presented as the other.
    assert 'Histogram intersection' in panel.text_content()
    assert errors == []


def test_the_map_term_line_selects_the_same_ff_distribution(dashboard, live_page):
    publish(dashboard, 'aa11bb22cc33', comparison=MAP_COMPARISON)
    publish_mapping(dashboard, 'aa11bb22cc33')
    publish_ff(dashboard, 'aa11bb22cc33')
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/run-view?run=aa11bb22cc33')
    root = page.locator(CARD)
    expect(root.locator('.analysis-views button').first).to_be_visible(timeout=30000)
    root.locator('.analysis-views button[data-section="mapping-bonded"]').click()
    wait_for_map(page, meta='term')
    expect(root.locator('.analysis-pane[data-section="mapping-bonded"] [data-ff-panel]')).to_be_visible(timeout=30000)
    host = map_host(page)

    # Weakest first: the dihedral (0.21) leads and is term:2 in the published comparison.
    host.locator('.rvm-attention li').nth(0).locator('button').click()
    expect(root.locator('.analysis-pane[data-section="mapping-bonded"] [data-item="term:2"]')) \
        .to_have_attribute('aria-selected', 'true')
    panel = root.locator('[data-ff-panel]')
    expect(panel).to_contain_text('dihedrals')
    expect(panel).to_contain_text('0.210')
    assert errors == []


def test_a_term_without_a_published_ff_record_says_so(dashboard, live_page):
    publish(dashboard, 'aa11bb22cc33', comparison=MAP_COMPARISON)
    publish_mapping(dashboard, 'aa11bb22cc33')
    page, errors = live_page
    pane = browser.open_run_section(page, live_page.base_url, 'aa11bb22cc33', 'mapping-bonded')

    panel = pane.locator('[data-ff-panel]')
    expect(panel).to_contain_text('No Fast-Forward interaction record has been published', timeout=30000)
    expect(panel.get_by_role('button', name='Calculate Fast-Forward distributions')).to_be_visible()
    pane.locator('details.rvm-term-group', has_text='Bonds (1)').locator('summary').click()
    pane.locator('[data-item="term:0"]').click()
    expect(panel).to_contain_text('No Fast-Forward interaction record has been published')
    assert errors == []


def test_a_term_with_no_reference_side_names_the_absent_side(dashboard, live_page):
    record = json.loads(json.dumps(FF_INTERACTIONS))
    record['terms'][0].pop('reference')
    record['terms'][0]['reference_missing'] = 'the consumed revision recorded no reference histogram for this term'
    publish(dashboard, 'aa11bb22cc33', comparison=MAP_COMPARISON)
    publish_mapping(dashboard, 'aa11bb22cc33')
    publish_ff(dashboard, 'aa11bb22cc33', record)
    page, errors = live_page
    pane = browser.open_run_section(page, live_page.base_url, 'aa11bb22cc33', 'mapping-bonded')

    pane.locator('details.rvm-term-group', has_text='Bonds (1)').locator('summary').click()
    pane.locator('[data-item="term:0"]').click()
    panel = pane.locator('[data-ff-panel]')
    expect(panel).to_contain_text('No reference distribution for this term')
    expect(panel).to_contain_text('One side alone is not a comparison')
    expect(panel.locator('.rvm-ff-chart')).to_have_count(0)
    assert errors == []


# --------------------------------------------------------------------------------------------- shape and volume

def test_the_envelope_analysis_is_drawn_with_its_statistics_and_its_own_figure(dashboard, live_page):
    publish(dashboard, 'bb22cc33dd44')
    publish_surfaces(dashboard, 'bb22cc33dd44')
    page, errors = live_page
    pane = browser.open_run_section(page, live_page.base_url, 'bb22cc33dd44', 'mapping-shape')

    envelope = pane.locator('[data-shape="surfaces"]')
    # Three columns, not five: frames and duration belong to the trajectory, and the probe is in the note above.
    assert envelope.locator('.rvm-table thead th').all_text_contents() == ['Model', 'Mean SASA', 'SD']
    expect(envelope.locator('.rvm-table tbody tr')).to_have_count(2, timeout=30000)
    rows = envelope.locator('.rvm-table tbody tr')
    assert rows.nth(0).locator('th').text_content() == 'AA'
    assert [value.strip() for value in rows.nth(0).locator('td').all_text_contents()] == ['5.816', '0.077']
    assert rows.nth(1).locator('th').text_content() == 'Simulated CG this run'
    assert [value.strip() for value in rows.nth(1).locator('td').all_text_contents()] == ['5.599', '0.174']
    # One scene with both models: two meshes and two marker traces, the checkboxes above are its legend.
    expect(envelope.locator('.rvm-surface-plot')).to_have_count(1)
    expect(envelope.locator('.rvm-checks input')).to_have_count(2)
    assert envelope.locator('.rvm-checks input').evaluate_all('els => els.map(el => el.checked)') == [True, True]
    browser.wait_for_traces(page, f'{CARD} .analysis-pane[data-section="mapping-shape"] .rvm-surface-plot', 4)
    traces = envelope.locator('.rvm-surface-plot').evaluate(
        'el => el.data.map(trace => ({type: trace.type, x: trace.x, y: trace.y}))')
    assert [trace['type'] for trace in traces] == ['mesh3d', 'scatter3d', 'mesh3d', 'scatter3d'], traces
    # The real vertices from the analysis's own pair JSON: a triangle and two markers on each model.
    assert traces[0]['x'] == [0.0, 0.2, 0.0] and traces[0]['y'] == [0.0, 0.0, 0.2], traces[0]
    assert traces[1]['x'] == [0.05, 0.1] and traces[1]['y'] == [0.02, 0.03], traces[1]
    assert traces[2]['x'] == [0.0, 0.25, 0.0] and traces[2]['y'] == [0.0, 0.0, 0.25], traces[2]
    assert traces[3]['x'] == [0.06, 0.12] and traces[3]['y'] == [0.03, 0.04], traces[3]

    # The 2D series reads the two sasa.xvg files the analysis recorded: both models, one point per frame.
    browser.wait_for_traces(page, f'{CARD} .analysis-pane[data-section="mapping-shape"] .rvm-sasa-chart', 2)
    traces = envelope.locator('.rvm-sasa-chart').evaluate(
        'el => el.data.map(trace => ({name: trace.name, x: trace.x, y: trace.y}))')
    assert [trace['name'] for trace in traces] == ['AA', 'Simulated CG'], traces
    assert all(len(trace['x']) == 3 for trace in traces), traces
    assert traces[0]['x'][0] == 0 and abs(traces[0]['y'][0] - 5.8) < 1e-9, traces
    note = envelope.locator('.hint').nth(0).text_content()
    assert 'SAS' in note and 'not a re-entrant solvent-excluded surface (SES)' in note, note
    assert 'Not scientifically validated' in note, note
    expect(envelope.locator('iframe')).to_have_count(0)
    assert errors == []


def test_the_surface_models_block_names_the_four_models_and_marks_this_run(dashboard, live_page):
    """What the four SASA models are, which one is this run's own data, and the AA run they are measured against.

    The block is plain and always visible above the scene, not a disclosure: a reader who never clicks still learns
    that three of the four rows are AA-derived context. It lists all four models even when a row is not published --
    a mapping that declares no rings publishes no "Mapped ring-scaled" row, and its line says why.
    """
    publish(dashboard, 'bb22cc33dd44')
    publish_surfaces(dashboard, 'bb22cc33dd44')
    page, errors = live_page
    pane = browser.open_run_section(page, live_page.base_url, 'bb22cc33dd44', 'mapping-shape')

    envelope = pane.locator('[data-shape="surfaces"]')
    block = envelope.locator('.rvm-models')
    expect(block).to_be_visible(timeout=30000)
    assert block.evaluate('el => !el.closest("details")')

    # The AA source run id is in this section's identity line, as the payload carries it.
    identity = pane.locator('.rvm-identity').first.text_content()
    assert 'AA source' in identity and '03875cf39790' in identity, identity

    # The producer's own row names, in its order: the block does not rename a row.
    assert [name.strip() for name in block.locator('dt').all_text_contents()] == [
        'AA', 'Mapped raw', 'Mapped ring-scaled', 'Simulated CG this run']
    # The lead defines SASA before it is used, and says outright that only one model is this run's data.
    lead = ' '.join(block.locator('.lead').text_content().split())
    assert 'SASA (solvent-accessible surface area)' in lead, lead
    assert 'only one is this run’s own data' in lead, lead

    # One plain line per model, each carrying the phrase a reword would drop.
    definitions = [' '.join(text.split()) for text in block.locator('dd').all_text_contents()]
    assert len(definitions) == 4
    for text, phrase in zip(definitions, [
            'atomistic reference',
            'average position of the atoms it owns',
            'ring dilation',
            'this run’s own coarse-grained trajectory']):
        assert phrase in text, text
    # A ringless mapping publishes no ring-scaled row and the line says why it is absent.
    assert 'absent when the mapping declares no rings' in definitions[2], definitions[2]
    assert envelope.locator('.rvm-table tbody th', has_text='Mapped ring-scaled').count() == 0

    # Plain block directly under the heading and above the scene's checkboxes, not a disclosure.
    heading_box = envelope.locator('h4').first.bounding_box()
    block_box = block.bounding_box()
    checks_box = envelope.locator('.rvm-checks').bounding_box()
    assert heading_box['y'] + heading_box['height'] <= block_box['y']
    assert block_box['y'] + block_box['height'] <= checks_box['y']

    # The marker is the Simulated CG row's alone; the block's Simulated CG term carries it too, and nothing else.
    rows = envelope.locator('.rvm-table tbody tr')
    expect(rows).to_have_count(2)
    assert rows.nth(0).locator('.rvm-own').count() == 0
    assert rows.nth(1).locator('.rvm-own').text_content() == 'this run'
    assert envelope.locator('.rvm-own').count() == 2
    assert 'AA-derived context' in ' '.join(envelope.locator('.rvm-surface-caption').text_content().split())
    assert 'None of these numbers is an experiment' in envelope.locator('.rvm-surface-caption').text_content()

    # The block is presentation only: the AA-vs-CG pair scene still draws from the published pair JSON.
    expect(envelope.locator('.rvm-surface-plot')).to_have_count(1)
    expect(envelope.locator('.rvm-checks input')).to_have_count(2)
    browser.wait_for_traces(page, f'{CARD} .analysis-pane[data-section="mapping-shape"] .rvm-surface-plot', 4)
    assert envelope.locator('.rvm-surface-plot').evaluate(
        'el => el.data.map(trace => trace.type)') == ['mesh3d', 'scatter3d', 'mesh3d', 'scatter3d']
    assert errors == []


def test_a_run_with_no_envelope_analysis_says_so_and_frames_nothing(dashboard, live_page):
    publish(dashboard, 'bb22cc33dd44')
    page, errors = live_page
    pane = browser.open_run_section(page, live_page.base_url, 'bb22cc33dd44', 'mapping-shape')

    envelope = pane.locator('[data-shape="surfaces"]')
    expect(envelope.locator('.hint').nth(0)).to_contain_text('queued by hand', timeout=30000)
    assert 'solvent-accessible surfaces analysis has been published' in envelope.locator('.hint').nth(0).text_content().lower()
    expect(envelope.locator('.rvm-table')).to_have_count(0)
    expect(envelope.locator('.rvm-surface-view')).to_have_count(0)
    expect(envelope.locator('.rvm-surface-plot')).to_have_count(0)
    expect(envelope.locator('.rvm-sasa-chart')).to_have_count(0)
    expect(envelope.locator('iframe')).to_have_count(0)
    expect(envelope.get_by_role('button', name='Calculate surfaces')).to_be_visible()
    assert errors == []


def test_an_older_surfaces_attempt_without_the_pair_falls_back_to_its_figure(dashboard, live_page):
    """An attempt published before the AA/CG pair existed still shows its own figure and the SASA series.

    The pair is data on the newest attempts; an older attempt must not read as a broken one, and its own figure is
    still the AA-vs-variant comparison it published.
    """
    publish(dashboard, 'bb22cc33dd44')
    attempt = publish_surfaces(dashboard, 'bb22cc33dd44')
    metadata_path = attempt / 'output/abc123/analysis/surfaces/metadata.json'
    metadata = json.loads(metadata_path.read_text())
    metadata.pop('aa_cg_comparison', None)
    metadata_path.write_text(json.dumps(metadata))
    (attempt / 'output/abc123/analysis/surfaces/surface-comparison-aa-cg.json').unlink()
    page, errors = live_page
    pane = browser.open_run_section(page, live_page.base_url, 'bb22cc33dd44', 'mapping-shape')

    envelope = pane.locator('[data-shape="surfaces"]')
    expect(envelope.locator('iframe')).to_have_count(1, timeout=30000)
    assert 'surface-comparison.html' in envelope.locator('iframe').get_attribute('src')
    assert 'predates the AA vs Simulated CG pair' in envelope.text_content()
    expect(envelope.get_by_role('button', name='Recalculate surfaces')).to_be_visible()
    browser.wait_for_traces(page, f'{CARD} .analysis-pane[data-section="mapping-shape"] .rvm-sasa-chart', 2)
    assert errors == []


def test_the_bead_overlap_analysis_is_drawn_with_its_numbers_and_its_own_figure(dashboard, live_page):
    publish(dashboard, 'bb22cc33dd44')
    publish_overlap(dashboard, 'bb22cc33dd44')
    page, errors = live_page
    pane = browser.open_run_section(page, live_page.base_url, 'bb22cc33dd44', 'mapping-shape')

    overlap = pane.locator('.rvm-sub').nth(1)
    expect(overlap.locator('iframe')).to_have_count(1, timeout=30000)
    frame = overlap.locator('iframe').get_attribute('src')
    assert frame.startswith('/api/jobs/bb22cc33dd44/artifacts/analyses/overlap/'), frame
    assert frame.endswith('overlap.html?inline=1'), frame
    note = overlap.locator('.hint').nth(0).text_content()
    detail = overlap.locator('.hint').nth(1).text_content()
    assert 'DDM' in note and 'Not scientifically validated' in note, note
    assert '3 bead pairs' in detail and '0.523' in detail, detail
    assert 'B01 → B03 at 0.310' in detail, detail
    assert 'B02 → B03 at 0.440' in detail, detail
    assert 'nothing here says anything about the bonds between residues' in detail, detail
    assert errors == []


def test_a_run_with_no_bead_overlap_analysis_says_so_and_frames_nothing(dashboard, live_page):
    publish(dashboard, 'bb22cc33dd44')
    page, errors = live_page
    pane = browser.open_run_section(page, live_page.base_url, 'bb22cc33dd44', 'mapping-shape')

    overlap = pane.locator('.rvm-sub').nth(1)
    expect(overlap.locator('.hint').nth(0)).to_contain_text('queued by hand', timeout=30000)
    assert 'bead pair by bead pair' in overlap.locator('.hint').nth(0).text_content()
    expect(overlap.locator('iframe')).to_have_count(0)
    expect(overlap.locator('.hint')).to_have_count(1)
    assert errors == []


def test_a_published_analysis_whose_figure_is_gone_still_states_its_numbers(dashboard, live_page):
    publish(dashboard, 'bb22cc33dd44')
    attempt = publish_overlap(dashboard, 'bb22cc33dd44')
    (attempt / 'output/abc123/overlap.html').unlink()
    page, errors = live_page
    pane = browser.open_run_section(page, live_page.base_url, 'bb22cc33dd44', 'mapping-shape')

    overlap = pane.locator('.rvm-sub').nth(1)
    expect(overlap.locator('.hint').nth(0)).to_contain_text('no longer on disk', timeout=30000)
    detail = overlap.locator('.hint').nth(1).text_content()
    assert '3 bead pairs' in detail and '0.523' in detail, detail
    expect(overlap.locator('iframe')).to_have_count(0)
    assert errors == []


# ------------------------------------------------------------------------------------------------- two monitors

def test_the_two_monitors_keep_their_own_section(dashboard, live_page):
    publish(dashboard, 'aa11bb22cc33')
    database = dashboard.coordinator.database()
    first = {**dict(database.all()[0]), 'molecule_id': 'Run A'}
    publish(dashboard, 'bb22cc33dd44')
    second = {**dict(database.all()[0]), 'molecule_id': 'Run B'}
    database.replace([first, second])
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/run-view?run=aa11bb22cc33')

    left = page.locator(CARD)
    right = page.locator(SECOND)
    expect(left.locator('.analysis-views button').first).to_be_visible(timeout=30000)
    expect(right.locator('.analysis-views button').first).to_be_visible(timeout=30000)

    left.locator('.analysis-views button[data-section="mapping-geometry"]').click()
    expect(left.locator('.analysis-pane[data-section="mapping-geometry"] .rvm-measure')).to_have_count(2)
    expect(right.locator('.analysis-pane[data-section="mapping-geometry"]')).to_be_hidden()

    right.locator('.analysis-views button[data-section="mapping-geometry"]').click()
    expect(right.locator('.analysis-pane[data-section="mapping-geometry"] .rvm-measure')).to_have_count(2)
    assert 'Run A' in left.locator('.analysis-pane[data-section="mapping-geometry"] .rvm-identity').text_content()
    assert 'Run B' in right.locator('.analysis-pane[data-section="mapping-geometry"] .rvm-identity').text_content()
    assert errors == []


# -------------------------------------------------------------------------------------------- the retired panel

def test_the_mapping_validation_page_is_gone(dashboard, live_page):
    page, errors = live_page
    response = page.goto(f'{live_page.base_url}/detergent-validation/mapping-validation')
    assert response.status == 404, response.status
    assert errors == []


def test_the_run_card_keeps_only_the_view_run_door(dashboard, live_page):
    publish(dashboard, 'bb22cc33dd44')
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/runs')
    expect(page.locator('.job')).to_have_count(1, timeout=30000)

    expect(page.locator('.job-validate')).to_have_count(0)
    expect(page.locator('.job .job-view-run')).to_be_visible()
    assert errors == []


# ------------------------------------------------------------------------------------------ the comparison map
#
# One scene above the three mapping sections. The record is the test's own: three pairs (one inside the AA range,
# one outside, one unconstrained) and three terms at 0.82, 0.44 and 0.21 overlap, so each perspective has a worst
# item to rank. The mapping is written where the run keeps it: `stages/2_mapping/model.json` and `mapped.gro`.

MAP_PLOT = f'{CARD} .analysis-map .rvm-map-plot'


def _dist(mean, spread):
    return {'mean': mean, 'std': spread, 'stderr': 0.0, 'count': 20001,
            'min': mean - 2 * spread, 'max': mean + 2 * spread}


MAP_COMPARISON = {
    'schema_version': 1, 'comparison': 'AA vs CG', 'molecule': 'Sucrose', 'entry': 'SUCR',
    'sections': {'pairs': 'AA vs CG', 'terms': 'AA-mapped vs CG-simulated',
                 'displacement': 'AA vs CG, rigid-body fitted on the beads that own atoms'},
    'pairs': {'counts': {'pairs': 3, 'compared': 3, 'cg_outside_aa_range': 1}, 'rows': [
        {'pair': [[1, 'A'], [1, 'B']], 'compared': True, 'unconstrained': False,
         'aa': _dist(0.3155, 0.0063), 'cg': _dist(0.3193, 0.0004), 'delta_pct': 1.2,
         'inside_range': True, 'inside_spread': True,
         'reference_nm': 0.3050, 'delta_vs_reference_pct': 3.4},
        {'pair': [[2, 'A'], [2, 'B']], 'compared': True, 'unconstrained': False,
         'aa': _dist(0.3011, 0.0035), 'cg': _dist(0.3147, 0.0004), 'delta_pct': 4.5,
         'inside_range': False, 'inside_spread': False,
         'reference_nm': 0.2960, 'delta_vs_reference_pct': 1.7},
        {'pair': [[1, 'A'], [2, 'A']], 'compared': True, 'unconstrained': True,
         'aa': _dist(0.4120, 0.0028), 'cg': _dist(0.4090, 0.0000), 'delta_pct': -0.7,
         'inside_range': True, 'inside_spread': True,
         'reference_nm': None, 'delta_vs_reference_pct': None}]},
    'terms': [
        {'section': 'bonds', 'atoms': [0, 3], 'beads': '(1,A) - (2,A)', 'compared': True,
         'aa': _dist(0.300, 0.010), 'cg': _dist(0.310, 0.012), 'delta': 0.01,
         'wasserstein': 0.001, 'overlap': 0.82, 'overlap_range': [0.23, 0.38]},
        {'section': 'angles', 'atoms': [0, 3, 4], 'beads': '(1,A) - (2,A) - (2,B)', 'compared': True,
         'aa': _dist(126.93, 5.09), 'cg': _dist(124.30, 10.46), 'delta': -2.63,
         'wasserstein': 5.19, 'overlap': 0.44, 'overlap_range': [95.65, 150.59]},
        {'section': 'dihedrals', 'atoms': [0, 1, 3, 4], 'beads': '(1,A) - (1,B) - (2,A) - (2,B)',
         'compared': True, 'aa': _dist(180.0, 4.0), 'cg': _dist(176.0, 8.0), 'delta': -4.0,
         'wasserstein': 8.0, 'overlap': 0.21, 'overlap_range': [150.0, 200.0]}],
    'displacement': {'comparison': 'AA vs CG, rigid-body fitted on the beads that own atoms',
                     'rmsd_nm': 0.0043, 'max_nm': 0.019, 'aa_frames': 20001, 'cg_frames': 20001,
                     'fit_beads': [[1, 'A'], [1, 'B']],
                     'per_bead': [{'bead': [1, 'A'], 'displacement_nm': 0.004},
                                  {'bead': [1, 'B'], 'displacement_nm': 0.019},
                                  {'bead': [1, 'VS'], 'displacement_nm': 0.001},
                                  {'bead': [2, 'A'], 'displacement_nm': 0.007},
                                  {'bead': [2, 'B'], 'displacement_nm': 0.012}]},
    'diagnostic_only': True, 'scientifically_validated': False,
    'interpretation': 'This compares our model with our own atomistic reference.',
}


def map_traces(page, selector=MAP_PLOT):
    """The Plotly traces the map drew, flattened to what the readings are asserted on."""
    return page.evaluate("""selector => {
      const host = document.querySelector(selector);
      return ((host && host.data) || []).map(trace => ({
        meta: trace.meta, name: trace.name,
        line: trace.line ? {color: trace.line.color, width: trace.line.width, dash: trace.line.dash} : null,
        marker: trace.marker ? {color: trace.marker.color, symbol: trace.marker.symbol,
                                outline: trace.marker.line ? trace.marker.line.color : null} : null,
        customdata: trace.customdata || null,
      }));
    }""", selector)


def wait_for_map(page, selector=MAP_PLOT, meta='bead'):
    page.wait_for_function("""([selector, meta]) => {
      const host = document.querySelector(selector);
      return Boolean(host && host.data && host.data.some(trace => trace.meta === meta));
    }""", arg=[selector, meta], timeout=30000)


def map_host(page):
    return page.locator(f'{CARD} .analysis-map')


def test_the_map_is_shown_on_a_mapping_section_and_hidden_on_figures(dashboard, live_page):
    publish(dashboard, 'aa11bb22cc33', comparison=MAP_COMPARISON)
    publish_mapping(dashboard, 'aa11bb22cc33')
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/run-view?run=aa11bb22cc33')
    root = page.locator(CARD)
    expect(root.locator('.analysis-views button').first).to_be_visible(timeout=30000)
    host = map_host(page)
    expect(host).to_be_hidden()

    root.locator('.analysis-views button[data-section="mapping-geometry"]').click()
    expect(host).to_be_visible()
    expect(host.locator('.rvm-map-title')).to_have_text('Comparison map')
    expect(host.locator('.rvm-map-mode')).to_have_text('Pairs · displacement')
    wait_for_map(page)

    root.locator('.analysis-views button[data-section="figures"]').click()
    expect(host).to_be_hidden()

    root.locator('.analysis-views button[data-section="mapping-bonded"]').click()
    expect(host).to_be_visible()
    expect(host.locator('.rvm-map-mode')).to_have_text('Terms · overlap')
    # Shape has no bead map: the card steps out and the pane carries the AA vs Simulated CG surface comparison. This
    # run has no surfaces published yet, so the pane says so instead of drawing anything.
    root.locator('.analysis-views button[data-section="mapping-shape"]').click()
    expect(host).to_be_hidden()
    expect(root.locator('.analysis-pane[data-section="mapping-shape"] [data-shape="surfaces"]')).to_be_visible()
    assert errors == []


def test_the_three_sections_recolour_one_map(dashboard, live_page):
    publish(dashboard, 'aa11bb22cc33', comparison=MAP_COMPARISON)
    publish_mapping(dashboard, 'aa11bb22cc33')
    publish_overlap(dashboard, 'aa11bb22cc33')
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/run-view?run=aa11bb22cc33')
    root = page.locator(CARD)
    expect(root.locator('.analysis-views button').first).to_be_visible(timeout=30000)

    root.locator('.analysis-views button[data-section="mapping-geometry"]').click()
    wait_for_map(page)
    geometry = map_traces(page)
    geometry_beads = next(trace for trace in geometry if trace['meta'] == 'bead')
    geometry_fills = geometry_beads['marker']['color']
    assert len(geometry_fills) == 4, 'one fill per physical bead; the virtual site is a diamond'
    assert all(str(colour).startswith('rgb(') for colour in geometry_fills), geometry_fills
    assert len(set(geometry_fills)) > 1, 'the displacement scale has more than one step'
    geometry_pairs = [trace for trace in geometry if trace['meta'] == 'pair']
    assert len(geometry_pairs) == 3, geometry_pairs
    pair_inks = {trace['line']['color'] for trace in geometry_pairs}
    assert 'rgba(31,122,77,1)' in pair_inks, 'inside the AA range is green'
    assert 'rgba(192,42,55,1)' in pair_inks, 'outside is red'
    assert 'rgba(139,152,168,1)' in pair_inks, 'unconstrained is grey'

    root.locator('.analysis-views button[data-section="mapping-bonded"]').click()
    wait_for_map(page, meta='term')
    bonded = map_traces(page)
    neutral = next(trace for trace in bonded if trace['meta'] == 'bead')
    assert set(neutral['marker']['color']) == {'rgb(139,152,168)'}, 'Bonded terms draws neutral beads'
    term_inks = {trace['line']['color'] for trace in bonded if trace['meta'] == 'term'}
    assert term_inks, 'the map draws the published terms'
    assert '#1f7a4d' in term_inks and '#c08a1f' in term_inks and '#c02a37' in term_inks, term_inks

    root.locator('.analysis-views button[data-section="mapping-shape"]').click()
    # The map is not recoloured for Shape: the surface comparison and the SASA series replace it there.
    expect(map_host(page)).to_be_hidden()
    expect(root.locator('.analysis-pane[data-section="mapping-shape"] [data-shape="surfaces"]')).to_be_visible()
    assert errors == []


def test_the_reading_headline_and_ranked_attention_name_their_own_metric(dashboard, live_page):
    publish(dashboard, 'aa11bb22cc33', comparison=MAP_COMPARISON)
    publish_mapping(dashboard, 'aa11bb22cc33')
    publish_overlap(dashboard, 'aa11bb22cc33')
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/run-view?run=aa11bb22cc33')
    root = page.locator(CARD)
    expect(root.locator('.analysis-views button').first).to_be_visible(timeout=30000)
    root.locator('.analysis-views button[data-section="mapping-geometry"]').click()
    wait_for_map(page)
    host = map_host(page)
    reading = host.locator('.rvm-reading')
    headline = reading.locator('.rvm-headline-text')
    expect(headline).to_contain_text('3 pairs · 1 outside the AA range · 1 unconstrained')
    expect(headline).to_contain_text('largest displacement 19 pm at (1,B)')
    assert 'not that the pair is free' in reading.locator('.rvm-caveat').text_content()
    assert 'composite' not in reading.text_content().lower()

    items = reading.locator('.rvm-attention li')
    expect(items).to_have_count(3)
    assert 'outside the AA observed range' in items.nth(0).text_content()
    assert 'largest displacement' in items.nth(1).text_content()
    assert '19 pm' in items.nth(1).text_content()
    assert '1 of 3 pairs unconstrained' in items.nth(2).text_content()

    root.locator('.analysis-views button[data-section="mapping-bonded"]').click()
    expect(headline).to_contain_text('3 terms · 2 below overlap 0.5')
    expect(headline).to_contain_text('weakest dihedrals at 0.21')
    expect(items.nth(0)).to_contain_text('dihedrals')
    expect(items.nth(0)).to_contain_text('0.21')

    root.locator('.analysis-views button[data-section="mapping-shape"]').click()
    expect(map_host(page)).to_be_hidden()
    expect(root.locator('.analysis-pane[data-section="mapping-shape"] [data-shape="surfaces"]')).to_be_visible()
    assert errors == []


def test_clicking_an_attention_item_selects_it_in_the_map_and_its_row(dashboard, live_page):
    publish(dashboard, 'aa11bb22cc33', comparison=MAP_COMPARISON)
    publish_mapping(dashboard, 'aa11bb22cc33')
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/run-view?run=aa11bb22cc33')
    root = page.locator(CARD)
    expect(root.locator('.analysis-views button').first).to_be_visible(timeout=30000)
    root.locator('.analysis-views button[data-section="mapping-geometry"]').click()
    wait_for_map(page)
    host = map_host(page)
    first = host.locator('.rvm-attention li').nth(0)
    expect(first).to_contain_text('outside the AA observed range')
    first.locator('button').click()

    assert host.get_attribute('data-selected-beads') == 'B04 B05'
    expect(host.locator('.rvm-map-status')).to_contain_text('outside the AA observed range')
    expect(first.locator('button')).to_have_attribute('aria-current', 'true')
    row = root.locator('.analysis-pane[data-section="mapping-geometry"] [data-item="pair:1"]')
    expect(row).to_have_attribute('aria-selected', 'true')
    page.wait_for_function("""selector => {
      const host = document.querySelector(selector);
      return Boolean(host && host.data && host.data.some(trace =>
        trace.meta === 'pair' && String(trace.customdata?.[0]) === 'pair:1' && trace.line.width === 8));
    }""", arg=MAP_PLOT, timeout=30000)
    assert errors == []


def test_a_term_attention_item_focuses_its_section_row(dashboard, live_page):
    """The weakest term's row carries the map's own item id, so the list and the table point at one row."""
    publish(dashboard, 'aa11bb22cc33', comparison=MAP_COMPARISON)
    publish_mapping(dashboard, 'aa11bb22cc33')
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/run-view?run=aa11bb22cc33')
    root = page.locator(CARD)
    expect(root.locator('.analysis-views button').first).to_be_visible(timeout=30000)
    root.locator('.analysis-views button[data-section="mapping-bonded"]').click()
    wait_for_map(page, meta='term')
    host = map_host(page)
    first = host.locator('.rvm-attention li').nth(0)
    expect(first).to_contain_text('dihedrals')
    first.locator('button').click()

    expect(host.locator('.rvm-map-status')).to_contain_text('dihedrals')
    row = root.locator('.analysis-pane[data-section="mapping-bonded"] [data-item="term:2"]')
    expect(row).to_have_attribute('aria-selected', 'true')
    page.wait_for_function("""selector => {
      const host = document.querySelector(selector);
      return Boolean(host && host.data && host.data.some(trace =>
        trace.meta === 'term' && String(trace.customdata?.[0]) === 'term:2' && trace.line.width === 10));
    }""", arg=MAP_PLOT, timeout=30000)
    assert errors == []


def test_the_selected_bead_survives_a_section_switch(dashboard, live_page):
    publish(dashboard, 'aa11bb22cc33', comparison=MAP_COMPARISON)
    publish_mapping(dashboard, 'aa11bb22cc33')
    publish_overlap(dashboard, 'aa11bb22cc33')
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/run-view?run=aa11bb22cc33')
    root = page.locator(CARD)
    expect(root.locator('.analysis-views button').first).to_be_visible(timeout=30000)
    root.locator('.analysis-views button[data-section="mapping-geometry"]').click()
    wait_for_map(page)
    host = map_host(page)
    host.locator('.rvm-attention li').nth(1).locator('button').click()
    assert host.get_attribute('data-selected-beads') == 'B02'

    root.locator('.analysis-views button[data-section="mapping-bonded"]').click()
    assert host.get_attribute('data-selected-beads') == 'B02', 'the bead selection is not a tab state'
    root.locator('.analysis-views button[data-section="mapping-shape"]').click()
    assert host.get_attribute('data-selected-beads') == 'B02'

    page.wait_for_function("""selector => {
      const host = document.querySelector(selector);
      const bead = (host && host.data || []).find(trace => trace.meta === 'bead');
      return Boolean(bead && (bead.marker.line.color || []).includes('#1c2940'));
    }""", arg=MAP_PLOT, timeout=30000)
    assert errors == []


def test_the_two_monitors_hold_independent_maps(dashboard, live_page):
    publish(dashboard, 'aa11bb22cc33', comparison=MAP_COMPARISON)
    publish_mapping(dashboard, 'aa11bb22cc33')
    database = dashboard.coordinator.database()
    first = {**dict(database.all()[0]), 'molecule_id': 'Run A'}
    publish(dashboard, 'bb22cc33dd44', comparison=MAP_COMPARISON)
    publish_mapping(dashboard, 'bb22cc33dd44')
    second = {**dict(database.all()[0]), 'molecule_id': 'Run B'}
    database.replace([first, second])
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/run-view?run=aa11bb22cc33')
    left = page.locator(CARD)
    right = page.locator(SECOND)
    expect(left.locator('.analysis-views button').first).to_be_visible(timeout=30000)
    expect(right.locator('.analysis-views button').first).to_be_visible(timeout=30000)

    left.locator('.analysis-views button[data-section="mapping-geometry"]').click()
    wait_for_map(page, selector=f'{CARD} .analysis-map .rvm-map-plot')
    left_host = left.locator('.analysis-map')
    left_host.locator('.rvm-attention li').nth(0).locator('button').click()
    assert left_host.get_attribute('data-selected-beads') == 'B04 B05'

    right.locator('.analysis-views button[data-section="mapping-geometry"]').click()
    wait_for_map(page, selector=f'{SECOND} .analysis-map .rvm-map-plot')
    right_host = right.locator('.analysis-map')
    expect(right_host).to_be_visible()
    assert right_host.get_attribute('data-selected-beads') == '', 'the second map chose nothing'
    assert errors == []


def test_a_run_with_no_published_comparison_states_it_in_the_map(dashboard, live_page):
    publish(dashboard, 'dd44ee55ff66', comparison=MAP_COMPARISON)
    publish_mapping(dashboard, 'dd44ee55ff66')
    (dashboard.coordinator.RUNS / 'dd44ee55ff66/analyses/mapping-consistency/hash/attempt1/result.json').unlink()
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/run-view?run=dd44ee55ff66')
    root = page.locator(CARD)
    expect(root.locator('.analysis-views button').first).to_be_visible(timeout=30000)
    root.locator('.analysis-views button[data-section="mapping-geometry"]').click()
    host = map_host(page)
    missing = host.locator('.rvm-map-missing')
    expect(missing).to_be_visible()
    expect(missing).to_contain_text('No AA vs CG comparison', timeout=30000)
    expect(host.locator('.rvm-map-plot')).to_be_hidden()
    assert errors == []


def test_a_missing_model_or_frame_states_the_file_and_still_reads_the_record(dashboard, live_page):
    publish(dashboard, 'dd44ee55ff66', comparison=MAP_COMPARISON)
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/run-view?run=dd44ee55ff66')
    root = page.locator(CARD)
    expect(root.locator('.analysis-views button').first).to_be_visible(timeout=30000)
    root.locator('.analysis-views button[data-section="mapping-geometry"]').click()
    host = map_host(page)
    missing = host.locator('.rvm-map-missing')
    expect(missing).to_be_visible(timeout=30000)
    expect(missing).to_contain_text('stages/2_mapping/model.json is missing')
    expect(host.locator('.rvm-headline-text')).to_contain_text('3 pairs', timeout=30000)
    expect(host.locator('.rvm-map-plot')).to_be_hidden()
    assert errors == []


def test_the_shape_section_queues_its_two_missing_analyses(dashboard, live_page):
    publish(dashboard, 'bb22cc33dd44', comparison=MAP_COMPARISON)
    publish_mapping(dashboard, 'bb22cc33dd44')
    page, errors = live_page
    posted = []

    def hold(route):
        if route.request.method == 'POST':
            posted.append(route.request.url)
            route.fulfill(status=202, content_type='application/json', body=json.dumps(
                {'id': 'queued1', 'kind': 'surfaces', 'status': 'queued',
                 'created_at': '2026-11-06T00:00:00+00:00'}))
        else:
            route.continue_()

    page.route('**/api/jobs/bb22cc33dd44/surfaces', hold)
    page.route('**/api/jobs/bb22cc33dd44/overlap', hold)
    pane = browser.open_run_section(page, live_page.base_url, 'bb22cc33dd44', 'mapping-shape')
    surfaces = pane.locator('.rvm-sub').nth(0)
    overlap = pane.locator('.rvm-sub').nth(1)
    surfaces_button = surfaces.get_by_role('button', name='Calculate surfaces')
    overlap_button = overlap.get_by_role('button', name='Calculate bead overlap')
    expect(surfaces_button).to_be_visible(timeout=30000)
    expect(overlap_button).to_be_visible()

    surfaces_button.click()
    expect(page.locator('#run-view-analysis-note-A')).to_contain_text('Surfaces analysis queued.', timeout=30000)
    assert posted and posted[0].endswith('/api/jobs/bb22cc33dd44/surfaces'), posted

    overlap_button.click()
    expect(page.locator('#run-view-analysis-note-A')).to_contain_text(
        'Bead overlap analysis queued.', timeout=30000)
    assert posted[-1].endswith('/api/jobs/bb22cc33dd44/overlap'), posted
    assert errors == []


def test_a_shape_queue_press_disables_both_buttons_until_the_card_answers(dashboard, live_page):
    publish(dashboard, 'bb22cc33dd44', comparison=MAP_COMPARISON)
    publish_mapping(dashboard, 'bb22cc33dd44')
    page, errors = live_page
    held = []

    def hold(route):
        if route.request.method == 'POST':
            held.append(route)
        else:
            route.continue_()

    page.route('**/api/jobs/bb22cc33dd44/surfaces', hold)
    page.route('**/api/jobs/bb22cc33dd44/overlap', hold)
    pane = browser.open_run_section(page, live_page.base_url, 'bb22cc33dd44', 'mapping-shape')
    surfaces = pane.locator('.rvm-sub').nth(0)
    overlap = pane.locator('.rvm-sub').nth(1)
    surfaces_button = surfaces.get_by_role('button', name='Calculate surfaces')
    overlap_button = overlap.get_by_role('button', name='Calculate bead overlap')
    expect(surfaces_button).to_be_visible(timeout=30000)

    surfaces_button.click()
    for _ in range(100):
        if held:
            break
        page.wait_for_timeout(50)
    assert held, 'the queue request was not made'
    expect(surfaces_button).to_be_disabled()
    expect(overlap_button).to_be_disabled()
    held[0].fulfill(status=202, content_type='application/json', body=json.dumps(
        {'id': 'queued1', 'kind': 'surfaces', 'status': 'queued',
         'created_at': '2026-11-06T00:00:00+00:00'}))
    expect(page.locator('#run-view-analysis-note-A')).to_contain_text('Surfaces analysis queued.', timeout=30000)
    expect(surfaces_button).to_be_enabled()
    assert errors == []
