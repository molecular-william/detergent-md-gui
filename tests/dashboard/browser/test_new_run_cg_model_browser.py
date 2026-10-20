"""`02 · CG MODEL` on the New Run panel: the parameterization this run will consume, before it starts.

D5 of `docs/design/2026-10-16-parameterization-and-new-run.md`: a run consumes a *model*, and the panel states
which one -- the mapping's current revision, its engine, its term count, its torsion model and the AA reference it
was fitted against -- or, when the model carries none, that stage 3 fits it and records that it did. The card is
read-only and cannot hold Start disabled: an absent parameterization is a state, not a blocker.

The two states arrive from `GET /api/readiness`'s `parameterization` key, so they are stubbed here with that
route's own shape (`dashboard/execution/adapters/cg.py:_parameterization_state`) rather than derived: what this file
judges is what the panel does with the answer, and a real record would make the test depend on the fitting pipeline
having run. The mapping list is stubbed for the same reason -- a fixture workspace holds no saved candidate -- and
because the test needs two mappings to watch the card follow a change.
"""
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect

#: Two saved candidates, in the shape `/api/mappings?view=summary` answers with. The files are what the picker's
#: option values carry, and therefore what the readiness answer is keyed by here.
#: `can_reuse` is not decoration: the picker offers only a mapping a run can reuse, which is the verdict
#: `models/molecules/draft.py` refuses on. A stub without it would list nothing and this file's own precondition --
#: two mappings on offer -- would wait forever.
CANDIDATES = [
    {'name': 'DDM · ring mapping', 'file': 'ddm-ring.json', 'validation': {'issues': [], 'can_reuse': True}},
    {'name': 'DDM · tail mapping', 'file': 'ddm-tail.json', 'validation': {'issues': [], 'can_reuse': True}},
]

#: A model with a current revision, with every field the card is asked to state. `engine_label` is the label
#: `models/bonded/parameterization.py:ENGINE_LABELS` publishes, not one this test invents.
PARAMETERIZED = {
    'parameterized': True,
    'revision': 3,
    'engine': 'fast-forward',
    'engine_label': 'Fast-Forward fit (ff_inter)',
    'terms': 34,
    'torsion_model': 'circular-harmonic',
    'checks': ['dihedral-fit', 'bonded-cross-check'],
    'aa_reference': {'run_id': 'a54ac8f64710', 'reference_sha256': 'ab' * 32, 'molecule_identity': 'DDM',
                     'temperature_k': 300.0, 'production_ns': 10.0},
    'revision_sha256': 'cd' * 32,
    'statement': 'this model is parameterized -- fitted with Fast-Forward fit (ff_inter) against a54ac8f64710, '
                 'revision 3, hash cdcbcbcbcbcb, torsion model circular-harmonic; the run uses it and does not '
                 're-fit',
}

#: The other honest state: no revision, and the sentence the run type keeps beside the code that fits in stage 3.
#: `terms` is `None` and not `0` -- a count of zero would read as a parameterization of nothing.
UNPARAMETERIZED = {
    'parameterized': False,
    'revision': None,
    'engine': None,
    'engine_label': None,
    'terms': None,
    'torsion_model': None,
    'checks': [],
    'aa_reference': None,
    'revision_sha256': None,
    'statement': 'this model carries no parameterization -- the run will fit it in stage 3 and record that it did',
}

#: The other mapping's revision, so a change of picker is visible as a change of number rather than as a re-render
#: the assertions cannot tell from the first answer.
PARAMETERIZED_TAIL = {**PARAMETERIZED, 'revision': 7, 'terms': 12, 'torsion_model': 'legacy',
                      'engine': 'bartender', 'engine_label': 'BARTENDER fit (-refit -owntraj)'}


