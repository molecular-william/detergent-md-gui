"""The protein-detergent workspace's New Run panel: what it asks for, and what it no longer asks.

One form, two fieldsets, and this tier is the only place that sees which one a workspace is given. The claims are the
plan's: the pdc fieldset drops Run type, Method, AA reference source and Bonded parameters -- controls the adapter
never reads, on a path where the detergent arrives already parameterized -- and shows the detergent list, the protein
picker with the OPM download, the detergent count, the two CG legs and the advanced settings.

The layout test is the one the plan singles out. Two columns here are a property of `layout.css` being linked *after*
`new-run.css` (`#run-form.new-run-layout` gets the twelve-column grid and the two halves span six each), so an
assertion that both halves exist would pass on a panel stacked into one column -- which is exactly what the mock's
first version did. The test measures, and it pins the breakpoint the halves collapse at as well.
"""
import re

from playwright.sync_api import expect

# The labels the plan says go: each is a control `pdc.validate_payload` does not read.
DROPPED = ('Run type', 'Method', 'AA reference source', 'Bonded parameters')
# And the ids of the controls that carried them, which must not be in this page's document at all.
DROPPED_IDS = ('#run-type', '#method', '#reference-run', '#run-bonded-state', '#run-mapping', '#molecule-panel',
               '#force-field', '#profile')

CATALOG = {
    'templates': [{'id': 'DDM:DDM', 'name': 'DDM skeleton', 'molecule': 'DDM', 'residue': 'DDM',
                   'template': 'molecules/DDM/micelle_template.json', 'registered_type': 'registered-template',
                   'files_present': True, 'missing_files': [],
                   'limitations': ['skeleton placeholder template, not a fitted detergent model']}],
    'proteins': [{'id': 'molecules/1qj8/1qj8.pdb', 'name': '1qj8', 'path': 'molecules/1qj8/1qj8.pdb',
                  'source': 'packaged', 'half_thickness_nm': 1.35}],
    'defaults': {'aggregation_number': 150, 'assessment_ns': 100, 'extension_ns': 900, 'salt_molar': 0.15,
                 'box_margin_nm': 2.0, 'initial_z_nm': 6.0, 'contact_nm': 0.6,
                 'selection_threshold_fraction': 0.1, 'snapshot_interval_ns': 20.0, 'snapshot_cap': 20},
}


def open_panel(page, base_url):
    page.goto(f'{base_url}/protein-detergent/new-run')
    page.get_by_role('tab', name='New run', exact=True).click()
    # The detergent list is the panel's first fetch, and every other claim here needs it to have landed.
    page.wait_for_function("() => document.querySelectorAll('#new-detergent option').length > 1", timeout=30000)


def serve_catalogue(page, proteins=None):
    """The catalogue the panel reads, with the protein list the case needs."""
    entries = [dict(item) for item in CATALOG['templates']]
    page.route(re.compile(r'/api/pdc/catalog'),
               lambda route: route.fulfill(json={**CATALOG, 'templates': entries,
                                                 'proteins': list(proteins or [])}))


def enter_seed(page, value):
    """The seed lives in the advanced block, whose summary names it, so it is opened before it is filled."""
    page.locator('#new-advanced summary').click()
    page.locator('[name=pdc_seed]').fill(value)


