"""The setup card's other way in: a PDB id typed into the panel.

The control is small; the assertion that matters is the refresh. The catalogue is cached with a sixty-second
lifetime, so a panel that trusted its cache would offer every structure except the one just imported -- the list the
user sees is the behaviour, and it is what these tests measure.
"""
import re

from playwright.sync_api import expect

BEFORE = {'templates': [], 'proteins': [], 'defaults': {'aggregation_number': 150}}
AFTER = {'templates': [],
         'proteins': [{'id': 'workspace/proteins/1qj8.pdb', 'name': '1qj8', 'path': 'workspace/proteins/1qj8.pdb',
                       'source': 'imported', 'half_thickness_nm': 1.18}],
         'defaults': {'aggregation_number': 150}}


def serve(page, posted, served, *, status=201, body=None):
    """The panel's own endpoints: the catalogue changing after the import, and the POST captured instead of sent."""

    def catalog(route):
        served.append(route.request.url)
        route.fulfill(json=AFTER if len(served) > 1 else BEFORE)

    page.route(re.compile(r'/api/pdc/catalog'), catalog)
    page.route(re.compile(r'/api/mappings\?'), lambda route: route.fulfill(json={'candidates': []}))

    def imported(route):
        posted.append(route.request.post_data_json or {})
        route.fulfill(status=status, json=body or {'pdbid': '1qj8', 'half_thickness_nm': 1.18})

    page.route(re.compile(r'/api/pdc/proteins/import'), imported)


def test_an_imported_id_is_offered_and_what_the_file_states_is_said(dashboard, live_page):
    page, errors = live_page
    posted, served = [], []
    serve(page, posted, served)
    page.goto(f'{live_page.base_url}/protein-detergent/complexes')

    expect(page.locator('#pdc-import')).to_be_visible()
    expect(page.locator('#pdc-protein')).to_have_value('')          # no protein until one is chosen
    before = len(served)

    page.locator('#pdc-protein-id').fill('1qj8')
    page.locator('#pdc-import').click()

    expect(page.locator('#pdc-import-status')).to_contain_text('1.18', timeout=30000)
    assert posted == [{'pdbid': '1qj8'}], posted
    assert len(served) > before, 'the catalogue was served from its cache rather than re-read'

    # Offered, and selected: an import is a way of choosing a protein, not a side errand.
    select = page.locator('#pdc-protein')
    expect(select.locator('option')).to_have_text(['No protein (empty micelle)', '1qj8'])
    expect(select).to_have_value('workspace/proteins/1qj8.pdb')
    assert page.locator('#pdc-protein-id').input_value() == '', 'the field is cleared for the next id'
    assert errors == [], errors


def test_a_refused_import_says_why_and_leaves_the_list_as_it_was(dashboard, live_page):
    """The boundary's refusal is the user's only feedback, and nothing may be added to a list nothing was added to.

    The id used here is four characters on purpose. The field's own `maxlength="4"` means the UI cannot express
    `1qj8.pdb` or a traversal path at all -- the browser truncates as you type -- so what it *can* send is a
    four-character string the server still refuses, and that is the refusal a user can actually meet.
    """
    page, errors = live_page
    posted, served = [], []
    serve(page, posted, served, status=400, body={'error': 'a PDB id is four letters or digits, not "1q;8"'})
    page.goto(f'{live_page.base_url}/protein-detergent/complexes')
    expect(page.locator('#pdc-import')).to_be_visible()

    page.locator('#pdc-protein-id').fill('1q;8')
    page.locator('#pdc-import').click()

    expect(page.locator('#pdc-import-status')).to_contain_text('four letters or digits', timeout=30000)
    expect(page.locator('#pdc-protein').locator('option')).to_have_text(['No protein (empty micelle)'])
    assert page.locator('#pdc-protein-id').input_value() == '1q;8', 'the refused id stays to be corrected'
    assert errors == [], errors
