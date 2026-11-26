"""The PDC analysis tab over a completed protein-detergent run.

The tab replaces the old Complexes panel: one completed run at a time, its newest published `pdc-structure` record and
the run's own `trajectory-overview`, with the two Compute buttons that queue those kinds. The routes are intercepted
here because a published attempt is an immutable directory the worker writes; what the tab owes a reader is the
render, the states and the requests it makes, and those are what these cases pin.

The contract the mocks hold is the real one: `GET /api/jobs/<id>/pdc-structure` answers the record plus
`figures: [{name, path}]`, each figure fetched through `/api/jobs/<id>/artifacts/<path>?inline=1`, and the overview is
found through `GET /api/jobs/<id>/analyses?view=summary` and read through the same artifact route.
"""
from __future__ import annotations

import base64
import re
from urllib.parse import unquote, urlsplit

from playwright.sync_api import expect

from tests.harness import browser

JOB = '0000000000bd'
RUNNING = '0000000000be'
CG_RUN = '0000000000bf'
PANEL = '/protein-detergent/complexes'
RUN_LIST = '/protein-detergent/runs'

#: A valid 1x1 PNG, so the published figures are images the page actually decodes.
PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==')

JOBS = {'jobs': [
    {'id': JOB, 'run_type': 'pdc', 'status': 'completed', 'label': 'DM_2ydo_144_libconf_500ns',
     'molecule_id': 'DDM', 'created': '2026-11-20T00:00:00+00:00'},
    {'id': RUNNING, 'run_type': 'pdc', 'status': 'running', 'label': 'DDM_2ydo_192_libconf_500ns-4',
     'molecule_id': 'DDM', 'created': '2026-11-21T00:00:00+00:00'},
    {'id': CG_RUN, 'run_type': 'cg', 'status': 'completed', 'label': 'a CG run',
     'molecule_id': 'DDM', 'created': '2026-11-19T00:00:00+00:00'},
], 'total': 3, 'page': 1, 'limit': 100}

FIGURE_NAMES = ('pdc-structure-rdf.png', 'pdc-structure-contacts-protein.png',
                'pdc-structure-contacts-water.png', 'pdc-structure-shape.png',
                'pdc-structure-aggregation.png')
ATTEMPT = 'analyses/pdc-structure/0002-20261124'
OVERVIEW_DIRECTORY = 'analyses/trajectory-overview/0001-20261123'


def figure_paths():
    return [{'name': name, 'path': f'{ATTEMPT}/output/abc123/{name}'} for name in FIGURE_NAMES]


