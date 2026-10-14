"""The Osmotic Series panel: the sugar and its refusal, the concentrations and the tally, the duration, the
failure behaviour, and the review.

Every claim here is about behaviour the panel has in a real browser against a real server. Most tests answer the
catalogue from the test, because a fixture workspace has no saved mapping and no prepared solute files, and the
point of those tests is the *panel's* handling of each of the three states a sugar can be in. One test goes
through the real route instead, because a stub cannot tell a wrong URL from a right one.

The two-column layout is measured, not eyeballed: two halves have different `x` and each is about half the form.
A stacked panel renders every control too, so a presence assertion would pass on the failure it exists to catch.
"""
import copy
import re

from playwright.sync_api import expect

#: The catalogue the panel reads, in the states the repository is actually in: Maltose has a molecule folder, a
#: saved mapping and its solute files; Sucrose has the first two and is *provisional*; Trehalose is missing one
#: solute file by name; Glucose has a folder in neither place, so it has no mapping and no box.
#:
#: Both failure choices are live, and that is the server's own answer now: the series run's driver honours
#: `series_on_failure` itself, so nothing outside the run type has to exist for `stop` to act.

CATALOGUE = {
    'sugars': [
        {'molecule_id': 'Maltose', 'label': 'Maltose', 'molecule_folder': True,
         'mappings': [{'file': 'mapping_candidate_maltose.json', 'name': 'Maltose carbohydrate paper draft'}],
         'solute_root': '/scratch/workspace/osmotic/maltose',
         'solute_files': ['solute.gro', 'solute.itp', 'water.gro', 'martini_v3.0.0_solvents_v1.itp'],
         'solute_files_present': 4, 'solute_files_missing': [], 'ready': True, 'state': 'ready', 'blockers': [],
         'provisional': False},
        {'molecule_id': 'Sucrose', 'label': 'Sucrose', 'molecule_folder': True,
         'mappings': [{'file': 'mapping_candidate_sucrose.json', 'name': 'Sucrose carbohydrate paper draft'}],
         'solute_root': '/scratch/workspace/osmotic/sucrose',
         'solute_files': ['solute.gro', 'solute.itp', 'water.gro', 'martini_v3.0.0_solvents_v1.itp'],
         'solute_files_present': 0,
         'solute_files_missing': ['solute.gro', 'solute.itp', 'water.gro', 'martini_v3.0.0_solvents_v1.itp'],
         'ready': False, 'state': 'blocked',
         'blockers': ['Solute files not prepared: /scratch/workspace/osmotic/sucrose is missing solute.gro, '
                      'solute.itp, water.gro, martini_v3.0.0_solvents_v1.itp',
                      'The mapping is provisional: the recogniser maps one hexopyranose ring and preserves the '
                      'rest as a draft, so a generated Sucrose mapping is a diagnostic input rather than an '
                      'official Martini parameter set'],
         'provisional': True},
        {'molecule_id': 'Trehalose', 'label': 'Trehalose', 'molecule_folder': True,
         'mappings': [{'file': 'mapping_candidate_trehalose.json', 'name': 'Trehalose carbohydrate paper draft'}],
         'solute_root': '/scratch/workspace/osmotic/trehalose',
         'solute_files': ['solute.gro', 'solute.itp', 'water.gro', 'martini_v3.0.0_solvents_v1.itp'],
         'solute_files_present': 3, 'solute_files_missing': ['water.gro'],
         'ready': False, 'state': 'blocked',
         'blockers': ['Solute files not prepared: /scratch/workspace/osmotic/trehalose is missing water.gro'],
         'provisional': False},
        {'molecule_id': 'Glucose', 'label': 'Glucose', 'molecule_folder': False, 'mappings': [],
         'solute_root': '/scratch/workspace/osmotic/glucose',
         'solute_files': ['solute.gro', 'solute.itp', 'water.gro', 'martini_v3.0.0_solvents_v1.itp'],
         'solute_files_present': 0,
         'solute_files_missing': ['solute.gro', 'solute.itp', 'water.gro', 'martini_v3.0.0_solvents_v1.itp'],
         'ready': False, 'state': 'refused',
         'blockers': ['No saved CG mapping: Glucose has no folder under molecules/, so it has no mapping candidate '
                      'and its beads have no radii to size the box from'],
         'provisional': False},
    ],
    'solute_files': ['solute.gro', 'solute.itp', 'water.gro', 'martini_v3.0.0_solvents_v1.itp'],
    'molality_range': [0.0, 2.5],
    'ns_per_day': 2400.0,
    'failure_policy': {
        'key': 'series_on_failure', 'default': 'carry_on', 'advertised': True, 'attempts_max': 3,
        'driver': 'osmotic_simulation.sh',
        'options': [
            {'value': 'carry_on', 'available': True, 'reason': None,
             'label': 'Carry on — the remaining conditions run; a gap is reported'},
            {'value': 'stop', 'available': True, 'reason': None,
             'label': 'Stop the series on the first failed condition — the conditions after it are not run'},
        ],
    },
    'defaults': {'duration_ns': 500, 'temperature_k': 308.15, 'production_ps': 500000.0,
                 'equilibration_ps': 10000.0, 'output_interval_ps': 10.0},
    'setup': {'box_nm': [5.04156, 5.04156, 10.08312], 'box_volume_nm3': 256.286,
              'dividing_area_nm2': 25.41733, 'confinement_nm': 2.52078,
              'confinement_kj_mol_nm2': 1000.0, 'kappa': 500.0,
              'restraint_kj_mol_nm2': 10000.0, 'seed': 20261006, 'mdrun_ntomp': 4, 'mdrun_ranks': 1},
}


