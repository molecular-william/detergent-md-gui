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
                   'template': 'molecules/DDM/v1/micelle_template.json', 'registered_type': 'registered-template',
                   'files_present': True, 'missing_files': [],
                   'limitations': ['skeleton placeholder template, not a fitted detergent model']}],
    'proteins': [{'id': 'molecules/1qj8/1qj8.pdb', 'name': '1qj8', 'path': 'molecules/1qj8/1qj8.pdb',
                  'source': 'packaged', 'half_thickness_nm': 1.35}],
    'defaults': {'aggregation_number': 150, 'assessment_ns': 100, 'extension_ns': 900, 'salt_molar': 0.15,
                 'box_margin_nm': 2.0, 'contact_nm': 0.6, 'belt_gap_nm': 0.0,
                 'min_body_gap_nm': 0.3, 'belt_axial_window_nm': 0.75, 'belt_vertical_spread_nm': 4.0,
                 'belt_vertical_spread': 2.0, 'belt_offset_nm': 0.0,
                 'belt_outlier_distance_nm': 0.75,
                 'selection_threshold_fraction': 0.1,
                 'nstlog': 100, 'nstenergy': 100, 'nstxtcout': 100, 'xtc_precision': 1000, 'nstcomm': 100,
                 'verlet_buffer_tolerance': 0.005, 'rlist': 1.35, 'rcoulomb': 1.1, 'rvdw': 1.1,
                 'pdc_nvt_nstlist': 40, 'pdc_nvt_ref_t': 300, 'pdc_nvt_tau_t': 1.0,
                 'pdc_npt_nstlist': 40, 'pdc_npt_ref_t': 300, 'pdc_npt_tau_t': 1.0,
                 'pdc_production_nstlist': 40, 'pdc_production_ref_t': 300, 'pdc_production_tau_t': 1.0,
                 'pdc_production_ref_p': 1.0, 'pdc_production_tau_p': 12.0,
                 'pdc_production_compressibility': 4.5e-5,
                 'minimisation_steps': 200000, 'nvt_ps': 500, 'npt_ps': 4500,
                 'pdc_posres_min': 'yes', 'pdc_posres_nvt': 'no', 'pdc_posres_npt': 'yes',
                 'pdc_minimisation_emtol': 100, 'pdc_minimisation_emstep': 0.001,
                 'pdc_npt_pcoupl': 'c-rescale', 'pdc_npt_pcoupltype': 'isotropic', 'pdc_npt_ref_p': 1.0,
                 'pdc_npt_tau_p': 4.0, 'pdc_npt_compressibility': 4.5e-5,
                 'mdrun_ntomp': 8, 'mdrun_ranks': 1, 'mdrun_nb': 'auto', 'mdrun_update': 'auto'},
}


#: The settings the Stage settings fieldset renders, keyed by the name each input posts. The panel attaches one
#: server-sent info button to each of them; this list is the contract between `setting_help.HELP` and the markup.
STAGE_SETTING_NAMES = (
    'pdc_minimisation_steps', 'pdc_minimisation_emtol', 'pdc_minimisation_emstep', 'pdc_posres_min',
    'pdc_nvt_ps', 'pdc_nvt_dt_fs', 'pdc_nvt_nstlist', 'pdc_nvt_ref_t', 'pdc_nvt_tau_t', 'pdc_posres_nvt',
    'pdc_npt_ps', 'pdc_npt_dt_fs', 'pdc_npt_nstlist', 'pdc_npt_ref_t', 'pdc_npt_tau_t', 'pdc_npt_pcoupl',
    'pdc_npt_pcoupltype', 'pdc_npt_ref_p', 'pdc_npt_tau_p', 'pdc_npt_compressibility', 'pdc_posres_npt',
    'pdc_assessment_ns', 'pdc_assessment_dt_fs', 'pdc_extension_ns', 'pdc_extension_dt_fs',
    'pdc_production_nstlist', 'pdc_production_ref_t', 'pdc_production_tau_t', 'pdc_production_tau_p',
    'pdc_production_ref_p', 'pdc_production_compressibility',
    'nstlog', 'nstenergy', 'nstxtcout', 'xtc_precision', 'nstcomm',
    'verlet_buffer_tolerance', 'rlist', 'rcoulomb', 'rvdw',
    'salt_molar', 'pdc_seed', 'box_margin_nm', 'initial_z_nm', 'contact_nm', 'belt_gap_nm',
    'min_body_gap_nm', 'belt_axial_window_nm', 'belt_vertical_spread_nm', 'belt_offset_nm',
    'belt_outlier_distance_nm',
    'initial_x_nm', 'initial_y_nm',
    'selection_threshold_fraction',
    'protein_vsite', 'mdrun_gpu', 'mdrun_ntomp', 'mdrun_ranks', 'mdrun_cpt', 'mdrun_nb', 'mdrun_update',
)

#: One sentence per setting, in the shape `/api/pdc/catalog` answers with. The sentences are the fixture's, so the
#: text is not the panel's claim; that every setting gets its own accessible button is.
CATALOG['help'] = {name: f'What {name} means.' for name in STAGE_SETTING_NAMES}
CATALOG['help_sources'] = {'mdp': 'https://manual.gromacs.org/', 'project': 'Dashboard text, not GROMACS'}


def control_label(page, name):
    """The one label a control sits in: the info button and any Default button are its siblings."""
    return page.locator('label').filter(has=page.locator(f'[name={name}]')).first


def open_panel(page, base_url):
    # The shape card and the preset bar read routes this lane's server does not serve yet; empty answers keep the
    # form's existing claims independent of those features while still exercising their mount.
    browser.serve_files(page,
                        (re.compile(r'/api/pdc/conformations/runs'), {'runs': []}),
                        (re.compile(r'/api/pdc/conformations/libraries'), {'libraries': []}),
                        (re.compile(r'/api/setting-presets'), {'presets': [], 'default': None}))
    opened = browser.open_pdc_new_run(page, base_url)
    # Mount fills the catalogue defaults, the seed and the device list after the detergent options the helper
    # waits for. A case that reads those controls has to wait for the panel, not for its first fetch.
    page.wait_for_function("() => document.querySelector('#new-run')?.getAttribute('aria-busy') !== 'true'",
                           timeout=30000)
    return opened


def serve_catalogue(page, proteins=None):
    """The catalogue the panel reads, with the protein list the case needs."""
    entries = [dict(item) for item in CATALOG['templates']]
    page.route(re.compile(r'/api/pdc/catalog'),
               lambda route: route.fulfill(json={**CATALOG, 'templates': entries,
                                                 'proteins': list(proteins or [])}))


