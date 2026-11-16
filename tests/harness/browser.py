"""Opening a panel on the test's server, and answering the calls it makes on mount.

Every browser file wrote the same three steps -- navigate, maybe click the tab that reveals the panel, then wait for the
panel's *own* signal -- and thirteen of them wrote it slightly differently. A fixed delay would be a test of the machine;
waiting for the signal is a test of the panel, so the signal stays a per-file argument and only the mechanics are here.

The pattern stays the same as elsewhere in the suite: shared construction, per-file meaning. A file writes

    def open_panel(page, base_url):
        return browser.open_panel(page, base_url, '/detergent-validation/osmotic-pressure',
                                 ready=lambda page: expect(page.locator('#osmotic-pressure:not([hidden])'))
                                 .to_be_visible())

and its tests keep calling `open_panel(page, live_page.base_url)` unchanged.
"""
from __future__ import annotations

import re
import time

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect

from tests.harness.support import automatic_mapping

#: What the bead legend calls each Martini 3 polarity family, keyed by the family code in the DOM. The legend is a
#: contract of its own -- a reader reads these words -- so the expected labels live here once rather than in each test.
BEAD_FAMILY_LABELS = {
    'unstated': 'family not stated',
    'C': 'apolar (C)',
    'N': 'nonpolar (N)',
    'P': 'polar (P)',
    'Q': 'charged (Q)',
}


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


def open_run_section(page, base_url, jid, section, card='#run-view-analysis-A'):
    """Open the Run view on one run and one analysis section, and return that section's pane."""
    page.goto(f'{base_url}/detergent-validation/run-view?run={jid}')
    root = page.locator(card)
    expect(root.locator('.analysis-views button').first).to_be_visible(timeout=30000)
    root.locator(f'.analysis-views button[data-section="{section}"]').click()
    pane = root.locator(f'.analysis-pane[data-section="{section}"]')
    expect(pane).to_be_visible()
    return pane


def seed_mapping_candidate(dashboard, molecule):
    """A scoped candidate in the fixture's workspace, saved the way the panel saves one."""
    from dashboard.models.mappings import context as mapping_context

    context = dashboard.client.get(f'/api/mappings/context?molecule_id={molecule}').get_json()['context']
    candidate = automatic_mapping(mapping_context.as_structure(context), molecule)
    candidate['molecule_id'] = molecule
    candidate['molecule_snapshot'] = context['snapshot']
    response = dashboard.client.post('/api/mappings/drafts', json=candidate)
    assert response.status_code == 201, response.get_json()
    return context, response.get_json()


#: The bead editor's 3D overlay -- the seam both mapping overlay files read.
MAPPING_OVERLAY = '#mapping-editor-overlay3d'


def open_mapping_editor(page, base_url, molecule, *, ready=True):
    """Open the bead editor on `molecule`, selecting it the way a reader does.

    `ready=True` waits for the editor's own busy attributes to clear and for the 3D overlay to hold the molecule and
    its beads. `ready=False` is the bond overlay's wait instead: the same two components, but only once the drawn
    structure carries the model's own bonds (`bondStore`), because that file reads them.
    """
    page.goto(f'{base_url}/detergent-validation/bead-assignment')
    # The mapping tab carries aria-label="CG mappings", so its accessible name is not the text on the button. The
    # id is the one handle that does not depend on how it is labelled.
    page.locator('#tab-mappings').click()
    page.wait_for_function("() => document.querySelector('#mapping-molecule')?.options.length > 0", timeout=30000)
    page.locator('#mapping-molecule').select_option(molecule)
    if ready:
        # The overlay still holds the previously selected molecule until the load answers: wait for the editor's own
        # busy state rather than for a stage the old molecule is already drawing.
        expect(page.locator('.molecule-mapping-workspace')).to_have_attribute('aria-busy', 'false')
        expect(page.locator(MAPPING_OVERLAY)).to_have_attribute('aria-busy', 'false')
        check = (f"() => document.querySelector('{MAPPING_OVERLAY}')?.overlayStage"
                 f" && document.querySelector('{MAPPING_OVERLAY}').overlayStage.compList.length >= 2")
    else:
        check = (f"() => document.querySelector('{MAPPING_OVERLAY}')?.overlayStage"
                 f" && document.querySelector('{MAPPING_OVERLAY}').overlayStage.compList.length >= 2"
                 f" && document.querySelector('{MAPPING_OVERLAY}').overlayStage.compList[0]?.structure?.bondStore")
    page.wait_for_function(check, timeout=60000)


def choose_fit_target(page, file, molecule=None):
    """Point the merged fit card at one mapping: its own molecule select, then its own mapping select."""
    page.wait_for_function(
        "() => document.querySelectorAll('#bonded-fit-molecule option').length > 0", timeout=30000)
    if molecule:
        page.locator('#bonded-fit-molecule').select_option(molecule)
    page.wait_for_function(
        """(file) => Array.from(document.querySelectorAll('#bonded-fit-mapping option'))
          .some(option => option.value === file)""", arg=file, timeout=30000)
    if page.locator('#bonded-fit-mapping').input_value() != file:
        page.locator('#bonded-fit-mapping').select_option(file)


def seed_pdc_run(dashboard, job_id, *, created):
    """A completed pdc run with one production stage, so the monitor has a run to open."""
    prod = dashboard.coordinator.RUNS / job_id / 'stages/06_assessment/prod'
    prod.mkdir(parents=True)
    (prod / 'run.xtc').write_bytes(b'raw')
    (prod / 'run.tpr').write_bytes(b'tpr')
    (prod / 'run.gro').write_text('gro')
    dashboard.coordinator.database().insert({'id': job_id, 'run_type': 'pdc', 'status': 'completed',
                                             'stage': 'complete', 'molecule_id': 'DDM', 'label': 'A pdc run',
                                             'created': created})


