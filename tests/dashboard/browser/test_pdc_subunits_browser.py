"""T9: choosing which subunits go into the simulation, and the estimate moving with the choice.

A deposited OPM entry can be an assembly -- 1AT9 is a trimer, 5,334 ATOM atoms across chains A/B/C -- and the
estimate and the build both take the whole file unless the panel narrows it. The selection is a row of tick boxes,
one per chain the entry declares, each carrying its chain id; this pins four claims:

- the ticks appear for an entry that declares chains, every one ticked (the whole file, as before);
- the estimate is *asked for the same selection*, and its numbers move with it. A picker that leaves the block
  unchanged is the defect this test exists to catch: chain A alone is a smaller slab than all three, so the two
  selections cannot render the same number;
- the run carries `protein_chains`; a run with no protein, or one whose entry declares none, is the whole file;
- no tick at all is a run with no protein to build, so the launch is blocked with the reason rather than queued
  with an empty selection.

The numbers are the ones the plan records for 1AT9 measured: chain A alone is 38 nm^2, all three are 75.285 nm^2.
They are served as a fixture keyed on the request's `chains` query, so the assertion is on what the panel asked for
as well as what it showed.
"""
import re
from urllib.parse import unquote

from playwright.sync_api import expect

TRIMER = {'id': 'molecules/1at9/1at9.pdb', 'name': '1at9', 'path': 'molecules/1at9/1at9.pdb',
          'source': 'imported', 'half_thickness_nm': 1.5, 'chains': ['A', 'B', 'C']}
CATALOG = {
    'templates': [{'id': 'DDM:DDM', 'name': 'DDM skeleton', 'molecule': 'DDM', 'residue': 'DDM',
                   'template': 'molecules/DDM/micelle_template.json', 'registered_type': 'registered-template',
                   'files_present': True, 'missing_files': [],
                   'limitations': ['skeleton placeholder template, not a fitted detergent model']}],
    'proteins': [TRIMER],
    'defaults': {'aggregation_number': 150, 'assessment_ns': 100, 'extension_ns': 900, 'salt_molar': 0.15,
                 'box_margin_nm': 2.0, 'initial_z_nm': 6.0, 'contact_nm': 0.6,
                 'selection_threshold_fraction': 0.1, 'snapshot_interval_ns': 20.0, 'snapshot_cap': 20},
}
MAPPING_FILE = 'mapping_candidate_fixture.json'
MAPPINGS = {'candidates': [{'name': 'DDM draft', 'file': MAPPING_FILE}]}
# The apolar area each selection is measured to have, from the plan for 1AT9.
APOLAR = {'A': 38.0, 'A,B,C': 75.285}


def body(chains):
    apolar = APOLAR[chains]
    head = 0.2187
    needed = apolar / head
    return {'protein': {'name': '1at9', 'id': TRIMER['id'], 'source': 'imported', 'half_thickness_nm': 1.5},
            'molecule_id': 'DDM', 'mappings': [MAPPING_FILE],
            'chains': chains.split(','),
            'slab': {'axis': 'z', 'centre_nm': 0.0, 'half_thickness_nm': 1.5},
            'atoms': 1200, 'apolar_area_nm2': apolar, 'head_radius_nm': 0.264, 'head_area_nm2': head,
            'requested': 150, 'needed': needed, 'fraction': 150 * head / apolar,
            'method': 'Flat-area estimate from the deposited structure.',
            'caveat': 'This is a sizing aid and not a verdict.'}


def served_chains(url):
    """The `chains` query the panel sent, decoded, or None when it sent one whole-file question."""
    match = re.search(r'[?&]chains=([^&]*)', url)
    return unquote(match.group(1)) if match else None


def serve(page, asked=None):
    page.route(re.compile(r'/api/pdc/catalog'), lambda route: route.fulfill(json=CATALOG))
    page.route(re.compile(r'/api/mappings\?'), lambda route: route.fulfill(json=MAPPINGS))
    page.route(re.compile(r'/api/readiness\?'),
               lambda route: route.fulfill(json={'ready': True, 'checks': [], 'blockers': []}))

    def estimate(route):
        chains = served_chains(route.request.url)
        if asked is not None:
            asked.append(chains)
        route.fulfill(json=body(chains or 'A,B,C'))

    page.route(re.compile(r'/encapsulation'), estimate)


def open_panel(page, base_url, *, protein=TRIMER['id']):
    page.goto(f'{base_url}/protein-detergent/new-run')
    page.get_by_role('tab', name='New run', exact=True).click()
    page.wait_for_function("() => document.querySelectorAll('#new-detergent option').length > 1", timeout=30000)
    page.wait_for_function("() => document.querySelectorAll('#new-protein option').length > 1", timeout=30000)
    if protein:
        page.locator('#new-protein').select_option(protein)


def ticks(page):
    """The tick boxes as rendered: each chain id with whether it is ticked."""
    return page.evaluate("Array.from(document.querySelectorAll('[name=protein_chains]')).map(b => [b.value, b.checked])")