def serve_catalogue(page, catalogue=None):
    """Answer the catalogue from the test. The series reader and the run list are answered by the same call,
    because they are two more requests the panel makes on mount: `test_the_series_as_it_stands_...` and
    `test_the_run_list_is_asked_for_this_run_type_alone` register their own answers after this one, and a later
    registration is the one that wins."""
    serve_conditions(page)
    serve_jobs(page)
    page.route(re.compile(r'/api/osmotic/catalogue'),
               lambda route: route.fulfill(json=catalogue or CATALOGUE))


def serve_conditions(page, conditions=None):
    page.route(re.compile(r'/api/osmotic/conditions'),
               lambda route: route.fulfill(json={'molecule_id': 'Maltose', 'citation': 'doi:10.1016/',
                                                 'conditions': conditions or [], 'measured': 0, 'total': 0,
                                                 'attempts_on_disk': 0}))


def serve_jobs(page, jobs=None, total=None):
    """The run list, as the run-type filter answers it: `{jobs, total, page, limit}`."""
    body = {'jobs': jobs or [], 'total': len(jobs or []) if total is None else total, 'page': 1, 'limit': 20}
    page.route(re.compile(r'/api/jobs\?'),
               lambda route: route.fulfill(json=body))


def open_panel(page, base_url):
    page.goto(f'{base_url}/detergent-validation/osmotic-pressure')
    expect(page.locator('#osmotic-pressure:not([hidden])')).to_be_visible()
    page.wait_for_function("() => document.querySelectorAll('.osmotic-sugar option').length > 1", timeout=30000)


def choose(page, molecule_id):
    page.locator('.osmotic-sugar').select_option(molecule_id)


def test_the_panel_offers_the_sugar_the_concentrations_the_duration_and_the_review(dashboard, live_page):
    """The panel exists, named as the mock names it, with the five measured points as its default."""
    page, errors = live_page
    serve_catalogue(page)
    open_panel(page, live_page.base_url)

    expect(page.locator('#osmotic-pressure h2')).to_have_text('Osmotic Series')
    expect(page.locator('#subtabs .subtab[aria-selected=true]')).to_contain_text('Osmotic Series')

    options = page.evaluate("() => Array.from(document.querySelectorAll('.osmotic-sugar option')).map(o => o.value)")
    assert options == ['Maltose', 'Sucrose', 'Trehalose', 'Glucose'], options
    # The ready sugar opens selected, so the panel is usable without a decision nobody has made yet.
    assert page.locator('.osmotic-sugar').input_value() == 'Maltose'

    # The default set is the five measured points, and the 0.0 control is not among them.
    values = page.evaluate("() => Array.from(document.querySelectorAll('.osmotic-conc-row input')).map(i => i.value)")
    assert values == ['0.5', '1', '1.5', '2', '2.5'], values
    expect(page.locator('.osmotic-count-line')).to_have_text('5 runs · 2,500 ns')
    expect(page.locator('.osmotic-count-detail')).to_contain_text('0.5, 1.0, 1.5, 2.0, 2.5 molal · 500 ns each')
    assert page.locator('[name=osmotic_duration_ns]').input_value() == '500'

    # The review names every value the series will carry.
    expect(page.locator('.osmotic-summary-sugar')).to_have_text('Maltose')
    expect(page.locator('.osmotic-summary-mapping')).to_have_text('Maltose carbohydrate paper draft')
    expect(page.locator('.osmotic-summary-solute')).to_contain_text('4 of 4 present')
    expect(page.locator('.osmotic-summary-count')).to_have_text('5')
    expect(page.locator('.osmotic-summary-conc')).to_have_text('0.5, 1.0, 1.5, 2.0, 2.5 molal')
    expect(page.locator('.osmotic-summary-duration')).to_have_text('500 ns each · 2,500 ns total')
    expect(page.locator('.osmotic-summary-temp')).to_have_text('308.15 K')
    expect(page.locator('.osmotic-review-status')).to_have_text('Ready')
    expect(page.locator('.osmotic-start')).to_be_enabled()

    # The standing values are shown rather than offered, each with the number the pipeline reads.
    setup = page.locator('.osmotic-setup-table').inner_text()
    assert '5.04156' in setup and '25.41733' in setup and '2.52078' in setup and '500' in setup
    assert '20261006' in setup and '10000' in setup
    assert errors == []