def stub(page, states, failing=()):
    """Serve the mapping list and answer readiness per mapping, recording every question asked.

    `page.route` also sees the document request, so both patterns are anchored on the endpoint's own path -- a stub
    on the page URL would swallow the page and leave every locator waiting on its own JSON.

    `failing` names mappings whose readiness the server cannot answer: the panel's own error branch, and the state
    in which the card has no answer for the mapping on the picker.
    """
    asked = []

    def readiness(route):
        query = parse_qs(urlsplit(route.request.url).query)
        mapping = (query.get('mapping_candidate') or [''])[0]
        asked.append(mapping)
        if mapping in failing:
            route.fulfill(status=500, json={'error': 'readiness could not be computed for this mapping'})
            return
        route.fulfill(json={'ready': True, 'checks': [], 'blockers': [],
                            'parameterization': states.get(mapping, UNPARAMETERIZED)})

    page.route('**/api/readiness?*', readiness)
    page.route('**/api/mappings?view=summary*',
               lambda route: route.fulfill(json={'candidates': CANDIDATES}))
    return asked


def open_panel(page, live_page):
    """The New Run panel of the validation workspace, mounted and its mapping list filled."""
    page.goto(f'{live_page.base_url}/detergent-validation/new-run')
    # Two mappings on offer is this file's precondition, and the molecule has to be a real one before readiness is
    # asked at all (`checkReadiness` returns early with no molecule record).
    page.wait_for_function(
        "() => document.querySelectorAll('[name=mapping_candidate] option').length > 2", timeout=30000)
    page.wait_for_function(
        "() => document.querySelector('[name=molecule_id]').value === 'DDM'", timeout=30000)


def card(page):
    return page.locator('.cg-model')


def test_the_card_states_the_revision_engine_terms_torsion_and_aa_reference(dashboard, live_page):
    """A parameterized model: the run's terms are named, with the link into the panel that produced them."""
    page, errors = live_page
    stub(page, {'ddm-ring.json': PARAMETERIZED})
    open_panel(page, live_page)

    page.locator('[name=mapping_candidate]').select_option('ddm-ring.json')

    expect(card(page)).to_be_visible()
    expect(card(page)).to_contain_text('02 · CG MODEL')
    expect(card(page).locator('[data-cg-model=name]')).to_contain_text('DDM · ring mapping')
    expect(card(page).locator('[data-cg-model=parameterization]')).to_have_text('revision 3 · 34 bonded terms')
    expect(card(page).locator('[data-cg-model=engine]')).to_have_text('Fast-Forward fit (ff_inter)')
    expect(card(page).locator('[data-cg-model=torsion]')).to_have_text('circular-harmonic')
    expect(card(page).locator('[data-cg-model=reference]')).to_have_text('a54ac8f64710 · 300 K · 10 ns')
    # The review's own row reads the same answer, so the panel cannot say two things about one model.
    expect(page.locator('#run-bonded-summary')).to_have_text('Used as-is · this run does not re-fit')
    # The door into the panel, addressed by the panel's own route and its mapping by name. The route is the
    # sub-tab's href, which `sections.py` writes -- not a URL this module keeps for itself.
    expect(card(page).locator('[data-cg-model=open]')).to_have_attribute(
        'href', '/detergent-validation/bond-interactions?mapping_candidate=ddm-ring.json')
    expect(card(page).locator('[data-cg-model=open]')).to_have_text('Open in CG Bond Interactions')
    assert errors == []


