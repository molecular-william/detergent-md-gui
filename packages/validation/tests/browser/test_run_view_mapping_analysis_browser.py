"""What the Run view Analysis card draws for a mapping's own records, over a comparison the test built itself.

The Mapping Validation tab used to be the reader; its three per-run sections now live in each Run view monitor's
Analysis card. These tests therefore open the run already selected (`?run=`), click the section they are about and
read the same published records the panel read -- pairs and the per-bead chart, the terms and the two cross-checks,
the envelope and the bead overlap -- plus the two states a run can be in: no comparison published, and no comparison
defined for the run type.
"""
import json

from playwright.sync_api import expect

from tests.harness.validation_fixtures import publish, publish_cross_check

CARD = '#run-view-analysis-A'
SECOND = '#run-view-analysis-B'


def open_section(page, live_page, jid, section, card=CARD):
    """Open the Run view on one run and one analysis section, and return that section's pane."""
    page.goto(f'{live_page.base_url}/detergent-validation/run-view?run={jid}')
    root = page.locator(card)
    expect(root.locator('.analysis-views button').first).to_be_visible(timeout=30000)
    root.locator(f'.analysis-views button[data-section="{section}"]').click()
    pane = root.locator(f'.analysis-pane[data-section="{section}"]')
    expect(pane).to_be_visible()
    return pane


SURFACES = {
    'probe_nm': 0.191, 'rendering': 'SAS mesh, GROMACS Connolly dots retained separately',
    'scientifically_validated': False, 'comparison_html': 'analysis/surfaces/surface-comparison.html',
    'statistics': {'AA': {'frames': 20001, 'start_ps': 0.0, 'end_ps': 200000.0,
                          'mean_nm2': 5.8157, 'std_nm2': 0.077},
                   'Simulated CG': {'frames': 20001, 'start_ps': 0.0, 'end_ps': 200000.0,
                                    'mean_nm2': 5.599, 'std_nm2': 0.174}},
}


def publish_surfaces(dashboard, jid):
    """Leave behind what `analysis.worker` leaves behind for a completed surfaces analysis."""
    attempt = dashboard.coordinator.RUNS / jid / 'analyses/surfaces/hash/attempt1'
    output = attempt / 'output/abc123/analysis/surfaces'
    output.mkdir(parents=True)
    (output / 'metadata.json').write_text(json.dumps(SURFACES))
    (output / 'surface-comparison.html').write_text('<html><body>envelopes</body></html>')
    (attempt / 'result.json').write_text(json.dumps(
        {'result': SURFACES, 'output_directory': 'output/abc123', 'wall_seconds': 121.0}))
    return attempt


OVERLAP = {
    'residue': 'DDM',
    'bead_names': ['B01', 'B02', 'B03'],
    'pairs': [['B01', 'B02'], ['B01', 'B03'], ['B02', 'B03']],
    'matrix': [[1.0, 0.82, 0.31], [0.82, 1.0, 0.44], [0.31, 0.44, 1.0]],
    'overlaps': [0.82, 0.31, 0.44],
    'per_bead_mean': [{'bead': 'B01', 'mean': 0.565}, {'bead': 'B02', 'mean': 0.63},
                      {'bead': 'B03', 'mean': 0.375}],
    'range_nm': [0.1, 0.6],
    'frames': {'reference': 20001, 'model': 2001},
    'limitations': ['Intra-residue bead distances only: an interaction spanning two residues is outside this report.'],
    'figure': 'overlap.html',
    'report': 'overlap.json',
    'scientifically_validated': False,
}