def test_the_panel_asks_for_the_pdc_inputs_and_for_nothing_else(dashboard, live_page):
    """The four dropped controls and the six kept ones, against the real routes."""
    page, errors = live_page
    open_panel(page, live_page.base_url)

    expect(page.locator('#new h2')).to_have_text('Protein-Detergent Simulations')
    panel_text = page.locator('#new').inner_text()
    for label in DROPPED:
        assert label not in panel_text, f'{label} is still offered on the protein-detergent panel'
    for selector in DROPPED_IDS:
        assert page.locator(selector).count() == 0, f'{selector} is still in the document'

    # The detergent list comes from the registry: DDM is filed there and the sugars in molecules/ are not.
    options = page.evaluate("Array.from(document.querySelectorAll('#new-detergent option')).map(o => o.value)")
    assert 'DDM' in options, options
    assert not {'Maltose', 'Sucrose', 'Trehalose'} & set(options), options
    expect(page.locator('#new-detergent-detail')).to_contain_text('n-Dodecyl')

    # The kept controls, by name: the detergent, its template and mapping, the protein with the OPM download, the
    # count, the two legs and the advanced block.
    expect(page.locator('#new-template')).to_be_visible()
    expect(page.locator('#new-mapping')).to_be_visible()
    expect(page.locator('#new-protein')).to_be_visible()
    expect(page.locator('#new-protein-id')).to_be_visible()
    expect(page.locator('#new-import')).to_be_visible()
    expect(page.locator('#new-count')).to_be_visible()
    expect(page.locator('#new-assessment-ns')).to_be_visible()
    expect(page.locator('#new-extension-ns')).to_be_visible()
    expect(page.locator('#new-advanced')).to_be_visible()
    for name in ('pdc_seed', 'salt_molar', 'box_margin_nm', 'initial_z_nm', 'contact_nm',
                 'selection_threshold_fraction', 'snapshot_interval_ns', 'snapshot_cap'):
        assert page.locator(f'[name={name}]').count() == 1, f'{name} is not offered, or is offered twice'

    # The workflow card is the top of the right column: what will run is read before the resolved values. With no
    # protein and the pre-assembled default, step 3 states the style it is really running.
    workflow = page.locator('.new-run-settings .card').first
    expect(workflow).to_contain_text('What this run will do')
    expect(workflow.locator('.new-pdc-selfassembly strong')).to_have_text('3 · Build the micelle')
    assert errors == [], errors


def test_the_two_halves_sit_side_by_side_and_stack_at_the_breakpoint(dashboard, live_page):
    """Measured, not merely present: different x, no overlap, and each about half the form's width."""
    page, errors = live_page
    serve_catalogue(page)
    open_panel(page, live_page.base_url)

    form = page.locator('#run-form').bounding_box()
    inputs = page.locator('.new-run-inputs').bounding_box()
    settings = page.locator('.new-run-settings').bounding_box()
    assert inputs['x'] < settings['x'], (inputs, settings)
    assert settings['x'] >= inputs['x'] + inputs['width'] - 1, 'the halves overlap: they are not side by side'
    assert settings['x'] + settings['width'] <= form['x'] + form['width'] + 1, 'the right half leaves the form'
    half = form['width'] / 2
    assert abs(inputs['width'] - half) <= 20, (inputs['width'], half)
    assert abs(settings['width'] - half) <= 20, (settings['width'], half)

    # `layout.css` resets every span at 1100 px, and a span of six in a one-column grid is six implicit columns --
    # so the halves must be one above the other there, not side by side.
    page.set_viewport_size({'width': 1000, 'height': 900})
    stacked = (page.locator('.new-run-inputs').bounding_box(), page.locator('.new-run-settings').bounding_box())
    assert stacked[1]['y'] >= stacked[0]['y'] + stacked[0]['height'] - 1, stacked
    assert errors == [], errors


def test_the_validation_workspace_still_gets_the_single_molecule_panel(dashboard, live_page):
    """The other workspace is unchanged: its heading, its own controls, and no detergent list."""
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/new-run')
    page.get_by_role('tab', name='New run', exact=True).click()
    expect(page.locator('#new h2')).to_have_text('Single Molecule Simulations')
    panel_text = page.locator('#new').inner_text()
    for label in DROPPED:
        assert label in panel_text, f'{label} is missing from the single-molecule panel'
    assert page.locator('#new-detergent').count() == 0, 'the pdc fieldset is rendered in the other workspace'
    assert page.locator('#new-import').count() == 0

    # And its two halves are still side by side, which is the layout this panel always had.
    form = page.locator('#run-form').bounding_box()
    inputs = page.locator('.new-run-inputs').bounding_box()
    settings = page.locator('.new-run-settings').bounding_box()
    assert settings['x'] >= inputs['x'] + inputs['width'] - 1, (inputs, settings)
    assert abs(inputs['width'] - form['width'] / 2) <= 20
    assert errors == [], errors