def test_the_concentrations_add_remove_edit_and_the_tally_follows(dashboard, live_page):
    """The count equals the rows and the total equals count x duration, in every state."""
    page, errors = live_page
    serve_catalogue(page)
    open_panel(page, live_page.base_url)

    page.locator('.osmotic-add-conc').click()
    expect(page.locator('.osmotic-conc-row')).to_have_count(6)
    expect(page.locator('.osmotic-count-line')).to_have_text('6 runs · 3,000 ns')

    page.locator('.osmotic-conc-row').nth(5).locator('.osmotic-conc-remove').click()
    expect(page.locator('.osmotic-conc-row')).to_have_count(5)
    expect(page.locator('.osmotic-count-line')).to_have_text('5 runs · 2,500 ns')

    # Four rows at 500 ns each is 2,000 ns, and the duration is a number the tally re-reads on every keystroke.
    page.locator('.osmotic-conc-row').nth(4).locator('.osmotic-conc-remove').click()
    expect(page.locator('.osmotic-conc-row')).to_have_count(4)
    expect(page.locator('.osmotic-count-line')).to_have_text('4 runs · 2,000 ns')
    assert page.locator('.osmotic-summary-count').inner_text() == '4'
    assert page.locator('.osmotic-summary-duration').inner_text() == '500 ns each · 2,000 ns total'

    page.locator('[name=osmotic_duration_ns]').fill('250')
    expect(page.locator('.osmotic-count-line')).to_have_text('4 runs · 1,000 ns')

    # Reset restores exactly the five measured points -- the concentrations, which is what its label names. The
    # duration is the user's own number and Reset leaves it alone.
    page.locator('.osmotic-reset-conc').click()
    values = page.evaluate("() => Array.from(document.querySelectorAll('.osmotic-conc-row input')).map(i => i.value)")
    assert values == ['0.5', '1', '1.5', '2', '2.5'], values
    assert page.locator('[name=osmotic_duration_ns]').input_value() == '250'
    expect(page.locator('.osmotic-count-line')).to_have_text('5 runs · 1,250 ns')
    assert errors == []


def test_a_molality_outside_the_paper_range_is_refused_at_the_row_and_excluded_from_the_count(dashboard, live_page):
    """The bound is the route's own (`osmotic_molality`, 0.0-2.5), it is named, and nothing is queued until fixed."""
    page, errors = live_page
    serve_catalogue(page)
    open_panel(page, live_page.base_url)

    page.locator('.osmotic-conc-row').first.locator('input').fill('3.0')
    warning = page.locator('.osmotic-range-warning')
    expect(warning).to_be_visible()
    expect(warning).to_contain_text('3.0')
    expect(warning).to_contain_text('0.0–2.5')
    # The offending row is out of the count, so five rows with one bad read four.
    expect(page.locator('.osmotic-count-line')).to_have_text('4 runs · 2,000 ns')
    expect(page.locator('.osmotic-start')).to_be_disabled()

    # The bound is inclusive at 2.5, so the top measured point is not refused.
    page.locator('.osmotic-conc-row').first.locator('input').fill('2.5')
    expect(warning).to_be_hidden()
    expect(page.locator('.osmotic-count-line')).to_have_text('5 runs · 2,500 ns')
    expect(page.locator('.osmotic-start')).to_be_enabled()

    # A 0.0 row is legitimate, counted, and says what it is: the control, with no measurement.
    page.locator('.osmotic-conc-row').first.locator('input').fill('0.0')
    expect(page.locator('.osmotic-count-line')).to_have_text('5 runs · 2,500 ns')
    expect(page.locator('.osmotic-conc-row').first).to_contain_text('0.0 control')
    expect(page.locator('.osmotic-start')).to_be_enabled()
    assert errors == []


