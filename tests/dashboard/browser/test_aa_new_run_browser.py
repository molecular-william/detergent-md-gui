"""New AA form state and payload, with simulation requests intercepted."""
import json
import threading
from unittest.mock import patch

from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from dashboard.app import default_coordinator as web
from tests.dashboard.fixtures import QuietHandler


def test_aa_form_preserves_cg_choices_and_reference_settings(tmp_path):
    aa = dict(aa_nvt_ps=100, aa_npt_ps=1000, aa_production_ps=10000,
              temperature_k=300, pressure_bar=1, output_interval_ps=10,
              box_padding_nm=1.5, aa_seed=12345)
    defaults = aa | dict(cg_equil_ps=10, cg_production_ps=50, sasa_probe_nm=.191, cg_seed=12345)
    inherited = aa | dict(temperature_k=310, aa_production_ps=500, output_interval_ps=5)
    with patch.object(web, 'DATA', tmp_path/'jobs.sqlite3'), patch.object(web, 'RUNS', tmp_path/'runs'), patch.dict(web.app.config, DISABLE_COORDINATOR=True):
        web.database().replace([])
        server = make_server('127.0.0.1', 0, web.app, request_handler=QuietHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(channel='chrome', headless=True)
                page = browser.new_page(viewport={'width':1440, 'height':1000})
                errors = []; submissions = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.route('**/api/defaults?*', lambda r: r.fulfill(json={'values':defaults,'sources':{'AA':'CHARMM AA protocol v1'},'profile':'draft-smoke'}))
                page.route('**/api/readiness?*', lambda r: r.fulfill(json={'ready':True,'checks':[],'blockers':[]}))
                page.route('**/api/references*', lambda r: r.fulfill(json={'references':[{'id':'111111111111','label':'Shared AA source','run_type':'aa_only','settings':inherited}]}))
                page.add_init_script("localStorage.setItem('ddm.form', JSON.stringify({run_type:'aa_cg',profile:'draft-smoke',molecule_id:'DDM',cg_production_ps:'250',temperature_k:'305'}))")
                url = f'http://127.0.0.1:{server.server_port}/'
                # Initial molecule loading refreshes the reference selector after defaults.
                # Wait for that request before selecting a reference to test inheritance.
                with page.expect_response(lambda response: '/api/references?molecule_id=DDM' in response.url):
                    page.goto(url+'#new')
                expect(page.locator('[name=aa_nvt_ps]')).to_have_value('100')
                page.locator('[name=reference_run_id]').select_option('111111111111')
                expect(page.locator('[name=temperature_k]')).to_have_value('310')
                expect(page.locator('[name=temperature_k]')).to_be_disabled()
                expect(page.locator('[name=output_interval_ps]')).to_be_disabled()
                page.locator('[name=reference_run_id]').select_option('')
                expect(page.locator('[name=temperature_k]')).to_have_value('305')
                expect(page.locator('[name=temperature_k]')).to_be_enabled()
                page.locator('#run-type').select_option('aa_only')
                expect(page.locator('#cg-inputs')).to_be_hidden()
                expect(page.locator('#start-run')).to_be_enabled()
                saved = json.loads(page.evaluate("localStorage.getItem('ddm.form')"))
                assert saved['cg_production_ps'] == '250'
                assert saved['profile'] == 'draft-smoke'
                def submit(route):
                    submissions.append(route.request.post_data_json)
                    route.fulfill(status=201, json={'id':'222222222222'})
                page.route(url, submit)
                page.locator('#start-run').click()
                expect(page.locator('#notice')).to_have_text('Run queued.')
                assert submissions[0]['run_type'] == 'aa_only'
                assert submissions[0]['aa_nvt_ps'] == '100'
                assert 'mapping_candidate' not in submissions[0]
                assert 'cg_production_ps' not in submissions[0]
                page.locator('#tab-new').click()
                page.locator('#run-type').select_option('aa_cg')
                expect(page.locator('[name=cg_production_ps]')).to_have_value('250')
                page.screenshot(path='/tmp/aa-new-run-desktop.png', full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path='/tmp/aa-new-run-mobile.png', full_page=True)
                assert not errors, errors
                browser.close()
        finally:
            server.shutdown(); thread.join(5); server.server_close()
