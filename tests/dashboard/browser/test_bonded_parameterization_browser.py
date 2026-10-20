"""CG Bond Interactions as the place a parameterization is produced: the model card, the fit job, the result,
the `source` column, and the revision strip.

The six routes this panel drives are landing in `web/routes/**` in a parallel slice, so all six are stubbed here
and what is asserted is the request the panel sends -- method, path and body -- beside what it renders from the
answers. A stub is the honest shape for that: the route's own contract is the design record's `## API` table, and
a test that queued a real fit would be minutes of `ff_inter` to learn nothing about the panel.

Four rules from this repository's history are held here rather than assumed:

1. **A superseded job never reaches the screen.** `test_a_superseded_job_never_repaints_the_screen` delays the
   first mapping's job answer inside the page and switches mapping while it is outstanding; the answer arrives
   after the switch and must be dropped, which is what the module's generation token is for.
2. **Polling stops** -- on a terminal status, and while the panel is off screen. Both are asserted as the absence
   of further requests, not as an internal flag.
3. **A failure is shown as what it recorded.** The failed job's `error` and `log_tail` are both read off the page.
4. **Every id is unique in the document**, which is checked over the whole rendered page and not only this panel.

The record is addressed by the mapping's **content** hash, so the fixture reads that hash back from the route the
panel reads it from (`/api/mappings/<file>`) instead of recomputing it and hoping the two agree.
"""
import json
import re
import time

from playwright.sync_api import expect

from dashboard.models import mappings
from dashboard.models.bonded import parameterization
from dashboard.models.mappings import context as mapping_context

AA_RUN = 'aa00aa000001'
OTHER_AA_RUN = 'aa00aa000002'
JOB_ID = 'ff00ff00ff00ff00'
CONTENT_HASH = 'c' * 64
CANDIDATE_HASH = 'b' * 64
REVISION_HASH = 'e' * 64

ENGINES = ({'value': 'fast-forward', 'label': 'Fast-Forward fit (ff_inter)', 'needs_reference': True},
           {'value': 'bartender', 'label': 'BARTENDER fit (-refit -owntraj)', 'needs_reference': True})

REFERENCES = (
    {'id': AA_RUN, 'label': 'Maltose AA reference', 'created': '2026-10-01T10:00:00+00:00',
     'run_type': 'aa_only', 'settings': {'temperature_k': 300, 'aa_production_ps': 10000}, 'frames': 20001},
    {'id': OTHER_AA_RUN, 'label': 'Maltose AA reference, 20 ns', 'created': '2026-10-02T10:00:00+00:00',
     'run_type': 'aa_only', 'settings': {'temperature_k': 300, 'aa_production_ps': 20000}, 'frames': 40001},
)

#: The revision's own topology: one constraint, one bond, one angle and one dihedral, over four named beads. Written
#: as an ITP because that is what a stored revision carries, and the panel has to read it rather than be told.
TOPOLOGY = """[ moleculetype ]
LIG1 1

[ atoms ]
1 SP1r 1 LIG1 B01 1 0 54
2 SP1r 1 LIG1 B02 2 0 54
3 SP1r 1 LIG1 B03 3 0 54
4 SP1r 1 LIG1 B04 4 0 54

[ constraints ]
1 2 1 0.315

[ bonds ]
2 3 1 0.32 5000

[ angles ]
1 2 3 10 141.6 26.8

[ dihedrals ]
1 2 3 4 2 -102.273 36.636 1
"""

#: One row per term of the topology above, as `parameterization.term_sources` computes them: the ring pair is the
#: mapping's, the bond and the angle are the engine's, and the dihedral is a geometry fallback.
SOURCES = ({'id': 'constraints:1', 'kind': 'constraints', 'beads': ['B01', 'B02'], 'source': 'mapping'},
           {'id': 'bonds:1', 'kind': 'bonds', 'beads': ['B02', 'B03'], 'source': 'ff_inter'},
           {'id': 'angles:1', 'kind': 'angles', 'beads': ['B01', 'B02', 'B03'], 'source': 'ff_inter'},
           {'id': 'dihedrals:1', 'kind': 'dihedrals', 'beads': ['B01', 'B02', 'B03', 'B04'], 'source': 'geometry'})

CHECKS = {'dihedral-fit': {'rows': [{'beads': ['B01', 'B02', 'B03', 'B04']}], 'disagreements': [],
                           'criterion': 'bic', 'frames_measured': 20001},
          'bonded-cross-check': {'rows': [{'beads': ['B01', 'B02']}, {'beads': ['B02', 'B03']}],
                                 'disagreements': [['B01', 'B02']], 'frames_measured': 20001}}


def revision(number, *, engine='fast-forward', created_at='2026-10-16T14:30:00+00:00', **extra):
    record = {'revision': number, 'created_at': created_at,
              'mapping_hash': CANDIDATE_HASH, 'mapping_content_hash': CONTENT_HASH,
              'engine': engine, 'engine_default_source': 'ff_inter',
              'options': {'constraints_threshold': 10000.0, 'temperature_k': 300.0,
                          'torsion_model': 'circular-harmonic', 'torsion_scale': 1.0},
              'temperature_source': "this fit's own temperature, 300 K",
              'ensemble': {'frames': 20001, 'trajectory': '1_AA-reference/prod/lig.xtc',
                           'source': 'the AA reference'},
              'aa_reference': {'run_id': AA_RUN, 'reference_sha256': 'd' * 64, 'molecule_identity': 'Maltose',
                               'temperature_k': 300.0, 'production_ns': 10.0},
              'topology': TOPOLOGY, 'terms': {'bonds': 1, 'angles': 1, 'dihedrals': 1, 'constraints': 1},
              'sources': list(SOURCES), 'refinement': None, 'diagnostics': [], 'checks': CHECKS,
              'notes': [], 'scientifically_validated': False}
    record.update(extra)
    return record


