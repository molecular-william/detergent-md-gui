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

from tests.harness import browser

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
                 'selection_threshold_fraction': 0.1,
                 'nstlog': 100, 'nstenergy': 100, 'nstxtcout': 100, 'xtc_precision': 1000, 'nstcomm': 100,
                 'nstlist': 40, 'verlet_buffer_tolerance': 0.005, 'rlist': 1.35, 'rcoulomb': 1.1, 'rvdw': 1.1,
                 'ref_t': 300, 'tau_t': 1.0, 'ref_p': 1.0, 'tau_p': 12.0, 'compressibility': 4.5e-5,
                 'mdrun_ntomp': 8, 'mdrun_ranks': 1, 'mdrun_nb': 'auto'},
}


def open_panel(page, base_url):
    return browser.open_pdc_new_run(page, base_url)


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
                 'selection_threshold_fraction', 'nstlog', 'nstenergy', 'nstxtcout', 'xtc_precision',
                 'nstcomm', 'nstlist', 'verlet_buffer_tolerance', 'rlist', 'rcoulomb', 'rvdw',
                 'ref_t', 'tau_t', 'ref_p', 'tau_p', 'compressibility', 'mdrun_ntomp', 'mdrun_ranks'):
        assert page.locator(f'[name={name}]').count() == 1, f'{name} is not offered, or is offered twice'
    assert page.locator('[name=snapshot_interval_ns], [name=snapshot_cap]').count() == 0, 'snapshot inputs are retired'

    # The system preview is the top of the right column and the workflow strip is the card under it: the picture the
    # inputs would build is read first, then what the run will do. (The preview card is the plan's addition; before it
    # the workflow card was this column's first child, which is what this line used to assert.)
    preview = page.locator('.new-run-settings .card').first
    expect(preview).to_contain_text('What these inputs would build')
    workflow = page.locator('.new-run-settings .card').nth(1)
    expect(workflow).to_contain_text('What this run will do')
    expect(workflow.locator('.new-pdc-placed-node text.title')).to_have_text('1 · Build the micelle')
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
    browser.assert_side_by_side(page, '.new-run-inputs', '.new-run-settings')
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
    """The other workspace is unchanged: its heading, its own controls, and no detergent list.

    `Bonded parameters` and `Bonded workflow` are *not* in the kept list any more: those two controls left the
    single-molecule panel in the AA-CG refactor (fitting is the AA-CG run type's own), and this test is the one that
    would have gone on asserting they were there.
    """
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/new-run')
    page.get_by_role('tab', name='New run', exact=True).click()
    expect(page.locator('#new h2')).to_have_text('Single Molecule Simulations')
    panel_text = page.locator('#new').inner_text()
    for label in ('Run type', 'Method', 'AA reference source'):
        assert label in panel_text, f'{label} is missing from the single-molecule panel'
    for label in ('Bonded parameters', 'Bonded workflow'):
        assert label not in panel_text, f'{label} is still offered on the single-molecule panel'
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


def test_every_other_run_option_has_a_default(dashboard, live_page):
    """Nothing in the collapsed block is blank on first load, even on a host whose device probe answers nothing."""
    page, errors = live_page
    serve_catalogue(page, proteins=CATALOG['proteins'])
    page.route('**/api/run/devices', lambda route: route.fulfill(json={'devices': [], 'in_use': {}}))
    open_panel(page, live_page.base_url)
    page.locator('#new-advanced').evaluate('(el) => el.open = true')

    values = page.evaluate("""() => Object.fromEntries(
        [...document.querySelectorAll('#new-advanced [name]')].map(el => [el.name, el.value]))""")
    assert values, 'the block renders no inputs'
    assert {name: value for name, value in values.items() if value in ('', None)} == {}, values
    assert values['mdrun_gpu'] == '0', "a host that reports no device still offers the command's default"
    assert values['mdrun_nb'] == 'auto'
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
    expect(page.locator('[data-new-summary=placement]')).to_have_text('Pre-assembled micelle · CHARMM-GUI')
    assert errors == [], errors


