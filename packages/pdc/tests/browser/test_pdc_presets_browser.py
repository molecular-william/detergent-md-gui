"""The protein-detergent New run panel's preset bar, for the `pdc` run type.

The bar is the validation panel's own markup and its ids, but this module owns the handlers: the engine's panel is not
created on this workspace. What the tests pin is the contract the store and the form share: Load restores the stage
settings (including the four per-stage timesteps and the facts line), Save posts the run type and the controls as they
stand, Set as default PATCHes the select's preset, and Delete asks before it deletes. A preset saved before per-stage
timesteps still restores the same physics by translating its two global timesteps onto the legs they meant.
"""
import re

from playwright.sync_api import expect

from tests.harness import browser

CATALOG = {
    'templates': [{'id': 'DDM:DDM', 'name': 'DDM skeleton', 'molecule': 'DDM', 'residue': 'DDM',
                   'template': 'molecules/DDM/v1/micelle_template.json', 'registered_type': 'registered-template',
                   'files_present': True, 'missing_files': [],
                   'limitations': ['skeleton placeholder template, not a fitted detergent model']}],
    'proteins': [],
    'defaults': {'aggregation_number': 150, 'assessment_ns': 100, 'extension_ns': 900, 'salt_molar': 0.15,
                 'box_margin_nm': 2.0, 'initial_z_nm': 6.0, 'contact_nm': 0.6,
                 'selection_threshold_fraction': 0.1,
                 'nstlog': 100, 'nstenergy': 100, 'nstxtcout': 100, 'xtc_precision': 1000, 'nstcomm': 100,
                 'nstlist': 40, 'verlet_buffer_tolerance': 0.005, 'rlist': 1.35, 'rcoulomb': 1.1, 'rvdw': 1.1,
                 'ref_t': 300, 'tau_t': 1.0, 'ref_p': 1.0, 'tau_p': 12.0, 'compressibility': 4.5e-5,
                 'minimisation_steps': 200000, 'nvt_ps': 500, 'npt_ps': 4500,
                 'pdc_posres_min': 'yes', 'pdc_posres_nvt': 'no', 'pdc_posres_npt': 'yes',
                 'pdc_minimisation_emtol': 100, 'pdc_minimisation_emstep': 0.001,
                 'pdc_npt_pcoupl': 'c-rescale', 'pdc_npt_pcoupltype': 'isotropic', 'pdc_npt_ref_p': 1.0,
                 'pdc_npt_tau_p': 4.0, 'pdc_npt_compressibility': 4.5e-5,
                 'mdrun_ntomp': 8, 'mdrun_ranks': 1, 'mdrun_nb': 'auto'},
}

#: The shape the store answers with: the adapter normalizes the durations to its builders' short names, so a preset
#: saved from this panel comes back as `nvt_ps`/`assessment_ns`, not as the controls' `pdc_*` spellings.
PRESET = {
    'id': 'preset000001', 'name': 'Standard', 'run_type': 'pdc', 'is_default': False,
    'settings': {'seed': 20261017, 'nvt_ps': 250, 'pdc_nvt_dt_fs': 5,
                 'npt_ps': 900, 'pdc_npt_dt_fs': 5,
                 'assessment_ns': 150, 'pdc_assessment_dt_fs': 20,
                 'extension_ns': 800, 'pdc_extension_dt_fs': 20},
}

#: A preset saved before the split: the panel rendered two global timesteps, and the store kept them under the names
#: the adapter retired. Loading it must still mean 5 fs equilibration and 20 fs production.
LEGACY = {
    'id': 'legacy000001', 'name': 'Pre-split', 'run_type': 'pdc', 'is_default': False,
    'settings': {'pdc_equil_dt_fs': '5', 'pdc_production_dt_fs': '20'},
}


def serve(page, presets=()):
    """The panel's reads, with the preset store answered by this test."""
    browser.serve_pdc_new_run(page, catalogue=CATALOG)
    browser.serve_files(
        page,
        (re.compile(r'/api/pdc/conformations/runs'), {'runs': []}),
        (re.compile(r'/api/pdc/conformations/libraries'), {'libraries': []}),
        (re.compile(r'/api/setting-presets\?'), {'presets': list(presets), 'default': None}),
    )


def open_panel(page, base_url):
    return browser.open_pdc_new_run(page, base_url)


