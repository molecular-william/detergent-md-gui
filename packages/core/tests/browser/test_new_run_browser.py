"""New run directory selection against the real API; simulation worker disabled."""
import json
import re
import shutil
from urllib.parse import parse_qs, urlsplit

from dashboard.execution.adapters import cg
from playwright.sync_api import expect

from tests.harness import browser
from tests.harness.support import PROJECT_ROOT

#: The tier's own budget for an answer the server has to produce (`browser/conftest.py`): Playwright's default
#: expectation timeout is 5 s, which a loaded box outruns.
SERVER_WAIT = 30000

#: A valid composition: glucose's published head, a deterministic C12 tail, and the provenance the panel now saves.
COMPOSITION = {'head_fragment_id': 'builtin:martini-sugars-v2:GLC', 'tail_recipe_id': 'linear-c1',
               'carbon_count': 12, 'head_endpoint': {'bead': 'C'}, 'tail_endpoint': {'bead': 'C01'},
               'linkage_profile_id': 'sugar-alkyl-ether-ddm-transfer',
               'molecule_name': 'GLC-C12', 'head_molecule_id': 'Glucose'}


def test_the_workflow_is_named_for_single_molecules(dashboard, live_page):
    """The tab and the panel heading say which workflow this is, now that there are two."""
    page, errors = live_page
    page.goto(live_page.base_url)
    expect(page.get_by_role('tab', name='New run', exact=True)).to_be_visible()
    page.get_by_role('tab', name='New run', exact=True).click()
    expect(page.locator('#new h2')).to_have_text('Single Molecule Simulations')
    assert errors == []


def test_the_run_type_is_aa_or_cg_and_nothing_else(dashboard, live_page):
    """Two run types, not four: the combined type and the two one-off CG shapes are out of the document."""
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/new-run')
    page.get_by_role('tab', name='New run', exact=True).click()
    options = page.evaluate(
        "Array.from(document.querySelectorAll('#run-type option')).map(o => [o.value, o.textContent.trim()])")
    assert options == [['cg', 'CG run'], ['aa_only', 'AA run']], options
    expect(page.locator('#run-type')).to_have_value('cg')
    # The controls the retired types carried are gone from the document entirely, not merely hidden.
    for selector in ('#method', '#run-mapping', '#reference-run', '#composition-run-selector', '#sugar-panel'):
        assert page.locator(selector).count() == 0, f'{selector} is still rendered'
    assert errors == []


def test_the_force_field_selector_is_the_registry(dashboard, live_page):
    """The panel offers what the server can run, each entry with its own temperature and water.

    The list is not held in the template: adding a registry entry must be enough for the panel to offer it, which
    is only true if the options come from the endpoint. Choosing an entry moves the temperature field to the value
    that entry's parameterisation assumes, and the form has to stay valid afterwards.
    """
    from dashboard.execution import forcefields
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/new-run')
    page.get_by_role('tab', name='New run', exact=True).click()
    # The template carries two fallback options; wait for the registry's own labels, which include the temperature.
    page.wait_for_function(
        "() => Array.from(document.querySelectorAll('#force-field option'))"
        "        .some(option => /[0-9]+\\.?[0-9]* K·?/.test(option.textContent))",
        timeout=30000)
    options = page.evaluate("Array.from(document.querySelectorAll('#force-field option')).map(o => [o.value, o.textContent])")
    assert [value for value, _ in options] == list(forcefields.names())
    for value, text in options:
        entry = forcefields.entry(value)
        assert entry.label in text, f'{value} is offered without its label'
        assert f'{entry.temperature_k} K' in text, f'{value} is offered without its temperature'
        assert entry.water_file[: -len('.itp')].upper() in text.upper()
    page.locator('#force-field').select_option('charmm36-jul2022')
    expect(page.locator('[name=temperature_k]')).to_have_value('303.15')
    assert page.evaluate("document.querySelector('#run-form').checkValidity()") is True
    assert errors == []


def test_the_run_form_accepts_the_temperatures_the_force_fields_use(dashboard, live_page):
    """The panel's own constraints must admit the values the server defaults to.

    Each force field is run at the temperature its parameterisation assumes, and two of them are not whole or
    tenths of a degree: 303.15 K is a stepMismatch against `step="0.1"`. HTML5 validation then blocks the form's
    submit event, so the click does nothing, nothing is reported, and the only visible symptom is an empty notice.
    """
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/new-run')
    page.get_by_role('tab', name='New run', exact=True).click()
    # Wait for the server's default to reach the field, which is this claim's precondition.
    page.wait_for_function("() => document.querySelector('[name=temperature_k]').value === '303.15'", timeout=30000)
    assert page.evaluate("document.querySelector('#run-form').checkValidity()") is True, \
        'the form is invalid before anyone touches it, so no submit can ever fire'
    assert errors == []


