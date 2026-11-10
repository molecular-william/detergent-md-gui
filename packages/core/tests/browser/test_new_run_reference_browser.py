"""A CG run from a published Martini 3 reference: the model selector's read-only branch.

The reference is one of the CG run's parameterizations, not a run type of its own. Choosing it hides the starting-
coordinate choice (the published entry carries its own start), states that there is no AA stage, fills the stage
settings from the sugar adapter's own profile, and posts `{kind: reference, sugar_entry}`. The routes are the real
ones: the installed Martini 3 set is what the panel reads, and the payload is the only part answered from the test.
"""
import re

from playwright.sync_api import expect

from tests.harness import browser

SERVER_WAIT = 30000


def seed(page, form):
    page.add_init_script(f"localStorage.setItem('ddm.form', JSON.stringify({form}));")


def open_panel(page, base_url, form):
    seed(page, form)
    return browser.open_panel(page, base_url, '/detergent-validation/new-run',
                              ready=lambda page: page.wait_for_function(
                                  "() => document.querySelector('[name=molecule_id]').value !== ''"
                                  " && document.querySelectorAll('#run-parameterization option').length >= 1",
                                  timeout=30000))


def test_the_reference_is_a_read_only_model_and_posts_its_own_vocabulary(dashboard, live_page):
    page, errors = live_page
    submissions = []
    open_panel(page, live_page.base_url, "{run_type:'cg',molecule_id:'Lactose'}")

    select = page.locator('#run-parameterization')
    expect(select).to_contain_text('Martini 3 reference · LAC')
    # It is the molecule's only model in this bare workspace, so the mount selects it.
    assert page.evaluate("document.querySelector('#run-parameterization option:checked').dataset.kind") == 'reference'
    expect(page.locator('#run-parameterization-summary')).to_have_text('Martini 3 reference · LAC')
    expect(page.locator('#run-aa-summary')).to_have_text('no AA stage')
    expect(page.locator('#run-coordinates-summary')).to_have_text('Mapped AA geometry')
    expect(page.locator('#starting-coordinates-field')).to_be_hidden()
    expect(page.locator('#start-run')).to_have_text('Start CG run')
    # The sugar profile's own durations, including when a saved form carried the revision kind's short ones.
    expect(page.locator('[name=cg_equil_ps]')).to_have_value('5000', timeout=SERVER_WAIT)
    expect(page.locator('[name=temperature_k]')).to_have_value('310')
    expect(page.locator('[name=label]')).to_have_value(re.compile(r'^Lactose-CG-15ns-\d{8}$'), timeout=SERVER_WAIT)
    expect(page.locator('#start-run')).to_be_enabled(timeout=SERVER_WAIT)

    def submit(route):
        submissions.append(route.request.post_data_json)
        route.fulfill(status=201, json={'id': '444444444444'})

    page.route(re.compile(r'^http://127\.0\.0\.1:\d+/$'), submit)
    page.locator('#start-run').click()
    expect(page.locator('#notice')).to_have_text('Run queued.')
    assert submissions, 'the form did not post a run'
    body = submissions[0]
    assert body['run_type'] == 'cg' and body['molecule_id'] == 'Lactose'
    assert body['parameterization'] == {'kind': 'reference', 'sugar_entry': 'LAC'}
    assert body['sugar_entry'] == 'LAC'
    assert body['cg_production_ps'] == '10000'
    for retired in ('method', 'mapping_candidate', 'reference_run_id', 'aa_nvt_ps', 'pressure_bar'):
        assert retired not in body, f'{retired} is still sent: {body}'
    assert errors == []


def test_a_saved_revision_duration_is_replaced_by_the_reference_profile(dashboard, live_page):
    """The reference kind's durations are its adapter's, not the last CG revision the form was left on."""
    page, errors = live_page
    open_panel(page, live_page.base_url,
               "{run_type:'cg',molecule_id:'Lactose',cg_equil_ps:'10',cg_production_ps:'100'}")

    expect(page.locator('[name=cg_equil_ps]')).to_have_value('5000', timeout=SERVER_WAIT)
    expect(page.locator('[name=cg_production_ps]')).to_have_value('10000')
    assert errors == []


def test_selecting_a_sugar_molecule_switches_the_model_and_the_aa_source(dashboard, live_page):
    """The molecule is the model's scope: choosing Lactose offers its reference and moves the review to 'no AA stage'."""
    page, errors = live_page
    open_panel(page, live_page.base_url, "{run_type:'cg',molecule_id:'DDM'}")
    expect(page.locator('#run-aa-summary')).to_have_text('no parameterization selected')

    page.locator('[name=molecule_id]').select_option('Lactose')

    expect(page.locator('#run-parameterization')).to_contain_text('Martini 3 reference · LAC', timeout=SERVER_WAIT)
    expect(page.locator('#run-aa-summary')).to_have_text('no AA stage')
    page.locator('#run-type').select_option('aa_only')
    expect(page.locator('#cg-inputs')).to_be_hidden()
    expect(page.locator('#run-aa-summary')).to_have_text('this run')
    expect(page.locator('#run-coordinates-summary')).to_have_text('this run')
    assert errors == []
