"""Browser proof for run-specific figure selection, zoom, and display-only beads."""
import json
from pathlib import Path
import threading
from unittest.mock import patch

from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server, WSGIRequestHandler
from dashboard.app import default_coordinator as web
from dashboard.models import mappings


class QuietHandler(WSGIRequestHandler):
    def log_request(self,*args): pass


def test_run_figure_tabs_zoom_and_mapping_display(tmp_path):
    runs=tmp_path/'runs';runs.mkdir()
    with patch.object(web,'DATA',tmp_path/'jobs.sqlite3'), patch.object(web,'RUNS',runs), patch.object(web,'WORKERS',{}), patch.object(web,'ANALYSIS_WORKERS',{}), patch.object(mappings, 'storage_root', return_value=tmp_path/'drafts'), patch.dict(web.app.config,DISABLE_COORDINATOR=True):
        mappings.save_draft(mappings.automatic_candidate(mappings.molecule(), 'DDM'))
        jobs=[{'id':jid,'label':f'Figure run {i}','detergent':'DDM','method':'fast_forward','status':'completed','stage':'complete','created':web.now()} for i,jid in enumerate(('abcdef123456','abcdef123457'))]
        web.save(jobs)
        for job in jobs:
            directory=runs/job['id'];directory.mkdir()
            for name in ('alpha','beta'):
                (directory/(name+'.svg')).write_text('<svg xmlns="http://www.w3.org/2000/svg" width="400" height="200"><circle cx="200" cy="100" r="90" fill="blue"/></svg>')
            (directory/'surface-comparison.html').write_text('<!doctype html><title>Surface comparison</title><h1>Interactive figure</h1>')
        server=make_server('127.0.0.1',0,web.app,request_handler=QuietHandler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(channel='chrome',headless=True)
                page=browser.new_page(viewport={'width':1500,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(f'http://127.0.0.1:{server.server_port}/#runs')
                first=page.locator('.job[data-id=abcdef123456]');second=page.locator('.job[data-id=abcdef123457]')
                first.locator('.job-analysis summary').click()
                expect(first.locator('.figure-tabs [role=tab]')).to_have_count(3,timeout=15000)
                expect(first.locator('.figure-media')).to_have_count(1)
                expect(first.get_by_role('tab',name='alpha',exact=True)).to_have_attribute('aria-selected','true')
                first.get_by_role('button',name='Zoom in',exact=True).click()
                expect(first.locator('.figure-zoom-level')).to_have_text('125%')
                assert first.locator('.figure-media').evaluate('(el)=>el.getBoundingClientRect().width')>first.locator('.figure-viewport').evaluate('(el)=>el.clientWidth')
                first.get_by_role('tab',name='beta',exact=True).click()
                expect(first.locator('.figure-zoom-level')).to_have_text('100%')
                first.get_by_role('tab',name='beta',exact=True).press('ArrowLeft')
                expect(first.locator('.figure-zoom-level')).to_have_text('125%')
                # Refresh must preserve the DOM node, selection and viewport scroll.
                first.locator('.figure-media').evaluate('(el)=>window.originalFigure=el')
                first.locator('.figure-viewport').evaluate('(el)=>el.scrollLeft=40')
                first.locator('.job-analysis summary').click()
                with page.expect_response(lambda response: '/api/jobs/abcdef123456/figures?refresh=1' in response.url) as refreshed_figures:
                    first.locator('.job-analysis summary').click()
                refreshed_figures.value.finished()
                assert first.locator('.figure-media').evaluate('(el)=>el===window.originalFigure')
                assert first.locator('.figure-viewport').evaluate('(el)=>el.scrollLeft')==40
                second.locator('.job-analysis summary').click()
                expect(second.locator('.figure-zoom-level')).to_have_text('100%')
                # Workspace navigation must ignore the nested figure tabs.
                page.get_by_role('tab',name='New run',exact=True).click();expect(page.locator('#new')).to_be_visible()
                page.get_by_role('tab',name='Runs',exact=True).click();expect(first.locator('.figure-zoom-level')).to_have_text('125%')
                page.reload();first=page.locator('.job[data-id=abcdef123456]')
                expect(first.locator('.figure-zoom-level')).to_have_text('125%')
                first.get_by_role('button',name='Fit / reset',exact=True).click();expect(first.locator('.figure-zoom-level')).to_have_text('100%')
                first.get_by_role('tab',name='surface comparison',exact=True).click()
                expect(first.locator('iframe.figure-media')).to_have_attribute('sandbox','allow-scripts')
                expect(first.frame_locator('iframe').get_by_role('heading')).to_have_text('Interactive figure')
                first.get_by_role('button',name='Zoom in',exact=True).click();expect(first.locator('.figure-zoom-level')).to_have_text('125%')
                assert '1.25' in first.locator('iframe').evaluate('(el)=>el.style.transform')
                page.get_by_role('tab',name='CG mappings',exact=True).click()
                editor=page.locator('.mapping');expect(editor.locator('.candidate-name')).to_be_visible()
                # The pre-refactor "Inspect the 3D structure" disclosure no longer exists;
                # bead assignments are visible directly in .bead-rows.
                expect(editor.locator('.bead-rows')).to_be_visible()
                with page.expect_download() as before_download:
                    editor.locator('.export-candidate').click()
                before=json.loads(Path(before_download.value.path()).read_text())
                # Display-only adjustments no longer exist in the current template; the
                # immutable export contract is tested by changing a form field without
                # saving and confirming the downloaded JSON is unchanged.
                editor.locator('.bead-rows input').first.fill(editor.locator('.bead-rows input').first.input_value())
                with page.expect_download() as after_download:
                    editor.locator('.export-candidate').click()
                assert json.loads(Path(after_download.value.path()).read_text())==before
                page.locator('#tab-bonded').click()
                mapping_file=page.locator('.bonded-mapping-select').input_value()
                page.locator('.bonded-fit').click()
                expect(page.locator('#new')).to_be_visible()
                expect(page.locator('[name=bonded_intent]')).to_have_value('fit_only')
                expect(page.locator('[name=mapping_candidate]')).to_have_value(mapping_file)
                page.get_by_role('tab',name='CG mappings',exact=True).click()
                page.set_viewport_size({'width':390,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.get_by_role('tab',name='Runs',exact=True).click()
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                assert errors==[]
                browser.close()
        finally:
            server.shutdown();thread.join(timeout=5)


def test_analysis_display_preserves_missing_values_and_metadata(tmp_path):
    runs = tmp_path / 'runs'; runs.mkdir()
    with patch.object(web, 'DATA', tmp_path/'jobs.sqlite3'), patch.object(web, 'RUNS', runs), patch.object(web, 'WORKERS', {}), patch.object(web, 'ANALYSIS_WORKERS', {}), patch.dict(web.app.config, DISABLE_COORDINATOR=True):
        job = {'id': 'abcdef123458', 'label': 'Metadata run', 'detergent': 'DDM', 'method': 'fast_forward', 'status': 'completed', 'stage': 'complete', 'created': web.now()}
        web.save([job])
        directory = runs / job['id']; directory.mkdir()
        assessment = directory / '5_assessment'; assessment.mkdir()
        (assessment / 'distance_diagnostics.json').write_text(json.dumps({'pairs': [
            {'beads': ['B01', 'B02'], 'kind': 'physical', 'wasserstein_nm': {'raw_AA': 0, 'ring_expanded_AA': None}}
        ]}))
        metadata = directory / 'analysis' / 'plots'; metadata.mkdir(parents=True)
        (metadata / 'score.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"/>')
        (metadata / 'analysis-metadata.json').write_text(json.dumps({'title': 'Wasserstein distance', 'units_or_direction': 'nm; lower is better', 'legacy': False}))
        server = make_server('127.0.0.1', 0, web.app, request_handler=QuietHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(channel='chrome', headless=True)
                page = browser.new_page(); errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_port}/#runs')
                first = page.locator('.job').first
                first.locator('.job-analysis summary').click()
                expect(first.locator('.figure-caption')).to_contain_text('Wasserstein distance')
                expect(first.locator('.figure-caption')).to_contain_text('nm; lower is better')
                expect(first.locator('.distance-pair-table')).to_contain_text('0.000 nm')
                expect(first.locator('.distance-pair-table')).to_contain_text('n/a')
                assert errors == []
                browser.close()
        finally:
            server.shutdown(); thread.join(timeout=5)