def enter_seed(page, value):
    """The seed is one of the Stage settings fieldset's own controls now."""
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
    # The stage settings are editors now, and every one of them starts collapsed so the form opens as a summary a
    # reader scans before opening the stage whose numbers they mean to change.
    expect(page.locator('#run-form .new-pdc-stages')).to_be_visible()
    for stage in ('minimisation', 'nvt', 'npt', 'production'):
        assert not page.locator(f'#run-form details[data-stage={stage}]').evaluate('el => el.open'), stage
    page.locator('#run-form details[data-stage=production] summary').click()
    expect(page.locator('#new-assessment-ns')).to_be_visible()
    expect(page.locator('#new-extension-ns')).to_be_visible()
    # There is no separate fold or Run configuration card any more: the run configuration and the starting box are
    # groups of the same Run and stage settings fieldset.
    assert page.locator('#new-advanced').count() == 0, 'the Other run options fold is still in the document'
    assert page.locator('#run-form fieldset.new-pdc-stages .new-option-group').count() == 7
    fieldset = page.locator('#run-form fieldset.new-pdc-stages')
    for name in ('box_margin_nm', 'initial_z_nm', 'initial_x_nm', 'initial_y_nm',
                 'aggregation_number', 'pdc_placement_mode', 'remove_out_of_micelle', 'backmap'):
        assert fieldset.locator(f'[name={name}]').count() == 1, f'{name} is not in the merged settings card'
    # Matched on the control's own label text, not a page-wide substring: each label now carries the server's
    # explanation in its info tooltip, and those sentences mention the other controls by name.
    for name, start in (('initial_x_nm', 'Initial box x'), ('initial_y_nm', 'Initial box y'),
                        ('initial_z_nm', 'Initial box z'), ('box_margin_nm', 'Box margin'),
                        ('belt_vertical_spread_nm', 'Vertical spread'),
                        ('belt_outlier_distance_nm', 'Outlier distance')):
        label = control_label(page, name)
        head = label.evaluate("el => el.firstChild?.textContent?.trim() || ''")
        assert head.startswith(start), f'{name} is labelled {head!r}, not {start!r}'
    for name in ('pdc_seed', 'salt_molar', 'box_margin_nm', 'initial_z_nm', 'contact_nm',
                 'selection_threshold_fraction', 'nstlog', 'nstenergy', 'nstxtcout', 'xtc_precision',
                 'nstcomm', 'verlet_buffer_tolerance', 'rlist', 'rcoulomb', 'rvdw',
                 'pdc_nvt_nstlist', 'pdc_nvt_ref_t', 'pdc_nvt_tau_t',
                 'pdc_npt_nstlist', 'pdc_npt_ref_t', 'pdc_npt_tau_t',
                 'pdc_production_nstlist', 'pdc_production_ref_t', 'pdc_production_tau_t',
                 'pdc_production_tau_p', 'pdc_production_ref_p', 'pdc_production_compressibility',
                 'mdrun_ntomp', 'mdrun_ranks', 'mdrun_update',
                 'protein_vsite', 'pdc_nvt_dt_fs', 'pdc_npt_dt_fs', 'pdc_assessment_dt_fs',
                 'pdc_extension_dt_fs',
                 'pdc_minimisation_steps', 'pdc_minimisation_emtol', 'pdc_minimisation_emstep',
                 'pdc_posres_min', 'pdc_posres_nvt', 'pdc_posres_npt',
                 'pdc_npt_pcoupl', 'pdc_npt_pcoupltype', 'pdc_npt_ref_p', 'pdc_npt_tau_p',
                 'pdc_npt_compressibility'):
        assert page.locator(f'[name={name}]').count() == 1, f'{name} is not offered, or is offered twice'
    # The run-wide physics controls are gone with their group: each leg states its own.
    for name in ('nstlist', 'ref_t', 'tau_t', 'ref_p', 'tau_p', 'compressibility'):
        assert page.locator(f'[name={name}]').count() == 0, f'the retired run-wide {name} is still offered'
    assert 'Thermostat and barostat' not in panel_text, 'the shared thermostat group is still offered'
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


def test_the_belt_and_box_labels_carry_their_unit_and_the_explanation_is_in_the_info_icon(dashboard, live_page):
    """A label says the name and its unit; what the number does is the server-sent info button's tooltip.

    The belt's five numbers and the four starting-box controls are measured, because those are the labels the user
    asked to shorten: a subtext like "nm · between detergents" is gone, replaced by "nm" beside the name with the
    sentence in the button. The old paragraph under the starting box and its per-axis note line are gone too.
    """
    page, errors = live_page
    serve_catalogue(page, proteins=CATALOG['proteins'])
    open_panel(page, live_page.base_url)
    page.locator('#new-protein').select_option('molecules/1qj8/1qj8.pdb')

    for name in ('belt_gap_nm', 'min_body_gap_nm', 'belt_axial_window_nm', 'belt_vertical_spread_nm',
                 'belt_offset_nm', 'initial_x_nm', 'initial_y_nm', 'initial_z_nm', 'box_margin_nm'):
        label = control_label(page, name)
        assert label.locator('.hint').inner_text().strip() == 'nm', name
        assert label.locator('button.info-btn').count() == 1, f'{name} has no info button'
        assert len(label.locator('.setting-tip').inner_text().strip()) > 10, f'{name} has no explanation'
        assert '·' not in label.locator('.hint').inner_text(), f'{name} still carries a folded explanation'

    assert page.locator('#run-form').get_by_text(
        'The starting box, and the cell the preview draws', exact=False).count() == 0
    assert page.locator('.new-pdc-box-note').count() == 0

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


def test_the_preview_viewer_is_tall_enough_to_read(dashboard, live_page):
    """The 3D box is measured, not assumed: a host with the old 320 px height would fail this by 140 px."""
    page, errors = live_page
    open_panel(page, live_page.base_url)
    box = page.locator('#run-form .new-pdc-preview-viewer').bounding_box()
    assert box['height'] >= 460, f'the preview viewer is only {box["height"]:.0f} px tall'
    assert errors == [], errors


def test_the_validation_workspace_still_gets_the_single_molecule_panel(dashboard, live_page):
    """The other workspace is unchanged: its heading, its own controls, and no detergent list.

    The single-molecule panel now offers an AA run and a CG run, and a CG run picks a *parameterization* of the
    molecule. `Method` and the AA-reference picker are gone (the parameterization names the AA source), and
    `Bonded parameters`/`Bonded workflow` never belonged here.
    """
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/new-run')
    page.get_by_role('tab', name='New run', exact=True).click()
    expect(page.locator('#new h2')).to_have_text('Single Molecule Simulations')
    panel_text = page.locator('#new').inner_text()
    for label in ('Run type', 'Parameterization', 'AA source'):
        assert label in panel_text, f'{label} is missing from the single-molecule panel'
    for label in ('Bonded parameters', 'Bonded workflow'):
        assert label not in panel_text, f'{label} is still offered on the single-molecule panel'
    assert page.locator('#new-detergent').count() == 0, 'the pdc fieldset is rendered in the other workspace'
    assert page.locator('#new-import').count() == 0

    # And its two halves are still side by side, with the stage-settings half the wider one: this is the AA form,
    # whose settings sit four across (`layout.css` scopes that split to the form carrying the stage editors; the pdc
    # form's own halves are measured 50/50 by the test above).
    form = page.locator('#run-form').bounding_box()
    inputs = page.locator('.new-run-inputs').bounding_box()
    settings = page.locator('.new-run-settings').bounding_box()
    assert settings['x'] >= inputs['x'] + inputs['width'] - 1, (inputs, settings)
    assert settings['width'] > inputs['width'] + 40, (inputs, settings)
    assert settings['x'] + settings['width'] <= form['x'] + form['width'] + 1, 'the right half leaves the form'
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

    # Emptied by hand, the gate names the seed again.
    page.locator('[name=pdc_seed]').fill('')
    expect(page.locator('#launch-blocker')).to_contain_text('Choose a random seed')
    expect(page.locator('#start-run')).to_be_disabled()
    expect(page.locator('#review-status')).to_have_text('Action required')
    assert errors == [], errors


