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


def test_the_setup_lists_what_can_be_built_and_what_it_is_worth(dashboard, live_page):
    """The selectors come from the catalogue, and the panel repeats the catalogue's own judgement of the template.

    The shipped DDM template is a skeleton, and the option text says what kind of entry it is rather than
    presenting it as a ready detergent.
    """
    page, errors = live_page
    page.goto(f'{live_page.base_url}/#pdc')

    expect(page.locator('#pdc-template option').first).to_contain_text('registered-template')
    expect(page.locator('#pdc-template')).to_have_value('DDM:DDM')
    expect(page.locator('#pdc-template-limitation')).not_to_have_text('')
    # An empty micelle is in scope, so the protein list offers the absence of a protein.
    expect(page.locator('#pdc-protein option').first).to_contain_text('No protein')
    assert errors == []
