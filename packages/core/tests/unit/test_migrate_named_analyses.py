"""The legacy analysis trees become sequence names, and the records that named them follow.

A legacy attempt is `analyses/<kind>/<signature>/<attempt>/` with its own `manifest.json`; the migration renames it
to `analyses/<kind>/<NNNN>-<YYYYMMDD>/`, rewrites the attempt's `directory` and rebases the job row's
`analyses[].directory`, in date order and above any sequence already present. It preserves a signature directory that
still holds something, is idempotent, rolls back from its backup, and refuses a run whose analysis is still working.
"""
import json
import os
from datetime import datetime, timezone

from dashboard import files
from dashboard.cli import migrate_named_analyses as migration
from dashboard.store import Store

RUN = 'run-20261116'
SIG = 'a' * 64
EARLIER = '2026-11-13T06:21:49.635866+00:00'
CREATED = '2026-11-16T06:18:20.596470+00:00'


def attempt(workspace, kind, signature, attempt_id, *, created_at=CREATED, modified=None, run=RUN):
    """One legacy attempt tree: a directory with a console log and the record the coordinator wrote."""
    directory = f'analyses/{kind}/{signature}/{attempt_id}'
    path = workspace / 'runs' / run / directory
    path.mkdir(parents=True, exist_ok=True)
    (path / 'console.log').write_text('log\n')
    record = {'id': attempt_id, 'kind': kind, 'status': 'completed', 'directory': directory,
              'log': f'{directory}/console.log'}
    if created_at is not None:
        record['created_at'] = created_at
    files.atomic_json(path / 'manifest.json', record)
    if modified is not None:
        os.utime(path, (modified, modified))
    return directory


def make_run(workspace, *, run_id=RUN, status='completed', analyses=None):
    """One run directory and its job row."""
    (workspace / 'runs' / run_id).mkdir(parents=True, exist_ok=True)
    Store(workspace / 'jobs.sqlite3').insert({
        'id': run_id, 'status': status, 'label': f'run {run_id}', 'run_type': 'cg',
        'created': '2026-11-16T00:00:00+00:00', 'settings': {'mdrun_gpu': 0}, 'analyses': analyses or []})
    return workspace / 'runs' / run_id


def row(workspace, run_id=RUN):
    return Store(workspace / 'jobs.sqlite3').get(run_id)


def snapshot(root):
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob('*')) if path.is_file()}


