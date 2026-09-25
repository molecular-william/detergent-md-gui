"""Browser acceptance test. Requires installed Playwright + Chromium."""
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server, WSGIRequestHandler
from dashboard.app import default_coordinator as web
from dashboard.models import mappings


class QuietHandler(WSGIRequestHandler):
    def log_request(self, *args):
        pass


class DashboardBrowserTests(unittest.TestCase):
    def test_tab_switch_preserves_form_and_mapping_edits(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / 'dashboard').mkdir()
            with patch.object(web, 'DATA', root/'dashboard/jobs.sqlite3'), patch.object(web, 'RUNS', root/'dashboard/runs'), patch.object(web, 'WORKERS', {}), patch.object(mappings, 'storage_root', return_value=root/'drafts'):
                candidate = mappings.save_draft(mappings.automatic_candidate(mappings.molecule(), 'DDM'))
                job = {'id': '123456abcdef', 'detergent': 'DDM', 'method': 'fast_forward', 'status': 'failed', 'stage': 'AA reference', 'created': web.now(), 'error': 'Missing mapping'}
                web.database().replace([job])
                server = make_server('127.0.0.1', 0, web.app, request_handler=QuietHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
                try:
                    with sync_playwright() as p:
                        browser = p.chromium.launch(channel='chrome', headless=True)
                        page = browser.new_page(viewport={'width': 1280, 'height': 900})
                        errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
                        page.clock.install()
                        page.goto(f'http://127.0.0.1:{server.server_port}')
                        expect(page.locator('.job-title')).to_contain_text('DDM')
                        page.locator('.job summary').nth(1).click()
                        page.get_by_role('tab', name='New run', exact=True).click()
                        page.locator('[name=label]').fill('My unsent run')
                        page.locator('#method').select_option('bartender')
                        web.database().update(job['id'], error='Updated failure explanation')
                        page.get_by_role('tab', name='Runs', exact=True).click()
                        expect(page.locator('.job-error')).to_have_text('Updated failure explanation')
                        page.get_by_role('tab', name='New run', exact=True).click()
                        expect(page.locator('[name=label]')).to_have_value('My unsent run')
                        expect(page.locator('#method')).to_have_value('bartender')
                        expect(page.locator('.job').first.locator('details').filter(has_text='Commands')).to_have_attribute('open', '')
                        page.get_by_role('tab', name='CG mappings', exact=True).click()
                        expect(page.locator('#mapping-editor-status')).to_contain_text('loaded')
                        page.locator('#generate-automatic').click()
                        expect(page.locator('#mapping-bead-rows tr')).not_to_have_count(0)
                        page.locator('#mapping-editor-name').fill('My edited mapping')
                        duplicate_atoms = ' '.join(map(str, candidate['beads'][0]['atoms'] + [candidate['beads'][1]['atoms'][0]]))
                        page.locator('#mapping-bead-rows input[aria-label$=" atoms"]').first.fill(duplicate_atoms)
                        page.clock.fast_forward(500)
                        expect(page.locator('#mapping-validation-issues')).to_contain_text('Repeated atom assignments')
                        page.get_by_role('tab', name='Runs', exact=True).click()
                        expect(page.locator('.job').first.locator('details').filter(has_text='Commands')).to_have_attribute('open', '')
                        page.get_by_role('tab', name='CG mappings', exact=True).click()
                        expect(page.locator('#mapping-editor-name')).to_have_value('My edited mapping')
                        self.assertEqual(errors, [])
                        browser.close()
                finally:
                    server.shutdown(); thread.join(3)

    def test_clone_resume_and_analysis_controls(self):
        from dashboard import files
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root/'dashboard/runs').mkdir(parents=True)
            with patch.object(web, 'ROOT', root), patch.object(web, 'DATA', root/'dashboard/jobs.sqlite3'), patch.object(web, 'RUNS', root/'dashboard/runs'), patch.object(web, 'WORKERS', {}), patch.object(web, 'ANALYSIS_WORKERS', {}):
                jobs = [{'id': f'{i:012x}', 'label': f'Run {i}', 'detergent': 'DDM', 'method': 'fast_forward', 'profile': 'draft-smoke', 'status': 'completed', 'created': web.now(), 'settings': {'temperature_k': 310}} for i in range(22)]
                web.database().replace(jobs)
                for job in jobs:
                    run = web.run_path(job); run.mkdir()
                    files.atomic_json(run/'manifest.json', {'stages': [], 'input_snapshot_sha256': {'input.txt': 'hash'}})
                    (run/'result.gro').write_text('artifact')
                newest = jobs[-1]
                worker = web.Worker(); web.ANALYSIS_WORKERS[(newest['id'], 'task')] = worker
                web.database().update(newest['id'], analyses=[{'id': 'task', 'kind': 'stability', 'status': 'running', 'directory': 'analyses/stability/test'}])
                server = make_server('127.0.0.1', 0, web.app, request_handler=QuietHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
                try:
                    with sync_playwright() as p:
                        browser = p.chromium.launch(channel='chrome', headless=True)
                        page = browser.new_page(); errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
                        page.goto(f'http://127.0.0.1:{server.server_port}')
                        first = page.locator('.job').first
                        first.locator('.job-analysis summary').click()
                        first.get_by_role('button', name='Cancel analysis', exact=True).click()
                        expect(first.locator('.analysis-tasks')).to_contain_text('cancelling')
                        self.assertTrue(worker.cancel.is_set()); web.ANALYSIS_WORKERS.clear()
                        first.locator('.job-clone').click()
                        expect(page.locator('#new')).to_be_visible()
                        expect(page.locator('[name=temperature_k]')).to_have_value('310')
                        expect(page.locator('[name=clone_of]')).to_have_value(newest['id'])
                        page.get_by_role('tab', name='Runs', exact=True).click()
                        expect(first.locator('.resume-stage')).to_have_value('AA reference')
                        self.assertEqual(errors, [])
                        browser.close()
                finally:
                    server.shutdown(); thread.join(3)

    def test_mapping_editor_clear_all_removes_local_assignments(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / 'dashboard').mkdir()
            with patch.object(web, 'DATA', root/'dashboard/jobs.sqlite3'), patch.object(web, 'RUNS', root/'dashboard/runs'), patch.object(web, 'WORKERS', {}), patch.object(mappings, 'storage_root', return_value=root/'drafts'):
                server = make_server('127.0.0.1', 0, web.app, request_handler=QuietHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
                try:
                    with sync_playwright() as p:
                        browser = p.chromium.launch(channel='chrome', headless=True)
                        page = browser.new_page(viewport={'width': 1280, 'height': 900})
                        page.goto(f'http://127.0.0.1:{server.server_port}/#mappings')
                        page.get_by_role('tab', name='CG mappings', exact=True).click()
                        page.locator('#generate-automatic').click()
                        expect(page.locator('#mapping-bead-rows tr')).not_to_have_count(0)
                        page.on('dialog', lambda dialog: dialog.accept())
                        page.locator('#clear-all-mapping').click()
                        expect(page.locator('#mapping-bead-rows tr')).to_have_count(0)
                        browser.close()
                finally:
                    server.shutdown(); thread.join(3)

    def test_mapping_editor_disables_save_for_an_identical_saved_mapping(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / 'dashboard').mkdir()
            with patch.object(web, 'DATA', root/'dashboard/jobs.sqlite3'), patch.object(web, 'RUNS', root/'dashboard/runs'), patch.object(web, 'WORKERS', {}), patch.object(mappings, 'storage_root', return_value=root/'drafts'):
                server = make_server('127.0.0.1', 0, web.app, request_handler=QuietHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
                try:
                    with sync_playwright() as p:
                        browser = p.chromium.launch(channel='chrome', headless=True)
                        page = browser.new_page(viewport={'width': 1280, 'height': 900})
                        page.goto(f'http://127.0.0.1:{server.server_port}/#mappings')
                        page.get_by_role('tab', name='CG mappings', exact=True).click()
                        expect(page.locator('#mapping-editor-status')).to_contain_text('loaded')
                        page.locator('#generate-automatic').click()
                        expect(page.locator('#mapping-bead-rows tr')).not_to_have_count(0)
                        expect(page.locator('#save-mapping-editor')).to_be_enabled()
                        page.locator('#save-mapping-editor').click()
                        expect(page.locator('#save-mapping-editor')).to_be_disabled()
                        browser.close()
                finally:
                    server.shutdown(); thread.join(3)


if __name__ == '__main__':
    unittest.main()
