"""The CG-only sugar mode in the engine's New run form.

The form is the shared single-molecule panel: a sugar run hides the AA half and the mapping controls, shows the
published reference's entry and conformance preview, and posts only the vocabulary its adapter advertises. The
preview and readiness answers are stubbed so the test is about the panel's own decisions, not the sugar package.
"""
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect

SUGAR = {'sugar_entry': 'SUCR', 'cg_equil_ps': 5000.0, 'cg_production_ps': 10000.0,
         'temperature_k': 310.0, 'cg_seed': 20260911, 'output_interval_ps': 10.0,
         'mdrun_ntomp': 8, 'mdrun_ranks': 1, 'mdrun_cpt': 10, 'mdrun_nb': 'auto', 'mdrun_pme': 'auto'}
BEADS = [{'name': f'B{index:02d}', 'export_name': name, 'residue': 1 if index <= 4 else 2,
          'type': bead_type, 'atoms': list(range(index, index + 3)),
          'virtual_site': bead_type == 'TC4'}
         for index, (name, bead_type) in enumerate(
             [('A', 'SP1r'), ('B', 'SP4r'), ('C', 'SP1r'), ('VS', 'TC4'),
              ('A', 'SN6'), ('B', 'SP4r'), ('C', 'SP1r'), ('VS', 'TC4')], 1)]


def _preview(entry='SUCR', *, ready=True, conforms=True, blockers=()):
    return {'molecule_id': 'Sucrose', 'sugar_entry': entry, 'ready': ready, 'conforms': conforms,
            'blockers': list(blockers), 'checks': [], 'beads': BEADS,
            'reference': {'path': 'martini3/martini_v3.0.0_sugars_v2.itp',
                          'sha256': '4d29956a77d936cfdad10e8bbdf201cebdaa24a2f5f50688988a1c7bb9ebfc50',
                          'commit': 'e11f1d31923ba8090779f8601847dbde84e559e4',
                          'paper_doi': '10.1021/acs.jctc.2c00757', 'martini_version': 3},
            'starting_structure': {'source': 'mapped-AA', 'scaled': True, 'ring_scale': 1.15},
            'topology_source': 'published-reference', 'scientifically_validated': False}


def _query(route):
    return parse_qs(urlparse(route.request.url).query)


def _routes(page, submissions, base_url):
    def defaults(route):
        # The route answers for the requested run type; the AA-CG profile's 10 ps equilibration must not leak into
        # the sugar profile's 5000 ps when the form switches type.
        if _query(route).get('run_type') == ['aa_cg']:
            route.fulfill(json={'values': {'cg_equil_ps': 10, 'cg_production_ps': 100, 'temperature_k': 300},
                                'sources': {'aa_cg': 'standard'}, 'profile': 'standard', 'force_fields': []})
        else:
            route.fulfill(json={'values': SUGAR, 'sources': {'sugar': 'sugar-cg-v1'}, 'profile': 'sugar-cg-v1',
                                'force_fields': []})

    def readiness(route):
        if _query(route).get('sugar_entry') == ['TREH']:
            route.fulfill(json={'ready': False, 'checks': [], 'blockers': [
                "residue 1: beads ['A', 'B', 'C', 'VS'] do not match the reference ['A', 'B', 'C', 'VS', 'VS']"]})
        else:
            route.fulfill(json={'ready': True, 'checks': [], 'blockers': []})

    def preview(route):
        entry = _query(route).get('sugar_entry', ['SUCR'])[0]
        if entry == 'TREH':
            route.fulfill(json=_preview('TREH', ready=False, conforms=False, blockers=[
                "residue 1: beads ['A', 'B', 'C', 'VS'] do not match the reference ['A', 'B', 'C', 'VS', 'VS']",
                "residue 2: beads ['A', 'B', 'C', 'VS'] do not match the reference ['A', 'B', 'C']"]))
        else:
            route.fulfill(json=_preview(entry))

    def submit(route):
        submissions.append(route.request.post_data_json)
        route.fulfill(status=201, json={'id': '333333333333'})

    page.route('**/api/defaults?*', defaults)
    page.route('**/api/readiness?*', readiness)
    page.route('**/api/sugar-cg/preview*', preview)
    page.route(f'{base_url}/', submit)