V2 = {
    'kind': 'pdc-structure', 'schema_version': 2,
    'leg': {'name': 'CG extension MD', 'stage_directory': '08_extension',
            'trajectory': 'stages/08_extension/prod/whole.xtc',
            'structure': 'stages/08_extension/prod/run.gro',
            'chosen_by': 'the latest playable production segment', 'fallback_reason': None},
    'sampling': {'frames_in_file': 45001, 'frames_sampled': 200, 'stride': 226, 'first_ns': 0.0,
                 'last_ns': 900.0, 'span_ns': 900.0, 'frame_dt_ps': 20.0,
                 'read': 'one gmx trjconv sample extracted once'},
    'thresholds': {'rdf_bin_nm': 0.05, 'rdf_rmax_nm': 2.0, 'contact_nm': 0.6, 'water_cutoff_nm': 0.6},
    'micelle': {'definition': 'largest connected cluster of tail beads, the run criterion',
                'contact_nm': 0.6, 'aggregation_number_requested': 144,
                'tail_beads': ['C1', 'C2', 'C3'], 'detergent_residue': 'DDM'},
    'shape_nm': {
        'rg': {'tool': 'gmx gyrate', 'weighting': 'mass', 'mean': 3.21, 'sem': 0.02, 'series': {}},
        'gyration_eigenvalues_nm2': {'mean': [12.1, 9.4, 7.8]},
        'asphericity': {'mean': 0.14, 'sem': 0.01},
        'relative_shape_anisotropy': {'mean': 0.07, 'sem': 0.0},
        'subject': 'the detergent micelle'},
    'aggregation': {'largest_mean': 141.0, 'cluster_count_mean': 2.0, 'free_mean': 3.0,
                    'size_distribution': {'bins': [141, 2, 3], 'counts': [180, 180, 20]}},
    'rdf': [
        {'tool': 'gmx rdf', 'first': 'protein', 'second': 'head', 'r_nm': [0.05, 0.1],
         'g': [0.1, 0.2], 'norm': 'rdf', 'excl': False, 'bin_width_nm': 0.05, 'r_max_nm': 2.0,
         'first_peak_nm': 1.18, 'first_peak_g': 1.31},
        {'tool': 'gmx rdf', 'first': 'protein', 'second': 'tail', 'r_nm': [0.05, 0.1],
         'g': [0.1, 0.2], 'norm': 'rdf', 'excl': False, 'bin_width_nm': 0.05, 'r_max_nm': 2.0,
         'first_peak_nm': 0.96, 'first_peak_g': 1.95},
        {'tool': 'gmx rdf', 'first': 'head', 'second': 'head', 'r_nm': [0.05, 0.1],
         'g': [0.1, 0.2], 'norm': 'rdf', 'excl': True, 'bin_width_nm': 0.05, 'r_max_nm': 2.0,
         'first_peak_nm': 0.71, 'first_peak_g': 2.10},
        {'tool': 'gmx rdf', 'first': 'tail', 'second': 'tail', 'r_nm': [0.05, 0.1],
         'g': [0.1, 0.2], 'norm': 'rdf', 'excl': True, 'bin_width_nm': 0.05, 'r_max_nm': 2.0,
         'first_peak_nm': 0.54, 'first_peak_g': 2.45},
    ],
    'contacts': {
        'definition': 'beads of the second selection within r of the first, minimum image; not hydrogen bonds',
        'tool': 'gmx mindist -on', 'group': False, 'cutoff_nm': 0.6, 'mean': 318.0, 'sem': 11.0,
        'series': {'time_ns': [], 'contacts': []},
        'groups': [
            {'first': 'protein', 'second': 'head', 'cutoff_nm': 0.6, 'mean': 208.0, 'sem': 7.0,
             'series': {'time_ns': [], 'contacts': []}, 'definition': 'bead pairs, not H-bonds'},
            {'first': 'protein', 'second': 'tail', 'cutoff_nm': 0.6, 'mean': 331.0, 'sem': 10.0,
             'series': {'time_ns': [], 'contacts': []}, 'definition': 'bead pairs, not H-bonds'},
            {'first': 'water', 'second': 'head', 'cutoff_nm': 0.6, 'mean': 1842.0, 'sem': 39.0,
             'series': {'time_ns': [], 'contacts': []},
             'definition': 'W beads within r of head beads; a bead count, not an all-atom hydration number'},
            {'first': 'water', 'second': 'tail', 'cutoff_nm': 0.6, 'mean': 2415.0, 'sem': 52.0,
             'series': {'time_ns': [], 'contacts': []},
             'definition': 'W beads within r of tail beads; a bead count, not an all-atom hydration number'},
        ],
    },
    'method': ('one bounded sample of one production leg, read by gmx gyrate (Rg), gmx rdf and gmx mindist; the '
               "run's own micelle criterion"),
    'caveats': ['A bounded sample, not an ensemble: 200 of 45,001 frames.',
                'Not validation: scientifically_validated is false.'],
    'scientifically_validated': False,
    'protein_present': True,
    'attempt': '0002-20261124', 'published_at': '2026-11-24T10:12:00+00:00',
    'source': f'{JOB}/{ATTEMPT}/output/abc123/pdc-structure.json',
    'figures': figure_paths(),
}

