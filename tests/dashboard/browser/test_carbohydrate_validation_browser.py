from pathlib import Path
import threading

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import WSGIRequestHandler, make_server

from dashboard.app import create_app
from dashboard.paths import Paths


class QuietHandler(WSGIRequestHandler):
    def log_request(self, *args):
        pass


def test_mapping_tab_shows_carbohydrate_validation_controls(tmp_path):
    app = create_app(Paths(project_root=Path(__file__).resolve().parents[3], workspace=tmp_path / 'workspace'),
                     {'TESTING': True, 'DISABLE_COORDINATOR': True})
    server = make_server('127.0.0.1', 0, app, request_handler=QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='chrome', headless=True)
            page = browser.new_page()
            page.goto(f'http://127.0.0.1:{server.server_port}/#mappings')
            page.get_by_role('tab', name='CG mappings', exact=True).click()
            expect(page.locator('#validation-representation')).to_have_count(1)
            expect(page.locator('#validation-tier')).to_have_count(1)
            expect(page.locator('#launch-carbohydrate-validation')).to_be_disabled()
            browser.close()
    finally:
        server.shutdown()
        thread.join(3)