def test_the_groups_are_sections_inside_the_run_and_stage_settings(dashboard, live_page):
    """The old Other run options fold is gone; its groups, the run configuration and the starting box are sections.

    A group that merely exists proves little -- the fold rendered them too. They are asserted to be inside the
    fieldset, after the four stage editors, each with an h4.new-option-title over a settings grid, and the page must
    still fit a phone: at 390 px the groups wrap rather than widen the document. The shared thermostat and barostat
    group is gone: those numbers are stated by the leg they act on.
    """
    page, errors = live_page
    page.route('**/api/run/devices', lambda route: route.fulfill(
        json={'devices': [{'index': 0, 'name': 'NVIDIA GeForce RTX 4090', 'memory_mib': 24564, 'uuid': 'GPU-aaaa'}],
              'in_use': {}}))
    open_panel(page, live_page.base_url)

    fieldset = page.locator('#run-form fieldset.new-pdc-stages')
    assert page.locator('#new-advanced').count() == 0, 'the Other run options fold is still in the document'
    groups = fieldset.locator(':scope > section.new-option-group')
    # Seven: the run configuration and the starting box were folded in on 2026-11-24, and joined by the five groups
    # the retired Other run options fold used to hold.
    assert groups.count() == 7, 'the option groups are not sections of the fieldset'
    assert page.locator('#run-form .new-option-group [name]').count() == 36, 'a control was lost with the fold'
    for index in range(7):
        group = groups.nth(index)
        expect(group.locator(':scope > h4.new-option-title')).to_be_visible()
    # The five grid groups keep their grid; the two merged ones state their own grids (the pair, the belt grid, the box
    # grid) because those have to pair controls the pairing tests measure.
    assert fieldset.locator(':scope > section.new-option-group > div.settings-grid').count() == 5
    # The order reads as the run is configured: the merged run configuration and starting box first, then the five
    # stage-setting groups after the last (production) stage editor.
    titles = page.evaluate("""() => [...document.querySelectorAll(
        '#run-form fieldset.new-pdc-stages > section.new-option-group')]
        .map(group => group.querySelector(':scope > h4').textContent.trim())""")
    assert titles[0] in ('Detergent belt and sampling', 'Micelle and sampling'), titles
    assert titles[1:] == ['Starting box',
                      'Output cadence', 'Neighbour search and cutoffs', 'Salt, seed and box',
                      'Back-map', 'Execution'], titles
    after_stages = page.evaluate("""() => {
        const last = [...document.querySelectorAll('#run-form details.stage-editor')].pop();
        return [...document.querySelectorAll('#run-form fieldset.new-pdc-stages > section.new-option-group')]
            .filter(group => last.compareDocumentPosition(group) & Node.DOCUMENT_POSITION_FOLLOWING)
            .map(group => group.querySelector(':scope > h4').textContent.trim()); }""")
    assert after_stages == ['Output cadence', 'Neighbour search and cutoffs', 'Salt, seed and box',
                            'Back-map', 'Execution'], after_stages

    page.set_viewport_size({'width': 390, 'height': 900})
    browser.assert_no_horizontal_scroll(page)
    assert errors == [], errors


def test_the_stage_settings_start_on_the_catalogues_own_numbers(dashboard, live_page):
    """Every stage box starts on the number the adapter's defaults state, and only the four timesteps stay blank.

    A blank timestep is not a missing value: it is that leg's reviewed profile dt, which the run records no override
    for. The durations the panel never showed a starting value for (the equilibration pair) are filled here, which is
    the alias this change had to repair: they used to render blank while the run used 500 and 4 500 ps.
    """
    page, errors = live_page
    serve_catalogue(page, proteins=CATALOG['proteins'])
    page.route('**/api/run/devices', lambda route: route.fulfill(json={'devices': [], 'in_use': {}}))
    open_panel(page, live_page.base_url)

    values = page.evaluate("""() => Object.fromEntries(
        [...document.querySelectorAll('#run-form .new-pdc-stages [name]')].map(el => [el.name, el.value]))""")
    assert values, 'the stage settings render no inputs'
    assert (values['pdc_nvt_ps'], values['pdc_npt_ps']) == ('500', '4500')
    assert values['pdc_minimisation_steps'] == '200000'
    assert (values['pdc_minimisation_emtol'], values['pdc_minimisation_emstep']) == ('100', '0.001')
    assert (values['pdc_posres_min'], values['pdc_posres_nvt'], values['pdc_posres_npt']) == ('yes', 'no', 'yes')
    assert (values['pdc_npt_pcoupl'], values['pdc_npt_pcoupltype']) == ('c-rescale', 'isotropic')
    assert tuple(float(values[name]) for name in
                 ('pdc_npt_ref_p', 'pdc_npt_tau_p', 'pdc_npt_compressibility')) == (1.0, 4.0, 4.5e-5)
    # Each leg states its own neighbour list, temperature and couplings; the run-wide group that used to carry them
    # is gone, so these are the only controls that hold those numbers.
    assert tuple(values[name] for name in ('pdc_nvt_nstlist', 'pdc_nvt_ref_t', 'pdc_nvt_tau_t')) == ('40', '300', '1')
    assert tuple(values[name] for name in ('pdc_npt_nstlist', 'pdc_npt_ref_t', 'pdc_npt_tau_t')) == ('40', '300', '1')
    assert tuple(values[name] for name in
                 ('pdc_production_nstlist', 'pdc_production_ref_t', 'pdc_production_tau_t')) == ('40', '300', '1')
    assert tuple(float(values[name]) for name in
                 ('pdc_production_ref_p', 'pdc_production_tau_p', 'pdc_production_compressibility')) == \
        (1.0, 12.0, 4.5e-5)
    assert values['mdrun_update'] == 'auto'
    # The four reviewed-profile timesteps, the three starting-box axes (blank is the derived cell) and the run label
    # are the only blanks; the belt's five numbers now all open on a stated default.
    # The label is a run name, not a setting, and its suggestion lands after the panel's own fetch: it is excluded
    # rather than raced.
    assert {name for name, value in values.items() if value in ('', None) and name != 'label'} == {
        'pdc_nvt_dt_fs', 'pdc_npt_dt_fs', 'pdc_assessment_dt_fs', 'pdc_extension_dt_fs',
        'initial_x_nm', 'initial_y_nm', 'initial_z_nm'}, values
    assert errors == [], errors


def test_each_stage_editor_states_what_it_holds_even_while_closed(dashboard, live_page):
    """The facts line is the label the paragraphs became: the duration, the timestep once stated, and the window."""
    page, errors = live_page
    serve_catalogue(page, proteins=CATALOG['proteins'])
    open_panel(page, live_page.base_url)

    page.wait_for_function(
        "() => document.querySelector('.new-pdc-stage-facts[data-stage=nvt]')?.textContent.length", timeout=30000)
    facts = page.evaluate("""() => Object.fromEntries(
        [...document.querySelectorAll('.new-pdc-stage-facts')].map(el => [el.dataset.stage, el.textContent]))""")
    assert facts['minimisation'] == '200 000 steps · 100 kJ/mol/nm · 0.001 nm · restrained', facts
    assert facts['nvt'] == '500 ps · free', facts
    assert facts['npt'] == '4 500 ps · restrained', facts
    # One editor holds both CG production durations; the timestep is stated per leg, so the line names it per leg
    # once the two differ.
    assert facts['production'] == '100 ns assessment · 900 ns extension', facts

    # The three boxes of a dynamics stage: the duration and its own timestep imply the step count, at the same
    # arithmetic the adapter prepares with (steps = duration / dt). The editor opens first.
    page.locator('#run-form details[data-stage=nvt] summary').click()
    page.locator('[name=pdc_nvt_ps]').fill('250')
    page.locator('[name=pdc_nvt_dt_fs]').fill('5')
    expect(page.locator('.new-pdc-stage-facts[data-stage=nvt]')).to_have_text('250 ps · 5 fs · 50 000 steps · free')
    expect(page.locator('.pdc-steps[data-stage=nvt]')).to_have_value('50000')
    # Editing the count back-solves the duration at that stage's own timestep.
    page.locator('.pdc-steps[data-stage=nvt]').fill('10000')
    expect(page.locator('[name=pdc_nvt_ps]')).to_have_value('50')
    expect(page.locator('.new-pdc-stage-facts[data-stage=nvt]')).to_have_text('50 ps · 5 fs · 10 000 steps · free')
    # The restored window shows on the same line, so a closed editor still says whether it holds the backbone.
    page.locator('[name=pdc_posres_nvt]').select_option('yes')
    expect(page.locator('.new-pdc-stage-facts[data-stage=nvt]')).to_have_text(
        '50 ps · 5 fs · 10 000 steps · restrained')
    # Zero duration is a leg the run skips, and the line says so instead of 0 ps.
    page.locator('[name=pdc_nvt_ps]').fill('0')
    expect(page.locator('.new-pdc-stage-facts[data-stage=nvt]')).to_contain_text('skipped')
    # A blank timestep leaves the count unknown to the browser, and says why.
    page.locator('[name=pdc_nvt_dt_fs]').fill('')
    steps = page.locator('.pdc-steps[data-stage=nvt]')
    expect(steps).to_have_value('')
    assert steps.evaluate('el => el.readOnly')
    assert 'timestep' in steps.get_attribute('title')

    # The production line states one shared timestep once when both legs use it, and the total step count they
    # imply: 100 ns at 20 fs is 5 000 000 steps and 900 ns at 20 fs is 45 000 000.
    page.locator('#run-form details[data-stage=production] summary').click()
    page.locator('[name=pdc_assessment_dt_fs]').fill('20')
    page.locator('[name=pdc_extension_dt_fs]').fill('20')
    expect(page.locator('.new-pdc-stage-facts[data-stage=production]')).to_have_text(
        '100 ns assessment · 900 ns extension · 20 fs · 50 000 000 steps')
    # A different timestep for the restarted extension names its own leg rather than claiming both.
    page.locator('[name=pdc_extension_dt_fs]').fill('40')
    expect(page.locator('.new-pdc-stage-facts[data-stage=production]')).to_have_text(
        '100 ns assessment · 900 ns extension · 20 fs assessment · 40 fs extension · 27 500 000 steps')
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


