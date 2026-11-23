"""The LINCS warnings endpoint: the stage log, the frame GROMACS wrote, and the neighbourhood it names."""
from __future__ import annotations

from dashboard import files

JOB_ID = '00000000c11c'
STAGE = 'stages/06_assessment'


def pdb():
    atoms = [('BB', 'LEU', 162, 0.0, 0.0, 0.0), ('BB', 'PHE', 163, 3.3, 0.0, 0.0),
             ('BB', 'GLU', 164, 6.6, 0.0, 0.0), ('SC1', 'GLU', 164, 6.6, 3.0, 0.0),
             ('BB', 'ASP', 165, 8.5, 0.0, 0.0), ('W', 'W', 1, 5.3, 3.0, 0.0)]
    lines = []
    for serial, (name, residue, resid, x, y, z) in enumerate(atoms, 1):
        lines.append(f'ATOM  {serial:5d} {name:>4s} {residue:>3s} A{resid:4d}    '
                     f'{x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00')
    return '\n'.join(lines) + '\n'


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


def lincs_run(dashboard, *, log=LOG):
    root = dashboard.coordinator.RUNS / JOB_ID
    stage = root / STAGE
    stage.mkdir(parents=True)
    (root / 'logs').mkdir(parents=True)
    (root / 'logs' / '06_assessment.log').write_text(log)
    (stage / 'step50b.pdb').write_text(pdb())
    (stage / 'step50c.pdb').write_text(pdb())
    files.atomic_json(root / 'manifest.json', {'stages': [{
        'name': 'CG assessment MD', 'status': 'failed',
        'log': str(root / 'logs' / '06_assessment.log'), 'cwd': str(stage),
    }]})
    dashboard.coordinator.database().insert({'id': JOB_ID, 'run_type': 'pdc', 'status': 'failed',
                                             'stage': 'CG assessment MD', 'molecule_id': 'DM',
                                             'created': '2026-11-19T00:00:00+00:00'})
    return root


def test_the_route_maps_the_warning_to_the_written_frame_and_its_neighbours(dashboard):
    lincs_run(dashboard)

    response = dashboard.client.get(f'/api/jobs/{JOB_ID}/lincs-warnings')

    assert response.status_code == 200, response.get_data(as_text=True)
    body = response.get_json()
    assert body['status'] == 'failed' and body['fatal_warnings'] == 1556
    assert body['selected'] == 0 and len(body['warnings']) == 1
    warning = body['warnings'][0]
    assert warning['step'] == 50 and warning['atoms'] == [2, 3]
    assert [bond['current_nm'] for bond in warning['bonds']] == [0.4, 0.5]
    assert warning['identities']['2']['residue'] == 'PHE'
    assert warning['identities']['5']['residue'] == 'ASP'
    short = [row for row in warning['neighbours'] if row['short']]
    assert short and short[0]['other'] == 5 and short[0]['distance_nm'] == 0.19
    assert set(warning['frames']) == {'initial', 'constrained'}
    assert warning['frames']['initial']['url'].endswith('/step50b.pdb?inline=1')

    frame = dashboard.client.get(warning['frames']['initial']['url'])
    assert frame.status_code == 200
    assert frame.get_data(as_text=True).startswith('ATOM')


def test_a_run_with_no_warning_answers_empty_rather_than_refusing(dashboard):
    lincs_run(dashboard, log='Step 10, time 1.0 (ps)\nall good\n')

    body = dashboard.client.get(f'/api/jobs/{JOB_ID}/lincs-warnings').get_json()

    assert body['warnings'] == [] and body['selected'] is None and body['fatal_warnings'] is None


def test_a_stage_path_outside_the_run_is_not_read(dashboard):
    root = lincs_run(dashboard)
    outside = root.parent / 'outside.log'
    outside.write_text(LOG)
    files.atomic_json(root / 'manifest.json', {'stages': [{
        'name': 'CG assessment MD', 'status': 'failed', 'log': str(outside), 'cwd': str(root / STAGE),
    }]})

    body = dashboard.client.get(f'/api/jobs/{JOB_ID}/lincs-warnings').get_json()

    assert body['warnings'] == [], 'a record must not let the diagnostic read outside its run'


def test_the_default_is_the_last_warning_that_wrote_a_frame(dashboard):
    """A later warning with no coordinates does not become the first thing a reader sees."""
    root = lincs_run(dashboard)
    log = root / 'logs' / '06_assessment.log'
    log.write_text(log.read_text() + """
Step 60, time 12.0 (ps)  LINCS WARNING
relative constraint deviation after LINCS:
rms 0.2, max 3.0 (between atoms 1 and 2)
bonds that rotated more than 30 degrees:
 atom 1 atom 2  angle  previous, current, constraint length
    1    2   60.0    0.33    0.40       0.33
""")

    body = dashboard.client.get(f'/api/jobs/{JOB_ID}/lincs-warnings').get_json()

    assert [warning['step'] for warning in body['warnings']] == [50, 60]
    assert body['selected'] == 0, 'the warning with coordinates is the default'
    assert body['warnings'][1]['frames'] == {}
    assert body['warnings'][1]['neighbours'] == []
    assert body['warnings'][1]['bonds'], 'its bond table is still exact'
