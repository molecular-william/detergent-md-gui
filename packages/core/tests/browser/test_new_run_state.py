"""Saved clone state must not strand New run after a source is deleted; a stage's numbers are form state too."""
import json

from playwright.sync_api import expect


def test_a_changed_timestep_survives_a_reload(dashboard, live_page):
    """The stage editor's timestep persists like every other setting, and its facts line follows it."""
    dashboard.coordinator.database().replace([])
    page, errors = live_page
    page.route('**/api/readiness?*', lambda route: route.fulfill(json={'ready': True, 'checks': [], 'blockers': []}))
    # Seed once: an init script runs on every navigation, and a reload must keep what the form last saved.
    page.add_init_script("""if (!sessionStorage.seeded) {
        localStorage.setItem('ddm.form', JSON.stringify({run_type:'aa_only',molecule_id:'DDM'}));
        sessionStorage.seeded = '1';
    }""")
    page.goto(f'{live_page.base_url}/detergent-validation/new-run')

    expect(page.locator('[name=aa_nvt_dt_fs]')).to_have_value('2', timeout=30000)
    expect(page.locator('#stage-aa-nvt-facts')).to_have_text('100 ps · 2 fs · 50 000 steps · nstlist 20')
    page.locator('[name=aa_nvt_dt_fs]').fill('1')
    expect(page.locator('#stage-aa-nvt-facts')).to_have_text('100 ps · 1 fs · 100 000 steps · nstlist 20')

    page.reload()
    page.get_by_role('tab', name='New run', exact=True).click()
    expect(page.locator('[name=aa_nvt_dt_fs]')).to_have_value('1', timeout=30000)
    expect(page.locator('#stage-aa-nvt-facts')).to_have_text('100 ps · 1 fs · 100 000 steps · nstlist 20')
    assert errors == []


def test_new_run_recovers_deleted_clone_and_preserves_settings(dashboard, live_page):
    dashboard.coordinator.database().replace([])
    page, errors = live_page
    requests = []
    page.route('**/api/readiness?*', lambda route: route.fulfill(json={'ready':True,'checks':[],'blockers':[]}))
    # All job creation is intercepted; this test never starts a simulation.
    def record_submit(route):
        requests.append((route.request.url, route.request.post_data_json))
        route.fulfill(status=201, json={'id':'123456abcdef'})
    page.route('**/api/jobs/*/clone', record_submit)
    page.add_init_script("""if (!sessionStorage.seeded) {
        localStorage.setItem('ddm.form', JSON.stringify({clone_of:'fef0e530fd7a',label:'Preserved settings',profile:'draft-smoke',cg_production_ps:'200'}));
        sessionStorage.seeded='1';
    }""")
    url = f'{live_page.base_url}/'
    page.goto(url + '/detergent-validation/new-run')
    page.route(url, record_submit)
    expect(page.locator('[name=clone_of]')).to_have_value('')
    expect(page.locator('#clone-notice')).to_contain_text('no longer available')
    expect(page.locator('[name=label]')).to_have_value('Preserved settings')
    expect(page.locator('[name=cg_production_ps]')).to_have_value('200')
    expect(page.locator('#leave-clone')).to_be_hidden()
    expect(page.locator('[name=temperature_k]')).not_to_have_value('')
    page.locator('#start-run').click()
    expect(page.locator('#notice')).to_have_text('Run queued.')
    assert len(requests)==1 and requests[0][0]==url
    assert requests[0][1]['cg_production_ps']=='200'
    assert json.loads(page.evaluate("localStorage.getItem('ddm.form')"))['clone_of']==''
    # A valid saved clone remains visible and usable across reloads.
    page.unroute(url, record_submit)
    page.route('**/api/jobs/abcdef123456', lambda route: route.fulfill(json={'id':'abcdef123456'}))
    page.evaluate("localStorage.setItem('ddm.form',JSON.stringify({...JSON.parse(localStorage.getItem('ddm.form')),clone_of:'abcdef123456'}))")
    page.reload()
    page.get_by_role('tab', name='New run', exact=True).click()
    page.route(url, record_submit)
    expect(page.locator('#clone-notice')).to_contain_text('Cloning abcdef123456')
    expect(page.locator('#leave-clone')).to_be_visible()
    page.locator('#start-run').click()
    expect(page.locator('#notice')).to_have_text('Run queued.')
    assert requests[-1][0].endswith('/api/jobs/abcdef123456/clone')
    assert json.loads(page.evaluate("localStorage.getItem('ddm.form')"))['clone_of']==''
    # Delete a source after opening the form: pause submission, preserve settings.
    page.evaluate("setCloneSource('abcdef123456'); selectTab('new')")
    expect(page.locator('#new')).to_have_attribute('aria-busy', 'false')
    page.unroute('**/api/jobs/abcdef123456')
    before=len(requests)
    page.locator('#start-run').click()
    expect(page.locator('#clone-notice')).to_contain_text('no longer available')
    assert len(requests)==before
    expect(page.locator('[name=cg_production_ps]')).to_have_value('200')
    # Network/server failures must not silently discard a valid clone choice.
    page.route('**/api/jobs/abcdef123456', lambda route: route.fulfill(status=500,json={'error':'Temporary failure'}))
    page.evaluate("setCloneSource('abcdef123456')")
    page.locator('#start-run').click()
    expect(page.locator('#notice')).to_have_text('Temporary failure')
    expect(page.locator('[name=clone_of]')).to_have_value('abcdef123456')
    assert len(requests)==before
    page.locator('#leave-clone').click()
    expect(page.locator('[name=clone_of]')).to_have_value('')
    assert errors==[]