def publish_overlap(dashboard, jid):
    """Leave behind what `analysis.worker` leaves behind for a completed overlap analysis."""
    attempt = dashboard.coordinator.RUNS / jid / 'analyses/overlap/hash/attempt1'
    output = attempt / 'output/abc123'
    output.mkdir(parents=True)
    (output / 'overlap.json').write_text(json.dumps(OVERLAP))
    (output / 'overlap.html').write_text('<html><body>heatmap</body></html>')
    (attempt / 'result.json').write_text(json.dumps(
        {'result': OVERLAP, 'output_directory': 'output/abc123', 'wall_seconds': 3.0}))
    return attempt


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
    pane = open_section(page, live_page, 'aa11bb22cc33', 'mapping-geometry')

    expect(pane.locator('.rvm-measure')).to_have_count(2)
    second = pane.locator('.rvm-measure').nth(1).text_content()
    # Two different statements side by side: the pair sits inside our own observed range, and is 16% away from the
    # published entry, which is carried as context and not as a verdict.
    assert 'inside the AA range' in second, second
    assert '(-16.0% context)' in second, second
    expect(pane.locator('.rvm-badge').filter(has_text='0 of 2 pairs outside the AA observed range')).to_have_count(1)

    page.wait_for_function(
        "() => { const host = document.querySelector('#run-view-analysis-A "
        ".analysis-pane[data-section=\"mapping-geometry\"] .rvm-chart');"
        " return host && host.data && host.data.length === 1; }", timeout=30000)
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
    pane = open_section(page, live_page, 'dd44ee55ff66', 'mapping-geometry')

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
    pane = open_section(page, live_page, 'dd44ee55ff66', 'mapping-geometry')

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
    pane = open_section(page, live_page, 'bb22cc33dd44', 'mapping-bonded')

    expect(pane.locator('.rvm-measures').first.locator('.rvm-measure')).to_have_count(2)
    terms = pane.locator('.rvm-measures').first.text_content()
    assert 'bond' in terms and 'angle' in terms, terms

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


def test_a_run_with_no_cross_check_or_dihedral_fit_says_so_and_lists_nothing(dashboard, live_page):
    publish(dashboard, 'bb22cc33dd44')
    page, errors = live_page
    pane = open_section(page, live_page, 'bb22cc33dd44', 'mapping-bonded')

    subs = pane.locator('.rvm-sub')
    expect(subs.nth(0).locator('.rvm-measure')).to_have_count(0)
    expect(subs.nth(0).locator('.hint').nth(0)).to_contain_text('queued by hand', timeout=30000)
    expect(subs.nth(1).locator('.rvm-measure')).to_have_count(0)
    expect(subs.nth(1).locator('.hint').nth(0)).to_contain_text('queued by hand')
    assert errors == []


# --------------------------------------------------------------------------------------------- shape and volume

def test_the_envelope_analysis_is_drawn_with_its_statistics_and_its_own_figure(dashboard, live_page):
    publish(dashboard, 'bb22cc33dd44')
    publish_surfaces(dashboard, 'bb22cc33dd44')
    page, errors = live_page
    pane = open_section(page, live_page, 'bb22cc33dd44', 'mapping-shape')

    surfaces = pane.locator('.rvm-sub').nth(0)
    expect(surfaces.locator('.rvm-table tbody tr')).to_have_count(2, timeout=30000)
    rows = surfaces.locator('.rvm-table tbody tr')
    assert 'AA' in rows.nth(0).text_content() and '5.816' in rows.nth(0).text_content(), rows.nth(0).text_content()
    assert 'Simulated CG' in rows.nth(1).text_content() and '5.599' in rows.nth(1).text_content()
    frame = surfaces.locator('iframe').get_attribute('src')
    assert frame.startswith('/api/jobs/bb22cc33dd44/artifacts/analyses/surfaces/'), frame
    assert frame.endswith('surface-comparison.html?inline=1'), frame
    note = surfaces.locator('.hint').nth(0).text_content()
    assert 'SAS mesh' in note and 'Not scientifically validated' in note, note
    assert errors == []


def test_a_run_with_no_envelope_analysis_says_so_and_frames_nothing(dashboard, live_page):
    publish(dashboard, 'bb22cc33dd44')
    page, errors = live_page
    pane = open_section(page, live_page, 'bb22cc33dd44', 'mapping-shape')

    surfaces = pane.locator('.rvm-sub').nth(0)
    expect(surfaces.locator('.hint').nth(0)).to_contain_text('queued by hand', timeout=30000)
    assert 'solvent-accessible surfaces analysis has been published' in surfaces.locator('.hint').nth(0).text_content().lower()
    expect(surfaces.locator('.rvm-table')).to_have_count(0)
    expect(surfaces.locator('iframe')).to_have_count(0)
    assert errors == []


def test_the_bead_overlap_analysis_is_drawn_with_its_numbers_and_its_own_figure(dashboard, live_page):
    publish(dashboard, 'bb22cc33dd44')
    publish_overlap(dashboard, 'bb22cc33dd44')
    page, errors = live_page
    pane = open_section(page, live_page, 'bb22cc33dd44', 'mapping-shape')

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
    pane = open_section(page, live_page, 'bb22cc33dd44', 'mapping-shape')

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
    pane = open_section(page, live_page, 'bb22cc33dd44', 'mapping-shape')

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