V1 = {
    'kind': 'pdc-structure', 'schema_version': 1,
    'leg': {'name': 'CG assessment MD', 'stage_directory': '06_assessment',
            'trajectory': 'stages/06_assessment/prod/whole.xtc',
            'structure': 'stages/06_assessment/prod/run.gro',
            'chosen_by': 'the latest playable production segment',
            'fallback_reason': 'the run switched out-of-micelle removal off, so there is nothing to extend'},
    'sampling': {'frames_in_file': 25001, 'frames_sampled': 200, 'stride': 126, 'first_ns': 0.0,
                 'last_ns': 500.0, 'span_ns': 500.0, 'frame_dt_ps': 20.0,
                 'read': 'one gmx trjconv sample extracted once'},
    'micelle': {'definition': 'largest connected cluster of tail beads, the run criterion',
                'contact_nm': 0.6, 'aggregation_number_requested': 144,
                'tail_beads': ['C1', 'C2', 'C3'], 'detergent_residue': 'DDM'},
    'shape_nm': {
        'rg': {'mean': 2.41, 'sem': 0.02},
        'asphericity_nm2': {'mean': 0.14, 'sem': 0.01},
        'relative_shape_anisotropy': {'mean': 0.02, 'sem': 0.0},
    },
    'aggregation': {'largest_mean': 92.0, 'cluster_count_mean': 4.0, 'free_mean': 7.0,
                    'size_distribution': {'bins': [], 'counts': []}},
    'rdf': [
        {'first': 'protein', 'second': 'head', 'r_nm': [0.05], 'g': [0.1],
         'bin_width_nm': 0.05, 'r_max_nm': 2.0, 'first_peak_nm': 0.47, 'first_peak_g': 2.1},
        {'first': 'head', 'second': 'head', 'r_nm': [0.05], 'g': [0.1],
         'bin_width_nm': 0.05, 'r_max_nm': 2.0, 'first_peak_nm': 0.52, 'first_peak_g': 2.4},
        {'first': 'tail', 'second': 'tail', 'r_nm': [0.05], 'g': [0.1],
         'bin_width_nm': 0.05, 'r_max_nm': 2.0, 'first_peak_nm': 0.54, 'first_peak_g': 2.6},
    ],
    'contacts': {'definition': 'protein–detergent bead pairs within the cutoff; not hydrogen bonds',
                 'tool': 'gmx mindist -on', 'cutoff_nm': 0.6, 'group': False, 'mean': 318.0, 'sem': 11.0,
                 'series': {'time_ns': [], 'contacts': []}},
    'caveats': ['A bounded sample, not an ensemble.'],
    'scientifically_validated': False, 'protein_present': True,
    'attempt': '0001-20261001', 'published_at': '2026-10-01T09:00:00+00:00',
    'source': f'{JOB}/analyses/pdc-structure/0001-20261001/output/def456/pdc-structure.json',
    'figures': [],
}

OVERVIEW = {
    'segment': 'CG assessment MD',
    'frames_in_file': 25001, 'frames_sampled': 199, 'stride': 126,
    'subject': 'the protein',
    'rmsd_nm': {'mean': 0.41, 'se': 0.01},
    'rmsf_nm': {'mean': 0.29, 'max': 0.51, 'atoms': 3000},
    'gyration_nm': {'mean': 10.56, 'se': 0.03},
    'energy': {'source': 'run.edr', 'components': {
        'Potential': {'mean': -209000.0}, 'LJ-(SR)': {'mean': -187000.0},
        'Coulomb-(SR)': {'mean': -20400.0}}},
    'energy_absent': None,
    'scientifically_validated': False,
}


def task(kind, status, *, error=None, directory=None, created='2026-11-24T10:00:00+00:00'):
    return {'id': f'{kind}-{status}', 'kind': kind, 'status': status, 'error': error,
            'directory': directory, 'created_at': created}


class Stub:
    """The panel's five reads, answered from one mutable state rather than from five separate stubs.

    `record` is the `pdc-structure` answer (``None`` -> the 404), `tasks` the analyses summary, and `overview_data`
    the published overview the artifact route serves when a `completed` overview task names a directory.
    """

    def __init__(self, page, *, record=None, tasks=(), overview_data=None):
        self.page = page
        self.record = record
        self.tasks = list(tasks)
        self.overview_data = overview_data
        self.posts = []
        self.summary_reads = 0
        self.after_post = None
        self.on_summary = None
        page.route(re.compile(r'/api/jobs\?limit=100$'), lambda route: route.fulfill(json=JOBS))
        page.route(re.compile(rf'/api/jobs/{JOB}/pdc-structure$'), self.structure)
        page.route(re.compile(rf'/api/jobs/{JOB}/trajectory-overview$'), self.overview)
        page.route(re.compile(rf'/api/jobs/{JOB}/analyses\?view=summary$'), self.summary)
        page.route(re.compile(rf'/api/jobs/{JOB}/artifacts/'), self.artifact)

    def structure(self, route):
        if route.request.method == 'POST':
            self.posts.append(('pdc-structure', route.request.post_data_json or {}))
            if self.after_post:
                self.after_post('pdc-structure')
            route.fulfill(status=202, json={'id': 'queued-1', 'kind': 'pdc-structure',
                                            'status': 'queued'})
            return
        if self.record is None:
            route.fulfill(status=404, json={'error': 'No structure analysis has been published for this run.'})
        else:
            route.fulfill(json=self.record)

    def overview(self, route):
        if route.request.method != 'POST':
            route.fulfill(status=405)
            return
        self.posts.append(('trajectory-overview', route.request.post_data_json or {}))
        if self.after_post:
            self.after_post('trajectory-overview')
        route.fulfill(status=202, json={'id': 'queued-2', 'kind': 'trajectory-overview',
                                        'status': 'queued'})

    def summary(self, route):
        self.summary_reads += 1
        if self.on_summary:
            self.on_summary()
        route.fulfill(json=self.tasks)

    def artifact(self, route):
        path = unquote(urlsplit(route.request.url).path.split(f'/api/jobs/{JOB}/artifacts/', 1)[1])
        if path.endswith('result.json'):
            route.fulfill(json={'output_directory': 'output/hash'})
        elif path.endswith('trajectory-overview.json') and self.overview_data is not None:
            route.fulfill(json=self.overview_data)
        elif path.endswith('.png'):
            route.fulfill(body=PNG, content_type='image/png')
        else:
            route.fulfill(status=404, json={'error': path})