def test_a_sugar_with_no_mapping_is_refused_with_the_reason_and_start_is_disabled(dashboard, live_page):
    """Refuse with a reason, never a generic 'cannot run': the refusal names the missing mapping."""
    page, errors = live_page
    serve_catalogue(page)
    open_panel(page, live_page.base_url)

    choose(page, 'Glucose')
    status = page.locator('.osmotic-sugar-status')
    expect(status).to_contain_text('Refused')
    expect(status).to_contain_text('Glucose has no folder under molecules/')
    expect(page.locator('.osmotic-review-status')).to_have_text('Blocked')
    expect(page.locator('.osmotic-start')).to_be_disabled()
    expect(page.locator('.osmotic-review-note')).to_contain_text('no mapping')
    assert errors == []


def test_a_sugar_with_a_mapping_but_no_solute_files_names_the_file_that_is_missing(dashboard, live_page):
    """Blocked is not refused: the mapping exists and the file that is not there is named in the text."""
    page, errors = live_page
    serve_catalogue(page)
    open_panel(page, live_page.base_url)

    choose(page, 'Trehalose')
    status = page.locator('.osmotic-sugar-status')
    expect(status).to_contain_text('Blocked')
    expect(status).to_contain_text('water.gro')
    expect(page.locator('.osmotic-start')).to_be_disabled()

    # Sucrose says the second thing the repository says about it: the mapping is provisional.
    choose(page, 'Sucrose')
    expect(page.locator('.osmotic-sugar-status')).to_contain_text('provisional')

    panel_text = page.locator('#osmotic-pressure').inner_text()
    assert 'does not establish scientific validation' in panel_text, panel_text[-600:]
    assert errors == []


def test_the_two_halves_sit_side_by_side_and_stack_at_the_breakpoint(dashboard, live_page):
    """Measured, not merely present: twelve tracks, different x, each about half the form; one column at 1000 px."""
    page, errors = live_page
    serve_catalogue(page)
    open_panel(page, live_page.base_url)

    tracks = page.evaluate("() => getComputedStyle(document.querySelector('.osmotic-layout')).gridTemplateColumns")
    assert len(tracks.split()) == 12, tracks

    form = page.locator('.osmotic-layout').bounding_box()
    inputs = page.locator('.osmotic-inputs').bounding_box()
    settings = page.locator('.osmotic-settings').bounding_box()
    assert inputs['x'] < settings['x'], (inputs, settings)
    assert settings['x'] >= inputs['x'] + inputs['width'] - 1, 'the halves overlap: they are not side by side'
    assert settings['x'] + settings['width'] <= form['x'] + form['width'] + 1, 'the right half leaves the form'
    half = form['width'] / 2
    assert abs(inputs['width'] - half) <= 20, (inputs['width'], half)
    assert abs(settings['width'] - half) <= 20, (settings['width'], half)

    page.set_viewport_size({'width': 1000, 'height': 900})
    stacked = (page.locator('.osmotic-inputs').bounding_box(), page.locator('.osmotic-settings').bounding_box())
    assert stacked[1]['y'] >= stacked[0]['y'] + stacked[0]['height'] - 1, stacked

    # And nothing in the panel widens the page at a phone width. The failure choice's own labels were the one
    # place it did: a bare text node in a flex row did not shrink, so it ran past the card at every width.
    page.set_viewport_size({'width': 390, 'height': 844})
    assert page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth") == 0
    assert errors == []


def test_the_failure_choice_offers_both_radios_and_both_are_live(dashboard, live_page):
    """Both choices are offered and both act: the series run's own driver honours `series_on_failure`."""
    page, errors = live_page
    serve_catalogue(page)
    open_panel(page, live_page.base_url)

    assert page.evaluate("() => Array.from(document.querySelectorAll('input[name=osmotic_series_on_failure]'))"
                         ".map(r => r.value)") == ['carry_on', 'stop']
    assert page.locator('input[name=osmotic_series_on_failure][value=carry_on]').is_checked(), 'carrying on is the default'
    assert page.locator('.osmotic-onfail-stop').is_enabled(), 'the series run honours the stop itself'
    expect(page.locator('.osmotic-stop-reason')).to_be_hidden()
    expect(page.locator('.osmotic-summary-onfail')).to_have_text(
        'Resume from the last checkpoint, up to 3 attempts · then carry on')
    # The retry note names the flag and the ceiling in `code`: written as a text node, the markup showed as
    # "(code>gmx mdrun -cpi</code>" on the page and the screenshot was what caught it.
    expect(page.locator('.osmotic-retry-note code')).to_have_count(2)
    assert '(code>' not in page.locator('.osmotic-retry-note').inner_text()
    assert errors == []


