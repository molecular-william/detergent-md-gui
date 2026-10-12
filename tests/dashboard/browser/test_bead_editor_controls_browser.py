"""The bead editor's 3D view and its bead buttons: numbers you can read, and two controls below the table.

The ask, in order: atoms twice as large, atoms numbered so a table row can be matched against the picture, and "Add
new bead" / "Delete selected bead" below the table. The numbers are the interesting half. The overlay draws the
molecule's PDB, and that file's serials *are* the mapping's atom ids, so labelling by serial is what turns a row's
`atoms` field from a guess into something a reader can check against the view.
"""
from playwright.sync_api import expect

MOLECULE = 'Maltose'
OVERLAY = '#mapping-editor-overlay3d'

# What the viewer is actually holding, read from the stage the panel publishes for tests.
REPRESENTATIONS = """(el) => {
  const stage = el.overlayStage;
  if (!stage) return null;
  const molecule = stage.compList[0];
  return (molecule?.reprList || []).map(repr => ({
    type: repr.getType(),
    radiusScale: (repr.parameters || {}).radiusScale,
    labelType: (repr.parameters || {}).labelType,
  }));
}"""


def seed_candidate(dashboard, molecule=MOLECULE):
    """A saved candidate for `molecule`, through the panel's own routes."""
    from dashboard.models import mappings
    from dashboard.models.mappings import context as mapping_context

    context = dashboard.client.get(f'/api/mappings/context?molecule_id={molecule}').get_json()['context']
    candidate = mappings.automatic_candidate(mapping_context.as_structure(context), molecule)
    candidate['molecule_id'] = molecule
    candidate['molecule_snapshot'] = context['snapshot']
    response = dashboard.client.post('/api/mappings/drafts', json=candidate)
    assert response.status_code == 201, response.get_json()
    return context


def open_editor(page, live_page, molecule=MOLECULE):
    page.goto(f'{live_page.base_url}/detergent-validation/bead-assignment')
    page.locator('#tab-mappings').click()
    page.wait_for_function("() => document.querySelector('#mapping-molecule')?.options.length > 0", timeout=30000)
    page.locator('#mapping-molecule').select_option(molecule)
    expect(page.locator('#mapping-editor-status')).to_contain_text('loaded', timeout=30000)
    page.locator('#mapping-bead-rows tr').first.wait_for(timeout=30000)


def test_the_atoms_are_twice_the_size_and_numbered_by_their_mapping_id(dashboard, live_page):
    seed_candidate(dashboard)
    page, errors = live_page
    open_editor(page, live_page)

    expect(page.locator(OVERLAY)).to_be_visible()
    representations = page.locator(OVERLAY).evaluate(REPRESENTATIONS)
    assert representations, 'the overlay is holding no representations'

    atoms = next((item for item in representations if item['type'] == 'ball+stick'), None)
    assert atoms is not None, representations
    assert atoms['radiusScale'] is not None and 0.85 <= atoms['radiusScale'] <= 0.95, representations

    labels = next((item for item in representations if item['type'] == 'label'), None)
    assert labels is not None, f'the atoms are not numbered: {representations}'
    # Serial, not atomindex: the PDB's serial is the id the table's `atoms` column lists.
    assert labels['labelType'] == 'serial', labels
    assert errors == []


def test_add_and_delete_beads_sit_below_the_table_and_act_on_the_selection(dashboard, live_page):
    seed_candidate(dashboard)
    page, errors = live_page
    open_editor(page, live_page)

    rows = page.locator('#mapping-bead-rows tr')
    before = rows.count()
    assert before > 0, 'the seeded candidate drew no bead rows'

    add = page.get_by_role('button', name='Add new bead')
    delete = page.get_by_role('button', name='Delete selected bead')
    expect(add).to_be_visible()
    expect(delete).to_be_visible()
    expect(delete).to_be_disabled()

    # "Below the table" is the ask, so it is measured rather than assumed.
    table = page.locator('#mapping-bead-rows').bounding_box()
    assert add.bounding_box()['y'] >= table['y'] + table['height'] - 1, (table, add.bounding_box())

    # Clicking a row selects it; the button acts on that selection.
    first = rows.first
    first.click()
    expect(first).to_have_attribute('aria-selected', 'true')
    expect(delete).to_be_enabled()

    # A new bead arrives selected, so the button is ready for it without a second click -- and the row that was
    # selected before is not, because the selection is one row at a time.
    add.click()
    expect(rows).to_have_count(before + 1)
    expect(rows.last).to_have_attribute('aria-selected', 'true')
    expect(first).to_have_attribute('aria-selected', 'false')
    expect(delete).to_be_enabled()

    delete.click()
    expect(rows).to_have_count(before)
    expect(delete).to_be_disabled()
    assert errors == []