def summary(number, revisions, *, terms=12):
    """`parameterization.view(record)`, for the record's current revision."""
    if number is None:
        return {'parameterized': False, 'revision': None, 'engine': None, 'engine_label': None, 'terms': None,
                'torsion_model': None, 'checks': [], 'aa_reference': None, 'revision_sha256': None,
                'mapping_hash': CANDIDATE_HASH, 'mapping_content_hash': CONTENT_HASH, 'revisions': []}
    current = [item for item in revisions if item['revision'] == number][0]
    return {'parameterized': True, 'revision': number, 'engine': current['engine'],
            'engine_label': 'Fast-Forward fit (ff_inter)', 'terms': terms,
            'torsion_model': current['options']['torsion_model'], 'checks': ['bonded-cross-check', 'dihedral-fit'],
            'aa_reference': current['aa_reference'], 'revision_sha256': REVISION_HASH,
            'created_at': current['created_at'], 'mapping_hash': CANDIDATE_HASH,
            'mapping_content_hash': CONTENT_HASH,
            'revisions': [item['revision'] for item in revisions]}


def answer(revisions=(), jobs=(), current=None):
    history = list(revisions)
    number = current if current is not None else (history[-1]['revision'] if history else None)
    return {'summary': summary(number, history), 'revisions': history, 'jobs': list(jobs)}


def job(status='running', *, error=None, log_tail=None, **extra):
    record = {'id': JOB_ID, 'status': status, 'engine': 'fast-forward', 'mapping_name': 'fixture mapping',
              'molecule_id': 'DDM', 'mapping_hash': CANDIDATE_HASH, 'mapping_content_hash': CONTENT_HASH,
              'options': {'constraints_threshold': 10000.0, 'temperature_k': 300.0,
                          'torsion_model': 'circular-harmonic', 'torsion_scale': 1.0},
              'steps': ['mapped frames', 'fit', 'checks', 'save'], 'step': 'fit',
              'completed_steps': ['mapped frames'],
              'progress': {'done': 1, 'total': 4, 'detail': 'ff_inter: distances, angles, dihedrals'},
              'created_at': '2026-10-16T14:31:00+00:00', 'started_at': '2026-10-16T14:31:02+00:00',
              'ended_at': None, 'error': error, 'log_tail': log_tail, 'revision': None,
              'scientifically_validated': False}
    record.update(extra)
    return record


def save(dashboard, name='E3 maltose mapping', molecule='DDM'):
    """One saved candidate in the test's own workspace, and the two hashes the panel will address it by.

    Two models that differ only in `name` are the same *content*, and a record is selected by content identity --
    so a test that needs two distinct models asks for two distinct molecules rather than two names.
    """
    if molecule == 'DDM':
        candidate = mappings.automatic_candidate(mappings.molecule(), molecule)
    else:
        context = dashboard.client.get(f'/api/mappings/context?molecule_id={molecule}').get_json()['context']
        candidate = mappings.automatic_candidate(mapping_context.as_structure(context), molecule)
        candidate['molecule_snapshot'] = context['snapshot']
    candidate.update(name=name, molecule_id=molecule)
    saved = mappings.save_draft(candidate)
    detail = dashboard.client.get(f'/api/mappings/{saved["file"]}').get_json()
    return saved, detail['mapping_content_hash'], detail['mapping_hash']


def stub(page, record, *, jobs=None, engines=ENGINES, references=REFERENCES, posts=None, patches=None,
         cancels=None, on_patch=None):
    """Every route this panel drives, answered from the test.

    `record` is the object `route.fulfill(json=...)` gets for a record read, so a test can mutate it where a route
    would have changed it (making a revision current); `jobs` overrides the job list separately for the poll route,
    because that is the answer the box watches.
    """
    posts = posts if posts is not None else []
    patches = patches if patches is not None else []
    cancels = cancels if cancels is not None else []

    page.route(re.compile(r'/api/bonded-parameterizations/engines$'),
               lambda route: route.fulfill(json={'engines': list(engines)}))
    page.route(re.compile(r'/api/bonded-parameterizations/jobs\?'),
               lambda route: route.fulfill(json={'jobs': (jobs if jobs is not None else record['jobs'])}))
    page.route(re.compile(r'/api/bonded-parameterizations/jobs/[a-f0-9]+/cancel$'),
               lambda route: (cancels.append((route.request.method, route.request.url.split('/api')[1],
                                              route.request.post_data)),
                              route.fulfill(json=job('cancelled', ended_at='2026-10-16T14:33:00+00:00')))[-1])
    def patch(route):
        patches.append((route.request.method, route.request.url.split('/api')[1], route.request.post_data))
        if on_patch is not None:
            on_patch(json.loads(route.request.post_data or '{}'))
        route.fulfill(json=record)

    page.route(re.compile(r'/api/bonded-parameterizations/[a-f0-9]{64}$'), patch)
    page.route(re.compile(r'/api/bonded-parameterizations\?'),
               lambda route: route.fulfill(json=record))
    page.route(re.compile(r'/api/references'),
               lambda route: route.fulfill(json={'references': list(references)}))
    page.route(re.compile(r'/api/bonded-parameterizations$'),
               lambda route: (posts.append((route.request.method, route.request.url.split('/api')[1],
                                            route.request.post_data)),
                              route.fulfill(status=201, json=job('queued', progress={'done': 0, 'total': 4,
                                                                                     'detail': 'queued'})))[-1])
    return posts, patches, cancels


def open_panel(page, live_page, file):
    page.goto(f'{live_page.base_url}/detergent-validation/bond-interactions')
    # The catalogue offers several candidates in some tests, and which one comes first is the catalogue's order
    # rather than this file's subject: select the one the test means, the way a reader would.
    page.wait_for_function("() => document.querySelectorAll('#bonded-mapping-select option').length > 0",
                           timeout=30000)
    if page.locator('#bonded-mapping-select').input_value() != file:
        page.locator('#bonded-mapping-select').select_option(file)
    expect(page.locator('#bonded-mapping-select')).to_have_value(file)
    # The engines are read once at mount and the model card cannot say anything about a fit before that lands.
    page.wait_for_function("() => document.querySelectorAll('#bonded-engine option').length > 0", timeout=30000)