def publish(stub, record, *, overview_data=None):
    """The callback a POST causes: one completed attempt, exactly what the worker leaves behind."""
    def answered(kind):
        if kind == 'pdc-structure':
            stub.record = record
            stub.tasks = [task('pdc-structure', 'completed', directory=ATTEMPT)]
        else:
            stub.tasks = [task('trajectory-overview', 'completed', directory=OVERVIEW_DIRECTORY)]
            if overview_data is not None:
                stub.overview_data = overview_data
    return answered


def overview_task():
    return task('trajectory-overview', 'completed', directory=OVERVIEW_DIRECTORY)


def grid_columns(locator):
    """The number of used tracks of a CSS grid, read from its computed `grid-template-columns`."""
    return len(locator.evaluate('el => getComputedStyle(el).gridTemplateColumns').split())


def shares_a_row(left, right):
    """True when two boxes' vertical spans overlap, so they are in the same layout row."""
    first, second = left.bounding_box(), right.bounding_box()
    assert first and second, (first, second)
    return first['y'] < second['y'] + second['height'] and second['y'] < first['y'] + first['height']


def assert_right_of(left, right):
    """Assert the right box starts at or after the left one ends, as a two-column row does."""
    first, second = left.bounding_box(), right.bounding_box()
    assert first and second, (first, second)
    assert second['x'] >= first['x'] + first['width'] - 1, (
        f'{right} is not beside {left}: {first} {second}')


def test_the_tab_is_pdc_analysis_and_lists_only_completed_pdc_runs(dashboard, live_page):
    browser.seed_pdc_run(dashboard, JOB, created='2026-11-20T00:00:00+00:00')
    page, errors = live_page
    Stub(page)
    page.goto(f'{live_page.base_url}{RUN_LIST}')

    tab = page.get_by_role('tab', name='PDC analysis', exact=True)
    expect(tab).to_be_visible()
    tab.click()
    expect(page.locator('#pdc')).to_be_visible()

    picker = page.locator('#pdc-analysis-run')
    expect(picker.locator('option')).to_have_count(2, timeout=30000)
    expect(picker.locator('option').nth(1)).to_contain_text('DM_2ydo_144_libconf_500ns')
    offered = picker.inner_html()
    assert RUNNING not in offered and CG_RUN not in offered, offered

    picker.select_option(JOB)
    expect(page.locator('#pdc-analysis-title')).to_have_text('DM_2ydo_144_libconf_500ns')
    body = page.locator('#pdc-analysis-body')
    expect(body).to_contain_text('Nothing computed yet', timeout=30000)
    expect(page.locator('#pdc-analysis-compute')).to_be_enabled()
    assert errors == [], errors


def test_a_url_names_a_run_and_the_engine_hook_selects_one(dashboard, live_page):
    browser.seed_pdc_run(dashboard, JOB, created='2026-11-20T00:00:00+00:00')
    page, errors = live_page
    Stub(page)
    page.goto(f'{live_page.base_url}{PANEL}?run={JOB}')

    expect(page.locator('#pdc-analysis-run')).to_have_value(JOB, timeout=30000)
    expect(page.locator('#pdc-analysis-identity')).to_contain_text('DM_2ydo_144_libconf_500ns')
    expect(page.locator('#pdc-analysis-body')).to_contain_text('Nothing computed yet')
    assert page.url.endswith(f'?run={JOB}')

    # `window.pdcSetRun` is the Run view's and the browser tests' door; a running run is selected-and-refused.
    page.evaluate(f"window.pdcSetRun('{RUNNING}')")
    body = page.locator('#pdc-analysis-body')
    expect(body).to_contain_text('This run is still running', timeout=30000)
    expect(page.locator('#pdc-analysis-run')).to_have_value('')
    expect(page.locator('#pdc-analysis-compute')).to_be_disabled()
    assert errors == [], errors