def test_directory_selection_supports_generic_aa_and_cg_pair(dashboard, live_page, monkeypatch, tmp_path):
    root = PROJECT_ROOT
    shutil.copytree(root / 'molecules/DDM', tmp_path / 'molecules/DDM')
    (tmp_path / 'molecules/Incomplete').mkdir()
    shutil.copytree(root / 'molecules/DDM', tmp_path / 'molecules/Other')
    monkeypatch.setattr(dashboard.coordinator, 'ROOT', tmp_path)
    # A CG run's readiness reads the revision store, which this fixture workspace has none of. The form's own claims
    # are what this test is about, so the run-type answer is stubbed; the AA run goes through the real route.
    monkeypatch.setattr(cg, 'parameterization_readiness', lambda *a, **k: {'ready': True, 'checks': [], 'blockers': []})
    monkeypatch.setattr(dashboard.coordinator, 'run_job', lambda *args: None)
    dashboard.coordinator.database().replace([])
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/new-run')
    expect(page).to_have_title('Detergent MD · Laboratory')
    expect(page.locator('#molecule-directory')).to_be_visible(timeout=SERVER_WAIT)
    expect(page.locator('#molecule-directory')).to_have_value('DDM', timeout=SERVER_WAIT)
    # The input check is folded: its verdict and the molecule's facts are the summary line, and the file list and
    # notes are inside the closed <details>.
    expect(page.locator('#molecule-inputs-status')).to_contain_text('81 atoms', timeout=SERVER_WAIT)
    expect(page.locator('#molecule-details')).to_contain_text('PDB → GRO automatically', timeout=SERVER_WAIT)
    expect(page.locator('#molecule-details')).to_contain_text('metadata.json generated automatically',
                                                              timeout=SERVER_WAIT)
    page.locator('#molecule-directory').select_option('Other')
    expect(page.locator('#molecule-inputs-status')).to_contain_text('Input files consistent', timeout=SERVER_WAIT)
    expect(page.locator('#molecule-inputs')).not_to_contain_text('No execution adapter')
    page.reload()
    expect(page.locator('#molecule-directory')).to_have_value('Other', timeout=SERVER_WAIT)
    # An AA run builds its own reference, so it needs no model and starts from the real route.
    page.locator('#run-type').select_option('aa_only')
    expect(page.locator('#cg-inputs')).to_be_hidden()
    expect(page.locator('#start-run')).to_be_enabled(timeout=SERVER_WAIT)
    with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/')) as response:
        page.locator('#start-run').click()
    assert response.value.status == 201, response.value.text()
    generic = dashboard.coordinator.database().all()[0]
    assert generic['run_type'] == 'aa_only' and generic['molecule_id'] == 'Other'
    assert not generic.get('mapping_snapshot')
    assert 'cg_production_ps' not in generic['settings']
    dashboard.coordinator.database().update(generic['id'], status='completed')
    dashboard.coordinator.WORKERS.clear()
    # A CG run consumes one model; admission refuses a revision with no mapping, so the queue call is answered here
    # and the payload it names is what this test reads.
    page.locator('#tab-new').click()
    page.locator('#run-type').select_option('cg')
    expect(page.locator('#cg-inputs')).to_be_visible()
    expect(page.locator('#start-run')).to_be_enabled(timeout=SERVER_WAIT)
    page.locator('[name=label]').fill('Directory selection test')
    source = page.locator('#molecule-panel').bounding_box()
    settings = page.locator('.run-settings').bounding_box()
    assert settings['x'] > source['x'] + source['width']
    page.set_viewport_size({'width': 390, 'height': 844})
    browser.assert_no_horizontal_scroll(page)
    expect(page.locator('#molecule-directory')).to_be_visible()
    posted = {}
    page.route(re.compile(r'^http://127\.0\.0\.1:\d+/$'), lambda route: (
        posted.update(route.request.post_data_json or {}), route.fulfill(status=201, json={'id': '222222222222'}))[-1])
    page.locator('#start-run').click()
    expect(page.locator('#notice')).to_have_text('Run queued.')
    assert posted['run_type'] == 'cg' and posted['molecule_id'] == 'Other'
    assert posted['label'] == 'Directory selection test'
    assert posted['parameterization']['kind'] == 'revision'
    assert 'starting_coordinates' in posted['parameterization']
    assert 'method' not in posted and 'reference_run_id' not in posted
    assert not errors, errors