def cells(page, index):
    return page.locator('.bonded-interaction-table tbody tr').nth(index).locator('td')


# -------------------------------------------------------------------------------------------- the model card


def test_the_model_card_offers_the_engines_their_references_and_the_four_options(dashboard, live_page):
    """D3/D4 as the panel renders them: which engines need a reference, and the four options with their units.

    The threshold is the option whose value decides what the model *is* — above it a fitted pair is written as a
    constraint and below it as a spring — so its unit and its default are on screen beside the field rather than
    in a document, and the engine's own `needs_reference` decides whether the reference is required.
    """
    saved, content, candidate = save(dashboard)
    record = answer()
    page, errors = live_page
    asked = []
    page.on('request', lambda request: asked.append(request.url))
    stub(page, record)
    open_panel(page, live_page, saved['file'])

    expect(page.locator('#bonded-engine option')).to_have_count(2)
    expect(page.locator('#bonded-engine option').nth(0)).to_contain_text('Fast-Forward fit (ff_inter)')
    expect(page.locator('#bonded-engine option').nth(0)).to_contain_text('needs an AA reference')
    expect(page.locator('#bonded-engine option').nth(1)).to_contain_text('needs an AA reference')
    assert page.locator('#bonded-engine').input_value() == 'fast-forward'
    expect(page.locator('#bonded-engine-note')).to_contain_text('needs an AA reference')

    # The reference picker lists the AA-only runs the route offered, and names the one it is talking about.
    expect(page.locator('#bonded-aa-reference option')).to_have_count(3)
    assert page.locator('#bonded-aa-reference option').nth(1).get_attribute('value') == AA_RUN
    page.locator('#bonded-aa-reference').select_option(OTHER_AA_RUN)
    expect(page.locator('#bonded-aa-facts')).to_contain_text('20 ns of production')
    expect(page.locator('#bonded-aa-facts')).to_contain_text('300 K')

    # The four options, with the threshold's unit and default named where the field is.
    expect(page.locator('#bonded-constraints-threshold')).to_have_value('10000')
    note = page.locator('#bonded-constraints-note').inner_text()
    assert 'kJ mol' in note and 'default 10000' in note, note
    assert 'constraint' in note and 'spring' in note, note
    expect(page.locator('#bonded-temperature')).to_have_value('300')
    scale = page.locator('#bonded-torsion-scale')
    expect(scale).to_be_disabled()
    page.locator('#bonded-torsion-model').select_option('circular-harmonic')
    expect(scale).to_be_enabled()
    expect(scale).to_have_value('1')
    page.locator('#bonded-torsion-model').select_option('legacy')
    expect(scale).to_be_disabled()

    # The record was asked for by both identities the panel holds, and the empty state says which it is.
    reads = [url for url in asked if '/api/bonded-parameterizations?' in url]
    assert reads, asked
    assert f'content_hash={content}' in reads[0] and f'mapping_hash={candidate}' in reads[0], reads[0]
    expect(page.locator('#bonded-model-badge')).to_have_text('no parameterization')
    expect(page.locator('#bonded-result')).to_be_hidden()
    expect(page.locator('#bonded-revisions')).to_contain_text('no revisions yet')
    # And the table is the mapping's own draft, saying so in the source column.
    expect(cells(page, 0).last).to_have_text('mapping')
    assert errors == [], errors


def test_the_fit_button_posts_the_models_snapshot_and_the_options_the_panel_shows(dashboard, live_page):
    """D2's request, exactly: the saved candidate, the engine, the reference, and the four values on screen.

    One button, one route: the engine comes from the select, and every engine left fits to an ensemble, so the request
    always carries an `aa_reference` — the reference-free engine and its second button were removed.
    """
    saved, content, candidate = save(dashboard)
    page, errors = live_page
    posts, _, _ = stub(page, answer())
    open_panel(page, live_page, saved['file'])

    page.locator('#bonded-aa-reference').select_option(AA_RUN)
    page.locator('#bonded-constraints-threshold').fill('12500')
    page.locator('#bonded-temperature').fill('310')
    page.locator('#bonded-torsion-model').select_option('circular-harmonic')
    page.locator('#bonded-torsion-scale').fill('0.8')
    page.locator('#bonded-fit').click()
    expect(page.locator('#bonded-job-status')).to_have_text('queued')
    assert len(posts) == 1, posts
    method, path, body = posts[0]
    assert method == 'POST' and path == '/bonded-parameterizations', (method, path)
    payload = json.loads(body)
    assert payload['engine'] == 'fast-forward'
    assert payload['aa_reference'] == AA_RUN
    assert payload['options'] == {'constraints_threshold': 12500, 'temperature_k': 310,
                                  'torsion_model': 'circular-harmonic', 'torsion_scale': 0.8}
    # The snapshot itself, not its file name: the fit runs against the mapping the reader was looking at.
    assert payload['mapping']['file'] == saved['file']
    assert payload['mapping']['beads'], 'the request carried no beads, so it is not the candidate snapshot'
    assert payload['mapping']['mapping_content_hash'] == content
    assert errors == [], errors


# ---------------------------------------------------------------------------------------------------- the job box


