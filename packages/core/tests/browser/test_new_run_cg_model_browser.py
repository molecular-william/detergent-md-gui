"""The New run parameterization selector: one model, grouped by mapping, chosen before the run starts.

A CG run consumes one parameterization of the selected molecule -- a saved mapping's revision, or the molecule's
published Martini 3 reference. The selector is grouped by mapping, names each revision's engine, currency and date,
marks a mapping that has no revision yet, and states whether the revision stored its starting frame. The readiness
and queue payloads are read here from the requests the panel makes, because the nested `parameterization` object is
the contract the run type validates.

The stores are stubbed with the routes' own shapes: a fixture workspace holds no fitted revision, and what this file
judges is what the panel does with the answer, not the fitting pipeline.
"""
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect

from tests.harness import browser

CANDIDATES = [
    {'name': 'DDM · ring mapping', 'file': 'ddm-ring.json', 'mapping_hash': 'a' * 64,
     'mapping_content_hash': 'b' * 64, 'validation': {'issues': [], 'can_reuse': True}},
    {'name': 'DDM · tail mapping', 'file': 'ddm-tail.json', 'mapping_hash': 'c' * 64,
     'mapping_content_hash': 'd' * 64, 'validation': {'issues': [], 'can_reuse': True}},
]

RING = {
    'summary': {'revision': 2, 'parameterized': True},
    'revisions': [
        {'revision': 2, 'engine': 'fast-forward', 'created_at': '2026-11-09T10:00:00+00:00',
         'coordinates': {'directory': 'records/x/2', 'files': [{'name': 'mapped.gro'}, {'name': 'mapped.xtc'}]},
         'aa_reference': {'run_id': '5a41c02e7d13', 'temperature_k': 300.0, 'production_ns': 10.0}},
        {'revision': 1, 'engine': 'bartender', 'created_at': '2026-11-05T10:00:00+00:00',
         'aa_reference': {'run_id': '5a41c02e7d13', 'temperature_k': 300.0, 'production_ns': 10.0}},
    ],
    'jobs': [],
}
TAIL = {'summary': {'revision': 0, 'parameterized': False}, 'revisions': [], 'jobs': []}

DEFAULT_VALUES = {'aa_nvt_ps': 100, 'aa_npt_ps': 1000, 'aa_production_ps': 10000, 'temperature_k': 300,
                  'pressure_bar': 1, 'output_interval_ps': 10, 'box_nm': 4, 'aa_seed': 1,
                  'mdrun_ntomp': 8, 'mdrun_ranks': 1, 'mdrun_gpu': 0, 'mdrun_cpt': 10,
                  'mdrun_nb': 'auto', 'mdrun_pme': 'auto', 'constraints': 'all-bonds',
                  'force_field': 'charmm36-jul2022', 'cg_equil_ps': 10, 'cg_production_ps': 10000, 'cg_seed': 7}


def stub(page, submissions=None):
    """Serve the mapping list, each mapping's record, and readiness; record the queue payload."""
    def defaults(route):
        query = parse_qs(urlsplit(route.request.url).query)
        values = dict(DEFAULT_VALUES)
        if (query.get('parameterization_kind') or [''])[0] == 'reference':
            values = {'sugar_entry': 'SUCR', 'cg_equil_ps': 5000.0, 'cg_production_ps': 10000.0,
                      'temperature_k': 310.0, 'cg_seed': 20260911, 'output_interval_ps': 10.0,
                      'mdrun_ntomp': 8, 'mdrun_ranks': 1, 'mdrun_gpu': 0, 'mdrun_cpt': 10,
                      'mdrun_nb': 'auto', 'mdrun_pme': 'auto'}
        route.fulfill(json={'values': values, 'sources': {'stub': 'stub'}, 'profile': 'stub', 'force_fields': []})

    def records(route):
        query = parse_qs(urlsplit(route.request.url).query)
        content = (query.get('content_hash') or [''])[0]
        route.fulfill(json=RING if content == CANDIDATES[0]['mapping_content_hash'] else TAIL)

    def reference(route):
        # DDM has no published Martini 3 entry, which is an answer rather than a failure.
        route.fulfill(status=404, json={'error': 'DDM has no published Martini 3 sugar entry'})

    page.route('**/api/mappings?view=summary&molecule_id=*',
               lambda route: route.fulfill(json={'candidates': CANDIDATES}))
    page.route('**/api/bonded-parameterizations?*', records)
    page.route('**/api/mappings/reference/*', reference)
    page.route('**/api/defaults?*', defaults)
    page.route('**/api/setting-presets?*', lambda route: route.fulfill(json={'presets': [], 'default': None}))
    page.route('**/api/readiness?*', lambda route: route.fulfill(json={'ready': True, 'checks': [], 'blockers': []}))
    if submissions is not None:
        def submit(route):
            submissions.append(route.request.post_data_json)
            route.fulfill(status=201, json={'id': '222222222222'})
        page.route('**/', submit)


def open_panel(page, base_url):
    def ready(page):
        page.wait_for_function("() => document.querySelector('[name=molecule_id]').value === 'DDM'", timeout=30000)
        page.wait_for_function(
            "() => document.querySelectorAll('#run-parameterization option').length >= 3", timeout=30000)

    return browser.open_panel(page, base_url, '/detergent-validation/new-run', ready=ready)


def options(page):
    return page.evaluate("""Array.from(document.querySelectorAll('#run-parameterization option')).map(option => ({
        value: option.value, text: option.textContent, kind: option.dataset.kind,
        mapping: option.dataset.mapping, revision: option.dataset.revision,
        coordinates: option.dataset.coordinates}))""")