def test_attempts_become_dated_sequences_in_order_and_both_records_follow(tmp_path):
    sig = SIG
    (tmp_path / 'runs' / RUN / 'analyses' / 'trajectory-overview').mkdir(parents=True)
    (tmp_path / 'runs' / RUN / 'analyses' / 'trajectory-overview' / '0003-20251101').mkdir()
    attempt(tmp_path, 'trajectory-overview', sig, 'c56f7099f2b1')
    attempt(tmp_path, 'trajectory-overview', sig, 'ee249a4bc060', created_at=EARLIER)
    stamp = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc).timestamp()
    attempt(tmp_path, 'trajectory-overview', sig, '3f75ac0f94fd', created_at=None, modified=stamp)
    make_run(tmp_path, analyses=[
        {'id': 'c56f7099f2b1', 'kind': 'trajectory-overview', 'status': 'completed',
         'directory': f'analyses/trajectory-overview/{sig}/c56f7099f2b1', 'exit_code': 0},
        {'id': 'ee249a4bc060', 'kind': 'trajectory-overview', 'status': 'completed',
         'directory': f'analyses/trajectory-overview/{sig}/ee249a4bc060', 'exit_code': 0},
        {'id': '3f75ac0f94fd', 'kind': 'trajectory-overview', 'status': 'completed',
         'directory': f'analyses/trajectory-overview/{sig}/3f75ac0f94fd', 'exit_code': 4},
    ])
    before = row(tmp_path)

    entries = migration.plan(tmp_path)

    assert [entry['status'] for entry in entries] == ['move'], entries
    assert [move['new_path'] for move in entries[0]['moves']] == [
        'analyses/trajectory-overview/0004-20261020',
        'analyses/trajectory-overview/0005-20261113',
        'analyses/trajectory-overview/0006-20261116',
    ], entries[0]['moves']
    assert not (tmp_path / 'runs' / RUN / 'analyses' / 'trajectory-overview' / '0004-20261020').exists(), \
        'a dry run moves nothing'

    migration.apply(entries, tmp_path)

    root = tmp_path / 'runs' / RUN
    assert not (root / 'analyses' / 'trajectory-overview' / sig).exists(), 'the emptied signature directory is gone'
    for old, new in zip(('3f75ac0f94fd', 'ee249a4bc060', 'c56f7099f2b1'),
                        ('0004-20261020', '0005-20261113', '0006-20261116')):
        moved = root / 'analyses' / 'trajectory-overview' / new
        assert (moved / 'console.log').is_file()
        record = json.loads((moved / 'manifest.json').read_text())
        assert record['directory'] == f'analyses/trajectory-overview/{new}'
        assert record['id'] == old
    after = row(tmp_path)
    assert [task['directory'] for task in after['analyses']] == [
        f'analyses/trajectory-overview/{new}' for new in ('0006-20261116', '0005-20261113', '0004-20261020')]
    assert {key: value for key, value in after.items() if key != 'analyses'} == \
        {key: value for key, value in before.items() if key != 'analyses'}, 'every other field is untouched'
    for task, old in zip(after['analyses'], before['analyses']):
        assert {key: value for key, value in task.items() if key != 'directory'} == \
            {key: value for key, value in old.items() if key != 'directory'}
    backup = json.loads((tmp_path / '.named-migration' / 'analyses.json').read_text())
    assert [(move['run'], move['kind'], move['old_path'], move['new_path'],
             move['old_directory'], move['new_directory']) for move in backup['moves']] == [
        (RUN, 'trajectory-overview', f'analyses/trajectory-overview/{sig}/3f75ac0f94fd',
         'analyses/trajectory-overview/0004-20261020',
         f'analyses/trajectory-overview/{sig}/3f75ac0f94fd', 'analyses/trajectory-overview/0004-20261020'),
        (RUN, 'trajectory-overview', f'analyses/trajectory-overview/{sig}/ee249a4bc060',
         'analyses/trajectory-overview/0005-20261113',
         f'analyses/trajectory-overview/{sig}/ee249a4bc060', 'analyses/trajectory-overview/0005-20261113'),
        (RUN, 'trajectory-overview', f'analyses/trajectory-overview/{sig}/c56f7099f2b1',
         'analyses/trajectory-overview/0006-20261116',
         f'analyses/trajectory-overview/{sig}/c56f7099f2b1', 'analyses/trajectory-overview/0006-20261116'),
    ]


def test_a_dry_run_writes_nothing_and_names_each_move(tmp_path, capsys):
    attempt(tmp_path, 'trajectory-overview', SIG, 'c56f7099f2b1')
    make_run(tmp_path, analyses=[{'id': 'c56f7099f2b1', 'kind': 'trajectory-overview', 'status': 'completed',
                                  'directory': f'analyses/trajectory-overview/{SIG}/c56f7099f2b1'}])
    before = snapshot(tmp_path / 'runs')
    report = tmp_path / 'report.json'

    code = migration.main(['--workspace', str(tmp_path), '--report', str(report)])

    output = capsys.readouterr().out
    assert code == 0
    assert f'move {RUN}/trajectory-overview/{SIG}/c56f7099f2b1 -> 0001-20261116' in output, output
    assert json.loads(report.read_text())[0]['moves'][0]['new_path'] == 'analyses/trajectory-overview/0001-20261116'
    assert snapshot(tmp_path / 'runs') == before
    assert not (tmp_path / '.named-migration').exists(), 'a dry run writes no backup'


def test_a_signature_that_still_holds_a_file_is_kept_and_reported(tmp_path, capsys):
    sig = 'b' * 64
    attempt(tmp_path, 'trajectory-overview', sig, 'c56f7099f2b1')
    (tmp_path / 'runs' / RUN / 'analyses' / 'trajectory-overview' / sig / 'result.json').write_text('{}\n')
    make_run(tmp_path)

    entries = migration.plan(tmp_path)

    assert entries[0]['kept'] == [{'path': f'analyses/trajectory-overview/{sig}', 'entries': ['result.json']}]
    migration.main(['--workspace', str(tmp_path), '--apply'])
    kept = tmp_path / 'runs' / RUN / 'analyses' / 'trajectory-overview' / sig
    assert (kept / 'result.json').is_file(), 'the published set file is not deleted'
    assert 'keep ' in capsys.readouterr().out


