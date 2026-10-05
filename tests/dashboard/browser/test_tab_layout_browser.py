"""One content measure and one navigation rail, at the widths where each decision matters.

Two things a reader noticed: Runs looked wider than the other panels, and the tab row had run out of room. The
first was real on a wide window — a `:has()` rule widened the page to 1800 px for Runs alone while every other
tab stayed at 1440 — and the second was real at any width, because seven buttons needed 1674 px inside a 1217 px
bar. These tests hold the replacement in place: one measure, no dead space beside a workspace, a rail that
compacts and returns to a row on a small window, and the arrow keys following the orientation it is told.
"""
from playwright.sync_api import expect

WIDE = {'width': 1440, 'height': 900}
MEDIUM = {'width': 1000, 'height': 900}
NARROW = {'width': 820, 'height': 900}

PANELS = ('runs', 'new', 'mappings', 'bonded', 'validation', 'compositions', 'pdc')

BOXES = ("() => [...document.querySelectorAll('nav[role=tablist] button')].map(b => {"
         " const r = b.getBoundingClientRect(); return [Math.round(r.top), Math.round(r.left)]; })")


def visible_panel(page):
    return page.evaluate("() => [...document.querySelectorAll('.panel')].find(p => !p.hidden).id")


def width(page, selector):
    return page.evaluate("sel => { const el = document.querySelector(sel); return el ? Math.round(el.getBoundingClientRect().width) : null; }", selector)


def test_every_panel_is_the_same_width_and_has_no_dead_space_beside_it(dashboard, live_page):
    """The measure is the page's, and a workspace fills its columns of it rather than sitting in a sub-column."""
    page, errors = live_page
    page.set_viewport_size(WIDE)
    page.goto(live_page.base_url)

    measures = {}
    for panel in PANELS:
        page.click(f'#tab-{panel}')
        page.wait_for_selector(f'#{panel}:not([hidden])')
        measures[panel] = width(page, f'#{panel}')
    assert len(set(measures.values())) == 1, f'the panels are the same width: {measures}'

    # Each workspace places its panels on the measure by span, and the widths follow the spans: this is what
    # "no dead space" means once a workspace wraps a third card onto its own row — summing all the children
    # weights the wrapped row twice, so the check is per span rather than per total.
    def track_width(selector):
        return page.evaluate("""sel => { const box = document.querySelector(sel); const cs = getComputedStyle(box);
          const gap = parseFloat(cs.columnGap) || 0;
          const width = box.getBoundingClientRect().width;
          return {gap: gap, track: (width - gap * 11) / 12, width: width,
                  kids: [...box.children].map(el => el.getBoundingClientRect().width)}; }""", selector)

    cases = (('new', '.new-run-layout', (6, 6)),
             ('mappings', '.mapping-editor-layout', (7, 5)),
             ('compositions', '.composition-workspace', (3, 9)),
             ('pdc', '.pdc-workspace', (3, 9, 12)),
             ('bonded', '.bonded-columns', (6, 6)))
    for panel, workspace, spans in cases:
        page.click(f'#tab-{panel}')
        page.wait_for_selector(f'#{panel}:not([hidden])')
        measured = track_width(workspace)
        assert len(measured['kids']) == len(spans), f'{panel}: {len(measured["kids"])} panels for {len(spans)} spans'
        for span, measured_width in zip(spans, measured['kids']):
            expected = span * measured['track'] + (span - 1) * measured['gap']
            assert abs(measured_width - expected) <= 2, \
                f'{panel}: a span-{span} panel is {measured_width:.0f} px where the measure says {expected:.0f}'
    assert errors == []


def test_the_tabs_are_a_rail_on_a_wide_window_and_say_so(dashboard, live_page):
    page, errors = live_page
    page.set_viewport_size(WIDE)
    page.goto(live_page.base_url)

    expect(page.locator('nav[role=tablist]')).to_have_attribute('aria-orientation', 'vertical')
    boxes = page.evaluate(BOXES)
    assert len({top for top, _ in boxes}) == len(boxes), 'each tab on its own row'
    assert len({left for _, left in boxes}) == 1, 'one common left edge'
    assert width(page, 'nav[role=tablist]') == 220

    # The rail is on the right, so the content keeps the left edge of the measure. Measured rather than inferred
    # from the stylesheet: the two are adjacent grid columns, so their edges meet.
    rail = page.locator('nav[role=tablist]').bounding_box()
    content = page.locator('.app-content').bounding_box()
    assert rail['x'] >= content['x'] + content['width'] - 1, \
        f"the rail is at {rail['x']:.0f} where the content ends at {content['x'] + content['width']:.0f}"

    # The visible label is short; the accessible name is the one the workflow is known by, so a reader who knows
    # the old name still finds it and no existing lookup by role and name breaks.
    assert page.evaluate("() => document.querySelector('#tab-new .tab-text').textContent") == 'Simulate'
    expect(page.get_by_role('tab', name='Single Molecule Simulations', exact=True)).to_be_visible()
    expect(page.get_by_role('tab', name='Protein-Detergent Complex Simulations', exact=True)).to_be_visible()
    assert page.evaluate("() => document.querySelectorAll('nav[role=tablist] .tab-group').length") == 2
    assert errors == []


def test_the_arrow_keys_move_between_tabs_in_a_rail(dashboard, live_page):
    page, errors = live_page
    page.set_viewport_size(WIDE)
    page.goto(live_page.base_url)

    page.click('#tab-runs')
    expect(page.locator('#tab-runs')).to_have_attribute('aria-selected', 'true')
    page.keyboard.press('ArrowDown')
    expect(page.locator('#tab-new')).to_have_attribute('aria-selected', 'true')
    page.keyboard.press('ArrowUp')
    expect(page.locator('#tab-runs')).to_have_attribute('aria-selected', 'true')
    assert errors == []


def test_a_medium_window_keeps_the_icons_so_the_table_keeps_its_room(dashboard, live_page):
    page, errors = live_page
    page.set_viewport_size(MEDIUM)
    page.goto(live_page.base_url)

    assert not page.locator('#tab-new .tab-text').is_visible(), 'the labels fold away before the content does'
    expect(page.get_by_role('tab', name='Single Molecule Simulations', exact=True)).to_be_visible()
    assert width(page, 'nav[role=tablist]') == 64
    rail = page.locator('nav[role=tablist]').bounding_box()
    content = page.locator('.app-content').bounding_box()
    assert rail['x'] >= content['x'] + content['width'] - 1, 'the icons stay on the right on the way down'
    assert errors == []


def test_a_narrow_window_gets_the_row_back_and_is_told_which_it_is(dashboard, live_page):
    """A rail costs content width a small window does not have, so below 900 px it is the row again."""
    page, errors = live_page
    page.set_viewport_size(NARROW)
    page.goto(live_page.base_url)

    expect(page.locator('nav[role=tablist]')).to_have_attribute('aria-orientation', 'horizontal')
    boxes = page.evaluate(BOXES)
    assert len({top for top, _ in boxes}) == 1, 'one row'
    # The rail is on the right at the widths above this one; here it is one column again and the row goes back
    # above the content, which is the only ordering a one-column layout has.
    rail = page.locator('nav[role=tablist]').bounding_box()
    content = page.locator('.app-content').bounding_box()
    assert rail['y'] + rail['height'] <= content['y'] + 1, 'the row sits above the content, not beside it'
    expect(page.locator('#tab-new .tab-text')).to_be_visible(), 'the labels come back with the room'
    assert visible_panel(page) == 'runs'
    assert page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth") == 0
    assert errors == []
