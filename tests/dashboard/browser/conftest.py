"""One browser and one live server for the browser tier, instead of nine copies of the same setup.

Every browser file used to launch Playwright, launch Chromium, build a server on port 0, start a
thread serving it, and tear the lot down -- the same 25 lines around a handful of assertions. The
browser is the expensive part and is safe to share, so it is session-scoped; the application is
not, because each test seeds its own workspace and database, so the server and the page are
per-test.

Usage:

    def test_something(dashboard, live_page):
        dashboard.coordinator.database().replace(jobs)     # seed through the built application
        page, errors = live_page
        page.goto(f'{live_page.base_url}/detergent-validation/runs')
        expect(page.locator('#jobs')).to_be_visible()
        assert not errors

`live_page` is a `LivePage` record rather than a bare page: the assertion lines in these tests
already refer to a local `errors` list, and unpacking keeps them untouched.

Waiting: most of these tests click a control and then assert on something a fetch fills in.
Playwright's default expectation timeout is 5 s, which was chosen for one worker on an idle machine:
this tier runs sixteen, and each page loads the Plotly bundle and draws WebGL scenes. The whole tier
therefore sets one expectation timeout of 15 s in the session fixture below, because a wait that
expires while the machine is busy reports a broken panel that is not broken.

Asserting "not empty" is still not a wait. Where a test waits for content to appear it calls
`locator.first.wait_for(timeout=30000)` first and keeps its assertion after that; the two other
timeouts a test sets itself -- a plot's first paint at 20 s, a reference picker at 30 s -- are there
because those waits are longer than any expectation should be.
"""
import threading
from dataclasses import dataclass, field

import pytest
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

from tests.dashboard.support import QuietHandler


@dataclass
class LivePage:
    """A page pointed at the test's own server, plus the page errors seen on it."""
    page: object
    base_url: str
    errors: list = field(default_factory=list)

    def __iter__(self):
        """Unpack as `page, errors = live_page`, so existing assertions keep working."""
        return iter((self.page, self.errors))


@pytest.fixture(scope='session')
def browser():
    """Chromium, launched once for the whole tier, with the tier's own expectation timeout."""
    # 15 s, not Playwright's 5: this tier runs in parallel and its pages draw 3D scenes, so an expectation that names a
    # fetched answer can lose a race with the machine rather than with the code. Measured on an idle box: the tier is
    # green at 5 s; under load the same waits expire at 5 s while the panel is fine.
    expect.set_options(timeout=15000)
    with sync_playwright() as playwright:
        launched = playwright.chromium.launch(channel='chrome', headless=True)
        try:
            yield launched
        finally:
            launched.close()


@pytest.fixture
def live_server(dashboard):
    """The test's application on a real port, served from a thread, torn down afterwards."""
    server = make_server('127.0.0.1', 0, dashboard.app, request_handler=QuietHandler, threaded=True)
    # Werkzeug's default poll interval is 0.5 s, and `shutdown()` waits for one poll: every test paid up to half a
    # second after its last assertion. The server is per test, so this is the cheapest teardown win in the tier.
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.02), daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        thread.join(timeout=10)


@pytest.fixture
def live_page(browser, live_server):
    """A fresh page on the live server, collecting the page errors the tests assert on."""
    context = browser.new_context(viewport={'width': 1700, 'height': 1050},
                                  permissions=['clipboard-read', 'clipboard-write'])
    page = context.new_page()
    record = LivePage(page=page, base_url=live_server)
    page.on('pageerror', lambda error: record.errors.append(str(error)))
    try:
        yield record
    finally:
        context.close()