def test_the_run_type_shows_only_the_settings_that_leg_builds(dashboard, live_page):
    """Constraints and the AA durations belong to the AA run; a CG run consumes a reference that already ran.

    The controls stay in the document with their values, because a preset and a clone must not lose a setting to a
    toggle, but only the leg the selected run type executes is shown.
    """
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/new-run')
    page.get_by_role('tab', name='New run', exact=True).click()
    expect(page.locator('#new')).to_have_attribute('aria-busy', 'false')
    # The panel opens on a CG run: the atomistic leg's controls are out of the way.
    expect(page.locator('#new-constraints-group')).to_be_hidden()
    expect(page.locator('[name=aa_nvt_ps]').locator('xpath=ancestor::label')).to_be_hidden()
    expect(page.locator('[name=cg_equil_ps]').locator('xpath=ancestor::label')).to_be_visible()
    expect(page.locator('[name=cg_production_ps]')).to_be_visible()
    page.locator('#run-type').select_option('aa_only')
    expect(page.locator('#new-constraints-group')).to_be_visible()
    expect(page.locator('[name=aa_nvt_ps]')).to_be_visible()
    expect(page.locator('[name=cg_equil_ps]').locator('xpath=ancestor::label')).to_be_hidden()
    expect(page.locator('[name=constraints]')).to_be_enabled()
    assert errors == []


def test_the_input_check_is_folded_and_keeps_the_readers_state(dashboard, live_page):
    """The verdict stays on one line and the file list lives inside a closed `<details>`.

    The block is re-rendered on every molecule selection and every readiness answer, so the open state is kept
    by the panel rather than by the element; a reader who opened it to check a file keeps it open.
    """
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/new-run')
    page.get_by_role('tab', name='New run', exact=True).click()
    inputs = page.locator('#molecule-inputs')
    expect(page.locator('#molecule-inputs-status')).to_contain_text('Input files consistent', timeout=SERVER_WAIT)
    assert inputs.evaluate('(el) => el.open') is False, 'the input check must start folded'
    expect(page.locator('#molecule-inputs-status')).to_contain_text('atoms', timeout=SERVER_WAIT)
    inputs.locator('> summary').click()
    assert inputs.evaluate('(el) => el.open') is True
    page.locator('#run-type').select_option('aa_only')
    assert inputs.evaluate('(el) => el.open') is True, 'a readiness repaint closed the block the reader opened'
    assert errors == []


def test_the_label_is_suggested_until_edited_and_suggest_restores_it(dashboard, live_page):
    """[molecule]-[AA|CG]-[length]ns-[YYYYMMDD], following the form while nobody has typed in the field."""
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/new-run')
    page.get_by_role('tab', name='New run', exact=True).click()
    label = page.locator('[name=label]')
    expect(label).to_have_value(re.compile(r'^DDM-CG-\d+(?:\.\d+)?ns-\d{8}$'), timeout=SERVER_WAIT)
    page.locator('#run-type').select_option('aa_only')
    expect(label).to_have_value(re.compile(r'^DDM-AA-11\.1ns-\d{8}$'), timeout=SERVER_WAIT)
    label.fill('My own label')
    page.locator('[name=aa_production_ps]').fill('20000')
    expect(label).to_have_value('My own label')
    page.locator('#suggest-label').click()
    # 100 + 1000 + 20000 ps, in the format the server's own fallback writes.
    expect(label).to_have_value(re.compile(r'^DDM-AA-21\.1ns-\d{8}$'))
    assert errors == []