def test_a_choice_the_server_cannot_honour_is_offered_disabled_with_its_reason(dashboard, live_page):
    """The panel still renders the state a choice with no acting half would be in -- with its reason on it.

    Nothing is in that state today: both choices are the run type's own. The rendering is kept because the answer
    arrives from the server (`available` and a `reason`), and a panel that rendered an unavailable choice as if it
    worked would be offering a control that silently does nothing.
    """
    page, errors = live_page
    unavailable = copy.deepcopy(CATALOGUE)
    unavailable['failure_policy']['options'][1].update(
        available=False, reason='Not available: the run type does not carry a series_on_failure setting.')
    serve_catalogue(page, unavailable)
    open_panel(page, live_page.base_url)

    assert page.locator('.osmotic-onfail-stop').is_disabled()
    expect(page.locator('.osmotic-stop-reason')).to_contain_text('does not carry a series_on_failure setting')
    assert page.locator('input[name=osmotic_series_on_failure][value=carry_on]').is_checked(), (
        'a choice that cannot act is not left selected')
    assert errors == []


def test_the_panel_queues_the_payload_the_osmotic_route_reads(dashboard, live_page):
    """The body carries the keys `routes/osmotic.series_api` reads, and nothing it would refuse."""
    page, errors = live_page
    posted = {}
    serve_catalogue(page)

    def queue(route):
        if route.request.method != 'POST':
            route.fallback()
            return
        posted.update(route.request.post_data_json or {})
        route.fulfill(status=201, json={'series_id': 'abc123abc123', 'run_id': 'run000000001',
                                        'count': 5, 'molalities': [0.5, 1.0, 1.5, 2.0, 2.5]})

    page.route(re.compile(r'/api/osmotic/series'), queue)
    open_panel(page, live_page.base_url)
    expect(page.locator('.osmotic-start')).to_be_enabled()
    page.locator('.osmotic-start').click()

    # The notice names the count, the run and the series: one run owns the concentrations.
    expect(page.locator('#notice')).to_contain_text('5 conditions', timeout=30000)
    expect(page.locator('#notice')).to_contain_text('run run000000001')
    expect(page.locator('#notice')).to_contain_text('abc123abc123')
    assert posted == {
        'molecule_id': 'Maltose',
        'mapping_candidate': 'mapping_candidate_maltose.json',
        'molalities': [0.5, 1.0, 1.5, 2.0, 2.5],
        'osmotic_production_ps': 500000,
        'temperature_k': 308.15,
        'solute_root': '/scratch/workspace/osmotic/maltose',
        'series_on_failure': 'carry_on',
    }, posted
    assert errors == []


def test_the_panel_renders_the_route_it_is_wired_to(dashboard, live_page):
    """No stub: the real catalogue answers, so a wrong URL or a missing section cannot pass as a working panel."""
    page, errors = live_page
    serve_conditions(page)
    open_panel(page, live_page.base_url)

    # The registry names four carbohydrates; the fixture workspace has a folder for three and a mapping for none.
    options = page.evaluate("() => Array.from(document.querySelectorAll('.osmotic-sugar option')).map(o => o.value)")
    assert options == ['Maltose', 'Sucrose', 'Trehalose', 'Glucose'], options
    expect(page.locator('.osmotic-sugar-status')).to_contain_text('Solute files not prepared')
    expect(page.locator('.osmotic-start')).to_be_disabled()
    assert errors == []


def test_the_series_as_it_stands_is_rendered_from_the_route_and_not_recomputed(dashboard, live_page):
    """The control row has no measurement by construction and is shown as a row, not dropped; no curve is drawn."""
    page, errors = live_page
    serve_catalogue(page)
    # Registered after `serve_catalogue`, so this answer is the one the panel's reader gets.
    serve_conditions(page, conditions=[
        {'run_id': 'control00001', 'molality_requested': 0.0, 'solute_molecules': 0, 'measured': None},
        {'run_id': 'measured0001', 'molality_requested': 0.5, 'solute_molecules': 70, 'measured': None,
         'paper': {'pressure_bar': 13.04, 'uncertainty_bar': 0.04}},
    ])
    open_panel(page, live_page.base_url)

    rows = page.locator('.osmotic-series-rows tr')
    expect(rows).to_have_count(2)
    expect(rows.nth(0)).to_contain_text('— control')
    expect(rows.nth(1)).to_contain_text('13.04')
    assert errors == []


