"""The protein-detergent complex tab exists as a panel with a pipeline behind it.

The tab was added early, when nothing was launched from it, and its first test pinned that: the hint had to say
"nothing is launched from here yet". That premise died in `34af539`, which gave the panel a queue button and a
mapping picker -- and the assertion stayed behind, red, until it was flipped here. What the panel owes a reader
has not changed and is still what this pins: it must state the limitation of the template it is holding rather
than offering a reassurance or saying nothing, and its viewer host must be sized before anything renders.
"""
from playwright.sync_api import expect


def test_the_complex_tab_opens_a_panel_that_says_what_it_would_build(dashboard, live_page):
    page, errors = live_page
    # The tab lives in the protein-detergent workspace. Before the split one page held every panel, so opening the
    # root and clicking the tab reached it; now the root is the detergent-validation workspace and the panel is
    # rendered hidden there, which is why this navigates to the panel's own URL.
    page.goto(live_page.base_url + '/protein-detergent/complexes')

    tab = page.get_by_role('tab', name='Complexes', exact=True)
    expect(tab).to_be_visible()
    tab.click()

    expect(page.locator('#pdc')).to_be_visible()
    for heading in ('Build a complex', 'System view', 'Status'):
        expect(page.locator('#pdc h3', has_text=heading)).to_be_visible()

    # The panel repeats the catalogue's own limitation for the template it holds -- so a reader cannot mistake
    # the smoke template for a fitted detergent model, and the sentence is not one this panel invents.
    catalogue = page.evaluate("() => fetch('/api/pdc/catalog').then(response => response.json())")
    chosen = page.evaluate("() => document.querySelector('#pdc-template').value")
    entry = next(item for item in catalogue['templates'] if item['id'] == chosen)
    expect(page.locator('#pdc-template-limitation')).to_have_text(' · '.join(entry['limitations']))
    assert entry['limitations'], 'the fixture template carries no limitation, so nothing is being pinned'

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
