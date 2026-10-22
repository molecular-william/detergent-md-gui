"""The Analysis graphs panel's second control: 'Re-score assessment'.

Two things this pins. It is *offered* only for a run whose recorded stages include the assessment -- the control is
not a run-type badge, because a run whose stage 5 never ran has no directory to write a second attempt into. And it
really asks: the request is a POST to the assessment's own route, and the answer -- how many references the attempt
will score with, and which revision they came from -- reaches `#notice`, or the server's refusal does.

What the server does with the request is pinned in `test_assessment_rescore.py`; here it is asked whether the panel
makes it rather than only drawing a control. The response is routed, so no run is actually re-scored.
"""
import re

from playwright.sync_api import expect

from dashboard import files

ASSESSED = 'abcdef123456'
UNASSESSED = 'abcdef654321'
STAGES = ['AA reference', 'trajectory mapping', 'CG parameterization', 'CG simulation',
          'CG assessment (ff_assess)', 'SASA analysis']


def seed(dashboard):
    """One completed run that ran stage 5, and one completed run that ran five stages without it."""
    runs = dashboard.coordinator.RUNS
    dashboard.coordinator.database().replace([
        {'id': job_id, 'label': label, 'detergent': 'DDM', 'method': 'fast_forward', 'profile': 'draft-smoke',
         'status': 'completed', 'stage': 'complete', 'run_type': 'aa_cg', 'created': '2026-09-16T10:00:00+00:00',
         'started_at': '2026-09-16T10:00:00+00:00', 'layout_version': 2, 'analyses': []}
        for job_id, label in ((ASSESSED, 'Scored once'), (UNASSESSED, 'Never assessed'))])
    for job_id, names in ((ASSESSED, STAGES), (UNASSESSED, STAGES[:-2])):
        directory = runs / job_id
        (directory / 'logs').mkdir(parents=True)
        files.atomic_json(directory / 'manifest.json',
                          {'stage_plan': [[name, f'{name}/script.sh'] for name in names],
                           'stages': [{'name': name, 'status': 'completed'} for name in names]})


def test_the_panel_asks_for_a_rescore_and_reports_what_it_will_score_with(dashboard, live_page):
    seed(dashboard)
    page, errors = live_page
    asked = []

    def rescore(route):
        asked.append(route.request.method)
        route.fulfill(json={'attempt': 1, 'directory': 'stages/5_assessment@1', 'references': 28, 'pairs': 28,
                            'revision': 2})

    page.route(re.compile(rf'/api/jobs/{ASSESSED}/assessment/rescore$'), rescore)
    page.goto(f'{live_page.base_url}/detergent-validation/runs')
    card = page.locator(f'.job[data-id="{ASSESSED}"]')
    card.locator('.job-analysis summary').click()

    button = card.get_by_role('button', name='Re-score assessment', exact=True)
    expect(button).to_be_visible()
    button.click()

    expect(page.locator('#notice')).to_contain_text('stages/5_assessment@1')
    expect(page.locator('#notice')).to_contain_text('28 reference histograms')
    expect(page.locator('#notice')).to_contain_text('28 of them pairwise')
    assert asked == ['POST'], 'the panel drew a control that asked nothing'
    assert errors == [], errors


def test_the_control_is_offered_only_for_a_run_that_ran_the_assessment(dashboard, live_page):
    """A run without stage 5 has nothing to re-score, so the control is absent rather than refused on press."""
    seed(dashboard)
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/runs')

    assessed = page.locator(f'.job[data-id="{ASSESSED}"]')
    assessed.locator('.job-analysis summary').click()
    expect(assessed.get_by_role('button', name='Re-score assessment', exact=True)).to_be_visible()

    unassessed = page.locator(f'.job[data-id="{UNASSESSED}"]')
    unassessed.locator('.job-analysis summary').click()
    expect(unassessed.get_by_role('button', name='Re-score assessment', exact=True)).to_be_hidden()
    assert errors == [], errors


def test_a_refusal_reaches_the_notice_rather_than_a_console_error(dashboard, live_page):
    """The refusal is the answer: a run whose model records no pairwise family says so, in the server's own words."""
    seed(dashboard)
    page, errors = live_page
    refusal = ("This model records 13 AA reference histogram(s) for its bonded terms and none of the pairwise distance "
               "histograms the CG assessment scores (55 expected, one `<resid>_<a>_<resid>_<b>_distances_distr.dat` per "
               "bead pair), so it has nothing to score this run against")
    page.route(re.compile(rf'/api/jobs/{ASSESSED}/assessment/rescore$'),
               lambda route: route.fulfill(status=409, json={'error': refusal}))
    page.goto(f'{live_page.base_url}/detergent-validation/runs')
    card = page.locator(f'.job[data-id="{ASSESSED}"]')
    card.locator('.job-analysis summary').click()

    card.get_by_role('button', name='Re-score assessment', exact=True).click()

    expect(page.locator('#notice')).to_contain_text('13 AA reference histogram(s)')
    expect(page.locator('#notice')).to_contain_text('55 expected')
    assert errors == [], errors