def test_a_running_job_shows_its_step_and_cancels_only_after_a_confirmation(dashboard, live_page):
    """The box states the job's own progress, and Cancel asks first: a dismissed confirm sends nothing.

    Polling is stopped by the cancellation, and that is asserted as requests that never arrive -- the panel is
    not trusted to say it stopped.
    """
    saved, _, _ = save(dashboard)
    page, errors = live_page
    page.add_init_script('window.__bondedPollMs = 200')
    record = answer(jobs=[job()])
    asks = []
    stub(page, record)
    page.on('request', lambda request: asks.append(request.url))
    open_panel(page, live_page, saved['file'])

    expect(page.locator('#bonded-job-status')).to_have_text('running')
    expect(page.locator('#bonded-job-title')).to_contain_text('Fitting · 1 of 4')
    expect(page.locator('#bonded-job-detail')).to_contain_text('distances, angles, dihedrals')
    expect(page.locator('#bonded-job-cancel')).to_be_visible()

    # A bar at a quarter tells a reader nothing about whether the job is moving; the four steps do. The names are
    # the record's own `steps`, and the one that is running is the only one marked `current`.
    labels = page.evaluate("Array.from(document.querySelectorAll('#bonded-job-steps li')).map(li => li.textContent)")
    assert labels == ['Mapped frames', 'Fit', 'Checks', 'Save'], labels
    states = page.evaluate("Array.from(document.querySelectorAll('#bonded-job-steps li')).map(li => li.dataset.state)")
    assert states == ['done', 'current', 'pending', 'pending'], states
    expect(page.locator('#bonded-job-steps li[aria-current=step]')).to_have_text('Fit')
    # The meter says the same thing to a screen reader, and the detail line says how long it has been running --
    # read off the job's own `started_at`, not estimated.
    expect(page.locator('.bonded-job-meter')).to_have_attribute('aria-valuetext', '1 of 4 · fit')
    # And the poll asks about *this job*, by the id it was handed when it queued it -- not about the mapping, whose
    # hash is a different question and answered nothing at all when the two disagreed.
    for _ in range(30):
        polls = [url for url in asks if '/api/bonded-parameterizations/jobs?' in url]
        if polls:
            break
        page.wait_for_timeout(100)
    assert polls and all(f'job_id={JOB_ID}' in url for url in polls), polls
    expect(page.locator('#bonded-job-detail')).to_contain_text('elapsed ')

    # A dismissed confirmation is a refusal: no request, and the job is still running.
    page.locator('#bonded-job-cancel').click()
    page.wait_for_timeout(300)
    assert not [url for url in asks if '/cancel' in url], asks
    expect(page.locator('#bonded-job-status')).to_have_text('running')

    page.on('dialog', lambda dialog: dialog.accept())
    page.locator('#bonded-job-cancel').click()
    page.wait_for_function("() => document.body.textContent.includes('cancelled')", timeout=10000)
    # The route the panel posts to names the job, and the body is empty: there is nothing to describe.
    cancels = [url for url in asks if '/cancel' in url]
    assert cancels, asks
    expect(page.locator('#bonded-job-status')).to_have_text('cancelled')
    expect(page.locator('#bonded-job-cancel')).to_be_hidden()

    # And the poll has stopped with the job: the count of job reads does not grow over several cadences.
    settled = len([url for url in asks if '/jobs?' in url])
    page.wait_for_timeout(700)
    assert len([url for url in asks if '/jobs?' in url]) == settled, asks
    assert errors == [], errors


def test_a_failed_job_is_shown_with_its_error_and_the_tail_of_its_log(dashboard, live_page):
    """A record carrying `failed` is a report, not a word: both fields it recorded are on the page."""
    saved, _, _ = save(dashboard)
    page, errors = live_page
    failure = job('failed', error='ff_inter: mapped trajectory has no bead B07',
                  log_tail='building mapped frames\nff_inter: mapped trajectory has no bead B07\n',
                  ended_at='2026-10-16T14:33:00+00:00')
    stub(page, answer(jobs=[failure]))
    open_panel(page, live_page, saved['file'])

    expect(page.locator('#bonded-job-status')).to_have_text('failed')
    expect(page.locator('#bonded-job-title')).to_have_text('Failed')
    expect(page.locator('#bonded-job-error')).to_contain_text('mapped trajectory has no bead B07')
    expect(page.locator('#bonded-job-log')).to_contain_text('building mapped frames')
    expect(page.locator('#bonded-job-log')).to_be_visible()
    expect(page.locator('#bonded-job-cancel')).to_be_hidden()
    assert errors == [], errors


def test_a_superseded_job_never_repaints_the_screen(dashboard, live_page):
    """The generation token, measured: an answer that arrives after the reader moved on is dropped.

    The first mapping's job answer is delayed inside the page, and the mapping is switched while it is
    outstanding. Without the token the late answer draws the old job's box over the new mapping's model card --
    the failure `run-view-monitor.js` was fixed for, in this panel's own shape.
    """
    first, first_content, _ = save(dashboard, 'First model')
    second, second_content, _ = save(dashboard, 'Second model', molecule='Sucrose')
    assert first_content != second_content, 'the two fixtures are the same content, so this test compares nothing'
    page, errors = live_page
    page.add_init_script('window.__bondedPollMs = 150')
    records = {first_content: answer(jobs=[job()]), second_content: answer([revision(1)])}
    page.route(re.compile(r'/api/bonded-parameterizations/engines$'),
               lambda route: route.fulfill(json={'engines': list(ENGINES)}))
    page.route(re.compile(r'/api/references'),
               lambda route: route.fulfill(json={'references': list(REFERENCES)}))
    page.route(re.compile(r'/api/bonded-parameterizations/jobs\?'),
               lambda route: route.fulfill(json={'jobs': [job()]}))
    page.route(re.compile(r'/api/bonded-parameterizations\?'),
               lambda route: route.fulfill(json=records[re.search(r'content_hash=([a-f0-9]+)', route.request.url).group(1)]))
    # The delay is in the page, on the first mapping's job reads only: a route handler that slept would block
    # the very click this test needs to make while the answer is outstanding.
    page.add_init_script(f"""(() => {{
      const original = window.fetch;
      window.fetch = async (url, options) => {{
        const response = await original(url, options);
        if (String(url).includes('/jobs?') && String(url).includes('{first_content}')) {{
          await new Promise(resolve => setTimeout(resolve, 900));
        }}
        return response;
      }};
    }})()""")
    open_panel(page, live_page, first['file'])
    expect(page.locator('#bonded-job-status')).to_have_text('running')

    page.locator('#bonded-mapping-select').select_option(second['file'])
    # The second mapping has a revision and no job, so its own card is the thing that says the switch landed.
    expect(page.locator('#bonded-result-title')).to_have_text('Revision 1 · current')
    expect(page.locator('#bonded-job')).to_be_hidden()

    # The delayed answer lands here, and must not bring the first mapping's job back onto the screen.
    page.wait_for_timeout(1400)
    expect(page.locator('#bonded-job')).to_be_hidden()
    expect(page.locator('#bonded-result-title')).to_have_text('Revision 1 · current')
    expect(page.locator('#bonded-mapping-select')).to_have_value(second['file'])
    assert errors == [], errors


