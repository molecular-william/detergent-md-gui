"""The run-type migration rewrites both records, archives the old ones, and is idempotent."""
import json

from dashboard import files
from dashboard.cli import migrate_run_types as migration
from dashboard.store import Store


def write(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def make_run(workspace, run_id, run_type='aa_cg', status='completed', stage_plan=None):
    run = workspace / 'runs' / run_id
    manifest = {'id': run_id, 'run_type': run_type, 'status': status,
                'stage_plan': stage_plan or [['AA reference', '1_AA-reference/aa_reference.sh'],
                                             ['trajectory mapping', '2_mapping/map_trajectory.sh']],
                'bonded': {'consumes_parameterization': True, 'revision': 2}}
    write(run / 'manifest.json', json.dumps(manifest, indent=2) + '\n')
    write(run / '2_mapping' / 'mapped.gro', 'beads\n')
    Store(workspace / 'jobs.sqlite3').insert({'id': run_id, 'run_type': run_type, 'status': status,
                                              'stage_plan': manifest['stage_plan'],
                                              'label': f'run {run_id}', 'created': '2026-11-01T00:00:00+00:00'})
    return run


def snapshot(root):
    return {path.relative_to(root).as_posix(): files.sha256(path)
            for path in sorted(root.rglob('*')) if path.is_file()}


def test_the_dry_run_lists_the_retired_runs_and_writes_nothing(tmp_path):
    make_run(tmp_path, 'aa0000000001')
    make_run(tmp_path, 'aa0000000002', status='running')
    make_run(tmp_path, 'pdc0000000001', run_type='pdc')
    before = snapshot(tmp_path)

    entries = migration.plan(tmp_path)
    assert [entry['id'] for entry in entries] == ['aa0000000001', 'aa0000000002', 'pdc0000000001']
    assert {entry['id']: entry['status'] for entry in entries} == {
        'aa0000000001': 'planned', 'aa0000000002': 'refused', 'pdc0000000001': 'unchanged'}
    assert snapshot(tmp_path) == before, 'a dry run reads only'
    assert migration.main(['--workspace', str(tmp_path)]) == 1, 'a refused run fails the command'


def test_apply_rewrites_manifest_and_job_row_and_keeps_the_stage_plan(tmp_path):
    run = make_run(tmp_path, 'aa0000000001')
    entries = migration.plan(tmp_path)
    applied = migration.apply(entries, tmp_path)

    assert len(applied) == 1
    manifest = json.loads((run / 'manifest.json').read_text())
    assert manifest['run_type'] == 'cg'
    assert manifest['legacy_run_type'] == 'aa_cg'
    assert manifest['cg_model_kind'] == 'revision'
    assert manifest['workflow_version'] == 'cg-v1'
    assert manifest['stage_plan'] == entries[0]['manifest']['stage_plan'], 'the plan is not rewritten'
    job = Store(tmp_path / 'jobs.sqlite3').get('aa0000000001')
    assert job['run_type'] == 'cg' and job['legacy_run_type'] == 'aa_cg'
    assert job['stage_plan'] == entries[0]['record']['stage_plan']
    record = json.loads((run / migration.RECORD).read_text())
    assert record['from'] == 'aa_cg' and record['to'] == 'cg'
    assert (run / record['archive']).is_file(), 'the old records are archived first'
    assert (run / '2_mapping' / 'mapped.gro').is_file(), 'stage files are untouched'


def test_a_second_apply_is_a_noop(tmp_path):
    make_run(tmp_path, 'aa0000000001')
    migration.apply(migration.plan(tmp_path), tmp_path)
    after_first = snapshot(tmp_path)

    entries = migration.plan(tmp_path)
    assert entries[0]['status'] == 'unchanged'
    assert migration.apply(entries, tmp_path) == []
    assert snapshot(tmp_path) == after_first


def test_the_other_retired_types_carry_their_own_cg_kind(tmp_path):
    make_run(tmp_path, 'su00000000001', run_type='sugar_cg')
    make_run(tmp_path, 'cg00000000001', run_type='cg_composition')

    entries = {entry['id']: entry for entry in migration.plan(tmp_path)}
    assert entries['su00000000001']['kind'] == 'reference'
    assert entries['cg00000000001']['kind'] == 'composition'
    migration.apply(list(entries.values()), tmp_path)
    assert json.loads((tmp_path / 'runs/su00000000001/manifest.json').read_text())['cg_model_kind'] == 'reference'
    assert json.loads((tmp_path / 'runs/cg00000000001/manifest.json').read_text())['cg_model_kind'] == 'composition'


def test_a_missing_job_record_is_refused_rather_than_half_migrated(tmp_path):
    run = make_run(tmp_path, 'aa0000000001')
    Store(tmp_path / 'jobs.sqlite3').delete('aa0000000001')

    entries = migration.plan(tmp_path)
    assert entries[0]['status'] == 'refused'
    assert json.loads((run / 'manifest.json').read_text())['run_type'] == 'aa_cg'


def test_a_record_that_names_no_run_type_is_the_historical_combined_job(tmp_path):
    """`aa_cg` was the default for an absent type, so the migration rewrites that record too.

    That is what lets `protocol.run_type_of` agree with the record the migration leaves behind: every absent
    record becomes a `cg` revision run instead of resolving to a retired name at read time.
    """
    run = make_run(tmp_path, 'aa0000000003')
    manifest = json.loads((run / 'manifest.json').read_text())
    manifest.pop('run_type')
    (run / 'manifest.json').write_text(json.dumps(manifest) + '\n')

    entry = migration.plan(tmp_path)[0]
    assert entry['status'] == 'planned' and entry['from'] == 'aa_cg' and entry['kind'] == 'revision'
    migration.apply([entry], tmp_path)
    assert json.loads((run / 'manifest.json').read_text())['run_type'] == 'cg'
