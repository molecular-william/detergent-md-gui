"""The AA run: its own vocabulary, its own review rows, and no CG model to carry.

An AA run publishes the reference a later parameterization is fitted against. It has no model selector, no AA-source
picker and no CG settings in its payload; its stage settings are the atomistic leg's. The simulation requests are
intercepted: what this file reads is the payload the panel builds, not a run.
"""
import json
import re

from playwright.sync_api import expect

from tests.harness import browser

DEFAULTS = {'aa_nvt_ps': 100, 'aa_npt_ps': 1000, 'aa_production_ps': 10000, 'temperature_k': 300,
            'pressure_bar': 1, 'output_interval_ps': 10, 'box_nm': 2.4, 'aa_seed': 12345,
            'mdrun_ntomp': 8, 'mdrun_ranks': 1, 'mdrun_gpu': 0, 'mdrun_cpt': 10,
            'mdrun_nb': 'auto', 'mdrun_pme': 'auto', 'constraints': 'all-bonds',
            'force_field': 'charmm36-jul2022', 'cg_equil_ps': 10, 'cg_production_ps': 50,
            'sasa_probe_nm': 0.191, 'cg_seed': 12345,
            # The three stages' own timesteps, neighbour-list cadence and Verlet buffer tolerance.
            'aa_nvt_dt_fs': 2, 'aa_npt_dt_fs': 2, 'aa_production_dt_fs': 2,
            'aa_nvt_nstlist': 20, 'aa_npt_nstlist': 20, 'aa_production_nstlist': 20,
            'aa_nvt_verlet_buffer_tolerance': -1, 'aa_npt_verlet_buffer_tolerance': -1,
            'aa_production_verlet_buffer_tolerance': -1,
            # The thermostat (every stage) and the barostat (NPT stages only), and the one run-wide hydrogen mass
            # factor, which is blank by default.
            'aa_nvt_tcoupl': 'V-rescale', 'aa_nvt_tau_t': 1,
            'aa_npt_tcoupl': 'V-rescale', 'aa_npt_tau_t': 1, 'aa_npt_pcoupl': 'C-rescale',
            'aa_npt_pcoupltype': 'isotropic', 'aa_npt_tau_p': 5, 'aa_npt_compressibility': 4.5e-5,
            'aa_production_tcoupl': 'V-rescale', 'aa_production_tau_t': 1,
            'aa_production_pcoupl': 'Parrinello-Rahman', 'aa_production_pcoupltype': 'isotropic',
            'aa_production_tau_p': 5, 'aa_production_compressibility': 4.5e-5,
            'mass_repartition_factor': None}


def stub(page):
    page.route('**/api/defaults?*', lambda route: route.fulfill(
        json={'values': DEFAULTS, 'sources': {'AA': 'CHARMM AA protocol v1'}, 'profile': 'draft-smoke',
              'force_fields': []}))
    page.route('**/api/readiness?*', lambda route: route.fulfill(json={'ready': True, 'checks': [], 'blockers': []}))
    page.route('**/api/setting-presets?*', lambda route: route.fulfill(json={'presets': [], 'default': None}))


def test_an_aa_run_posts_only_its_own_vocabulary_and_says_this_run(dashboard, live_page):
    dashboard.coordinator.database().replace([])
    page, errors = live_page
    stub(page)
    submissions = []
    page.add_init_script("localStorage.setItem('ddm.form', JSON.stringify({run_type:'aa_only',molecule_id:'DDM',"
                         "cg_production_ps:'250',temperature_k:'305'}))")
    page.goto(f'{live_page.base_url}/detergent-validation/new-run')

    expect(page.locator('[name=aa_nvt_ps]')).to_have_value('100', timeout=30000)
    expect(page.locator('#run-type')).to_have_value('aa_only')
    expect(page.locator('#cg-inputs')).to_be_hidden()
    expect(page.locator('#run-parameterization-summary')).to_have_text('not needed')
    expect(page.locator('#run-aa-summary')).to_have_text('this run')
    expect(page.locator('#run-coordinates-summary')).to_have_text('this run')
    expect(page.locator('[name=label]')).to_have_value(re.compile(r'^DDM-AA-11\.1ns-\d{8}$'), timeout=30000)
    # There is no AA-source picker any more: the AA run is its own source.
    assert page.locator('[name=reference_run_id]').count() == 0
    # The saved CG durations are kept for the CG form, not posted by this run.
    saved = json.loads(page.evaluate("localStorage.getItem('ddm.form')"))
    assert saved['cg_production_ps'] == '250'

    url = f'{live_page.base_url}/'

    def submit(route):
        submissions.append(route.request.post_data_json)
        route.fulfill(status=201, json={'id': '222222222222'})

    page.route(url, submit)
    page.locator('#start-run').click()
    expect(page.locator('#notice')).to_have_text('Run queued.')
    body = submissions[0]
    assert body['run_type'] == 'aa_only' and body['molecule_id'] == 'DDM'
    assert body['aa_nvt_ps'] == '100' and body['temperature_k'] == '305'
    for retired in ('mapping_candidate', 'reference_run_id', 'parameterization', 'method', 'profile'):
        assert retired not in body, f'{retired} is still sent: {body}'
    assert 'cg_production_ps' not in body and 'cg_seed' not in body
    # A blank hydrogen-mass box writes no setting at all: the run keeps GROMACS' own default (no repartitioning).
    assert 'mass_repartition_factor' not in body
    # The AA controls are the ones the run type executes; a CG run's are hidden again.
    page.locator('#tab-new').click()
    page.locator('#run-type').select_option('cg')
    expect(page.locator('#cg-inputs')).to_be_visible()
    expect(page.locator('[name=cg_production_ps]')).to_have_value('250')
    expect(page.locator('#run-aa-summary')).to_have_text('no parameterization selected')
    page.set_viewport_size({'width': 390, 'height': 844})
    browser.assert_no_horizontal_scroll(page)
    assert not errors, errors