def test_compute_structure_posts_the_thresholds_and_draws_the_published_record(dashboard, live_page):
    browser.seed_pdc_run(dashboard, JOB, created='2026-11-20T00:00:00+00:00')
    page, errors = live_page
    stub = Stub(page)
    stub.after_post = publish(stub, V2)
    page.goto(f'{live_page.base_url}{PANEL}?run={JOB}')
    expect(page.locator('#pdc-analysis-body')).to_contain_text('Nothing computed yet', timeout=30000)

    compute = page.locator('#pdc-analysis-compute')
    compute.click()
    expect(compute).to_be_enabled(timeout=30000)
    assert stub.posts == [('pdc-structure', {})], stub.posts
    expect(page.locator('#pdc-analysis-stats')).to_contain_text('Radius of gyration', timeout=30000)

    # A stated threshold travels alone; the blank fields stay absent, which is what "the default" means.
    page.locator('#pdc-opt-bin').fill('0.1')
    compute.click()
    expect(compute).to_be_enabled(timeout=30000)
    assert stub.posts[1] == ('pdc-structure', {'rdf_bin_nm': 0.1}), stub.posts[1]
    assert errors == [], errors


def test_a_v2_record_draws_every_metric_its_figures_and_the_overview(dashboard, live_page):
    browser.seed_pdc_run(dashboard, JOB, created='2026-11-20T00:00:00+00:00')
    page, errors = live_page
    Stub(page, record=V2, tasks=[overview_task()], overview_data=OVERVIEW)
    page.goto(f'{live_page.base_url}{PANEL}?run={JOB}')
    body = page.locator('#pdc-analysis-body')
    stats = page.locator('#pdc-analysis-stats')
    expect(stats).to_contain_text('Radius of gyration', timeout=30000)

    # Micelle, RDF and contacts are the record's own numbers. The summary statistics live beside the options; the
    # tables keep only their own numbers.
    expect(stats.locator('.pds-fig', has_text='Radius of gyration')).to_contain_text('3.21')
    expect(stats.locator('.pds-fig', has_text='Largest cluster')).to_contain_text('141')
    rdf_table = body.locator('.pds-sub', has_text='Radial distribution')
    expect(rdf_table.locator('tr', has_text='protein → tail')).to_contain_text('0.96')
    contacts_table = body.locator('.pds-sub', has_text='Contacts')
    expect(contacts_table.locator('tr', has_text='water – head')).to_contain_text('1842')
    expect(body).to_contain_text('scientifically_validated: false')

    # Each per-metric PNG is fetched from the artifact route at the path the record's route gave.
    rdf = page.locator('img[src*="pdc-structure-rdf.png"]')
    expect(rdf).to_have_attribute(
        'src', re.compile(rf'/api/jobs/{JOB}/artifacts/{ATTEMPT}/output/abc123/pdc-structure-rdf\.png\?inline=1$'))
    for name in FIGURE_NAMES[1:]:
        expect(page.locator(f'img[src*="{name}"]')).to_have_count(1)

    # The overview's summary values live in the statistics column; its own PNG is full width.
    expect(stats.locator('.pds-fig', has_text='RMSD')).to_contain_text('0.41')
    expect(stats.locator('.pds-fig', has_text='RMSF, mean')).to_contain_text('0.29')
    expect(page.locator('img[src*="trajectory-overview.png"]')).to_have_count(1)

    # Downloads carry the record's own run-relative source (the job prefix dropped), the CSV and each PNG.
    json_link = page.locator('.downloads a', has_text='pdc-structure.json')
    expect(json_link).to_have_attribute(
        'href', re.compile(rf'/api/jobs/{JOB}/artifacts/{ATTEMPT}/output/abc123/pdc-structure\.json$'))
    expect(page.locator('.downloads a', has_text='pdc-analysis.csv')).to_have_count(1)
    for name in FIGURE_NAMES:
        expect(page.locator('.downloads a', has_text=name)).to_have_count(1)

    # Data only: no verdict, no mild/harsh label, no trend.
    words = page.locator('#pdc').inner_text()
    banned = [word for word in ('verdict', 'mild', 'harsh', 'trend', 'slope')
              if re.search(rf'\b{word}\b', words, re.IGNORECASE)]
    assert not banned, f'the panel states a conclusion: {banned}'
    assert errors == [], errors


