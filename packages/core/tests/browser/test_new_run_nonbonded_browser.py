"""The New run form's one Nonbonded and constraints section.

The section is shared by the AA and CG legs (docs/plans/2026-11-18-new-run-nonbonded-and-constraints.md): the AA
run's PME stages and the CG run's reaction-field legs read the same controls, and a control that belongs to one
kind is hidden for the other. The reviewed values prefill the boxes; a control whose blank is the reviewed rule
clears on its Default button and is never posted blank.
"""

from playwright.sync_api import expect

from tests.harness import browser

AA_DEFAULTS = {'aa_nvt_ps': 100, 'aa_npt_ps': 1000, 'aa_production_ps': 10000, 'temperature_k': 300,
               'pressure_bar': 1, 'output_interval_ps': 10, 'box_nm': 2.5, 'aa_seed': 12345,
               'mdrun_ntomp': 8, 'mdrun_ranks': 1, 'mdrun_gpu': 0, 'mdrun_cpt': 10,
               'mdrun_nb': 'auto', 'mdrun_pme': 'auto', 'constraints': 'all-bonds',
               'force_field': 'charmm36-jul2022', 'vsite': 'none',
               'aa_nvt_dt_fs': 2, 'aa_npt_dt_fs': 2, 'aa_production_dt_fs': 2,
               'aa_nvt_nstlist': 20, 'aa_npt_nstlist': 20, 'aa_production_nstlist': 20,
               'aa_nvt_verlet_buffer_tolerance': -1, 'aa_npt_verlet_buffer_tolerance': -1,
               'aa_production_verlet_buffer_tolerance': -1,
               'aa_minimization_steps': 20000, 'aa_minimization_emtol': 1000, 'aa_minimization_emstep': 0.01,
               'aa_nvt_tcoupl': 'V-rescale', 'aa_nvt_tau_t': 1,
               'aa_npt_tcoupl': 'V-rescale', 'aa_npt_tau_t': 1, 'aa_npt_pcoupl': 'C-rescale',
               'aa_npt_pcoupltype': 'isotropic', 'aa_npt_tau_p': 5, 'aa_npt_compressibility': 4.5e-5,
               'aa_production_tcoupl': 'V-rescale', 'aa_production_tau_t': 1,
               'aa_production_pcoupl': 'Parrinello-Rahman', 'aa_production_pcoupltype': 'isotropic',
               'aa_production_tau_p': 5, 'aa_production_compressibility': 4.5e-5,
               # The shared section's reviewed prefills.
               'rlist': 1.2, 'rcoulomb': 1.2, 'rvdw': 1.2, 'rvdw_switch': 1.0, 'vdwtype': 'cutoff',
               'vdw_modifier': 'force-switch'}

CG_DEFAULTS = {'cg_equil_ps': 5000, 'cg_production_ps': 10000, 'temperature_k': 300,
               'output_interval_ps': 10, 'cg_seed': 12345, 'mdrun_ntomp': 8, 'mdrun_ranks': 1,
               'mdrun_gpu': 0, 'mdrun_cpt': 10, 'mdrun_nb': 'auto',
               'cg_minimization_steps': 20000, 'cg_minimization_nstlist': 20,
               'cg_minimization_verlet_buffer_tolerance': 0.005,
               'cg_equil_dt_fs': 5, 'cg_equil_nstlist': 40, 'cg_equil_verlet_buffer_tolerance': 0.005,
               'cg_equil_tau_t': 1, 'cg_equil_tau_p': 4, 'cg_equil_compressibility': 4.5e-5,
               'cg_equil_pcoupl': 'c-rescale', 'cg_equil_pcoupltype': 'isotropic', 'cg_equil_ref_p': 1,
               'cg_production_dt_fs': 20, 'nstlist': 40, 'verlet_buffer_tolerance': 0.005,
               'tau_t': 1, 'tau_p': 12, 'compressibility': 4.5e-5,
               # The shared section's reviewed prefills.
               'rcoulomb': 1.1, 'rvdw': 1.1, 'vdwtype': 'cutoff', 'vdw_modifier': 'potential-shift-verlet',
               'coulombtype': 'reaction-field', 'epsilon_r': 15, 'epsilon_rf': 0,
               'lincs_order': 4, 'lincs_warnangle': 30}


