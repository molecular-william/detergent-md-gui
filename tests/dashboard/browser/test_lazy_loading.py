"""Tab activation fetches only visible data and reuses unchanged catalogues."""
from urllib.parse import urlsplit

from playwright.sync_api import expect

from dashboard.execution.adapters import cg
from dashboard.models import mappings
from dashboard.models.bonded import states as bonded_states
from dashboard.models.mappings import context as mapping_context
from tests.dashboard.fixtures import physical_mapping


def test_lazy_tabs_reuse_catalogues_and_preserve_edits(dashboard, browser, live_page, monkeypatch):
    context = mapping_context.build_context(dashboard.paths.project_root / 'molecules', 'DDM')
    candidate = physical_mapping()
    candidate.update(molecule_id='DDM', molecule_snapshot=context['snapshot'])
    saved = mappings.save_draft(candidate)
    bonded_states.create(saved, 'Test state')
    monkeypatch.setattr(cg, 'readiness', lambda *a, **k: {'ready': False, 'checks': [], 'blockers': ['Test only']})
    owner = dashboard.coordinator
    owner.database().insert({'id':'123456abcdef','status':'completed','detergent':'DDM'})
    run = owner.RUNS/'123456abcdef'; run.mkdir(parents=True)
    (run/'figure.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    page, errors = live_page
    urls=[]
    page.on('request', lambda r: urls.append(urlsplit(r.url).path+'?'+urlsplit(r.url).query))
    page.goto(f'{live_page.base_url}/#runs')
    expect(page.locator('.job')).to_have_count(1)
    assert not any(u.startswith(('/api/mappings','/api/bonded-states','/api/molecules')) for u in urls)
    page.evaluate("window.tabEvents=[]; document.addEventListener('dashboard:tab', event => tabEvents.push(event.detail.id))")
    page.locator('.job-analysis summary').click()
    expect(page.locator('.figure-tabs [role=tab]')).to_have_count(1)
    for _ in range(2): page.evaluate('window.refreshJobs()')
    assert len([u for u in urls if '/figures?' in u]) == 1
    assert not any('/artifacts?' in u for u in urls)
    page.locator('#tab-new').click()
    expect(page.locator('#run-mapping option')).to_have_count(2)
    expect(page.locator('#run-bonded-state option')).to_have_count(2)
    expect(page.locator('#review-status')).not_to_have_text('Checking readiness…')
    # The catalogue is fetched once, scoped to the molecule the editor is bound to.
    assert [u for u in urls if u.startswith('/api/mappings?view=summary')] == ['/api/mappings?view=summary&molecule_id=DDM']
    assert urls.count('/api/bonded-states?view=summary') == 1
    # Keyboard and hash navigation have the same activation semantics.
    page.locator('#tab-new').press('ArrowRight')
    expect(page.locator('#mapping-editor-name')).to_have_value(saved['name'])
    page.locator('#mapping-editor-name').fill('Unsaved local edit')
    page.locator('#tab-bonded').click()
    expect(page.locator('.bonded-mapping-select')).to_have_value(saved['file'])
    page.evaluate("location.hash='mappings'")
    expect(page.locator('#mapping-editor-name')).to_have_value('Unsaved local edit')
    assert page.evaluate('tabEvents') == ['new', 'mappings', 'bonded', 'mappings']
    catalogues = [u for u in urls if u.startswith('/api/mappings?view=summary')]
    # Two catalogue questions exist: the editor's molecule-scoped one and the global
    # one another panel asks for. The round trip must refetch neither.
    assert sorted(catalogues) == ['/api/mappings?view=summary', '/api/mappings?view=summary&molecule_id=DDM'], catalogues
    assert urls.count('/api/bonded-states?view=summary') == 1
    assert urls.count('/api/mappings/'+saved['file']+'?') == 1
    assert not errors
    # A fresh direct link to Bonded does not construct the mapping editor.
    other = browser.new_page()
    other.goto(f'{live_page.base_url}/#bonded')
    expect(other.locator('.bonded-mapping-select')).to_have_value(saved['file'])
    expect(other.locator('.bonded-plot .plotly')).to_be_visible()
    expect(other.locator('#mapping-bead-rows tr')).to_have_count(0)


def test_shared_cache_rejects_stale_refill_after_invalidation(dashboard, live_page):
    dashboard.coordinator.database().replace([])
    page = live_page.page
    page.goto(f'{live_page.base_url}/#runs')
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
    page.goto(f'{live_page.base_url}/#new')
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
