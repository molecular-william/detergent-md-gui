"""The Run view Analysis layouts: full-width columns, disclosures, the single surface scene and chart resizing.

These read the same published records the analysis browser tests read, but ask about the shape of the card: with two
monitors the card is half the page and the comparison map stacks its scene above the reading; with the second monitor
minimized (`#run-view-monitors.one-column`) the scene and the reading sit side by side, the SASA table moves beside the
surface scene, and every Plotly host is resized to the card's new width. The published records are the shared
construction in `tests/harness/validation_fixtures.py`; what this file pins is the layout, not their meaning.
"""
import re

from playwright.sync_api import expect

from tests.harness import browser
from tests.harness.validation_fixtures import publish, publish_cross_check, publish_mapping, publish_overlap, publish_surfaces

CARD = '#run-view-analysis-A'


def one_column(page):
    """Minimize the second monitor, which is what makes the first monitor's card full width."""
    page.locator('#run-view-second-toggle').click()
    expect(page.locator('#run-view-monitors')).to_have_class(re.compile(r'\bone-column\b'))


def _overlap(above, below):
    """Whether two bounding boxes share a vertical span."""
    return above['y'] < below['y'] + below['height'] and below['y'] < above['y'] + above['height']


def test_the_map_and_reading_are_stacked_at_half_width_and_side_by_side_at_full_width(dashboard, live_page):
    publish(dashboard, 'aa11bb22cc33')
    publish_mapping(dashboard, 'aa11bb22cc33')
    page, errors = live_page
    browser.open_run_section(page, live_page.base_url, 'aa11bb22cc33', 'mapping-geometry')
    map_host = page.locator(f'{CARD} .analysis-map')
    body = map_host.locator('.rvm-map-body')
    reading = map_host.locator('.rvm-reading')
    expect(body).to_be_visible(timeout=30000)
    expect(reading).to_be_visible()
    # The scene is drawn asynchronously: measuring before Plotly sets its height would compare a short body with a
    # reading box that is still above where it settles. Wait for the scene, then measure.
    page.wait_for_function("""selector => {
      const host = document.querySelector(selector);
      return Boolean(host && host.querySelector('.main-svg'));
    }""", arg=f'{CARD} .analysis-map .rvm-map-plot', timeout=30000)

    # Two monitors: the card is half the page, so the reading is beneath the scene.
    stacked_body = body.bounding_box()
    stacked_reading = reading.bounding_box()
    assert stacked_reading['y'] >= stacked_body['y'] + stacked_body['height'] - 2, (stacked_body, stacked_reading)
    assert stacked_reading['x'] < stacked_body['x'] + stacked_body['width'], (stacked_body, stacked_reading)

    one_column(page)

    # One monitor: the scene on the left, the reading on the right, the head across both.
    body_box = body.bounding_box()
    reading_box = reading.bounding_box()
    assert reading_box['x'] > body_box['x'] + 40, (body_box, reading_box)
    assert _overlap(body_box, reading_box), (body_box, reading_box)
    head = map_host.locator('.rvm-map-head').bounding_box()
    assert head['width'] >= body_box['width'] + reading_box['width'] - 20, (head, body_box, reading_box)
    assert errors == []


