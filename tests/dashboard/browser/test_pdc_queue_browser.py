"""The complex panel's setup controls: a mapping to build from, and a button that queues the build.

The panel had the two gaps the plan names -- nothing to launch with and no way to say which mapping a build is made
of -- so what is pinned here is the pair: the picker follows the template's molecule and posts the *file* the
coordinator resolves, and the button reads readiness before it posts anything, because a build that cannot start
should say why in the panel rather than in a run that dies at stage one.

The queue test deliberately does **not** stub the route it is testing. The button used to POST `/api/jobs`, which
registers GET only (`runs.py:jobs_api`) and so answers 405; the old test intercepted that path and passed while the
button was dead. The POST now goes to the route that exists (`/`, `runs.py:queue`) and the test lets that real route
answer it -- capturing the request and its response instead of intercepting both -- so a wrong target fails here:
the URL checked is the queue route's, and its status is never 405.
"""
import re

from playwright.sync_api import expect

CATALOG = {
    'templates': [{'id': 'DDM:DDM', 'name': 'DDM skeleton', 'molecule': 'DDM', 'residue': 'DDM',
                   'template': 'molecules/DDM/micelle_template.json', 'registered_type': 'registered-template',
                   'files_present': True, 'missing_files': [],
                   'limitations': ['skeleton placeholder template, not a fitted detergent model']}],
    'proteins': [],
    'defaults': {'aggregation_number': 150, 'assessment_ns': 100, 'extension_ns': 900, 'salt_molar': 0.15},
}

CANDIDATE = {'name': 'DDM draft from the automatic recogniser (Martini 3)',
             'file': 'mapping_candidate_2bcc24c3e5f149fab1e4f11f5d80ae0e.json'}
MAPPING_FILE = CANDIDATE['file']


def serve(page, readiness=None):
    """The endpoints the panel reads, with the queue POST left alone so the real route answers it."""
    page.route(re.compile(r'/api/pdc/catalog'), lambda route: route.fulfill(json=CATALOG))
    page.route(re.compile(r'/api/mappings\?'), lambda route: route.fulfill(json={'candidates': [CANDIDATE]}))
    page.route(re.compile(r'/api/readiness\?'),
               lambda route: route.fulfill(json=readiness or {'ready': True, 'checks': [], 'blockers': []}))


def capture_posts(page, posted):
    """Record every POST the page makes, without intercepting any of them."""
    def record(request):
        if request.method == 'POST':
            posted.update(request.post_data_json or {})
    page.on('request', record)


def test_the_build_button_posts_to_the_route_that_accepts_post(dashboard, live_page):
    """No route stub: the build is POSTed to the real `/`. The old target (`/api/jobs`) registers GET only, so a
    regression would show up here as the wrong URL or a 405; the request payload is read off the request itself."""
    page, errors = live_page
    posted = {}
    serve(page)
    capture_posts(page, posted)
    page.goto(f'{live_page.base_url}/protein-detergent/complexes')

    expect(page.locator('#pdc-mapping')).to_have_value(MAPPING_FILE, timeout=30000)
    expect(page.locator('#pdc-queue')).to_be_enabled()

    with page.expect_response(lambda response: response.request.method == 'POST') as outcome:
        page.locator('#pdc-queue').click()
    response = outcome.value

    # The queue route answered: the URL is `/`, and its status is its own answer, never Method Not Allowed. (The
    # scratch workspace holds no mapping for DDM to resolve, so the route refuses it -- a refusal only the real
    # route can produce, and the assertion that would fail on the old, GET-only target.)
    assert response.url.rstrip('/') == live_page.base_url.rstrip('/'), response.url
    assert response.status != 405, 'the POST reached a route that does not accept POST'

    # The payload is the shape `queue()` reads: `protein` (a path or null) and a seed the adapter requires, beside
    # the settings under their `pdc_` names.
    assert posted['run_type'] == 'pdc' and posted['method'] == 'bartender', posted
    assert posted['molecule_id'] == 'DDM', posted
    assert posted['template'] == 'molecules/DDM/micelle_template.json', posted
    assert posted['mapping_candidate'] == MAPPING_FILE, posted
    assert posted['protein'] is None, posted
    assert 'protein_free' not in posted, 'protein_free was a key nothing consumed'
    assert isinstance(posted['pdc_seed'], int) and posted['pdc_seed'] > 0, 'the adapter requires a seed'
    assert posted['aggregation_number'] == 150, 'the settings are the catalogue defaults the pipeline is prepared with'
    assert posted['pdc_assessment_ns'] == 100, "the builders' assessment_ns reaches the route under its pdc_ spelling"

    # The panel repeats the route's own message, not a bare HTTP status.
    expect(page.locator('#pdc-panel-status')).to_contain_text('That build was refused', timeout=30000)
    expect(page.locator('#pdc-panel-status')).not_to_contain_text('405')
    assert errors == []


def test_a_build_that_is_not_ready_says_why_instead_of_queueing(dashboard, live_page):
    """Readiness is read first: a refused build names its blocker in the panel, and nothing is posted."""
    page, errors = live_page
    posted = {}
    serve(page, readiness={'ready': False, 'checks': [],
                           'blockers': ['Detergent template: not a file: molecules/DDM/nothing.json']})
    capture_posts(page, posted)
    page.goto(f'{live_page.base_url}/protein-detergent/complexes')
    expect(page.locator('#pdc-mapping')).to_have_value(MAPPING_FILE, timeout=30000)

    page.locator('#pdc-queue').click()

    expect(page.locator('#pdc-panel-status')).to_contain_text('Detergent template: not a file', timeout=30000)
    assert posted == {}, 'a build that cannot start is not queued'
    assert errors == []
