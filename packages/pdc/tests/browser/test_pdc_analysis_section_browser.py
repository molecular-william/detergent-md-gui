"""The Run view's Structure and interactions section over a published `pdc-structure` record.

Two states are pinned here: a pdc run that has never published one gets the empty state and its Calculate button
posts to the engine's generic queue route; a published record draws the leg, the sample, the figures, the method and
the report's own caveats. A third case is the two states a run's record itself carries: no protein, and the fallback
production leg.

The record is written here the way `analysis.worker` leaves one behind -- an immutable attempt under
`analyses/pdc-structure/<signature>/<attempt>/` whose `result.json` names the content-addressed output directory --
and nothing in it is read from the developer's workspace.
"""
import json

from playwright.sync_api import expect

JOB = '0000000000ad'
RUN_VIEW = f'/protein-detergent/run-view?run={JOB}'
CARD = '#run-view-analysis-A'
SECTION = 'pdc-structure'

RECORD = {
    'kind': 'pdc-structure',
    'schema_version': 1,
    'leg': {
        'name': 'CG extension MD', 'stage_directory': '08_extension',
        'trajectory': 'stages/08_extension/prod/whole.xtc',
        'structure': 'stages/08_extension/prod/run.gro',
        'run_input': 'stages/08_extension/prod/run.tpr',
        'chosen_by': "the run's own segmenter: the latest playable segment",
        'fallback_reason': None,
    },
    'sampling': {'frames_in_file': 45001, 'frames_sampled': 200, 'stride': 226, 'first_ns': 0.0,
                 'last_ns': 900.0, 'span_ns': 900.0, 'frame_dt_ps': 20.0,
                 'read': 'one gmx trjconv sample extracted once (sample.xtc)'},
    'micelle': {'definition': 'largest connected cluster of tail beads, run criterion',
                'contact_nm': 0.6, 'aggregation_number_requested': 80,
                'tail_beads': ['TAIL1', 'TAIL2', 'TAIL3'], 'detergent_residue': 'DDM'},
    'shape_nm': {
        'rg': {'tool': 'gmx gyrate', 'weighting': 'mass', 'mean': 2.41, 'sem': 0.02,
               'axis_components_nm': {'Rg/sX/N': 2.1, 'Rg/sY/N': 2.2, 'Rg/sZ/N': 2.0},
               'series': {'time_ns': [], 'rg_nm': []}},
        'gyration_eigenvalues_nm2': {'tool': 'producer (numpy eigvalsh)', 'mean': [1.2, 1.1, 1.0]},
        'asphericity_nm2': {'formula': 'λ1 - (λ2 + λ3)/2', 'mean': 0.14, 'sem': 0.01},
        'relative_shape_anisotropy': {'formula': '(3/2)(Σλ²/(Σλ)² - 1/3)', 'mean': 0.02, 'sem': 0.0},
        'subject': 'every detergent bead in the sample',
    },
    'aggregation': {'largest_mean': 92.0, 'cluster_count_mean': 4.0, 'free_mean': 7.0,
                    'size_distribution': {'bins': [92], 'counts': [200]}},
    'rdf': [
        {'tool': 'gmx rdf', 'first': 'protein', 'second': 'head', 'r_nm': [0.0, 0.05], 'g': [0.0, 0.2],
         'norm': 'rdf', 'excl': False, 'normalization': 'gmx rdf -norm rdf',
         'bin_width_nm': 0.05, 'r_max_nm': 2.0, 'first_peak_nm': 0.47, 'first_peak_g': 2.1},
        {'tool': 'gmx rdf', 'first': 'head', 'second': 'head', 'r_nm': [0.0, 0.05], 'g': [0.0, 0.3],
         'norm': 'rdf', 'excl': True, 'normalization': 'gmx rdf -norm rdf',
         'bin_width_nm': 0.05, 'r_max_nm': 2.0, 'first_peak_nm': 0.52, 'first_peak_g': 2.4},
        {'tool': 'gmx rdf', 'first': 'tail', 'second': 'tail', 'r_nm': [0.0, 0.05], 'g': [0.0, 0.4],
         'norm': 'rdf', 'excl': True, 'normalization': 'gmx rdf -norm rdf',
         'bin_width_nm': 0.05, 'r_max_nm': 2.0, 'first_peak_nm': 0.54, 'first_peak_g': 2.6},
    ],
    'contacts': {'definition': 'protein bead–detergent bead pairs within the cutoff; not hydrogen bonds',
                 'tool': 'gmx mindist -on', 'cutoff_nm': 0.6, 'group': False, 'mean': 318.0, 'sem': 11.0,
                 'series': {'time_ns': [], 'contacts': []}},
    'commands': [{'step': 'extract sample', 'argv': ['gmx', 'trjconv']}],
    'method': ("one bounded sample of one production leg: gmx gyrate (Rg), gmx rdf (radial distributions) and "
               'gmx mindist -on (bead contacts); the run\'s own micelle criterion'),
    'caveats': ['A bounded sample, not an ensemble: 200 of 45,001 frames.',
                'Not validation: scientifically_validated is false.'],
    'scientifically_validated': False,
    'protein_present': True,
}


def seed_run(dashboard):
    """A completed pdc run with one production stage, so the monitor has a run to open."""
    prod = dashboard.coordinator.RUNS / JOB / 'stages/06_assessment/prod'
    prod.mkdir(parents=True)
    (prod / 'run.xtc').write_bytes(b'raw')
    (prod / 'run.tpr').write_bytes(b'tpr')
    (prod / 'run.gro').write_text('gro')
    dashboard.coordinator.database().insert({'id': JOB, 'run_type': 'pdc', 'status': 'completed',
                                             'stage': 'complete', 'molecule_id': 'DDM',
                                             'label': 'A pdc run',
                                             'created': '2026-11-09T00:00:00+00:00'})


