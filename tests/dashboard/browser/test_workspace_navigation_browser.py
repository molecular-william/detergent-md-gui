"""The two-level navigation: two workspace tabs across the top, and the active workspace's sub-panels beneath.

This file replaces one that specified the vertical rail -- its 220 px column, its right-hand placement, its
icon-only medium width and its row below 900 px. The rail is gone, and so is everything that described it. What
survives from that file is its first test, because its subject was never the rail: the page has one measure, each
workspace places its panels on that measure by span, and a workspace must not sit in a sub-column of its own.

The assertions here are **boxes and counts, not appearance**. The failure this navigation actually produced -- the
two workspace tabs stacked in a column instead of sharing a row -- looked entirely plausible in a screenshot; only
`y` coordinates said otherwise.
"""
import re

from playwright.sync_api import expect

WIDE = {'width': 1440, 'height': 900}
NARROW = {'width': 820, 'height': 900}

# The panels of each workspace, in its own order, by DOM id. The two navigations are different lists, which is the
# point of the split: `runs` and `new` appear in both because they are different run lists and different forms.
VALIDATION = ('runs', 'runview', 'new', 'mappings', 'bonded', 'compositions', 'validation', 'osmotic-pressure')
SIMULATIONS = ('runs', 'runview', 'new', 'pdc')


def width(page, selector):
    return page.evaluate("sel => { const el = document.querySelector(sel); return el ? Math.round(el.getBoundingClientRect().width) : null; }", selector)


def box(page, selector):
    return page.evaluate("""sel => { const el = document.querySelector(sel); if (!el) return null;
      const r = el.getBoundingClientRect();
      return {top: Math.round(r.top), left: Math.round(r.left), width: Math.round(r.width), height: Math.round(r.height)}; }""", selector)


def test_the_two_workspace_tabs_share_one_row_and_split_it_evenly(dashboard, live_page):
    """The failure this catches is invisible in a screenshot: a column of tabs reads as a plausible layout."""
    page, errors = live_page
    page.set_viewport_size(WIDE)
    page.goto(live_page.base_url)

    tabs = page.locator('.section-tab')
    expect(tabs).to_have_count(2)
    first, second = box(page, '.section-tab:nth-of-type(1)'), box(page, '.section-tab:nth-of-type(2)')
    assert abs(first['top'] - second['top']) < 4, f'the two tabs are on one row: {first} {second}'
    assert abs(first['width'] - second['width']) < 8, 'and they split it evenly'
    assert first['left'] < second['left'], 'in registry order'
    # Each carries a one-line description: that sentence is what the abandoned overview page was for.
    assert page.evaluate(
        "() => [...document.querySelectorAll('.section-tab .sub')].every(el => el.textContent.trim().length > 20)"
    ), 'each tab says what is in its workspace'
    assert errors == []


def test_the_sub_tab_row_changes_with_the_workspace(dashboard, live_page):
    """The row is rebuilt per workspace, so it can never offer a panel the workspace does not have."""
    page, errors = live_page
    page.set_viewport_size(WIDE)
    page.goto(live_page.base_url)
    expect(page.locator('#subtabs .subtab')).to_have_count(len(VALIDATION))

    page.locator('.section-tab[data-section=protein-detergent]').click()
    expect(page).to_have_url(re.compile(r'/protein-detergent/'))
    expect(page.locator('#subtabs .subtab')).to_have_count(len(SIMULATIONS))
    assert page.locator('#subtabs .subtab[aria-selected=true]').count() == 1
    # The panels a workspace does not own are absent from its URL space entirely.
    assert page.locator('a[href="/detergent-validation/bond-interactions"]').count() == 0
    assert errors == []


def test_the_open_panel_is_the_one_the_server_marked(dashboard, live_page):
    """A cold request for a panel returns that panel, open, before any JavaScript has run.

    The panel's own module is mounted by a `dashboard:tab` event, and a page that never announces its open panel
    mounts nothing at all -- the runs table reads "Loading runs…" forever while the API answers 200. So this asserts
    the *content* of the panel, not the attribute that selects it.
    """
    page, errors = live_page
    page.set_viewport_size(WIDE)
    page.goto(f'{live_page.base_url}/detergent-validation/bond-interactions')
    expect(page.locator('#bonded:not([hidden])')).to_be_visible()
    expect(page.locator('#subtabs .subtab[aria-selected=true]')).to_contain_text('Bond Interactions')
    assert errors == []


