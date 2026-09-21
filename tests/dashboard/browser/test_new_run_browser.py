"""New run directory selection against the real API; simulation worker disabled."""
from tests.dashboard.fixtures import PROJECT_ROOT
import json
from pathlib import Path
import shutil
import threading
from unittest.mock import patch

from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from dashboard.app import default_coordinator as web
from dashboard.execution import workflow
from tests.dashboard.fixtures import QuietHandler


def test_directory_selection_supports_generic_aa_and_ddm_cg_pair(tmp_path):
    root=PROJECT_ROOT
    shutil.copytree(root/'molecules/DDM',tmp_path/'molecules/DDM')
    missing=tmp_path/'molecules/Incomplete'; missing.mkdir()
    shutil.copytree(root/'molecules/DDM',tmp_path/'molecules/Other')
    with patch.object(web,'ROOT',tmp_path), patch.object(web,'DATA',tmp_path/'jobs.sqlite3'), patch.object(web,'RUNS',tmp_path/'runs'), patch.object(web,'WORKERS',{}), patch.object(web,'ANALYSIS_WORKERS',{}), patch.dict(web.app.config,DISABLE_COORDINATOR=True), patch.object(workflow,'readiness',return_value={'ready':True,'checks':[],'blockers':[]}), patch.object(web,'run_job',lambda *args: None):
        web.save([])
        server=make_server('127.0.0.1',0,web.app,request_handler=QuietHandler)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(channel='chrome',headless=True)
                page=browser.new_page(viewport={'width':1440,'height':1000}); errors=[]
                page.on('pageerror',lambda error: errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_port}/#new')
                expect(page).to_have_title('Detergent MD · Laboratory')
                expect(page.locator('#molecule-directory')).to_be_visible()
                expect(page.locator('#molecule-directory')).to_have_value('DDM')
                expect(page.locator('#molecule-details')).to_contain_text('81 atoms')
                expect(page.locator('#molecule-details')).to_contain_text('PDB → GRO automatically')
                expect(page.locator('#molecule-details')).to_contain_text('metadata.json generated automatically')
                page.locator('#molecule-directory').select_option('Other')
                # Any valid molecule is now a candidate for the generic CG workflow; the
                # previous "No execution adapter" gate was removed in Phase 4.2. The CG
                # readiness panel reports the AA-reference prerequisite instead.
                expect(page.locator('#molecule-details')).to_contain_text('Input files consistent')
                expect(page.locator('#molecule-details')).not_to_contain_text('No execution adapter')
                page.reload()
                expect(page.locator('#molecule-directory')).to_have_value('Other')
                # A compatible non-DDM directory is now runnable through AA-only.
                page.locator('#run-type').select_option('aa_only')
                expect(page.locator('#cg-inputs')).to_be_hidden()
                expect(page.locator('#start-run')).to_be_enabled()
                with page.expect_response(lambda r: r.request.method=='POST' and r.url.endswith('/')) as response:
                    page.locator('#start-run').click()
                assert response.value.status==201, response.value.text()
                generic=web.load()[0]
                assert generic['run_type']=='aa_only' and generic['molecule_id']=='Other'
                assert not generic.get('mapping_snapshot')
                assert 'cg_production_ps' not in generic['settings']
                web.update_job(generic['id'],status='completed')
                web.WORKERS.clear()
                page.locator('#tab-new').click()
                page.locator('#run-type').select_option('aa_cg')
                expect(page.locator('#start-run')).to_be_disabled()
                page.locator('#molecule-directory').select_option('DDM')
                expect(page.locator('#start-run')).to_be_enabled()
                page.locator('[name=label]').fill('Directory selection test')
                source=page.locator('#molecule-panel').bounding_box()
                settings=page.locator('.run-settings').bounding_box()
                assert settings['x'] > source['x']+source['width']
                page.screenshot(path='/tmp/new-run-directory-desktop.png',full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                expect(page.locator('#molecule-directory')).to_be_visible()
                page.screenshot(path='/tmp/new-run-directory-mobile.png',full_page=True)
                with page.expect_response(lambda r: r.request.method=='POST' and r.url.endswith('/')) as response:
                    page.locator('#start-run').click()
                assert response.value.status==201, response.value.text()
                jobs=[job for job in web.load() if job['id']!=generic['id']]
                assert len(jobs)==2
                cg=next(job for job in jobs if job['run_type']=='aa_cg')
                aa=next(job for job in jobs if job['run_type']=='aa_only')
                assert cg['reference_run_id']==aa['id'] and cg['status']=='waiting'
                assert aa['molecule_id']==cg['molecule_id']=='DDM'
                assert set(aa['molecule_snapshot']['sha256'])=={'results/MMFF/lig1.pdb','results/MMFF/lig1.itp','metadata.json'}
                assert cg['label']=='Directory selection test'
                assert not errors, errors
                browser.close()
        finally:
            server.shutdown(); thread.join(timeout=3)
