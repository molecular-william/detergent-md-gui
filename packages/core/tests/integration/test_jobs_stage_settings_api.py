"""The stage settings the run records carry over HTTP: groups on the detail, segments on both.

The Runs card segments an AA bar before its row is expanded, so the segments are part of the list payload; the
groups are the detail's, read when the Stage settings tab is opened. A run of any other type keeps the single
bar, which is the same null the shared module answers.
"""
import json

import pytest

JOBS = '/api/jobs'

AA_SETTINGS = {
    'aa_minimization_steps': 20000, 'aa_minimization_emtol': 1000, 'aa_minimization_emstep': 0.01,
    'aa_nvt_ps': 100, 'aa_nvt_dt_fs': 2,
    'aa_npt_ps': 1000, 'aa_npt_dt_fs': 2,
    'aa_production_ps': 10000, 'aa_production_dt_fs': 2,
    'temperature_k': 303.15, 'mdrun_gpu': 0,
}
AA_PLAN = [['AA solvation', '01_solvation/run.sh'], ['AA neutralization', '02_ions/run.sh'],
           ['AA minimization', '03_minimization/run.sh'], ['AA NVT equilibration', '04_nvt/run.sh'],
           ['AA NPT equilibration', '05_npt/run.sh'], ['AA NPT production', '06_production/run.sh'],
           ['AA reference publication', '07_reference/run.sh']]


def _run(owner, run_id, run_type, settings):
    """One completed run record with the manifest of the run it names, in the fixture's own runs directory."""
    run_dir = owner.RUNS / run_id
    run_dir.mkdir(parents=True)
    manifest = {'id': run_id, 'run_type': run_type, 'status': 'completed', 'stage': 'complete',
                'stages': [], 'settings': settings, 'stage_plan': AA_PLAN}
    (run_dir / 'manifest.json').write_text(json.dumps(manifest))
    job = {'id': run_id, 'label': 'run', 'detergent': 'DDM', 'method': 'gromacs', 'status': 'completed',
           'stage': 'complete', 'created': owner.now(), 'profile': 'standard', 'layout_version': 2,
           'run_type': run_type, 'settings': settings}
    owner.database().insert(job)
    return job


def test_a_run_detail_carries_the_groups_and_the_segments(dashboard):
    owner = dashboard.coordinator
    job = _run(owner, 'aaa000000010', 'aa_only', AA_SETTINGS)

    with dashboard.client as client:
        body = client.get(f'{JOBS}/{job["id"]}').get_json()

    settings = body['stage_settings']
    assert [group['label'] for group in settings['groups']] == \
           ['Energy minimization', 'NVT equilibration', 'NPT equilibration', 'NPT production', 'Run settings']
    assert [field['key'] for field in settings['groups'][0]['fields']] == \
           ['aa_minimization_steps', 'aa_minimization_emtol', 'aa_minimization_emstep']
    assert [segment['stage'] for segment in body['stage_segments']] == \
           ['AA minimization', 'AA NVT equilibration', 'AA NPT equilibration', 'AA NPT production']
    assert body['stage_segments'] == settings['segments']
    assert settings['total_steps'] == 5570000


def test_the_list_carries_the_segments_and_not_the_groups(dashboard):
    owner = dashboard.coordinator
    job = _run(owner, 'aaa000000011', 'aa_only', AA_SETTINGS)

    with dashboard.client as client:
        summary = client.get(JOBS).get_json()['jobs'][0]
        full = client.get(JOBS + '?view=full').get_json()['jobs'][0]

    assert [segment['kind'] for segment in summary['stage_segments']] == ['min', 'nvt', 'npt', 'production']
    assert sum(segment['fraction'] for segment in summary['stage_segments']) == pytest.approx(1)
    assert 'stage_settings' not in summary, 'the list does not carry the groups'
    assert full['stage_settings']['groups'], 'a full record does'
    assert job['id'] == summary['id']


def test_a_run_of_another_type_keeps_the_single_bar(dashboard):
    owner = dashboard.coordinator
    job = _run(owner, 'bbb000000012', 'cg', {'cg_equil_ps': 10, 'cg_production_ps': 200, 'mdrun_gpu': 0})

    with dashboard.client as client:
        body = client.get(f'{JOBS}/{job["id"]}').get_json()

    assert body['stage_segments'] is None
    assert body['stage_settings']['segments'] is None and body['stage_settings']['total_steps'] is None
    assert [group['label'] for group in body['stage_settings']['groups']] == \
           ['CG equilibration', 'CG production', 'Run settings']