def test_a_model_without_a_parameterization_says_stage_three_fits_it_and_start_is_not_blocked(dashboard, live_page):
    """The fallback: the run still starts, and the card says what it will do rather than what it lacks."""
    page, errors = live_page
    stub(page, {'ddm-ring.json': UNPARAMETERIZED})
    open_panel(page, live_page)

    page.locator('[name=mapping_candidate]').select_option('ddm-ring.json')

    expect(card(page)).to_be_visible()
    expect(card(page).locator('[data-cg-model=statement]')).to_contain_text(
        'this model carries no parameterization')
    expect(card(page).locator('[data-cg-model=statement]')).to_contain_text(
        'the run will fit it in stage 3 and record that it did')
    # No provenance is claimed when there is none: the rows are the parameterized state's, and they are gone.
    expect(card(page).locator('[data-cg-model=terms]')).to_be_hidden()
    expect(card(page).locator('[data-cg-model=parameterization]')).to_be_hidden()
    expect(page.locator('#run-bonded-summary')).to_have_text('Stage 3 fits it during the run')
    # The one assertion this state exists for: an absent parameterization is not a blocker.
    expect(page.locator('#start-run')).to_be_enabled()
    expect(card(page).locator('[data-cg-model=open]')).to_have_text(
        'Parameterize first in CG Bond Interactions…')
    assert errors == []


def test_changing_the_mapping_asks_readiness_again_and_the_card_follows_the_answer(dashboard, live_page):
    """The card is the answer's, not a copy taken once: a new mapping is a new question and a new model."""
    page, errors = live_page
    asked = stub(page, {'ddm-ring.json': PARAMETERIZED, 'ddm-tail.json': PARAMETERIZED_TAIL})
    open_panel(page, live_page)

    page.locator('[name=mapping_candidate]').select_option('ddm-ring.json')
    expect(card(page).locator('[data-cg-model=parameterization]')).to_have_text('revision 3 · 34 bonded terms')

    page.locator('[name=mapping_candidate]').select_option('ddm-tail.json')
    expect(card(page).locator('[data-cg-model=name]')).to_contain_text('DDM · tail mapping')
    expect(card(page).locator('[data-cg-model=parameterization]')).to_have_text('revision 7 · 12 bonded terms')
    expect(card(page).locator('[data-cg-model=engine]')).to_have_text('BARTENDER fit (-refit -owntraj)')
    expect(card(page).locator('[data-cg-model=torsion]')).to_have_text('legacy')
    expect(card(page).locator('[data-cg-model=open]')).to_have_attribute(
        'href', '/detergent-validation/bond-interactions?mapping_candidate=ddm-tail.json')

    # Both mappings were asked about, the second after the first: the card follows the answer to the question the
    # picker is asking. What this ordering does not prove is that the card was *empty* while the second answer was
    # in flight -- that is its own test below, where the second answer never arrives.
    assert 'ddm-ring.json' in asked and 'ddm-tail.json' in asked, asked
    assert asked.index('ddm-ring.json') < asked.index('ddm-tail.json'), asked
    assert errors == []


def test_no_answer_for_the_new_mapping_leaves_no_previous_revision_beside_its_name(dashboard, live_page):
    """A change of picker empties the card before the question is asked, and an error leaves it empty.

    The failure this guards is the one a card keyed by nothing would make: the new mapping's name over the old
    mapping's revision, engine and torsion model, printed for as long as the readiness answer takes -- or forever,
    when it never arrives. `#run-bonded-summary` reads the same answer, so it must not claim the old model either.
    """
    page, errors = live_page
    stub(page, {'ddm-ring.json': PARAMETERIZED}, failing={'ddm-tail.json'})
    open_panel(page, live_page)

    page.locator('[name=mapping_candidate]').select_option('ddm-ring.json')
    expect(card(page).locator('[data-cg-model=parameterization]')).to_have_text('revision 3 · 34 bonded terms')
    expect(page.locator('#run-bonded-summary')).to_have_text('Used as-is · this run does not re-fit')

    # The second mapping's readiness fails. There is no answer for it, so there is nothing to print beside its name.
    page.locator('[name=mapping_candidate]').select_option('ddm-tail.json')
    expect(card(page)).to_be_hidden()
    # Hidden is not enough: the rows are read out of the DOM by anything that asks, so nothing of revision 3 may
    # survive the change of mapping.
    assert 'revision 3' not in (card(page).text_content() or '')
    assert 'DDM · ring mapping' not in (card(page).text_content() or '')
    expect(page.locator('#run-bonded-summary')).not_to_have_text('Used as-is · this run does not re-fit')

    # A run-type toggle re-renders from what the panel holds: with no answer for this mapping, that is nothing.
    page.locator('#run-type').select_option('aa_only')
    page.locator('#run-type').select_option('aa_cg')
    expect(card(page)).to_be_hidden()
    assert 'revision 3' not in (card(page).text_content() or '')
    expect(page.locator('#run-bonded-summary')).not_to_have_text('Used as-is · this run does not re-fit')
    assert errors == []


