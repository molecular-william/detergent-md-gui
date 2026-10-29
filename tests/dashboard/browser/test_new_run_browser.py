"""New run directory selection against the real API; simulation worker disabled."""
import shutil

from dashboard.execution.adapters import cg
from playwright.sync_api import expect

from tests.dashboard.support import PROJECT_ROOT

from . import panels

#: The tier's own budget for an answer the server has to produce (`browser/conftest.py`): Playwright's default
#: expectation timeout is 5 s, which a loaded box outruns.
SERVER_WAIT = 30000


def test_the_workflow_is_named_for_single_molecules(dashboard, live_page):
    """The tab and the panel heading say which workflow this is, now that there are two."""
    page, errors = live_page
    page.goto(live_page.base_url)
    expect(page.get_by_role('tab', name='New run', exact=True)).to_be_visible()
    page.get_by_role('tab', name='New run', exact=True).click()
    expect(page.locator('#new h2')).to_have_text('Single Molecule Simulations')
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
    page.wait_for_function("() => document.querySelectorAll('#force-field option').length > 1", timeout=30000)
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
    # Wait for the server's default to reach the field, which is this claim's precondition. The submit button is
    # deliberately not waited on: readiness may hold it disabled in a bare fixture, and that is a different claim.
    page.wait_for_function("() => document.querySelector('[name=temperature_k]').value === '303.15'", timeout=30000)
    assert page.evaluate("document.querySelector('#run-form').checkValidity()") is True, \
        'the form is invalid before anyone touches it, so no submit can ever fire'
    assert errors == []


def test_directory_selection_supports_generic_aa_and_ddm_cg_pair(dashboard, live_page, monkeypatch, tmp_path):
    root=PROJECT_ROOT
    shutil.copytree(root/'molecules/DDM',tmp_path/'molecules/DDM')
    missing=tmp_path/'molecules/Incomplete'; missing.mkdir()
    shutil.copytree(root/'molecules/DDM',tmp_path/'molecules/Other')
    monkeypatch.setattr(dashboard.coordinator,'ROOT',tmp_path)
    monkeypatch.setattr(cg,'readiness',lambda *a,**k:{'ready':True,'checks':[],'blockers':[]})
    monkeypatch.setattr(dashboard.coordinator,'run_job',lambda *args: None)
    dashboard.coordinator.database().replace([])
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/new-run')
    expect(page).to_have_title('Detergent MD · Laboratory')
    # The panel shows itself, fills the picker, and answers `/api/readiness` for the selection before it
    # enables Start -- three round trips, and none of them is fast when the tier is loaded. The assertions that wait
    # on one of those answers take the tier's own budget (`SERVER_WAIT`): measured with sixteen copies of this test
    # running at once, `/api/readiness` returned 200 'Inputs ready' at 5.4-6.5 s and every copy failed on
    # Playwright's 5 s default while the server was answering correctly. The assertions over a control the page
    # itself has just toggled keep the 5 s default, which is what they are given and all they need.
    expect(page.locator('#molecule-directory')).to_be_visible(timeout=SERVER_WAIT)
    expect(page.locator('#molecule-directory')).to_have_value('DDM', timeout=SERVER_WAIT)
    expect(page.locator('#molecule-details')).to_contain_text('81 atoms', timeout=SERVER_WAIT)
    expect(page.locator('#molecule-details')).to_contain_text('PDB → GRO automatically', timeout=SERVER_WAIT)
    expect(page.locator('#molecule-details')).to_contain_text('metadata.json generated automatically',
                                                              timeout=SERVER_WAIT)
    page.locator('#molecule-directory').select_option('Other')
    # Any valid molecule is now a candidate for the generic CG workflow; the
    # previous "No execution adapter" gate was removed in Phase 4.2. The CG
    # readiness panel reports the AA-reference prerequisite instead.
    expect(page.locator('#molecule-details')).to_contain_text('Input files consistent', timeout=SERVER_WAIT)
    expect(page.locator('#molecule-details')).not_to_contain_text('No execution adapter')
    page.reload()
    expect(page.locator('#molecule-directory')).to_have_value('Other', timeout=SERVER_WAIT)
    # A compatible non-DDM directory is now runnable through AA-only.
    page.locator('#run-type').select_option('aa_only')
    expect(page.locator('#cg-inputs')).to_be_hidden()
    expect(page.locator('#start-run')).to_be_enabled(timeout=SERVER_WAIT)
    with page.expect_response(lambda r: r.request.method=='POST' and r.url.endswith('/')) as response:
        page.locator('#start-run').click()
    assert response.value.status==201, response.value.text()
    generic=dashboard.coordinator.database().all()[0]
    assert generic['run_type']=='aa_only' and generic['molecule_id']=='Other'
    assert not generic.get('mapping_snapshot')
    assert 'cg_production_ps' not in generic['settings']
    dashboard.coordinator.database().update(generic['id'],status='completed')
    dashboard.coordinator.WORKERS.clear()
    page.locator('#tab-new').click()
    page.locator('#run-type').select_option('aa_cg')
    expect(page.locator('#start-run')).to_be_disabled()
    page.locator('#molecule-directory').select_option('DDM')
    expect(page.locator('#start-run')).to_be_enabled(timeout=SERVER_WAIT)
    page.locator('[name=label]').fill('Directory selection test')
    source=page.locator('#molecule-panel').bounding_box()
    settings=page.locator('.run-settings').bounding_box()
    assert settings['x'] > source['x']+source['width']
    page.set_viewport_size({'width':390,'height':844})
    panels.assert_no_horizontal_scroll(page)
    expect(page.locator('#molecule-directory')).to_be_visible()
    with page.expect_response(lambda r: r.request.method=='POST' and r.url.endswith('/')) as response:
        page.locator('#start-run').click()
    assert response.value.status==201, response.value.text()
    jobs=[job for job in dashboard.coordinator.database().all() if job['id']!=generic['id']]
    assert len(jobs)==2
    cg_job=next(job for job in jobs if job['run_type']=='aa_cg')
    aa_job=next(job for job in jobs if job['run_type']=='aa_only')
    assert cg_job['reference_run_id']==aa_job['id'] and cg_job['status']=='waiting'
    assert aa_job['molecule_id']==cg_job['molecule_id']=='DDM'
    assert set(aa_job['molecule_snapshot']['sha256'])=={'results/MMFF/lig1.pdb','results/MMFF/lig1.itp','metadata.json'}
    assert cg_job['label']=='Directory selection test'
    assert not errors, errors
