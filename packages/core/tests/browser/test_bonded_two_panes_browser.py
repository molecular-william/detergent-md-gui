"""The right comparison pane renders every control the workspace controller addresses.

The Bond Interactions panel is one Jinja macro rendered twice: the left pane keeps the bare ids the rest of the
browser tier already uses, and the right pane carries the same ids with a `-B` suffix. Nothing in the panel's JS
addresses those suffixed ids through a literal selector, so `test_dom_ids.py` cannot see them; this module is what
keeps them honest. Without it a changed macro could drop a control from the right pane and no test would notice until
a reader typed into it.
"""
from playwright.sync_api import expect

#: Every id the right pane must render. The left pane's ids are covered by the rest of the tier.
COLUMN_B_IDS = (
    '#bonded-column-B',
    '#bonded-minimize-B',
    '#bonded-model-badge-B',
    '#bonded-model-summary-B',
    '#bonded-molecule-select-B',
    '#bonded-parameterization-display-B',
    '#bonded-mapping-facts-B',
    '#bonded-shown-status-B',
    '#bonded-make-current-B',
    '#bonded-delete-parameterization-B',
    '#bonded-save-terms-inplace-B',
    '#bonded-save-terms-new-B',
    '#bonded-terms-status-B',
)


def test_the_second_pane_renders_every_control(live_page):
    """One page load: two panes, and the right one carries its whole control set exactly once."""
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/bond-interactions')
    page.wait_for_selector('#bonded-molecule-select', timeout=15000)
    expect(page.locator('.bonded-columns > .bonded-column')).to_have_count(2)
    for selector in COLUMN_B_IDS:
        expect(page.locator(selector)).to_have_count(1)
    assert errors == []


def test_the_merged_card_keeps_the_fit_target_and_the_torsion_explainer(live_page):
    """The fit card owns its molecule and mapping selects; the torsion explainer is an info control, not a fieldset."""
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/bond-interactions')
    page.wait_for_selector('#bonded-fit-molecule', timeout=15000)
    expect(page.locator('#bonded-fit-molecule')).to_have_count(1)
    expect(page.locator('#bonded-fit-mapping')).to_have_count(1)
    expect(page.locator('#bonded-torsion-info')).to_have_count(1)
    expect(page.locator('fieldset.bonded-torsion')).to_have_count(0)
    assert errors == []