def test_the_count_stays_an_input_in_both_modes_and_the_empty_micelle_has_no_estimate(dashboard, live_page):
    """The first mock hid the count inside the belt; the review caught it. It is an input either way."""
    page, errors = live_page
    serve_catalogue(page, proteins=CATALOG['proteins'])
    open_panel(page, live_page.base_url)

    # No protein: no belt to size, so no coverage estimate -- and the registry's own number instead.
    expect(page.locator('#new-empty-block')).to_be_visible()
    expect(page.locator('#new-belt-block')).to_be_hidden()
    expect(page.locator('#new-count-label')).to_have_text('Detergents in the micelle')
    expect(page.locator('.new-pdc-empty-number')).to_have_text('— not recorded yet')

    # The count is the micelle's size here, and it is set from the same input.
    page.locator('#new-count').fill('320')
    page.locator('#new-count').press('Tab')
    expect(page.locator('.new-pdc-empty-count')).to_have_text('320')
    expect(page.locator('[data-new-summary=count]')).to_have_text('320')

    # With a protein: the belt comes back, the experimental number's cell changes label, and the count survives.
    page.locator('#new-protein').select_option('molecules/1qj8/1qj8.pdb')
    expect(page.locator('#new-belt-block')).to_be_visible()
    expect(page.locator('#new-empty-block')).to_be_hidden()
    expect(page.locator('#new-count-label')).to_have_text('Detergents in the belt')
    expect(page.locator('.new-pdc-estimate-label')).to_have_text('Estimate')
    expect(page.locator('#new-count')).to_have_value('320')
    expect(page.locator('[data-new-summary=count]')).to_have_text('320')
    assert errors == [], errors


def test_the_seed_defaults_to_today_and_the_gate_still_names_it_when_cleared(dashboard, live_page):
    """The seed is prefilled with today's date, but `pdc.validate_payload` still requires one, so clearing it by
    hand re-arms the launch blocker rather than disabling the button silently."""
    page, errors = live_page
    serve_catalogue(page, proteins=CATALOG['proteins'])
    page.route(re.compile(r'/api/readiness\?'), lambda route: route.fulfill(json={'ready': True, 'checks': [], 'blockers': []}))
    open_panel(page, live_page.base_url)
    page.locator('#new-protein').select_option('molecules/1qj8/1qj8.pdb')

    today = page.evaluate("() => { const d = new Date(); const pad = n => String(n).padStart(2, '0');"
                          "return Number(`${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}`); }")
    expect(page.locator('[name=pdc_seed]')).to_have_value(str(today))
    expect(page.locator('[data-new-summary=seed]')).to_have_text(str(today))
    expect(page.locator('#start-run')).to_be_enabled()
    expect(page.locator('#review-status')).to_have_text('Inputs ready')

    # Emptied by hand, the gate names the seed again. The seed lives in the collapsed advanced block.
    page.locator('#new-advanced summary').click()
    page.locator('[name=pdc_seed]').fill('')
    expect(page.locator('#launch-blocker')).to_contain_text('Choose a random seed')
    expect(page.locator('#start-run')).to_be_disabled()
    expect(page.locator('#review-status')).to_have_text('Action required')
    assert errors == [], errors