def test_the_sugar_mode_hides_the_aa_half_and_posts_only_its_own_vocabulary(dashboard, live_page):
    dashboard.coordinator.database().replace([])
    page, errors = live_page
    submissions = []
    _routes(page, submissions, live_page.base_url)
    page.add_init_script("localStorage.setItem('ddm.form', JSON.stringify({run_type:'sugar_cg',"
                         "molecule_id:'Sucrose',sugar_entry:'SUCR'}))")
    page.goto(f'{live_page.base_url}/detergent-validation/new-run')

    expect(page.locator('#sugar-panel')).to_be_visible(timeout=30000)
    expect(page.locator('#run-type')).to_have_value('sugar_cg')
    expect(page.locator('#sugar-entry')).to_have_value('SUCR')
    expect(page.locator('#sugar-reference-source')).to_have_value('martini_v3.0.0_sugars_v2.itp')
    expect(page.locator('#sugar-preview')).to_contain_text('Conforms to the published bead layout', timeout=30000)
    expect(page.locator('#sugar-preview .sugar-beads tbody tr')).to_have_count(8)
    expect(page.locator('#sugar-reference-detail')).to_contain_text('sha256 4d29956a')
    # The AA half, the mapping/reference pickers and the AA-only settings are not this run's.
    expect(page.locator('#cg-inputs')).to_be_hidden()
    expect(page.locator('#run-mapping').locator('xpath=ancestor::label')).to_be_hidden()
    expect(page.locator('#reference-run').locator('xpath=ancestor::label')).to_be_hidden()
    expect(page.locator('[name=method]').locator('xpath=ancestor::label')).to_be_hidden()
    expect(page.locator('[name=aa_nvt_ps]').locator('xpath=ancestor::label')).to_be_hidden()
    expect(page.locator('[name=pressure_bar]').locator('xpath=ancestor::label')).to_be_hidden()
    expect(page.locator('#start-run')).to_have_text('Start CG sugar run')
    expect(page.locator('#start-run')).to_be_enabled(timeout=30000)

    page.locator('#start-run').click()
    expect(page.locator('#notice')).to_have_text('Run queued.')
    assert submissions, 'the form did not post a run'
    body = submissions[0]
    assert body['run_type'] == 'sugar_cg'
    assert body['molecule_id'] == 'Sucrose'
    assert body['sugar_entry'] == 'SUCR'
    assert body['cg_production_ps'] == '10000'
    assert 'method' not in body and 'reference_run_id' not in body and 'mapping_candidate' not in body
    assert 'aa_nvt_ps' not in body and 'pressure_bar' not in body
    assert errors == []


def test_switching_to_sugar_replaces_the_aa_cg_durations_with_its_own_profile(dashboard, live_page):
    """The saved AA-CG 10 ps equilibration is not the sugar profile's 5 ns; switching type must re-default."""
    dashboard.coordinator.database().replace([])
    page, errors = live_page
    submissions = []
    _routes(page, submissions, live_page.base_url)
    page.add_init_script("localStorage.setItem('ddm.form', JSON.stringify({run_type:'aa_cg',"
                         "molecule_id:'Sucrose',cg_equil_ps:'10'}))")
    page.goto(f'{live_page.base_url}/detergent-validation/new-run')

    expect(page.locator('#run-type')).to_have_value('aa_cg')
    expect(page.locator('[name=cg_equil_ps]')).to_have_value('10')
    page.locator('#run-type').select_option('sugar_cg')
    expect(page.locator('#sugar-panel')).to_be_visible(timeout=30000)
    expect(page.locator('[name=cg_equil_ps]')).to_have_value('5000', timeout=30000)
    expect(page.locator('#start-run')).to_have_text('Start CG sugar run')
    assert errors == []


def test_trehalose_is_selectable_but_the_published_residue_issue_blocks_it(dashboard, live_page):
    dashboard.coordinator.database().replace([])
    page, errors = live_page
    submissions = []
    _routes(page, submissions, live_page.base_url)
    page.add_init_script("localStorage.setItem('ddm.form', JSON.stringify({run_type:'sugar_cg',"
                         "molecule_id:'Trehalose',sugar_entry:'TREH'}))")
    page.goto(f'{live_page.base_url}/detergent-validation/new-run')

    expect(page.locator('#sugar-panel')).to_be_visible(timeout=30000)
    expect(page.locator('#sugar-entry')).to_have_value('TREH')
    expect(page.locator('#sugar-preview')).to_contain_text("do not match the reference", timeout=30000)
    expect(page.locator('#sugar-preview .sugar-status')).to_have_attribute('data-ready', 'false')
    expect(page.locator('#start-run')).to_be_disabled()
    assert submissions == []
    assert errors == []


def test_the_sugar_option_is_offered_only_for_a_recognised_sugar(dashboard, live_page):
    dashboard.coordinator.database().replace([])
    page, errors = live_page
    _routes(page, [], live_page.base_url)
    page.add_init_script("localStorage.setItem('ddm.form', JSON.stringify({run_type:'aa_cg',molecule_id:'DDM'}))")
    page.goto(f'{live_page.base_url}/detergent-validation/new-run')
    expect(page.locator('#molecule-directory')).to_have_value('DDM', timeout=30000)

    def option_state():
        return page.evaluate("(() => { const o=document.querySelector('#run-type option[value=sugar_cg]');"
                             "return [o.hidden, o.disabled]; })()")

    assert option_state() == [True, True]
    page.locator('#molecule-directory').select_option('Sucrose')
    page.wait_for_function("() => { const o=document.querySelector('#run-type option[value=sugar_cg]');"
                           "return !o.hidden && !o.disabled; }", timeout=30000)
    page.locator('#run-type').select_option('sugar_cg')
    expect(page.locator('#sugar-panel')).to_be_visible()
    assert errors == []
