"""Saved clone state must not strand New run after a source is deleted."""
import json

from playwright.sync_api import expect


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
