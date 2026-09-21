"""Browser proof for mapping-filtered bonded states and revision controls."""
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


def test_bonded_workspace_filters_states_and_exposes_revision_modes(tmp_path):
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
            expect(page.get_by_role('button', name='Revise selected state')).to_be_visible()
            assert first_state['state_id'] != second_state['state_id']
            assert errors == []
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=3)
