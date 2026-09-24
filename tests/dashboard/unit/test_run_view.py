"""The run view: what the browser is shown about a run, built from plain inputs.

Deciding which fields a run presents, where its logs are, and what its ETA says is a
view concern. It lives in one module that takes a job record, the run's directory, its
manifest and the ownership flags as arguments -- so it can be tested without a Flask
app, and so a request cannot be aborted from inside it.
"""
import json
from pathlib import Path

from dashboard.web import views

RUN_ID = 'a' * 12


def job(**overrides):
    record = {'id': RUN_ID, 'status': 'completed', 'created': '2026-09-24T00:00:00+00:00',
              'edited': None, 'run_type': 'aa_only', 'stage': 'complete'}
    record.update(overrides)
    return record


def test_run_view_builds_without_flask(tmp_path):
    view = views.run_view(job(), run_dir=tmp_path, manifest={'stages': [], 'stage_plan': ['AA solvation']},
                          ownership={'can_delete': True}, summary=True)
    assert view['id'] == RUN_ID
    assert view['stages'] == []
    assert view['workflow_stages'] == ['AA solvation']
    assert view['elapsed_seconds'] is None


def test_an_unusable_run_id_is_reported_in_the_view_not_raised():
    """A view built from a record that cannot address a directory says so.

    The coordinator used to abort(404) from inside the same method that builds the
    view; a pure view has nothing to abort, so it reports the record as unrepairable.
    """
    view = views.run_view({'id': 'not-a-run-id', 'status': 'completed'}, run_dir=None)
    assert view['status'] == 'failed'
    assert 'Invalid persisted run ID' in view['error']
    assert (view['can_cancel'], view['can_retry'], view['can_delete']) == (False, False, False)
    assert view['stages'] == [] and view['elapsed_seconds'] is None and view['analyses'] == []


def test_the_summary_shape_hides_the_heavy_fields(tmp_path):
    stages = [{'name': 'AA solvation', 'status': 'complete', 'started_at': 'T0', 'ended_at': 'T1',
               'command': ['gmx', 'solvate'], 'log': str(tmp_path / 'logs/x.log')}]
    record = job(pid=4242, gromacs_eta='soon', internal_note='kept in the full view')
    manifest = {'stages': stages, 'stage_plan': ['AA solvation']}
    full = views.run_view(record, run_dir=tmp_path, manifest=manifest)
    # The full view is the record minus the hidden fields; summary is an allowlist.
    assert 'pid' not in full and 'gromacs_eta' not in full
    assert full['internal_note'] == 'kept in the full view'
    assert full['stages'][0]['command'] == ['gmx', 'solvate']
    assert 'detail_revision' not in full
    summary = views.run_view(record, run_dir=tmp_path, manifest=manifest, summary=True)
    assert set(summary['stages'][0]) == {'name', 'status', 'started_at', 'ended_at'}
    assert 'internal_note' not in summary
    assert summary['detail_revision']


def test_elapsed_time_comes_from_the_recorded_timestamps(tmp_path):
    record = job(status='running', started_at='2026-09-24T00:00:00+00:00', ended_at='2026-09-24T00:10:00+00:00')
    view = views.run_view(record, run_dir=tmp_path, manifest={'stages': []})
    assert view['elapsed_seconds'] == 600
    assert view['metadata_warnings'] == []
    broken = views.run_view(job(started_at='yesterday'), run_dir=tmp_path, manifest={'stages': []})
    assert broken['elapsed_seconds'] is None
    assert any('timestamp' in warning for warning in broken['metadata_warnings'])


def test_the_eta_comes_from_the_running_stage_log(tmp_path):
    log = tmp_path / 'logs' / '01_solvation.log'
    log.parent.mkdir(parents=True)
    log.write_text('starting mdrun\nwill finish Thu Sep 24 12:00:00 2026\n')
    record = job(status='running', stage_plan=['AA solvation'])
    stages = [{'name': 'AA solvation', 'status': 'running', 'log': str(log)}]
    view = views.run_view(record, run_dir=tmp_path,
                          manifest={'stages': stages, 'stage_plan': ['AA solvation']})
    assert view['gromacs_eta'] == 'Thu Sep 24 12:00:00 2026'
    assert view['eta_source'] == 'GROMACS console output'