def test_polling_stops_while_the_panel_is_off_screen_and_picks_up_when_it_returns(dashboard, live_page):
    """A hidden panel asks nothing: the box keeps its state and the timer stops, then resumes on the event.

    This is the rule `runs.js` follows before every fetch, held here as requests that stop arriving rather than
    as a flag inside the module -- a poll that keeps running behind another tab is a request a reader cannot see
    the result of, and the job list is the one route this panel hits repeatedly.
    """
    saved, _, _ = save(dashboard)
    page, errors = live_page
    page.add_init_script('window.__bondedPollMs = 150')
    polls = []
    stub(page, answer(jobs=[job()]))
    page.route(re.compile(r'/api/bonded-parameterizations/jobs\?'),
               lambda route: (polls.append(time.monotonic()),
                              route.fulfill(json={'jobs': [job()]}))[-1])
    open_panel(page, live_page, saved['file'])
    expect(page.locator('#bonded-job-status')).to_have_text('running')

    deadline = time.monotonic() + 10
    while len(polls) < 2 and time.monotonic() < deadline:
        page.wait_for_timeout(100)
    assert len(polls) >= 2, polls

    page.evaluate("() => { document.querySelector('#bonded').hidden = true; document.dispatchEvent(new Event('visibilitychange')); }")
    page.wait_for_timeout(400)
    settled = len(polls)
    page.wait_for_timeout(700)
    assert len(polls) == settled, f'the box polled {len(polls) - settled} times with the panel hidden'

    page.evaluate("() => { document.querySelector('#bonded').hidden = false; document.dispatchEvent(new Event('visibilitychange')); }")
    deadline = time.monotonic() + 10
    while len(polls) == settled and time.monotonic() < deadline:
        page.wait_for_timeout(100)
    assert len(polls) > settled, 'the box never resumed polling a live job'
    assert errors == [], errors


def test_the_default_cadence_polls_a_few_seconds_apart_and_stops_when_the_job_ends(dashboard, live_page):
    """The default interval, run rather than described: the seam is not set here, so `POLL_MS` is what polls.

    A cadence of milliseconds would flood the route and one of minutes would leave a finished fit looking live;
    the assertion is a band, and what ends the polling is the job's own terminal status.
    """
    saved, _, _ = save(dashboard)
    page, errors = live_page
    state = {'job': job('running'), 'record': answer(jobs=[job('running')])}
    polls = []
    stub(page, state['record'])
    # Re-registered after `stub`, because these two answers change while the test runs.
    page.route(re.compile(r'/api/bonded-parameterizations/jobs\?'),
               lambda route: (polls.append(time.monotonic()),
                              route.fulfill(json={'jobs': [state['job']]}))[-1])
    page.route(re.compile(r'/api/bonded-parameterizations\?'),
               lambda route: route.fulfill(json=state['record']))
    open_panel(page, live_page, saved['file'])

    expect(page.locator('#bonded-job-status')).to_have_text('running')
    # Two polls, timed from the route's side: the gap is the module's own cadence, not the seam's.
    deadline = time.monotonic() + 15
    while len(polls) < 2 and time.monotonic() < deadline:
        page.wait_for_timeout(250)
    assert len(polls) >= 2, f'the box never polled again: {polls}'
    gap = polls[1] - polls[0]
    assert 1.5 <= gap <= 10.0, f'the poll cadence is {gap:.1f}s, which is not "every few seconds"'

    # Now end the job the way the route would, and see the panel stop asking.
    state['job'] = job('completed', ended_at='2026-10-16T14:35:00+00:00', revision=1)
    state['record'] = answer([revision(1)], jobs=[state['job']])
    page.wait_for_function(
        "() => document.querySelector('#bonded-job-status')?.textContent === 'completed'", timeout=25000)
    settled = len(polls)
    page.wait_for_timeout(4000)
    assert len(polls) == settled, 'the box kept polling a finished job'
    expect(page.locator('#bonded-result')).to_be_visible()
    expect(page.locator('#bonded-result-title')).to_have_text('Revision 1 · current')
    # A finished job has nothing running: all four steps read done, and none claims to be current.
    expect(page.locator('#bonded-job-steps li[data-state=done]')).to_have_count(4)
    expect(page.locator('#bonded-job-steps li[aria-current=step]')).to_have_count(0)
    assert errors == [], errors


# -------------------------------------------------------------------------------------------- the result card


def test_the_result_card_names_the_revisions_provenance_and_the_two_checks_numbers(dashboard, live_page):
    """What the terms were fitted from, in the units they were fitted in, and the checks' own numbers.

    Every value here is read off the revision the route answered with; nothing is reconstructed from the options
    the panel itself holds, which is what makes the card usable as provenance for a run.
    """
    saved, _, _ = save(dashboard)
    page, errors = live_page
    history = [revision(1), revision(2), revision(3)]
    stub(page, answer(history, current=3))
    open_panel(page, live_page, saved['file'])

    expect(page.locator('#bonded-result')).to_be_visible()
    expect(page.locator('#bonded-result-title')).to_have_text('Revision 3 · current')
    provenance = page.locator('#bonded-result-provenance').inner_text()
    expect(page.locator('#bonded-result-summary')).to_contain_text('12 terms')
    for expected in ('Fast-Forward fit (ff_inter)', '20,001 mapped AA frames', '1_AA-reference/prod/lig.xtc',
                     '10000 kJ mol', '300 K', 'circular-harmonic · stiffness scale 1',
                     AA_RUN, '10 ns', '1 bonds · 1 angles · 1 dihedrals · 1 constraints'):
        assert expected in provenance, f'{expected} is not in the provenance card:\n{provenance}'
    checks = page.locator('#bonded-result-checks').inner_text()
    assert 'dihedral-fit — 1 declared torsion' in checks, checks
    assert 'bonded-cross-check — 2 terms' in checks, checks
    assert '1 disagree on whether it is a constraint' in checks, checks
    # A check that could not run is reported with its reason, never as a failed fit and never as a pass.
    stub_checks = revision(1, checks={'dihedral-fit': {'error': 'no dihedral in the topology'},
                                      'bonded-cross-check': None})
    stub(page, answer([stub_checks], current=1))
    page.reload()
    expect(page.locator('#bonded-result-checks')).to_contain_text('could not run: no dihedral in the topology')
    expect(page.locator('#bonded-result-checks')).to_contain_text('bonded-cross-check — not run')
    assert errors == [], errors


