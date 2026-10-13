"""The coverage estimate the panel renders, from the route that computes it.

The estimate is the server's: the panel asks
`GET /api/pdc/proteins/<entry>/encapsulation?molecule_id=<detergent>&aggregation_number=N` and renders what comes
back -- the verdict it implies from the server's own fraction, the numbers, the method the route states and its
caveat -- and when the route refuses, the route's own reason. The panel sizes nothing itself.

The live workspace has no packaged protein entry to size, so the answer is served as a fixture on the route, not
read from the developer's workspace: the panel's contract is with the route's response, and that is what these
tests pin by hand.
"""
import re
from urllib.parse import unquote, urlsplit

from playwright.sync_api import expect

# The catalogue and the mapping list the panel reads: one protein and one saved mapping, so both questions the
# route needs can be asked.
PROTEIN = {'id': 'molecules/1qj8/1qj8.pdb', 'name': '1qj8', 'path': 'molecules/1qj8/1qj8.pdb',
           'source': 'packaged', 'half_thickness_nm': 1.35}
CATALOG = {'templates': [{'id': 'DDM:DDM', 'name': 'DDM skeleton', 'molecule': 'DDM', 'residue': 'DDM',
                          'template': 'molecules/DDM/micelle_template.json',
                          'registered_type': 'registered-template', 'files_present': True, 'missing_files': [],
                          'limitations': ['skeleton placeholder template, not a fitted detergent model']}],
           'proteins': [PROTEIN],
           'defaults': {'aggregation_number': 150, 'assessment_ns': 100, 'extension_ns': 900, 'salt_molar': 0.15,
                        'box_margin_nm': 2.0, 'initial_z_nm': 6.0, 'contact_nm': 0.6,
                        'selection_threshold_fraction': 0.1, 'snapshot_interval_ns': 20.0, 'snapshot_cap': 20}}
MAPPING_FILE = 'mapping_candidate_fixture.json'
MAPPINGS = {'candidates': [{'name': 'DDM draft', 'file': MAPPING_FILE}]}

METHOD = ('Flat-area estimate from the deposited structure, no simulation. Per-atom solvent-accessible area by '
          'Shrake-Rupley (biotite.structure.sasa), summed over the transmembrane slab, divided by the area one '
          'detergent head bead covers.')
CAVEAT = ('This is a sizing aid and not a verdict: it treats the protein as a flat surface, with no curvature, '
          'packing or shape, so it says the requested count is roughly the right order and never that the micelle '
          'forms.')

# The three refusals the route states, each in the route's own words.
REFUSALS = {
    'membrane': "1qj8 states no membrane annotation, so it has no transmembrane slab to size a belt against",
    'mapping': "DDM has no saved CG mapping, so its head bead's size class -- and with it the area one detergent "
               "covers -- cannot be resolved",
    'head': 'the saved mapping mapping_candidate_fixture.json names no head bead this can size: the detergent '
            'mapping names no head bead: every physical bead is of the aliphatic carbon series',
}


def estimate_body(requested=150, fraction=0.797, needed=188.2):
    """A response shaped as the route answers, with numbers chosen so the formatting is checkable by hand."""
    return {'protein': {'name': '1qj8', 'id': PROTEIN['id'], 'source': 'packaged', 'half_thickness_nm': 1.35},
            'molecule_id': 'DDM', 'mappings': [MAPPING_FILE],
            'slab': {'axis': 'z', 'centre_nm': 0.0, 'half_thickness_nm': 1.35},
            'atoms': 1200, 'apolar_area_nm2': 41.2, 'head_radius_nm': 0.264, 'head_area_nm2': 0.2187,
            'requested': requested, 'needed': needed, 'fraction': fraction,
            'method': METHOD, 'caveat': CAVEAT}


def serve(page, body, catalog=None):
    """The reads the panel makes before it can ask, and the route under test.

    `body` handles every encapsulation request, so a case can answer 200, answer a refusal, or hold the request and
    fulfil it later in an order of its own choosing.
    """
    page.route(re.compile(r'/api/pdc/catalog'), lambda route: route.fulfill(json=catalog or CATALOG))
    page.route(re.compile(r'/api/mappings\?'), lambda route: route.fulfill(json=MAPPINGS))
    page.route(re.compile(r'/api/readiness\?'),
               lambda route: route.fulfill(json={'ready': True, 'checks': [], 'blockers': []}))
    page.route(re.compile(r'/encapsulation'), body)


def open_panel(page, base_url, *, protein=PROTEIN['id']):
    page.goto(f'{base_url}/protein-detergent/new-run')
    page.get_by_role('tab', name='New run', exact=True).click()
    # The detergent list is the panel's first fetch, and every claim here needs it to have landed.
    page.wait_for_function("() => document.querySelectorAll('#new-detergent option').length > 1", timeout=30000)
    if protein:
        # The protein list is the catalogue's answer; it is awaited so a case can choose from it.
        page.wait_for_function("() => document.querySelectorAll('#new-protein option').length > 1", timeout=30000)
        page.locator('#new-protein').select_option(protein)


