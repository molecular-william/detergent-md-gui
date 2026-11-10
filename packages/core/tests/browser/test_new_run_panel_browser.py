"""The New run panel after the split: what it asks for, and what it no longer asks.

Two run types -- AA run and CG run -- replace the combined AA-CG type, the CG-only sugar type and the composition
type. The controls those types carried are out of the document, not hidden: a hidden control still has a value, and
the failures that made this change worth doing (a method the adapter never read, a profile that disagreed with the
one the queue stamped, a bonded choice that was always the run type's) were all silent.

The review is the panel's own statement of the run before it starts: molecule, run type, parameterization, AA
source, coordinates, preset, length and label -- the same eight facts for both run types.
"""
import re

from playwright.sync_api import expect

from tests.harness import browser


def open_panel(page, base_url):
    """The single-molecule New run panel: its own mount signal, not a fixed delay."""
    return browser.open_panel(page, base_url, '/detergent-validation/new-run', tab='New run',
                              ready=lambda page: expect(page.locator('#new')).to_have_attribute('aria-busy', 'false'))


def test_the_panel_offers_two_run_types_and_no_retired_control(dashboard, live_page):
    dashboard.coordinator.database().replace([])
    page, errors = live_page
    open_panel(page, live_page.base_url)

    expect(page.locator('#run-type')).to_have_value('cg')
    expect(page.locator('#run-type option')).to_have_count(2)
    # The controls that made the retired run types choices are out of the document entirely.
    for name in ('method', 'profile', 'bonded_state_id', 'bonded_intent', 'mapping_candidate',
                 'reference_run_id', 'composition_id', 'sugar_entry'):
        assert page.locator(f'[name={name}]').count() == 0, f'{name} is still offered on the New run panel'
    # The run-configuration row is Run type and Force field only.
    labels = page.evaluate("Array.from(document.querySelectorAll('#run-form .run-config-row > label'))"
                           ".map(label => label.firstChild.textContent.trim())")
    assert labels == ['Run type', 'Force field'], labels
    # The parameterization is the one CG model selector, and it carries no name: the payload is built from it.
    expect(page.locator('#run-parameterization')).to_be_visible()
    assert page.evaluate("document.querySelector('#run-parameterization').name") == ''
    expect(page.locator('#start-run')).to_have_text('Start CG run')
    assert errors == [], errors


def test_the_review_states_the_eight_facts_the_run_is_queued_from(dashboard, live_page):
    page, errors = live_page
    open_panel(page, live_page.base_url)

    rows = page.evaluate("Array.from(document.querySelectorAll('#run-input-summary dt')).map(dt => dt.textContent)")
    assert rows == ['Molecule', 'Run type', 'Parameterization', 'AA source', 'Coordinates', 'Preset', 'Length',
                    'Label'], rows
    # Nothing in the review is a control: it reads the form and states what the run will consume.
    assert page.locator('#run-input-summary select, #run-input-summary input').count() == 0
    expect(page.locator('#run-type-summary')).to_have_text('CG run')
    expect(page.locator('#run-length-summary')).to_contain_text('ns total')
    assert errors == [], errors


def test_a_cg_payload_carries_no_method_profile_or_bonded_choice(dashboard, live_page):
    """The keys the panel stopped sending, read off the request it actually makes.

    `profile` was a duration preset wearing a pipeline name and the method was never read by the CG adapter; both are
    out of the form, so neither can travel by accident. The run type's profile is stamped by the queue route in their
    place, and the model is one nested `parameterization` object.
    """
    page, errors = live_page
    posted = {}
    page.route(re.compile(r'/api/readiness\?'),
               lambda route: route.fulfill(json={'ready': True, 'checks': [], 'blockers': []}))
    page.route(re.compile(r'/api/mappings\?view=summary&molecule_id=.*'), lambda route: route.fulfill(
        json={'candidates': []}))
    page.route(re.compile(r'/api/mappings/reference/.*'), lambda route: route.fulfill(
        status=404, json={'error': 'no published entry'}))
    page.route(re.compile(r'/api/defaults\?.*'), lambda route: route.fulfill(
        json={'values': {'cg_equil_ps': 10, 'cg_production_ps': 10000, 'temperature_k': 300},
              'sources': {'stub': 'stub'}, 'profile': 'stub', 'force_fields': []}))
    page.route(re.compile(r'/api/setting-presets\?.*'), lambda route: route.fulfill(
        json={'presets': [], 'default': None}))

    def queue(route):
        if route.request.method != 'POST':
            route.fallback()
            return
        posted.update(route.request.post_data_json or {})
        route.fulfill(status=201, json={'id': 'cgqueued0001', 'run_type': 'cg'})

    page.route(re.compile(r'^http://127\.0\.0\.1:\d+/$'), queue)
    open_panel(page, live_page.base_url)
    page.locator('[name=molecule_id]').select_option('DDM')
    expect(page.locator('#start-run')).to_be_enabled()
    page.locator('#start-run').click()
    expect(page.locator('#notice')).to_contain_text('Run queued.')

    assert posted['run_type'] == 'cg', posted
    for key in ('profile', 'method', 'bonded_state_id', 'bonded_intent', 'reference_run_id'):
        assert key not in posted, f'{key} is still sent for a CG run: {posted}'
    assert posted['parameterization']['kind'] == 'revision'
    assert 'starting_coordinates' in posted['parameterization']
    assert errors == [], errors


def test_no_run_type_offers_a_profile_or_method_control(dashboard, live_page):
    """Every run type, not just the one the panel opens on: the answer is the route's now, so the form asks nothing."""
    page, errors = live_page
    open_panel(page, live_page.base_url)

    for run_type in ('cg', 'aa_only'):
        page.locator('#run-type').select_option(run_type)
        assert page.locator('[name=profile]').count() == 0, f'{run_type} still offers a profile control'
        assert page.locator('[name=method]').count() == 0, f'{run_type} still offers a method control'
        expect(page.locator('#start-run')).to_have_text(
            'Start AA run' if run_type == 'aa_only' else 'Start CG run')
    assert errors == [], errors
