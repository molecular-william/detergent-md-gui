"""Deleting a mapping takes its parameterization with it, unless another mapping still carries it.

The owner's rule is one sentence: "when a CG mapping is deleted, all its corresponding bond
interactions are also deleted." The difficulty is that the two stores are keyed differently: a draft
is addressed by its file name, and its parameterization by the mapping's *content* identity, which
ignores the name so that a rename keeps its fitted revisions. A copy of a draft saved under another
name therefore carries the same content hash and the same revisions, and deleting one of the two must
not take the other's bond interactions with it.

So the rule these tests hold is: delete the parameterization when no remaining mapping carries that
content hash, and keep it -- naming the holder -- when one does.

Nothing here reads a developer's workspace: the drafts land in a root this test owns and the
parameterization in the isolated workspace the `isolated_workspace` fixture selects.
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


def test_deleting_the_last_holder_removes_its_record_every_revision_and_its_jobs(drafts):
    """The rule itself: no mapping carries this content any more, so nothing under it survives."""
    candidate = mapping()
    parameterization.save(candidate, revision())
    parameterization.save(candidate, revision(engine='bartender'))
    content = parameterization.content_identity(candidate)
    name = save_draft(drafts, 'solo', beads=candidate['beads'])

    jobs = add_job(content)
    add_job('c' * 64, job_id='b' * 16)
    work = parameterization.work_root() / f'{content}-{"a" * 12}'
    work.mkdir(parents=True)
    (work / 'mapped.gro').write_text('trajectory')

    result = candidate_store.delete_draft(name)

    assert result['deleted'] == name
    removed = result['parameterization']
    assert removed['content_hash'] == content
    assert removed['deleted'] is True
    assert removed['retained_by'] == []
    assert removed['revisions'] == [1, 2]
    assert removed['jobs'] == ['a' * 16]
    assert not (parameterization.records_root() / f'{content}.json').exists()
    assert parameterization.one(content)['revisions'] == []
    assert parameterization.current(candidate) is None
    assert not (jobs / f'{"a" * 16}.json').exists()
    assert not (jobs / f'{"a" * 16}.log').exists()
    assert not work.exists()
    # Another mapping's job is not collateral damage of this deletion.
    assert (jobs / f'{"b" * 16}.json').exists()


def test_deleting_one_of_two_drafts_holding_the_same_content_keeps_the_other_s_revisions(drafts):
    """A copy saved under another name shares one content hash, so one deletion cannot empty it."""
    candidate = mapping()
    parameterization.save(candidate, revision())
    content = parameterization.content_identity(candidate)
    first = save_draft(drafts, 'first', beads=candidate['beads'])
    second = save_draft(drafts, 'second', beads=candidate['beads'])

    result = candidate_store.delete_draft(first)

    kept = result['parameterization']
    assert kept['content_hash'] == content
    assert kept['deleted'] is False
    assert kept['retained_by'] == [second]
    assert 'another saved mapping' in kept['reason']
    assert kept['revisions'] == []
    # The record is untouched, and the surviving draft still reads its revisions by content hash.
    assert (parameterization.records_root() / f'{content}.json').exists()
    assert [item['revision'] for item in parameterization.document(candidate)['revisions']] == [1]
    assert parameterization.one(content)['current']['engine'] == 'fast-forward'

    # The last holder going is the case the rule exists for, and then it does remove the record.
    last = candidate_store.delete_draft(second)
    assert last['parameterization']['deleted'] is True
    assert parameterization.one(content)['revisions'] == []


def test_deleting_a_parameterization_that_is_not_there_is_not_an_error():
    """Idempotent: a hash with no record answers what it removed, which is nothing."""
    content = 'd' * 64
    empty = parameterization.delete(content)
    assert empty == {'content_hash': content, 'deleted': False, 'revisions': [], 'jobs': [], 'work': [],
                     'distributions': None}

    candidate = mapping()
    parameterization.save(candidate, revision())
    content = parameterization.content_identity(candidate)
    assert parameterization.delete(content)['revisions'] == [1]
    again = parameterization.delete(content)
    assert again['deleted'] is False
    assert again['revisions'] == []


def test_a_deletion_address_that_is_not_a_content_hash_is_refused():
    """The validator every reader already uses is the door here too, rather than a glob."""
    with pytest.raises(ValueError):
        parameterization.delete('../../records')
    with pytest.raises(ValueError):
        parameterization.delete(None)


def test_a_draft_that_cannot_be_read_is_still_deleted_but_claims_no_parameterization(drafts):
    """A corrupt draft has no content identity, so there is nothing to address: delete the file only."""
    name = 'mapping_candidate_broken.json'
    (drafts / name).write_text('not json')

    result = candidate_store.delete_draft(name)

    assert result['deleted'] == name
    assert result['parameterization']['deleted'] is False
    assert result['parameterization']['content_hash'] is None
    assert not (drafts / name).exists()