def move_count(page, value):
    """Move the count, which is how a reader changes the question while an answer is in flight.

    The count is a number input now -- the coarse range slider went in T10 -- and the panel re-asks the estimate on
    its `input` event, so dispatching one is the same gesture the slider used to make.
    """
    page.evaluate("""value => {
        const count = document.querySelector('#new-count');
        count.value = String(value);
        count.dispatchEvent(new Event('input', {bubbles: true}));
    }""", value)


def test_the_estimate_renders_the_servers_numbers_its_method_and_its_caveat(dashboard, live_page):
    page, errors = live_page
    asked = []

    def answer(route):
        asked.append(route.request.url)
        route.fulfill(json=estimate_body())

    serve(page, answer)
    open_panel(page, live_page.base_url)
    # A detergent with a saved mapping, chosen: the server is the one that resolves it, so this only says the
    # control a reader would set is set.
    page.locator('#new-mapping').select_option(MAPPING_FILE)

    expect(page.locator('.new-pdc-verdict')).to_contain_text('150 detergents cover about 80% of the apolar slab')
    expect(page.locator('.new-pdc-apolar')).to_have_text('41.2 nm²')
    expect(page.locator('.new-pdc-head')).to_have_text('0.219 nm²')
    expect(page.locator('.new-pdc-need')).to_have_text('188 detergents')
    expect(page.locator('.new-pdc-have')).to_have_text('79.7%')
    expect(page.locator('.new-pdc-method')).to_contain_text('Shrake-Rupley')
    expect(page.locator('.new-pdc-caveat')).to_contain_text('flat surface')
    expect(page.locator('.new-pdc-shortfall')).to_contain_text('expect bare patches')

    assert asked, 'the panel never asked the route it renders'
    assert 'aggregation_number=150' in asked[-1] and 'molecule_id=DDM' in asked[-1], asked
    assert 'not built' not in page.locator('#new-belt-block').inner_text(), 'the retired sentence is still on the panel'
    assert errors == [], errors


def test_a_count_that_covers_the_slab_says_so_and_asks_for_nothing_more(dashboard, live_page):
    page, errors = live_page
    serve(page, lambda route: route.fulfill(json=estimate_body(requested=150, fraction=1.2, needed=125.0)))
    open_panel(page, live_page.base_url)

    expect(page.locator('.new-pdc-verdict')).to_have_text('150 detergents cover the apolar slab (120%).')
    expect(page.locator('.new-pdc-verdict')).to_have_class(re.compile(r'\benough\b'))
    expect(page.locator('.new-pdc-shortfall')).to_have_text('')
    assert errors == [], errors


def test_every_refusal_renders_the_servers_own_reason_and_never_a_blank_block(dashboard, live_page):
    page, errors = live_page
    served = {'body': {'error': REFUSALS['membrane']}}
    serve(page, lambda route: route.fulfill(status=400, json=served['body']))
    open_panel(page, live_page.base_url)

    verdict = page.locator('.new-pdc-verdict')
    expect(verdict).to_contain_text(REFUSALS['membrane'])
    assert verdict.inner_text().strip(), 'the refusal left the block blank'
    expect(page.locator('.new-pdc-estimate-table')).to_be_hidden()

    # The route's other two refusals travel the same way: whatever the reason is, those are the words shown, and no
    # number is invented beside them.
    for value, reason in ((200, REFUSALS['mapping']), (250, REFUSALS['head'])):
        served['body'] = {'error': reason}
        move_count(page, value)
        expect(verdict).to_contain_text(reason)
        expect(verdict).to_have_class(re.compile(r'\brefused\b'))
        expect(page.locator('.new-pdc-estimate-table')).to_be_hidden()
        assert '%' not in verdict.inner_text(), 'a refused estimate still states a coverage'
    assert errors == [], errors


def test_the_empty_micelle_keeps_the_experimental_number_and_asks_the_route_nothing(dashboard, live_page):
    page, errors = live_page
    asked = []
    serve(page, lambda route: (asked.append(route.request.url), route.fulfill(json=estimate_body()))[1])
    open_panel(page, live_page.base_url, protein=None)

    expect(page.locator('#new-empty-block')).to_be_visible()
    expect(page.locator('#new-belt-block')).to_be_hidden()
    expect(page.locator('.new-pdc-empty-number')).to_have_text('— not recorded yet')
    expect(page.locator('.new-pdc-empty-count')).to_have_text('150')
    assert asked == [], 'an empty micelle has no belt, so no estimate may be asked for'
    assert errors == [], errors


