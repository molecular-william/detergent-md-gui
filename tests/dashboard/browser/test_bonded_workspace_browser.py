"""Browser proof for mapping-filtered bonded states and the 3D editor."""
import threading

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import WSGIRequestHandler, make_server

from dashboard.app import create_app
from dashboard.models import bonded_states, mappings
from dashboard.paths import Paths, use
from tests.dashboard.fixtures import PROJECT_ROOT, physical_mapping


class QuietHandler(WSGIRequestHandler):
    def log_request(self, *args):
        pass


def test_bonded_workspace_filters_states_and_creates_a_new_state_from_two_beads(tmp_path):
    selected = Paths(project_root=PROJECT_ROOT, workspace=tmp_path)
    app = create_app(selected, {'TESTING': True, 'DISABLE_COORDINATOR': True})
    with use(selected):
        first = mappings.save_draft(mappings.automatic_candidate(mappings.molecule(), 'DDM'))
        second_data = mappings.automatic_candidate(mappings.molecule(), 'DDM')
        second_data['name'] = 'Second mapping'
        second = mappings.save_draft(second_data)
        first_state = bonded_states.create(first, 'First state', topology='[ moleculetype ]\n[ atoms ]', status='complete')
        second_state = bonded_states.create(second, 'Second state', topology='[ moleculetype ]\n[ atoms ]', status='complete')

    server = make_server('127.0.0.1', 0, app, request_handler=QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='chrome', headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{server.server_port}/#bonded')
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
            names = plot.evaluate('(el) => el.data[0].customdata.slice(0, 4)')
            assert len(names) == 4
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
            parameter = page.locator('.bonded-interaction-table input[type=number]').first
            parameter.fill('0.31')
            expect(page.get_by_role('button', name='Save as new state')).to_be_enabled()
            page.get_by_role('button', name='Save as new state').click()
            expect(page.locator('.bonded-state-select option')).to_have_count(4)
            assert first_state['state_id'] != second_state['state_id']
            assert errors == []
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=3)
