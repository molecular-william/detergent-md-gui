"""The molecule-version migration: dry run, apply, rollback, and the refusals that leave a folder alone.

Every fixture is a temporary molecule root with its own plain folders, built by flattening the versioned fixture
back into the retired shape. The live `molecules/` tree is never read or written.
"""
import json
import os

from dashboard import files
from dashboard.cli import migrate_molecule_versions as migration
from dashboard.models.molecules import aa

from tests.harness.support import write_aa_fixture


def plain(root, molecule_id='Fixture', *, metadata=True):
    """A legacy molecule folder: the versioned fixture's files directly under `<id>/`, no `v1/`."""
    versioned = write_aa_fixture(root, molecule_id)
    folder = versioned.parent
    for path in list(versioned.iterdir()):
        if path.name == 'metadata.json' and not metadata:
            path.unlink()
            continue
        os.rename(path, folder / path.name)
    versioned.rmdir()
    if metadata:
        record = json.loads((folder / 'metadata.json').read_text())
        record.pop('version', None)
        (folder / 'metadata.json').write_text(json.dumps(record))
    return folder


def snapshot(root):
    """Every molecule file under a root, by relative path and digest, so a rollback can be compared byte for byte."""
    return {path.relative_to(root).as_posix(): files.sha256(path)
            for path in sorted(root.rglob('*'))
            if path.is_file() and migration.BACKUP.parts[0] not in path.relative_to(root).parts}


def test_the_dry_run_lists_the_move_and_writes_nothing(tmp_path):
    root = tmp_path / 'molecules'
    folder = plain(root)
    before = snapshot(root)

    entries = migration.plan(root)

    assert [(entry['id'], entry['status']) for entry in entries] == [('Fixture', 'move')]
    assert entries[0]['entries'] == ['metadata.json', 'molecule.gro', 'molecule.itp']
    assert snapshot(root) == before, 'a dry run reads only'
    assert not (root / migration.BACKUP).exists()
    assert migration.main(['--root', str(root)]) == 0
    assert not (root / migration.BACKUP).exists()
    assert (folder / 'molecule.itp').is_file(), 'the command line defaults to a dry run'


def test_apply_moves_the_files_under_v1_and_stamps_the_version(tmp_path):
    root = tmp_path / 'molecules'
    folder = plain(root)
    before = json.loads((folder / 'metadata.json').read_text())

    done = migration.apply(migration.plan(root), root)

    assert [record['id'] for record in done] == ['Fixture']
    versioned = folder / 'v1'
    assert {path.name for path in folder.iterdir()} == {'v1'}
    assert {path.name for path in versioned.iterdir()} == {'metadata.json', 'molecule.gro', 'molecule.itp'}
    metadata = json.loads((versioned / 'metadata.json').read_text())
    assert metadata['version'] == 'v1'
    assert {key: value for key, value in metadata.items() if key != 'version'} == before, \
        'every other field is kept'
    record = aa.inspect(root, 'Fixture')
    assert record['version'] == 'v1' and record['valid']
    assert record['path'] == 'molecules/Fixture/v1'

    after, ledger = snapshot(root), (root / migration.BACKUP).stat().st_ino
    assert [entry['status'] for entry in migration.plan(root)] == ['unchanged']
    assert migration.apply(migration.plan(root), root) == []
    assert snapshot(root) == after
    assert (root / migration.BACKUP).stat().st_ino == ledger, 'a no-op apply rewrote the ledger'


def test_rollback_restores_the_unversioned_folder(tmp_path):
    root = tmp_path / 'molecules'
    plain(root, 'Fixture')
    plain(root, 'Other')
    before = snapshot(root)
    migration.apply(migration.plan(root), root)
    assert (root / 'Fixture' / 'v1' / 'metadata.json').is_file()

    assert migration.rollback(root) == 2

    assert snapshot(root) == before
    assert not (root / 'Fixture' / 'v1').exists()
    assert 'version' not in json.loads((root / 'Fixture' / 'metadata.json').read_text())


def test_a_folder_without_metadata_gets_the_catalogue_record(tmp_path):
    root = tmp_path / 'molecules'
    plain(root, metadata=False)

    migration.apply(migration.plan(root), root)

    metadata = json.loads((root / 'Fixture' / 'v1' / 'metadata.json').read_text())
    assert metadata['version'] == 'v1' and metadata['generated'] is True
    assert aa.inspect(root, 'Fixture')['valid']


def test_a_symlinked_folder_is_refused_and_left_alone(tmp_path):
    root = tmp_path / 'molecules'
    root.mkdir()
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    (root / 'Linked').symlink_to(elsewhere)

    entry = migration.plan(root)[0]

    assert entry['status'] == 'refused' and 'symbolic link' in entry['why']
    assert migration.apply(migration.plan(root), root) == []
    assert (root / 'Linked').is_symlink() and not (root / 'Linked' / 'v1').exists()


def test_a_collision_is_refused(tmp_path):
    root = tmp_path / 'molecules'
    folder = plain(root)
    (folder / 'v1').write_text('occupied')

    entry = migration.plan(root)[0]

    assert entry['status'] == 'refused' and 'v1 already exists' in entry['why']
    assert migration.apply(migration.plan(root), root) == []
    assert (folder / 'v1').is_file() and (folder / 'molecule.itp').is_file()


def test_rollback_refuses_when_an_entry_reappeared(tmp_path):
    root = tmp_path / 'molecules'
    folder = plain(root)
    migration.apply(migration.plan(root), root)
    (folder / 'molecule.itp').write_text('written after the migration')

    assert migration.rollback(root) is None
    assert (folder / 'v1' / 'molecule.itp').is_file(), 'a refused rollback moves nothing'