def test_the_selector_is_grouped_by_mapping_and_names_each_revision(dashboard, live_page):
    """A mapping's revisions read as history: number, currency, engine and date, and the draft when there is none."""
    page, errors = live_page
    stub(page)
    open_panel(page, live_page.base_url)

    groups = page.evaluate("Array.from(document.querySelectorAll('#run-parameterization optgroup')).map(g => g.label)")
    assert groups == ['DDM · ring mapping', 'DDM · tail mapping'], groups
    listed = options(page)
    assert [item['text'] for item in listed] == [
        'DDM · ring mapping · Revision 2 · current · fast-forward · 2026-11-09',
        'DDM · ring mapping · Revision 1 · earlier · bartender · 2026-11-05',
        'Draft mapping connectivity (no parameterization)',
    ], listed
    assert [item['coordinates'] for item in listed] == ['stored', 'none', 'none']
    # The first mapping's current revision is what opens, and the review names it.
    expect(page.locator('#run-parameterization')).to_have_value('revision:ddm-ring.json:2')
    expect(page.locator('#run-parameterization-summary')).to_contain_text('Revision 2 · current · fast-forward')
    expect(page.locator('#run-aa-summary')).to_have_text('5a41c02e7d13 · 300 K · 10 ns')
    expect(page.locator('#run-coordinates-summary')).to_have_text('stored · revision 2')
    expect(page.locator('#starting-coordinates-field')).to_be_visible()
    assert errors == []


def test_a_revision_is_posted_nested_and_the_aa_source_is_read_only(dashboard, live_page):
    """The queue body carries `parameterization`, never a top-level mapping, method or sugar entry."""
    page = live_page.page
    submissions = []
    stub(page, submissions)
    open_panel(page, live_page.base_url)

    page.locator('#start-run').click()
    expect(page.locator('#notice')).to_have_text('Run queued.')
    assert len(submissions) == 1, submissions
    body = submissions[0]
    assert body['run_type'] == 'cg' and body['molecule_id'] == 'DDM'
    assert body['parameterization'] == {'kind': 'revision', 'mapping_candidate': 'ddm-ring.json',
                                        'revision': 2, 'starting_coordinates': 'stored'}, body['parameterization']
    assert 'sugar_entry' not in str(body['parameterization'])
    for retired in ('method', 'mapping_candidate', 'reference_run_id', 'sugar_entry', 'profile'):
        assert retired not in body, f'{retired} is still sent: {body}'
    # The AA half's settings still travel, because the adapter mirrors them into the CG dialect it records.
    assert body['aa_nvt_ps'] == '100' and body['cg_production_ps'] == '10000'
    assert live_page.errors == []


def test_an_earlier_revision_without_a_stored_frame_chooses_re_map(dashboard, live_page):
    """The stored default is annotated and withdrawn when the revision records no frame; the run re-maps instead."""
    page = live_page.page
    submissions = []
    stub(page, submissions)
    open_panel(page, live_page.base_url)

    page.locator('#run-parameterization').select_option('revision:ddm-ring.json:1')
    expect(page.locator('#run-parameterization-summary')).to_contain_text('Revision 1 · earlier · bartender')
    expect(page.locator('#run-coordinates-summary')).to_have_text('re-map the AA reference')
    stored = page.locator('#run-parameterization option[value="revision:ddm-ring.json:1"]')
    assert stored.get_attribute('data-coordinates') == 'none'
    expect(page.locator('#starting-coordinates')).to_have_value('remap')
    stored_option = page.locator('#starting-coordinates option[value=stored]')
    expect(stored_option).to_have_text('Stored with this parameterization · no coordinates recorded')
    expect(page.locator('#starting-coordinates-note')).to_contain_text(
        'choose Re-map the AA reference')

    page.locator('#start-run').click()
    expect(page.locator('#notice')).to_have_text('Run queued.')
    assert submissions[0]['parameterization']['revision'] == 1, submissions
    assert submissions[0]['parameterization']['starting_coordinates'] == 'remap', submissions
    assert live_page.errors == []


def test_a_mapping_without_a_revision_is_offered_as_a_draft(dashboard, live_page):
    """The draft states the mapping's connectivity and carries no revision; it is a state, not a silent fit."""
    page = live_page.page
    submissions = []
    stub(page, submissions)
    open_panel(page, live_page.base_url)

    page.locator('#run-parameterization').select_option('draft:ddm-tail.json')
    expect(page.locator('#run-parameterization-summary')).to_have_text(
        'Draft mapping connectivity (no parameterization)')
    expect(page.locator('#run-aa-summary')).to_have_text('no parameterization selected')
    expect(page.locator('#starting-coordinates-field')).to_be_hidden()

    page.locator('#start-run').click()
    expect(page.locator('#notice')).to_have_text('Run queued.')
    payload = submissions[0]['parameterization']
    assert payload['kind'] == 'revision' and payload['mapping_candidate'] == 'ddm-tail.json'
    assert payload['revision'] is None
    assert live_page.errors == []


def test_the_door_opens_cg_bond_interactions_on_the_selected_mapping(dashboard, live_page):
    """The door preselects the model the selector names through the hidden bridge the bonded panel keeps for it."""
    page = live_page.page
    stub(page)
    open_panel(page, live_page.base_url)

    page.locator('#run-parameterization').select_option('revision:ddm-ring.json:2')
    door = page.locator('#open-bonded')
    expect(door).to_have_attribute(
        'href', '/detergent-validation/bond-interactions?mapping_candidate=ddm-ring.json')
    door.click()
    expect(page.locator('#bonded')).to_be_visible()
    expect(page.locator('#bonded-mapping-select')).to_have_value('ddm-ring.json')
    assert page.url.endswith('/detergent-validation/bond-interactions?mapping_candidate=ddm-ring.json'), page.url
    assert live_page.errors == []
