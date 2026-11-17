"""The Run view's Whole trajectory card: offered for a pdc run and posting the chosen numbers.

The rebuild itself is pinned in the unit and integration files; this is the panel's half -- the card renders under
the Trajectory block, Compact is prefilled, and Recompute posts exactly what the reader sees.
"""
from __future__ import annotations

import re
import time

from playwright.sync_api import expect

from tests.harness import browser

JOB = '0000000000ac'
RUN_VIEW = f'/protein-detergent/run-view?run={JOB}'

ANSWER = {
    'defaults': {'dt_ps': 100, 'decimals': 2},
    'decimals': [1, 2, 3],
    'stage': 'assessment',
    'raw': {'bytes': 2 * 1024 ** 3, 'frames': 50000, 'cadence_ps': 20, 'path': 'stages/06_assessment/prod/run.xtc'},
    'whole': {'bytes': 2 * 1024 ** 3, 'frames': 50000, 'cadence_ps': 20, 'path': 'stages/06_assessment/prod/whole.xtc'},
    'sidecar': None,
    'state': {},
    'error': None,
}


def test_the_whole_trajectory_card_is_offered_compact_and_posts_its_numbers(dashboard, live_page):
    browser.seed_pdc_run(dashboard, JOB, created='2026-11-05T00:00:00+00:00')
    page, errors = live_page
    posted = []
    page.route(re.compile(rf'/api/pdc/{JOB}/whole-trajectory$'),
               lambda route: route.fulfill(json=ANSWER) if route.request.method == 'GET'
               else (posted.append(route.request.post_data_json), route.fulfill(status=202, json={'state': {'status': 'running'}}))[1])
    page.goto(f'{live_page.base_url}{RUN_VIEW}', wait_until='load')

    card = page.locator('.whole-trajectory')
    expect(card).to_be_visible(timeout=30000)
    expect(card.locator('.summary-meta')).to_contain_text('2.0 GB')
    assert card.locator('.whole-dt').input_value() == '100'
    assert card.locator('.whole-decimals').input_value() == '2'
    # 2 GiB at 20 ps, rebuilt at 100 ps and 2 decimals: 2 GiB * (20/100) * 0.76 = about 0.3 GiB, 6.6x smaller.
    expect(card.locator('.estimate')).to_contain_text('6.6×')
    expect(card.locator('.estimate')).to_contain_text('smaller')

    card.locator('.whole-recompute').click()
    page.wait_for_function('() => true')
    expect(card.locator('.whole-recompute')).to_have_text('Recomputing…', timeout=10000)

    assert posted and posted[0] == {'dt_ps': 100, 'decimals': 2}, posted
    assert errors == [], errors


def test_the_whole_trajectory_poll_stops_with_the_run_view_panel_and_resumes_with_it(dashboard, live_page):
    """The 2 s poll is gated on the Run view panel, not only on page visibility, and resumes when the panel returns.

    Counted from the route: a card behind another tab asks nothing while its rebuild runs, and showing the panel
    again arms the next poll. The terminal-state stop rule is the card's own and is untouched -- every answer here
    says `running`, so every poll re-arms until the panel hides.
    """
    browser.seed_pdc_run(dashboard, JOB, created='2026-11-05T00:00:00+00:00')
    page, errors = live_page
    reads = []
    page.route(re.compile(rf'/api/pdc/{JOB}/whole-trajectory$'),
               lambda route: (reads.append(route.request.url),
                              route.fulfill(json={**ANSWER, 'state': {'status': 'running'}}))[-1])
    page.goto(f'{live_page.base_url}{RUN_VIEW}', wait_until='load')

    card = page.locator('.whole-trajectory')
    expect(card).to_be_visible(timeout=30000)
    deadline = time.monotonic() + 10
    while len(reads) < 2 and time.monotonic() < deadline:
        page.wait_for_timeout(100)
    assert len(reads) >= 2, f'the card never polled a running rebuild: {len(reads)}'

    page.evaluate("""() => {
      document.querySelector('#runview').hidden = true;
      document.dispatchEvent(new CustomEvent('dashboard:tab', {detail: {id: 'runs'}}));
    }""")
    page.wait_for_timeout(2600)          # one cadence plus the poll already armed
    settled = len(reads)
    page.wait_for_timeout(2600)
    assert len(reads) == settled, f'the card polled {len(reads) - settled} times with the Run view hidden'

    page.evaluate("""() => {
      document.querySelector('#runview').hidden = false;
      document.dispatchEvent(new CustomEvent('dashboard:tab', {detail: {id: 'runview'}}));
    }""")
    deadline = time.monotonic() + 5
    while len(reads) == settled and time.monotonic() < deadline:
        page.wait_for_timeout(100)
    assert len(reads) > settled, 'the card did not resume when the Run view came back'
    assert errors == [], errors
