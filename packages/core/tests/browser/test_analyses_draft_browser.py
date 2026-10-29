"""The Analyses control, as the draft renders it: which kinds a completed run can be asked for, and which it cannot.

**This file and `static/analyses-draft.html` are deleted together when the control lands in the run card.** It exists
so the draft's words and states are pinned while the layout is being judged, the same arrangement the two-monitor Run
view used.

No test here queues a real analysis. BARTENDER is minutes of CPU and `dihedral-fit` is uncounted, so the queue route
is stubbed and what is asserted is the request the control would make -- method, path and body -- rather than the
attempt it would leave behind. The one published-report test stubs the reader for the same reason: the readers have
their own tests, and this one is about the link the control offers.

The artifact index is read as the control reads it -- one search per declared input -- so a planted file is what makes
a kind available, and a kind's unavailable sentence names the path that is actually missing.
"""
import re

from playwright.sync_api import expect

DRAFT = '/static/analyses-draft.html'
#: What `dihedral-fit` and `bonded-cross-check` declare, planted so both kinds are available.
BONDED_INPUTS = ('2_mapping/mapped.gro', '2_mapping/mapped.xtc', '2_mapping/model.json',
                 '3_initial_CG/LIG1_ff_inter.itp', '3_initial_CG/LIG1_initial.itp')
#: What `bartender-fit` declares on top of `2_mapping/model.json`; the AA reference is deliberately not among them in
#: the second fixture, because that is the state the E3 maltose run is in.
AA_REFERENCE = ('1_AA-reference/prod/lig.gro', '1_AA-reference/prod/lig.xtc')
MAPPING_NDX = '2_mapping/mapping.ndx'
INITIAL_ITP = '3_initial_CG/LIG1.itp'


def plant(dashboard, jid, *, status='completed', files=(), analyses=None):
    """A run whose record says `status` and whose own files are exactly `files`."""
    runs = dashboard.coordinator.RUNS
    runs.mkdir(parents=True, exist_ok=True)
    record = {'id': jid, 'label': 'E3 maltose CG', 'detergent': 'Maltose', 'method': 'fast_forward',
              'run_type': 'aa_cg', 'profile': 'draft-smoke-reference', 'reference_run_id': 'dbc366ae772b',
              'molecule_id': 'Maltose', 'status': status, 'stage': 'complete',
              'created': dashboard.coordinator.now()}
    if analyses is not None:
        record['analyses'] = analyses
    dashboard.coordinator.database().replace([record])
    for relative in files:
        path = runs / jid / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('')
    return runs / jid


def open_draft(page, live_page, jid):
    page.goto(f'{live_page.base_url}{DRAFT}?run={jid}')
    page.wait_for_selector('#kinds tr')


def row(page, label):
    return page.locator('#kinds tr', has=page.locator(f'strong:text-is("{label}")'))


def test_the_draft_offers_the_kinds_it_can_queue_and_names_every_input_they_read(dashboard, live_page):
    page, _ = live_page
    plant(dashboard, 'aa00aa000001', files=BONDED_INPUTS)
    open_draft(page, live_page, 'aa00aa000001')

    expect(page.locator('#kinds tr')).to_have_count(3)
    bonded = row(page, 'Dihedral terms · a criterion against the tool default')
    expect(bonded.locator('button')).to_be_enabled()
    for declared in ('2_mapping/mapped.gro', '2_mapping/mapped.xtc', '2_mapping/model.json',
                     '3_initial_CG/*_ff_inter.itp', '3_initial_CG/*initial*.itp'):
        expect(bonded.locator('code', has_text=declared)).to_have_count(1)
    expect(bonded.locator('.mark.present')).to_have_count(5)


