"""The Detergent shape card: the two lists it reads, the body it shows, and the spec it sends.

The two conformation routes do not exist in this checkout's server yet (lane 3 owns them), so every test here stubs
them and the same fixtures: a completed protein-free pdc run, a protein-carrying run that is listed but not eligible,
and one stored library. The card's three modes are the plan's: `single` (today's one rigid conformation, no body and
no setting), `build` (`{runs,size,seed}`), and `stored` (`{key,sha256}`). What the browser tier can prove is the
wiring -- that only the chosen body renders, and that the spec reaches both the submit payload and the preview query.
"""
import json
import re
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect

from tests.harness import browser

CATALOG = {
    'templates': [{'id': 'DDM:DDM', 'name': 'DDM skeleton', 'molecule': 'DDM', 'residue': 'DDM',
                   'template': 'molecules/DDM/micelle_template.json', 'registered_type': 'registered-template',
                   'files_present': True, 'missing_files': [],
                   'limitations': ['skeleton placeholder template, not a fitted detergent model']}],
    'proteins': [],
    'defaults': {'aggregation_number': 150, 'assessment_ns': 100, 'extension_ns': 900, 'salt_molar': 0.15,
                 'box_margin_nm': 2.0, 'initial_z_nm': 6.0, 'contact_nm': 0.6,
                 'selection_threshold_fraction': 0.1,
                 'nstlog': 100, 'nstenergy': 100, 'nstxtcout': 100, 'xtc_precision': 1000, 'nstcomm': 100,
                 'nstlist': 40, 'verlet_buffer_tolerance': 0.005, 'rlist': 1.35, 'rcoulomb': 1.1, 'rvdw': 1.1,
                 'ref_t': 300, 'tau_t': 1.0, 'ref_p': 1.0, 'tau_p': 12.0, 'compressibility': 4.5e-5,
                 'mdrun_ntomp': 8, 'mdrun_ranks': 1, 'mdrun_nb': 'auto'},
}
MODELS = {'molecule': 'DDM', 'models': []}
RUN_IDS = ['b920391735dd', '8f2c1a4e9d3b']
RUNS = {'runs': [
    {'id': RUN_IDS[0], 'label': 'DDM 100 ns', 'residue': 'DDM', 'protein': False, 'completed': True,
     'duration_ns': 100.0, 'eligible': True, 'reason': None},
    {'id': RUN_IDS[1], 'label': '', 'residue': 'DDM', 'protein': False, 'completed': True,
     'duration_ns': 300.0, 'eligible': True, 'reason': None},
    # An ineligible run is listed, with its sentence, and cannot be selected -- never hidden.
    {'id': '4iar-DDM-run', 'label': '', 'residue': 'DDM', 'protein': True, 'completed': True,
     'duration_ns': 100.0, 'eligible': False,
     'reason': 'run 4iar-DDM-run carries a protein; a micelle-only run is required'},
]}
KEY = '3fa9c2e71b04d865'
SHA256 = '5d0a' + 'ab' * 28 + 'c1e8'
LIBRARIES = {'libraries': [
    {'key': KEY, 'residue': 'DDM', 'size': 2000, 'sha256': SHA256, 'sources': RUN_IDS,
     'path': f'workspace/dashboard/conformations/DDM/{KEY}/library.json'},
]}
ROW_COUNT = len(RUNS['runs'])
#: What `/api/pdc/preview/placement` answers once lane 3 resolves a library: the basis names the library's key,
#: size, mode and sources, never its coordinates. The shape line beside the picture reads exactly this block.
PREVIEW_BODY = {
    'valid': True,
    'pdb': '',
    'basis': {'protein': None, 'chains': [], 'placement_mode': 'lattice', 'aggregation_number': 150, 'seed': 1,
              'beads': 150, 'box_nm': [5.0, 5.0, 8.0],
              'conformations': {'key': KEY, 'size': 2000, 'mode': 'build', 'sources': RUN_IDS}},
    'cost': {},
}