def test_the_initialisation_style_is_offered_with_the_pre_assembled_micelle_as_default(dashboard, live_page):
    """Two styles, named for the papers behind them: CHARMM-GUI's pre-assembled micelle (the default, the builder's
    tested path) and MemProtMD's self-assembly."""
    page, errors = live_page
    serve_catalogue(page, proteins=CATALOG['proteins'])
    open_panel(page, live_page.base_url)

    style = page.locator('#new-placement')
    expect(style).to_be_visible()
    assert style.input_value() == 'lattice', 'the builder’s established lattice path is the default'
    options = page.evaluate("Array.from(document.querySelectorAll('#new-placement option')).map(o => o.value)")
    assert options == ['lattice', 'self-assembly'], options
    expect(page.locator('.new-pdc-placement-note')).to_contain_text('CHARMM-GUI')
    assert errors == [], errors


def test_the_style_decides_whether_the_belt_is_the_count_or_settles_from_it(dashboard, live_page):
    """With a protein the pre-assembled belt *is* the count asked for; self-assembly starts from it and lets MD
    settle it. Both the estimate note and the review summary say which is in force."""
    page, errors = live_page
    serve_catalogue(page, proteins=CATALOG['proteins'])
    open_panel(page, live_page.base_url)
    page.locator('#new-protein').select_option('molecules/1qj8/1qj8.pdb')

    expect(page.locator('[data-new-summary=placement]')).to_have_text('Pre-assembled micelle · CHARMM-GUI')
    expect(page.locator('.new-pdc-estimate-note')).to_contain_text('exactly the 150 detergents')
    expect(page.locator('.new-pdc-selfassembly strong')).to_have_text('3 · Place the belt')

    page.locator('#new-placement').select_option('self-assembly')
    expect(page.locator('[data-new-summary=placement]')).to_have_text('Self-assembly · MemProtMD')
    expect(page.locator('.new-pdc-placement-note')).to_contain_text('settles')
    expect(page.locator('.new-pdc-estimate-note')).to_contain_text('placed at random')
    expect(page.locator('.new-pdc-selfassembly strong')).to_have_text('3 · Self-assemble')
    assert errors == [], errors


def test_the_empty_micelle_branch_works_in_both_styles(dashboard, live_page):
    """No protein stays a valid build for either style: the empty branch is shown, and the style sentence adapts."""
    page, errors = live_page
    serve_catalogue(page, proteins=CATALOG['proteins'])
    open_panel(page, live_page.base_url)

    expect(page.locator('#new-empty-block')).to_be_visible()
    expect(page.locator('#new-belt-block')).to_be_hidden()
    expect(page.locator('.new-pdc-estimate-note')).to_contain_text('exactly the 150 detergents')

    page.locator('#new-placement').select_option('self-assembly')
    expect(page.locator('#new-empty-block')).to_be_visible()
    expect(page.locator('#new-belt-block')).to_be_hidden()
    expect(page.locator('.new-pdc-estimate-note')).to_contain_text('settles the micelle')
    expect(page.locator('[data-new-summary=placement]')).to_have_text('Self-assembly · MemProtMD')
    assert errors == [], errors


def test_the_panel_sends_the_initialisation_style_it_shows(dashboard, live_page):
    """The choice reaches the payload under the adapter's placement-mode alias, beside the same settings the rest of
    the panel sends."""
    page, errors = live_page
    posted = {}
    serve_catalogue(page, proteins=CATALOG['proteins'])
    page.route(re.compile(r'/api/readiness\?'), lambda route: route.fulfill(json={'ready': True, 'checks': [], 'blockers': []}))

    def queue(route):
        if route.request.method != 'POST':
            route.fallback()
            return
        posted.update(route.request.post_data_json or {})
        route.fulfill(status=201, json={'id': 'pdcqueued1', 'run_type': 'pdc'})

    page.route(re.compile(r'^http://127\.0\.0\.1:\d+/$'), queue)
    open_panel(page, live_page.base_url)
    page.locator('#new-protein').select_option('molecules/1qj8/1qj8.pdb')
    page.locator('#new-placement').select_option('self-assembly')
    expect(page.locator('#start-run')).to_be_enabled()
    page.locator('#start-run').click()

    expect(page.locator('#notice')).to_contain_text('Run queued.', timeout=30000)
    assert posted['pdc_placement_mode'] == 'self-assembly', posted
    assert errors == [], errors