def test_a_fit_answer_that_arrives_after_the_reader_moved_on_does_not_paint_the_screen(dashboard, live_page):
    """`fit()`'s own post-await race: an answer for a model the reader has left is dropped, not painted.

    The queue request is delayed inside the page and the mapping is switched while it is outstanding. Without a
    token re-checked after the await, the late answer opens the job box for the previous model's fit -- and that box
    then polls *this* model's content hash for a job that is not its own. The `busy` flag belongs to the answer that
    was dropped too: the panel the reader is looking at has to be usable afterwards.
    """
    first, first_content, _ = save(dashboard, 'First model')
    second, second_content, _ = save(dashboard, 'Second model', molecule='Sucrose')
    assert first_content != second_content, 'the two fixtures are the same content, so this test compares nothing'
    page, errors = live_page
    stub(page, answer([revision(1)]))
    page.add_init_script("""(() => {
      const original = window.fetch;
      window.fetch = async (url, options) => {
        const answer = await original(url, options);
        if (String(url).endsWith('/api/bonded-parameterizations')
            && String((options && options.method) || 'GET').toUpperCase() === 'POST') {
          await new Promise(resolve => setTimeout(resolve, 900));
        }
        return answer;
      };
    })()""")
    open_panel(page, live_page, first['file'])
    # Both engines left fit to an ensemble, so the reference has to be chosen before the button is usable; the wait
    # pins that choice to the reference list having landed, not to this test's timing.
    # The value is re-applied until it sticks: the panel re-renders the picker whenever the reference list lands, and
    # with two references it deliberately answers none rather than guessing -- so a single click can be undone.
    page.wait_for_function(
        f"""() => {{
          const select = document.querySelector('#bonded-aa-reference');
          if (!Array.from(select.options).some(option => option.value)) return false;
          if (select.value !== '{AA_RUN}') {{
            select.value = '{AA_RUN}';
            select.dispatchEvent(new Event('change', {{bubbles: true}}));
          }}
          // Both halves matter: a value the picker still holds with a button the panel has not re-enabled from it
          // is a click that would do nothing.
          return select.value === '{AA_RUN}' && !document.querySelector('#bonded-fit').disabled;
        }}""", timeout=30000)
    page.locator('#bonded-fit').click()
    expect(page.locator('#bonded-fit-status')).to_contain_text('Queueing a Fast-Forward')
    expect(page.locator('#bonded-fit')).to_be_disabled()

    # The reader moves on while the queue answer is still outstanding.
    page.locator('#bonded-mapping-select').select_option(second['file'])
    expect(page.locator('#bonded-result-title')).to_have_text('Revision 1 · current')
    page.wait_for_timeout(1500)

    # The answer landed here, and it is about the model that is no longer on screen.
    expect(page.locator('#bonded-job')).to_be_hidden()
    expect(page.locator('#bonded-result-title')).to_have_text('Revision 1 · current')
    # Not left disabled by a `busy` flag that only the dropped answer would have cleared. The button is disabled here
    # for a reason the panel states -- the model now on screen has no AA reference chosen, and every engine left fits
    # to one -- so the evidence that `busy` was released is the hint replacing the queuing line, not the button.
    expect(page.locator('#bonded-fit-status')).to_have_text('Choose an AA reference: this engine fits to its ensemble.')
    page.wait_for_function(
        "() => { const select = document.querySelector('#bonded-aa-reference');"
        " if (!Array.from(select.options).some(option => option.value)) return false;"
        f" select.value = '{AA_RUN}'; select.dispatchEvent(new Event('change', {{bubbles: true}}));"
        " return !document.querySelector('#bonded-fit').disabled; }", timeout=30000)
    assert errors == [], errors


def test_the_interactions_table_carries_a_source_column(dashboard, live_page):
    """The column the design adds: every term says which engine produced it, or that the mapping did.

    The topology is parsed by the panel from the revision's own ITP in atom names, so the rows are the revision's
    terms and not a restatement of the mapping: a source the store computed lands beside the row it belongs to.
    """
    saved, _, _ = save(dashboard)
    page, errors = live_page
    stub(page, answer([revision(1)]))
    open_panel(page, live_page, saved['file'])

    header = page.locator('.bonded-interaction-table thead th')
    expect(header).to_have_count(5)
    expect(header.nth(4)).to_have_text('Source')
    rows = page.locator('.bonded-interaction-table tbody tr')
    expect(rows).to_have_count(4)
    assert cells(page, 0).nth(0).inner_text() == 'constraints'
    assert cells(page, 0).nth(1).inner_text() == 'B01 · B02'
    assert cells(page, 0).last.inner_text() == 'mapping'
    assert cells(page, 1).last.inner_text() == 'ff_inter'
    assert cells(page, 3).nth(0).inner_text() == 'dihedrals'
    assert cells(page, 3).nth(1).inner_text() == 'B01 · B02 · B03 · B04'
    assert cells(page, 3).last.inner_text() == 'geometry', "a fallback term is not the engine's"
    # The parameters are in the units the section states, not a JSON dump.
    assert cells(page, 0).nth(3).inner_text() == '0.315 nm'
    assert cells(page, 2).nth(2).inner_text() == '10 — Restricted bending'
    assert errors == [], errors