def serve(page, *, runs=None, runs_status=200, libraries=None, posted=None, previews=None, library_calls=None,
          preview_body=None):
    """Every read the panel makes before it can ask, plus the two conformation routes this feature is about."""
    page.route(re.compile(r'/api/pdc/catalog'), lambda route: route.fulfill(json=CATALOG))
    page.route(re.compile(r'/api/pdc/models\?'), lambda route: route.fulfill(json=MODELS))
    page.route(re.compile(r'/api/readiness\?'),
               lambda route: route.fulfill(json={'ready': True, 'checks': [], 'blockers': []}))
    page.route(re.compile(r'/api/pdc/conformations/runs'), lambda route: route.fulfill(
        status=runs_status, json=(runs or RUNS) if runs_status == 200 else {'error': 'the run store is unavailable'}))

    def libraries_route(route):
        if library_calls is not None:
            library_calls.append(route.request.url)
        route.fulfill(json=libraries or LIBRARIES)

    page.route(re.compile(r'/api/pdc/conformations/libraries'), libraries_route)

    def preview(route):
        if previews is not None:
            previews.append(route.request.url)
        # Where a case reads only the request, a refusal keeps the card from drawing anything it would have to parse;
        # the shape-line cases pass a valid answer carrying `basis.conformations`.
        route.fulfill(json=preview_body if preview_body is not None
                      else {'valid': False, 'reasons': ['stub refusal: this test reads the request only']})

    page.route(re.compile(r'/api/pdc/preview/placement'), preview)

    def queue(route):
        if route.request.method != 'POST':
            route.fallback()
            return
        if posted is not None:
            posted.update(route.request.post_data_json or {})
        route.fulfill(status=201, json={'id': 'pdcqueued1', 'run_type': 'pdc'})

    page.route(re.compile(r'^http://127\.0\.0\.1:\d+/$'), queue)


def open_panel(page, base_url):
    browser.open_pdc_new_run(page, base_url)
    # The runs list is the card's own mount signal: the card exists before it, and its rows arrive from the stub.
    page.wait_for_function(f"() => document.querySelectorAll('.new-pdc-shape .eligible-run').length === {ROW_COUNT}",
                           timeout=30000)


def choose_shape(page, label):
    """Click a pill of the segmented control; the radio itself is transparent and fills the label."""
    page.locator('.new-pdc-shape .seg').filter(has_text=label).click()


def derive(page):
    page.locator('.new-pdc-preview-derive').click()
    expect(page.locator('.new-pdc-preview-refusal')).to_be_visible(timeout=30000)


def test_the_card_follows_run_configuration_and_shows_only_the_chosen_body(dashboard, live_page):
    page, errors = live_page
    serve(page)
    open_panel(page, live_page.base_url)

    # Card 4 in the approved draft: Detergent, Membrane protein, Run configuration, Detergent shape.
    cards = page.locator('.new-run-inputs > .card')
    expect(cards.nth(3)).to_have_class(re.compile(r'new-pdc-shape'))
    expect(page.locator('.new-pdc-shape')).to_be_visible()
    # `single` is the default and has no body; the other two are hidden until chosen.
    expect(page.locator('[data-shape-body="single"]')).to_be_hidden()
    expect(page.locator('[data-shape-body="build"]')).to_be_hidden()
    expect(page.locator('[data-shape-body="stored"]')).to_be_hidden()

    choose_shape(page, 'Build from runs')
    expect(page.locator('[data-shape-body="build"]')).to_be_visible()
    expect(page.locator('[data-shape-body="single"]')).to_be_hidden()
    expect(page.locator('[data-shape-body="stored"]')).to_be_hidden()
    rows = page.locator('.new-pdc-shape .eligible-run')
    expect(rows).to_have_count(ROW_COUNT)
    expect(rows.nth(0)).to_contain_text(RUN_IDS[0])
    expect(rows.nth(0)).to_contain_text('DDM empty micelle · 100 ns')
    expect(rows.nth(0).locator('input[type=checkbox]')).to_be_checked()
    expect(rows.nth(2)).to_contain_text('not eligible')
    expect(rows.nth(2)).to_contain_text('carries a protein')
    assert rows.nth(2).locator('input[type=checkbox]').is_disabled()
    assert page.locator('[name=conformations_size]').input_value() == '2000'
    assert page.locator('[name=conformations_seed]').input_value() == '0'
    expect(page.locator('.new-pdc-shape .shape-summary')).to_contain_text('stored once built')

    choose_shape(page, 'Stored library')
    expect(page.locator('[data-shape-body="stored"]')).to_be_visible()
    expect(page.locator('[data-shape-body="build"]')).to_be_hidden()
    page.wait_for_function("() => document.querySelectorAll('.new-pdc-shape .stored-library').length === 1",
                           timeout=30000)
    stored = page.locator('.new-pdc-shape .stored-library').first
    expect(stored).to_contain_text(KEY)
    expect(stored.locator('input[type=radio]')).to_be_checked()
    assert errors == [], errors


