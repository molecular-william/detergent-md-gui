"""The named mapping-identity migration: dry run, apply, rollback, and the refusals that leave a record alone.

Every fixture is a temporary project and workspace built here, so neither the live workspace nor the checkout's
molecules are read or written: one versioned molecule folder, one saved draft still carrying a digest snapshot, one
parameterization record, one job row and one prepared manifest that all stamp the old identity and carry the mapping
document with its digest snapshot. One apply rewrites them, one second apply writes nothing, and one rollback restores
the exact bytes.
"""
import json
import shutil

from dashboard import files, martini3, paths
from dashboard.cli import migrate_mapping_identities as migration
from dashboard.models.bonded import parameterization
from dashboard.models.mappings import identity
from dashboard.models.mappings.context import as_structure, build_context
from dashboard.models.molecules import draft as draft_model
from dashboard.store import Store

from tests.harness.support import automatic_mapping
from tests.harness.support import write_aa_fixture as write_fixture

DRAFT_FILE = 'mapping_candidate_' + '0' * 32 + '.json'
JOB = 'cg0000000001'
DIGEST_SNAPSHOT = {'files': {'molecule.itp': 'a' * 64}, 'atom_order_sha256': 'b' * 64,
                   'snapshot_sha256': 'c' * 64}


def snapshot(root):
    """Every file except the job database and the migration's own ledger."""
    return {path.relative_to(root).as_posix(): files.sha256(path)
            for path in sorted(root.rglob('*'))
            if path.is_file() and not path.name.startswith('jobs.sqlite3')
            and migration.BACKUP_DIRECTORY not in path.parts}


def upstream(project):
    """The smallest Martini 3 upstream the draft validation reads: one bead type and the set's own files.

    `draft_model.load` checks a bead's type against the installed Martini set, so a temporary project needs the
    upstream the install is built from. The file names and the atomtypes block are what `martini3.names` and
    `packaged.bead_types` read; the rest of the real set is science no test here needs.
    """
    itps = project / 'references' / 'M3-Lipid-Parameters' / 'ITPs'
    itps.mkdir(parents=True)
    (itps / 'martini_v3.0.0.itp').write_text('[ atomtypes ]\nC1 72 0 A 0 0\nP1 72 0 A 0 0\nP2 72 0 A 0 0\n')
    (itps / 'martini_v3.0.0_solvents_v1.itp').write_text('[ moleculetype ]\nW 1\n')
    (itps / 'martini_v3.0.0_ions_v1.itp').write_text('[ moleculetype ]\nION 1\n')
    (itps / 'README.md').write_text('test upstream\n')
    (project / 'references' / 'martini_v3.0.0_sugars_v2.itp').write_text('[ moleculetype ]\nSUCR 1\n')
    (project / 'references' / 'martini_v3.0.0_sugars_v2.source.json').write_text('{"martini_version": 3}\n')
    (project / 'references' / 'M3-Lipid-Parameters' / 'LICENSE.txt').write_text('Apache-2.0\n')


def draft_for(project, molecule_id='Fixture', name='Fixture draft'):
    context = build_context(project / 'molecules', molecule_id)
    draft = automatic_mapping(as_structure(context), name)
    draft.update(schema_version=3, molecule_id=molecule_id, molecule_snapshot=dict(DIGEST_SNAPSHOT),
                 rings=[], connections=[], provenance={'origin': 'manual', 'algorithm': None, 'references': []})
    return draft


def old_identities(draft):
    return {'mapping_hash': identity.legacy_candidate_identity(draft),
            'mapping_content_hash': identity.legacy_content_identity(draft)}


