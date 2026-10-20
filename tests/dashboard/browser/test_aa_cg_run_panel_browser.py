"""The AA-CG run panel after D1 and D2: what it no longer asks, and what it says instead.

A panel that renders nothing looks identical to one whose script never parsed, so the assertions here are on the
arrangement and on the words: which controls the AA-CG fieldset carries, which of them left the document entirely,
which one is left for the run type that still owns it, and the sentence that says what an AA-CG run does with no
help from the panel.

The reasoning the two decisions carry, which is what makes the shape below the right one and not merely a shape:

* D1 -- fitting is a property of the run type. `aa_cg` always fits its own bonded parameters from the AA reference,
  and a run type that consumes a pre-parameterized molecule never fits. So there is no per-run bonded state to
  select and no per-run bonded workflow to choose, and both controls are gone rather than hidden: they named run
  shapes the store has never run (0 of 8 jobs carried either).
* D2 -- the profile was a duration preset wearing a pipeline name, and its only non-duration effect was whether a
  mapping is staged at all. The run route stamps `'draft-smoke-reference'` for the run type and the manifest records
  it. The *control* stays in the document -- the AA-only panel's own handling of it is not this slice's business --
  so for an AA-CG run it is hidden and disabled, which is what "not offered" means for an element that has to keep
  serving another run type.
"""
from playwright.sync_api import expect


def open_panel(page, base_url):
    """The single-molecule New run panel, waiting for its own mount rather than for a fixed delay."""
    page.goto(f'{base_url}/detergent-validation/new-run')
    page.get_by_role('tab', name='New run', exact=True).click()
    expect(page.locator('#new')).to_have_attribute('aria-busy', 'false')


def test_the_aa_cg_panel_fits_for_itself_and_offers_no_bonded_choice(dashboard, live_page):
    dashboard.coordinator.database().replace([])
    page, errors = live_page
    open_panel(page, live_page.base_url)

    # The run type this panel opens on: every assertion below is about the AA-CG fieldset.
    expect(page.locator('#run-type')).to_have_value('aa_cg')

    # The two controls that made fitting a per-run choice are out of the document, not merely hidden: no element
    # carries either name anywhere on the page, and neither label survives in the panel's own text.
    for name in ('bonded_state_id', 'bonded_intent'):
        assert page.locator(f'[name={name}]').count() == 0, f'{name} is still offered on the AA-CG panel'
    panel_text = page.locator('#new').inner_text()
    for label in ('Bonded parameters', 'Bonded workflow'):
        assert label not in panel_text, f'{label} is still offered on the AA-CG panel'

    # The profile is the run type's own for an AA-CG run: the element is still here because the AA-only panel keeps
    # it, and this run type does not offer it -- hidden, and disabled so no hidden value can travel by accident.
    profile = page.locator('[name=profile]')
    expect(profile).to_have_count(1)
    expect(profile).to_be_hidden()
    expect(profile).to_be_disabled()

    # What stays: the mapping, which is what a run is queued from and what its bonded parameters come from, and the
    # AA reference source, which is what the fit is made against.
    expect(page.locator('#run-mapping')).to_be_visible()
    expect(page.locator('#reference-run')).to_be_visible()

    # And the panel says in words what the run does with the model's parameterization -- the stage is named, the
    # revision is the one CG Bond Interactions makes current, and the one switch that remains belongs to the mapping
    # rather than to the run. The two branches are the model card's own two sentences.
    facts = page.locator('.cg-run-facts')
    expect(facts).to_be_visible()
    expect(facts).to_contain_text('does not re-fit it')
    expect(facts).to_contain_text('fits it during the run')
    expect(facts).to_contain_text('CG parameterization')
    expect(facts).to_contain_text('CG Bond Interactions')
    assert errors == [], errors


def test_the_aa_cg_payload_carries_neither_a_profile_nor_a_bonded_choice(dashboard, live_page):
    """The keys the panel stopped sending, read off the request it actually makes.

    `profile` (D2), `bonded_state_id` and `bonded_intent` (D1) are gone from what an AA-CG run posts. The profile is
    dropped by name rather than never sent, because the one `profile` control this form carries still serves the
    AA-only and composition panels -- so this assertion is what keeps a hidden control's value from travelling, and
    the route stamps the run type's own profile in its place.
    """
    import re

    page, errors = live_page
    posted = {}
    page.route(re.compile(r'/api/readiness\?'),
               lambda route: route.fulfill(json={'ready': True, 'checks': [], 'blockers': []}))

    def queue(route):
        if route.request.method != 'POST':
            route.fallback()
            return
        posted.update(route.request.post_data_json or {})
        route.fulfill(status=201, json={'id': 'aaqueued0001', 'run_type': 'aa_cg'})

    page.route(re.compile(r'^http://127\.0\.0\.1:\d+/$'), queue)
    open_panel(page, live_page.base_url)
    page.locator('#molecule-directory').select_option('DDM')
    expect(page.locator('#start-run')).to_be_enabled()
    page.locator('#start-run').click()
    expect(page.locator('#notice')).to_contain_text('Run queued.')

    assert posted['run_type'] == 'aa_cg', posted
    for key in ('profile', 'bonded_state_id', 'bonded_intent'):
        assert key not in posted, f'{key} is still sent for an AA-CG run: {posted}'
    # And the run still hands over what it does own: the mapping it is queued from and the CG settings it will use.
    assert 'mapping_candidate' in posted and 'cg_production_ps' in posted, posted
    assert errors == [], errors


def test_the_profile_control_survives_for_the_run_types_that_still_use_it(dashboard, live_page):
    """The removal is that run type's, not the panel's: the element and its options are what they were."""
    page, errors = live_page
    open_panel(page, live_page.base_url)
    options = page.evaluate("Array.from(document.querySelectorAll('[name=profile] option')).map(o => o.value)")
    assert options == ['standard', 'draft-smoke', 'draft-smoke-reference'], options

    # An AA-only run hides the whole CG block, and the profile with it -- exactly the behaviour it had before this
    # slice, which is why the element is kept rather than deleted.
    page.locator('#run-type').select_option('aa_only')
    expect(page.locator('#cg-inputs')).to_be_hidden()
    expect(page.locator('[name=profile]')).to_be_hidden()

    # A composition screening run still chooses its own profile.
    page.locator('#run-type').select_option('cg_composition')
    expect(page.locator('[name=profile]')).to_be_visible()
    expect(page.locator('[name=profile]')).to_be_enabled()
    assert errors == [], errors