def test_a_second_apply_reports_unchanged_and_writes_nothing(tmp_path, capsys):
    attempt(tmp_path, 'trajectory-overview', SIG, 'c56f7099f2b1')
    make_run(tmp_path, analyses=[{'id': 'c56f7099f2b1', 'kind': 'trajectory-overview', 'status': 'completed',
                                  'directory': f'analyses/trajectory-overview/{SIG}/c56f7099f2b1'}])
    migration.main(['--workspace', str(tmp_path), '--apply'])
    capsys.readouterr()
    backup = (tmp_path / '.named-migration' / 'analyses.json').read_bytes()
    before, record_before = snapshot(tmp_path / 'runs'), row(tmp_path)

    code = migration.main(['--workspace', str(tmp_path), '--apply'])

    output = capsys.readouterr().out
    assert code == 0 and 'move=0 unchanged=1' in output, output
    assert snapshot(tmp_path / 'runs') == before
    assert row(tmp_path) == record_before
    assert (tmp_path / '.named-migration' / 'analyses.json').read_bytes() == backup, 'the backup is not rewritten'


def test_rollback_puts_the_tree_and_the_row_back(tmp_path):
    sig = SIG
    attempt(tmp_path, 'trajectory-overview', sig, 'c56f7099f2b1')
    attempt(tmp_path, 'trajectory-overview', sig, 'ee249a4bc060', created_at=EARLIER)
    make_run(tmp_path, analyses=[
        {'id': 'c56f7099f2b1', 'kind': 'trajectory-overview', 'status': 'completed',
         'directory': f'analyses/trajectory-overview/{sig}/c56f7099f2b1', 'exit_code': 0},
        {'id': 'ee249a4bc060', 'kind': 'trajectory-overview', 'status': 'completed',
         'directory': f'analyses/trajectory-overview/{sig}/ee249a4bc060', 'exit_code': 0},
    ])
    before, record_before = snapshot(tmp_path / 'runs'), row(tmp_path)
    migration.apply(migration.plan(tmp_path), tmp_path)
    assert snapshot(tmp_path / 'runs') != before

    assert migration.rollback(tmp_path) == 2

    assert snapshot(tmp_path / 'runs') == before, 'the legacy names and their records are back, byte for byte'
    assert row(tmp_path) == record_before


def test_a_running_run_is_refused_and_nothing_moves(tmp_path, capsys):
    attempt(tmp_path, 'trajectory-overview', SIG, 'c56f7099f2b1')
    make_run(tmp_path, status='running')
    before = snapshot(tmp_path / 'runs')

    code = migration.main(['--workspace', str(tmp_path), '--apply'])

    output = capsys.readouterr().out
    assert code == 1 and 'refused' in output and 'the run is running' in output, output
    assert snapshot(tmp_path / 'runs') == before


def test_a_run_with_a_running_analysis_is_refused(tmp_path):
    attempt(tmp_path, 'surfaces', SIG, 'c56f7099f2b1')
    make_run(tmp_path, analyses=[{'id': 'c56f7099f2b1', 'kind': 'surfaces', 'status': 'running',
                                  'directory': f'analyses/surfaces/{SIG}/c56f7099f2b1'}])

    entry = migration.plan(tmp_path)[0]

    assert entry['status'] == 'refused' and 'the analysis surfaces is running' in entry['why']
    assert migration.apply([entry], tmp_path) == []
    assert (tmp_path / 'runs' / RUN / 'analyses' / 'surfaces' / SIG / 'c56f7099f2b1').is_dir()


