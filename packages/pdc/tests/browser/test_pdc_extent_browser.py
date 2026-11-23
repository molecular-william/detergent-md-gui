"""The protein card's size and initial-box lines, from the extent route that measures them.

The panel asks `GET /api/pdc/proteins/<entry>/extent?margin_nm=…` (plus `initial_z_nm=` when stated and `chains=` for a selection)
and renders the route's own `dimensions_nm` and `initial_box_nm`, naming the box rule it answered with, or its
refusal sentence as text. Nothing is measured here: the route is stubbed, because the live workspace's protein list
is not the fixture's, and what these tests pin is the panel's contract with the answer. An empty micelle has no
structure to measure, so it asks nothing and shows neither line.
"""
import re
import time
from urllib.parse import parse_qs, unquote, urlsplit

from playwright.sync_api import expect

from tests.harness import browser

PROTEIN = {'id': 'molecules/1qj8/1qj8.pdb', 'name': '1qj8', 'path': 'molecules/1qj8/1qj8.pdb',
           'source': 'packaged', 'half_thickness_nm': 1.35, 'chains': ['A', 'B', 'C']}
CATALOG = {
    'templates': [{'id': 'DDM:DDM', 'name': 'DDM skeleton', 'molecule': 'DDM', 'residue': 'DDM',
                   'template': 'molecules/DDM/v1/micelle_template.json', 'registered_type': 'registered-template',
                   'files_present': True, 'missing_files': [],
                   'limitations': ['skeleton placeholder template, not a fitted detergent model']}],
    'proteins': [PROTEIN],
    'defaults': {'aggregation_number': 150, 'assessment_ns': 100, 'extension_ns': 900,
                 'box_margin_nm': 2.0},
}
ANSWER = {'protein': {'name': '1qj8'}, 'dimensions_nm': {'x': 5.2, 'y': 4.8, 'z': 6.0},
          'initial_box_nm': [9.2, 8.8, 6.0], 'rule': 'membrane'}
REFUSAL = '1qj8 states no coordinates this can measure'


def serve(page, answer):
    """The panel's reads plus the extent route under test, answered by `answer`."""
    browser.serve_pdc_new_run(page, catalogue=CATALOG)
    browser.serve_files(
        page,
        (re.compile(r'/api/pdc/conformations/runs'), {'runs': []}),
        (re.compile(r'/api/pdc/conformations/libraries'), {'libraries': []}),
        (re.compile(r'/api/setting-presets'), {'presets': [], 'default': None}),
    )
    page.route(re.compile(r'/extent'), answer)


def open_panel(page, base_url, protein=PROTEIN['id']):
    return browser.open_pdc_new_run(page, base_url, protein=protein)


def asked_queries(url):
    return parse_qs(urlsplit(url).query)


def test_the_card_renders_the_size_and_the_box_with_the_rule_the_route_names(dashboard, live_page):
    page, errors = live_page
    asked = []
    serve(page, lambda route: (asked.append(route.request.url), route.fulfill(json=ANSWER))[1])
    open_panel(page, live_page.base_url)

    expect(page.locator('.new-pdc-protein-size')).to_have_text('5.2 × 4.8 × 6.0 nm')
    expect(page.locator('.new-pdc-box-estimate')).to_have_text('membrane box 9.2 × 8.8 × 6.0 nm')

    assert asked, 'the panel never asked the extent route'
    query = asked_queries(asked[-1])
    assert query['margin_nm'] == ['2'], query
    # The starting-box z is blank by default now, so the query does not send one; the route's own 6.0 still answers.
    assert 'initial_z_nm' not in query, query
    assert query['chains'] == ['A,B,C'], query
    # The entry id travels with its leading slash stripped, exactly as the encapsulation estimate reads it.
    path = unquote(urlsplit(asked[-1]).path)
    assert path == '/api/pdc/proteins/molecules/1qj8/1qj8.pdb/extent', path

    # A structure whose file states no membrane answers with the other rule, and the line says so.
    page.route(re.compile(r'/extent'), lambda route: route.fulfill(json={**ANSWER, 'rule': 'initial'}))
    page.locator('[name=box_margin_nm]').fill('3')
    expect(page.locator('.new-pdc-box-estimate')).to_have_text('initial box 9.2 × 8.8 × 6.0 nm')
    assert errors == [], errors


def test_the_empty_micelle_hides_both_lines_and_asks_the_route_nothing(dashboard, live_page):
    page, errors = live_page
    asked = []
    serve(page, lambda route: (asked.append(route.request.url), route.fulfill(json=ANSWER))[1])
    open_panel(page, live_page.base_url, protein=None)

    expect(page.locator('.new-pdc-protein-size')).to_be_hidden()
    expect(page.locator('.new-pdc-box-estimate')).to_be_hidden()
    # The mount schedules one request; give the debounce time to fire so "no request" means none was ever asked for.
    page.wait_for_timeout(400)
    assert asked == [], f'an empty micelle asked for a protein measurement: {asked}'
    assert errors == [], errors


def test_the_routes_refusal_is_shown_as_text(dashboard, live_page):
    page, errors = live_page
    serve(page, lambda route: route.fulfill(status=400, json={'error': REFUSAL}))
    open_panel(page, live_page.base_url)

    expect(page.locator('.new-pdc-protein-size')).to_have_text(REFUSAL)
    expect(page.locator('.new-pdc-box-estimate')).to_have_text('')
    assert errors == [], errors


def test_an_older_measurement_is_cancelled_and_never_overwrites_a_newer_one(dashboard, live_page):
    """The reader can move the margin while a measurement is in flight; the last question asked is what is shown.

    The superseded question is aborted rather than left to finish and dropped, so its answer cannot land on the newer
    one at all -- and the abort is not reported as the coordinator failing to answer.
    """
    page, errors = live_page
    held, failed = [], []
    serve(page, lambda route: held.append(route))
    page.on('requestfailed', lambda request: failed.append(request))
    open_panel(page, live_page.base_url)

    def wait_for_held(count):
        for _ in range(60):
            if len(held) >= count:
                return
            page.wait_for_timeout(100)
        raise AssertionError(f'the panel asked the route {len(held)} times, expected {count}')

    wait_for_held(1)
    page.locator('[name=box_margin_nm]').fill('3')
    wait_for_held(2)
    assert asked_queries(held[0].request.url)['margin_nm'] == ['2'], held[0].request.url
    assert asked_queries(held[1].request.url)['margin_nm'] == ['3'], held[1].request.url

    # The first question was cancelled the moment the second was asked: nothing is left to answer it late.
    deadline = time.monotonic() + 5
    while not failed and time.monotonic() < deadline:
        page.wait_for_timeout(50)
    assert any('/extent' in request.url for request in failed), \
        f'the superseded measurement was left in flight: {[request.url for request in failed]}'

    held[1].fulfill(json={**ANSWER, 'initial_box_nm': [7.0, 6.0, 6.0], 'rule': 'initial'})
    expect(page.locator('.new-pdc-box-estimate')).to_have_text('initial box 7.0 × 6.0 × 6.0 nm')
    expect(page.locator('.new-pdc-protein-size')).to_have_text('5.2 × 4.8 × 6.0 nm')
    assert errors == [], errors