def test_the_style_decides_whether_the_belt_is_the_count_or_settles_from_it(dashboard, live_page):
    """With a protein the pre-assembled belt *is* the count asked for; self-assembly starts from it and lets MD
    settle it. The review summary and the chain's own step say which is in force."""
    page, errors = live_page
    serve_catalogue(page, proteins=CATALOG['proteins'])
    open_panel(page, live_page.base_url)
    page.locator('#new-protein').select_option('molecules/1qj8/1qj8.pdb')

    expect(page.locator('[data-new-summary=placement]')).to_have_text('Pre-assembled micelle · CHARMM-GUI')
    expect(page.locator('.new-pdc-placed-node text.title')).to_have_text('3 · Place the belt')

    page.locator('#new-placement').select_option('self-assembly')
    expect(page.locator('[data-new-summary=placement]')).to_have_text('Self-assembly · MemProtMD')
    expect(page.locator('.new-pdc-placed-node text.title')).to_have_text('3 · Self-assemble')
    assert errors == [], errors


def test_the_empty_micelle_branch_works_in_both_styles(dashboard, live_page):
    """No protein stays a valid build for either style: the empty branch is shown, and the review names the style.
    The protein-preparation statement is not shown, because an empty micelle has nothing to prepare."""
    page, errors = live_page
    serve_catalogue(page, proteins=CATALOG['proteins'])
    open_panel(page, live_page.base_url)

    expect(page.locator('#new-empty-block')).to_be_visible()
    expect(page.locator('#new-belt-block')).to_be_hidden()
    expect(page.locator('.new-pdc-prepare-note')).to_be_hidden()

    page.locator('#new-placement').select_option('self-assembly')
    expect(page.locator('#new-empty-block')).to_be_visible()
    expect(page.locator('#new-belt-block')).to_be_hidden()
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
    # The device select is filled from the host's own answer, so it is stubbed: this fixture may or may not have a
    # GPU, and the payload this test pins must not depend on the machine it runs on.
    page.route('**/api/run/devices', lambda route: route.fulfill(json={
        'devices': [{'index': 0, 'name': 'NVIDIA GeForce RTX 4090', 'memory_mib': 24564, 'uuid': 'GPU-aaaa'}],
        'in_use': {}}))

    def queue(route):
        if route.request.method != 'POST':
            route.fallback()
            return
        posted.update(route.request.post_data_json or {})
        route.fulfill(status=201, json={'id': 'pdcqueued1', 'run_type': 'pdc'})

    page.route(re.compile(r'^http://127\.0\.0\.1:\d+/$'), queue)
    open_panel(page, live_page.base_url)
    page.wait_for_function("() => document.querySelectorAll('[name=mdrun_gpu] option').length === 1", timeout=30000)

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
        'backmap': True, 'remove_out_of_micelle': True,
        # The plan's step 1, stated rather than omitted, and on by default: a run that asked for the preparation must not
        # be readable as one that did not -- the same reason the back-map choice is always sent.
        'prepare_protein': True,
        'aggregation_number': 220, 'pdc_assessment_ns': 100, 'pdc_extension_ns': 900, 'pdc_seed': 20260928,
        'salt_molar': 0.15, 'box_margin_nm': 2.0, 'initial_z_nm': 6.0, 'contact_nm': 0.6,
        'selection_threshold_fraction': 0.1,
        'nstlog': 100, 'nstenergy': 100, 'nstxtcout': 100, 'xtc_precision': 1000, 'nstcomm': 100,
        'nstlist': 40, 'verlet_buffer_tolerance': 0.005, 'rlist': 1.35, 'rcoulomb': 1.1, 'rvdw': 1.1,
        'ref_t': 300, 'tau_t': 1.0, 'ref_p': 1.0, 'tau_p': 12.0, 'compressibility': 4.5e-5,
        'mdrun_ntomp': 8, 'mdrun_ranks': 1, 'mdrun_nb': 'auto',
        # The device the run will use, as an ordinary setting: `mdrun_gpu` is the CUDA ordinal the panel selected.
        'mdrun_gpu': 0,
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


#: Two models, in the shape `/api/pdc/models` answers with: a saved mapping, the fit it carries (or `None`), and the
#: sentence the picker shows. Which of them a build can reuse, and which carries a fit, is the server's decision --
#: the panel used to filter `can_reuse` itself and to read a file name into the label.
FITTED = {'file': 'mapping_candidate_fitted.json', 'name': 'DDM_CG_20261021', 'beads': 11,
          'content_hash': 'ab' * 32,
          'fitted': {'revision': 2, 'terms': 26, 'term_kinds': {'bonds': 20, 'angles': 6}, 'engine': 'fast-forward',
                     'created_at': '2026-10-22T06:35:10.928624+00:00', 'scientifically_validated': False},
          'label': 'DDM_CG_20261021 · revision 2 · 11 beads · 26 terms · fitted 2026-10-22'}