def test_a_stable_kinds_legacy_attempts_are_retired_and_keep_their_bytes(tmp_path, capsys):
    """`frame-series` publishes at its kind root, so its two legacy attempts leave the row, not the disk."""
    root = tmp_path / 'runs' / RUN / 'analyses' / 'frame-series'
    root.mkdir(parents=True)
    files.atomic_json(root / 'manifest.json', {'id': '8bfbcc59d852', 'kind': 'frame-series',
                                               'stable': True, 'directory': 'analyses/frame-series'})
    failed = attempt(tmp_path, 'frame-series', 'a' * 64, '1f6ecb87b820')
    completed = attempt(tmp_path, 'frame-series', 'b' * 64, '947cc2626c50')
    root_entry = {'id': '8bfbcc59d852', 'kind': 'frame-series', 'stable': True, 'status': 'completed',
                  'directory': 'analyses/frame-series',
                  'log': 'analyses/frame-series/console.log',
                  'outputs': ['analyses/frame-series/analysis-metadata.json',
                              'analyses/frame-series/frames.json']}
    make_run(tmp_path, analyses=[
        {'id': '1f6ecb87b820', 'kind': 'frame-series', 'status': 'failed', 'directory': failed},
        {'id': '947cc2626c50', 'kind': 'frame-series', 'status': 'completed', 'directory': completed},
        root_entry,
    ])
    before, record_before = snapshot(tmp_path / 'runs'), row(tmp_path)

    entries = migration.plan(tmp_path)

    assert [entry['status'] for entry in entries] == ['retire'], entries
    assert [(retire['signature'], retire['attempt']) for retire in entries[0]['retires']] == [
        ('a' * 64, '1f6ecb87b820'), ('b' * 64, '947cc2626c50')], entries[0]['retires']
    assert snapshot(tmp_path / 'runs') == before, 'a dry run moves and retires nothing'

    code = migration.main(['--workspace', str(tmp_path)])
    output = capsys.readouterr().out
    assert code == 0, output
    assert f'retire {RUN}/frame-series/{"a" * 64}/1f6ecb87b820' in output, output
    assert f'retire {RUN}/frame-series/{"b" * 64}/947cc2626c50' in output, output
    assert 'move ' not in output

    migration.main(['--workspace', str(tmp_path), '--apply'])
    capsys.readouterr()
    after = row(tmp_path)
    assert after['analyses'] == [root_entry], 'only the root entry is left, untouched'
    assert snapshot(tmp_path / 'runs') == before, 'the retired attempts keep every byte and their records'
    backup = json.loads((tmp_path / '.named-migration' / 'analyses.json').read_text())
    assert [(record['action'], record['attempt'], record['index']) for record in backup['moves']] == [
        ('retire', '1f6ecb87b820', 0), ('retire', '947cc2626c50', 1)]

    code = migration.main(['--workspace', str(tmp_path), '--apply'])
    assert code == 0 and 'move=0 unchanged=1' in capsys.readouterr().out
    assert row(tmp_path) == after and snapshot(tmp_path / 'runs') == before, 'a second apply writes nothing'

    assert migration.rollback(tmp_path) == 2

    assert row(tmp_path) == record_before, 'rollback restores both retired entries exactly'
    assert snapshot(tmp_path / 'runs') == before


def test_a_stable_kind_without_a_root_entry_or_manifest_is_refused(tmp_path, capsys):
    directory = attempt(tmp_path, 'frame-series', SIG, '1f6ecb87b820')
    make_run(tmp_path, analyses=[{'id': '1f6ecb87b820', 'kind': 'frame-series', 'status': 'failed',
                                  'directory': directory}])
    before = snapshot(tmp_path / 'runs')

    code = migration.main(['--workspace', str(tmp_path), '--apply'])

    output = capsys.readouterr().out
    assert code == 1 and 'refused' in output and 'no root entry or manifest' in output, output
    assert snapshot(tmp_path / 'runs') == before
    assert row(tmp_path)['analyses'][0]['directory'] == directory


def test_a_moved_attempts_log_and_outputs_follow_it_in_the_row(tmp_path):
    directory = attempt(tmp_path, 'trajectory-overview', SIG, 'c56f7099f2b1')
    task = {'id': 'c56f7099f2b1', 'kind': 'trajectory-overview', 'status': 'completed',
            'directory': directory, 'log': f'{directory}/console.log',
            'outputs': [f'{directory}/output/result.json', 'stages/1_AA-reference/prod/lig.gro']}
    make_run(tmp_path, analyses=[task])
    record_before = row(tmp_path)

    migration.apply(migration.plan(tmp_path), tmp_path)

    new = 'analyses/trajectory-overview/0001-20261116'
    after = row(tmp_path)['analyses'][0]
    assert after['directory'] == new
    assert after['log'] == f'{new}/console.log'
    assert after['outputs'] == [f'{new}/output/result.json', 'stages/1_AA-reference/prod/lig.gro']
    backup = json.loads((tmp_path / '.named-migration' / 'analyses.json').read_text())
    assert backup['moves'][0]['action'] == 'move'
    assert backup['moves'][0]['entry'] == task

    assert migration.rollback(tmp_path) == 1
    assert row(tmp_path) == record_before