def test_the_panel_queues_the_payload_the_pdc_adapter_reads(dashboard, live_page):
    """The payload is the adapter's own vocabulary, and nothing else is on it.

    A control whose value no stage consumes is a control that lies, so this pins the key set: the run type, the
    detergent, its template and mapping, the protein (or its absence), the label, whether the run is back-mapped,
    and the settings under the names `pdc.SETTING_SPECS` declares.

    This fixture's protein declares no chains, so `protein_chains` is absent: a whole-file run carries no subunit
    selection, and `test_pdc_subunits_browser.py` pins the payload when an entry does declare them.
    """
    page, errors = live_page
    posted = {}
    serve_catalogue(page, proteins=CATALOG['proteins'])
    page.route(re.compile(r'/api/readiness\?'), lambda route: route.fulfill(json={'ready': True, 'checks': [], 'blockers': []}))

    def queue(route):
        if route.request.method != 'POST':
            route.fallback()
            return
        posted.update(route.request.post_data_json or {})
        route.fulfill(status=201, json={'id': 'pdcqueued1', 'run_type': 'pdc'})

    page.route(re.compile(r'^http://127\.0\.0\.1:\d+/$'), queue)
    open_panel(page, live_page.base_url)

    page.locator('#new-protein').select_option('molecules/1qj8/1qj8.pdb')
    enter_seed(page, '20260928')
    page.locator('#new-count').fill('220')
    page.locator('#new-count').press('Tab')
    page.locator('[name=label]').fill('pdc panel test')
    expect(page.locator('#start-run')).to_be_enabled()
    page.locator('#start-run').click()

    expect(page.locator('#notice')).to_contain_text('Run queued.', timeout=30000)
    assert posted == {
        'run_type': 'pdc', 'molecule_id': 'DDM', 'template': 'molecules/DDM/micelle_template.json',
        'protein': 'molecules/1qj8/1qj8.pdb', 'label': 'pdc panel test', 'pdc_placement_mode': 'lattice',
        'backmap': True,
        'aggregation_number': 220, 'pdc_assessment_ns': 100, 'pdc_extension_ns': 900, 'pdc_seed': 20260928,
        'salt_molar': 0.15, 'box_margin_nm': 2.0, 'initial_z_nm': 6.0, 'contact_nm': 0.6,
        'selection_threshold_fraction': 0.1, 'snapshot_interval_ns': 20.0, 'snapshot_cap': 20,
    }, posted
    assert errors == [], errors


def test_an_opm_download_joins_the_picker_and_states_the_half_thickness_it_found(dashboard, live_page):
    """The download reuses the route the Complexes panel drives, including its honesty about the membrane."""
    page, errors = live_page
    imported = {'pdbid': '1qj8', 'half_thickness_nm': 1.35}
    served = {'proteins': []}

    def catalogue(route):
        route.fulfill(json={**CATALOG, 'proteins': served['proteins']})

    def import_structure(route):
        served['proteins'] = [{'id': 'molecules/1qj8/1qj8.pdb', 'name': '1qj8', 'path': 'molecules/1qj8/1qj8.pdb',
                               'source': 'imported', 'half_thickness_nm': 1.35}]
        route.fulfill(status=201, json=imported)

    page.route(re.compile(r'/api/pdc/catalog'), catalogue)
    page.route(re.compile(r'/api/pdc/proteins/import'), import_structure)
    open_panel(page, live_page.base_url)

    page.locator('#new-protein-id').fill('1qj8')
    page.locator('#new-import').click()

    expect(page.locator('#new-import-status')).to_contain_text('1.35 nm half-thickness')
    expect(page.locator('#new-protein')).to_have_value('molecules/1qj8/1qj8.pdb')
    expect(page.locator('[data-new-summary=protein]')).to_contain_text('1qj8')
    assert errors == [], errors
