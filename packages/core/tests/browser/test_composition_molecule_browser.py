"""The Combinations panel saves a *named* CG molecule and shows the derived model it made.

A composition is no longer an anonymous record with a display string: it has a molecule name (`GLC-C12` by default,
from the sugar residue and carbon count), an optional link to the atomistic molecule its head came from, and a
derived -- never fitted -- parameterization. The panel is where those two choices are made, and the card beside it is
where the resulting model is read: molecule id and name, head link, beads, terms, `derived · revision 0 · source`,
status `candidate-unvalidated`, and the two doors into Bond Interactions and a CG run.

The routes are the real ones: the save builds the immutable artifacts in the test's workspace and the card reads the
catalog row back from `/api/cg-models`. The name and link defaults are the panel's own claim, asserted on the DOM.
"""
import json
import re
import urllib.parse

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
    expect(rows.first.locator('button').first).to_have_text('Open the CG run')
    expect(rows.first.locator('button').nth(1)).to_have_text('Edit terms')
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


def test_the_saved_models_row_opens_the_cg_run_after_a_reload(dashboard, live_page):
    """The row's own door, not only the side card's: the table is what a returning reader sees first."""
    page, errors = live_page
    open_panel(page, live_page.base_url)
    _save(page, 'GLC-C12')
    row = _saved_row(dashboard, 'GLC-C12')

    page.reload()
    page.get_by_role('tab', name='Combinations', exact=True).click()
    page.wait_for_function("() => document.querySelectorAll('#composition-model-rows tr').length === 1",
                           timeout=SERVER_WAIT)
    # The row's Edit terms action selects the model for the card below; the side card's door then opens the run.
    page.locator('#composition-model-rows tr button').nth(1).click()
    expect(page.locator('#composition-terms')).to_be_visible(timeout=SERVER_WAIT)
    expect(page.locator('#composition-terms-badge')).to_have_text('derived · revision 0')
    page.locator('#composition-start-run').click()
    expect(page.locator('#new')).to_be_visible(timeout=SERVER_WAIT)
    page.wait_for_function("id => document.querySelector('[name=molecule_id]').value === id",
                           arg=row['molecule_id'], timeout=SERVER_WAIT)
    page.wait_for_function("() => !document.querySelector('#start-run').disabled", timeout=SERVER_WAIT)
    expect(page.locator('#run-parameterization')).to_contain_text('derived · revision 0')
    assert errors == []


def test_editing_a_bond_saves_a_revision_and_the_run_names_it(dashboard, live_page):
    """Edit terms -> Save in place -> the New run door consumes the revision the table showed."""
    page, errors = live_page
    open_panel(page, live_page.base_url)
    # A preview has no persistence target, so the terms card stays hidden until the composition is saved.
    _preview(page)
    expect(page.locator('#composition-terms')).to_be_hidden()
    _save(page, 'GLC-C12')

    expect(page.locator('#composition-terms')).to_be_visible(timeout=SERVER_WAIT)
    expect(page.locator('#composition-terms-badge')).to_have_text('derived · revision 0')
    rows = page.locator('#composition-term-rows tr')
    expect(rows).to_have_count(7)
    # A virtual site is a model term: shown, but with no inputs to retype.
    virtual = page.locator('#composition-term-rows tr', has_text='virtual site')
    expect(virtual).to_have_count(1)
    expect(virtual.locator('input')).to_have_count(0)

    linkage = page.locator('#composition-term-rows tr', has_text='A – C01')
    expect(linkage).to_have_count(1)
    force = linkage.locator('input').nth(1)
    expect(force).to_have_value('5000')
    force.fill('3000')
    expect(page.locator('#composition-save-terms')).to_be_enabled()
    page.locator('#composition-save-terms').click()
    expect(page.locator('#composition-terms-status')).to_contain_text('Saved as revision 1', timeout=SERVER_WAIT)
    expect(page.locator('#composition-terms-badge')).to_have_text('edited · revision 1')
    expect(page.locator('#composition-provenance-list')).to_contain_text('edited · revision 1')

    row = _saved_row(dashboard, 'GLC-C12')
    assert row['parameterization']['revision'] == 1 and row['parameterization']['base'] == 'edited'
    view = dashboard.client.get(f"/api/compositions/{row['id']}/parameterizations").json
    assert [term['source'] for term in view['terms'] if term['source'] == 'manual']

    # The run door asks readiness for the revision the card showed; capture the question the form sends.
    asked = []
    page.on('request', lambda request: asked.append(request.url) if '/api/readiness' in request.url else None)
    page.locator('#composition-start-run').click()
    expect(page.locator('#new')).to_be_visible(timeout=SERVER_WAIT)
    expect(page.locator('#run-parameterization')).to_contain_text('edited · revision 1')
    page.wait_for_function("() => !document.querySelector('#start-run').disabled", timeout=SERVER_WAIT)
    assert asked, 'opening the run did not ask readiness'
    payload = json.loads(urllib.parse.parse_qs(urllib.parse.urlsplit(asked[-1]).query)['parameterization'][0])
    assert payload == {'kind': 'composition', 'composition_id': row['molecule_id'], 'composition_revision': 1}
    assert errors == []


def test_a_second_edit_keeps_the_first_override(dashboard, live_page):
    """Every save posts the complete override set: a revision applies to the derived base, not to the last edit."""
    page, errors = live_page
    open_panel(page, live_page.base_url)
    _save(page, 'GLC-C12')
    expect(page.locator('#composition-terms')).to_be_visible(timeout=SERVER_WAIT)

    linkage = page.locator('#composition-term-rows tr', has_text='A – C01')
    linkage.locator('input').nth(1).fill('3000')
    page.locator('#composition-save-terms').click()
    expect(page.locator('#composition-terms-status')).to_contain_text('Saved as revision 1', timeout=SERVER_WAIT)

    tail = page.locator('#composition-term-rows tr', has_text='C01 – C02')
    tail.locator('input').nth(1).fill('2500')
    page.locator('#composition-save-terms').click()
    expect(page.locator('#composition-terms-status')).to_contain_text('Saved as revision 2', timeout=SERVER_WAIT)
    expect(page.locator('#composition-terms-badge')).to_have_text('edited · revision 2')

    row = _saved_row(dashboard, 'GLC-C12')
    view = dashboard.client.get(f"/api/compositions/{row['id']}/parameterizations").json
    overrides = {(item['section'], tuple(item['beads'])): item['parameters']
                 for item in view['revisions'][-1]['overrides']}
    assert overrides[('bonds', ('A', 'C01'))] == [0.47, 3000]
    assert overrides[('bonds', ('C01', 'C02'))] == [0.47, 2500]
    assert errors == []
