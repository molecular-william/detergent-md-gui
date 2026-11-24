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
    expect(page.locator('#pdc-analysis-body')).to_contain_text('Radius of gyration', timeout=30000)

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
    expect(body).to_contain_text('Radius of gyration', timeout=30000)

    # Micelle, RDF and contacts are the record's own numbers.
    expect(body.locator('.pds-fig', has_text='Radius of gyration')).to_contain_text('3.21')
    expect(body.locator('.pds-fig', has_text='Largest cluster')).to_contain_text('141')
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

    # The overview's summary values and its own PNG, read through the same artifact route.
    expect(body.locator('.pds-fig', has_text='RMSD')).to_contain_text('0.41')
    expect(body.locator('.pds-fig', has_text='RMSF, mean')).to_contain_text('0.29')
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


def test_a_v1_record_marks_the_new_metrics_not_measured(dashboard, live_page):
    browser.seed_pdc_run(dashboard, JOB, created='2026-11-20T00:00:00+00:00')
    page, errors = live_page
    Stub(page, record=V1)
    page.goto(f'{live_page.base_url}{PANEL}?run={JOB}')
    body = page.locator('#pdc-analysis-body')
    expect(body).to_contain_text('Radius of gyration', timeout=30000)

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
    expect(body).to_contain_text('Radius of gyration', timeout=30000)
    expect(body).to_contain_text('Not computed')

    page.get_by_role('button', name='Compute overview').click()
    expect(body).to_contain_text('RMSD', timeout=30000)
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
