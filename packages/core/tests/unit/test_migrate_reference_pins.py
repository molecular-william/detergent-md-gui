"""Re-pinning stored parameterization revisions: the edition replaces the digest, atomically.

A revision written before the named identity carries `aa_reference.reference_sha256`, which `references.resolve` no
longer accepts as a pin. The migration reads the referenced run's own published edition (never a guess), rewrites
both the revision and the record's `current` copy, keeps the run id and the fit's provenance, and refuses the whole
run when any referenced run publishes no edition -- a half-migrated store would leave some runs on a pin no reader
can check.
"""
import json

import pytest
from dashboard import files
from dashboard.analysis.runs import references
from dashboard.cli import migrate_reference_pins as migration

RUN = 'abc123def456'
EDITION = 1
DIGEST = 'ab' * 32


@pytest.fixture
def world(tmp_path):
    """One completed AA reference that publishes edition 1, and one record whose revision carries a digest."""
    run = tmp_path / 'runs' / RUN
    (run / 'stages/07_reference').mkdir(parents=True)
    files.atomic_json(run / 'manifest.json',
                      {'id': RUN, 'run_type': 'aa_only', 'status': 'completed', 'stages': []})
    for name in ('lig.gro', 'lig.xtc'):
        (run / 'stages/07_reference' / name).write_text(name)
    files.atomic_json(run / 'stages/07_reference/reference.json', {
        'schema_version': 2, 'edition': EDITION, 'reference_eligible': True,
        'sha256': {'stages/07_reference/lig.gro': files.sha256(run / 'stages/07_reference/lig.gro')},
    })
    revision = {'revision': 1, 'engine': 'fast-forward',
                'aa_reference': {'run_id': RUN, 'reference_sha256': DIGEST,
                                 'molecule_identity': 'cd' * 32, 'temperature_k': 300.0,
                                 'production_ns': 200.0}}
    record = {'name': 'Glucose-0', 'revision': 1, 'current': json.loads(json.dumps(revision)),
              'revisions': [revision], 'owners': []}
    records = tmp_path / 'parameterizations/records'
    records.mkdir(parents=True)
    files.atomic_json(records / 'Glucose-0.json', record)
    return tmp_path, record


def record_of(workspace):
    return json.loads((workspace / 'parameterizations/records/Glucose-0.json').read_text())


def test_a_dry_run_reports_the_revision_and_writes_nothing(world):
    workspace, original = world

    entries = migration.plan(workspace)

    assert [entry['status'] for entry in entries] == ['write']
    assert entries[0]['changes'] == [{'revision': 1, 'run': RUN, 'edition': EDITION}]
    assert record_of(workspace) == original
    assert not (workspace / migration.BACKUP).exists()


def test_apply_pins_the_edition_in_the_revision_and_its_current_copy(world):
    workspace, original = world

    migration.apply(migration.plan(workspace), workspace)
    migrated = record_of(workspace)

    for revision in (migrated['revisions'][0], migrated['current']):
        reference = revision['aa_reference']
        assert reference['reference_edition'] == EDITION
        assert 'reference_sha256' not in reference
        assert reference['run_id'] == RUN
        assert reference['temperature_k'] == 300.0 and reference['production_ns'] == 200.0
        assert reference['molecule_identity'] == 'cd' * 32, 'the fit provenance stays'
    ledger = json.loads((workspace / migration.BACKUP).read_text())
    assert ledger['records']['Glucose-0']['original'] == original
    assert references.resolve(workspace / 'runs', RUN, expected={'edition': EDITION})[1]['edition'] == EDITION
    # A second pass has nothing to do, and writes nothing.
    assert [entry['status'] for entry in migration.plan(workspace)] == ['unchanged']
    assert migration.apply(migration.plan(workspace), workspace) == []


def test_a_reference_without_an_edition_refuses_and_writes_nothing(world):
    workspace, original = world
    path = workspace / 'runs' / RUN / 'stages/07_reference/reference.json'
    record = json.loads(path.read_text())
    record.pop('edition')
    files.atomic_json(path, record)

    entries = migration.plan(workspace)

    assert entries[0]['status'] == 'refused' and 'no edition' in entries[0]['reason']
    with pytest.raises(ValueError, match='writes nothing'):
        migration.apply(entries, workspace)
    assert record_of(workspace) == original and not (workspace / migration.BACKUP).exists()


def test_one_blocked_reference_writes_nothing_for_any_record(world):
    workspace, original = world
    records = workspace / 'parameterizations/records'
    blocked = {'name': 'Blocked', 'revision': 1, 'current': None,
               'revisions': [{'revision': 1,
                              'aa_reference': {'run_id': 'ffffffffffff', 'reference_sha256': DIGEST}}]}
    files.atomic_json(records / 'Blocked.json', blocked)

    entries = migration.plan(workspace)

    assert {entry['record']: entry['status'] for entry in entries} == {'Blocked': 'refused', 'Glucose-0': 'write'}
    with pytest.raises(ValueError, match='writes nothing'):
        migration.apply(entries, workspace)
    assert record_of(workspace) == original and not (workspace / migration.BACKUP).exists()


def test_a_revision_with_no_pin_at_all_is_refused(world):
    workspace, _ = world
    path = workspace / 'parameterizations/records/Glucose-0.json'
    record = json.loads(path.read_text())
    for revision in (record['revisions'][0], record['current']):
        revision['aa_reference'].pop('reference_sha256')
    files.atomic_json(path, record)

    entries = migration.plan(workspace)

    assert entries[0]['status'] == 'refused' and 'no edition' in entries[0]['reason']


def test_an_already_pinned_revision_is_left_alone(world):
    workspace, _ = world
    path = workspace / 'parameterizations/records/Glucose-0.json'
    record = json.loads(path.read_text())
    for revision in (record['revisions'][0], record['current']):
        revision['aa_reference'].pop('reference_sha256')
        revision['aa_reference']['reference_edition'] = EDITION
    files.atomic_json(path, record)

    entries = migration.plan(workspace)

    assert [entry['status'] for entry in entries] == ['unchanged']


def test_rollback_restores_the_original_record(world):
    workspace, original = world
    migration.apply(migration.plan(workspace), workspace)
    assert record_of(workspace) != original

    assert migration.rollback(workspace) == 1

    assert record_of(workspace) == original
    assert [entry['status'] for entry in migration.plan(workspace)] == ['write']
    assert migration.rollback(workspace / 'absent-workspace') is None


def test_main_is_a_dry_run_until_apply(world):
    workspace, original = world

    assert migration.main(['--workspace', str(workspace)]) == 0
    assert record_of(workspace) == original and not (workspace / migration.BACKUP).exists()
    assert migration.main(['--workspace', str(workspace), '--apply']) == 0
    assert record_of(workspace)['revisions'][0]['aa_reference']['reference_edition'] == EDITION
    assert migration.main(['--workspace', str(workspace), '--rollback']) == 0
    assert record_of(workspace) == original