def test_the_link_opens_cg_bond_interactions_on_the_mapping_the_card_names(dashboard, live_page):
    """The door preselects the mapping it describes -- the second candidate, not the first in the panel's list.

    The two panels are one document (`tabs.js` switches them in place), so the address alone is not the door: the
    picker belongs to the panel and is filled by `mappings.js` after the switch. Following the link must leave the
    picker on the mapping the card names, and a cold load of the same address must land there too.
    """
    page, errors = live_page
    stub(page, {'ddm-ring.json': PARAMETERIZED, 'ddm-tail.json': PARAMETERIZED_TAIL})
    open_panel(page, live_page)

    page.locator('[name=mapping_candidate]').select_option('ddm-tail.json')
    door = card(page).locator('[data-cg-model=open]')
    expect(door).to_have_attribute(
        'href', '/detergent-validation/bond-interactions?mapping_candidate=ddm-tail.json')

    door.click()
    expect(page.locator('#bonded')).to_be_visible()
    expect(page.locator('.bonded-mapping-select')).to_have_value('ddm-tail.json')
    assert page.url.endswith('/detergent-validation/bond-interactions?mapping_candidate=ddm-tail.json'), page.url

    # A copied address or a link opened in a new tab is the same door.
    page.goto(f'{live_page.base_url}/detergent-validation/bond-interactions?mapping_candidate=ddm-tail.json')
    expect(page.locator('.bonded-mapping-select')).to_have_value('ddm-tail.json', timeout=30000)
    assert errors == []


def test_the_card_belongs_to_the_cg_branch_and_carries_nothing_without_a_mapping(dashboard, live_page):
    """An AA-only run has no model to describe, and an empty picker has no parameterization to state."""
    page, errors = live_page
    stub(page, {'ddm-ring.json': PARAMETERIZED})
    open_panel(page, live_page)

    # Nothing chosen yet: the card exists (it is built under the picker) and says nothing.
    expect(card(page)).to_be_hidden()

    page.locator('[name=mapping_candidate]').select_option('ddm-ring.json')
    expect(card(page)).to_be_visible()

    page.locator('#run-type').select_option('aa_only')
    expect(card(page)).to_be_hidden()
    assert errors == []


def test_the_card_fits_a_narrow_window_without_sideways_scroll(dashboard, live_page):
    """It sits in a card inside a card on a two-column form, so it is measured at the width that has one column.

    The stylesheet is not this module's to change, and a block added to a card that already holds a picker, a hint
    and a grid is exactly where a horizontal scrollbar appears unnoticed -- `test_lazy_loading.py` only measures the
    panels it names.
    """
    page, errors = live_page
    stub(page, {'ddm-ring.json': PARAMETERIZED})
    open_panel(page, live_page)
    page.locator('[name=mapping_candidate]').select_option('ddm-ring.json')
    expect(card(page)).to_be_visible()

    page.set_viewport_size({'width': 390, 'height': 844})
    page.wait_for_timeout(200)
    expect(card(page)).to_be_visible()
    # The card's own right edge, against the viewport: a text node that will not break is the usual cause, and
    # `overflow-wrap:anywhere` on `#run-form .hint` is the rule that has to reach these lines.
    box = card(page).bounding_box()
    assert box['x'] >= 0 and box['x'] + box['width'] <= 390, box
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert errors == []