def test_a_resumed_attempt_does_not_read_the_previous_attempts_console_log(tmp_path):
    """The same contract the log resolver pins, at the level the browser sees it."""
    logs = tmp_path / 'logs'
    logs.mkdir()
    (logs / 'console.log').write_text('starting mdrun\nwill finish OLD ATTEMPT\n')
    record = job(status='running', resume_in_place=True, resume_count=1, stage_plan=['AA solvation'])
    stages = [{'name': 'AA solvation', 'status': 'running',
               'log': str(logs / 'resume-0001' / '01_solvation.log')}]
    manifest = {'stages': stages, 'stage_plan': ['AA solvation']}
    assert 'gromacs_eta' not in views.run_view(record, run_dir=tmp_path, manifest=manifest,
                                               console_log=logs / 'console.log')
    current = logs / 'resume-0001' / '01_solvation.log'
    current.parent.mkdir(parents=True)
    current.write_text('starting mdrun\nwill finish CURRENT ATTEMPT\n')
    view = views.run_view(record, run_dir=tmp_path, manifest=manifest, console_log=logs / 'console.log')
    assert view['gromacs_eta'] == 'CURRENT ATTEMPT'


def test_analyses_are_summarised_and_a_running_one_reports_its_phase(tmp_path):
    directory = tmp_path / 'analyses/abc'
    directory.mkdir(parents=True)
    (directory / 'progress.json').write_text(json.dumps({'phase': 'parsing trajectory'}))
    record = job(analyses=[{'id': 'abc', 'kind': 'sasa', 'status': 'running', 'directory': 'analyses/abc',
                            'outputs': [{'name': 'heavy'}], 'created_at': 'T0'}])
    full = views.run_view(record, run_dir=tmp_path, manifest={'stages': []})
    assert full['analyses'][0]['outputs'] == [{'name': 'heavy'}]
    assert full['analyses'][0]['progress'] == 'parsing trajectory'
    summary = views.run_view(record, run_dir=tmp_path, manifest={'stages': []}, summary=True)
    assert 'outputs' not in summary['analyses'][0]
    assert summary['analyses'][0]['progress'] == 'parsing trajectory'


def test_an_unreadable_manifest_is_reported_and_still_yields_a_view(tmp_path):
    (tmp_path / 'manifest.json').write_text('{not json')
    view = views.run_view(job(), run_dir=tmp_path, manifest={})
    assert view['stages'] == []
    assert any('unreadable' in warning for warning in view['metadata_warnings'])


def test_an_external_worker_blocks_reuse_and_deletion(tmp_path):
    record = job(status='completed')
    view = views.run_view(record, run_dir=tmp_path, manifest={'stages': []},
                          ownership={'can_delete': True, 'can_cancel': False, 'can_retry': False}, busy=True)
    assert view['can_delete'] is False
    assert view['resume_stages'] == []
    assert any('external worker' in warning for warning in view['metadata_warnings'])


def test_the_detail_revision_follows_the_manifest(tmp_path):
    record = job()
    first = views.run_view(record, run_dir=tmp_path, manifest={'stages': [], 'stage_plan': ['AA solvation']}, summary=True)
    second = views.run_view(record, run_dir=tmp_path, manifest={'stages': [], 'stage_plan': ['CG simulation']}, summary=True)
    assert first['detail_revision'] != second['detail_revision']


def test_the_eta_parser_ignores_estimates_before_the_latest_mdrun(tmp_path):
    text = 'will finish STALE\nstarting mdrun\nremaining wall clock time: 42.5 s\n'
    assert views.parse_gromacs_eta(text) == {'eta_source': 'GROMACS console output',
                                             'gromacs_remaining_seconds': 42.5}
    assert views.parse_gromacs_eta('nothing to see') == {}


def test_tail_returns_the_end_of_a_log_and_nothing_for_a_missing_one(tmp_path):
    log = tmp_path / 'x.log'
    log.write_text('a' * 100 + 'END')
    assert views.tail(log, limit=3) == 'END'
    assert views.tail(tmp_path / 'absent.log') == ''