def test_the_belt_packing_controls_start_on_their_defaults_and_only_show_for_a_belt(dashboard, live_page):
    """The belt numbers are belt settings: defaults, Default buttons, hidden in self-assembly, and carried in the
    preview query as the run's own settings (including the outlier distance)."""
    page, errors = live_page
    serve_catalogue(page, proteins=CATALOG['proteins'])
    page.route(re.compile(r'/api/pdc/preview/placement'),
               lambda route: route.fulfill(json={'valid': False, 'reasons': ['the fixture draws no frame']}))
    open_panel(page, live_page.base_url)
    page.locator('#new-protein').select_option('molecules/1qj8/1qj8.pdb')

    gap = page.locator('[name=belt_gap_nm]')
    body = page.locator('[name=min_body_gap_nm]')
    axial = page.locator('[name=belt_axial_window_nm]')
    vertical = page.locator('[name=belt_vertical_spread_nm]')
    outlier = page.locator('[name=belt_outlier_distance_nm]')
    expect(gap).to_have_value('0')
    expect(body).to_have_value('0.3')
    expect(axial).to_have_value('0.75')
    # The vertical spread is a stated nm with a 4 nm default now, so it opens on 4 and its Default button restores it
    # beside the other four.
    expect(vertical).to_have_value('4')
    expect(vertical).not_to_have_attribute('placeholder', re.compile(r'detergent'))
    expect(outlier).to_have_value('0.75')
    gap.fill('0.8')
    body.fill('0.5')
    axial.fill('1.2')
    vertical.fill('2.5')
    outlier.fill('1.4')
    for name in ('belt_gap_nm', 'min_body_gap_nm', 'belt_axial_window_nm', 'belt_vertical_spread_nm',
                 'belt_outlier_distance_nm'):
        control_label(page, name).locator('button.pdc-default').click()
    expect(gap).to_have_value('0')
    expect(body).to_have_value('0.3')
    expect(axial).to_have_value('0.75')
    expect(vertical).to_have_value('4')
    expect(outlier).to_have_value('0.75')

    offset = page.locator('[name=belt_offset_nm]')
    expect(offset).to_have_value('0')
    offset.fill('0.5')
    control_label(page, 'belt_offset_nm').locator('button.pdc-default').click()
    expect(offset).to_have_value('0')

    # They act on a pre-assembled belt: self-assembly hides them, lattice brings them back, and the values still post
    # either way (the adapter ignores them outside a belt).
    for name in ('belt_gap_nm', 'min_body_gap_nm', 'belt_axial_window_nm', 'belt_vertical_spread_nm',
                 'belt_outlier_distance_nm'):
        expect(control_label(page, name)).to_be_visible()
    page.locator('#new-placement').select_option('self-assembly')
    for name in ('belt_gap_nm', 'min_body_gap_nm', 'belt_axial_window_nm', 'belt_vertical_spread_nm',
                 'belt_outlier_distance_nm'):
        expect(control_label(page, name)).to_be_hidden()
    page.locator('#new-placement').select_option('lattice')

    gap.fill('0.5')
    body.fill('0.4')
    axial.fill('1.1')
    vertical.fill('2.2')
    outlier.fill('1.2')
    with page.expect_request(re.compile(r'/api/pdc/preview/placement')) as captured:
        page.locator('.new-pdc-preview-derive').click()
    url = captured.value.url
    assert ('belt_gap_nm=0.5' in url and 'min_body_gap_nm=0.4' in url
            and 'belt_axial_window_nm=1.1' in url and 'belt_vertical_spread_nm=2.2' in url
            and 'belt_outlier_distance_nm=1.2' in url), url
    assert errors == [], errors