def test_a_kind_the_run_cannot_answer_is_disabled_and_names_the_input_that_is_missing(dashboard, live_page):
    page, _ = live_page
    # Everything `bartender-fit` needs except its AA reference -- which is exactly the E3 maltose run's state, where
    # the reference trajectory lives in the paired AA run rather than under this run's `stages/1_AA-reference/prod`.
    plant(dashboard, 'aa00aa000002', files=(*BONDED_INPUTS, MAPPING_NDX, INITIAL_ITP))
    open_draft(page, live_page, 'aa00aa000002')

    bartender = row(page, 'BARTENDER bonded fit')
    expect(bartender.locator('button')).to_be_disabled()
    expect(bartender.locator('.reason')).to_have_text(
        'cannot run: 1_AA-reference/prod/lig.gro, 1_AA-reference/prod/lig.xtc are not in this run')
    # The kinds that can run are untouched by their neighbour's absence.
    expect(row(page, 'Dihedral terms · a criterion against the tool default').locator('button')).to_be_enabled()


def test_queueing_posts_to_the_kinds_own_route_and_nothing_is_simulated_again(dashboard, live_page):
    page, _ = live_page
    plant(dashboard, 'aa00aa000003', files=BONDED_INPUTS)
    asked = []
    page.route(re.compile(r'/api/jobs/aa00aa000003/dihedral-fit$'),
               lambda route: (asked.append((route.request.method, route.request.post_data)),
                              route.fulfill(json={'id': 'newtask', 'kind': 'dihedral-fit', 'status': 'queued'}))[-1])
    page.on('dialog', lambda dialog: dialog.accept())
    open_draft(page, live_page, 'aa00aa000003')

    row(page, 'Dihedral terms · a criterion against the tool default').locator('button').click()
    page.wait_for_timeout(500)
    # The reader for this kind lives on the same path as its queue route, so only the POSTs are the control's doing.
    posts = [entry for entry in asked if entry[0] == 'POST']
    assert posts == [('POST', '{}')], asked


def test_a_live_attempt_disables_the_button_and_offers_cancel_instead(dashboard, live_page):
    page, _ = live_page
    plant(dashboard, 'aa00aa000004', files=BONDED_INPUTS,
          analyses=[{'id': 'task1', 'kind': 'dihedral-fit', 'status': 'running',
                     'started_at': '2026-10-16T00:00:00+00:00', 'created_at': '2026-10-16T00:00:00+00:00'}])
    open_draft(page, live_page, 'aa00aa000004')

    bonded = row(page, 'Dihedral terms · a criterion against the tool default')
    expect(bonded.locator('button')).to_be_disabled()
    expect(bonded.locator('button')).to_have_attribute(
        'title', 'An attempt is already queued or running')
    # The payload carries no `progress` and no `error`, so the row states the status and the duration it does hold.
    expect(page.locator('.attempt', has_text='dihedral-fit')).to_contain_text('running')
    expect(page.locator('.attempt button')).to_have_text('Cancel')


def test_a_published_report_is_linked_through_the_route_that_reads_it(dashboard, live_page):
    page, _ = live_page
    plant(dashboard, 'aa00aa000005', files=BONDED_INPUTS)
    # Stubbed, not planted: the reader's own file layout is asserted where the reader is, and this test is about the
    # link the control offers a reader who has a report.
    page.route(re.compile(r'/api/jobs/aa00aa000005/bonded-cross-check$'),
               lambda route: route.fulfill(json={'terms': [{'section': 'bonds', 'atoms': [0, 4]}]}))
    open_draft(page, live_page, 'aa00aa000005')

    link = row(page, 'Bonded terms · our fit against the estimate').locator('a')
    expect(link).to_have_text('Published report')
    expect(link).to_have_attribute('href', '/api/jobs/aa00aa000005/bonded-cross-check')
    # And a kind with no report published offers no link rather than an empty one.
    expect(row(page, 'Dihedral terms · a criterion against the tool default').locator('a')).to_have_count(0)


def test_a_run_that_is_not_completed_is_not_offered_at_all(dashboard, live_page):
    page, _ = live_page
    plant(dashboard, 'aa00aa000006', status='running', files=BONDED_INPUTS)
    plant(dashboard, 'aa00aa000007', status='completed', files=BONDED_INPUTS)
    page.goto(f'{live_page.base_url}{DRAFT}')
    page.wait_for_selector('#kinds tr')

    options = page.locator('#run-pick option')
    expect(options).to_have_count(1)
    assert page.locator('#run-pick').input_value() == 'aa00aa000007'