def test_the_layout_separates_statistics_tables_and_figures(dashboard, live_page):
    """Statistics left of Options; the micelle graphs full width; three tables and then three graphs in three equal
    columns; the overview full width; method and downloads together."""
    browser.seed_pdc_run(dashboard, JOB, created='2026-11-20T00:00:00+00:00')
    page, errors = live_page
    # A fallback leg so the record also carries a notice, which must span the body like the status line and caveat.
    record = {**V2, 'leg': {**V2['leg'], 'name': 'CG assessment MD', 'stage_directory': '06_assessment'}}
    Stub(page, record=record, tasks=[overview_task()], overview_data=OVERVIEW)
    page.goto(f'{live_page.base_url}{PANEL}?run={JOB}')
    stats = page.locator('#pdc-analysis-stats')
    body = page.locator('#pdc-analysis-body')
    expect(stats).to_contain_text('Radius of gyration', timeout=30000)

    top = page.locator('.pdc-analysis-top')
    assert grid_columns(top) == 2, top.evaluate('el => getComputedStyle(el).gridTemplateColumns')
    micelle = stats.locator('.pds-sub', has_text=re.compile(r'^Micelle'))
    protein = stats.locator('.pds-sub', has_text=re.compile(r'^Protein shape and energy'))
    expect(micelle).to_have_count(1)
    expect(protein).to_have_count(1)
    options = page.locator('.pdc-analysis-top > .analysis-options')
    # Both statistics blocks sit left of the options; the protein block is one row below the micelle block.
    assert_right_of(micelle, options)
    assert_right_of(protein, options)
    assert protein.bounding_box()['y'] >= micelle.bounding_box()['y'] + micelle.bounding_box()['height'] - 1

    figure_rows = body.locator('.pdc-analysis-row.pdc-figure-row')
    expect(figure_rows).to_have_count(2)
    micelle_row = figure_rows.nth(0)
    assert grid_columns(micelle_row) == 2
    expect(micelle_row.locator('figure.analysis-figure')).to_have_count(2)
    assert abs(micelle_row.bounding_box()['width'] - body.bounding_box()['width']) <= 1

    # The table row: one cell each for radial distribution, contacts and the energy terms, with no figure among them.
    table_row = body.locator('.pdc-analysis-row.columns-3:not(.pdc-figure-row)')
    assert grid_columns(table_row) == 3
    expect(table_row.locator('.pds-sub')).to_have_count(3)
    expect(table_row.locator('.pds-sub', has_text='Radial distribution')).to_have_count(1)
    expect(table_row.locator('.pds-sub', has_text='Contacts')).to_have_count(1)
    expect(table_row.locator('.pds-sub', has_text='Energy terms')).to_have_count(1)
    expect(table_row.locator('figure.analysis-figure')).to_have_count(0)
    table_cells = table_row.locator('.pdc-row-cell')
    expect(table_cells).to_have_count(3)
    table_boxes = [table_cells.nth(index).bounding_box() for index in range(3)]
    assert max(box['y'] for box in table_boxes) - min(box['y'] for box in table_boxes) <= 1
    assert max(box['width'] for box in table_boxes) - min(box['width'] for box in table_boxes) <= 1

    # The graph row: RDF, protein contacts and water contacts, three equal columns and no table among them.
    analysis_row = figure_rows.nth(1)
    assert grid_columns(analysis_row) == 3
    figures = analysis_row.locator('figure.analysis-figure')
    expect(figures).to_have_count(3)
    assert shares_a_row(figures.nth(0), figures.nth(1))
    assert_right_of(figures.nth(0), figures.nth(1))
    assert_right_of(figures.nth(1), figures.nth(2))
    figure_boxes = [figures.nth(index).bounding_box() for index in range(3)]
    assert max(box['width'] for box in figure_boxes) - min(box['width'] for box in figure_boxes) <= 1
    expect(analysis_row.locator('table')).to_have_count(0)

    # The trajectory overview spans the body; method and downloads share another row.
    overview_row = body.locator('.pdc-analysis-row.columns-1')
    expect(overview_row).to_have_count(1)
    assert abs(overview_row.bounding_box()['width'] - body.bounding_box()['width']) <= 1
    expect(overview_row).to_contain_text('Trajectory overview')
    method_row = body.locator('.pdc-analysis-row.columns-2:not(.pdc-figure-row)')
    expect(method_row.locator('.pds-sub', has_text='Method, sampling, cutoffs')).to_have_count(1)
    expect(method_row.locator('.downloads')).to_have_count(1)

    # Notices, the published status line and the caveat span the body, not one column.
    width = body.bounding_box()['width']
    for line in (body.locator('.pds-notice').first, body.locator('.pds-status'), body.locator('.pds-caveat')):
        assert abs(line.bounding_box()['width'] - width) <= 1, (line.bounding_box(), width)
    assert errors == [], errors


