"""The run trajectory endpoint: segments a panel can play, rather than one trajectory a pdc run does not have.

The HTTP half of `analysis/runs/segments.py`. What matters here is the contract the panel reads: an ordered list, each
entry naming its own structure and trajectory, the merge group it belongs to, and the boundary where the system is
rebuilt -- plus artefacts served by the artifact route, so the client never builds a URL from a filesystem path.
"""
from __future__ import annotations

JOB_ID = '00000000beef'
GRO = 'system {count}\n{count:5d}\n    1DDM      S1A     1   0.100   0.200   0.300\n   8.00000   8.00000   8.00000\n'


def write(root, relative, text='', size=0):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text else 'x' * size)
    return path


def pdc_run(dashboard, *, job_id=JOB_ID, run_type='pdc'):
    root = dashboard.coordinator.RUNS / job_id
    write(root, '1_system/system.gro', GRO.format(count=8))
    write(root, '3_nvt/system.gro', GRO.format(count=40))
    write(root, '3_nvt/system.xtc', size=120)
    write(root, '4_npt/system.gro', GRO.format(count=40))
    write(root, '4_npt/system.xtc', size=140)
    write(root, '2_assessment/prod/run.gro', GRO.format(count=40))
    write(root, '2_assessment/prod/whole.xtc', size=160)
    write(root, '4_extension/prod/run.gro', GRO.format(count=32))
    write(root, '4_extension/prod/whole.xtc', size=180)
    write(root, '4_extension/prod/run.xtc', size=90)
    write(root, '5_assessment/prod/run.gro', GRO.format(count=32))
    write(root, '5_assessment/prod/run.xtc', size=90)
    dashboard.coordinator.database().insert({'id': job_id, 'run_type': run_type, 'status': 'completed',
                                             'stage': 'complete', 'molecule_id': 'DDM',
                                             'created': '2026-10-14T00:00:00+00:00'})
    return root


def test_a_pdc_run_answers_with_its_segments_in_order(dashboard):
    pdc_run(dashboard)

    response = dashboard.client.get(f'/api/jobs/{JOB_ID}/trajectory')

    assert response.status_code == 200, response.get_data(as_text=True)
    body = response.get_json()
    assert body['run_type'] == 'pdc' and body['why'] is None
    names = [entry['name'] for entry in body['segments']]
    assert names[:3] == ['System preparation', 'NVT equilibration', 'NPT equilibration'], names
    assert body['segments'][0]['trajectory'] is None, 'the dry build has a structure and no frames'


def test_each_entry_names_its_own_structure_and_trajectory_as_urls(dashboard):
    pdc_run(dashboard)

    body = dashboard.client.get(f'/api/jobs/{JOB_ID}/trajectory').get_json()
    nvt = next(entry for entry in body['segments'] if entry['name'] == 'NVT equilibration')

    assert nvt['structure_url'] == f'/api/jobs/{JOB_ID}/structure?path=3_nvt/system.gro'
    assert nvt['trajectory_url'] == f'/api/jobs/{JOB_ID}/artifacts/3_nvt/system.xtc'
    assert nvt['atoms'] == 40 and nvt['group'] is not None


def test_the_boundary_and_the_duplicate_are_both_in_the_answer(dashboard):
    """One thing the panel must not infer: where the system is rebuilt, and which leg repeats another's frames."""
    pdc_run(dashboard)

    body = dashboard.client.get(f'/api/jobs/{JOB_ID}/trajectory').get_json()

    assert body['boundaries'][0]['at'] == 'CG extension MD'
    assert body['boundaries'][0]['atoms_from'] == 40 and body['boundaries'][0]['atoms_to'] == 32
    final = next(entry for entry in body['segments'] if entry['name'] == 'Final assessment')
    assert final['duplicate_of'] == 'CG extension MD'


def test_a_run_with_nothing_to_play_is_a_200_with_a_reason(dashboard):
    root = dashboard.coordinator.RUNS / JOB_ID
    write(root, '07_reference/lig.gro', GRO.format(count=4))
    dashboard.coordinator.database().insert({'id': JOB_ID, 'run_type': 'aa_only', 'status': 'completed',
                                             'stage': 'complete', 'created': '2026-10-14T00:00:00+00:00'})

    response = dashboard.client.get(f'/api/jobs/{JOB_ID}/trajectory')

    assert response.status_code == 200
    body = response.get_json()
    assert body['segments'] == [] and 'no trajectory' in body['why']


def test_an_unknown_run_is_the_routes_own_404(dashboard):
    response = dashboard.client.get('/api/jobs/nosuchrun/trajectory')

    assert response.status_code == 404
