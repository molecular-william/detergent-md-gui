"""The run-rename migration: a dry run, a verified rename, collision suffixing, refusal and exact rollback."""
import json

from dashboard import files
from dashboard.cli import rename_runs as migration
from dashboard.store import Store


def write_json(path, value):
    files.atomic_json(path, value)


def make_run(workspace, run_id, label, *, status='completed', run_type='cg', reference_run_id=None,
             created='2026-11-01T00:00:00+00:00'):
    run = workspace / 'runs' / run_id
    (run / 'inputs').mkdir(parents=True)
    (run / 'inputs' / 'note.txt').write_text('note')
    inputs = [{'role': 'generated', 'label': 'note.txt', 'kind': 'generated', 'root': 'run',
               'path': 'inputs/note.txt'}]
    manifest = {'id': run_id, 'label': label, 'run_type': run_type, 'status': status, 'inputs': inputs}
    if reference_run_id is not None:
        manifest['reference_run_id'] = reference_run_id
        manifest['shared_reference'] = {'source_run_id': reference_run_id, 'edition': 1}
        manifest['stages'] = [{
            'name': '1_AA-reference',
            'source_run': reference_run_id,
            'shared_reference': {'source_run_id': reference_run_id},
            'log': f'/work/runs/{run_id}/logs/1_AA-reference.log',
            'command': ['bash', 'run.sh'],
        }]
    write_json(run / 'manifest.json', manifest)
    write_json(run / 'inputs' / 'inputs.json', {'inputs': inputs})
    write_json(run / 'provenance.json',
               {'reference': {'run_id': reference_run_id} if reference_run_id else {}})
    attempt = run / 'analyses' / 'snapshots' / '0001-20261116'
    attempt.mkdir(parents=True)
    write_json(attempt / 'request.json', {'run': str(run), 'kind': 'snapshots'})
    write_json(attempt / 'manifest.json', {'id': 'attempt1', 'status': 'completed',
                                           'directory': 'analyses/snapshots/0001-20261116'})
    write_json(attempt / 'result.json', {'run': run_id})
    write_json(attempt / 'progress.json', {'done': 1})
    if run_type == 'aa_only':
        reference = run / 'stages' / '07_reference'
        reference.mkdir(parents=True)
        write_json(reference / 'reference.json',
                   {'reference_eligible': True, 'edition': 1, 'sha256': {}, 'molecule_identity': 'm1'})
    job = {'id': run_id, 'label': label, 'status': status, 'run_type': run_type, 'created': created,
           'analyses': [{'id': 'attempt1', 'status': 'completed',
                         'directory': 'analyses/snapshots/0001-20261116'}]}
    if reference_run_id is not None:
        job['reference_run_id'] = reference_run_id
        job['shared_reference'] = {'source_run_id': reference_run_id, 'edition': 1}
    Store(workspace / 'jobs.sqlite3').insert(job)
    return run


def make_parameterization(workspace, run_id):
    records = workspace / 'parameterizations' / 'records'
    jobs = workspace / 'parameterizations' / 'jobs'
    records.mkdir(parents=True)
    jobs.mkdir(parents=True)
    write_json(records / 'DDM.json',
               {'current': {'aa_reference': {'run_id': run_id, 'reference_edition': 1}},
                'engine_command': ['bash', f'/work/fit-{run_id}/fit.sh']})
    write_json(jobs / '019.json', {'id': '019', 'aa_reference': {'run_id': run_id},
                                   'reference_run_id': run_id, 'work': f'/work/fit-{run_id}'})


def snapshot(root, *, database=True):
    hashes = {}
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root).as_posix()
        if not path.is_file() or path.is_symlink():
            continue
        if relative == '.named-migration' or relative.startswith('.named-migration/'):
            continue
        if not database and relative.startswith('jobs.sqlite3'):
            continue
        hashes[relative] = files.sha256(path)
    return hashes