def test_the_disclosures_start_closed_and_open_on_click(dashboard, live_page):
    publish(dashboard, 'aa11bb22cc33')
    publish_cross_check(dashboard, 'aa11bb22cc33')
    page, errors = live_page

    geometry = browser.open_run_section(page, live_page.base_url, 'aa11bb22cc33', 'mapping-geometry')
    pairs = geometry.locator('details.rvm-term-group', has_text='Constrained pairs')
    expect(pairs).to_have_count(1)
    expect(pairs.locator('summary')).to_contain_text('Constrained pairs (2)')
    expect(pairs).not_to_have_attribute('open', '')
    expect(pairs.locator('.rvm-measure').first).to_be_hidden()
    pairs.locator('summary').click()
    expect(pairs).to_have_attribute('open', '')
    expect(pairs.locator('.rvm-measure')).to_have_count(2)
    expect(pairs.locator('.rvm-measure').first).to_be_visible()
    # The caveat is inside the disclosure, after the rows it is about.
    expect(pairs.locator('.hint').last).to_contain_text('These constraints are fitted')

    pane = browser.open_run_section(page, live_page.base_url, 'aa11bb22cc33', 'mapping-bonded')
    bonds = pane.locator('details.rvm-term-group', has_text='Bonds (1)')
    angles = pane.locator('details.rvm-term-group', has_text='Angles (1)')
    for group in (bonds, angles):
        expect(group).not_to_have_attribute('open', '')
        expect(group.locator('.rvm-measure')).to_be_hidden()

    fit = pane.locator('details.rvm-sub-group')
    expect(fit).to_have_count(1)
    expect(fit.locator('summary')).to_have_text('Our fit against the independent estimate')
    expect(fit).not_to_have_attribute('open', '')
    expect(fit.locator('.rvm-measure').first).to_be_hidden()
    fit.locator('summary').click()
    expect(fit).to_have_attribute('open', '')
    expect(fit.locator('.rvm-measure')).to_have_count(3)
    expect(fit.locator('.rvm-measure').first).to_be_visible()
    assert 'Threshold 10000' in ' '.join(fit.text_content().split())

    # A map attention item that names a term reveals the row inside its own closed group. The weakest term in the
    # fixture is the angle, so the first item points into the Angles group.
    items = page.locator(f'{CARD} .analysis-map .rvm-attention li')
    expect(items.first).to_be_visible(timeout=30000)
    assert 'angles' in items.nth(0).text_content().lower(), items.nth(0).text_content()
    items.nth(0).locator('button').click()
    expect(angles).to_have_attribute('open', '')
    expect(pane.locator('[data-item="term:1"]')).to_have_attribute('aria-selected', 'true')
    expect(pane.locator('[data-item="term:1"]')).to_be_visible()

    # Bonds is its own disclosure, still closed until the reader opens it.
    expect(bonds).not_to_have_attribute('open', '')
    bonds.locator('summary').click()
    expect(bonds).to_have_attribute('open', '')
    expect(bonds.locator('.rvm-measure').first).to_be_visible()
    assert errors == []


def test_the_shape_scene_has_four_traces_and_the_checkboxes_toggle_them(dashboard, live_page):
    publish(dashboard, 'bb22cc33dd44')
    publish_surfaces(dashboard, 'bb22cc33dd44')
    publish_overlap(dashboard, 'bb22cc33dd44')
    page, errors = live_page
    pane = browser.open_run_section(page, live_page.base_url, 'bb22cc33dd44', 'mapping-shape')
    envelope = pane.locator('[data-shape="surfaces"]')
    plot = envelope.locator('.rvm-surface-plot')
    expect(plot).to_have_count(1)
    browser.wait_for_traces(page, f'{CARD} .analysis-pane[data-section="mapping-shape"] .rvm-surface-plot', 4)
    types = plot.evaluate('el => el.data.map(trace => trace.type)')
    assert types == ['mesh3d', 'scatter3d', 'mesh3d', 'scatter3d'], types
    assert plot.evaluate('el => el.layout.showlegend') is not True

    # The table is three columns of the published statistics, beside the plot only once the card is full width.
    assert envelope.locator('.rvm-table thead th').all_text_contents() == ['Model', 'Mean SASA', 'SD']
    rows = envelope.locator('.rvm-table tbody tr')
    expect(rows).to_have_count(2)
    assert [value.strip() for value in rows.nth(0).locator('td').all_text_contents()] == ['5.816', '0.077']
    assert [value.strip() for value in rows.nth(1).locator('td').all_text_contents()] == ['5.599', '0.174']

    checks = envelope.locator('.rvm-checks input')
    assert checks.evaluate_all('els => els.map(el => el.checked)') == [True, True]
    envelope.locator('.rvm-checks').get_by_label('Simulated CG').uncheck()
    browser.wait_for_traces(page, f'{CARD} .analysis-pane[data-section="mapping-shape"] .rvm-surface-plot', 4,
                            ready='el.data[2].visible === false && el.data[3].visible === false')
    visible = plot.evaluate('el => el.data.map(trace => trace.visible)')
    assert visible[0] is not False and visible[1] is not False, 'AA reference stays drawn'
    assert visible[2] is False and visible[3] is False, 'Simulated CG is hidden'

    one_column(page)
    plot_box = plot.bounding_box()
    table_box = envelope.locator('.rvm-surface-table').bounding_box()
    assert table_box['x'] > plot_box['x'] + 40, (plot_box, table_box)
    assert _overlap(plot_box, table_box), (plot_box, table_box)

    # The bead-overlap figure keeps its own, smaller frame; the surface fallback keeps the full-width one.
    frame = pane.locator('.rvm-overlap-frame')
    expect(frame).to_have_count(1)
    size = frame.evaluate("el => { const style = getComputedStyle(el);"
                          " return {maxWidth: style.maxWidth, height: style.height}; }")
    assert size == {'maxWidth': '640px', 'height': '300px'}, size
    assert errors == []


