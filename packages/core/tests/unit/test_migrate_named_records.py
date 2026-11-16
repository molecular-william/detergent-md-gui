"""The named-record migration: dry run, apply, rollback, and the refusals that leave a record alone.

Every fixture is a temporary workspace with its own data root, so the live workspace is never read or written. The
consumer run carries every legacy spelling at once -- a digest input entry, a workspace Martini path, a {path,
sha256} stage script and Python module, a shared reference pinned by digest, and a digest-shaped molecule snapshot
-- so one apply exercises the whole conversion and one rollback proves it is reversible.
"""
import json
import shutil

import pytest
from dashboard import files, martini3, paths
from dashboard.cli import migrate_named_records as migration
from dashboard.models.molecules import aa
from dashboard.store import Store

SOURCE = 'aa0000000001'
CONSUMER = 'cg0000000002'
MOLECULE = 'Glucose'
MARTINI = martini3.REQUIRED[0]
DIGEST = '0' * 64


def snapshot(root):
    """Every file except the job database and the migration's own backup ledger."""
    return {path.relative_to(root).as_posix(): files.sha256(path)
            for path in sorted(root.rglob('*'))
            if path.is_file() and not path.name.startswith('jobs.sqlite3')
            and migration.BACKUP_DIRECTORY not in path.parts}


def rows(root):
    return {row['data']['id']: (row['text'], row['revision']) for row in migration._job_rows(root)}


def legacy(project, run_type):
    """A digest-era selection: the shape `digests=True` used to write, kept here as the migration's input."""
    record = aa.inspect(project / 'molecules', MOLECULE, version=None)
    snapshot = aa._selection(record, run_type)
    snapshot.pop('version', None)
    snapshot.update(name=record['name'], sha256=record['sha256'],
                    reference_sha256=record['reference_sha256'])
    return snapshot


def upstream(project):
    itps = project / 'references' / 'M3-Lipid-Parameters' / 'ITPs'
    itps.mkdir(parents=True)
    for name in martini3.REQUIRED:
        (itps / name).write_text(f'; {name}\n[ moleculetype ]\nW 1\n')
    (itps / 'README.md').write_text('the lipidome readme\n')
    (project / 'references' / 'M3-Lipid-Parameters' / 'LICENSE.txt').write_text('Apache-2.0\n')
    (project / 'references' / 'martini_v3.0.0_sugars_v2.itp').write_text('; sugars\n')
    (project / 'references' / 'martini_v3.0.0_sugars_v2.source.json').write_text('{"martini_version": 3}\n')
    shutil.copytree(paths.PROJECT_ROOT / 'molecules' / MOLECULE, project / 'molecules' / MOLECULE)


def source_run(project, workspace):
    run = workspace / 'runs' / SOURCE
    run.mkdir(parents=True)
    files.atomic_json(run / 'manifest.json', {
        'id': SOURCE, 'run_type': 'aa_only', 'status': 'completed', 'layout_version': 3,
        'stage_plan': ['AA solvation']})
    names = ('lig.gro', 'lig.xtc', 'lig.tpr')
    for name in names:
        (run / 'stages' / '07_reference' / name).parent.mkdir(parents=True, exist_ok=True)
        (run / 'stages' / '07_reference' / name).write_text('x\n')
    files.atomic_json(run / 'stages' / '07_reference' / 'reference.json', {
        'schema_version': 1, 'reference_eligible': True,
        'artifacts': {name: f'stages/07_reference/{name}' for name in names},
        'sha256': {f'stages/07_reference/{name}': str(index) * 64 for index, name in enumerate(names)},
        'molecule_snapshot': legacy(project, 'aa_only')})


