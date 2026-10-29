"""Plotly is fetched on demand, not on every page load.

Assertions, each about one load of the same channel:

A. A page load that plots nothing -- `/detergent-validation/runs`, through the `dashboard` and `live_page`
   fixtures -- issues **no** request for the bundle and leaves `window.Plotly` undefined. The 4.8 MB bundle
   used to be an unconditional `<script>` in the template, so every panel paid for it, including the ones
   that never draw a chart.

B. Opening a panel that plots -- the Bonded workspace, reached by clicking its tab from the load in A --
   issues that request **exactly one** time, after which `window.Plotly` exists and the host carries
   Plotly's own `.plotly` class. A re-render (a bead click) must not fetch the bundle again.

C. Two concurrent callers, from two copies of the module, share **one** script element. This is the case the
   shared `loading` promise cannot cover on its own: `loading` lives in a module instance, and a page can hold
   more than one.

D. A bundle that fails to load leaves no element behind, and the next ask is not a wait on the element that
   already failed.

E. The Mapping Validation panel's text does not wait for the bundle: its tables are filled, and readable,
   while the bundle is still held open.

Every assertion about the bundle's URL derives it from `meta[name="plotly-src"]`, which the template writes
from the route: the URL is defined in one place and the tests read that place rather than repeating it.
"""
from dashboard.models import mappings
from playwright.sync_api import expect

from tests.dashboard.browser.test_mapping_validation_browser import publish, publish_cross_check


def bundle_url(page):
    """Where the template says the bundle lives."""
    return page.evaluate("() => document.querySelector('meta[name=\"plotly-src\"]')?.content")


def bundle_requests(requests, url):
    return [request for request in requests if url and url in request]


def test_a_page_that_plots_nothing_fetches_no_plotly(dashboard, live_page):
    """Load A: the run list requests no Plotly bundle and defines no `window.Plotly`."""
    page, errors = live_page
    requests = []
    page.on('request', lambda request: requests.append(request.url))
    page.goto(f'{live_page.base_url}/detergent-validation/runs')
    expect(page.locator('#jobs')).to_be_visible(timeout=30000)

    src = bundle_url(page)
    assert src, 'the template states no bundle URL, so no panel could ask for one'
    assert not bundle_requests(requests, src), requests
    assert page.evaluate('typeof window.Plotly') == 'undefined', 'Plotly was already on the page at load'
    assert page.evaluate("() => document.querySelectorAll('script[data-plotly]').length") == 0
    assert errors == []


def test_the_bonded_panel_fetches_plotly_once_and_draws(dashboard, live_page):
    """Load B: the same load fetches nothing; opening the plotting panel fetches the bundle exactly once."""
    saved = mappings.save_draft(mappings.automatic_candidate(mappings.molecule(), 'DDM'))
    page, errors = live_page
    requests = []
    page.on('request', lambda request: requests.append(request.url))
    page.goto(f'{live_page.base_url}/detergent-validation/runs')
    expect(page.locator('#jobs')).to_be_visible(timeout=30000)
    src = bundle_url(page)
    assert not bundle_requests(requests, src), requests

    page.locator('#tab-bonded').click()
    expect(page.locator('.bonded-mapping-select')).to_have_value(saved['file'])
    expect(page.locator('.bonded-plot .plotly')).to_be_visible(timeout=30000)

    assert len(bundle_requests(requests, src)) == 1, requests
    assert page.evaluate('!!window.Plotly') is True, 'the plot appeared without a Plotly global'

    # A later request for the same module shares the one bundle: no second <script> is injected.
    page.evaluate("""async () => {
        const loader = await import('/static/js/plotly-loader.js');
        await loader.ensurePlotly();
        await loader.ensurePlotly();
    }""")
    assert len(bundle_requests(requests, src)) == 1, requests

    # The click wiring moved behind the lazy draw, and a bead click re-renders this module: both have to
    # survive the bundle arriving late. Plotly drops anything emitted into the div before our handler is
    # attached, so the wait is for the handler (the module records the moment), then one emission, then the
    # effect. Emitting from inside the predicate is what re-entered the handler: a poll landing between the
    # handler's own state and the status text toggled the bead straight back off.
    page.wait_for_function(
        "() => document.querySelector('.bonded-plot')?.dataset.clickReady === 'true'", timeout=30000)
    page.evaluate("""() => {
        const host = document.querySelector('.bonded-plot');
        const bead = host.data.find(trace => trace.meta === 'bead');
        host.emit('plotly_click', {points: [{data: {meta: 'bead'}, customdata: [bead.text[0], 'R']}]});
    }""")
    expect(page.locator('.bonded-selection-status')).to_contain_text('Selected beads:', timeout=30000)
    expect(page.locator('.bonded-plot .plotly')).to_be_visible(timeout=30000)
    # That re-render asked for nothing further: one bundle, one script.
    assert len(bundle_requests(requests, src)) == 1, requests
    assert errors == []