def stub(page):
    def defaults(route):
        values = CG_DEFAULTS if 'run_type=cg' in route.request.url else AA_DEFAULTS
        route.fulfill(json={'values': values, 'sources': {'AA': 'CHARMM AA protocol', 'CG': 'cg profiles'},
                            'profile': 'standard', 'force_fields': []})
    page.route('**/api/defaults?*', defaults)
    page.route('**/api/readiness?*', lambda route: route.fulfill(json={'ready': True, 'checks': [], 'blockers': []}))
    page.route('**/api/setting-presets?*', lambda route: route.fulfill(json={'presets': [], 'default': None}))


def open_form(page, base_url, run_type):
    page.add_init_script("localStorage.setItem('ddm.form', JSON.stringify({run_type:'%s',molecule_id:'DDM'}))"
                         % run_type)
    page.goto(f'{base_url}/detergent-validation/new-run')
    expect(page.locator('#new-nonbonded-title')).to_be_visible(timeout=30000)


def test_the_aa_form_shows_the_shared_section_with_the_force_fields_own_values(dashboard, live_page):
    dashboard.coordinator.database().replace([])
    page, errors = live_page
    stub(page)
    open_form(page, live_page.base_url, 'aa_only')

    # The section replaced the old CG-production cut-off group inside Other run options.
    assert page.locator('[name=rlist]').count() == 1
    assert page.locator('#new-cutoffs-title').count() == 0
    expect(page.locator('[name=rlist]')).to_have_value('1.2')
    expect(page.locator('[name=rcoulomb]')).to_have_value('1.2')
    expect(page.locator('[name=rvdw]')).to_have_value('1.2')
    expect(page.locator('[name=rvdw_switch]')).to_have_value('1')
    expect(page.locator('[name=vdw_modifier]')).to_have_value('force-switch')
    # The AA half is PME: the reaction-field controls belong to the CG form and stay out of this one.
    expect(page.locator('[name=epsilon_rf]')).to_be_hidden()
    expect(page.locator('[name=lincs_iter]')).to_be_visible()

    # A control whose reviewed rule is "no line" starts blank and its Default button clears it.
    expect(page.locator('[name=nsttcouple]')).to_have_value('')
    page.locator('[name=nsttcouple]').fill('50')
    page.locator('button.use-default[data-field=nsttcouple]').click()
    expect(page.locator('[name=nsttcouple]')).to_have_value('')
    page.locator('[name=nsttcouple]').fill('50')

    submissions = []
    page.route(f'{live_page.base_url}/', lambda route: (
        submissions.append(route.request.post_data_json), route.fulfill(status=201, json={'id': '555555555555'}))[1])
    page.locator('[name=rvdw]').fill('1.1')
    page.locator('[name=rvdw_switch]').fill('0.9')
    page.locator('[name=lincs_order]').fill('6')
    page.locator('#start-run').click()
    expect(page.locator('#notice')).to_have_text('Run queued.')
    body = submissions[0]
    assert (body['rlist'], body['rcoulomb'], body['rvdw'], body['rvdw_switch']) == ('1.2', '1.2', '1.1', '0.9')
    assert body['nsttcouple'] == '50' and body['lincs_order'] == '6'
    # A blank LINCS field writes no setting at all: the reviewed profile keeps its own line.
    assert 'lincs_iter' not in body and 'epsilon_rf' not in body
    assert not errors, errors


def test_the_cg_form_shows_the_reaction_field_controls_and_hides_the_aa_lincs_one(dashboard, live_page):
    dashboard.coordinator.database().replace([])
    page, errors = live_page
    stub(page)
    open_form(page, live_page.base_url, 'cg')

    expect(page.locator('[name=rcoulomb]')).to_have_value('1.1')
    expect(page.locator('[name=rvdw]')).to_have_value('1.1')
    expect(page.locator('[name=vdw_modifier]')).to_have_value('potential-shift-verlet')
    expect(page.locator('[name=coulombtype]')).to_have_value('reaction-field')
    expect(page.locator('[name=epsilon_r]')).to_have_value('15')
    expect(page.locator('[name=epsilon_rf]')).to_have_value('0')
    # rlist is the one shared control the CG profile leaves to GROMACS: the box is blank, not a pinned number.
    expect(page.locator('[name=rlist]')).to_have_value('')
    # LINCS is inert for a CG model (its profiles state constraints = none); the AA-only iteration count is out.
    expect(page.locator('[name=lincs_order]')).to_have_value('4')
    expect(page.locator('[name=lincs_iter]')).to_be_hidden()
    page.set_viewport_size({'width': 390, 'height': 844})
    browser.assert_no_horizontal_scroll(page)
    assert not errors, errors
