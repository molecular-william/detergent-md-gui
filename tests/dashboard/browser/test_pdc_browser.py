"""The protein-detergent complex tab exists as a panel before any of its pipeline does.

The tab is added early on purpose: it shows where the second workflow lives, and its own hint says that nothing
is launched from it yet. These tests pin that shape, so the pipeline tasks have somewhere to land and a reader is
never left guessing whether the panel is broken or simply unfinished.
"""
from playwright.sync_api import expect


def test_the_complex_tab_opens_an_empty_panel_that_says_so(dashboard, live_page):
    page, errors = live_page
    page.goto(live_page.base_url)

    tab = page.get_by_role('tab', name='Protein-Detergent Complex Simulations', exact=True)
    expect(tab).to_be_visible()
    tab.click()

    expect(page.locator('#pdc')).to_be_visible()
    for heading in ('Build a complex', 'System view', 'Status'):
        expect(page.locator('#pdc h3', has_text=heading)).to_be_visible()

    # The panel is honest about having no pipeline behind it yet.
    expect(page.locator('.pdc-setup .hint').first).to_contain_text('nothing is launched from here yet')

    # The viewer host is sized before anything renders into it: NGL sizes itself to its element, not to content,
    # and a zero-height host is how a working viewer looks like a broken one.
    box = page.locator('#pdc-viewer').bounding_box()
    assert box and box['height'] >= 360 and box['width'] >= 300, box
    assert errors == []
