"""New AA form state and payload, with simulation requests intercepted."""
import json

from playwright.sync_api import expect

from tests.harness import browser


def test_aa_form_preserves_cg_choices_and_reference_settings(dashboard, live_page):
    aa = dict(aa_nvt_ps=100, aa_npt_ps=1000, aa_production_ps=10000,
              temperature_k=300, pressure_bar=1, output_interval_ps=10,
              box_nm=2.4, aa_seed=12345)
    defaults = aa | dict(cg_equil_ps=10, cg_production_ps=50, sasa_probe_nm=.191, cg_seed=12345)
    inherited = aa | dict(temperature_k=310, aa_production_ps=500, output_interval_ps=5)
    dashboard.coordinator.database().replace([])
    page, errors = live_page
    submissions = []
    page.route('**/api/defaults?*', lambda r: r.fulfill(json={'values':defaults,'sources':{'AA':'CHARMM AA protocol v1'},'profile':'draft-smoke'}))
    page.route('**/api/readiness?*', lambda r: r.fulfill(json={'ready':True,'checks':[],'blockers':[]}))
    page.route('**/api/references*', lambda r: r.fulfill(json={'references':[{'id':'111111111111','label':'Shared AA source','run_type':'aa_only','settings':inherited}]}))
    page.add_init_script("localStorage.setItem('ddm.form', JSON.stringify({run_type:'aa_cg',molecule_id:'DDM',cg_production_ps:'250',temperature_k:'305'}))")
    url = f'{live_page.base_url}/'
    # Initial molecule loading refreshes the reference selector after defaults.
    # Wait for that request before selecting a reference to test inheritance.
    with page.expect_response(lambda response: '/api/references?molecule_id=DDM' in response.url):
        page.goto(url + '/detergent-validation/new-run')
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
    assert 'profile' not in saved, 'the panel still persists a profile it no longer offers'
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
    page.set_viewport_size({'width':390,'height':844})
    browser.assert_no_horizontal_scroll(page)
    assert not errors, errors


def test_the_help_map_renders_accessible_info_buttons(dashboard, live_page):
    """The info icon is a real button whose text comes from the server's map, and Escape closes the click-opened tip.

    The template carries no help sentence: `dashboard.html` renders the control, `new-run.js` attaches a button per
    entry in `/api/defaults`' `help`, and the button's `aria-describedby` names its tooltip. Hover and keyboard focus
    show it through CSS; a click opens it for touch, and Escape closes it.
    """
    dashboard.coordinator.database().replace([])
    page, errors = live_page
    defaults = {'values': {'box_shape': 'cubic', 'aa_nvt_ps': 100}, 'sources': {'AA': 'stub'}, 'profile': 'draft-smoke',
                'help': {'box_shape': 'The unit cell the protocol builds (stub text).', 'aa_nvt_ps': 'The NVT leg.',
                         'nstlog': 'number of steps between log lines (stub text)'}}
    page.route('**/api/defaults?*', lambda r: r.fulfill(json=defaults))
    page.route('**/api/readiness?*', lambda r: r.fulfill(json={'ready': False, 'checks': [], 'blockers': ['stub']}))
    url = f'{live_page.base_url}/detergent-validation/new-run'
    with page.expect_response(lambda response: '/api/defaults?' in response.url):
        page.goto(url)
    label = page.locator('label:has([name=box_shape])')
    button = label.locator('button.info-btn')
    expect(button).to_have_count(1)
    described = button.get_attribute('aria-describedby')
    assert described, 'the info button must name its tooltip'
    tip = page.locator(f'#{described}')
    expect(tip).to_have_attribute('role', 'tooltip')
    expect(tip).to_have_text('The unit cell the protocol builds (stub text).')
    expect(tip).to_be_hidden()
    # Keyboard focus displays it (CSS :focus-within), and Escape closes a click-opened tip.
    button.focus()
    expect(tip).to_be_visible()
    button.click()
    expect(tip).to_be_visible()
    page.keyboard.press('Escape')
    assert 'is-open' not in (tip.get_attribute('class') or '')
    # Hovering the button keeps its tip up by design; once the pointer leaves and Escape released the focus, it closes.
    page.mouse.move(0, 0)
    expect(tip).to_be_hidden()
    # The fold starts collapsed and opens to the CG production group and the execution controls.
    advanced = page.locator('#new-advanced')
    assert advanced.evaluate('(el) => el.open') is False
    advanced.locator('> summary').click()
    expect(advanced).to_be_visible()
    expect(page.locator('label:has([name=nstlog]) button.info-btn')).to_have_count(1)
    assert not errors, errors
