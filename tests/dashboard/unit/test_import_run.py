"""Porting a run: the directory and its job row move together or not at all."""
import json

import pytest
from dashboard import files
from dashboard.cli import import_run
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