def consumer_run(project, workspace):
    run = workspace / 'runs' / CONSUMER
    run.mkdir(parents=True)
    inputs = [
        {'role': 'martini_force_field', 'label': 'Martini 3 force field', 'kind': 'published',
         'root': 'workspace', 'path': f'martini3/{MARTINI}', 'sha256': 'a' * 64, 'bytes': 1},
        {'role': 'molecule', 'label': 'Glucose/metadata.json', 'kind': 'published',
         'root': 'repo', 'path': f'molecules/{MOLECULE}/v1/metadata.json', 'sha256': 'b' * 64, 'bytes': 2},
        {'role': 'generated', 'label': '01_solvation/run.mdp', 'kind': 'generated',
         'root': 'run', 'path': 'inputs/01_solvation/run.mdp', 'sha256': 'c' * 64, 'bytes': 3},
    ]
    files.atomic_json(run / 'manifest.json', {
        'id': CONSUMER, 'run_type': 'cg', 'status': 'completed', 'layout_version': 3,
        'stage_plan': [['CG simulation', '4_CG_sim/cg_simulation_run.sh']],
        'parameterization': {'kind': 'revision', 'mapping': 'model', 'revision': 1},
        'input_snapshot_sha256': DIGEST,
        'inputs': inputs,
        'stage_scripts': {'CG simulation': {
            'path': 'dashboard/execution/scripts/cg_simulation.sh', 'sha256': 'd' * 64}},
        'python_modules': {'aa_references': {
            'path': 'dashboard/analysis/runs/references.py', 'sha256': 'e' * 64}},
        'shared_reference': {'source_run_id': SOURCE,
                            'sha256': {'stages/07_reference/lig.gro': 'f' * 64}},
        'molecule_snapshot': legacy(project, 'aa_cg'),
        'settings': {}, 'tools': {}, 'stages': []})
    files.atomic_json(run / 'inputs' / 'inputs.json', {'inputs': inputs})
    generated = run / 'inputs' / '01_solvation' / 'run.mdp'
    generated.parent.mkdir(parents=True)
    generated.write_text('; a generated input\n')


@pytest.fixture
def world(tmp_path):
    project, workspace = tmp_path / 'project', tmp_path / 'workspace'
    upstream(project)
    (workspace / 'martini3').mkdir(parents=True)
    (workspace / 'martini3' / 'flat-install.txt').write_text('do not rewrite\n')
    source_run(project, workspace)
    consumer_run(project, workspace)
    store = Store(workspace / 'jobs.sqlite3')
    store.insert({'id': SOURCE, 'run_type': 'aa_only', 'status': 'completed',
                  'molecule_snapshot': legacy(project, 'aa_only'),
                  'created': '2026-11-01T00:00:00+00:00'})
    store.insert({'id': CONSUMER, 'run_type': 'cg', 'status': 'completed',
                  'molecule_snapshot': legacy(project, 'aa_cg'),
                  'created': '2026-11-02T00:00:00+00:00'})
    return project, workspace


def test_the_dry_run_lists_every_change_and_writes_nothing(world):
    project, workspace = world
    before, before_rows = snapshot(workspace), rows(workspace)

    entries = migration.plan(workspace, project_root=project)

    assert [(entry['run'], entry['status']) for entry in entries['references']] == [(SOURCE, 'edition')]
    assert entries['martini']['status'] == 'install'
    assert [(entry['run'], entry['status']) for entry in entries['manifests']] == [
        (SOURCE, 'write'), (CONSUMER, 'write')]
    assert {entry['run']: entry['status'] for entry in entries['jobs']} == {
        SOURCE: 'write', CONSUMER: 'write'}
    assert snapshot(workspace) == before, 'a dry run reads only'
    assert rows(workspace) == before_rows
    assert not (workspace / migration.BACKUP_DIRECTORY).exists()


