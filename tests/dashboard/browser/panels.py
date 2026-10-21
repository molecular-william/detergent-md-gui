"""Opening a panel on the test's server, and answering the calls it makes on mount.

Every browser file wrote the same three steps -- navigate, maybe click the tab that reveals the panel, then wait for the
panel's *own* signal -- and thirteen of them wrote it slightly differently. A fixed delay would be a test of the machine;
waiting for the signal is a test of the panel, so the signal stays a per-file argument and only the mechanics are here.

The pattern stays the same as elsewhere in the suite: shared construction, per-file meaning. A file writes

    def open_panel(page, base_url):
        return panels.open_panel(page, base_url, '/detergent-validation/osmotic-pressure',
                                 ready=lambda page: expect(page.locator('#osmotic-pressure:not([hidden])'))
                                 .to_be_visible())

and its tests keep calling `open_panel(page, live_page.base_url)` unchanged.
"""
from __future__ import annotations

import re


def open_panel(page, base_url, path, *, tab=None, ready=None):
    """Navigate to `path`, optionally click a tab, then wait for the panel's own mount signal.

    `ready` takes the page, so a file can wait on an attribute, a visible panel, or a JS predicate about its own data
    without the fixture having to guess which kind it is.
    """
    page.goto(f'{base_url}{path}')
    if tab is not None:
        page.get_by_role('tab', name=tab, exact=True).click()
    if ready is not None:
        ready(page)
    return page


def serve_json(page, pattern, payload=None):
    """Answer requests matching `pattern` (a regex string) with JSON.

    `payload` is the body, or a callable taking the request when the answer depends on it -- a readiness probe asking
    about a run this test has not built, for instance.
    """
    expression = re.compile(pattern)
    page.route(expression, lambda route: route.fulfill(
        json=payload(route.request) if callable(payload) else payload))


def serve_files(page, *pairs):
    """Answer several GETs at once: `serve_files(page, (r'/api/a', body), (r'/api/b', other))`.

    A panel on mount asks for the catalogue, then the mappings, then readiness; stating them in one call says "these are
    the answers this panel receives" in one place instead of three consecutive `page.route` lines per file.
    """
    for pattern, payload in pairs:
        serve_json(page, pattern, payload)


def open_pdc_new_run(page, base_url, *, protein=None, chains=False):
    """The protein-detergent *New run* panel, mounted with the lists its own claims need.

    Seven files opened this panel with the same four lines and one real difference -- whether they go on to choose a
    protein, and whether they then need that choice's chains. The detergent list is the panel's first fetch; the protein
    list is the catalogue's answer to the workspace, awaited only when a case chooses from it, because a run with no
    protein is a case these tests cover.
    """
    def ready(page):
        page.wait_for_function("() => document.querySelectorAll('#new-detergent option').length > 1", timeout=30000)
        if protein is None:
            return
        page.wait_for_function("() => document.querySelectorAll('#new-protein option').length > 1", timeout=30000)
        page.locator('#new-protein').select_option(protein)
        if chains:
            page.wait_for_function("() => document.querySelectorAll('[name=protein_chains]').length > 0",
                                   timeout=30000)

    return open_panel(page, base_url, '/protein-detergent/new-run', tab='New run', ready=ready)