def test_the_run_label_is_suggested_until_the_reader_types_one_and_the_suggestion_is_posted(dashboard, live_page):
    """The suggestion names what the run builds, moves with the inputs, is stored only once the reader writes one,
    is regenerated by its own button after an edit, and travels with the payload.
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
    page.wait_for_function("() => document.querySelector('[name=label]')?.value !== ''", timeout=30000)
    page.locator('#new-count').fill('192')
    page.locator('#new-count').press('Tab')

    # The button sits beside the input; generating is its own action, not something the reader has to know about.
    assert page.locator('label:has([name=label]) .new-pdc-suggest-label').count() == 1
    expect(page.locator('.new-pdc-suggest-label')).to_be_visible()
    input_box = page.locator('[name=label]').bounding_box()
    button_box = page.locator('.new-pdc-suggest-label').bounding_box()
    assert button_box['x'] > input_box['x'] + 10, (input_box, button_box)
    assert abs((input_box['y'] + input_box['height'] / 2) - (button_box['y'] + button_box['height'] / 2)) <= 8, \
        (input_box, button_box)

    # No protein: the micelle's own name. A protein adds the entry's catalogue name where `micelle` stood.
    expect(page.locator('[name=label]')).to_have_value('DDM_micelle_192_1conf_1us')
    page.locator('#new-protein').select_option('molecules/1qj8/1qj8.pdb')
    expect(page.locator('[name=label]')).to_have_value('DDM_1qj8_192_1conf_1us')

    # A suggestion is not the reader's value: it is not in the stored form, but it is what the field carries, so it
    # is what the payload posts.
    stored = page.evaluate("() => JSON.parse(localStorage.getItem('ddm.pdc-form') || '{}')")
    assert 'label' not in stored, stored
    expect(page.locator('#start-run')).to_be_enabled()
    page.locator('#start-run').click()
    expect(page.locator('#notice')).to_contain_text('Run queued.', timeout=30000)
    assert posted['label'] == 'DDM_1qj8_192_1conf_1us', posted
    # Queuing a run leaves the reader on the form: the New run tab stays selected and its panel stays visible.
    expect(page.locator('#tab-new')).to_have_attribute('aria-selected', 'true')
    expect(page.locator('#new')).to_be_visible()

    # Typing stops the updates: the form moves on, the label the reader wrote does not.
    page.locator('[name=label]').fill('my run')
    page.locator('#new-count').fill('200')
    page.locator('#new-count').press('Tab')
    expect(page.locator('[name=label]')).to_have_value('my run')
    stored = page.evaluate("() => JSON.parse(localStorage.getItem('ddm.pdc-form') || '{}')")
    assert stored.get('label') == 'my run', stored

    # The button regenerates the name after that edit, for the inputs as they now stand.
    page.locator('.new-pdc-suggest-label').click()
    expect(page.locator('[name=label]')).to_have_value('DDM_1qj8_200_1conf_1us')
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
    # A stated starting cell travels under the adapter's advertised names; a blank pair (below, in the big payload
    # test) records no key at all, so the run derives its footprint rather than reading a zero.
    page.locator('[name=initial_x_nm]').fill('11.5')
    page.locator('[name=initial_y_nm]').fill('12.5')
    # Leaving the field settles the readiness check the input events scheduled; clicking while one is pending hits a
    # disabled button, as the big payload test also notes.
    page.locator('[name=initial_y_nm]').press('Tab')
    expect(page.locator('#start-run')).to_be_enabled()
    page.locator('#start-run').click()

    expect(page.locator('#notice')).to_contain_text('Run queued.', timeout=30000)
    assert posted['pdc_placement_mode'] == 'self-assembly', posted
    assert (posted['initial_x_nm'], posted['initial_y_nm']) == (11.5, 12.5), posted
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
    # Each dynamics stage carries its own timestep beside its duration; stated, all four post under the adapter's
    # advertised names. Every editor starts collapsed, so each one is opened before its controls are touched.
    for stage in ('minimisation', 'nvt', 'npt', 'production'):
        page.locator(f'#run-form details[data-stage={stage}] summary').click()
    page.locator('[name=pdc_nvt_dt_fs]').fill('10')
    page.locator('[name=pdc_npt_dt_fs]').fill('10')
    page.locator('[name=pdc_assessment_dt_fs]').fill('20')
    page.locator('[name=pdc_extension_dt_fs]').fill('20')
    page.locator('[name=pdc_nvt_ps]').fill('100')
    page.locator('[name=pdc_npt_ps]').fill('200')
    # The minimisation's own boxes and one restraint choice per leg: each editor states its own window, and the
    # selects post their values under the adapter's advertised names.
    page.locator('[name=pdc_minimisation_steps]').fill('400000')
    page.locator('[name=pdc_minimisation_emtol]').fill('250')
    page.locator('[name=pdc_minimisation_emstep]').fill('0.002')
    for leg in ('min', 'nvt', 'npt'):
        page.locator(f'[name=pdc_posres_{leg}]').select_option('no')
    page.locator('[name=pdc_npt_pcoupl]').select_option('berendsen')
    page.locator('[name=pdc_npt_pcoupltype]').select_option('semiisotropic')
    page.locator('[name=pdc_npt_ref_p]').fill('2.5')
    page.locator('[name=pdc_npt_tau_p]').fill('8')
    page.locator('[name=pdc_npt_compressibility]').fill('0.0001')
    # Leaving the field runs the readiness check that re-enables the button; clicking while it is pending would hit a
    # disabled button (a number input's change fires on blur, before the click).
    page.locator('[name=pdc_extension_dt_fs]').press('Tab')
    expect(page.locator('#start-run')).to_be_enabled()
    page.locator('#start-run').click()

    expect(page.locator('#notice')).to_contain_text('Run queued.', timeout=30000)
    assert posted == {
        'run_type': 'pdc', 'molecule_id': 'DDM', 'template': 'molecules/DDM/v1/micelle_template.json',
        'protein': 'molecules/1qj8/1qj8.pdb', 'label': 'pdc panel test', 'pdc_placement_mode': 'lattice',
        # Both pipeline toggles start off: the run is coarse-grained and has no removal chain unless asked.
        'backmap': False, 'remove_out_of_micelle': False,
        # The launch button's own choice, like the validation panel's: Queue is the default action.
        'gpu_sharing': 'queue',
        # The cell shape a run states: the historical rectangular box is the default, and it travels as a choice.
        'box_shape': 'rectangular',
        # The back-map's pdb2gmx choice is stated always, like the back-map toggle: a run that asked for virtual sites
        # must not be readable as one that used the default.
        'protein_vsite': 'none',
        # The plan's step 1, stated rather than omitted, and on by default: a run that asked for the preparation must not
        # be readable as one that did not -- the same reason the back-map choice is always sent.
        'prepare_protein': True,
        'aggregation_number': 220, 'pdc_nvt_ps': 100, 'pdc_npt_ps': 200,
        'pdc_assessment_ns': 100, 'pdc_extension_ns': 900, 'pdc_seed': 20260928,
        'salt_molar': 0.15, 'box_margin_nm': 2.0, 'contact_nm': 0.6,
        'belt_gap_nm': 0.0,
        # The form opens on the belt's stated defaults now, so all five numbers post: the vertical spread is the 4 nm
        # default and the offset is 0.
        'belt_vertical_spread_nm': 4.0, 'belt_offset_nm': 0.0, 'belt_outlier_distance_nm': 0.75,
        'min_body_gap_nm': 0.3, 'belt_axial_window_nm': 0.75,
        'selection_threshold_fraction': 0.1,
        'nstlog': 100, 'nstenergy': 100, 'nstxtcout': 100, 'xtc_precision': 1000, 'nstcomm': 100,
        'pdc_nvt_dt_fs': 10, 'pdc_npt_dt_fs': 10,
        'pdc_assessment_dt_fs': 20, 'pdc_extension_dt_fs': 20,
        'pdc_posres_min': 'no', 'pdc_posres_nvt': 'no', 'pdc_posres_npt': 'no',
        'pdc_npt_pcoupl': 'berendsen', 'pdc_npt_pcoupltype': 'semiisotropic',
        'pdc_minimisation_steps': 400000, 'pdc_minimisation_emtol': 250, 'pdc_minimisation_emstep': 0.002,
        'pdc_npt_ref_p': 2.5, 'pdc_npt_tau_p': 8, 'pdc_npt_compressibility': 0.0001,
        'verlet_buffer_tolerance': 0.005, 'rlist': 1.35, 'rcoulomb': 1.1, 'rvdw': 1.1,
        # The physics each leg states for itself: the retired run-wide names are not on the payload at all.
        'pdc_nvt_nstlist': 40, 'pdc_nvt_ref_t': 300, 'pdc_nvt_tau_t': 1,
        'pdc_npt_nstlist': 40, 'pdc_npt_ref_t': 300, 'pdc_npt_tau_t': 1,
        'pdc_production_nstlist': 40, 'pdc_production_ref_t': 300, 'pdc_production_tau_t': 1,
        'pdc_production_tau_p': 12, 'pdc_production_ref_p': 1, 'pdc_production_compressibility': 4.5e-5,
        'mdrun_ntomp': 8, 'mdrun_ranks': 1, 'mdrun_nb': 'auto',
        # The update scheme is stated always, so a run that asked for one is not readable as one that took the
        # profile's own.
        'mdrun_update': 'auto',
        # The checkpoint cadence is a run setting with a stated default, so the panel sends the number it shows:
        # ten minutes is this project's cadence and the run's command records it rather than relying on a default.
        'mdrun_cpt': 10,
        # The device the run will use, as an ordinary setting: `mdrun_gpu` is the CUDA ordinal the panel selected.
        'mdrun_gpu': 0,
    }, posted
    # A blank x/y is not a zero and not a number: the run derives the footprint exactly as it did before the fields
    # existed. `test_the_panel_sends_the_initialisation_style_it_shows` pins the stated pair.
    assert 'initial_x_nm' not in posted and 'initial_y_nm' not in posted, posted
    assert errors == [], errors


EXTENT = {'protein': {'name': '1qj8'}, 'dimensions_nm': {'x': 5.2, 'y': 4.8, 'z': 6.0},
          'initial_box_nm': [9.2, 8.8, 6.0], 'rule': 'initial'}


def test_the_seed_generate_button_draws_a_valid_integer_and_the_form_follows(dashboard, live_page):
    """Generate draws a seed from 1 through today's date and fires the events the gate, store and review listen for."""
    page, errors = live_page
    serve_catalogue(page, proteins=CATALOG['proteins'])
    page.route(re.compile(r'/api/readiness\?'), lambda route: route.fulfill(json={'ready': True, 'checks': [], 'blockers': []}))
    open_panel(page, live_page.base_url)
    page.locator('#new-protein').select_option('molecules/1qj8/1qj8.pdb')

    today = page.evaluate("() => { const d = new Date(); const pad = n => String(n).padStart(2, '0');"
                          "return Number(`${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}`); }")
    seed = page.locator('[name=pdc_seed]')
    # A value the button can never draw, so "it changed" is not a coincidence of the random draw.
    seed.fill('2000000000')
    page.locator('.pdc-generate-seed').click()

    drawn = int(seed.input_value())
    assert 1 <= drawn <= today, (drawn, today)
    expect(page.locator('[data-new-summary=seed]')).to_have_text(str(drawn))
    stored = page.evaluate("() => JSON.parse(localStorage.getItem('ddm.pdc-form') || '{}')")
    assert stored.get('pdc_seed') == str(drawn), stored
    assert errors == [], errors