def test_apply_rewrites_every_legacy_spelling(world):
    project, workspace = world

    result = migration.apply(migration.plan(workspace, project_root=project), workspace)

    assert result['verification'] == [], result['verification']
    manifest = json.loads((workspace / 'runs' / CONSUMER / 'manifest.json').read_text())
    assert manifest['layout_version'] == 4
    assert 'input_snapshot_sha256' not in manifest
    assert manifest['inputs'][0] == {
        'role': 'martini_force_field', 'label': 'Martini 3 force field', 'kind': 'published',
        'root': 'workspace', 'path': f'martini3/{martini3.VERSION}/{MARTINI}'}
    assert set(manifest['inputs'][0]) == {'role', 'label', 'kind', 'root', 'path'}
    assert manifest['stage_scripts']['CG simulation'] == {'name': 'cg_simulation', 'version': 1}
    assert manifest['python_modules']['aa_references'] == {'name': 'references', 'version': 1}
    assert manifest['shared_reference'] == {'source_run_id': SOURCE, 'edition': 1}
    assert manifest['molecule_snapshot'] == aa.selection(
        project / 'molecules', MOLECULE, 'aa_cg')
    assert (workspace / 'runs' / CONSUMER / 'provenance.json').is_file()
    assert (workspace / 'runs' / CONSUMER / 'inputs' / 'inputs.json').is_file()
    inputs_record = json.loads((workspace / 'runs' / CONSUMER / 'inputs' / 'inputs.json').read_text())
    assert inputs_record['inputs'] == manifest['inputs']

    reference = json.loads((workspace / 'runs' / SOURCE / 'stages/07_reference/reference.json').read_text())
    assert reference['edition'] == 1 and reference['molecule'] == MOLECULE

    job = Store(workspace / 'jobs.sqlite3').get(CONSUMER)
    assert job['molecule_snapshot'] == manifest['molecule_snapshot']
    assert {key: value for key, value in job.items() if key != 'molecule_snapshot'} == {
        'id': CONSUMER, 'run_type': 'cg', 'status': 'completed',
        'created': '2026-11-02T00:00:00+00:00'}, 'every other row field is kept'

    versioned = workspace / 'martini3' / martini3.VERSION
    assert (versioned / MARTINI).is_file() and (versioned / martini3.MANIFEST_NAME).is_file()
    assert (workspace / 'martini3' / 'flat-install.txt').read_text() == 'do not rewrite\n', \
        'the flat install is never rewritten'


def test_the_second_run_reports_unchanged_and_writes_nothing(world):
    project, workspace = world
    migration.apply(migration.plan(workspace, project_root=project), workspace)
    after, after_rows = snapshot(workspace), rows(workspace)

    entries = migration.plan(workspace, project_root=project)

    assert [entry['status'] for entry in entries['references']] == ['unchanged']
    assert entries['martini']['status'] == 'present'
    assert [entry['status'] for entry in entries['manifests']] == ['unchanged', 'unchanged']
    assert [entry['status'] for entry in entries['jobs']] == ['unchanged', 'unchanged']
    ledger = workspace / migration.BACKUP_DIRECTORY / migration.RECORDS_NAME
    inode = ledger.stat().st_ino
    result = migration.apply(entries, workspace)
    assert result['written'] == {'references': [], 'manifests': [], 'jobs': []}
    assert snapshot(workspace) == after and rows(workspace) == after_rows
    assert ledger.stat().st_ino == inode, 'a no-op apply rewrote the backup ledger'


def test_rollback_restores_every_original_byte_and_revision(world):
    project, workspace = world
    before, before_rows = snapshot(workspace), rows(workspace)
    migration.apply(migration.plan(workspace, project_root=project), workspace)

    result = migration.rollback(workspace)

    assert result['status'] == 'rolled-back' and result['warnings'] == []
    assert snapshot(workspace) == before
    assert rows(workspace) == before_rows
    assert not (workspace / 'martini3' / martini3.VERSION).exists()
    assert not (workspace / 'runs' / CONSUMER / 'provenance.json').exists()