def test_choosing_stop_lands_in_the_review_and_in_the_payload(dashboard, live_page):
    """When the server can honour a stop -- which it now can -- the radio is live and the choice travels."""
    page, errors = live_page
    posted = {}
    serve_catalogue(page)

    def queue(route):
        if route.request.method != 'POST':
            route.fallback()
            return
        posted.update(route.request.post_data_json or {})
        route.fulfill(status=201, json={'series_id': 'stopseries0', 'run_id': 'run000000002',
                                        'count': 5, 'molalities': [0.5, 1.0, 1.5, 2.0, 2.5]})

    page.route(re.compile(r'/api/osmotic/series'), queue)
    open_panel(page, live_page.base_url)

    assert page.locator('.osmotic-onfail-stop').is_enabled(), \
        'the series run is its own driver, so the choice is always available'
    expect(page.locator('.osmotic-stop-reason')).to_be_hidden()

    page.locator('.osmotic-onfail-stop').check()
    expect(page.locator('.osmotic-summary-onfail')).to_have_text(
        'Resume from the last checkpoint, up to 3 attempts · then stop the series')

    page.locator('.osmotic-start').click()
    expect(page.locator('#notice')).to_contain_text('5 conditions', timeout=30000)
    assert posted['series_on_failure'] == 'stop', posted
    assert errors == []


# --- the run list, through the run-type filter ------------------------------------------------------------------

def test_the_run_list_is_asked_for_this_run_type_alone(dashboard, live_page):
    """The panel asks `/api/jobs` for `run_type=osmotic`, and renders the runs it is given.

    This is the panel's half of the filter: without it the run list would be every run in the repository, and the
    panel would be filtering in the browser after a page had already been chosen.
    """
    page, errors = live_page
    asked = []

    def jobs(route):
        asked.append(route.request.url)
        route.fulfill(json={'jobs': [
            {'id': 'series000001', 'label': 'Maltose osmotic series · 5 conditions', 'status': 'completed',
             'run_type': 'osmotic', 'settings': {'molalities': [0.5, 1.0, 1.5, 2.0, 2.5]}},
            {'id': 'series000002', 'label': 'Maltose osmotic series · 2 conditions', 'status': 'failed',
             'run_type': 'osmotic', 'settings': {'molalities': [0.5, 1.0]}},
        ], 'total': 2, 'page': 1, 'limit': 20})

    serve_catalogue(page)
    page.route(re.compile(r'/api/jobs\?'), jobs)
    open_panel(page, live_page.base_url)

    expect(page.locator('.osmotic-run-rows tr')).to_have_count(2)
    assert all('run_type=osmotic' in url for url in asked), asked
    rows = page.locator('.osmotic-run-rows tr')
    expect(rows.nth(0)).to_contain_text('series000001')
    expect(rows.nth(0)).to_contain_text('completed')
    expect(rows.nth(0)).to_contain_text('5')
    expect(rows.nth(1)).to_contain_text('series000002')
    expect(page.locator('.osmotic-runs-note')).to_contain_text('2 of 2 run(s)')
    assert errors == []


def test_a_condition_that_failed_is_a_row_that_says_so(dashboard, live_page):
    """The gap a series leaves is shown as failed -- not as a condition nobody has got to yet."""
    page, errors = live_page
    serve_catalogue(page)
    serve_conditions(page, conditions=[
        {'run_id': 'series000001', 'condition': '00_0.5molal', 'molality_requested': 0.5, 'solute_molecules': 70,
         'measured': None, 'state': 'failed'},
        {'run_id': 'series000001', 'condition': '01_1molal', 'molality_requested': 1.0, 'solute_molecules': 0,
         'measured': None, 'state': 'complete'},
    ])
    open_panel(page, live_page.base_url)

    rows = page.locator('.osmotic-series-rows tr')
    expect(rows).to_have_count(2)
    expect(rows.nth(0)).to_contain_text('— failed')
    expect(rows.nth(1)).to_contain_text('— not measured')
    assert errors == []