def test_a_term_with_no_recorded_source_says_so_rather_than_borrowing_the_engines(dashboard, live_page):
    """An unknown source is stated as unknown: the column reads the store's list and invents nothing.

    `sources` is computed from the topology when a revision is saved, so a row missing from it is a revision written
    before the column existed. Filling that gap with the engine's default would report `ff_inter` for a term no
    record attributes to `ff_inter` -- a claim the store never made, in the one column whose purpose is to tell a
    hand edit from a fit.
    """
    saved, _, _ = save(dashboard)
    page, errors = live_page
    without_bond = [row for row in SOURCES if row['id'] != 'bonds:1']
    stub(page, answer([revision(1, sources=without_bond)]))
    open_panel(page, live_page, saved['file'])

    expect(page.locator('.bonded-interaction-table tbody tr')).to_have_count(4)
    assert cells(page, 1).nth(0).inner_text() == 'bonds'
    assert cells(page, 1).last.inner_text() == 'unrecorded', cells(page, 1).last.inner_text()
    # The rows the store did answer for keep their own source: this is a gap, not a second answer for everything.
    assert cells(page, 0).last.inner_text() == 'mapping'
    assert cells(page, 3).last.inner_text() == 'geometry'
    assert errors == [], errors


# ------------------------------------------------------------------------------------------ the revision strip


def test_the_revision_strip_shows_each_revision_and_makes_one_current_after_a_confirmation(dashboard, live_page):
    """D1's replacement for the flat state select: the mapping's own history, with one of it current.

    Making an earlier revision current is a PATCH carrying the revision and `confirm: true`, and it is asked for
    first -- `{}` and `null` are not enough, and a dismissed confirmation sends nothing at all.
    """
    saved, content, _ = save(dashboard)
    page, errors = live_page
    history = [revision(1, created_at='2026-10-16T10:00:00+00:00'),
               revision(2, engine='bartender', created_at='2026-10-16T11:00:00+00:00'),
               revision(3, created_at='2026-10-16T14:30:00+00:00')]
    record = answer(history, current=3)

    def make_current(body):
        record['summary'] = summary(body['current'], history)

    _, patches, _ = stub(page, record, on_patch=make_current)
    open_panel(page, live_page, saved['file'])

    items = page.locator('#bonded-revisions .bonded-revision')
    expect(items).to_have_count(3)
    for index, number in enumerate((1, 2, 3)):
        expect(items.nth(index).locator('.bonded-revision-number')).to_have_text(f'r{number}')
        expect(items.nth(index).locator('.bonded-revision-date')).to_have_text('2026-10-16')
    expect(items.nth(1).locator('.bonded-revision-engine')).to_contain_text('BARTENDER')
    expect(items.nth(2)).to_have_attribute('aria-current', 'true')
    expect(items.nth(2).locator('.bonded-make-current')).to_be_disabled()
    expect(items.nth(2).locator('.bonded-make-current')).to_have_text('current')

    # A dismissed confirmation is a refusal.
    items.nth(1).locator('.bonded-make-current').click()
    page.wait_for_timeout(300)
    assert patches == [], patches

    page.on('dialog', lambda dialog: dialog.accept())
    items.nth(1).locator('.bonded-make-current').click()
    page.wait_for_function("() => document.querySelector('#bonded-result-title')?.textContent?.includes('Revision 2')",
                           timeout=10000)
    assert len(patches) == 1, patches
    method, path, body = patches[0]
    assert method == 'PATCH', method
    assert path == f'/bonded-parameterizations/{content}', path
    assert json.loads(body) == {'current': 2, 'confirm': True}, body

    # The strip and the result follow the record, not the click.
    expect(page.locator('#bonded-revisions .bonded-revision').nth(1)).to_have_attribute('aria-current', 'true')
    expect(page.locator('#bonded-result-title')).to_have_text('Revision 2 · current')
    expect(page.locator('#bonded-revisions .bonded-revision').nth(2).locator('.bonded-make-current')).to_be_enabled()
    assert errors == [], errors


# ------------------------------------------------------------------- against the routes, not against a stub


def test_the_panel_renders_a_revision_the_store_itself_made(dashboard, live_page):
    """A revision written by the store, read back through the real routes and drawn by the panel -- no stub anywhere.

    The tests above assert the panel against the design's `## API` table; this one asserts that the table and the store
    agree, which is the failure a stub cannot see. The revision is written with `parameterization.save` -- the call a
    fit ends with -- so what the panel reads is a stored record and not a fixture shaped like one; this used to run the
    reference-free engine instead, which made no MD and no frames and so was the only engine a test could run.
    """
    saved, content, candidate = save(dashboard)
    stored = parameterization.save(saved, revision(1))
    assert stored['revision'] == 1

    page, errors = live_page
    open_panel(page, live_page, saved['file'])
    expect(page.locator('#bonded-result-title')).to_have_text('Revision 1 · current')
    provenance = page.locator('#bonded-result-provenance').inner_text()
    assert 'Fast-Forward' in provenance, provenance
    expect(page.locator('#bonded-revisions .bonded-revision')).to_have_count(1)
    # Every term's source is what the store computed from the revision rather than anything the fixture said: a
    # Fast-Forward revision's terms are the engine's, and the store is what stamps that name onto them.
    sources = set(page.locator('.bonded-interaction-table tbody tr td:last-child').all_inner_texts())
    assert sources == {'ff_inter'}, sources
    assert errors == [], errors


def test_the_panel_fits_a_narrow_window_without_scrolling_sideways(dashboard, live_page):
    """The 390 px guard, on this panel's own cards: a strip of revisions is the obvious place to overflow.

    The revision strip wraps rather than scrolling and the provenance list states its own single column below
    700 px; both are new, so both are measured where a narrow window would show the difference.
    """
    saved, _, _ = save(dashboard)
    page, errors = live_page
    stub(page, answer([revision(1), revision(2), revision(3)], current=3, jobs=[job('failed', error='x', log_tail='y')]))
    page.set_viewport_size({'width': 390, 'height': 844})
    open_panel(page, live_page, saved['file'])
    expect(page.locator('#bonded-result')).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), \
        page.evaluate('document.documentElement.scrollWidth')
    boxes = page.evaluate("""() => ['#bonded-model-summary', '#bonded-result-provenance', '#bonded-revisions',
                                     '.bonded-interaction-table']
      .map(selector => {
        const element = document.querySelector(selector);
        return element ? Math.round(element.getBoundingClientRect().right) : 0;
      })""")
    assert max(boxes) <= 390, boxes
    assert errors == [], errors