def publish(dashboard, record=None):
    """Leave behind what `analysis.worker` leaves behind for a completed pdc-structure attempt."""
    published = record if record is not None else RECORD
    attempt = dashboard.coordinator.RUNS / JOB / 'analyses/pdc-structure/hash/attempt1'
    output = attempt / 'output/abc123'
    output.mkdir(parents=True)
    (output / 'pdc-structure.json').write_text(json.dumps(published))
    (attempt / 'result.json').write_text(json.dumps(
        {'result': published, 'output_directory': 'output/abc123', 'wall_seconds': 16.0}))
    return attempt


def open_section(page, live_page):
    page.goto(f'{live_page.base_url}{RUN_VIEW}')
    root = page.locator(CARD)
    expect(root.locator('.analysis-views button').first).to_be_visible(timeout=30000)
    root.locator(f'.analysis-views button[data-section="{SECTION}"]').click()
    pane = root.locator(f'.analysis-pane[data-section="{SECTION}"]')
    expect(pane).to_be_visible()
    return pane


def test_the_section_is_a_tab_and_starts_with_nothing_computed(dashboard, live_page):
    """A pdc run that never queued the kind says so, and its button queues through the generic route."""
    seed_run(dashboard)
    page, errors = live_page
    root = page.locator(CARD)
    page.goto(f'{live_page.base_url}{RUN_VIEW}')
    expect(root.locator('.analysis-views button').first).to_be_visible(timeout=30000)

    tabs = root.locator('.analysis-views button').all_text_contents()
    assert 'Structure and interactions' in tabs, tabs

    root.locator(f'.analysis-views button[data-section="{SECTION}"]').click()
    pane = root.locator(f'.analysis-pane[data-section="{SECTION}"]')
    expect(pane.locator('.pds-empty')).to_contain_text('Nothing computed yet', timeout=30000)
    posted = []

    def hold(route):
        if route.request.method != 'POST':
            route.continue_()
            return
        posted.append(route.request.url)
        route.fulfill(status=202, content_type='application/json', body=json.dumps(
            {'id': 'queued1', 'kind': 'pdc-structure', 'status': 'queued',
             'created_at': '2026-11-09T00:00:00+00:00'}))

    page.route(f'**/api/jobs/{JOB}/pdc-structure', hold)
    pane.get_by_role('button', name='Calculate structure').click()
    page.wait_for_function('() => true')
    assert posted == [f'{live_page.base_url}/api/jobs/{JOB}/pdc-structure'], posted
    assert errors == [], errors


def test_a_published_record_draws_the_leg_the_figures_and_the_caveats(dashboard, live_page):
    seed_run(dashboard)
    publish(dashboard)
    page, errors = live_page
    pane = open_section(page, live_page)

    expect(pane.locator('.pds-status')).to_contain_text('CG extension MD', timeout=30000)
    expect(pane.locator('.pds-status')).to_contain_text('200 of 45,001 frames')
    expect(pane.locator('.pds-fig', has_text='Radius of gyration')).to_contain_text('2.41')
    expect(pane.locator('.pds-fig', has_text='Largest cluster')).to_contain_text('92.0')
    expect(pane.locator('.pds-fig', has_text='Free detergents')).to_contain_text('7.0')
    # The first peaks are the record's own, one figure per curve, with units.
    expect(pane.locator('.pds-fig', has_text='protein→head')).to_contain_text('0.47')
    expect(pane.locator('.pds-fig', has_text='head–head')).to_contain_text('0.52')
    expect(pane.locator('.pds-fig', has_text='tail–tail')).to_contain_text('0.54')
    expect(pane.locator('.pds-fig', has_text='Protein–detergent beads within 0.60 nm')).to_contain_text('318')
    expect(pane.locator('.pds-meta').first).to_contain_text('gmx gyrate')
    expect(pane.locator('.pds-meta').nth(1)).to_contain_text('spanning 900.0 ns')
    expect(pane.locator('.pds-caveat')).to_contain_text('A bounded sample, not an ensemble')
    expect(pane.get_by_role('button', name='Recalculate structure')).to_be_visible()
    assert errors == [], errors


def test_a_no_protein_record_states_the_interface_as_not_defined_and_names_its_fallback_leg(dashboard, live_page):
    """The two states §8 draws: no protein, and the assessment leg that answered instead of the extension."""
    seed_run(dashboard)
    record = json.loads(json.dumps(RECORD))
    record['protein_present'] = False
    record['contacts'] = None
    record['rdf'] = [curve for curve in record['rdf'] if curve['first'] != 'protein']
    record['leg'].update({'name': 'CG assessment MD', 'stage_directory': '06_assessment',
                          'trajectory': 'stages/06_assessment/prod/whole.xtc',
                          'fallback_reason': 'the run switched out-of-micelle removal off, so there is nothing '
                                             'to extend or assess'})
    publish(dashboard, record)
    page, errors = live_page
    pane = open_section(page, live_page)

    expect(pane.locator('.pds-notice').first).to_contain_text('This run has no protein', timeout=30000)
    expect(pane.locator('.pds-notice').nth(1)).to_contain_text('out-of-micelle removal off')
    expect(pane.locator('.pds-fig', has_text='Protein–detergent contacts')).to_contain_text('not defined')
    expect(pane.locator('.pds-fig', has_text='protein→head')).to_have_count(0)
    assert errors == [], errors
