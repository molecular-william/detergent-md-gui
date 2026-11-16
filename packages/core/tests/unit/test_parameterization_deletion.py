"""Deleting a mapping takes its parameterization with it, by the name the record carries.

The owner's rule is one sentence: "when a CG mapping is deleted, all its corresponding bond interactions are also
deleted." A record is now addressed by the mapping's name, so deleting the mapping removes what that name addresses:
its record, its revisions, its fit jobs and the working directories those fits built. A record written before names
were addresses has no name of its own; it still goes when the deleted draft is the last one carrying its content, which
is the old holder question asked for the legacy shape only.

Nothing here reads a developer's workspace: the drafts land in a root this test owns and the parameterization in the
isolated workspace the `dashboard` fixture selects.
"""
import json

import pytest
from dashboard.models.bonded import parameterization
from dashboard.models.mappings import store as candidate_store

from tests.harness.support import parameterization_mapping as mapping
from tests.harness.support import parameterization_revision as revision


@pytest.fixture
def drafts(tmp_path, monkeypatch):
    """A drafts root this test owns, so the store's listing never reaches the real one."""
    root = tmp_path / 'drafts'
    root.mkdir()
    monkeypatch.setattr(candidate_store, 'storage_root', lambda: root)
    return root


def save_draft(root, stem, **fields):
    """A saved draft with the fields the content identity hashes; returns its file name."""
    payload = mapping(name=stem)
    payload.update(fields)
    name = f'mapping_candidate_{stem}.json'
    (root / name).write_text(json.dumps(payload))
    return name


def add_job(content_hash, job_id='a' * 16):
    """A fit job's record and log, under the root the job store shares with the revisions."""
    jobs = parameterization.storage_root() / 'jobs'
    jobs.mkdir(parents=True, exist_ok=True)
    (jobs / f'{job_id}.json').write_text(json.dumps({'id': job_id, 'mapping_content_hash': content_hash}))
    (jobs / f'{job_id}.log').write_text('fit log')
    return jobs


def test_deleting_the_mapping_removes_its_record_every_revision_jobs_and_work(drafts):
    """The rule itself: the mapping's name is the record's address, so the record goes with the mapping."""
    candidate = mapping(name='solo')
    parameterization.save(candidate, revision())
    parameterization.save(candidate, revision(engine='bartender'))
    content = parameterization.content_identity(candidate)
    name = save_draft(drafts, 'solo')
    assert parameterization.one('solo')['revision'] == 2, 'the draft and the record name the same model'

    jobs = add_job(content)
    add_job('c' * 64, job_id='b' * 16)
    work = parameterization.work_root() / f'solo--{"a" * 12}'
    work.mkdir(parents=True)
    (work / 'mapped.gro').write_text('trajectory')

    result = candidate_store.delete_draft(name)

    assert result['deleted'] == name
    removed = result['parameterization']
    assert removed['name'] == 'solo'
    assert removed['content_hash'] == content
    assert removed['deleted'] is True
    assert removed['retained_by'] == []
    assert removed['revisions'] == [1, 2]
    assert removed['jobs'] == ['a' * 16]
    assert not (parameterization.records_root() / 'solo.json').exists()
    assert parameterization.one('solo')['revisions'] == []
    assert parameterization.current(candidate) is None
    assert not (jobs / f'{"a" * 16}.json').exists()
    assert not (jobs / f'{"a" * 16}.log').exists()
    assert not work.exists()
    # Another mapping's job is not collateral damage of this deletion.
    assert (jobs / f'{"b" * 16}.json').exists()


def test_a_legacy_work_directory_is_removed_with_its_mapping_too(drafts):
    """A pair fitted before names were addresses worked in `<content hash>-<run>`; it goes with the mapping."""
    candidate = mapping(name='solo')
    parameterization.save(candidate, revision())
    content = parameterization.content_identity(candidate)
    work = parameterization.work_root() / f'{content}-{"b" * 12}'
    work.mkdir(parents=True)

    removed = candidate_store.delete_draft(save_draft(drafts, 'solo'))

    assert removed['parameterization']['work'] == [work.name]
    assert not work.exists()


def test_deleting_a_name_that_a_different_model_holds_keeps_that_record(drafts):
    """A name answers one model; deleting a draft that happens to share content is not that model's deletion."""
    candidate = mapping(name='first')
    parameterization.save(candidate, revision())
    second = save_draft(drafts, 'second', beads=candidate['beads'])

    result = candidate_store.delete_draft(second)

    kept = result['parameterization']
    assert kept['deleted'] is False
    assert 'name' in kept['reason']
    assert (parameterization.records_root() / 'first.json').exists()
    assert parameterization.one('first')['revision'] == 1


def test_a_legacy_record_no_name_answers_is_removed_with_the_last_holder(drafts):
    """The old shape is still deleted the old way: its hash record goes when no draft carries its content."""
    candidate = mapping()
    content = parameterization.content_identity(candidate)
    legacy = {**parameterization.identities(candidate), 'revision': 1,
              'current': {'revision': 1}, 'revisions': [{'revision': 1}]}
    path = parameterization.records_root() / f'{content}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(legacy))

    result = candidate_store.delete_draft(save_draft(drafts, 'solo', beads=candidate['beads']))

    assert result['parameterization']['deleted'] is True
    assert result['parameterization']['revisions'] == [1]
    assert not path.exists()


def test_deleting_a_parameterization_that_is_not_there_is_not_an_error():
    """Idempotent: an address with no record answers what it removed, which is nothing."""
    empty = parameterization.delete('d' * 64)
    assert empty['name'] == 'd' * 64 and empty['deleted'] is False and empty['revisions'] == []

    candidate = mapping()
    parameterization.save(candidate, revision())
    assert parameterization.delete('DDM')['revisions'] == [1]
    again = parameterization.delete('DDM')
    assert again['deleted'] is False
    assert again['revisions'] == []


def test_a_deletion_address_that_is_not_a_record_name_is_refused():
    """The validator every reader already uses is the door here too, rather than a glob."""
    with pytest.raises(ValueError):
        parameterization.delete('../../records')
    with pytest.raises(ValueError):
        parameterization.delete(None)


def test_a_draft_that_cannot_be_read_is_still_deleted_but_claims_no_parameterization(drafts):
    """A corrupt draft has no name, so there is nothing to address: delete the file only."""
    name = 'mapping_candidate_broken.json'
    (drafts / name).write_text('not json')

    result = candidate_store.delete_draft(name)

    assert result['deleted'] == name
    assert result['parameterization']['deleted'] is False
    assert result['parameterization']['content_hash'] is None
    assert not (drafts / name).exists()
