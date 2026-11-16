"""The migration from content-hash record names to the mapping's name: dry-run, move, stamp, report.

A legacy record is `records/<content_hash>.json` with a `<content_hash>.revisions/` directory beside it. The migration
resolves the name from the record's own claim list (and from the drafts carrying its content), moves both, stamps
`legacy_hash` so a run manifest that named the old address can still be traced, and rebases the revision records'
directories to where the files now live. It is idempotent and never deletes: a record two names claim, no name claims,
or a name that already holds a record is reported and left for a person.
"""
import json

import pytest
from dashboard.cli import migrate_named_parameterizations as migration
from dashboard.models import mappings
from dashboard.models.bonded import parameterization

from tests.harness.support import physical_mapping

CONTENT = 'ab' * 32


def write_record(root, content=CONTENT, owners=None, name=None, revisions=True):
    """One pre-name record, with its revision directory and a recorded baseline directory."""
    records = root / 'parameterizations' / 'records'
    records.mkdir(parents=True, exist_ok=True)
    if revisions:
        revision = records / f'{content}.revisions' / '1'
        revision.mkdir(parents=True, exist_ok=True)
        (revision / '1_B01_1_B02_distances_distr.dat').write_text('0.0 1.0\n')
    record = {'mapping_hash': 'a' * 64, 'mapping_content_hash': content, 'revision': 1,
              'current': {'revision': 1},
              'revisions': [{'revision': 1,
                             'distributions': {'directory': f'records/{content}.revisions/1',
                                               'files': []}}]}
    if owners:
        record['owners'] = [{'mapping_hash': 'b' * 64, 'name': name} for name in owners]
    path = records / f'{content}.json'
    path.write_text(json.dumps(record))
    return path


@pytest.fixture
def saved(dashboard):
    """A saved draft whose display name is the record's future record name."""
    return mappings.save_draft({**physical_mapping(), 'name': 'DDM'})


def test_a_claimed_record_moves_to_its_name_and_stamps_the_old_hash(dashboard, saved):
    path = write_record(dashboard.paths.workspace, owners=['DDM'])

    entries = migration.plan()

    assert [(entry['status'], entry['name']) for entry in entries] == [('move', 'DDM')], entries
    assert path.exists(), 'a dry run writes nothing'

    migration.apply(entries)

    records = parameterization.records_root()
    target = records / 'DDM.json'
    assert target.is_file() and not path.exists()
    record = json.loads(target.read_text())
    assert record['name'] == 'DDM' and record['legacy_hash'] == CONTENT
    assert record['revisions'][0]['distributions']['directory'] == 'records/DDM.revisions/1'
    assert (records / 'DDM.revisions' / '1' / '1_B01_1_B02_distances_distr.dat').is_file()
    assert not (records / f'{CONTENT}.revisions').exists()


def test_the_second_run_writes_nothing(dashboard, saved):
    write_record(dashboard.paths.workspace, owners=['DDM'])
    migration.apply(migration.plan())

    entries = migration.plan()

    assert [entry['status'] for entry in entries] == ['unchanged'], entries
    assert migration.apply(entries) == []


def test_a_record_two_names_claim_is_reported_and_left_alone(dashboard, saved):
    path = write_record(dashboard.paths.workspace, owners=['DDM', 'DDM copy'])
    before = path.read_text()

    entries = migration.plan()

    assert [(entry['status'], entry['names']) for entry in entries] == [
        ('ambiguous', ['DDM', 'DDM-copy'])], entries
    migration.apply(entries)
    assert path.read_text() == before


def test_a_record_no_name_claims_is_reported_and_left_alone(tmp_path, dashboard):
    path = write_record(dashboard.paths.workspace, content=CONTENT)
    before = path.read_text()

    entries = migration.plan()

    assert [(entry['status'], entry['content_hash']) for entry in entries] == [('unclaimed', CONTENT)], entries
    assert 'no saved draft' in entries[0]['why']
    migration.apply(entries)
    assert path.read_text() == before


def test_a_name_that_already_holds_a_record_is_a_conflict(dashboard, saved):
    write_record(dashboard.paths.workspace, owners=['DDM'])
    parameterization.save({**physical_mapping(), 'name': 'DDM'},
                          {'engine': 'fast-forward', 'topology': '[ moleculetype ]\nDDM 1\n\n[ atoms ]\n',
                           'options': {'constraints_threshold': 10000.0, 'temperature_k': 300.0,
                                       'torsion_model': 'legacy', 'torsion_scale': 1.0},
                           'ensemble': {'frames': 0}, 'checks': {}})

    entries = migration.plan()

    assert [entry['status'] for entry in entries] == ['unchanged', 'conflict'], entries
    conflicted = next(entry for entry in entries if entry['status'] == 'conflict')
    assert 'already answers this name' in conflicted['why']


def test_it_reads_the_workspace_it_is_given(tmp_path, dashboard):
    other = tmp_path / 'elsewhere'
    legacy = write_record(other, owners=['DDM'])
    drafts = other / 'mapping_drafts'
    drafts.mkdir(parents=True)
    (drafts / 'mapping_candidate_ddm.json').write_text(
        json.dumps({**physical_mapping(), 'name': 'DDM'}))

    entries = migration.plan(other)

    assert [(entry['status'], entry['name']) for entry in entries] == [('move', 'DDM')], entries
    assert legacy.exists() and not (other / 'parameterizations' / 'records' / 'DDM.json').exists()
    assert parameterization.records_root().parent != other / 'parameterizations', 'the live workspace is untouched'