def test_the_stage_grids_hold_three_boxes_a_row_and_never_scroll_sideways(dashboard, live_page):
    """Measured: three across at the wide viewport, two below the shared 1100 px breakpoint, one on a phone."""
    page, errors = live_page
    open_panel(page, live_page.base_url)
    page.evaluate("() => document.querySelectorAll('#run-form details.stage-editor').forEach(el => { el.open = true; })")

    def grids():
        return page.evaluate("""() => Array.from(document.querySelectorAll('#run-form .new-pdc-stages .settings-grid'))
            .map(grid => Array.from(grid.children).filter(el => !el.hidden).map(el => {
              const r = el.getBoundingClientRect();
              return {x: r.x, y: r.y, width: r.width};
            }))""")

    def rows(cells):
        """The number of cells on the first row: those sharing its top."""
        return sum(1 for cell in cells if abs(cell['y'] - cells[0]['y']) <= 2)

    wide = [cells for cells in grids() if len(cells) >= 3]
    assert wide, 'the stage settings render no grid of three controls'
    for cells in wide:
        assert rows(cells) == 3, f'a stage grid is not three across: {cells}'
        xs = [cell['x'] for cell in cells[:3]]
        assert xs[0] < xs[1] < xs[2], f'the first three boxes do not march left to right: {xs}'

    page.set_viewport_size({'width': 1000, 'height': 900})
    for cells in [cells for cells in grids() if len(cells) >= 3]:
        assert rows(cells) == 2, f'a stage grid is not two across below 1100 px: {cells}'

    page.set_viewport_size({'width': 390, 'height': 900})
    for cells in grids():
        if len(cells) < 2:
            continue
        assert rows(cells) == 1, f'a stage grid is not stacked on a phone: {cells}'
    browser.assert_no_horizontal_scroll(page)
    assert errors == [], errors


def test_the_protein_card_states_its_size_and_the_initial_box_and_the_refusal(dashboard, live_page):
    """The two lines are the extent route's answer: the protein's dimensions and the box the build starts from."""
    page, errors = live_page
    serve_catalogue(page, proteins=CATALOG['proteins'])
    state = {'status': 200, 'body': EXTENT}
    page.route(re.compile(r'/extent'), lambda route: route.fulfill(status=state['status'], json=state['body']))
    open_panel(page, live_page.base_url)

    # No protein: there is nothing to measure, so neither line is shown.
    expect(page.locator('.new-pdc-protein-size')).to_be_hidden()
    expect(page.locator('.new-pdc-box-estimate')).to_be_hidden()

    page.locator('#new-protein').select_option('molecules/1qj8/1qj8.pdb')
    expect(page.locator('.new-pdc-protein-size')).to_have_text('5.2 × 4.8 × 6.0 nm')
    expect(page.locator('.new-pdc-box-estimate')).to_have_text('initial box 9.2 × 8.8 × 6.0 nm')

    # A membrane-stating structure names the membrane rule; a refusal is the route's own sentence as text.
    state['body'] = {**EXTENT, 'rule': 'membrane', 'initial_box_nm': [8.4, 8.0, 6.0]}
    page.locator('[name=box_margin_nm]').fill('3')
    expect(page.locator('.new-pdc-box-estimate')).to_have_text('membrane box 8.4 × 8.0 × 6.0 nm')

    state.update(status=400, body={'error': '1qj8 states no coordinates this can measure'})
    page.locator('[name=initial_z_nm]').fill('7')
    expect(page.locator('.new-pdc-protein-size')).to_have_text('1qj8 states no coordinates this can measure')
    expect(page.locator('.new-pdc-box-estimate')).to_have_text('')
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
    mapping is now one the server never lists (`packages/pdc/tests/integration/test_pdc_models_api.py`), and the option's
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
    """The settings the plan adds are visible where they act: no protein means no Ribbon and no
    prepare/coarse-grain node; the removal pipeline is off by default (one CG MD leg), and switching it on turns the
    judge/extend/final half of the chain on."""
    page, errors = live_page
    serve_catalogue(page, proteins=CATALOG['proteins'])
    open_panel(page, live_page.base_url)
    page.locator('#new-protein').select_option('')

    expect(page.locator('[data-new-summary=prepare]')).to_contain_text('skipped · empty micelle')
    expect(page.locator('[data-new-summary=removal]')).to_contain_text('off')
    # The protein's beads are no longer drawn, so the card carries no Bonds control at all; the ribbon is the one
    # protein view left, and an empty micelle has no all-atom structure to draw.
    assert page.locator('.new-pdc-preview-bonds').count() == 0, 'the Bonds control is gone from the card'
    assert page.locator('.new-pdc-preview-ribbon input').is_disabled()

    page.locator('details.new-pdc-diagram summary').click()
    expect(page.locator('.new-pdc-flow [data-stage=build] text.title')).to_have_text('1 · Build the micelle')
    assert page.locator('.new-pdc-flow [data-stage=prepare]').count() == 0
    assert page.locator('.new-pdc-flow [data-stage=coarse-grain]').count() == 0
    assert page.locator('.new-pdc-flow [data-stage=judge]').count() == 0, 'the removal chain is off by default'
    expect(page.locator('[data-new-summary=sampling]')).to_contain_text('1000 ns CG MD')
    expect(page.locator('.new-pdc-flow [data-stage=sample] text.title')).to_contain_text('CG MD')

    # Switching removal on adds the judged half of the chain, which the same clicked disclosure must redraw.
    page.locator('[name=remove_out_of_micelle]').check()
    expect(page.locator('[data-new-summary=removal]')).to_contain_text('on')
    assert page.locator('.new-pdc-flow [data-stage=judge]').count() == 1

    page.locator('[name=remove_out_of_micelle]').uncheck()
    expect(page.locator('[data-new-summary=removal]')).to_contain_text('off')
    assert page.locator('.new-pdc-flow [data-stage=judge]').count() == 0
    assert page.locator('.new-pdc-flow [data-stage=extend]').count() == 0
    assert page.locator('.new-pdc-flow [data-stage=final-assessment]').count() == 0
    assert errors == [], errors


def test_the_front_door_uses_the_only_module_s_form_and_its_storage_line(dashboard, live_page):
    """`/` renders a workspace without naming it in the path; the panel and the storage line must follow the page.

    Two failures this pins, both from the same assumption that the URL segment names the workspace: the New run
    factory built the engine form inside the pdc markup (`#leave-clone` missing, a null `onclick`), and the Runs
    storage line wrote to the engine form's `#new-storage`, replacing its own text with the error.
    """
    # The front door renders the first shown workspace: hide validation so it is pdc, as a module switch can.
    response = dashboard.client.put('/api/modules', json={'enabled': ['pdc']})
    assert response.status_code == 200
    page, errors = live_page
    # The shape card mounts with this panel too, so its two routes are stubbed here as well.
    browser.serve_files(page,
                        (re.compile(r'/api/pdc/conformations/runs'), {'runs': []}),
                        (re.compile(r'/api/pdc/conformations/libraries'), {'libraries': []}))
    page.goto(f'{live_page.base_url}/')

    expect(page.locator('#storage-report')).to_contain_text('Storage:')
    page.get_by_role('tab', name='New run', exact=True).click()
    expect(page.locator('#new-protein')).to_be_visible()
    assert page.locator('#leave-clone').count() == 0, 'the engine form was built inside the pdc workspace'
    assert errors == [], errors