def test_two_copies_of_the_loader_share_one_script_element(dashboard, live_page):
    """Load C: concurrent callers, from two module instances, wait on one element and one request.

    The early return on `window.Plotly` is not this case: it is the state after a load. Here the bundle is
    absent, both copies start at the same moment, and the element in the document is the only record they
    share -- without it each copy appends its own script and the page downloads 4.8 MB twice.
    """
    page, errors = live_page
    requests = []
    page.on('request', lambda request: requests.append(request.url))
    page.goto(f'{live_page.base_url}/detergent-validation/runs')
    expect(page.locator('#jobs')).to_be_visible(timeout=30000)
    src = bundle_url(page)
    assert not bundle_requests(requests, src), requests

    shared = page.evaluate("""async () => {
        const meta = document.querySelector('meta[name="plotly-src"]').content;
        const first = await import('/static/js/plotly-loader.js');
        const second = await import('/static/js/plotly-loader.js?copy=2');
        const results = await Promise.all([first.ensurePlotly(), second.ensurePlotly()]);
        const wanted = new URL(meta, location.href).href;
        return {
            onePromise: results[0] === results[1] && results[0] === window.Plotly,
            marked: document.querySelectorAll('script[data-plotly]').length,
            pointingAtBundle: [...document.querySelectorAll('script')].filter(script => script.src === wanted).length,
        };
    }""")
    assert shared['onePromise'] is True, shared
    assert shared['marked'] == 1, shared
    assert shared['pointingAtBundle'] == 1, 'two script elements were pointed at the bundle'
    assert len(bundle_requests(requests, src)) == 1, requests
    assert errors == []


def test_a_failed_bundle_leaves_nothing_for_a_retry_to_wait_on(dashboard, live_page):
    """Load D: the failed element is removed, so the retry is a fresh ask rather than a wait that never ends."""
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/runs')
    expect(page.locator('#jobs')).to_be_visible(timeout=30000)
    src = bundle_url(page)

    page.evaluate("""() => { document.querySelector('meta[name="plotly-src"]').content = '/static/js/no-plotly-here.js'; }""")
    failure = page.evaluate("""async () => {
        const loader = await import('/static/js/plotly-loader.js');
        try { await loader.ensurePlotly(); return 'resolved'; } catch (error) { return error.message; }
    }""")
    assert 'could not be fetched' in failure, failure
    assert page.evaluate("() => document.querySelectorAll('script[data-plotly]').length") == 0, \
        'the element that failed is still in the document, and its error event will not fire again'

    page.evaluate("""(src) => { document.querySelector('meta[name="plotly-src"]').content = src; }""", src)
    retry = page.evaluate("""async () => {
        const loader = await import('/static/js/plotly-loader.js');
        await loader.ensurePlotly();
        return {plotly: !!window.Plotly, scripts: document.querySelectorAll('script[data-plotly]').length};
    }""")
    assert retry == {'plotly': True, 'scripts': 1}, retry


def test_the_validation_panel_text_does_not_wait_for_the_bundle(dashboard, live_page):
    """Load E: the cards below the chart read before the chart can draw.

    `render` used to await the per-bead chart, which awaits the bundle: every card after it -- the envelopes,
    the overlap, the cross-check, the dihedral fit, the interpretation -- waited on 4.8 MB for a picture that
    states no number the tables do not. The bundle is held open here, and the last card must still fill.
    """
    publish(dashboard, 'aa11bb22cc33')
    publish_cross_check(dashboard, 'aa11bb22cc33')
    page, errors = live_page
    held = []

    def hold(route):
        if route.request.url.endswith('.js'):
            held.append(route)
        else:
            route.continue_()

    page.route('**/api/assets/*', hold)
    page.goto(f'{live_page.base_url}/detergent-validation/mapping-validation')

    page.wait_for_function(
        "() => document.querySelectorAll('#validation-crosscheck-rows tr').length === 3", timeout=30000)
    assert page.evaluate("() => document.querySelector('#validation-shape-plot').data === undefined"), \
        'the chart drew before the bundle was released, so the hold proved nothing'
    assert held, 'the panel never asked for the bundle'
    assert held[0].request.url.endswith(bundle_url(page)), held[0].request.url

    for route in held:
        route.continue_()
    page.wait_for_function(
        "() => { const host = document.querySelector('#validation-shape-plot');"
        " return host && host.data && host.data.length === 1; }", timeout=30000)
    assert errors == []