def test_a_reference_with_a_missing_artifact_keeps_its_legacy_pin(world):
    project, workspace = world
    (workspace / 'runs' / SOURCE / 'stages/07_reference/lig.gro').unlink()

    entries = migration.plan(workspace, project_root=project)
    reference = next(entry for entry in entries['references'] if entry['run'] == SOURCE)
    assert reference['status'] == 'blocked' and 'missing' in reference['reason']

    result = migration.apply(entries, workspace)
    assert result['verification'] == []
    record = json.loads((workspace / 'runs' / SOURCE / 'stages/07_reference/reference.json').read_text())
    assert 'edition' not in record
    manifest = json.loads((workspace / 'runs' / CONSUMER / 'manifest.json').read_text())
    assert manifest['shared_reference']['source_run_id'] == SOURCE
    assert 'sha256' in manifest['shared_reference'], 'the legacy map is kept and reported'


def test_an_unregistered_code_path_is_reported_and_the_run_is_left_alone(world):
    project, workspace = world
    manifest_path = workspace / 'runs' / CONSUMER / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['stage_scripts']['CG simulation'] = {
        'path': 'dashboard/execution/scripts/not_registered.sh', 'sha256': 'f' * 64}
    files.atomic_json(manifest_path, manifest)
    before = manifest_path.read_text()

    entries = migration.plan(workspace, project_root=project)
    entry = next(entry for entry in entries['manifests'] if entry['run'] == CONSUMER)
    assert entry['status'] == 'blocked' and 'no code version is registered' in entry['reason']

    migration.apply(entries, workspace)

    assert manifest_path.read_text() == before
    assert not (workspace / 'runs' / CONSUMER / 'provenance.json').exists()


def test_a_snapshot_that_does_not_match_leaves_the_job_row_alone(world):
    project, workspace = world
    store = Store(workspace / 'jobs.sqlite3')
    mismatched = legacy(project, 'aa_cg')
    mismatched['metadata'] = {**mismatched['metadata'], 'net_charge': 999}
    store.update(CONSUMER, molecule_snapshot=mismatched)
    before = rows(workspace)

    entries = migration.plan(workspace, project_root=project)
    entry = next(entry for entry in entries['jobs'] if entry['run'] == CONSUMER)
    assert entry['status'] == 'blocked' and 'does not match the molecule' in entry['reason']

    migration.apply(entries, workspace)
    assert rows(workspace)[CONSUMER] == before[CONSUMER]


def test_a_store_path_is_rebased_from_the_legacy_hash_to_the_record_name(tmp_path):
    """A run written before the store was renamed names its revision files under the old content hash."""
    workspace = tmp_path / 'workspace'
    records = workspace / 'parameterizations' / 'records'
    records.mkdir(parents=True)
    (records / 'Glucose-0.json').write_text(json.dumps({'legacy_hash': DIGEST, 'name': 'Glucose-0'}))
    names = migration._store_names(workspace)

    assert names == {DIGEST: 'Glucose-0'}
    entry = {'role': 'reference_distribution', 'label': '1_B01_1_B02', 'kind': 'store', 'root': 'workspace',
             'path': f'parameterizations/records/{DIGEST}.revisions/1/1_B01_1_B02_distances_distr.dat'}
    converted = migration._convert_input(entry, names)
    assert converted == {'role': 'reference_distribution', 'label': '1_B01_1_B02', 'kind': 'store',
                         'root': 'workspace',
                         'path': 'parameterizations/records/Glucose-0.revisions/1/1_B01_1_B02_distances_distr.dat'}
    assert migration._convert_input(entry, {})['path'] == entry['path'], 'an unknown hash is left for a human'


def test_a_working_run_refuses_apply(world):
    project, workspace = world
    Store(workspace / 'jobs.sqlite3').update(CONSUMER, status='running')
    entries = migration.plan(workspace, project_root=project)

    assert CONSUMER in ' '.join(entries['busy'])
    with pytest.raises(RuntimeError, match='working'):
        migration.apply(entries, workspace)
