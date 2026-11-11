"""The Combinations panel saves a *named* CG molecule and shows the derived model it made.

A composition is no longer an anonymous record with a display string: it has a molecule name (`GLC-C12` by default,
from the sugar residue and carbon count), an optional link to the atomistic molecule its head came from, and a
derived -- never fitted -- parameterization. The panel is where those two choices are made, and the card beside it is
where the resulting model is read: molecule id and name, head link, beads, terms, `derived · revision 0 · source`,
status `candidate-unvalidated`, and the two doors into Bond Interactions and a CG run.

The routes are the real ones: the save builds the immutable artifacts in the test's workspace and the card reads the
catalog row back from `/api/cg-models`. The name and link defaults are the panel's own claim, asserted on the DOM.
"""
import re

from playwright.sync_api import expect

from tests.harness import browser

SERVER_WAIT = 30000


def open_panel(page, base_url):
    return browser.open_compositions(page, base_url)


def _preview(page):
    page.locator('#composition-preview').click()
    expect(page.locator('#composition-panel-status')).to_contain_text('Preview ready', timeout=SERVER_WAIT)


def _save(page, name):
    _preview(page)
    page.locator('#composition-save').click()
    expect(page.locator('#composition-panel-status')).to_contain_text(f'Saved {name}', timeout=SERVER_WAIT)


def _saved_row(dashboard, name):
    return next(row for row in dashboard.client.get('/api/cg-models').json['models']
                if row['kind'] == 'composition' and row['molecule_name'] == name)


def test_the_name_and_the_head_link_follow_the_recipe_until_typed(dashboard, live_page):
    """`[sugar]-C[carbons]`, and the sugar's own molecule when the catalogue has that folder."""
    page, errors = live_page
    open_panel(page, live_page.base_url)

    name = page.locator('#composition-molecule-name')
    expect(name).to_have_value('GLC-C12')
    expect(page.locator('#composition-head-molecule')).to_have_value('Glucose')
    page.locator('#composition-sugar').select_option('LAC')
    expect(name).to_have_value('LAC-C12')
    expect(page.locator('#composition-head-molecule')).to_have_value('Lactose')
    page.locator('#composition-carbon-count').fill('10')
    expect(name).to_have_value('LAC-C10')
    # A typed name stops following the recipe; the link still belongs to the reader until they choose one.
    name.fill('my-model')
    page.locator('#composition-carbon-count').fill('12')
    expect(name).to_have_value('my-model')
    page.locator('#composition-head-molecule').select_option('')
    expect(page.locator('#composition-head-molecule')).to_have_value('')
    assert errors == []


def test_a_saved_composition_renders_its_derived_model_and_both_doors(dashboard, live_page):
    page, errors = live_page
    open_panel(page, live_page.base_url)
    _save(page, 'GLC-C12')

    row = _saved_row(dashboard, 'GLC-C12')
    # Both choices travelled with the recipe: the saved record names the model and links its head.
    assert row['molecule_name'] == 'GLC-C12' and row['head_molecule_id'] == 'Glucose'
    parameterization = row['parameterization']
    provenance = page.locator('#composition-provenance-list')
    expect(provenance).to_contain_text(row['molecule_id'])
    expect(provenance).to_contain_text('GLC-C12')
    expect(provenance).to_contain_text('Glucose')
    expect(provenance).to_contain_text(f"{parameterization['topology']['beads']} beads")
    expect(provenance).to_contain_text('derived · revision 0 · recipe+reference')
    expect(provenance).to_contain_text('candidate-unvalidated')
    bonds = parameterization['topology']['terms'].get('bonds')
    if bonds:
        expect(provenance).to_contain_text(f'{bonds} bonds')
    expect(page.locator('#composition-open-bonded')).to_be_enabled()
    expect(page.locator('#composition-open-bonded')).to_have_text('Open in Bond Interactions')
    expect(page.locator('#composition-start-run')).to_be_enabled()
    expect(page.locator('#composition-start-run')).to_have_text('Open the CG run')

    rows = page.locator('#composition-model-rows tr')
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text('GLC-C12')
    expect(rows.first).to_contain_text('candidate-unvalidated')
    expect(rows.first.locator('button')).to_have_text('Open the CG run')
    assert page.locator('#composition-models-status').text_content() == ''
    assert errors == []


def test_open_in_bond_interactions_selects_the_saved_composition(dashboard, live_page):
    """The other door: Bond Interactions reads the same catalog row, addressed as `composition:<id>`."""
    page, errors = live_page
    open_panel(page, live_page.base_url)
    _save(page, 'GLC-C12')
    row = _saved_row(dashboard, 'GLC-C12')

    page.locator('#composition-open-bonded').click()
    expect(page.locator('#bonded')).to_be_visible(timeout=SERVER_WAIT)
    expect(page.locator('#bonded-mapping-select')).to_have_value(f"composition:{row['id']}", timeout=SERVER_WAIT)
    assert errors == []


def test_open_the_cg_run_selects_the_composition_and_its_derived_model(dashboard, live_page):
    """The door into New run: the composition is the molecule and its derived model is the parameterization."""
    page, errors = live_page
    open_panel(page, live_page.base_url)
    _save(page, 'GLC-C12')
    row = _saved_row(dashboard, 'GLC-C12')

    page.locator('#composition-start-run').click()
    expect(page.locator('#new')).to_be_visible(timeout=SERVER_WAIT)
    page.wait_for_function("id => document.querySelector('[name=molecule_id]').value === id",
                           arg=row['molecule_id'], timeout=SERVER_WAIT)
    expect(page.locator('#molecule-inputs-status')).to_contain_text('No AA inputs', timeout=SERVER_WAIT)
    expect(page.locator('#run-parameterization')).to_contain_text(
        'derived · revision 0 · composition recipe · recipe+reference')
    expect(page.locator('#run-parameterization')).to_contain_text('links to Glucose')
    expect(page.locator('#run-aa-summary')).to_have_text('no AA stage')
    expect(page.locator('#starting-coordinates-field')).to_be_hidden()
    expect(page.locator('[name=label]')).to_have_value(re.compile(r'^GLC-C12-CG-\d+(?:\.\d+)?ns-\d{8}$'))
    assert errors == []