# The launch row: the validation panel's split, with the same ids and the same gating rule. Share is a second run on a
# device that already has one, so it is enabled only when the chosen device reports an active run.
DEVICES = [{'index': 0, 'name': 'NVIDIA GeForce RTX 4090', 'memory_mib': 24564, 'uuid': 'GPU-aaaa'}]


def serve_devices(page, active):
    page.route('**/api/run/devices', lambda route: route.fulfill(
        json={'devices': DEVICES, 'in_use': {}, 'active': active}))


def serve_ready(page):
    page.route(re.compile(r'/api/readiness\?'), lambda route: route.fulfill(
        json={'ready': True, 'checks': [], 'blockers': []}))


def capture_queue(page, posted):
    def queue(route):
        if route.request.method != 'POST':
            route.fallback()
            return
        posted.append(route.request.post_data_json or {})
        route.fulfill(status=201, json={'id': 'pdcqueued1', 'run_type': 'pdc'})
    page.route(re.compile(r'^http://127\.0\.0\.1:\d+/$'), queue)


def test_the_launch_row_splits_queue_from_share_and_share_posts_its_own_choice(dashboard, live_page):
    """A busy device enables Share; pressing it stamps the run with `gpu_sharing=share` and the adapter keeps it."""
    page, errors = live_page
    posted = []
    serve_catalogue(page, proteins=CATALOG['proteins'])
    serve_ready(page)
    serve_devices(page, {'0': ['an-active-run']})
    capture_queue(page, posted)
    open_panel(page, live_page.base_url)
    page.locator('#new-protein').select_option('molecules/1qj8/1qj8.pdb')

    expect(page.locator('#start-run')).to_have_text('Queue run on GPU')
    expect(page.locator('#start-run-share')).to_have_text('Share run on GPU')
    expect(page.locator('#start-run')).to_be_enabled()
    expect(page.locator('#start-run-share')).to_be_enabled()
    page.locator('#start-run-share').click()

    expect(page.locator('#notice')).to_contain_text('Run queued.', timeout=30000)
    assert posted and posted[0]['gpu_sharing'] == 'share', posted
    assert errors == [], errors


def test_share_is_disabled_while_the_chosen_device_is_free(dashboard, live_page):
    """Share is not a second way to press Queue: with no active run on the device there is nothing to share."""
    page, errors = live_page
    serve_catalogue(page, proteins=CATALOG['proteins'])
    serve_ready(page)
    serve_devices(page, {})
    open_panel(page, live_page.base_url)
    page.locator('#new-protein').select_option('molecules/1qj8/1qj8.pdb')

    expect(page.locator('#start-run')).to_be_enabled()
    expect(page.locator('#start-run-share')).to_be_disabled()
    assert errors == [], errors


#: The run-wide groups the user asked to carry a Default button: output cadence, neighbour search and cutoffs, and
#: salt and box. Initial z is the exception: it carries Auto, not Default. The seed carries neither: it is drawn by
#: its Generate button and has no reviewed catalogue number to restore.
DEFAULTED = (('nstlog', '2'), ('nstenergy', '2'), ('nstxtcout', '2'), ('xtc_precision', '2'), ('nstcomm', '2'),
             ('verlet_buffer_tolerance', '0.02'), ('rlist', '2'), ('rcoulomb', '2'), ('rvdw', '2'),
             ('salt_molar', '1'), ('box_margin_nm', '3'), ('contact_nm', '1'),
             ('selection_threshold_fraction', '0.2'))


def test_each_run_wide_group_restores_its_default(dashboard, live_page):
    page, errors = live_page
    serve_catalogue(page, proteins=CATALOG['proteins'])
    serve_devices(page, {})
    open_panel(page, live_page.base_url)

    for name, sample in DEFAULTED:
        field = page.locator(f'[name={name}]')
        default = field.input_value()
        field.fill(sample)
        control_label(page, name).locator('button.pdc-default').click()
        expect(field).to_have_value(default)

    # The seed is drawn, not restored: no Default button, only Generate.
    seed_label = control_label(page, 'pdc_seed')
    assert seed_label.locator('button.pdc-default').count() == 0
    assert seed_label.locator('button.pdc-generate-seed').count() == 1
    assert errors == [], errors


def test_every_stage_setting_carries_an_info_button_with_the_servers_sentence(dashboard, live_page):
    """One focusable info control per setting, its tooltip the text the server sent, and Escape closes it.

    The map is the contract: a setting with no sentence renders no button, so this fails on a missing entry as well
    as on a missing attachment.
    """
    page, errors = live_page
    serve_catalogue(page, proteins=CATALOG['proteins'])
    serve_devices(page, {})
    open_panel(page, live_page.base_url)
    # Every stage editor starts collapsed, so the controls whose buttons this case clicks are opened first.
    page.evaluate("() => document.querySelectorAll('#run-form details.stage-editor').forEach(el => { el.open = true; })")

    for name in STAGE_SETTING_NAMES:
        label = control_label(page, name)
        assert label.count() == 1, f'{name} has no label'
        assert label.locator('button.info-btn').count() == 1, f'{name} has no info button'
    button = control_label(page, 'pdc_nvt_ps').locator('button.info-btn')
    # The caption's units and the info button share the line rather than covering each other: a hint pushed into the
    # button's cell is text nobody can read.
    geometry = control_label(page, 'pdc_nvt_ps').evaluate("""el => {
      const hint = el.querySelector('.hint').getBoundingClientRect();
      const help = el.querySelector('.field-help').getBoundingClientRect();
      return {hintRight: hint.right, helpLeft: help.left};
    }""")
    assert geometry['helpLeft'] >= geometry['hintRight'] - 1, geometry
    button.click()
    expect(page.locator('#setting-help-pdc_nvt_ps')).to_be_visible()
    expect(page.locator('#setting-help-pdc_nvt_ps')).to_have_text('What pdc_nvt_ps means.')
    page.keyboard.press('Escape')
    # The pointer is still over the button, and CSS shows the tip on hover; the click-opened state is what Escape owns.
    tip = page.locator('#setting-help-pdc_nvt_ps')
    assert 'is-open' not in (tip.get_attribute('class') or '')
    page.mouse.move(0, 0)
    expect(tip).to_be_hidden()
    assert errors == [], errors


def test_the_starting_box_fields_mirror_the_preview_box_as_placeholders(dashboard, live_page):
    """The starting box a reader states is the box the preview draws: blank fields show its numbers, three across."""
    page, errors = live_page
    serve_catalogue(page, proteins=CATALOG['proteins'])
    page.route(re.compile(r'/api/pdc/preview/placement'), lambda route: route.fulfill(json={
        'valid': True, 'reasons': [], 'pdb': '',
        'basis': {'box_nm': [18.22, 18.22, 12.13], 'beads': 1500, 'protein_residues': 0,
                  'placement_mode': 'lattice', 'aggregation_number': 150, 'seed': 20261123,
                  'template': 'micelle_template.json', 'solvent_reason': 'not drawn'},
        'cost': {}}))
    open_panel(page, live_page.base_url)
    page.locator('#new-protein').select_option('molecules/1qj8/1qj8.pdb')
    page.locator('[name=aggregation_number]').fill('150')
    page.locator('.new-pdc-preview-derive').click()

    expect(page.locator('.new-pdc-preview-box')).to_contain_text('18.22 × 18.22 × 12.13 nm')
    for name, value in (('initial_x_nm', '18.22'), ('initial_y_nm', '18.22'), ('initial_z_nm', '12.13')):
        field_ = page.locator(f'[name={name}]')
        expect(field_).to_have_value('')
        expect(field_).to_have_attribute('placeholder', value)
    # Three dimensions share the first row, the margin sits below it: every row of box inputs is three across.
    columns = page.locator('.new-pdc-box-grid').evaluate(
        'el => getComputedStyle(el).gridTemplateColumns.split(" ").filter(Boolean).length')
    assert columns == 3, columns
    assert errors == [], errors