def tick(page, *chains):
    """Tick exactly the named chains and untick the rest -- the reader's gesture on the checkbox row.

    Every box is set before any event fires: setting one box and dispatching immediately would ask the route about a
    half-applied selection (`A,C` while moving from all to `A`), which is a state no reader ever causes. Setting the
    boxes first also means each `change` describes the same, final selection.
    """
    page.evaluate("""chains => {
        const want = new Set(chains);
        const boxes = [...document.querySelectorAll('[name=protein_chains]')];
        for (const box of boxes) box.checked = want.has(box.value);
        for (const box of boxes) box.dispatchEvent(new Event('change', {bubbles: true}));
    }""", list(chains))


def test_the_ticks_default_to_every_chain_the_entry_declares(dashboard, live_page):
    """An assembly entry offers a tick per chain, all ticked: the default run is still the whole file."""
    page, errors = live_page
    serve(page)
    open_panel(page, live_page.base_url)

    block = page.locator('#new .new-pdc-subunits')
    expect(block).to_be_visible()
    assert ticks(page) == [['A', True], ['B', True], ['C', True]], ticks(page)
    expect(page.locator('.new-pdc-subunits-note')).to_contain_text('3 of 3 subunits selected')
    expect(page.locator('[data-new-summary=subunits]')).to_contain_text('3/3')

    # No protein, or an entry that declares none, is the whole-file run: no ticks to make a choice against.
    page.locator('#new-protein').select_option('')
    expect(block).to_be_hidden()
    assert errors == [], errors


def test_the_estimate_is_asked_for_the_chosen_subunits_and_its_numbers_move(dashboard, live_page):
    """The load-bearing claim: A alone and A+B+C cannot show the same slab.

    The estimate block is the server's, so the panel's job is to ask the route for the same selection it will
    simulate. If the numbers do not move with the ticks, the run and its estimate describe two different runs -- which
    is exactly the bug this test exists to catch.
    """
    page, errors = live_page
    asked = []
    serve(page, asked)
    open_panel(page, live_page.base_url)
    page.locator('#new-mapping').select_option(MAPPING_FILE)

    expect(page.locator('.new-pdc-apolar')).to_have_text('75.3 nm²')
    assert asked and asked[-1] == 'A,B,C', asked

    # Chain A alone: the selection shrinks and the block must shrink with it.
    tick(page, 'A')
    expect(page.locator('.new-pdc-apolar')).to_have_text('38.0 nm²')
    assert asked[-1] == 'A', asked
    expect(page.locator('.new-pdc-subunits-note')).to_contain_text('1 of 3 subunits selected: A')

    # And back to all three: the first number returns, so the block tracks the ticks rather than a cached answer.
    tick(page, 'A', 'B', 'C')
    expect(page.locator('.new-pdc-apolar')).to_have_text('75.3 nm²')
    assert asked[-1] == 'A,B,C', asked
    assert {'A', 'A,B,C'} <= set(asked), asked
    assert errors == [], errors


def test_no_tick_blocks_the_launch_with_a_reason(dashboard, live_page):
    """An entry that declares chains and no tick is a run with no protein to build: the gate names it, not a queue."""
    page, errors = live_page
    serve(page)
    open_panel(page, live_page.base_url)

    tick(page)
    expect(page.locator('.new-pdc-subunits-note')).to_contain_text('choose at least one')
    expect(page.locator('#launch-blocker')).to_contain_text('Choose at least one subunit')
    expect(page.locator('#start-run')).to_be_disabled()
    assert errors == [], errors


def test_the_run_carries_the_subunit_selection_it_shows(dashboard, live_page):
    """The ticks are the run's protein preparation, so the selection travels as `protein_chains`."""
    page, errors = live_page
    posted = {}
    serve(page)
    page.route(re.compile(r'/api/readiness\?'),
               lambda route: route.fulfill(json={'ready': True, 'checks': [], 'blockers': []}))

    def queue(route):
        if route.request.method != 'POST':
            route.fallback()
            return
        posted.update(route.request.post_data_json or {})
        route.fulfill(status=201, json={'id': 'pdcqueued1', 'run_type': 'pdc'})

    page.route(re.compile(r'^http://127\.0\.0\.1:\d+/$'), queue)
    open_panel(page, live_page.base_url)

    # Chain A alone, then queued: the payload carries exactly that.
    tick(page, 'A')
    expect(page.locator('#start-run')).to_be_enabled()
    page.locator('#start-run').click()
    expect(page.locator('#notice')).to_contain_text('Run queued.', timeout=30000)
    assert posted['protein_chains'] == ['A'], posted

    # And all three is still stated explicitly, so a run records the chains it simulated. Queuing switches the tab
    # to the runs list, so the panel is opened again before the second queue.
    posted.clear()
    page.get_by_role('tab', name='New run', exact=True).click()
    tick(page, 'A', 'B', 'C')
    page.locator('#start-run').click()
    expect(page.locator('#notice')).to_contain_text('Run queued.', timeout=30000)
    assert posted['protein_chains'] == ['A', 'B', 'C'], posted
    assert errors == [], errors