def test_the_stage_editors_state_their_numbers_and_post_while_collapsed(dashboard, live_page):
    """The three AA stages are minimisable editors: NVT open, NPT and production collapsed with their facts.

    The facts line is the stage's own arithmetic -- duration, timestep, the steps they imply and the neighbour-list
    cadence -- so a collapsed stage still says what it holds. A collapsed `<details>` keeps its inputs in the form,
    so its numbers post; only the visible face of the editor is minimised.
    """
    dashboard.coordinator.database().replace([])
    page, errors = live_page
    stub(page)
    page.add_init_script("localStorage.setItem('ddm.form', JSON.stringify({run_type:'aa_only',molecule_id:'DDM'}))")
    page.goto(f'{live_page.base_url}/detergent-validation/new-run')

    expect(page.locator('#stage-aa-nvt-facts')).to_have_text(
        '100 ps · 2 fs · 50 000 steps · nstlist 20', timeout=30000)
    assert page.locator('#stage-aa-nvt').evaluate('(el) => el.open') is True
    assert page.locator('#stage-aa-npt').evaluate('(el) => el.open') is False
    assert page.locator('#stage-aa-production').evaluate('(el) => el.open') is False
    expect(page.locator('#stage-aa-npt-facts')).to_have_text('1 000 ps · 2 fs · 500 000 steps · nstlist 20')
    expect(page.locator('#stage-aa-production-facts')).to_have_text(
        '10 000 ps · 2 fs · 5 000 000 steps · nstlist 20')
    # The CG legs are the other run type's: their three editors are out of the AA form's way.
    for stage in ('minimization', 'equilibration', 'production'):
        expect(page.locator(f'#stage-cg-{stage}')).to_be_hidden()

    # A shorter timestep is more steps over the same duration.
    page.locator('[name=aa_nvt_dt_fs]').fill('1')
    expect(page.locator('#stage-aa-nvt-facts')).to_have_text('100 ps · 1 fs · 100 000 steps · nstlist 20')

    # A part whose control is empty is omitted rather than guessed.
    page.locator('[name=aa_nvt_ps]').fill('')
    expect(page.locator('#stage-aa-nvt-facts')).to_have_text('1 fs · nstlist 20')
    page.locator('[name=aa_nvt_ps]').fill('100')
    expect(page.locator('#stage-aa-nvt-facts')).to_have_text('100 ps · 1 fs · 100 000 steps · nstlist 20')

    # Open production, change one of its numbers, close it again: a collapsed stage still posts.
    page.locator('#stage-aa-production > summary').click()
    page.locator('[name=aa_production_nstlist]').fill('50')
    page.locator('#stage-aa-production > summary').click()
    assert page.locator('#stage-aa-production').evaluate('(el) => el.open') is False
    expect(page.locator('#stage-aa-production-facts')).to_have_text(
        '10 000 ps · 2 fs · 5 000 000 steps · nstlist 50')

    submissions = []
    page.route(f'{live_page.base_url}/', lambda route: (
        submissions.append(route.request.post_data_json), route.fulfill(status=201, json={'id': '444444444444'}))[1])
    page.locator('#start-run').click()
    expect(page.locator('#notice')).to_have_text('Run queued.')
    body = submissions[0]
    assert body['aa_nvt_dt_fs'] == '1'
    assert (body['aa_npt_dt_fs'], body['aa_production_dt_fs']) == ('2', '2')
    assert body['aa_npt_nstlist'] == '20'
    assert body['aa_production_nstlist'] == '50'
    assert body['aa_production_verlet_buffer_tolerance'] == '-1'

    # A CG run consumes a reference that already ran: none of the three AA stage editors is offered, and the three
    # CG editors take their place.
    page.locator('#tab-new').click()
    page.locator('#run-type').select_option('cg')
    for stage in ('nvt', 'npt', 'production'):
        expect(page.locator(f'#stage-aa-{stage}')).to_be_hidden()
    for stage in ('minimization', 'equilibration', 'production'):
        expect(page.locator(f'#stage-cg-{stage}')).to_be_visible()
    expect(page.locator('h4.new-option-title.cg-setting')).to_be_visible()
    # The stage group's heading, its blurb and the box-shape note go with the controls they describe.
    expect(page.locator('h4.new-option-title.aa-setting')).to_be_hidden()
    expect(page.locator('p.hint.aa-setting').first).to_be_hidden()
    assert not errors, errors


