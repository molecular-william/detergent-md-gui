"""T10: the fields that read as a pair share a row, and the count slider is gone.

The plan pairs four controls -- Detergent with Detergent template, Protein with Download from OPM, Initialisation
style with Detergents in the micelle, CG assessment leg with CG extension leg -- and drops the coarse count range
slider. A pair that merely *exists* proves nothing: two block labels stack and every assertion about presence still
holds. So this measures, the way the two-column test in `test_pdc_new_run_browser.py` measures: the two controls of
a pair share a y within a pixel or two, and both sit inside the left column.

The two-column assertions themselves are unchanged and still run there; what this file adds is the row geometry of
each pair, plus the absence of the slider.

The Download-from-OPM row is measured a second way, because its shape is a claim about three controls rather than
two cells: the OPM id, its button and the chain ticks are one row, in that left-to-right order, inside the left
column. The tiers' viewport is 1700 px, so the row is measured at the width it is really asked to fit.
"""
import re

from playwright.sync_api import expect

from . import panels

CATALOG = {
    'templates': [{'id': 'DDM:DDM', 'name': 'DDM skeleton', 'molecule': 'DDM', 'residue': 'DDM',
                   'template': 'molecules/DDM/micelle_template.json', 'registered_type': 'registered-template',
                   'files_present': True, 'missing_files': [],
                   'limitations': ['skeleton placeholder template, not a fitted detergent model']}],
    'proteins': [{'id': 'molecules/1qj8/1qj8.pdb', 'name': '1qj8', 'path': 'molecules/1qj8/1qj8.pdb',
                  'source': 'packaged', 'half_thickness_nm': 1.35}],
    'defaults': {'aggregation_number': 150, 'assessment_ns': 100, 'extension_ns': 900, 'salt_molar': 0.15,
                 'box_margin_nm': 2.0, 'initial_z_nm': 6.0, 'contact_nm': 0.6,
                 'selection_threshold_fraction': 0.1, 'snapshot_interval_ns': 20.0, 'snapshot_cap': 20},
}
PROTEIN = 'molecules/1qj8/1qj8.pdb'
# A deposited assembly, so the chain ticks are on the row: 1qj8 (the packaged fixture) declares no chains, and the
# Download row is measured with the ticks it only has when an entry has some.
TRIMER = {'id': 'molecules/1at9/1at9.pdb', 'name': '1at9', 'path': 'molecules/1at9/1at9.pdb',
          'source': 'imported', 'half_thickness_nm': 1.5, 'chains': ['A', 'B', 'C']}
TRIMER_CATALOG = {**CATALOG, 'proteins': [TRIMER]}
# Each pair: the class the plan's row carries, and the two controls whose row it is. Measured on the pair's own two
# grid children, because those are the row; a control's own top can drift a few pixels with the inline line box
# above it (a tall select against a short input) without the row itself moving.
PAIRS = (('new-pdc-detergent-pair', 'Detergent · Detergent template', '#new-detergent', '#new-template'),
         ('new-pdc-protein-pair', 'Protein · Download from OPM', '#new-protein', '#new-protein-id'),
         ('new-pdc-config-pair', 'Initialisation style · Detergents in the micelle', '#new-placement', '#new-count'),
         ('new-pdc-legs', 'CG assessment leg · CG extension leg', '#new-assessment-ns', '#new-extension-ns'))
# A row is shared when the two cells' tops agree within the rounding of a sub-pixel layout.
TOLERANCE_PX = 2
# The download row's three controls are different element kinds -- a text input, a button and checkbox inputs -- so
# they cannot share a top: the 43 px field and the 13 px box are centred on the same line instead, and a wrapped
# control drops a whole line. What is asserted is that they share the line, not that they are pixel-identical.
ROW_TOLERANCE_PX = 3


def serve(page, catalog=CATALOG):
    page.route(re.compile(r'/api/pdc/catalog'), lambda route: route.fulfill(json=catalog))
    page.route(re.compile(r'/api/mappings\?'), lambda route: route.fulfill(json={'candidates': []}))
    page.route(re.compile(r'/api/readiness\?'),
               lambda route: route.fulfill(json={'ready': True, 'checks': [], 'blockers': []}))
    page.route(re.compile(r'/encapsulation'),
               lambda route: route.fulfill(status=400, json={'error': 'sizing is not exercised here'}))


def open_panel(page, base_url, protein=PROTEIN):
    return panels.open_pdc_new_run(page, base_url, protein=protein)


def pair_rows(page):
    """Each pair's two grid cells and the column they must sit inside, measured from the rendered page."""
    return page.evaluate("""() => {
      const column = document.querySelector('.new-run-inputs').getBoundingClientRect();
      return Array.from(document.querySelectorAll('#run-form .new-pdc-pair')).map(pair => ({
        classes: Array.from(pair.classList),
        kids: Array.from(pair.children).map(child => {
          const r = child.getBoundingClientRect();
          return {x: r.x, y: r.y, width: r.width, height: r.height};
        }),
        column: {x: column.x, y: column.y, width: column.width, height: column.height},
      }));
    }""")


