"""The digest migration rewrites only what it can prove, and says so about the rest.

The property that matters: a record rewritten by this migration carries a digest that `files.json_sha256` reproduces
from its own body -- and a record whose stored digest is not its body's is left exactly as it was, because a migration
that guesses is worse than one that reports.
"""
import json

import pytest

from dashboard import files, paths
from dashboard.cli import migrate_digests as migration
from dashboard.store import Store

BODY = {'payload': {'protein': '1AT9', 'detergent': 'DDM'}, 'identity': 'composition-identity'}
FRAGMENT = {'name': 'a fragment', 'reference_ids': ['r1'], 'atoms': [1, 2, 3]}


def write(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record))


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / 'workspace'
    write(root / 'compositions' / 'cccc0000cccc0000.json',
          {'id': 'cccc0000cccc0000', 'kind': 'composition', 'snapshot': BODY,
           'snapshot_hash': migration.legacy_sha256(BODY)})
    write(root / 'model_registry' / 'fragments' / 'ffff0000ffff0000.json',
          {'id': 'ffff0000ffff0000', 'kind': 'fragment', 'snapshot_hash': migration.legacy_sha256(FRAGMENT),
           **FRAGMENT, 'created_at': '2026-10-01T00:00:00+00:00'})
    write(root / 'runs' / 'run000000001' / 'manifest.json',
          {'id': 'run000000001', 'composition_id': 'cccc0000cccc0000',
           'composition_snapshot_sha256': migration.legacy_sha256(BODY)})
    Store(paths.Paths(project_root=paths.DEFAULT.project_root, workspace=root).database).insert({'id': 'run000000002', 'composition_id': 'cccc0000cccc0000',
                                    'composition_snapshot_sha256': migration.legacy_sha256(BODY)})
    return root


def entries(plan, store=None):
    return [entry for entry in plan if store is None or entry['store'] == store]


def test_every_stored_digest_is_planned_for_a_rewrite(workspace):
    plan = migration.plan(workspace)

    assert migration.summary(plan) == {'rewrite': 4}, plan


def test_the_rewritten_digest_is_the_one_the_canonical_serializer_computes(workspace):
    migration.apply(migration.plan(workspace), workspace)

    composition = json.loads((workspace / 'compositions' / 'cccc0000cccc0000.json').read_text())
    fragment = json.loads((workspace / 'model_registry' / 'fragments' / 'ffff0000ffff0000.json').read_text())
    assert composition['snapshot_hash'] == files.json_sha256(BODY)
    assert fragment['snapshot_hash'] == files.json_sha256(FRAGMENT)


def test_a_copy_is_rewritten_to_the_composition_it_names(workspace):
    migration.apply(migration.plan(workspace), workspace)

    manifest = json.loads((workspace / 'runs' / 'run000000001' / 'manifest.json').read_text())
    job = Store(paths.Paths(project_root=paths.DEFAULT.project_root, workspace=workspace).database).get('run000000002')
    assert manifest['composition_snapshot_sha256'] == files.json_sha256(BODY)
    assert job['composition_snapshot_sha256'] == files.json_sha256(BODY)


def test_the_second_run_changes_nothing(workspace):
    migration.apply(migration.plan(workspace), workspace)
    plan = migration.plan(workspace)

    assert migration.summary(plan) == {'unchanged': 4}, plan
    assert migration.apply(plan, workspace) == []


def test_a_record_whose_digest_is_not_its_bodys_is_reported_and_left_alone(workspace):
    path = workspace / 'compositions' / 'dddd0000dddd0000.json'
    write(path, {'id': 'dddd0000dddd0000', 'snapshot': BODY, 'snapshot_hash': 'ab' * 32})
    before = path.read_text()

    plan = migration.plan(workspace)
    refused = [entry for entry in plan if entry['status'] == 'unreconstructible']

    assert [entry['id'] for entry in refused] == ['dddd0000dddd0000'], plan
    assert 'not this body' in refused[0]['why']
    migration.apply(plan, workspace)
    assert path.read_text() == before


def test_a_copy_of_a_composition_this_workspace_does_not_hold_is_unattributable(workspace):
    write(workspace / 'runs' / 'run000000003' / 'manifest.json',
          {'id': 'run000000003', 'composition_id': 'eeee0000eeee0000',
           'composition_snapshot_sha256': migration.legacy_sha256(BODY)})

    plan = migration.plan(workspace)
    orphans = [entry for entry in plan if entry['status'] == 'unattributable']

    assert [entry['id'] for entry in orphans] == ['run000000003'], plan
    assert migration.apply(plan, workspace) == [entry for entry in plan if entry['status'] == 'rewrite']