def test_the_stage_settings_take_the_wider_half_and_fit_four_in_a_row(dashboard, live_page):
    """The AA form's settings half is the wider one, and four settings of a stage editor share a row.

    Only this form carries the stage editors, so `layout.css` widens the settings column on `:has(.stage-editor)`;
    the pdc workspace's form keeps its 6 + 6 halves. Four per row is the outcome at the default viewport (NVT holds
    six controls -- duration, timestep, neighbour list, Verlet tolerance, thermostat and its coupling time -- so the
    last two wrap), the page still fits the window, and below the breakpoint both halves take the full width.
    """
    dashboard.coordinator.database().replace([])
    page, errors = live_page
    stub(page)
    page.add_init_script("localStorage.setItem('ddm.form', JSON.stringify({run_type:'aa_only',molecule_id:'DDM'}))")
    page.goto(f'{live_page.base_url}/detergent-validation/new-run')
    expect(page.locator('#stage-aa-nvt')).to_be_visible(timeout=30000)
    # Measure only once the stylesheet has laid the grid out; a page whose CSS is still in flight stacks the labels
    # and would read as a layout failure.
    page.wait_for_function("""() => {
      const grid = document.querySelector('#stage-aa-nvt .settings-grid');
      return grid && getComputedStyle(grid).gridTemplateColumns.split(' ').filter(Boolean).length === 4;
    }""", timeout=30000)

    cells = page.locator('#stage-aa-nvt .settings-grid > label').evaluate_all(
        "els => els.map(el => { const box = el.getBoundingClientRect(); return {x: box.x, y: box.y} })")
    assert len(cells) == 6, cells
    first, wrapped = cells[:4], cells[4:]
    assert max(cell['y'] for cell in first) - min(cell['y'] for cell in first) <= 4, cells
    assert len({round(cell['x']) for cell in first}) == 4, cells
    assert all(cell['y'] > max(cell['y'] for cell in first) + 4 for cell in wrapped), cells

    inputs = page.locator('#run-form > .new-run-inputs').bounding_box()
    settings = page.locator('#run-form > .new-run-settings').bounding_box()
    assert settings['width'] > inputs['width'] + 40, (inputs, settings)
    browser.assert_no_horizontal_scroll(page)

    # Below the breakpoint the scoped spans must not beat the full-width rule: both halves stack.
    page.set_viewport_size({'width': 1000, 'height': 900})
    stacked = page.locator('#run-form > .new-run-inputs').bounding_box()
    stacked_settings = page.locator('#run-form > .new-run-settings').bounding_box()
    assert abs(stacked_settings['width'] - stacked['width']) <= 2, (stacked, stacked_settings)
    assert stacked_settings['y'] >= stacked['y'] + stacked['height'] - 1, (stacked, stacked_settings)
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
    # The panel opens on a CG run, whose fields are the CG leg's; the AA run is the one that builds a box.
    page.locator('#run-type').select_option('aa_only')
    label = page.locator('label:has([name=box_shape])')
    button = label.locator('button.info-btn')
    expect(button).to_have_count(1)
    # The button sits on the caption's line at its right, above the control row.
    geometry = label.evaluate("""el => {
      const help = el.querySelector('.field-help').getBoundingClientRect();
      const control = el.querySelector('.setting-control').getBoundingClientRect();
      const cell = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return {helpY: help.y - cell.y, helpX: help.x - cell.x, controlY: control.y - cell.y,
              marginTop: style.marginTop, marginBottom: style.marginBottom};
    }""")
    assert geometry['helpY'] < 8, geometry
    assert geometry['helpX'] > 20, geometry
    assert geometry['controlY'] > geometry['helpY'] + 12, geometry
    assert geometry['marginTop'] == '0px' and geometry['marginBottom'] == '0px', geometry
    described = button.get_attribute('aria-describedby')
    assert described, 'the info button must name its tooltip'
    tip = page.locator(f'#{described}')
    expect(tip).to_have_attribute('role', 'tooltip')
    expect(tip).to_have_text('The unit cell the protocol builds (stub text).')
    expect(tip).to_be_hidden()
    button.focus()
    expect(tip).to_be_visible()
    button.click()
    expect(tip).to_be_visible()
    page.keyboard.press('Escape')
    assert 'is-open' not in (tip.get_attribute('class') or '')
    page.mouse.move(0, 0)
    expect(tip).to_be_hidden()
    # The fold starts collapsed and opens to the CG production group and the execution controls.
    advanced = page.locator('#new-advanced')
    assert advanced.evaluate('(el) => el.open') is False
    advanced.locator('> summary').click()
    expect(advanced).to_be_visible()
    expect(page.locator('label:has([name=nstlog]) button.info-btn')).to_have_count(1)
    assert not errors, errors