def test_the_arrow_keys_move_within_each_row(dashboard, live_page):
    """Both rows are horizontal tablists, so the keys that move through them are the horizontal pair."""
    page, errors = live_page
    page.set_viewport_size(WIDE)
    page.goto(f'{live_page.base_url}/detergent-validation/runs')

    page.locator('#tab-runs').focus()
    page.keyboard.press('ArrowRight')
    # `run-view` sits directly after `runs` in both workspaces, so the horizontal pair walks into it.
    expect(page.locator('#tab-runview')).to_have_attribute('aria-selected', 'true')
    page.keyboard.press('ArrowLeft')
    expect(page.locator('#tab-runs')).to_have_attribute('aria-selected', 'true')
    expect(page.locator('nav.subtabs')).to_have_attribute('aria-orientation', 'horizontal')
    assert errors == []


def test_nothing_overflows_sideways_at_a_narrow_window(dashboard, live_page):
    """A six-item row has to wrap rather than push the page wide, and the workspace tabs stack."""
    page, errors = live_page
    page.set_viewport_size(NARROW)
    page.goto(live_page.base_url)

    assert page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth") == 0
    first, second = box(page, '.section-tab:nth-of-type(1)'), box(page, '.section-tab:nth-of-type(2)')
    assert second['top'] >= first['top'] + first['height'] - 2, 'the workspace tabs stack when there is no room'
    assert errors == []


def test_every_panel_is_the_same_width_and_has_no_dead_space_beside_it(dashboard, live_page):
    """The measure is the page's, and a workspace fills its columns of it rather than sitting in a sub-column.

    Kept from the file this one replaces, because its subject was never the rail. Each workspace is walked through
    its own tabs -- the previous version clicked one flat list of seven ids, which is a list no single page has now.
    """
    page, errors = live_page
    page.set_viewport_size(WIDE)

    measures = {}
    for workspace, panels in (('detergent-validation', VALIDATION), ('protein-detergent', SIMULATIONS)):
        page.goto(f'{live_page.base_url}/{workspace}/{panels[0]}')
        for panel in panels:
            page.click(f'#tab-{panel}')
            page.wait_for_selector(f'#{panel}:not([hidden])')
            measures[panel] = width(page, f'#{panel}')
    assert len(set(measures.values())) == 1, f'the panels are the same width: {measures}'

    def track_width(selector):
        return page.evaluate("""sel => { const box = document.querySelector(sel);
          if (!box) return {missing: sel};
          const cs = getComputedStyle(box);
          const gap = parseFloat(cs.columnGap) || 0;
          const width = box.getBoundingClientRect().width;
          return {gap: gap, track: (width - gap * 11) / 12,
                  kids: [...box.children].map(el => el.getBoundingClientRect().width)}; }""", selector)

    cases = (('detergent-validation', 'new-run', '.new-run-layout', (6, 6)),
             ('detergent-validation', 'osmotic-pressure', '.osmotic-layout', (6, 6)),
             ('detergent-validation', 'bead-assignment', '.mapping-editor-layout', (7, 5)),
             ('detergent-validation', 'combinations', '.composition-workspace', (3, 9)),
             # The Run view is not in this table any more: it has no 12-column layout of its own, it is two
             # monitors of equal width side by side. That claim is asserted where the panel's own layout is
             # (`test_run_view_browser.py`), and its children still span the measure at panel level, which the loop
             # above checks for every panel in both workspaces.
             ('protein-detergent', 'complexes', '.pdc-workspace', (3, 9, 12)),
             ('detergent-validation', 'bond-interactions', '.bonded-columns', (6, 6)))
    for workspace, panel, layout, spans in cases:
        # `panel` is the URL *slug*, not the DOM id: the registry keeps those two vocabularies apart on purpose, and
        # using the id here asked for `/detergent-validation/new`, which is not a panel. The diagnostic assertion
        # below is what named it -- the page reported its own URL rather than a timeout pretending to be a missing
        # element.
        page.goto(f'{live_page.base_url}/{workspace}/{panel}')
        assert page.url.rstrip('/').endswith(f'/{workspace}/{panel}'), f'asked for {panel}, landed on {page.url}'
        page.wait_for_selector(layout, timeout=15000)
        measured = track_width(layout)
        assert 'missing' not in measured, f'{panel}: no {layout} in the page'
        assert len(measured['kids']) == len(spans), f'{panel}: {len(measured["kids"])} panels for {len(spans)} spans'
        for span, measured_width in zip(spans, measured['kids']):
            expected = span * measured['track'] + (span - 1) * measured['gap']
            assert abs(measured_width - expected) <= 2, \
                f'{panel}: a span-{span} panel is {measured_width:.0f} px where the measure says {expected:.0f}'
    assert errors == []
