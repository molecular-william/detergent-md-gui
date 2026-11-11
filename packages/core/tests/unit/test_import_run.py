"""Porting a run: the directory and its job row move together or not at all.

`import_run` is the transfer when the sender's workspace is at hand; `adoption` is the other half — a directory
copied in by hand, whose row is rebuilt from the manifest it carries. Both keep the same rule: nothing is listed
until the copy is verified against the receiving checkout.
"""
import json

import pytest
from dashboard import files, paths
from dashboard.cli import import_run
from dashboard.execution import adoption
from dashboard.execution.coordination import errors
from dashboard.store import Store


def make_workspace(root, run_id='a1b2c3d4e5f6'):
    workspace = root / 'workspace'
    run = workspace / 'runs' / run_id
    (run / 'inputs').mkdir(parents=True)
    document = {'inputs': []}
    (run / 'inputs' / 'inputs.json').write_text(json.dumps(document))
    manifest = {'run_type': 'aa_only', 'inputs': [], 'input_snapshot_sha256': files.json_sha256(document),
                'stages': []}
    (run / 'manifest.json').write_text(json.dumps(manifest))
    Store(workspace / 'jobs.sqlite3').insert({'id': run_id, 'status': 'completed', 'run_type': 'aa_only',
                                              'created': '2026-10-29T00:00:00+00:00'})
    return workspace


def test_a_dry_run_reports_without_copying(tmp_path):
    source = make_workspace(tmp_path / 'source')
    target = tmp_path / 'target'
    report = import_run.import_run(source, target, 'a1b2c3d4e5f6')
    assert report['applied'] is False
    assert not (target / 'runs' / 'a1b2c3d4e5f6').exists()


def test_applied_it_copies_the_directory_and_the_row(tmp_path):
    source = make_workspace(tmp_path / 'source')
    target = tmp_path / 'target'
    report = import_run.import_run(source, target, 'a1b2c3d4e5f6', apply=True)
    assert report['applied'] is True
    assert (target / 'runs' / 'a1b2c3d4e5f6' / 'manifest.json').is_file()
    assert Store(target / 'jobs.sqlite3').get('a1b2c3d4e5f6')['status'] == 'completed'


def test_a_second_import_is_refused(tmp_path):
    source = make_workspace(tmp_path / 'source')
    target = tmp_path / 'target'
    import_run.import_run(source, target, 'a1b2c3d4e5f6', apply=True)
    with pytest.raises(ValueError, match='already in'):
        import_run.import_run(source, target, 'a1b2c3d4e5f6', apply=False)


def test_an_unknown_run_is_refused(tmp_path):
    source = make_workspace(tmp_path / 'source')
    with pytest.raises(ValueError, match='no run nope'):
        import_run.import_run(source, tmp_path / 'target', 'nope')


# --- adoption: a directory copied in by hand, with no row to import ------------------------------------------------


def pasted_workspace(root, run_id='a1b2c3d4e5f6', *, status='completed', run_type='aa_only', **manifest_extra):
    """A workspace holding a run directory and its manifest, and no job row."""
    workspace = root / 'workspace'
    run = workspace / 'runs' / run_id
    (run / 'inputs').mkdir(parents=True)
    document = {'inputs': []}
    (run / 'inputs' / 'inputs.json').write_text(json.dumps(document))
    manifest = {'id': run_id, 'run_type': run_type, 'status': status, 'layout_version': 2,
                'molecule_id': 'Fixture', 'stage_plan': ['AA solvation'], 'stages': [],
                'inputs': [], 'input_snapshot_sha256': files.json_sha256(document)}
    manifest.update(manifest_extra)
    (run / 'manifest.json').write_text(json.dumps(manifest))
    return workspace


def test_a_pasted_directory_is_listed_adopted_and_then_refused(tmp_path):
    workspace = pasted_workspace(tmp_path)
    selected = paths.Paths(workspace=workspace)

    assert [run['id'] for run in adoption.unregistered(selected)] == ['a1b2c3d4e5f6']
    report = adoption.adopt(selected, 'a1b2c3d4e5f6')
    assert report['applied'] is False and report['status'] == 'completed'
    assert Store(workspace / 'jobs.sqlite3').get('a1b2c3d4e5f6') is None, 'a dry run writes nothing'

    report = adoption.adopt(selected, 'a1b2c3d4e5f6', apply=True)
    assert report['applied'] is True
    job = Store(workspace / 'jobs.sqlite3').get('a1b2c3d4e5f6')
    assert job['run_type'] == 'aa_only' and job['adopted_at'], job
    assert adoption.unregistered(selected) == []
    with pytest.raises(errors.RunConflict, match='already registered'):
        adoption.adopt(selected, 'a1b2c3d4e5f6')


def test_a_run_still_marked_running_is_not_adopted(tmp_path):
    selected = paths.Paths(workspace=pasted_workspace(tmp_path, status='running'))
    with pytest.raises(ValueError, match='only a stopped run'):
        adoption.build(selected, 'a1b2c3d4e5f6')


def test_adoption_rebuilds_the_analysis_attempts(tmp_path):
    workspace = pasted_workspace(tmp_path)
    run = workspace / 'runs' / 'a1b2c3d4e5f6'
    for attempt, status in (('aaaa', 'completed'), ('bbbb', 'running')):
        directory = run / 'analyses' / 'overlap' / 'signature' / attempt
        directory.mkdir(parents=True)
        (directory / 'manifest.json').write_text(json.dumps(
            {'id': attempt, 'kind': 'overlap', 'status': status,
             'directory': f'analyses/overlap/signature/{attempt}', 'created_at': f'2026-11-0{attempt == "bbbb" and 2 or 1}'}))

    job, _ = adoption.build(paths.Paths(workspace=workspace), 'a1b2c3d4e5f6')
    by_id = {task['id']: task for task in job['analyses']}
    assert by_id['aaaa']['status'] == 'completed'
    assert by_id['bbbb']['status'] == 'failed' and 'restarted' in by_id['bbbb']['error']


def test_a_cg_run_needs_its_aa_source_adopted_first(tmp_path):
    run_id = 'cccccccccccc'
    selected = paths.Paths(workspace=pasted_workspace(tmp_path, run_id, run_type='cg',
                                                      reference_run_id='dddddddddddd'))
    with pytest.raises(errors.SourceUnavailable, match='dddddddddddd'):
        adoption.build(selected, run_id)


def test_an_aa_run_is_offered_when_its_sources_are_not_on_this_host(tmp_path):
    """Adoption records the reference eligibility and the provenance warnings the picker will state."""
    workspace = pasted_workspace(tmp_path)
    run = workspace / 'runs' / 'a1b2c3d4e5f6'
    (run / 'stages/07_reference').mkdir(parents=True)
    (run / 'stages/07_reference/reference.json').write_text(json.dumps(
        {'schema_version': 1, 'reference_eligible': True, 'sha256': {},
         'referenced_sources': [{'role': 'molecule', 'kind': 'file', 'label': 'molecule.itp',
                                 'path': '/nonexistent/other-checkout/molecules/Fixture/molecule.itp',
                                 'sha256': '0' * 64}]}))
    report = adoption.adopt(paths.Paths(workspace=workspace), 'a1b2c3d4e5f6', apply=True)
    assert report['reference_eligible'] is True
    assert report['warnings'] and 'not present on this host' in report['warnings'][0]['reason']
