"""T10: the fields that read as a pair share a row, and the count slider is gone.

The plan pairs four controls -- Detergent with Detergent template, Protein with Download from OPM, Initialisation
style with Detergents in the micelle, CG assessment leg with CG extension leg -- and drops the coarse count range
slider. A pair that merely *exists* proves nothing: two block labels stack and every assertion about presence still
holds. So this measures, the way the two-column test in `test_pdc_new_run_browser.py` measures: the two controls of
a pair share a y within a pixel or two, and both sit inside the left column.

The two-column assertions themselves are unchanged and still run there; what this file adds is the row geometry of
each pair, plus the absence of the slider.
"""
import re

from playwright.sync_api import expect

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
# Each pair: the class the plan's row carries, and the two controls whose row it is. Measured on the pair's own two
# grid children, because those are the row; a control's own top can drift a few pixels with the inline line box
# above it (a tall select against a short input) without the row itself moving.
PAIRS = (('new-pdc-detergent-pair', 'Detergent · Detergent template', '#new-detergent', '#new-template'),
         ('new-pdc-protein-pair', 'Protein · Download from OPM', '#new-protein', '#new-protein-id'),
         ('new-pdc-config-pair', 'Initialisation style · Detergents in the micelle', '#new-placement', '#new-count'),
         ('new-pdc-legs', 'CG assessment leg · CG extension leg', '#new-assessment-ns', '#new-extension-ns'))
# A row is shared when the two cells' tops agree within the rounding of a sub-pixel layout.
TOLERANCE_PX = 2


def serve(page):
    page.route(re.compile(r'/api/pdc/catalog'), lambda route: route.fulfill(json=CATALOG))
    page.route(re.compile(r'/api/mappings\?'), lambda route: route.fulfill(json={'candidates': []}))
    page.route(re.compile(r'/api/readiness\?'),
               lambda route: route.fulfill(json={'ready': True, 'checks': [], 'blockers': []}))
    page.route(re.compile(r'/encapsulation'),
               lambda route: route.fulfill(status=400, json={'error': 'sizing is not exercised here'}))


def open_panel(page, base_url):
    page.goto(f'{base_url}/protein-detergent/new-run')
    page.get_by_role('tab', name='New run', exact=True).click()
    page.wait_for_function("() => document.querySelectorAll('#new-detergent option').length > 1", timeout=30000)
    page.wait_for_function("() => document.querySelectorAll('#new-protein option').length > 1", timeout=30000)
    page.locator('#new-protein').select_option('molecules/1qj8/1qj8.pdb')


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
