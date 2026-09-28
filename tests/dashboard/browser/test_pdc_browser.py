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


def test_the_viewer_says_when_there_is_no_system_and_renders_one_when_there_is(dashboard, live_page):
    """Both halves of the viewer's contract, against the real route and then against a stubbed built system.

    The failure half is the real thing: asking for a run that has no built system must explain that rather than draw
    an empty box. The success half is stubbed, because a built system needs a stage that Phase B's wiring task has not
    run yet -- the point here is that the viewer renders what the route returns.
    """
    page, errors = live_page
    page.goto(f'{live_page.base_url}/#pdc')

    # A run with no built system: an honest line rather than a blank canvas.
    page.evaluate("window.pdcSetRun('000000000000')")
    expect(page.locator('#pdc-view-basis')).to_contain_text('No built system to show yet')

    # And a system, stubbed at the route, rendering into the stage.
    stub = ('HETATM    1  BB  PRO A   1      10.000  20.000  30.000  1.00  0.00           C\n'
            'HETATM    2  C1  DET A   1      40.000  50.000  60.000  1.00  0.00           C\n'
            'END\n')
    page.route('**/api/pdc/*/system.pdb', lambda route: route.fulfill(status=200, content_type='text/plain', body=stub))
    page.evaluate("window.pdcSetRun('abcdef123456')")
    page.wait_for_function("() => document.querySelector('#pdc-viewer').pdcStage?.compList.length > 0", timeout=30000)
    expect(page.locator('#pdc-view-basis')).to_contain_text('Showing 2 beads')
    assert errors == []