def test_each_initialisation_style_keeps_its_own_sentence_beside_the_servers_answer(dashboard, live_page):
    page, errors = live_page
    serve(page, lambda route: route.fulfill(json=estimate_body()))
    open_panel(page, live_page.base_url)

    # Pre-assembled: the count *is* the belt, and the server's number sits beside that sentence rather than
    # replacing it.
    expect(page.locator('.new-pdc-estimate-note')).to_contain_text('belt is exactly the 150 detergents')
    expect(page.locator('.new-pdc-verdict')).to_contain_text('150 detergents cover about 80%')

    # Self-assembly: the count is where the belt starts, and the server's answer still stands.
    page.locator('#new-placement').select_option('self-assembly')
    expect(page.locator('.new-pdc-estimate-note')).to_contain_text('belt starts from 150 detergents')
    expect(page.locator('.new-pdc-verdict')).to_contain_text('150 detergents cover about 80%')
    assert errors == [], errors


def test_a_catalogue_id_that_is_a_path_is_asked_for_the_way_the_route_reads_it(dashboard, live_page):
    """An imported structure's id is an absolute path, and the route reads it with the leading slash stripped.

    That is also the only spelling the route answers directly: a percent-encoded leading slash decodes to `//` in
    the path, which the server answers with a redirect rather than the estimate.
    """
    page, errors = live_page
    asked = []
    imported = {**PROTEIN, 'id': '/workspace/proteins/1qj8.pdb', 'path': '/workspace/proteins/1qj8.pdb',
                'source': 'imported'}
    serve(page, lambda route: (asked.append(route.request.url), route.fulfill(json=estimate_body()))[1],
          catalog={**CATALOG, 'proteins': [imported]})
    open_panel(page, live_page.base_url, protein=imported['id'])

    expect(page.locator('.new-pdc-verdict')).to_contain_text('150 detergents cover about 80%')
    assert asked, 'the panel never asked the route'
    path = unquote(urlsplit(asked[-1]).path)
    assert path == '/api/pdc/proteins/workspace/proteins/1qj8.pdb/encapsulation', path
    assert errors == [], errors


def test_an_older_answer_never_overwrites_a_newer_one(dashboard, live_page):
    """The reader can move the count while a request is in flight; the last question asked is the one on screen."""
    page, errors = live_page
    held = []
    serve(page, lambda route: held.append(route))
    open_panel(page, live_page.base_url)

    def wait_for_held(count):
        for _ in range(60):
            if len(held) >= count:
                return
            page.wait_for_timeout(100)
        raise AssertionError(f'the panel asked the route {len(held)} times, expected {count}')

    wait_for_held(1)
    move_count(page, 300)
    wait_for_held(2)

    oldest, newest = held[0], held[1]
    assert 'aggregation_number=150' in oldest.request.url, oldest.request.url
    assert 'aggregation_number=300' in newest.request.url, newest.request.url

    # The newer answer is delivered first, the older one second: without a guard the late, stale answer would win.
    newest.fulfill(json=estimate_body(requested=300, fraction=0.9, needed=111.0))
    expect(page.locator('.new-pdc-verdict')).to_contain_text('300 detergents cover about 90%')
    oldest.fulfill(json=estimate_body(requested=150, fraction=0.1, needed=1882.0))
    page.wait_for_timeout(300)

    expect(page.locator('.new-pdc-verdict')).to_contain_text('300 detergents cover about 90%')
    assert '10%' not in page.locator('#new-belt-block').inner_text(), 'the stale answer overwrote the newer one'
    assert errors == [], errors


def test_the_explanation_starts_hidden_and_opens_when_the_reader_asks(dashboard, live_page):
    """The verdict and the table are the answer; the method, its caveat and the note about what the estimate is not
    wait behind a disclosure until the reader asks for them.

    Asserted by visibility, not by text: the prose is in the DOM whether the disclosure is open or closed, so a
    `to_contain_text` would pass on a collapsed panel. The table and the verdict are the half that stays out.
    """
    page, errors = live_page
    serve(page, lambda route: route.fulfill(json=estimate_body()))
    open_panel(page, live_page.base_url)

    # What a reader sees without asking: the verdict, the numbers, and the summary to open.
    expect(page.locator('.new-pdc-verdict')).to_be_visible()
    expect(page.locator('.new-pdc-estimate-table')).to_be_visible()
    explanation = page.locator('.new-pdc-explanation')
    expect(explanation).to_be_visible()
    assert not explanation.evaluate('el => el.open'), 'the explanation is open before anyone asked for it'

    # The explanatory prose is in the DOM and not visible.
    expect(page.locator('.new-pdc-method')).to_be_hidden()
    expect(page.locator('.new-pdc-caveat')).to_be_hidden()
    expect(page.locator('.new-pdc-about')).to_be_hidden()

    # Opening it shows every sentence, and leaves the verdict and the numbers where they were.
    explanation.locator('summary').click()
    assert explanation.evaluate('el => el.open')
    expect(page.locator('.new-pdc-method')).to_be_visible()
    expect(page.locator('.new-pdc-method')).to_contain_text('Shrake-Rupley')
    expect(page.locator('.new-pdc-caveat')).to_be_visible()
    expect(page.locator('.new-pdc-about')).to_be_visible()
    expect(page.locator('.new-pdc-verdict')).to_be_visible()
    expect(page.locator('.new-pdc-estimate-table')).to_be_visible()
    assert errors == [], errors