def rows(workspace):
    with Store(workspace / 'jobs.sqlite3').connection() as database:
        return database.execute('SELECT id, data, revision FROM jobs ORDER BY id').fetchall()


def test_the_dry_run_names_the_renames_and_writes_nothing(tmp_path, capsys):
    make_run(tmp_path, 'aa0000000001', 'DDM AA reference')
    make_run(tmp_path, 'aa0000000002', 'DDM-CG-100ns', created='2026-11-02T00:00:00+00:00')
    before = snapshot(tmp_path)

    assert migration.main(['--workspace', str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert 'rename aa0000000001 -> DDM-AA-reference' in output
    assert 'rename aa0000000002 -> DDM-CG-100ns' in output
    assert snapshot(tmp_path) == before, 'a dry run reads only'
    assert not (tmp_path / '.named-migration' / 'run-rename.json').exists()


def test_apply_renames_the_directory_references_and_retires_the_old_name(tmp_path):
    source = make_run(tmp_path, 'aa0000000001', 'DDM AA reference', run_type='aa_only')
    consumer = make_run(tmp_path, 'aa0000000002', 'DDM-CG-100ns', reference_run_id='aa0000000001',
                        created='2026-11-02T00:00:00+00:00')
    (source / 'stages' / 'out.dat').write_bytes(b'out')
    entry = {'role': 'source', 'label': 'out.dat', 'kind': 'run-output', 'root': 'runs',
             'path': 'aa0000000001/stages/out.dat'}
    manifest = json.loads((consumer / 'manifest.json').read_text())
    manifest['inputs'].append(entry)
    write_json(consumer / 'manifest.json', manifest)
    inputs = json.loads((consumer / 'inputs' / 'inputs.json').read_text())
    inputs['inputs'].append(entry)
    write_json(consumer / 'inputs' / 'inputs.json', inputs)
    make_parameterization(tmp_path, 'aa0000000001')

    result = migration.apply(migration.plan(tmp_path), tmp_path)

    assert result['verification'] == []
    new = 'DDM-AA-reference'
    assert (tmp_path / 'runs' / new).is_dir()
    assert not (tmp_path / 'runs' / 'aa0000000001').exists()
    store = Store(tmp_path / 'jobs.sqlite3')
    assert store.get(new)['id'] == new
    assert store.get('aa0000000001') is None
    assert 'aa0000000001' in store.retired_names()
    assert json.loads((tmp_path / 'runs' / new / 'manifest.json').read_text())['id'] == new

    consumer = tmp_path / 'runs' / 'DDM-CG-100ns'
    consumer_manifest = json.loads((consumer / 'manifest.json').read_text())
    assert consumer_manifest['reference_run_id'] == new
    assert consumer_manifest['shared_reference']['source_run_id'] == new
    assert consumer_manifest['stages'][0]['shared_reference']['source_run_id'] == new
    consumer_inputs = json.loads((consumer / 'inputs' / 'inputs.json').read_text())
    assert consumer_inputs['inputs'][-1]['path'] == f'{new}/stages/out.dat'
    consumer_job = Store(tmp_path / 'jobs.sqlite3').get('DDM-CG-100ns')
    assert consumer_job['reference_run_id'] == new
    assert consumer_job['shared_reference']['source_run_id'] == new

    request = json.loads((consumer / 'analyses' / 'snapshots' / '0001-20261116' / 'request.json').read_text())
    assert request['run'].endswith('DDM-CG-100ns') and 'aa0000000002' not in request['run']
    source_request = json.loads((tmp_path / 'runs' / new / 'analyses' / 'snapshots' / '0001-20261116'
                                 / 'request.json').read_text())
    assert source_request['run'].endswith(new) and 'aa0000000001' not in source_request['run']
    record = json.loads((tmp_path / 'parameterizations' / 'records' / 'DDM.json').read_text())
    assert record['current']['aa_reference']['run_id'] == new
    job_record = json.loads((tmp_path / 'parameterizations' / 'jobs' / '019.json').read_text())
    assert job_record['aa_reference']['run_id'] == new and job_record['reference_run_id'] == new
    assert migration.leftovers(tmp_path, ['aa0000000001']) == []
    ledger = json.loads((tmp_path / '.named-migration' / 'run-rename.json').read_text())
    assert [item['old'] for item in ledger['runs']] == ['aa0000000001', 'aa0000000002']


def test_a_new_name_colliding_with_a_live_id_is_suffixed(tmp_path):
    make_run(tmp_path, 'aa0000000001', 'foo')
    make_run(tmp_path, 'foo', 'foo', created='2026-11-02T00:00:00+00:00')

    plan = migration.plan(tmp_path)
    assert [(item['old'], item['new']) for item in plan['runs']] == [('aa0000000001', 'foo-2')]
    migration.apply(plan, tmp_path)
    assert (tmp_path / 'runs' / 'foo-2').is_dir()
    assert Store(tmp_path / 'jobs.sqlite3').get('foo-2')['id'] == 'foo-2'


def test_two_labels_with_one_slug_are_suffixed_in_created_order(tmp_path):
    make_run(tmp_path, 'aa0000000001', 'same label')
    make_run(tmp_path, 'aa0000000002', 'same label', created='2026-11-02T00:00:00+00:00')

    plan = migration.plan(tmp_path)
    assert [(item['old'], item['new']) for item in plan['runs']] == [
        ('aa0000000001', 'same-label'), ('aa0000000002', 'same-label-2')]


def test_a_working_run_refuses_the_whole_migration(tmp_path, capsys):
    make_run(tmp_path, 'aa0000000001', 'DDM AA reference', status='running')
    make_run(tmp_path, 'aa0000000002', 'DDM-CG-100ns')
    before = snapshot(tmp_path)

    assert migration.main(['--workspace', str(tmp_path), '--apply']) == 1
    assert 'refused: a run or analysis is working' in capsys.readouterr().out
    assert snapshot(tmp_path) == before
    assert not (tmp_path / '.named-migration' / 'run-rename.json').exists()


def test_a_busy_analysis_also_refuses(tmp_path):
    make_run(tmp_path, 'aa0000000001', 'DDM AA reference')
    job = Store(tmp_path / 'jobs.sqlite3').get('aa0000000001')
    job['analyses'][0]['status'] = 'queued'
    Store(tmp_path / 'jobs.sqlite3').update('aa0000000001', analyses=job['analyses'])

    plan = migration.plan(tmp_path)
    assert plan['busy'] == ['aa0000000001/attempt1']


def test_the_second_apply_is_a_noop(tmp_path, capsys):
    make_run(tmp_path, 'aa0000000001', 'DDM AA reference')
    migration.apply(migration.plan(tmp_path), tmp_path)
    after_first = snapshot(tmp_path)

    assert migration.main(['--workspace', str(tmp_path), '--apply']) == 0
    assert 'nothing to do' in capsys.readouterr().out
    assert snapshot(tmp_path) == after_first


def test_the_renamed_runs_own_paths_follow_it_and_another_run_is_untouched(tmp_path):
    source = make_run(tmp_path, 'aa0000000001', 'DDM AA reference')
    other = make_run(tmp_path, 'cc0000000002', 'another run')
    old_root = '/work/runs/aa0000000001'
    manifest_path = source / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['stages'] = [{
        'name': 'AA solvation',
        'log': f'{old_root}/logs/01_solvation.log',
        'cwd': f'{old_root}/stages/01_solvation',
        'command': ['bash', '-e', f'{old_root}/stages/01_solvation/run.sh'],
        'environment': {'RUN_ROOT': old_root},
    }]
    manifest['resume_history'] = [{'checkpoint': 'runs/aa0000000001/stages/01/cpt.cpt'}]
    write_json(manifest_path, manifest)
    attempt = source / 'analyses' / 'snapshots' / '0001-20261116'
    write_json(attempt / 'request.json', {'run': old_root,
                                          'command': ['gmx', 'trjconv', '-f', 'runs/aa0000000001/x.xtc']})
    other_manifest_path = other / 'manifest.json'
    other_manifest = json.loads(other_manifest_path.read_text())
    other_manifest['note'] = f'history naming {old_root}, which is not this run'
    write_json(other_manifest_path, other_manifest)
    Store(tmp_path / 'jobs.sqlite3').update('aa0000000001', log='runs/aa0000000001/logs/console.log',
                                            command=f'bash {old_root}/run.sh')
    before = snapshot(tmp_path, database=False)
    before_rows = rows(tmp_path)

    migration.apply(migration.plan(tmp_path), tmp_path)

    new = 'DDM-AA-reference'
    new_root = f'/work/runs/{new}'
    rewritten = json.loads((tmp_path / 'runs' / new / 'manifest.json').read_text())
    stage = rewritten['stages'][0]
    assert stage['log'] == f'{new_root}/logs/01_solvation.log'
    assert stage['cwd'] == f'{new_root}/stages/01_solvation'
    assert stage['command'][2] == f'{new_root}/stages/01_solvation/run.sh'
    assert stage['environment']['RUN_ROOT'] == new_root
    assert rewritten['resume_history'][0]['checkpoint'] == f'runs/{new}/stages/01/cpt.cpt'
    request = json.loads((tmp_path / 'runs' / new / 'analyses' / 'snapshots' / '0001-20261116'
                          / 'request.json').read_text())
    assert request['run'] == new_root and request['command'][-1] == f'runs/{new}/x.xtc'
    job = Store(tmp_path / 'jobs.sqlite3').get(new)
    assert job['log'] == f'runs/{new}/logs/console.log' and job['command'] == f'bash {new_root}/run.sh'
    untouched = json.loads((tmp_path / 'runs' / 'another-run' / 'manifest.json').read_text())
    assert untouched['note'] == f'history naming {old_root}, which is not this run'

    migration.rollback(tmp_path)
    assert snapshot(tmp_path, database=False) == before
    assert rows(tmp_path) == before_rows
    restored = json.loads((tmp_path / 'runs' / 'aa0000000001' / 'manifest.json').read_text())
    assert restored['stages'][0]['log'] == f'{old_root}/logs/01_solvation.log'


def test_rollback_restores_exact_bytes_rows_and_retired_entries(tmp_path):
    make_run(tmp_path, 'aa0000000001', 'DDM AA reference', run_type='aa_only')
    make_run(tmp_path, 'aa0000000002', 'DDM-CG-100ns', reference_run_id='aa0000000001',
             created='2026-11-02T00:00:00+00:00')
    make_parameterization(tmp_path, 'aa0000000001')
    before_files, before_rows = snapshot(tmp_path, database=False), rows(tmp_path)

    migration.apply(migration.plan(tmp_path), tmp_path)
    assert snapshot(tmp_path, database=False) != before_files
    assert 'aa0000000001' in Store(tmp_path / 'jobs.sqlite3').retired_names()

    restored = migration.rollback(tmp_path)
    assert restored['runs'] == 2 and restored['rows'] == 2 and restored['retired'] == 2
    assert restored['files'] > 0
    assert snapshot(tmp_path, database=False) == before_files
    assert rows(tmp_path) == before_rows
    assert Store(tmp_path / 'jobs.sqlite3').retired_names() == []


def test_an_existing_target_directory_is_refused_without_writing(tmp_path, capsys):
    make_run(tmp_path, 'aa0000000001', 'DDM AA reference')
    (tmp_path / 'runs' / 'DDM-AA-reference').mkdir()
    before = snapshot(tmp_path)

    assert migration.main(['--workspace', str(tmp_path), '--apply']) == 1
    output = capsys.readouterr().out
    assert 'refused aa0000000001 -> DDM-AA-reference' in output
    assert snapshot(tmp_path) == before
    assert Store(tmp_path / 'jobs.sqlite3').get('aa0000000001')['id'] == 'aa0000000001'