def test_the_coupling_hmr_timestep_and_label_are_editable_and_post(dashboard, live_page):
    """Thermostat on every dynamics stage, barostat where the stage couples pressure, one HMR factor, no dt ceiling.

    The NVT leg fixes its box, so it has no barostat control at all; NPT and production have all six. The label is
    free text and takes the row's spare width rather than the 9 rem numeric-control cap.
    """
    dashboard.coordinator.database().replace([])
    page, errors = live_page
    stub(page)
    page.add_init_script("localStorage.setItem('ddm.form', JSON.stringify({run_type:'aa_only',molecule_id:'DDM'}))")
    page.goto(f'{live_page.base_url}/detergent-validation/new-run')

    # The old 4 fs ceiling is gone; the floor stays.
    timestep = page.locator('[name=aa_nvt_dt_fs]')
    expect(timestep).to_have_value('2', timeout=30000)
    assert timestep.get_attribute('max') is None
    timestep.fill('5')

    expect(page.locator('[name=aa_nvt_tcoupl]')).to_have_value('V-rescale')
    assert page.locator('[name=aa_nvt_pcoupl]').count() == 0, 'NVT fixes the box; it has no barostat'

    # `name="aa-stages"` is an accordion, so each stage is opened (closing the previous one) before it is read or
    # filled; its controls stay in the form even when the editor is collapsed again.
    page.locator('#stage-aa-npt > summary').click()
    for field in ('tcoupl', 'tau_t', 'pcoupl', 'pcoupltype', 'tau_p', 'compressibility'):
        assert page.locator(f'[name=aa_npt_{field}]').count() == 1, field
    expect(page.locator('[name=aa_npt_pcoupl]')).to_have_value('C-rescale')
    page.locator('[name=aa_npt_tcoupl]').select_option('Berendsen')
    page.locator('[name=aa_npt_tau_t]').fill('2')
    page.locator('[name=aa_npt_pcoupltype]').select_option('semiisotropic')
    page.locator('[name=aa_npt_compressibility]').fill('2e-5')

    page.locator('#stage-aa-production > summary').click()
    for field in ('tcoupl', 'tau_t', 'pcoupl', 'pcoupltype', 'tau_p', 'compressibility'):
        assert page.locator(f'[name=aa_production_{field}]').count() == 1, field
    expect(page.locator('[name=aa_production_pcoupl]')).to_have_value('Parrinello-Rahman')
    page.locator('[name=aa_production_tau_p]').fill('7')
    page.locator('[name=mass_repartition_factor]').fill('3')

    # The label box is wider than the numeric controls' cap (9 rem = 144 px).
    assert page.locator('[name=label]').bounding_box()['width'] > 250

    submissions = []
    page.route(f'{live_page.base_url}/', lambda route: (
        submissions.append(route.request.post_data_json), route.fulfill(status=201, json={'id': '555555555555'}))[1])
    page.locator('#start-run').click()
    expect(page.locator('#notice')).to_have_text('Run queued.')
    body = submissions[0]
    assert body['aa_nvt_dt_fs'] == '5'
    assert (body['aa_npt_tcoupl'], body['aa_npt_tau_t']) == ('Berendsen', '2')
    assert body['aa_npt_pcoupltype'] == 'semiisotropic'
    assert body['aa_npt_compressibility'] == '2e-5'
    assert body['aa_production_tau_p'] == '7'
    assert body['mass_repartition_factor'] == '3'
    assert body['aa_nvt_tcoupl'] == 'V-rescale' and body['aa_nvt_tau_t'] == '1'
    assert not errors, errors
