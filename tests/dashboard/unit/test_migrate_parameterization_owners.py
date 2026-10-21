"""The ownership migration claims a record for the drafts that carry its content, and invents nothing."""
import json

import pytest

from dashboard.cli import migrate_parameterization_owners as migration
from dashboard.models import mappings
from dashboard.models.bonded import parameterization
from tests.dashboard.support import physical_mapping


@pytest.fixture
def record_without_owners(dashboard):
    """A record as it was written before claims existed: addressed by content, naming no mapping."""
    candidate = {**physical_mapping(), 'name': 'DDM'}
    saved = mappings.save_draft(candidate)
    content = parameterization.content_identity(candidate)
    path = parameterization.records_root() / f'{content}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'mapping_hash': None, 'mapping_content_hash': content,
                                'revision': 1, 'current': {'revision': 1}, 'revisions': [{'revision': 1}]}))
    return candidate, saved, content


def test_a_record_is_claimed_for_the_draft_that_carries_its_content(record_without_owners):
    candidate, saved, content = record_without_owners

    plan = migration.plan()
    assert [entry['status'] for entry in plan] == ['claim'], plan
    assert plan[0]['new'][0]['name'] == saved['name']

    migration.apply(plan)
    owners = parameterization.owners(parameterization.one(content))
    assert [entry['mapping_hash'] for entry in owners] == [mappings.candidate_identity({**candidate})]


def test_the_second_run_writes_nothing(record_without_owners):
    migration.apply(migration.plan())

    plan = migration.plan()

    assert [entry['status'] for entry in plan] == ['unchanged'], plan
    assert migration.apply(plan) == []


def test_a_record_no_draft_carries_is_reported_and_left_alone(tmp_path, dashboard):
    orphan = parameterization.records_root() / f'{"cd" * 32}.json'
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_text(json.dumps({'mapping_content_hash': 'cd' * 32, 'revision': 1,
                                  'current': {'revision': 1}, 'revisions': [{'revision': 1}]}))
    before = orphan.read_text()

    plan = migration.plan()

    assert [(entry['status'], entry['content_hash']) for entry in plan] == [('unclaimed', 'cd' * 32)], plan
    assert 'no saved draft' in plan[0]['why']
    migration.apply(plan)
    assert orphan.read_text() == before


def test_a_record_is_read_from_the_workspace_it_is_given(tmp_path, record_without_owners):
    """`--workspace` reads that workspace's store, not the selected one."""
    _, _, content = record_without_owners
    other = tmp_path / 'elsewhere'
    (other / 'parameterizations' / 'records').mkdir(parents=True)

    assert migration.plan(other) == []
