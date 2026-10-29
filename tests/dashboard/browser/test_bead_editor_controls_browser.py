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
    return candidate


def open_editor(page, live_page, molecule=MOLECULE):
    page.goto(f'{live_page.base_url}/detergent-validation/bead-assignment')
    page.locator('#tab-mappings').click()
    page.wait_for_function("() => document.querySelector('#mapping-molecule')?.options.length > 0", timeout=30000)
    page.locator('#mapping-molecule').select_option(molecule)
    # The status line and the table both still describe the previously selected molecule until this load answers,
    # so the workspace's own busy state is what says the editor has switched.
    expect(page.locator('.molecule-mapping-workspace')).to_have_attribute('aria-busy', 'false')
    expect(page.locator('#mapping-editor-status')).to_contain_text('loaded', timeout=30000)
    # The table fills before the 3D view finishes drawing, and every test here reads the drawn stage.
    expect(page.locator(OVERLAY)).to_have_attribute('aria-busy', 'false')
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
    candidate = seed_candidate(dashboard)
    page, errors = live_page
    open_editor(page, live_page)

    # The expected count is the seeded candidate's, not a guess that the table is ready: the editor replaces its rows
    # whenever a molecule or a candidate lands, so the assertion is also the wait.
    rows = page.locator('#mapping-bead-rows tr')
    expect(rows).to_have_count(len(candidate['beads']))
    before = rows.count()

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


def _label_representations(page):
    """The label representations the viewer is holding right now, read from the stage it publishes."""
    return [item for item in page.locator(OVERLAY).evaluate(REPRESENTATIONS) or [] if item['type'] == 'label']


def test_the_atom_numbers_can_be_turned_off_and_on_again_without_a_reload(dashboard, live_page):
    """The numbering is a toggle, and flipping it must not cost a request or a redraw of the molecule.

    The molecule file is fetched once, by `update()`, and only when the assignment changed; a toggle acts on the
    structure the viewer is already holding. So the request count is part of the claim, not decoration: it is what
    separates "the numbers were turned off" from "the view was rebuilt without them".
    """
    seed_candidate(dashboard)
    page, errors = live_page
    open_editor(page, live_page)

    requests = []
    page.on('request', lambda request: requests.append(request.url) if '/api/mappings/overlay3d' in request.url else None)
    page.wait_for_function("() => document.querySelector('#mapping-editor-overlay3d')?.overlayStage", timeout=30000)
    before = len(requests)

    numbers = page.get_by_role('checkbox', name='Number atoms')
    expect(numbers).to_be_visible()
    # The default is on, which is what the test above pins: an editor that opened unnumbered would send a reader
    # looking for a control before they could match a table row against the picture.
    expect(numbers).to_be_checked()
    labels = _label_representations(page)
    assert labels, 'the overlay opened unnumbered'
    assert labels[0]['labelType'] == 'serial', labels

    numbers.uncheck()
    expect(numbers).not_to_be_checked()
    assert _label_representations(page) == [], 'the numbers survived being turned off'
    # Gone means gone: the molecule is still drawn, so removing the numbers took nothing else with it.
    assert page.locator(OVERLAY).evaluate("(el) => (el.overlayStage.compList[0].reprList || [])"
                                          ".map(repr => repr.getType())") == ['ball+stick']

    numbers.check()
    expect(numbers).to_be_checked()
    labels = _label_representations(page)
    assert labels and labels[0]['labelType'] == 'serial', labels
    # Neither direction asked the server for anything: no refetch, no flicker, no window where the molecule is gone.
    assert len(requests) == before, requests
    assert errors == []
    # Leave the reader's default where the rest of the file expects to find it.
    expect(numbers).to_be_checked()


def test_the_numbering_choice_survives_a_reload(dashboard, live_page):
    """A reloaded page comes up the way it was left, and the checkbox says so before the molecule is drawn.

    The reload is a fresh document on the same origin, and the template carries no `checked` attribute, so an
    unchecked box here can only have been read back out of storage -- which is the claim under test.
    """
    seed_candidate(dashboard)
    page, errors = live_page
    open_editor(page, live_page)

    expect(page.get_by_role('checkbox', name='Number atoms')).to_be_checked()
    page.get_by_role('checkbox', name='Number atoms').uncheck()
    assert _label_representations(page) == []

    page.reload()
    # The panel mounts itself from the URL and loads the first molecule, so its "loaded" line is the wait: the
    # restore happens on that mount, ahead of the structure.
    expect(page.locator('#mapping-editor-status')).to_contain_text('loaded', timeout=30000)
    expect(page.get_by_role('checkbox', name='Number atoms')).not_to_be_checked()

    # Same molecule as before the reload, so the overlay drawn on this fresh page can be read the same way.
    page.locator('#mapping-molecule').select_option(MOLECULE)
    page.locator('#mapping-bead-rows tr').first.wait_for(timeout=30000)
    page.wait_for_function("() => document.querySelector('#mapping-editor-overlay3d')?.overlayStage"
                           "?.compList.length", timeout=30000)
    assert _label_representations(page) == [], 'the reloaded page drew the numbers back'
    assert page.locator(OVERLAY).evaluate("(el) => (el.overlayStage.compList[0].reprList || [])"
                                          ".map(repr => repr.getType())") == ['ball+stick']
    assert errors == []

    # And the reload is not a one-way door: ticking it here numbers the molecule this page is holding, and that
    # choice is what the next load reads back.
    page.get_by_role('checkbox', name='Number atoms').check()
    assert len(_label_representations(page)) == 1
    assert page.evaluate("localStorage.getItem('ddm.mappingAtomLabels')") == 'true'