def world(tmp_path, monkeypatch, molecule_id='Fixture'):
    """A project, a workspace and the three records that stamp the pre-naming identity.

    The Martini install points at this test's own directory: the session's shared install must not be built from this
    fixture's minimal upstream, and the install is outside the workspace so no snapshot of it counts as a write.
    """
    monkeypatch.setenv(martini3.ENVIRONMENT_VARIABLE, str(tmp_path / 'martini3'))
    project, workspace = tmp_path / 'project', tmp_path / 'workspace'
    write_fixture(project / 'molecules', molecule_id)
    upstream(project)
    # Install the shared set once, as the application would: the verification's draft load reads it, and installing
    # it during apply would be a workspace write outside the ledger.
    with paths.use(paths.Paths(project_root=project, workspace=workspace)):
        martini3.ensure()
    draft = draft_for(project, molecule_id)
    drafts = workspace / 'mapping_drafts'
    drafts.mkdir(parents=True)
    files.atomic_json(drafts / DRAFT_FILE, draft)
    slug = parameterization.address(draft)
    old = old_identities(draft)
    records = workspace / 'parameterizations' / 'records'
    files.atomic_json(records / f'{slug}.json', {
        'name': slug, 'revision': 2, **old,
        'current': {'revision': 2, 'engine': 'fast-forward', **old},
        'revisions': [{'revision': 1, 'engine': 'fast-forward', **old},
                      {'revision': 2, 'engine': 'fast-forward', **old}]})
    files.atomic_json(records / 'orphan.json', {
        'name': 'orphan', 'revision': 0, 'mapping_hash': 'd' * 64,
        'mapping_content_hash': 'e' * 64, 'revisions': []})
    store = Store(workspace / 'jobs.sqlite3')
    # A run keeps the whole mapping document it was prepared with, nested snapshot and all, beside its draft's name.
    store.insert({'id': JOB, 'run_type': 'cg', 'status': 'completed', 'mapping_snapshot': draft,
                  'parameterization': {'kind': 'revision', 'mapping': slug,
                                       'mapping_candidate': DRAFT_FILE, **old}})
    run = workspace / 'runs' / JOB
    files.atomic_json(run / 'manifest.json', {
        'id': JOB, 'run_type': 'cg', 'mapping_candidate': draft, 'parameterization': {
            'kind': 'revision', 'mapping': slug, 'mapping_candidate': DRAFT_FILE, **old}})
    return project, workspace, draft, slug, old


def test_a_dry_run_reports_and_writes_nothing(tmp_path, monkeypatch):
    project, workspace, _draft, slug, old = world(tmp_path, monkeypatch)
    before = snapshot(workspace)

    entries = migration.plan(workspace, project_root=project)

    assert snapshot(workspace) == before, 'a dry run is a report'
    assert [entry['status'] for entry in entries['drafts']] == ['write']
    assert [entry['status'] for entry in entries['records']] == ['write', 'blocked']
    assert [entry['status'] for entry in entries['jobs']] == ['write']
    assert [entry['status'] for entry in entries['manifests']] == ['write']
    blocked = next(entry for entry in entries['records'] if entry['status'] == 'blocked')
    assert blocked['record'] == 'orphan'
    assert 'no saved mapping draft' in blocked['reason']
    assert not (workspace / migration.BACKUP_DIRECTORY).exists()


def test_apply_names_the_version_and_restamps_every_record(tmp_path, monkeypatch):
    project, workspace, draft, slug, old = world(tmp_path, monkeypatch)
    original_draft_text = (workspace / 'mapping_drafts' / DRAFT_FILE).read_text()

    result = migration.apply(migration.plan(workspace, project_root=project),
                             workspace, project_root=project)

    assert result['verification'] == []
    migrated = json.loads((workspace / 'mapping_drafts' / DRAFT_FILE).read_text())
    assert migrated['molecule_snapshot'] == {'molecule_id': 'Fixture', 'version': 'v1'}
    for key in ('name', 'beads', 'rings', 'connections'):
        assert migrated[key] == draft[key], 'the migration renames the molecule, never the mapping'
    wanted = {'mapping_hash': identity.candidate_identity(migrated),
              'mapping_content_hash': identity.content_identity(migrated)}
    assert wanted != old

    record = json.loads((workspace / 'parameterizations' / 'records' / f'{slug}.json').read_text())
    assert {key: record[key] for key in wanted} == wanted
    assert record['revision'] == 2, 'revisions are restamped, not renumbered'
    for revision in record['revisions'] + [record['current']]:
        assert {key: revision[key] for key in wanted} == wanted

    job = Store(workspace / 'jobs.sqlite3').get(JOB)
    assert {key: job['parameterization'][key] for key in wanted} == wanted
    manifest = json.loads((workspace / 'runs' / JOB / 'manifest.json').read_text())
    assert {key: manifest['parameterization'][key] for key in wanted} == wanted

    ledger = json.loads((workspace / migration.BACKUP_DIRECTORY / migration.RECORDS_NAME).read_text())
    assert ledger['drafts'][DRAFT_FILE]['text'] == original_draft_text
    assert ledger['records'][slug]['text']
    assert ledger['jobs'][JOB]['text'] and ledger['manifests'][JOB]['text']
    # The record whose name no draft answers is reported and left untouched.
    orphan = json.loads((workspace / 'parameterizations' / 'records' / 'orphan.json').read_text())
    assert orphan['mapping_content_hash'] == 'e' * 64


def rewrite_job(workspace, change):
    """Apply one change to the stored job row, as a stale workspace or a hand edit would leave it."""
    store = Store(workspace / 'jobs.sqlite3')
    job = store.get(JOB)
    change(job)
    with store.connection() as db:
        db.execute('UPDATE jobs SET data=? WHERE id=?', (json.dumps(job), JOB))


