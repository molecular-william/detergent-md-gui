"""Browser proof that the Molecule Combination panel draws the CG geometry as 3D scenes.

The panel used to draw a grid of bead labels positioned by index arithmetic, so nothing on screen
reflected the molecule. These tests read the Plotly traces the panel actually produced, which means a
server or a code path that stops sending geometry fails here instead of leaving three empty rectangles.

The plots are read from `el.data` rather than from pixels: a 3D scene is a WebGL canvas, and the data
is what decides whether the beads are on screen at all.
"""
from playwright.sync_api import expect

HEAD = '#composition-plot-head'
TAIL = '#composition-plot-tail'
JOINED = '#composition-plot-joined'
RED = '#df203d'

BEAD_NAMES = """(el, colour) => el.data
  .filter(trace => trace.meta === 'bead')
  .flatMap(trace => {
    const colours = [].concat(trace.marker?.color ?? []);
    return colours.map((colourAt, index) => [colourAt, trace.text[index]])
      .filter(([colourAt, name]) => !colour || String(colourAt).toLowerCase() === colour)
      .map(([, name]) => name);
  })"""

EDGE_POINTS = "(el, meta) => el.data.filter(trace => trace.meta === meta).reduce((total, trace) => total + (trace.x || []).length, 0)"


def _preview(page):
    page.locator('#composition-preview').click()
    expect(page.locator('#composition-panel-status')).to_contain_text('Preview ready', timeout=30000)


def test_the_panel_draws_both_fragments_and_the_join_with_the_linkage_beads_in_red(dashboard, live_page):
    page, errors = live_page
    page.goto(f'{live_page.base_url}/#compositions')
    _preview(page)

    head, tail, joined = (page.locator(selector) for selector in (HEAD, TAIL, JOINED))
    for plot in (head, tail, joined):
        expect(plot.locator('.plotly')).to_be_visible()

    head_beads = head.evaluate(BEAD_NAMES, None)
    tail_beads = tail.evaluate(BEAD_NAMES, None)
    joined_beads = joined.evaluate(BEAD_NAMES, None)
    assert len(head_beads) == 3, head_beads
    assert len(tail_beads) == 3, tail_beads
    assert set(joined_beads) == set(head_beads) | set(tail_beads)

    # Virtual sites are not drawn: the sugar fragment has one and the head panel does not show it.
    assert 'VS' not in head_beads

    # Each fragment has exactly one red bead, and it is the endpoint the linkage currently attaches to.
    head_endpoint = page.locator('#composition-head-endpoint').input_value()
    tail_endpoint = page.locator('#composition-tail-endpoint').input_value()
    assert head.evaluate(BEAD_NAMES, RED) == [head_endpoint]
    assert tail.evaluate(BEAD_NAMES, RED) == [tail_endpoint]
    assert sorted(joined.evaluate(BEAD_NAMES, RED)) == sorted([head_endpoint, tail_endpoint])

    # Bonds are drawn: three head bonds, two tail bonds, plus the link between the fragments.
    assert head.evaluate(EDGE_POINTS, 'edge') == 3 * 3
    assert tail.evaluate(EDGE_POINTS, 'edge') == 2 * 3
    assert joined.evaluate(EDGE_POINTS, 'edge') == 6 * 3

    caption = page.locator('#composition-geometry-basis').text_content()
    assert 'layout' in caption and 'minimised' in caption and 'CG' in caption
    assert errors == []


def test_choosing_another_endpoint_moves_the_red_bead_in_every_view(dashboard, live_page):
    page, errors = live_page
    page.goto(f'{live_page.base_url}/#compositions')
    _preview(page)

    head = page.locator(HEAD)
    first = page.locator('#composition-head-endpoint').input_value()
    second = [value for value in head.evaluate(BEAD_NAMES, None) if value != first][0]

    page.locator('#composition-head-endpoint').select_option(second)
    _preview(page)
    assert head.evaluate(BEAD_NAMES, RED) == [second]
    assert second in page.locator(JOINED).evaluate(BEAD_NAMES, RED)
    assert errors == []


def test_clicking_a_bead_picks_it_as_the_endpoint(dashboard, live_page):
    page, errors = live_page
    page.goto(f'{live_page.base_url}/#compositions')
    _preview(page)

    head = page.locator(HEAD)
    current = page.locator('#composition-head-endpoint').input_value()
    target = [value for value in head.evaluate(BEAD_NAMES, None) if value != current][0]
    head.evaluate(
        '(el, name) => el.emit("plotly_click", {points: [{data: {meta: "bead"}, customdata: [name, "R"]}]})',
        target,
    )
    expect(page.locator('#composition-head-endpoint')).to_have_value(target)
    assert errors == []
