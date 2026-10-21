"""Tab activation fetches only visible data and reuses unchanged catalogues."""
from urllib.parse import urlsplit

from playwright.sync_api import expect

from dashboard.execution.adapters import cg
from dashboard.models import mappings
from dashboard.models.mappings import context as mapping_context
from tests.dashboard.support import physical_mapping


def test_lazy_tabs_reuse_catalogues_and_preserve_edits(dashboard, browser, live_page, monkeypatch):
    context = mapping_context.build_context(dashboard.paths.project_root / 'molecules', 'DDM')
    candidate = physical_mapping()
    candidate.update(molecule_id='DDM', molecule_snapshot=context['snapshot'])
    saved = mappings.save_draft(candidate)
    monkeypatch.setattr(cg, 'readiness', lambda *a, **k: {'ready': False, 'checks': [], 'blockers': ['Test only']})
    owner = dashboard.coordinator
    owner.database().insert({'id':'123456abcdef','status':'completed','detergent':'DDM'})
    run = owner.RUNS/'123456abcdef'; run.mkdir(parents=True)
    (run/'figure.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    page, errors = live_page
    urls=[]
    page.on('request', lambda r: urls.append(urlsplit(r.url).path+'?'+urlsplit(r.url).query))
    page.goto(f'{live_page.base_url}/detergent-validation/runs')
    expect(page.locator('.job')).to_have_count(1)
    assert not any(u.startswith(('/api/mappings','/api/molecules')) for u in urls)
    page.evaluate("window.tabEvents=[]; document.addEventListener('dashboard:tab', event => tabEvents.push(event.detail.id))")
    page.locator('.job-analysis summary').click()
    expect(page.locator('.figure-tabs [role=tab]')).to_have_count(1)
    for _ in range(2): page.evaluate('window.refreshJobs()')
    assert len([u for u in urls if '/figures?' in u]) == 1
    assert not any('/artifacts?' in u for u in urls)
    page.locator('#tab-new').click()
    expect(page.locator('#run-mapping option')).to_have_count(2)
    # The panel used to offer a bonded-state select here, filled from a flat store that no longer exists. Fitting is
    # the AA-CG run type's own (D1), so the control is gone and the page asks nothing bonded-shaped at all: the only
    # bonded question left in the dashboard is the CG Bond Interactions panel's, and it carries a mapping's content hash.
    expect(page.locator('#run-bonded-state')).to_have_count(0)
    expect(page.locator('#review-status')).not_to_have_text('Checking readiness…')
    # The catalogue is fetched once, scoped to the molecule the editor is bound to.
    assert [u for u in urls if u.startswith('/api/mappings?view=summary')] == ['/api/mappings?view=summary&molecule_id=DDM']
    # Returning to the editor keeps what was typed, and the hash activation below reaches the same panel.
    # Arrow-key activation is covered in test_tab_layout_browser, where the order is the rail's own.
    page.locator('#tab-mappings').click()
    expect(page.locator('#mapping-editor-name')).to_have_value(saved['name'])
    page.locator('#mapping-editor-name').fill('Unsaved local edit')
    page.locator('#tab-bonded').click()
    expect(page.locator('.bonded-mapping-select')).to_have_value(saved['file'])
    # Every one of those clicks switched in place, which is what the tab links are for: the assertion belongs here,
    # before anything navigates. It used to sit after a `location.hash` write, which was the old way to reach a
    # panel; that write is a legacy fragment now, so following it *replaces* the document and takes this record,
    # the typed text, and the whole point of the assertion with it. The last click above already proves the panel
    # is reachable, and the direct-URL path is proved further down by a second page.
    assert page.evaluate('tabEvents') == ['new', 'mappings', 'bonded']
    catalogues = [u for u in urls if u.startswith('/api/mappings?view=summary')]
    # Two catalogue questions exist: the editor's molecule-scoped one and the global
    # one another panel asks for. The round trip must refetch neither.
    assert sorted(catalogues) == ['/api/mappings?view=summary', '/api/mappings?view=summary&molecule_id=DDM'], catalogues
    # The Bonded workspace asks its own question about the model, keyed by the mapping it drew. The flat
    # bonded-state list it used to read here is gone: a mapping's bonded states became its parameterization's
    # revisions (D1), and the panel reads them off `/api/bonded-parameterizations` by content hash.
    assert not [u for u in urls if u.startswith('/api/bonded-states')], urls
    records = [u for u in urls if u.startswith('/api/bonded-parameterizations?')]
    assert records, urls
    assert all('content_hash=' in url for url in records), records
    assert urls.count('/api/mappings/'+saved['file']+'?') == 1
    assert not errors
    # A fresh direct link to Bonded does not construct the mapping editor.
    other = browser.new_page()
    other.goto(f'{live_page.base_url}/detergent-validation/bond-interactions')
    expect(other.locator('.bonded-mapping-select')).to_have_value(saved['file'])
    expect(other.locator('.bonded-plot .plotly')).to_be_visible()
    expect(other.locator('#mapping-bead-rows tr')).to_have_count(0)


def test_shared_cache_rejects_stale_refill_after_invalidation(dashboard, live_page):
    dashboard.coordinator.database().replace([])
    page = live_page.page
    page.goto(f'{live_page.base_url}/detergent-validation/runs')
    result = page.evaluate("""async () => {
        const shared = await import('/static/js/shared.js');
        let release;
        const pending = shared.loadOnce('/probe', () => new Promise(resolve => { release = resolve; }));
        await Promise.resolve(); // Let the deferred loader begin.
        shared.invalidateResource('/probe');
        release('stale');
        await pending;
        let loads = 0;
        const fresh = await shared.loadOnce('/probe', async () => { loads += 1; return 'fresh'; });
        try { await shared.loadOnce('/rejected', async () => { throw new Error('failed'); }); } catch {}
        const retried = await shared.loadOnce('/rejected', async () => 'retried');
        return {fresh, loads, retried};
    }""")
    assert result == {'fresh': 'fresh', 'loads': 1, 'retried': 'retried'}


def test_readiness_debounces_changes_and_ignores_cancelled_response(dashboard, live_page):
    dashboard.coordinator.database().replace([])
    page, errors = live_page
    page.clock.install()
    # Control only readiness responses; retain real form activation and
    # the API helper's AbortSignal so late responses can be exercised.
    page.add_init_script("""(() => {
        const originalFetch = window.fetch;
        window.readinessRequests = [];
        window.fetch = (url, options) => {
            if (!String(url).startsWith('/api/readiness?')) return originalFetch(url, options);
            return new Promise(resolve => readinessRequests.push({url, signal: options.signal,
                reply: ready => resolve(new Response(JSON.stringify({ready, checks: [], blockers: ready ? [] : ['Latest check blocked']}),
                    {headers: {'Content-Type': 'application/json'}}))}));
        };
    })()""")
    page.goto(f'{live_page.base_url}/detergent-validation/new-run')
    expect(page.locator('#new')).to_have_attribute('aria-busy', 'false')
    page.clock.fast_forward(200)
    page.wait_for_function('readinessRequests.length === 1')
    page.locator('#method').select_option('bartender')
    page.locator('#method').select_option('fast_forward')
    page.clock.fast_forward(200)
    page.wait_for_function('readinessRequests.length === 2')
    assert page.evaluate('readinessRequests[0].signal.aborted')
    page.evaluate('readinessRequests[1].reply(false)')
    expect(page.locator('#launch-blocker')).to_have_text('Latest check blocked')
    page.evaluate('readinessRequests[0].reply(true)')
    expect(page.locator('#start-run')).to_be_disabled()
    expect(page.locator('#launch-blocker')).to_have_text('Latest check blocked')
    page.locator('#method').select_option('bartender')
    page.clock.fast_forward(200)
    page.wait_for_function('readinessRequests.length === 3')
    page.locator('#tab-runs').click()
    assert page.evaluate('readinessRequests[2].signal.aborted')
    page.evaluate('readinessRequests[2].reply(true)')
    expect(page.locator('#start-run')).to_be_disabled()
    assert errors == []
