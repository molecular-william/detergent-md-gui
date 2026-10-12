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
    page.goto(f'{live_page.base_url}/detergent-validation/bond-interactions')
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
    page.locator('.bonded-interaction-table tbody tr').first.wait_for(timeout=30000)
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
    page.locator('.bonded-interaction-table tbody tr').first.wait_for(timeout=30000)
    expect(page.locator('.bonded-interaction-table tbody tr')).not_to_have_count(0)
    expect(page.locator('.bonded-interaction-table select[aria-label^="bonds "]')).to_have_count(0)
    expect(page.locator('.bonded-interaction-table input[aria-label*="length (nm)"]')).to_have_count(0)
    page.locator('.bonded-interaction-table .bonded-readonly-parameter').first.wait_for(timeout=30000)
    expect(page.locator('.bonded-interaction-table .bonded-readonly-parameter')).not_to_have_count(0)
    parameter = page.locator('.bonded-interaction-table input[type=number]').first
    parameter.fill('0.31')
    expect(page.get_by_role('button', name='Save as new state')).to_be_enabled()
    page.get_by_role('button', name='Save as new state').click()
    expect(page.locator('.bonded-state-select option')).to_have_count(4)
    assert first_state['state_id'] != second_state['state_id']
    assert errors == []


def test_the_diagram_draws_the_candidates_own_molecule_and_not_the_packaged_one(dashboard, live_page):
    """A non-DDM candidate was drawn on the packaged DDM atoms, so its geometry was another molecule's.

    The panel read its atoms once, from the workspace default -- the packaged DDM reference -- and used that reading
    for every candidate. A candidate mapping Sucrose's atoms was therefore drawn on DDM's 81: the same atom id is a
    different atom in a different molecule, so the bead cloud came out 4.4x too long on one axis and 0.4x too short
    on another. That reads as a scaling error and is not one -- and it is why sucrose, trehalose and maltose all drew
    as the identical cloud.

    The assertion is against the molecule's own geometry, computed here from the context the panel is given, so it
    holds for any molecule instead of pinning one molecule's numbers.
    """
    from dashboard.models.mappings import context as mapping_context

    context = dashboard.client.get('/api/mappings/context?molecule_id=Sucrose').get_json()['context']
    candidate = mappings.automatic_candidate(mapping_context.as_structure(context), 'Sucrose')
    candidate['molecule_id'] = 'Sucrose'
    candidate['molecule_snapshot'] = context['snapshot']
    saved = mappings.save_draft(candidate)

    # Every physical bead at the mean of the atoms it maps, in this molecule's own coordinates: what the diagram
    # would draw if it were drawing the molecule the candidate names.
    atoms = {atom['id']: atom['xyz'] for atom in context['atoms']}
    centres = []
    for bead in saved['beads']:
        if bead.get('virtual_site'):
            continue
        points = [atoms[atom_id] for atom_id in (bead.get('atoms') or []) if atom_id in atoms]
        if points:
            centres.append([sum(point[axis] for point in points) / len(points) for axis in range(3)])
    assert centres, 'the candidate maps no physical bead, so there is no geometry to check'
    expected = [round(max(centre[axis] for centre in centres) - min(centre[axis] for centre in centres), 3)
                for axis in range(3)]

    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/bond-interactions')
    page.locator('.bonded-mapping-select').select_option(saved['file'])
    plot = page.locator('.bonded-plot')
    expect(plot.locator('.plotly')).to_be_visible()

    drawn = plot.evaluate("""(el) => {
      const beads = el.data.filter(trace => trace.meta === 'bead');
      const span = axis => {
        const values = beads.flatMap(trace => trace[axis] || []);
        return Math.round((Math.max(...values) - Math.min(...values)) * 1000) / 1000;
      };
      return [span('x'), span('y'), span('z')];
    }""")
    for axis, want in enumerate(expected):
        assert abs(drawn[axis] - want) < 0.05, (
            f'axis {axis}: the diagram draws {drawn[axis]} nm where Sucrose itself spans {want} nm '
            f'(drawn {drawn}, the molecule its own {expected})')
    assert errors == []