def test_build_mode_sends_exactly_its_spec_and_single_sends_no_key(dashboard, live_page):
    page, errors = live_page
    posted = {}
    serve(page, posted=posted)
    open_panel(page, live_page.base_url)

    # `single` first: it is the default, so the payload must not carry the setting at all.
    expect(page.locator('#start-run')).to_be_enabled()
    page.locator('#start-run').click()
    expect(page.locator('#notice')).to_contain_text('Run queued.', timeout=30000)
    assert 'conformation_library' not in posted, posted

    # The same form in build mode sends the two eligible runs and the footer's numbers, nested under one key.
    posted.clear()
    page.get_by_role('tab', name='New run', exact=True).click()
    choose_shape(page, 'Build from runs')
    expect(page.locator('#start-run')).to_be_enabled()
    page.locator('#start-run').click()
    expect(page.locator('#notice')).to_contain_text('Run queued.', timeout=30000)
    assert posted['conformation_library'] == {'runs': RUN_IDS, 'size': 2000, 'seed': 0}, posted
    # The spec travels as one setting, never as loose top-level keys.
    assert not {'runs', 'size', 'seed'} & set(posted), posted
    assert errors == [], errors


def test_stored_mode_sends_the_key_and_digest(dashboard, live_page):
    page, errors = live_page
    posted = {}
    serve(page, posted=posted)
    open_panel(page, live_page.base_url)
    choose_shape(page, 'Stored library')
    page.wait_for_function("() => document.querySelectorAll('.new-pdc-shape .stored-library').length === 1",
                           timeout=30000)

    expect(page.locator('#start-run')).to_be_enabled()
    page.locator('#start-run').click()
    expect(page.locator('#notice')).to_contain_text('Run queued.', timeout=30000)
    assert posted['conformation_library'] == {'key': KEY, 'sha256': SHA256}, posted
    assert errors == [], errors


def test_the_preview_query_carries_the_spec_in_both_non_default_modes(dashboard, live_page):
    page, errors = live_page
    previews = []
    serve(page, previews=previews)
    open_panel(page, live_page.base_url)

    # `single` sends no argument, just as it sends no payload key.
    derive(page)
    assert 'conformation_library' not in parse_qs(urlparse(previews[-1]).query), previews[-1]

    choose_shape(page, 'Build from runs')
    derive(page)
    url = previews[-1]
    assert 'conformation_library=%7B' in url, url
    query = parse_qs(urlparse(url).query)
    assert json.loads(query['conformation_library'][0]) == {'runs': RUN_IDS, 'size': 2000, 'seed': 0}
    # The shape rides beside the preview's existing arguments rather than replacing them.
    assert query['pdc_seed'] and query['placement_mode'], query

    choose_shape(page, 'Stored library')
    page.wait_for_function("() => document.querySelectorAll('.new-pdc-shape .stored-library').length === 1",
                           timeout=30000)
    derive(page)
    query = parse_qs(urlparse(previews[-1]).query)
    assert json.loads(query['conformation_library'][0]) == {'key': KEY, 'sha256': SHA256}
    assert errors == [], errors


