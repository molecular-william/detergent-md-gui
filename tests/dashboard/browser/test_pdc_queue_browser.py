"""The complex panel's setup controls: a mapping to build from, and a button that queues the build.

The panel had the two gaps the plan names -- nothing to launch with and no way to say which mapping a build is made
of -- so what is pinned here is the pair: the picker follows the template's molecule and posts the *file* the
coordinator resolves, and the button reads readiness before it posts anything, because a build that cannot start
should say why in the panel rather than in a run that dies at stage one.
"""
import re

from playwright.sync_api import expect

CATALOG = {
    'templates': [{'id': 'DDM:DDM', 'name': 'DDM skeleton', 'molecule': 'DDM', 'residue': 'DDM',
                   'template': 'molecules/DDM/micelle_template.json', 'registered_type': 'registered-template',
                   'files_present': True, 'missing_files': [],
                   'limitations': ['skeleton placeholder template, not a fitted detergent model']}],
    'proteins': [],
    'defaults': {'aggregation_number': 150, 'assessment_ns': 100, 'salt_molar': 0.15},
}

CANDIDATE = {'name': 'DDM draft from the automatic recogniser (Martini 3)',
             'file': 'mapping_candidate_2bcc24c3e5f149fab1e4f11f5d80ae0e.json'}
MAPPING_FILE = CANDIDATE['file']


def serve(page, posted, readiness=None):
    """The four endpoints this panel reads, with the queue POST captured instead of sent."""
    page.route(re.compile(r'/api/pdc/catalog'), lambda route: route.fulfill(json=CATALOG))
    page.route(re.compile(r'/api/mappings\?'), lambda route: route.fulfill(json={'candidates': [CANDIDATE]}))
    page.route(re.compile(r'/api/readiness\?'),
               lambda route: route.fulfill(json=readiness or {'ready': True, 'checks': [], 'blockers': []}))

    def queue(route):
        # Only the POST is this panel's; the runs table reads the same path, so everything else goes through.
        if route.request.method != 'POST':
            route.fallback()
            return
        posted.update(route.request.post_data_json or {})
        route.fulfill(status=201, json={'id': 'pdcqueued1', 'run_type': 'pdc'})

    page.route(re.compile(r'/api/jobs'), queue)


def test_the_panel_offers_the_saved_mappings_and_queues_the_build_it_describes(dashboard, live_page):
    page, errors = live_page
    posted = {}
    serve(page, posted)
    page.goto(f'{live_page.base_url}/#pdc')

    select = page.locator('#pdc-mapping')
    expect(select).to_have_value(MAPPING_FILE, timeout=30000)
    expect(select.locator('option')).to_have_text([CANDIDATE['name']])
    expect(page.locator('#pdc-queue')).to_be_enabled()

    page.locator('#pdc-queue').click()

    expect(page.locator('#pdc-panel-status')).to_contain_text('pdcqueued1', timeout=30000)
    assert posted['run_type'] == 'pdc' and posted['method'] == 'bartender', posted
    assert posted['molecule_id'] == 'DDM', posted
    assert posted['template'] == 'molecules/DDM/micelle_template.json', posted
    assert posted['mapping_candidate'] == MAPPING_FILE, posted
    assert posted['protein_free'] is True, 'an empty micelle is the choice the panel leads with'
    assert posted['aggregation_number'] == 150, 'the settings are the catalogue defaults the pipeline is prepared with'
    assert errors == []


def test_a_build_that_is_not_ready_says_why_instead_of_queueing(dashboard, live_page):
    """Readiness is read first: a refused build names its blocker in the panel, and nothing is posted."""
    page, errors = live_page
    posted = {}
    serve(page, posted, readiness={'ready': False, 'checks': [],
                                   'blockers': ['Detergent template: not a file: molecules/DDM/nothing.json']})
    page.goto(f'{live_page.base_url}/#pdc')
    expect(page.locator('#pdc-mapping')).to_have_value(MAPPING_FILE, timeout=30000)

    page.locator('#pdc-queue').click()

    expect(page.locator('#pdc-panel-status')).to_contain_text('Detergent template: not a file', timeout=30000)
    assert posted == {}, 'a build that cannot start is not queued'
    assert errors == []