def open_compositions(page, base_url):
    """The Molecule Combination panel, mounted with the catalogue its form is built from.

    The form's controls are real only once that catalogue has arrived: until then the selects are empty and a click
    would post an empty fragment.
    """
    def ready(page):
        page.wait_for_function(
            "() => document.querySelector('#composition-molecule-name').value !== ''"
            " && document.querySelectorAll('#composition-head-molecule option').length > 1", timeout=30000)

    return open_panel(page, base_url, '/detergent-validation/combinations', tab='Combinations', ready=ready)


def serve_json(page, pattern, payload=None):
    """Answer requests matching `pattern` with JSON.

    `pattern` is whatever `page.route` takes -- a glob string (`'**/api/pdc/*/snapshots'`) or a compiled regex -- and it
    is passed through **unconverted**. Rewriting a glob into a regex is not a refactor: it changed which route answered
    in one file here, and the panel's tests caught it by going red in three places at once.

    `payload` is the body, or a callable taking the request when the answer depends on it.
    """
    page.route(pattern, lambda route: route.fulfill(json=payload(route.request) if callable(payload) else payload))


def serve_files(page, *pairs):
    """Answer several GETs at once: `serve_files(page, (pattern, body), (pattern, other))`.

    A panel on mount asks for the catalogue, then the mappings, then readiness; stating them in one call says "these are
    the answers this panel receives" in one place instead of three consecutive `page.route` lines per file.
    """
    for pattern, payload in pairs:
        serve_json(page, pattern, payload)


def serve_pdc_new_run(page, *, catalogue=None, models=None, readiness=None):
    """Answer the three reads the protein-detergent *New run* panel makes before it can be used.

    `catalogue` is the panel's own lists (detergents, proteins, defaults), `models` is its mapping picker, and
    `readiness` decides whether a run may start. The defaults are an empty catalogue, no models and a ready start; a
    case about a blocked start passes its own `readiness` and keeps the two payloads that made it blocked.
    """
    serve_files(
        page,
        (re.compile(r'/api/pdc/catalog'),
         {'templates': [], 'proteins': [], 'defaults': {}} if catalogue is None else catalogue),
        (re.compile(r'/api/pdc/models\?'), {'molecule': 'DDM', 'models': []} if models is None else models),
        (re.compile(r'/api/readiness\?'),
         {'ready': True, 'checks': [], 'blockers': []} if readiness is None else readiness),
    )


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


def assert_side_by_side(page, left_selector, right_selector):
    """Assert the two boxes do not overlap: the right one starts at or after the left one ends.

    Measured, not merely present: a stacked layout renders every control too, so presence would pass on the failure
    this exists to catch.
    """
    left = page.locator(left_selector).bounding_box()
    right = page.locator(right_selector).bounding_box()
    assert left and right, (left_selector, left, right_selector, right)
    assert right['x'] >= left['x'] + left['width'] - 1, (
        f'{right_selector} overlaps {left_selector}: they are not side by side: {left} {right}')


def assert_no_horizontal_scroll(page):
    """Assert the document does not widen past the viewport at the current width."""
    measured = page.evaluate(
        '() => ({content: document.documentElement.scrollWidth, viewport: innerWidth})')
    assert measured['content'] <= measured['viewport'], (
        f'the page scrolls sideways: {measured["content"]}px of content in a {measured["viewport"]}px viewport')


def wait_for_traces(page, selector, count=1, timeout=30000, *, ready=None):
    """Wait until the Plotly host at `selector` holds `count` traces, and return the host element.

    `ready` is an extra JS expression about the host (`el`), for a wait that also needs Plotly's layout or a trace's
    visibility: `'el._fullLayout'`, `'el.data[2].visible === false'`. The expression is about this host only, so it
    stays a fixed string at the call site instead of a page-wide function.
    """
    check = f'el && el.data && el.data.length === {int(count)}'
    if ready is not None:
        check = f'{check} && ({ready})'
    return page.wait_for_function(
        f"""selector => {{
          const el = document.querySelector(selector);
          return Boolean({check}) ? el : false;
        }}""", arg=selector, timeout=timeout)


def read_when(page, selector, expression, *, ready=bool, timeout=30000):
    """Read `expression` off the element at `selector` once `ready` accepts the value, and return that value.

    `expression` is a JS arrow taking the element and returns `null` while the panel has cleared it to rebuild;
    `ready` is a predicate over the value read (truthiness by default). `wait_for_function` does the polling -- a read
    that meets a cleared viewer waits rather than failing -- and a value `ready` rejects is read again until
    `timeout`, so the failure names the last value the viewer held.
    """
    deadline = time.monotonic() + timeout / 1000
    value = None
    while True:
        remaining = int((deadline - time.monotonic()) * 1000)
        if remaining <= 0:
            raise AssertionError(f'the viewer never held what this read needs: {expression.strip()[:70]};'
                                 f' it held {value!r}')
        try:
            page.wait_for_function(
                f"""selector => {{
                  const el = document.querySelector(selector);
                  return Boolean(el && ({expression})(el) !== null);
                }}""", arg=selector, timeout=remaining, polling=250)
        except PlaywrightTimeoutError:
            raise AssertionError(f'the viewer never held what this read needs: {expression.strip()[:70]};'
                                 f' it held {value!r}') from None
        value = page.locator(selector).evaluate(expression)
        if ready(value):
            return value
        page.wait_for_timeout(250)