def test_apply_names_the_embedded_mapping_snapshot_and_leaves_the_mapping_alone(tmp_path, monkeypatch):
    project, workspace, _draft, _slug, _old = world(tmp_path, monkeypatch)
    job_before = Store(workspace / 'jobs.sqlite3').get(JOB)['mapping_snapshot']
    manifest_before = json.loads((workspace / 'runs' / JOB / 'manifest.json').read_text())['mapping_candidate']

    result = migration.apply(migration.plan(workspace, project_root=project), workspace, project_root=project)

    assert result['verification'] == []
    job = Store(workspace / 'jobs.sqlite3').get(JOB)['mapping_snapshot']
    manifest = json.loads((workspace / 'runs' / JOB / 'manifest.json').read_text())['mapping_candidate']
    for document, original in ((job, job_before), (manifest, manifest_before)):
        assert document['molecule_snapshot'] == {'molecule_id': 'Fixture', 'version': 'v1'}
        assert {key: value for key, value in document.items() if key != 'molecule_snapshot'} == \
               {key: value for key, value in original.items() if key != 'molecule_snapshot'}, \
               'the migration renames the molecule, never the mapping'
        draft_model.load(document, molecule_root=project / 'molecules')


def test_a_run_whose_stamps_are_current_still_gets_its_snapshot_named(tmp_path, monkeypatch):
    """The live shape: a run restamped by the first half of this migration still embeds the digest snapshot, so the
    two rewrites are planned independently and one apply carries both."""
    project, workspace, draft, _slug, _old = world(tmp_path, monkeypatch)
    named = {**draft, 'molecule_snapshot': {'molecule_id': 'Fixture', 'version': 'v1'}}
    files.atomic_json(workspace / 'mapping_drafts' / DRAFT_FILE, named)
    wanted = {'mapping_hash': identity.candidate_identity(named),
              'mapping_content_hash': identity.content_identity(named)}
    rewrite_job(workspace, lambda job: job['parameterization'].update(wanted))
    path = workspace / 'runs' / JOB / 'manifest.json'
    manifest = json.loads(path.read_text())
    manifest['parameterization'].update(wanted)
    files.atomic_json(path, manifest)

    entries = migration.plan(workspace, project_root=project)
    result = migration.apply(entries, workspace, project_root=project)

    assert [entry['status'] for entry in entries['jobs']] == ['write']
    assert [entry['status'] for entry in entries['manifests']] == ['write']
    assert result['verification'] == []
    job = Store(workspace / 'jobs.sqlite3').get(JOB)
    assert job['mapping_snapshot']['molecule_snapshot'] == {'molecule_id': 'Fixture', 'version': 'v1'}
    assert job['parameterization']['mapping_hash'] == wanted['mapping_hash']


def test_a_run_without_a_parameterization_block_is_still_migrated(tmp_path, monkeypatch):
    project, workspace, _draft, _slug, _old = world(tmp_path, monkeypatch)
    rewrite_job(workspace, lambda job: job.pop('parameterization'))
    path = workspace / 'runs' / JOB / 'manifest.json'
    manifest = json.loads(path.read_text())
    manifest.pop('parameterization')
    files.atomic_json(path, manifest)

    entries = migration.plan(workspace, project_root=project)
    result = migration.apply(entries, workspace, project_root=project)

    assert [entry['status'] for entry in entries['jobs']] == ['write']
    assert [entry['status'] for entry in entries['manifests']] == ['write']
    assert result['verification'] == []
    assert 'parameterization' not in Store(workspace / 'jobs.sqlite3').get(JOB)
    assert 'parameterization' not in json.loads(path.read_text())
    assert json.loads(path.read_text())['mapping_candidate']['molecule_snapshot'] == {
        'molecule_id': 'Fixture', 'version': 'v1'}


def test_a_run_whose_rewritten_mapping_cannot_load_is_left_alone(tmp_path, monkeypatch):
    """The reader a Retry or Clone calls is the proof: a document it refuses is reported, and nothing of that run is
    written, not even the identity stamps the same row carries."""
    project, workspace, _draft, _slug, _old = world(tmp_path, monkeypatch)

    def unloadable(document):
        document['beads'][0]['type'] = 'ZZ1'

    rewrite_job(workspace, lambda job: unloadable(job['mapping_snapshot']))
    path = workspace / 'runs' / JOB / 'manifest.json'
    manifest = json.loads(path.read_text())
    unloadable(manifest['mapping_candidate'])
    files.atomic_json(path, manifest)
    rows_before = [(row['text'], row['revision']) for row in migration._job_rows(workspace)]
    manifest_before = path.read_text()

    entries = migration.plan(workspace, project_root=project)
    result = migration.apply(entries, workspace, project_root=project)

    assert [entry['status'] for entry in entries['jobs']] == ['blocked']
    assert [entry['status'] for entry in entries['manifests']] == ['blocked']
    assert 'the rewritten mapping cannot load' in entries['jobs'][0]['reason']
    assert result['written']['jobs'] == [] and result['written']['manifests'] == []
    assert [(row['text'], row['revision']) for row in migration._job_rows(workspace)] == rows_before
    assert path.read_text() == manifest_before