def test_a_shape_change_marks_the_derived_frame_stale(dashboard, live_page):
    page, errors = live_page
    serve(page, previews=[])
    open_panel(page, live_page.base_url)
    derive(page)
    expect(page.locator('.new-pdc-preview-state')).not_to_have_class(re.compile(r'\bstale\b'))

    choose_shape(page, 'Build from runs')
    expect(page.locator('.new-pdc-preview-state')).to_have_class(re.compile(r'\bstale\b'))
    expect(page.locator('.new-pdc-preview-state')).to_contain_text('detergent shape')

    page.locator('[name=conformations_seed]').fill('7')
    page.locator('[name=conformations_seed]').press('Tab')
    expect(page.locator('.new-pdc-preview-state')).to_have_class(re.compile(r'\bstale\b'))
    assert errors == [], errors


def test_a_failed_runs_fetch_says_so_and_leaves_the_form_usable(dashboard, live_page):
    page, errors = live_page
    posted = {}
    serve(page, runs_status=503, posted=posted)
    browser.open_pdc_new_run(page, live_page.base_url)
    choose_shape(page, 'Build from runs')

    expect(page.locator('.new-pdc-shape .shape-summary')).to_contain_text('The micelle-only runs could not be read')
    # The card says the cause and the form still submits in its default mode.
    choose_shape(page, 'One conformation')
    expect(page.locator('#start-run')).to_be_enabled()
    page.locator('#start-run').click()
    expect(page.locator('#notice')).to_contain_text('Run queued.', timeout=30000)
    assert 'conformation_library' not in posted, posted
    assert errors == [], errors


def test_the_stored_list_is_read_on_mount_with_the_residue_and_again_after_a_submit(dashboard, live_page):
    page, errors = live_page
    calls = []
    serve(page, library_calls=calls)
    open_panel(page, live_page.base_url)
    choose_shape(page, 'Stored library')
    page.wait_for_function("() => document.querySelectorAll('.new-pdc-shape .stored-library').length === 1",
                           timeout=30000)

    assert calls, 'the stored-library list was never read'
    assert all('residue=DDM' in url for url in calls), calls
    # A successful build writes into the store, so the list is read again to make the new library selectable.
    with page.expect_response(lambda response: '/api/pdc/conformations/libraries' in response.url):
        page.locator('#start-run').click()
    expect(page.locator('#notice')).to_contain_text('Run queued.', timeout=30000)
    assert len(calls) >= 2, calls
    assert errors == [], errors


SINGLE_LINE = "One rigid conformation. No library; the template's own coordinates are rotated onto every site."


def test_the_preview_line_names_the_resolved_library_key_and_size(dashboard, live_page):
    """The plan's browser acceptance: the preview shows the library key and size, read from `basis.conformations`."""
    page, errors = live_page
    serve(page, preview_body=PREVIEW_BODY)
    open_panel(page, live_page.base_url)
    line = page.locator('.new-pdc-preview-library')

    # Nothing has been derived, and `single` is the default: the line describes a rigid conformation.
    expect(line).to_have_text(SINGLE_LINE)

    choose_shape(page, 'Build from runs')
    page.locator('.new-pdc-preview-derive').click()
    expect(page.locator('.new-pdc-preview-basis')).to_contain_text('Placement for', timeout=30000)
    expect(line).to_have_text(f'Library {KEY} · 2,000 conformations · from 2 runs')

    # The frame answered the build spec, not the stored one; switching modes leaves the resolved key behind.
    choose_shape(page, 'Stored library')
    expect(line).to_have_text(SINGLE_LINE)
    assert errors == [], errors


def test_a_preview_body_without_conformations_keeps_the_single_line(dashboard, live_page):
    """Lane 3 has not added the field yet, and the card must not break or invent a key when it is absent."""
    page, errors = live_page
    body = {**PREVIEW_BODY, 'basis': {name: value for name, value in PREVIEW_BODY['basis'].items()
                                      if name != 'conformations'}}
    serve(page, preview_body=body)
    open_panel(page, live_page.base_url)
    choose_shape(page, 'Build from runs')
    page.locator('.new-pdc-preview-derive').click()
    expect(page.locator('.new-pdc-preview-basis')).to_contain_text('Placement for', timeout=30000)
    expect(page.locator('.new-pdc-preview-library')).to_have_text(SINGLE_LINE)
    assert errors == [], errors