#: The box the preview route answers with, distinct from `EXTENT`'s belt-less box on purpose: Auto must write these
#: numbers and not the extent route's.
PREVIEW_BOX = [12.34, 13.56, 14.78]


def _serve_preview(page, *, box=PREVIEW_BOX, valid=True, reasons=()):
    page.route(re.compile(r'/api/pdc/preview/placement'), lambda route: route.fulfill(json={
        'valid': valid, 'reasons': list(reasons), 'pdb': '',
        'basis': {'box_nm': box, 'beads': 1500, 'protein_residues': 0,
                  'placement_mode': 'lattice', 'aggregation_number': 150, 'seed': 20261123,
                  'template': 'micelle_template.json', 'solvent_reason': 'not drawn'},
        'cost': {}}))


def test_the_initial_box_auto_button_writes_the_box_the_preview_draws(dashboard, live_page):
    """One Auto for the starting cell, and it writes the preview's own box rather than a second measurement.

    A belt widens x and y to its radial reach, so the extent route's footprint-plus-margin is not the cell the
    picture draws; Auto derives the preview and writes its `basis.box_nm` exactly, which is what the placeholders
    still show while the fields are blank. An empty micelle has no structure to measure, so the button is disabled.
    """
    page, errors = live_page
    serve_catalogue(page, proteins=CATALOG['proteins'])
    serve_devices(page, {})
    _serve_preview(page)
    open_panel(page, live_page.base_url)

    expect(page.locator('.pdc-auto-box')).to_be_disabled()
    page.locator('#new-protein').select_option('molecules/1qj8/1qj8.pdb')
    expect(page.locator('.pdc-auto-box')).to_be_enabled()
    for name in ('initial_x_nm', 'initial_y_nm', 'initial_z_nm'):
        expect(page.locator(f'[name={name}]')).to_have_value('')
    page.locator('.pdc-auto-box').click()
    expect(page.locator('[name=initial_x_nm]')).to_have_value('12.34')
    expect(page.locator('[name=initial_y_nm]')).to_have_value('13.56')
    expect(page.locator('[name=initial_z_nm]')).to_have_value('14.78')
    assert errors == [], errors


def test_the_auto_button_says_why_when_the_preview_draws_no_box(dashboard, live_page):
    """No picture means no measured cell: the fields are left alone and the builder's own reason is on screen."""
    page, errors = live_page
    serve_catalogue(page, proteins=CATALOG['proteins'])
    serve_devices(page, {})
    _serve_preview(page, box=None, valid=False, reasons=['the placement refuses this belt'])
    open_panel(page, live_page.base_url)
    page.locator('#new-protein').select_option('molecules/1qj8/1qj8.pdb')

    page.locator('.pdc-auto-box').click()
    expect(page.locator('#notice')).to_contain_text('the placement refuses this belt')
    for name in ('initial_x_nm', 'initial_y_nm', 'initial_z_nm'):
        expect(page.locator(f'[name={name}]')).to_have_value('')
    assert errors == [], errors


def test_a_preset_carries_the_box_the_count_and_the_pipeline_switches(dashboard, live_page):
    """The merged card is one preset: the starting box, the count, the placement and the two switches.

    Saving posts every named control under the adapter's names -- a checkbox as a boolean, not the string its `value`
    always carries -- and the run label stays out, because it names this run rather than configuring it. Loading puts
    the ticks back as ticks.
    """
    page, errors = live_page
    serve_catalogue(page, proteins=CATALOG['proteins'])
    posted = {}
    saved = {'id': 'preset-box', 'name': 'box and switches', 'is_default': False,
             'settings': {'initial_x_nm': 12.0, 'initial_y_nm': 13.0, 'initial_z_nm': 20.0,
                          'aggregation_number': 320, 'pdc_placement_mode': 'self-assembly',
                          'backmap': True, 'remove_out_of_micelle': True,
                          'belt_vertical_spread_nm': 3.5, 'box_margin_nm': 2.0}}

    def answer(route):
        if route.request.method == 'POST':
            posted.update(route.request.post_data_json or {})
            route.fulfill(json={'preset': saved})
        else:
            route.fulfill(json={'presets': [saved], 'default': None})

    open_panel(page, live_page.base_url)
    page.route(re.compile(r'/api/setting-presets'), answer)
    page.on('dialog', lambda dialog: dialog.accept('box and switches'))
    # The belt numbers only show for a belt: a protein is what turns the empty micelle into one.
    page.locator('#new-protein').select_option('molecules/1qj8/1qj8.pdb')

    page.locator('[name=initial_x_nm]').fill('12')
    page.locator('[name=initial_y_nm]').fill('13')
    page.locator('[name=initial_z_nm]').fill('20')
    page.locator('#new-count').fill('320')
    page.locator('[name=remove_out_of_micelle]').check()
    page.locator('[name=backmap]').check()
    page.locator('[name=belt_vertical_spread_nm]').fill('3.5')
    page.locator('[name=label]').fill('a different label')
    page.locator('#preset-save').click()

    settings = posted['settings']
    assert settings['initial_x_nm'] == '12' and settings['initial_y_nm'] == '13'
    assert settings['initial_z_nm'] == '20' and settings['aggregation_number'] == '320'
    assert settings['remove_out_of_micelle'] is True and settings['backmap'] is True
    assert settings['belt_vertical_spread_nm'] == '3.5'
    assert settings['pdc_placement_mode'] == 'lattice'
    assert 'label' not in settings, 'the run label is not a setting'

    # Another run's form, then Load: the stored values land on the merged controls, ticks included.
    page.locator('#new-count').fill('150')
    page.locator('[name=initial_x_nm]').fill('')
    page.locator('[name=belt_vertical_spread_nm]').fill('')
    page.locator('[name=backmap]').uncheck()
    page.locator('[name=remove_out_of_micelle]').uncheck()
    page.locator('.preset-select').select_option('preset-box')
    page.locator('#preset-load').click()

    expect(page.locator('#new-count')).to_have_value('320')
    expect(page.locator('[name=initial_x_nm]')).to_have_value('12')
    expect(page.locator('[name=initial_y_nm]')).to_have_value('13')
    expect(page.locator('[name=initial_z_nm]')).to_have_value('20')
    expect(page.locator('[name=belt_vertical_spread_nm]')).to_have_value('3.5')
    expect(page.locator('[name=backmap]')).to_be_checked()
    expect(page.locator('[name=remove_out_of_micelle]')).to_be_checked()
    expect(page.locator('#new-placement')).to_have_value('self-assembly')
    assert errors == [], errors



def test_a_shaped_cell_hides_the_rectangular_lengths_and_is_a_choice(dashboard, live_page):
    """A shaped cell has one derived edge, so the three rectangular lengths and their Auto are not its inputs."""
    page, errors = live_page
    open_panel(page, live_page.base_url)
    shape = page.locator('[name=box_shape]')
    expect(shape).to_have_value('rectangular')
    for name in ('initial_x_nm', 'initial_y_nm', 'initial_z_nm'):
        expect(page.locator(f'label:has([name={name}])')).to_be_visible()

    shape.select_option('octahedron')

    for name in ('initial_x_nm', 'initial_y_nm', 'initial_z_nm'):
        expect(page.locator(f'label:has([name={name}])')).to_be_hidden()
    expect(page.locator('.new-pdc-box-shape-note')).to_be_visible()
    expect(page.locator('.pdc-auto-box')).to_be_disabled()

    shape.select_option('rectangular')

    for name in ('initial_x_nm', 'initial_y_nm', 'initial_z_nm'):
        expect(page.locator(f'label:has([name={name}])')).to_be_visible()
    expect(page.locator('.new-pdc-box-shape-note')).to_be_hidden()
    assert errors == [], errors
