"""The Runs row's LINCS diagnostics: the warnings table, the selected bond/neighbour detail, and the frame dialog."""

from dashboard import files
from playwright.sync_api import expect

JOB_ID = '00000000c11c'
STAGE = 'stages/06_assessment'


def pdb():
    atoms = [('BB', 'LEU', 162, 0.0, 0.0, 0.0), ('BB', 'PHE', 163, 3.3, 0.0, 0.0),
             ('BB', 'GLU', 164, 6.6, 0.0, 0.0), ('SC1', 'GLU', 164, 6.6, 3.0, 0.0),
             ('BB', 'ASP', 165, 8.5, 0.0, 0.0), ('W', 'W', 1, 5.3, 3.0, 0.0)]
    return '\n'.join(f'ATOM  {serial:5d} {name:>4s} {residue:>3s} A{resid:4d}    '
                     f'{x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00'
                     for serial, (name, residue, resid, x, y, z) in enumerate(atoms, 1)) + '\n'


LOG = """Step 50, time 10.0 (ps)  LINCS WARNING
relative constraint deviation after LINCS:
rms 0.01, max 0.50 (between atoms 2 and 3)
bonds that rotated more than 30 degrees:
 atom 1 atom 2  angle  previous, current, constraint length
    1    2   42.0    0.33    0.40       0.33
    2    3   70.0    0.33    0.50       0.33
Wrote pdb files with previous and current coordinates

Fatal error:
Too many LINCS warnings (1556)
"""


def lincs_run(dashboard):
    root = dashboard.coordinator.RUNS / JOB_ID
    stage = root / STAGE
    stage.mkdir(parents=True)
    (root / 'logs').mkdir(parents=True)
    (root / 'logs' / '06_assessment.log').write_text(LOG)
    (stage / 'step50b.pdb').write_text(pdb())
    (stage / 'step50c.pdb').write_text(pdb())
    files.atomic_json(root / 'manifest.json', {'stages': [{
        'name': 'CG assessment MD', 'status': 'failed',
        'log': str(root / 'logs' / '06_assessment.log'), 'cwd': str(stage),
    }]})
    dashboard.coordinator.database().insert({'id': JOB_ID, 'run_type': 'pdc', 'status': 'failed',
                                             'stage': 'CG assessment MD', 'molecule_id': 'DM',
                                             'created': '2026-11-19T00:00:00+00:00'})


def test_a_failed_run_shows_its_lincs_warning_and_opens_the_written_frame(dashboard, live_page):
    lincs_run(dashboard)
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/runs')
    row = page.locator(f'.job[data-id="{JOB_ID}"]')
    expect(row).to_be_visible()
    row.locator('.job-diagnostics summary').click()

    expect(row.locator('.run-lincs')).to_be_visible()
    expect(row.locator('.lincs-count')).to_have_text('· 1 LINCS')
    expect(row.locator('.lincs-warnings')).to_contain_text('50')
    expect(row.locator('.lincs-warnings')).to_contain_text('0.5')
    expect(row.locator('.run-lincs-detail')).to_contain_text('The constrained bonds')
    expect(row.locator('.run-lincs-detail')).to_contain_text('PHE 163 BB')
    expect(row.locator('.run-lincs-detail')).to_contain_text('0.190 nm · short')
    expect(row.locator('.run-lincs-verdict')).to_contain_text('1,556')
    # Six data rows fit without a scrollbar; the seventh makes the wrapper scroll. The one-warning table does not.
    capped = row.locator('.run-lincs-detail .lincs-scroll.has-more')
    assert capped.count() == 1, capped.count()
    assert capped.first.evaluate('el => el.scrollHeight > el.clientHeight + 1'), \
        'the neighbour table should scroll inside the six-row window'
    warnings_wrap = row.locator('.run-lincs .lincs-scroll').first
    assert 'has-more' not in (warnings_wrap.get_attribute('class') or ''), 'one row must not scroll'

    row.get_by_role('button', name='Show initial frame').click()
    dialog = page.locator('#lincs-frame-dialog')
    expect(dialog).to_be_visible()
    expect(page.locator('#lincs-frame-title')).to_contain_text('Step 50')
    expect(page.locator('#lincs-frame-caption')).to_contain_text('step50b.pdb')
    expect(page.locator('#lincs-frame-viewer canvas')).to_be_visible(timeout=30000)
    page.get_by_role('button', name='Close').click()
    expect(dialog).not_to_be_visible()
    assert errors == [], errors