# ---------------------------------------------------------------------------------------------- the document


def test_every_id_on_the_page_is_unique(dashboard, live_page):
    """`id` is unique in the document, measured over everything the page renders rather than this panel only.

    The panels are all mounted in one document, and an id used twice resolves to the first one: the second
    panel's control then reads and writes the first panel's element with nothing thrown and nothing logged.
    """
    save(dashboard)
    page, errors = live_page
    stub(page, answer([revision(1)], jobs=[job('failed', error='x', log_tail='y')]))
    page.goto(f'{live_page.base_url}/detergent-validation/bond-interactions')
    page.wait_for_function("() => document.querySelectorAll('#bonded-engine option').length > 0", timeout=30000)
    duplicates = page.evaluate("""() => {
      const seen = new Map();
      for (const element of document.querySelectorAll('[id]')) {
        const id = element.id;
        seen.set(id, (seen.get(id) || 0) + 1);
      }
      return [...seen].filter(([, count]) => count > 1);
    }""")
    assert duplicates == [], f'ids rendered more than once: {duplicates}'
    assert errors == [], errors


# ------------------------------------------------------------------- deleting the mapping from here


def test_the_panel_deletes_the_selected_mapping_and_says_what_went_with_it(dashboard, live_page):
    """The one destructive control on this panel: the editor's own route, and the rule stated before it acts.

    The sentence matters as much as the request. What this replaced -- in the editor, where the button first lived --
    said a mapping's bonded states were *not* deleted, while `mappings.delete_draft` removes them unless another
    saved mapping carries the same content hash. A reader's only warning before an irreversible click has to be the
    behaviour, so this asserts the wording against the answer the route gives.
    """
    first, first_content, _ = save(dashboard, 'First model')
    second, second_content, _ = save(dashboard, 'Second model', molecule='Sucrose')
    page, errors = live_page
    stub(page, answer([revision(1)], current=1))
    dialogs, deletes = [], []

    def remove(route):
        deletes.append((route.request.method, route.request.url.split('/api')[1]))
        # The catalogue this panel re-reads after the deletion: one model left, and not the one deleted.
        page.route(re.compile(r'/api/mappings\?view=summary'),
                   lambda later: later.fulfill(json={'candidates': [second]}))
        route.fulfill(json={'deleted': first['file'], 'parameterization': {
            'content_hash': first_content, 'deleted': True, 'revisions': [1], 'jobs': ['0123456789abcdef'],
            'work': [], 'retained_by': [], 'reason': None}})

    def accept(dialog):
        dialogs.append(dialog.message)
        dialog.accept()

    page.route(re.compile(r'/api/mappings/drafts/'), remove)
    page.on('dialog', accept)
    open_panel(page, live_page, first['file'])
    expect(page.locator('#bonded-delete-mapping')).to_be_enabled()
    expect(page.locator('#bonded-revisions .bonded-revision')).to_have_count(1)

    page.locator('#bonded-delete-mapping').click()
    expect(page.locator('#bonded-mapping-select')).to_have_value(second['file'])

    assert deletes == [('DELETE', f"/mappings/drafts/{first['file']}")], deletes
    assert len(dialogs) == 1, dialogs
    warning = dialogs[0]
    assert 'Its single bond interaction revision is deleted with it' in warning, warning
    assert 'unless another saved mapping has the same content hash' in warning, warning
    assert 'fit jobs and staged frames' in warning, warning
    assert 'not deleted' not in warning, warning
    # The notice is refined once the next model is on screen, so the wait is on that final line rather than on a read
    # taken while the reload is still outstanding.
    expect(page.locator('.bonded-panel-message')).to_contain_text(
        'Mapping deleted: its 1 bond interaction revision went with it. Showing Second model.')
    assert errors == [], errors


def test_deleting_the_last_mapping_empties_the_panel_rather_than_leaving_a_model_on_screen(dashboard, live_page):
    """No mapping left: the select is empty, the delete button is off, and the card says there is no parameterization."""
    saved, content, _ = save(dashboard)
    page, errors = live_page
    stub(page, answer([revision(1)], current=1))
    page.route(re.compile(r'/api/mappings/drafts/'),
               lambda route: (page.route(re.compile(r'/api/mappings\?view=summary'),
                                         lambda later: later.fulfill(json={'candidates': []})),
                              route.fulfill(json={'deleted': saved['file'], 'parameterization': {
                                  'content_hash': content, 'deleted': False, 'revisions': [],
                                  'jobs': [], 'work': [], 'retained_by': ['mapping_candidate_copy.json'],
                                  'reason': 'another saved mapping still carries this content'}}))[-1])
    page.on('dialog', lambda dialog: dialog.accept())
    open_panel(page, live_page, saved['file'])
    expect(page.locator('#bonded-result')).to_be_visible()

    page.locator('#bonded-delete-mapping').click()

    expect(page.locator('#bonded-mapping-select option')).to_have_count(0)
    expect(page.locator('#bonded-delete-mapping')).to_be_disabled()
    expect(page.locator('#bonded-result')).to_be_hidden()
    # With no mapping at all the card's badge says so, which is a different reading from `no parameterization`.
    expect(page.locator('#bonded-model-badge')).to_have_text('no mapping')
    # The answer said another mapping keeps this content, and the panel repeats that rather than claiming a deletion.
    expect(page.locator('.bonded-panel-message')).to_contain_text(
        'its bond interactions are kept, held by mapping_candidate_copy.json')
    expect(page.locator('.bonded-panel-message')).to_contain_text('No saved mapping is left')
    assert errors == [], errors