DERIVED = {'file': 'mapping_candidate_derived.json', 'name': 'DDM draft from the automatic recogniser', 'beads': 11,
           'content_hash': 'cd' * 32, 'fitted': None,
           'label': 'DDM draft from the automatic recogniser · 11 beads · derived terms'}
MODELS = {'molecule': 'DDM', 'models': [FITTED, DERIVED]}


def test_the_model_picker_lists_the_servers_models_by_what_they_carry(dashboard, live_page):
    """One option per model, grouped fitted-then-derived, each labelled with what it carries and never with its file.

    The mappings a build can reuse, and whether one carries a fitted parameterization, are `/api/pdc/models`'s
    answer: the panel used to filter `validation.can_reuse` itself and to print `${name} · ${file}`. An unusable
    mapping is now one the server never lists (`tests/dashboard/integration/test_pdc_models_api.py`), and the option's
    value is still the file, because that file is the model's identity to the form.
    """
    page, errors = live_page
    serve_catalogue(page)
    page.route(re.compile(r'/api/pdc/models\?'), lambda route: route.fulfill(json=MODELS))
    page.route(re.compile(r'/api/readiness\?'),
               lambda route: route.fulfill(json={'ready': True, 'checks': [], 'blockers': []}))
    open_panel(page, live_page.base_url)

    page.wait_for_function("() => document.querySelectorAll('#new-mapping option').length > 1", timeout=30000)
    expect(page.locator('#new-mapping')).to_have_value(FITTED['file'])
    options = page.evaluate("Array.from(document.querySelectorAll('#new-mapping option')).map(o => o.textContent)")
    assert options == ['No model: a build records centres-only', FITTED['label'], DERIVED['label']], options
    assert not [text for text in options if '.json' in text], f'a mapping file is still what the picker shows: {options}'
    labels = page.evaluate("Array.from(document.querySelectorAll('#new-mapping optgroup')).map(g => g.label)")
    assert labels == ['Models (fitted)', 'Mappings with derived terms'], labels
    assert errors == [], errors


def test_the_empty_micelle_disables_the_protein_views_and_the_removal_gate_redraws_the_chain(
        dashboard, live_page):
    """The two settings the plan adds are visible where they act: no protein means no Bonds/Ribbon and no
    prepare/coarse-grain node; removing the removal pipeline leaves one CG MD leg instead of judge/extend/final."""
    page, errors = live_page
    serve_catalogue(page, proteins=CATALOG['proteins'])
    open_panel(page, live_page.base_url)
    page.locator('#new-protein').select_option('')

    expect(page.locator('[data-new-summary=prepare]')).to_contain_text('skipped · empty micelle')
    expect(page.locator('[data-new-summary=removal]')).to_contain_text('on')
    assert page.locator('.new-pdc-preview-bonds input').is_disabled()
    assert page.locator('.new-pdc-preview-ribbon input').is_disabled()

    page.locator('details.new-pdc-diagram summary').click()
    expect(page.locator('.new-pdc-flow [data-stage=build] text.title')).to_have_text('1 · Build the micelle')
    assert page.locator('.new-pdc-flow [data-stage=prepare]').count() == 0
    assert page.locator('.new-pdc-flow [data-stage=coarse-grain]').count() == 0
    assert page.locator('.new-pdc-flow [data-stage=judge]').count() == 1

    page.locator('[name=remove_out_of_micelle]').uncheck()
    expect(page.locator('[data-new-summary=removal]')).to_contain_text('off')
    expect(page.locator('[data-new-summary=sampling]')).to_contain_text('1000 ns CG MD')
    expect(page.locator('.new-pdc-flow [data-stage=sample] text.title')).to_have_text('3 · CG MD')
    assert page.locator('.new-pdc-flow [data-stage=judge]').count() == 0
    assert page.locator('.new-pdc-flow [data-stage=extend]').count() == 0
    assert page.locator('.new-pdc-flow [data-stage=final-assessment]').count() == 0
    assert errors == [], errors
