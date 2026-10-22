"""T11: back-mapping is optional, and the review says what the run will and will not produce.

CG2AT2 becomes a toggle, on by default so nothing existing moves. The panel has to say the difference out loud:
switched on, the run ends atomistic; switched off, the back-map stage records `skipped` and the run stops
coarse-grained. A review that said the same thing either way would let a reader mistake a run without back-mapping
for one with it, so the two states are asserted to be different strings, and the toggle's value is asserted to
travel on the payload.
"""
import re

from playwright.sync_api import expect

from . import panels

CATALOG = {
    'templates': [{'id': 'DDM:DDM', 'name': 'DDM skeleton', 'molecule': 'DDM', 'residue': 'DDM',
                   'template': 'molecules/DDM/micelle_template.json', 'registered_type': 'registered-template',
                   'files_present': True, 'missing_files': [],
                   'limitations': ['skeleton placeholder template, not a fitted detergent model']}],
    'proteins': [{'id': 'molecules/1qj8/1qj8.pdb', 'name': '1qj8', 'path': 'molecules/1qj8/1qj8.pdb',
                  'source': 'packaged', 'half_thickness_nm': 1.35}],
    'defaults': {'aggregation_number': 150, 'assessment_ns': 100, 'extension_ns': 900, 'salt_molar': 0.15,
                 'box_margin_nm': 2.0, 'initial_z_nm': 6.0, 'contact_nm': 0.6,
                 'selection_threshold_fraction': 0.1, 'snapshot_interval_ns': 20.0, 'snapshot_cap': 20},
}


def serve(page):
    page.route(re.compile(r'/api/pdc/catalog'), lambda route: route.fulfill(json=CATALOG))
    page.route(re.compile(r'/api/pdc/models\?'),
               lambda route: route.fulfill(json={'molecule': 'DDM', 'models': []}))
    page.route(re.compile(r'/api/readiness\?'),
               lambda route: route.fulfill(json={'ready': True, 'checks': [], 'blockers': []}))
    page.route(re.compile(r'/encapsulation'),
               lambda route: route.fulfill(status=400, json={'error': 'sizing is not exercised here'}))


def open_panel(page, base_url):
    return panels.open_pdc_new_run(page, base_url, protein='molecules/1qj8/1qj8.pdb')


def test_the_toggle_is_on_by_default_and_the_review_names_the_atomistic_end(dashboard, live_page):
    """On by default: a run that never touches the toggle still produces the atomistic structure."""
    page, errors = live_page
    serve(page)
    open_panel(page, live_page.base_url)

    toggle = page.locator('[name=backmap]')
    expect(toggle).to_be_visible()
    assert toggle.is_checked(), 'back-mapping must be on by default so nothing existing moves'
    expect(page.locator('[data-new-summary=backmap]')).to_contain_text('CG2AT2 to atomistic')
    expect(page.locator('.new-pdc-backmap-step strong')).to_contain_text('back-map')
    expect(page.locator('.new-pdc-backmap-note')).to_contain_text('atomistic')
    assert errors == [], errors


def test_switching_it_off_says_the_run_stops_coarse_grained(dashboard, live_page):
    """The two states must not read alike: a reader cannot mistake one for the other."""
    page, errors = live_page
    serve(page)
    open_panel(page, live_page.base_url)

    summary = page.locator('[data-new-summary=backmap]')
    on_text = summary.inner_text()
    assert 'atomistic' in on_text, on_text

    page.locator('[name=backmap]').uncheck()
    off_text = summary.inner_text()
    assert 'coarse-grained' in off_text, off_text
    assert on_text != off_text
    expect(page.locator('.new-pdc-backmap-step strong')).to_have_text('6 · Extend (no back-map)')
    expect(page.locator('.new-pdc-backmap-step span')).to_contain_text('coarse-grained')
    expect(page.locator('.new-pdc-backmap-note')).to_contain_text('skipped')

    # And back on: the atomistic sentence returns, so the review tracks the toggle rather than a stale render.
    page.locator('[name=backmap]').check()
    expect(summary).to_contain_text('CG2AT2 to atomistic')
    assert errors == [], errors


def test_the_toggle_value_reaches_the_payload(dashboard, live_page):
    """On and off are both stated, so a run cannot be read as back-mapped when it is not."""
    page, errors = live_page
    posted = {}
    serve(page)

    def queue(route):
        if route.request.method != 'POST':
            route.fallback()
            return
        posted.update(route.request.post_data_json or {})
        route.fulfill(status=201, json={'id': 'pdcqueued1', 'run_type': 'pdc'})

    page.route(re.compile(r'^http://127\.0\.0\.1:\d+/$'), queue)
    open_panel(page, live_page.base_url)

    page.locator('[name=backmap]').uncheck()
    expect(page.locator('#start-run')).to_be_enabled()
    page.locator('#start-run').click()
    expect(page.locator('#notice')).to_contain_text('Run queued.', timeout=30000)
    assert posted['backmap'] is False, posted

    posted.clear()
    page.get_by_role('tab', name='New run', exact=True).click()
    page.locator('[name=backmap]').check()
    page.locator('#start-run').click()
    expect(page.locator('#notice')).to_contain_text('Run queued.', timeout=30000)
    assert posted['backmap'] is True, posted
    assert errors == [], errors
