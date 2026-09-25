"""Browser proof for mapping-filtered bonded states and the 3D editor."""
from playwright.sync_api import expect

from dashboard.models import mappings
from dashboard.models.bonded import states as bonded_states


def test_bonded_workspace_filters_states_and_creates_a_new_state_from_two_beads(dashboard, live_page):
    first = mappings.save_draft(mappings.automatic_candidate(mappings.molecule(), 'DDM'))
    second_data = mappings.automatic_candidate(mappings.molecule(), 'DDM')
    second_data['name'] = 'Second mapping'
    second = mappings.save_draft(second_data)
    first_state = bonded_states.create(first, 'First state', topology='[ moleculetype ]\n[ atoms ]', status='complete')
    second_state = bonded_states.create(second, 'Second state', topology='[ moleculetype ]\n[ atoms ]', status='complete')

    page, errors = live_page
    page.goto(f'{live_page.base_url}/#bonded')
    mapping_select = page.locator('.bonded-mapping-select')
    state_select = page.locator('.bonded-state-select')
    mapping_select.select_option(first['file'])
    expect(state_select.locator('option')).to_have_count(2)
    expect(state_select.locator('option').nth(1)).to_contain_text('First state')
    expect(state_select.locator('option').nth(1)).not_to_contain_text('Second state')
    mapping_select.select_option(second['file'])
    expect(state_select.locator('option')).to_have_count(2)
    expect(state_select.locator('option').nth(1)).to_contain_text('Second state')
    expect(state_select.locator('option').nth(1)).not_to_contain_text('First state')
    expect(page.get_by_role('button', name='Save as new state')).to_be_visible()
    for name in ('Generate automatic bonded state', 'Create interaction', 'Run short CG validation', 'Save as new state', 'Delete state'):
        expect(page.get_by_role('button', name=name)).to_have_count(1)
    for name in ('Load mapping', 'Create bonded state', 'Fit bonded parameters', 'Revise selected state'):
        expect(page.get_by_role('button', name=name)).to_have_count(0)
    expect(page.get_by_role('button', name='Create interaction')).to_be_disabled()
    plot = page.locator('.bonded-plot')
    expect(plot.locator('.plotly')).to_be_visible()
    names = plot.evaluate("(el) => el.data.filter(trace => trace.meta === 'bead').flatMap(trace => trace.customdata.map(item => Array.isArray(item) ? item[0] : item)).slice(0, 4)")
    assert len(names) == 4
    plot_data = plot.evaluate("(el) => el.data.map(trace => ({meta: trace.meta, showlegend: trace.showlegend, name: trace.name, sizes: trace.marker?.size || []}))")
    bead_traces = [trace for trace in plot_data if trace['meta'] == 'bead']
    assert bead_traces and all(size > 9 for trace in bead_traces for size in trace['sizes'])
    assert all(trace['showlegend'] is not True for trace in plot_data if trace['meta'] in ('edge', 'term'))
    for name in names[:3]:
        plot.evaluate('(el, bead) => el.emit("plotly_click", {points: [{data: {meta: "bead"}, customdata: bead}]})', name)
    expect(page.locator('.bonded-selection-status')).to_contain_text(names[1])
    expect(page.locator('.bonded-selection-status')).to_contain_text(names[2])
    expect(page.get_by_role('button', name='Create interaction')).to_be_enabled()
    plot.evaluate('(el, bead) => el.emit("plotly_click", {points: [{data: {meta: "bead"}, customdata: bead}]})', names[0])
    expect(page.locator('.bonded-selection-status')).to_contain_text(names[0])
    expect(page.locator('.bonded-selection-status')).to_contain_text(names[2])
    expect(page.locator('.bonded-selection-status')).not_to_contain_text(names[1])
    expect(page.get_by_role('button', name='Create interaction')).to_be_enabled()
    for name in (names[2], names[0]):
        plot.evaluate('(el, bead) => el.emit("plotly_click", {points: [{data: {meta: "bead"}, customdata: bead}]})', name)
    for name in (names[0], names[3]):
        plot.evaluate('(el, bead) => el.emit("plotly_click", {points: [{data: {meta: "bead"}, customdata: bead}]})', name)
    page.get_by_role('button', name='Create interaction').click()
    expect(page.locator('.bonded-interaction-table tbody tr')).not_to_have_count(0)
    page.get_by_role('button', name='Save as new state').click()
    expect(page.locator('.bonded-state-select option')).to_have_count(3)
    assert page.get_by_role('button', name='Save as new state').is_disabled()
    new_state_id = page.locator('.bonded-state-select option').evaluate_all(
        "(options, existing) => options.map(option => option.value).find(value => value && value !== existing)",
        second_state['state_id'],
    )
    assert new_state_id
    state_select.select_option(new_state_id)
    expect(page.locator('.bonded-interaction-table tbody tr')).not_to_have_count(0)
    expect(page.locator('.bonded-interaction-table select[aria-label^="bonds "]')).to_have_count(0)
    expect(page.locator('.bonded-interaction-table input[aria-label*="length (nm)"]')).to_have_count(0)
    expect(page.locator('.bonded-interaction-table .bonded-readonly-parameter')).not_to_have_count(0)
    parameter = page.locator('.bonded-interaction-table input[type=number]').first
    parameter.fill('0.31')
    expect(page.get_by_role('button', name='Save as new state')).to_be_enabled()
    page.get_by_role('button', name='Save as new state').click()
    expect(page.locator('.bonded-state-select option')).to_have_count(4)
    assert first_state['state_id'] != second_state['state_id']
    assert errors == []