def test_the_dry_run_names_every_row_and_manifest_it_will_write(tmp_path, monkeypatch, capsys):
    project, workspace, _draft, _slug, _old = world(tmp_path, monkeypatch)
    before = snapshot(workspace)

    code = migration.main(['--workspace', str(workspace), '--project-root', str(project)])

    printed = [line for line in capsys.readouterr().out.splitlines() if 'write' in line]
    assert code == 0
    assert snapshot(workspace) == before, 'a dry run is a report'
    assert any(line.startswith('  jobs') and JOB in line for line in printed)
    assert any(line.startswith('  manifests') and JOB in line for line in printed)
    assert any('snapshot -> mapping_snapshot=Fixture/v1' in line for line in printed)


def test_a_record_stamped_with_another_models_identity_is_refused(tmp_path, monkeypatch):
    """A name is one model, but a hand-written or copied record can still claim another content. Rewriting its stamps
    would make that other model read as this one, so it is reported and left alone."""
    project, workspace, _draft, slug, _old = world(tmp_path, monkeypatch)
    path = workspace / 'parameterizations' / 'records' / f'{slug}.json'
    record = json.loads(path.read_text())
    record['mapping_content_hash'] = 'f' * 64
    files.atomic_json(path, record)

    entries = migration.plan(workspace, project_root=project)
    migration.apply(entries, workspace, project_root=project)

    blocked = [entry for entry in entries['records'] if entry['record'] == slug]
    assert blocked and 'belongs to another model' in blocked[0]['reason']
    assert json.loads(path.read_text())['mapping_content_hash'] == 'f' * 64


def test_a_second_apply_writes_nothing(tmp_path, monkeypatch):
    project, workspace, _draft, _slug, _old = world(tmp_path, monkeypatch)
    migration.apply(migration.plan(workspace, project_root=project), workspace, project_root=project)
    before = snapshot(workspace)
    ledger_before = (workspace / migration.BACKUP_DIRECTORY / migration.RECORDS_NAME).read_text()

    entries = migration.plan(workspace, project_root=project)
    result = migration.apply(entries, workspace, project_root=project)

    assert [entry['status'] for entry in entries['drafts']] == ['unchanged']
    assert [entry['status'] for entry in entries['records']] == ['unchanged', 'blocked']
    assert [entry['status'] for entry in entries['jobs']] == ['unchanged']
    assert [entry['status'] for entry in entries['manifests']] == ['unchanged']
    assert result['written'] == {'drafts': [], 'records': [], 'jobs': [], 'manifests': []}
    assert snapshot(workspace) == before
    assert (workspace / migration.BACKUP_DIRECTORY / migration.RECORDS_NAME).read_text() == ledger_before


def test_rollback_restores_every_original(tmp_path, monkeypatch):
    project, workspace, _draft, _slug, _old = world(tmp_path, monkeypatch)
    before = snapshot(workspace)
    rows = {row['data']['id']: (row['text'], row['revision']) for row in migration._job_rows(workspace)}
    migration.apply(migration.plan(workspace, project_root=project), workspace, project_root=project)

    migration.rollback(workspace, project_root=project)

    assert snapshot(workspace) == before
    assert {row['data']['id']: (row['text'], row['revision'])
            for row in migration._job_rows(workspace)} == rows


def test_an_unversioned_molecule_folder_blocks_the_draft_rather_than_a_guessed_version(tmp_path, monkeypatch):
    project, workspace, draft, _slug, _old = world(tmp_path, monkeypatch)
    folder = project / 'molecules' / 'Fixture'
    shutil.move(str(folder / 'v1'), str(folder.parent / 'Flat'))
    # The draft cannot even be built from an unversioned folder now, so it is the moved draft a stale store holds.
    unversioned = {**draft, 'molecule_id': 'Flat', 'molecule_snapshot': dict(DIGEST_SNAPSHOT)}
    files.atomic_json(workspace / 'mapping_drafts' / DRAFT_FILE, unversioned)
    before = snapshot(workspace)

    entries = migration.plan(workspace, project_root=project)
    result = migration.apply(entries, workspace, project_root=project)

    blocked = [entry for entry in entries['drafts'] if entry['status'] == 'blocked']
    assert blocked and 'no version directory' in blocked[0]['reason']
    assert result['written']['drafts'] == []
    assert snapshot(workspace) == before, 'a blocked draft is left exactly as it was'
    assert not (workspace / migration.BACKUP_DIRECTORY).exists()
