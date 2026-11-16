"""The bonded surface pane: two meshes, a dots switch, and a status line that says what was drawn.

The module is mounted by hand here because the workspace wiring is a separate change: this file pins the pane's own
contract -- the POST it makes, the Plotly traces it produces, the ARIA it states, the dots toggle, and the clear/destroy
lifecycle. The surface route is stubbed with a two-triangle mesh per envelope, so nothing reads a trajectory.
"""
from playwright.sync_api import expect

AA_MESH = {'vertices': [0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 1, 0], 'faces': [0, 1, 2, 1, 3, 2]}
CG_MESH = {'vertices': [0, 0, 1, 1, 0, 1, 0, 1, 1, 1, 1, 1], 'faces': [0, 1, 2, 1, 3, 2]}
SURFACE = {'aa': AA_MESH, 'cg': CG_MESH, 'probe_radius_nm': 0.14, 'spacing_nm': 0.04}


def surface_data(page):
    """The trace types and names Plotly is currently holding for the fixture's plot."""
    return page.evaluate("""() => {
      const plot = document.querySelector('#surface-fixture .bonded-surface-plot');
      if (!plot || !plot.data) return {types: [], names: []};
      return {types: plot.data.map(trace => trace.type), names: plot.data.map(trace => trace.name || '')};
    }""")


def test_the_surface_pane_draws_two_meshes_and_toggles_its_dots(dashboard, live_page):
    page, errors = live_page
    asked = []

    def surface(route):
        asked.append(route.request.post_data_json)
        route.fulfill(json=SURFACE)

    page.route('**/api/bonded-surfaces', surface)
    page.goto(f'{live_page.base_url}/detergent-validation/new-run')
    page.evaluate("""async () => {
      const pane = await import('/static/js/bonded-surface.js');
      const host = document.createElement('div');
      host.id = 'surface-fixture';
      document.body.append(host);
      window.__surface = pane.createBondedSurface({host});
    }""")
    page.evaluate("window.__surface.load({molecule_id: 'DDM', beads: [{name: 'B01'}]})")

    plot = page.locator('#surface-fixture .bonded-surface-plot')
    expect(plot).to_be_visible(timeout=30000)
    expect(plot).to_have_attribute('aria-label', 'Mapped AA and CG solvent-accessible surface')
    expect(page.locator('#surface-fixture .bonded-surface-status')).to_have_attribute('role', 'status')
    data = surface_data(page)
    assert data['types'].count('mesh3d') == 2, data
    assert [name for name in data['names'] if name in ('AA', 'mapped CG')] == ['AA', 'mapped CG'], data
    assert asked == [{'molecule_id': 'DDM', 'beads': [{'name': 'B01'}]}], asked

    status = page.locator('#surface-fixture .bonded-surface-status')
    expect(status).to_contain_text('SAS envelope from the mapped coordinates, not a simulation')
    expect(status).to_contain_text('Probe radius 0.14 nm')
    expect(status).to_contain_text('spacing 0.04 nm')
    expect(status).to_contain_text('AA 4 points / 2 triangles')
    expect(status).to_contain_text('CG 4 points / 2 triangles')

    # The dots are extra traces over the same vertices; the meshes stay either way.
    page.locator('#surface-fixture .bonded-surface-toggle input').check()
    page.wait_for_function("""() => document.querySelector('#surface-fixture .bonded-surface-plot').data
      .filter(trace => trace.type === 'scatter3d').length === 2""", timeout=15000)
    data = surface_data(page)
    assert data['types'].count('mesh3d') == 2 and data['types'].count('scatter3d') == 2, data
    page.locator('#surface-fixture .bonded-surface-toggle input').uncheck()
    page.wait_for_function("""() => document.querySelector('#surface-fixture .bonded-surface-plot').data
      .filter(trace => trace.type === 'scatter3d').length === 0""", timeout=15000)
    assert surface_data(page)['types'].count('mesh3d') == 2

    # clear() is the "no model selected" state, with only the hint left in the host.
    page.evaluate("window.__surface.clear()")
    host = page.locator('#surface-fixture')
    expect(host).to_contain_text('Choose a model to see its mapped AA/CG surface')
    expect(page.locator('#surface-fixture .bonded-surface-plot')).to_have_count(0)

    page.evaluate("window.__surface.destroy()")
    expect(host).to_be_empty()
    assert errors == [], errors


def test_the_panel_renders_the_bulk_controls_and_surface_host_in_both_panes(dashboard, live_page):
    """Both panes carry the bulk edits and a surface host; the ids are the ones the panel reads."""
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/bond-interactions')
    expect(page.locator('#bonded')).to_be_visible(timeout=30000)
    for selector in ('#bonded-revert-terms, #bonded-revert-terms-B',
                     '#bonded-scale-factor, #bonded-scale-factor-B',
                     '#bonded-scale-terms, #bonded-scale-terms-B',
                     '#bonded-bulk-status, #bonded-bulk-status-B',
                     '#bonded-surface, #bonded-surface-B'):
        expect(page.locator(selector)).to_have_count(2)
    assert errors == [], errors