def test_each_figure_row_is_equal_and_each_figure_is_separate_from_the_tables(dashboard, live_page):
    browser.seed_pdc_run(dashboard, JOB, created='2026-11-20T00:00:00+00:00')
    page, errors = live_page
    Stub(page, record=V2, tasks=[overview_task()], overview_data=OVERVIEW)
    page.goto(f'{live_page.base_url}{PANEL}?run={JOB}')
    body = page.locator('#pdc-analysis-body')
    expect(body.locator('.pdc-analysis-row.pdc-figure-row')).to_have_count(2, timeout=30000)

    micelle = body.locator('.pdc-analysis-row.pdc-figure-row').nth(0).locator('figure.analysis-figure')
    expect(micelle).to_have_count(2)
    assert shares_a_row(micelle.nth(0), micelle.nth(1))
    expect(micelle.nth(0).locator('img')).to_have_attribute('loading', 'lazy')
    expect(micelle.nth(0).locator('figcaption')).to_contain_text('Radius of gyration')
    expect(micelle.nth(1).locator('figcaption')).to_contain_text('Largest cluster')

    analysis = body.locator('.pdc-analysis-row.pdc-figure-row').nth(1).locator('figure.analysis-figure')
    expect(analysis).to_have_count(3)
    assert shares_a_row(analysis.nth(0), analysis.nth(1))
    assert shares_a_row(analysis.nth(1), analysis.nth(2))
    for index in range(3):
        expect(analysis.nth(index).locator('img')).to_have_attribute('loading', 'lazy')
    expect(analysis.nth(0).locator('figcaption')).to_contain_text('radial distribution')
    expect(analysis.nth(1).locator('figcaption')).to_contain_text('Protein–head')
    expect(analysis.nth(2).locator('figcaption')).to_contain_text('Water–head')

    overview = body.locator('.pdc-analysis-row.columns-1 figure.analysis-figure')
    expect(overview).to_have_count(1)
    expect(overview.locator('img')).to_have_attribute('loading', 'lazy')

    # Tables and figures are different blocks: no table row carries a figure, and every figure is in a figure row.
    expect(body.locator('.pdc-analysis-row.columns-3:not(.pdc-figure-row) figure.analysis-figure')).to_have_count(0)
    assert body.locator('figure.analysis-figure').count() == body.locator(
        '.pdc-analysis-row.pdc-figure-row figure.analysis-figure, .pdc-analysis-row.columns-1 figure').count()
    assert errors == [], errors


def test_a_narrow_window_stacks_every_row(dashboard, live_page):
    browser.seed_pdc_run(dashboard, JOB, created='2026-11-20T00:00:00+00:00')
    page, errors = live_page
    Stub(page, record=V2, tasks=[overview_task()], overview_data=OVERVIEW)
    page.set_viewport_size({'width': 820, 'height': 1000})
    page.goto(f'{live_page.base_url}{PANEL}?run={JOB}')
    expect(page.locator('#pdc-analysis-stats')).to_contain_text('Radius of gyration', timeout=30000)

    top = page.locator('.pdc-analysis-top')
    assert grid_columns(top) == 1, top.evaluate('el => getComputedStyle(el).gridTemplateColumns')
    stats = page.locator('#pdc-analysis-stats')
    options = page.locator('.pdc-analysis-top > .analysis-options')
    assert options.bounding_box()['y'] >= stats.bounding_box()['y'] + stats.bounding_box()['height'] - 1
    for row in page.locator('.pdc-analysis-row').all():
        assert grid_columns(row) == 1, row.evaluate('el => getComputedStyle(el).gridTemplateColumns')

    # The existing 640 px behaviour is untouched: the four threshold fields become one per row.
    page.set_viewport_size({'width': 600, 'height': 1000})
    opt_grid = page.locator('.analysis-options .opt-grid')
    assert grid_columns(opt_grid) == 1, opt_grid.evaluate('el => getComputedStyle(el).gridTemplateColumns')
    assert errors == [], errors


