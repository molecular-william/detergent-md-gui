"""The Run view's Whole trajectory card: offered for a pdc run and posting the chosen numbers.

The rebuild itself is pinned in the unit and integration files; this is the panel's half -- the card renders under
the Trajectory block, Compact is prefilled, and Recompute posts exactly what the reader sees.
"""
from __future__ import annotations

import re

from playwright.sync_api import expect

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


def seed_run(dashboard):
    prod = dashboard.coordinator.RUNS / JOB / 'stages/06_assessment/prod'
    prod.mkdir(parents=True)
    (prod / 'run.xtc').write_bytes(b'raw')
    (prod / 'run.tpr').write_bytes(b'tpr')
    (prod / 'run.gro').write_text('gro')
    dashboard.coordinator.database().insert({'id': JOB, 'run_type': 'pdc', 'status': 'completed',
                                             'stage': 'complete', 'molecule_id': 'DDM', 'label': 'A pdc run',
                                             'created': '2026-11-05T00:00:00+00:00'})


def test_the_whole_trajectory_card_is_offered_compact_and_posts_its_numbers(dashboard, live_page):
    seed_run(dashboard)
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
