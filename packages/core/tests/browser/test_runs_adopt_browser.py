"""The Runs banner registers run directories copied in without a job row.

A run is a directory and a row; a directory copied in by hand has only the first, so the table cannot list it.
`GET /api/runs/unregistered` finds those directories and `POST /api/runs/adopt` rebuilds the row from the manifest.
These tests drive that through the panel: the banner appears, its dialog lists the copies with the AA source first,
and the table gains the adopted rows.
"""
import json

from dashboard import files
from playwright.sync_api import expect

RUN = 'a1b2c3d4e5f6'
CONSUMER = 'cccccccccccc'


def paste(dashboard, run_id=RUN, *, run_type='aa_only', **extra):
    """A finished run directory in the test's workspace and no job row."""
    run = dashboard.coordinator.RUNS / run_id
    (run / 'inputs').mkdir(parents=True)
    document = {'inputs': []}
    (run / 'inputs' / 'inputs.json').write_text(json.dumps(document))
    manifest = {'id': run_id, 'run_type': run_type, 'status': 'completed', 'layout_version': 2,
                'molecule_id': 'Fixture', 'stage_plan': ['AA solvation'], 'stages': [],
                'inputs': [], 'input_snapshot_sha256': files.json_sha256(document)}
    manifest.update(extra)
    files.atomic_json(run / 'manifest.json', manifest)
    return run


def test_the_banner_registers_a_copied_aa_run_before_its_cg_consumer(dashboard, live_page):
    paste(dashboard, RUN)
    paste(dashboard, CONSUMER, run_type='cg', reference_run_id=RUN)
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/runs')

    expect(page.locator('#adopt-runs-banner')).to_be_visible()
    expect(page.locator('#adopt-runs-summary')).to_contain_text('2 run directories')
    page.locator('#adopt-runs').click()
    expect(page.locator('#adopt-runs-dialog')).to_be_visible()
    identities = page.locator('#adopt-runs-list .adopt-id')
    expect(identities).to_have_count(2)
    # The AA source is listed first so one click can register a cg run and the source it consumes.
    expect(identities.first).to_have_text(RUN)

    page.locator('#adopt-runs-confirm').click()
    expect(page.locator('#adopt-runs-banner')).to_be_hidden(timeout=30000)
    expect(page.locator(f'.job[data-id="{RUN}"]')).to_have_count(1)
    expect(page.locator(f'.job[data-id="{CONSUMER}"]')).to_have_count(1)
    expect(page.locator('#notice')).to_contain_text('Registered 2 runs')
    assert errors == [], errors


def test_a_cg_copy_without_its_aa_source_is_named_in_the_dialog(dashboard, live_page):
    paste(dashboard, CONSUMER, run_type='cg', reference_run_id='dddddddddddd')
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/runs')

    page.locator('#adopt-runs').click()
    page.locator('#adopt-runs-confirm').click()

    expect(page.locator('#adopt-runs-dialog')).to_be_visible()
    expect(page.locator('#adopt-runs-status')).to_contain_text('Registered 0 of 1')
    expect(page.locator('#adopt-runs-list .adopt-sub.failed')).to_contain_text('dddddddddddd')
    expect(page.locator('#adopt-runs-banner')).to_be_visible()
    assert errors == [], errors