def test_a_preset_is_saved_loaded_made_default_and_deleted(dashboard, live_page):
    """The preset bar's four controls against the real routes, on the workspace's own store."""
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/new-run')
    page.get_by_role('tab', name='New run', exact=True).click()
    page.locator('#run-type').select_option('aa_only')
    page.locator('[name=aa_production_ps]').fill('4321')
    page.once('dialog', lambda dialog: dialog.accept('Browser preset'))
    page.locator('#preset-save').click()
    select = page.locator('#preset-select')
    expect(select.locator('option')).to_have_count(2, timeout=SERVER_WAIT)
    assert select.locator('option').nth(1).text_content() == 'Browser preset'
    page.locator('[name=aa_production_ps]').fill('100')
    page.locator('#preset-load').click()
    expect(page.locator('[name=aa_production_ps]')).to_have_value('4321')
    page.locator('#preset-default').click()
    expect(select.locator('option').nth(1)).to_have_text('Browser preset · default', timeout=SERVER_WAIT)
    # The default is what the form opens on, so a reload lands on the preset's numbers, not the profile's.
    page.locator('[name=aa_production_ps]').fill('100')
    page.reload()
    page.get_by_role('tab', name='New run', exact=True).click()
    expect(page.locator('[name=aa_production_ps]')).to_have_value('4321', timeout=SERVER_WAIT)
    expect(page.locator('#preset-marker')).to_contain_text('Applied preset: Browser preset · default')
    page.once('dialog', lambda dialog: dialog.accept())
    page.locator('#preset-delete').click()
    expect(select.locator('option')).to_have_count(1, timeout=SERVER_WAIT)
    assert errors == []


def test_a_saved_composition_is_a_molecule_and_posts_its_derived_model(dashboard, live_page):
    """A composition is offered as a CG molecule, and the run it queues names the derived model, not a mapping.

    The record is built through the route the panel uses, so the catalog row New run reads is the one Combinations
    saves. The payload is read off the request the form actually makes, and the questions it asks before it --
    `/api/defaults` and `/api/readiness` -- are held to the composition kind too.
    """
    record = dashboard.client.post('/api/compositions', json=COMPOSITION).json
    dashboard.coordinator.database().replace([])
    page, errors = live_page
    seen = {'defaults': [], 'readiness': []}
    page.route('**/api/defaults?*',
               lambda route: (seen['defaults'].append(route.request.url), route.continue_())[1])
    page.route('**/api/readiness?*',
               lambda route: (seen['readiness'].append(route.request.url), route.continue_())[1])

    page.goto(f'{live_page.base_url}/detergent-validation/new-run')
    page.get_by_role('tab', name='New run', exact=True).click()
    option = page.locator(f'[name=molecule_id] option[value="{record["molecule_id"]}"]')
    expect(option).to_have_count(1, timeout=SERVER_WAIT)
    expect(option).to_contain_text('GLC-C12 · composition · candidate-unvalidated')
    page.locator('[name=molecule_id]').select_option(record['molecule_id'])

    expect(page.locator('#run-parameterization')).to_contain_text(
        'derived · revision 0 · composition recipe · recipe+reference', timeout=SERVER_WAIT)
    expect(page.locator('#run-aa-summary')).to_have_text('no AA stage')
    expect(page.locator('#starting-coordinates-field')).to_be_hidden()
    expect(page.locator('#molecule-inputs-status')).to_contain_text('No AA inputs')
    expect(page.locator('#start-run')).to_be_enabled(timeout=SERVER_WAIT)

    posted = {}
    page.route(re.compile(r'^http://127\.0\.0\.1:\d+/$'), lambda route: (
        posted.update(route.request.post_data_json or {}),
        route.fulfill(status=201, json={'id': '333333333333'}))[-1])
    page.locator('#start-run').click()
    expect(page.locator('#notice')).to_have_text('Run queued.')

    assert posted['run_type'] == 'cg' and posted['molecule_id'] == record['molecule_id']
    assert posted['parameterization'] == {'kind': 'composition', 'composition_id': record['id'],
                                           'composition_revision': 0}
    for retired in ('mapping_candidate', 'reference_run_id', 'sugar_entry', 'method', 'profile', 'force_field'):
        assert retired not in posted, f'{retired} is still sent: {posted}'
    # The composition adapter's CG dialect, not the AA half's: the AA durations never reach this run.
    assert 'cg_equil_ps' in posted and 'cg_production_ps' in posted
    for aa_key in ('aa_nvt_ps', 'aa_npt_ps', 'aa_production_ps', 'pressure_bar', 'box_nm', 'sasa_probe_nm'):
        assert aa_key not in posted, f'{aa_key} is still sent: {posted}'

    # The two questions before the queue used the composition kind as well.
    readiness = [json.loads(parse_qs(urlsplit(url).query)['parameterization'][0])
                 for url in seen['readiness'] if 'parameterization=' in url]
    assert {'kind': 'composition', 'composition_id': record['id'], 'composition_revision': 0} in \
        readiness, readiness
    assert any(parse_qs(urlsplit(url).query).get('parameterization_kind') == ['composition']
               for url in seen['defaults']), seen['defaults']
    assert errors == []