def test_the_bar_renders_and_load_restores_the_stage_settings(dashboard, live_page):
    """Every control in the fieldset is a preset field: the four dt/duration boxes and the facts line follow."""
    page, errors = live_page
    serve(page, presets=[PRESET])
    open_panel(page, live_page.base_url)

    for selector in ('#preset-select', '#preset-load', '#preset-save', '#preset-default', '#preset-delete',
                     '#preset-marker'):
        expect(page.locator(selector)).to_be_visible()
    expect(page.locator('#preset-marker')).to_have_text('Profile defaults')

    page.locator('#preset-select').select_option(PRESET['id'])
    page.locator('#preset-load').click()

    # The seed is stored under the adapter's `seed`; the panel's control is `pdc_seed`, so this also proves the
    # canonical-name translation rather than only the four dt keys.
    expect(page.locator('[name=pdc_seed]')).to_have_value('20261017')
    for name, value in (('pdc_nvt_ps', '250'), ('pdc_nvt_dt_fs', '5'),
                        ('pdc_npt_ps', '900'), ('pdc_npt_dt_fs', '5'),
                        ('pdc_assessment_ns', '150'), ('pdc_assessment_dt_fs', '20'),
                        ('pdc_extension_ns', '800'), ('pdc_extension_dt_fs', '20')):
        expect(page.locator(f'[name={name}]')).to_have_value(value)
    expect(page.locator('.new-pdc-stage-facts[data-stage=nvt]')).to_have_text('250 ps · 5 fs · 50 000 steps · free')
    expect(page.locator('.pdc-steps[data-stage=assessment]')).to_have_value('7500000')
    expect(page.locator('#preset-marker')).to_have_text('Applied preset: Standard')
    assert errors == [], errors


def test_a_preset_saved_before_per_stage_timesteps_still_restores_the_same_physics(dashboard, live_page):
    """equil -> NVT + NPT, production -> assessment + extension: the legs keep the dt the old preset stated."""
    page, errors = live_page
    serve(page, presets=[LEGACY])
    open_panel(page, live_page.base_url)

    page.locator('#preset-select').select_option(LEGACY['id'])
    page.locator('#preset-load').click()

    for name in ('pdc_nvt_dt_fs', 'pdc_npt_dt_fs'):
        expect(page.locator(f'[name={name}]')).to_have_value('5')
    for name in ('pdc_assessment_dt_fs', 'pdc_extension_dt_fs'):
        expect(page.locator(f'[name={name}]')).to_have_value('20')
    assert errors == [], errors


def test_save_posts_the_run_type_and_the_controls_as_they_stand(dashboard, live_page):
    """Save sends `pdc` and the named controls, skipping blank values and never sending a derived step count."""
    page, errors = live_page
    posted = {}
    serve(page, presets=[PRESET])

    def save(route):
        posted.update(route.request.post_data_json or {})
        route.fulfill(status=201, json={'preset': {'id': 'saved0000001', 'name': 'Workspace standard',
                                                   'run_type': 'pdc', 'is_default': False, 'settings': {}}})

    page.route(re.compile(r'/api/setting-presets$'), save)
    page.on('dialog', lambda dialog: dialog.accept('Workspace standard'))
    open_panel(page, live_page.base_url)

    page.locator('[name=pdc_nvt_ps]').fill('140')
    page.locator('[name=pdc_nvt_dt_fs]').fill('7')
    page.locator('#preset-save').click()

    expect(page.locator('#notice')).to_contain_text('Preset Workspace standard saved.')
    assert posted['run_type'] == 'pdc', posted
    assert posted['name'] == 'Workspace standard', posted
    assert posted['settings']['pdc_nvt_ps'] == '140'
    assert posted['settings']['pdc_nvt_dt_fs'] == '7'
    assert all(value != '' for value in posted['settings'].values()), posted
    assert 'pdc_assessment_dt_fs' not in posted['settings'], 'a blank timestep is not a stored override'
    assert errors == [], errors


def test_set_as_default_patches_the_selected_preset(dashboard, live_page):
    page, errors = live_page
    patched = {}
    serve(page, presets=[PRESET])

    def update(route):
        patched.update(method=route.request.method, url=route.request.url,
                       body=route.request.post_data_json)
        route.fulfill(json={'preset': PRESET, 'defaults': {'pdc': PRESET['id']}})

    page.route(re.compile(r'/api/setting-presets/'), update)
    open_panel(page, live_page.base_url)

    page.locator('#preset-select').select_option(PRESET['id'])
    page.locator('#preset-default').click()

    expect(page.locator('#notice')).to_contain_text('is the pdc default')
    assert patched['method'] == 'PATCH', patched
    assert patched['body'] == {'is_default': True}, patched
    assert patched['url'].endswith('/' + PRESET['id']), patched
    assert errors == [], errors


def test_delete_confirms_and_deletes_the_selected_preset(dashboard, live_page):
    page, errors = live_page
    deleted = {}
    serve(page, presets=[PRESET])

    def remove(route):
        deleted.update(method=route.request.method, url=route.request.url)
        route.fulfill(json={'deleted': PRESET['id']})

    page.route(re.compile(r'/api/setting-presets/'), remove)
    page.on('dialog', lambda dialog: dialog.accept())
    open_panel(page, live_page.base_url)

    page.locator('#preset-select').select_option(PRESET['id'])
    page.locator('#preset-delete').click()

    expect(page.locator('#notice')).to_contain_text('Preset Standard deleted.')
    assert deleted['method'] == 'DELETE', deleted
    assert deleted['url'].endswith('/' + PRESET['id']), deleted
    assert errors == [], errors