def download_row(page):
    """The Download-from-OPM row: the id, the button and the chain ticks, each with its box and vertical centre.

    A checkbox is 13 px and the text field is 43 px, so their tops cannot coincide on one row; the coordinate that
    says "same line" for controls of different heights is the vertical centre. A control that had wrapped would sit a
    whole line (about 44 px) lower, so the centre also tells the two apart.
    """
    return page.evaluate("""() => {
      const column = document.querySelector('.new-run-inputs').getBoundingClientRect();
      const controls = [document.querySelector('#new-protein-id'), document.querySelector('#new-import'),
                        ...document.querySelectorAll('[name=protein_chains]')];
      return {
        column: {x: column.x, y: column.y, width: column.width},
        boxes: controls.map(el => { const r = el.getBoundingClientRect();
          return {name: el.id || el.value || el.tagName, x: r.x, y: r.y, width: r.width, height: r.height,
                  cy: r.y + r.height / 2}; }),
      };
    }""")


def test_every_pair_shares_a_row_inside_the_column(dashboard, live_page):
    page, errors = live_page
    serve(page)
    open_panel(page, live_page.base_url)

    rows = pair_rows(page)
    assert len(rows) == len(PAIRS), f'{len(rows)} pairs rendered, expected {len(PAIRS)}: {[r["classes"] for r in rows]}'
    by_class = {name: row for row in rows for name in row['classes']}
    for cls, label, first, second in PAIRS:
        row = by_class.get(cls)
        assert row is not None, f'{cls} is not rendered as a pair: {sorted(by_class)}'
        assert len(row['kids']) == 2, f'{cls} has {len(row["kids"])} cells, not two'
        left, right = row['kids']
        delta = abs(left['y'] - right['y'])
        assert delta <= TOLERANCE_PX, f'{label} is stacked, not paired: y {left["y"]} vs {right["y"]} (Δ{delta})'
        column = row['column']
        for name, box in ((first, left), (second, right)):
            assert box['x'] >= column['x'] - 1, f'{name} leaves the column on the left: {box} vs {column}'
            assert box['x'] + box['width'] <= column['x'] + column['width'] + 1, \
                f'{name} leaves the column on the right: {box} vs {column}'
        # And the two named controls really are in this pair's cells, so the row measured is the row claimed.
        for selector in (first, second):
            assert page.locator(f'#new .{cls} {selector}').count() == 1, f'{selector} is not inside .{cls}'

    assert errors == [], errors


def test_the_download_row_holds_the_input_the_button_and_the_chain_ticks(dashboard, live_page):
    """One row: the OPM id, its Download button, then a tick per chain the entry declares, all inside the column.

    A row that has wrapped still shows every control and still passes any assertion that the controls exist, so this
    measures the line the controls share -- a wrapped row puts the ticks a whole line lower and the spread of the
    vertical centres says so -- and the right edges, so nothing reaches past the left column at the 1700 px viewport.
    """
    page, errors = live_page
    serve(page, TRIMER_CATALOG)
    open_panel(page, live_page.base_url, protein=TRIMER['id'])
    page.wait_for_selector('.new-pdc-chain-list input', timeout=30000)

    row = download_row(page)
    boxes = row['boxes']
    assert [b['name'] for b in boxes] == ['new-protein-id', 'new-import', 'A', 'B', 'C'], boxes
    detail = ', '.join(f'{b["name"]} (x{b["x"]:.0f} y{b["y"]:.0f} h{b["height"]:.0f} {b["width"]:.0f}px)'
                       for b in boxes)
    centres = [b['cy'] for b in boxes]
    spread = max(centres) - min(centres)
    assert spread <= ROW_TOLERANCE_PX, f'the download controls are on different lines (centre spread {spread:.2f} px): {detail}'
    # And they really overlap vertically: a wrapped control would sit below the others' bottoms.
    assert max(b['y'] for b in boxes) < min(b['y'] + b['height'] for b in boxes), \
        f'the download controls do not overlap on the line: {detail}'

    column = row['column']
    for box in boxes:
        assert box['x'] >= column['x'] - 1, f'{box["name"]} leaves the column on the left: {box} vs {column}'
        assert box['x'] + box['width'] <= column['x'] + column['width'] + 1, \
            f'{box["name"]} overflows the column on the right: {box} vs {column}'

    # Left to right: the id field, its button, then the ticks.
    xs = [b['x'] for b in boxes]
    assert boxes[0]['x'] < boxes[1]['x'] < boxes[2]['x'], xs
    assert errors == [], errors


def test_the_count_slider_is_gone_and_the_number_input_stays(dashboard, live_page):
    """The range slider went in T10; the number input the adapter reads stays, in both modes."""
    page, errors = live_page
    serve(page)
    open_panel(page, live_page.base_url)

    assert page.locator('#new-count-range').count() == 0, 'the count range slider is still rendered'
    assert page.locator('.new-pdc-count-range').count() == 0, 'a count range slider is still rendered'
    expect(page.locator('#new-count')).to_be_visible()
    assert page.locator('#new-count').get_attribute('type') == 'number'
    assert errors == [], errors


def test_the_two_columns_are_still_side_by_side_at_the_wide_viewport(dashboard, live_page):
    """The existing two-column proof, restated beside the geometry above so a regression lands here too."""
    page, errors = live_page
    serve(page)
    open_panel(page, live_page.base_url)

    form = page.locator('#run-form').bounding_box()
    inputs = page.locator('.new-run-inputs').bounding_box()
    settings = page.locator('.new-run-settings').bounding_box()
    assert settings['x'] >= inputs['x'] + inputs['width'] - 1, 'the halves overlap: they are not side by side'
    assert abs(inputs['width'] - form['width'] / 2) <= 20, (inputs['width'], form['width'])
    assert abs(settings['width'] - form['width'] / 2) <= 20, (settings['width'], form['width'])
    assert errors == [], errors