def test_a_v1_record_marks_the_new_metrics_not_measured(dashboard, live_page):
    browser.seed_pdc_run(dashboard, JOB, created='2026-11-20T00:00:00+00:00')
    page, errors = live_page
    Stub(page, record=V1)
    page.goto(f'{live_page.base_url}{PANEL}?run={JOB}')
    body = page.locator('#pdc-analysis-body')
    expect(page.locator('#pdc-analysis-stats')).to_contain_text('Radius of gyration', timeout=30000)
    expect(body).to_contain_text('This record predates the new metrics')
    rdf_table = body.locator('.pds-sub', has_text='Radial distribution')
    contacts_table = body.locator('.pds-sub', has_text='Contacts')
    expect(contacts_table.locator('tr', has_text='protein → tail')).to_contain_text('not measured')
    expect(contacts_table.locator('tr', has_text='water – head')).to_contain_text('not measured')
    expect(contacts_table.locator('tr', has_text='water – tail')).to_contain_text('not measured')
    # The v1 pooled protein–detergent count stays readable, as what it is.
    expect(contacts_table.locator('tr', has_text='protein – all detergent (pooled)')).to_contain_text('318')
    expect(rdf_table.locator('tr', has_text='protein → head')).to_contain_text('0.47')
    expect(rdf_table.locator('tr', has_text='protein → tail')).to_contain_text('not measured')
    assert page.locator('img[src*="pdc-structure-rdf.png"]').count() == 0
    assert errors == [], errors


def test_a_record_with_no_protein_and_a_fallback_leg_says_both(dashboard, live_page):
    browser.seed_pdc_run(dashboard, JOB, created='2026-11-20T00:00:00+00:00')
    page, errors = live_page
    record = {
        **V2,
        'protein_present': False,
        'contacts': {**V2['contacts'],
                     'groups': [group for group in V2['contacts']['groups'] if group['first'] == 'water']},
        'rdf': [curve for curve in V2['rdf'] if curve['first'] != 'protein'],
        'leg': {**V2['leg'], 'name': 'CG assessment MD', 'stage_directory': '06_assessment',
                'fallback_reason': 'the run switched out-of-micelle removal off'},
        'schema_version': 2,
    }
    Stub(page, record=record)
    page.goto(f'{live_page.base_url}{PANEL}?run={JOB}')
    body = page.locator('#pdc-analysis-body')
    expect(body).to_contain_text('This run has no protein', timeout=30000)
    expect(body).to_contain_text('fallback production leg')
    expect(body).to_contain_text('out-of-micelle removal off')
    contacts_table = body.locator('.pds-sub', has_text='Contacts')
    expect(contacts_table.locator('tr', has_text='protein → head')).to_contain_text('not defined')
    expect(contacts_table.locator('tr', has_text='water – head')).to_contain_text('1842')
    assert errors == [], errors


def test_compute_overview_queues_the_core_kind_and_reads_the_cached_record(dashboard, live_page):
    browser.seed_pdc_run(dashboard, JOB, created='2026-11-20T00:00:00+00:00')
    page, errors = live_page
    stub = Stub(page, record=V2)
    stub.after_post = publish(stub, V2, overview_data=OVERVIEW)
    page.goto(f'{live_page.base_url}{PANEL}?run={JOB}')
    body = page.locator('#pdc-analysis-body')
    stats = page.locator('#pdc-analysis-stats')
    expect(stats).to_contain_text('Radius of gyration', timeout=30000)
    expect(body).to_contain_text('Not computed')

    page.get_by_role('button', name='Compute overview').click()
    expect(stats).to_contain_text('RMSD', timeout=30000)
    assert stub.posts == [('trajectory-overview', {})], stub.posts
    # The overview's cached attempt is the record; once it exists the button is gone.
    expect(page.get_by_role('button', name='Compute overview')).to_have_count(0)
    assert errors == [], errors


def test_a_running_attempt_disables_compute_and_a_failure_reports_its_sentence(dashboard, live_page):
    browser.seed_pdc_run(dashboard, JOB, created='2026-11-20T00:00:00+00:00')
    page, errors = live_page
    page.add_init_script('window.__pdcAnalysisPollMs = 40')
    stub = Stub(page, tasks=[task('pdc-structure', 'running')])
    reads = []

    def flip():
        reads.append(stub.summary_reads)
        if len(reads) >= 2:
            stub.tasks = [task('pdc-structure', 'failed',
                               error='gmx trjconv exited 1: no such trajectory')]

    stub.on_summary = flip
    page.goto(f'{live_page.base_url}{PANEL}?run={JOB}')

    compute = page.locator('#pdc-analysis-compute')
    expect(compute).to_be_disabled(timeout=30000)
    expect(compute).to_have_text('Computing…')
    expect(page.locator('#pdc-analysis-status')).to_contain_text('gmx trjconv exited 1', timeout=30000)
    expect(compute).to_be_enabled()
    assert errors == [], errors