def test_the_map_and_chart_legends_are_twelve_pixels(dashboard, live_page):
    publish(dashboard, 'aa11bb22cc33')
    publish_mapping(dashboard, 'aa11bb22cc33')
    publish_surfaces(dashboard, 'aa11bb22cc33')
    page, errors = live_page
    browser.open_run_section(page, live_page.base_url, 'aa11bb22cc33', 'mapping-geometry')
    legend = page.locator(f'{CARD} .analysis-map .rvm-map-legend')
    expect(legend).to_be_visible(timeout=30000)
    legend_size = legend.evaluate('el => parseFloat(getComputedStyle(el).fontSize)')
    assert legend_size >= 12, legend_size

    page.locator(f'{CARD} .analysis-views button[data-section="mapping-shape"]').click()
    chart = page.locator(f'{CARD} .analysis-pane[data-section="mapping-shape"] .rvm-sasa-chart')
    browser.wait_for_traces(page, f'{CARD} .analysis-pane[data-section="mapping-shape"] .rvm-sasa-chart', 2)
    chart_size = chart.evaluate('el => el.layout.legend.font.size')
    assert chart_size >= 12, chart_size
    assert errors == []


def test_the_plotly_hosts_resize_when_the_card_width_changes(dashboard, live_page):
    publish(dashboard, 'aa11bb22cc33')
    publish_mapping(dashboard, 'aa11bb22cc33')
    page, errors = live_page
    browser.open_run_section(page, live_page.base_url, 'aa11bb22cc33', 'mapping-geometry')
    # Only Plotly's layout, not a trace count: the map draws one trace per bead type, virtual site and pair, so its
    # count depends on the comparison this run published.
    page.wait_for_function("""selector => {
      const el = document.querySelector(selector);
      return Boolean(el && el.data && el._fullLayout);
    }""", arg=f'{CARD} .analysis-map .rvm-map-plot', timeout=30000)
    svg = page.locator(f'{CARD} .analysis-map .rvm-map-plot .main-svg').first
    half_width = svg.bounding_box()['width']

    one_column(page)
    page.wait_for_function("""([selector, before]) => {
      const el = document.querySelector(selector);
      return Boolean(el && el.getBoundingClientRect().width > before + 50);
    }""", arg=[f'{CARD} .analysis-map .rvm-map-plot .main-svg', half_width], timeout=30000)
    full_width = svg.bounding_box()['width']
    assert full_width > half_width + 50, (half_width, full_width)

    # Restoring the second monitor halves the card again: the scene follows it back.
    page.locator('#run-view-second-toggle').click()
    expect(page.locator('#run-view-monitors')).not_to_have_class(re.compile(r'\bone-column\b'))
    page.wait_for_function("""([selector, after]) => {
      const el = document.querySelector(selector);
      return Boolean(el && el.getBoundingClientRect().width < after - 50);
    }""", arg=[f'{CARD} .analysis-map .rvm-map-plot .main-svg', full_width], timeout=30000)
    assert svg.bounding_box()['width'] < full_width - 50
    assert errors == []
