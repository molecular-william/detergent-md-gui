"""What a parameterization belongs to now: the one mapping whose name it carries.

A record used to be addressed by the mapping's content identity, and a claim list (`owners`) said which saved
mappings that content belonged to. The name is the address now: `records/<slug>.json`, one record per mapping, and
the content identities are provenance a run compares rather than a key that selects a file. So a save stamps no
claims, and two names are two records even when their assignments are identical bytes.

The old shape is still read. A record written before names were addresses is answered by its content hash, its own
claim list still says which names it belonged to, and `release` still drops one claim -- which is the deletion
fallback for a record the migration has not moved. Nothing writes a claim now.
"""
import json

import pytest
from dashboard.models import mappings
from dashboard.models.bonded import parameterization

from tests.harness.support import parameterization_mapping as mapping
from tests.harness.support import parameterization_revision as revision


def record_file(candidate):
    return parameterization.records_root() / f'{parameterization.address(candidate)}.json'


def write_legacy(candidate, **fields):
    """A pre-name record: hash-addressed, carrying its own identities and claim list."""
    content = parameterization.content_identity(candidate)
    record = {**parameterization.identities(candidate), 'revision': 1, 'current': {'revision': 1},
              'revisions': [{'revision': 1}], **fields}
    path = parameterization.records_root() / f'{content}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record))
    return path, content


def test_a_save_writes_the_mappings_name_and_no_claim_list():
    """The name is the answer to "whose revisions are these", so the claim list is not written."""
    candidate = mapping()
    parameterization.save(candidate, revision())

    record = parameterization.document(candidate)

    assert record['name'] == 'DDM' and record_file(candidate).is_file()
    assert parameterization.owners(record) == [], record['owners']


def test_two_names_are_two_records_and_each_keeps_its_own_revisions():
    """One record per mapping: identical assignments under two names are two models here."""
    first = mapping()
    second = mapping(name='DDM copy')
    parameterization.save(first, revision())
    parameterization.save(second, revision(engine='bartender'))

    assert parameterization.current(first)['engine'] == 'fast-forward'
    assert parameterization.current(second)['engine'] == 'bartender'
    assert {entry['name'] for entry in parameterization.records()} == {'DDM', 'DDM-copy'}
    assert mappings.content_identity(first) == mappings.content_identity(second), \
        'the assignments are one content, and the two names are still two records'


def test_a_name_another_model_holds_is_refused_and_can_be_overwritten_explicitly():
    """A fit under a name that is another model's answers with that name; overwriting is a caller's decision."""
    first = mapping()
    parameterization.save(first, revision())
    changed = json.loads(json.dumps(first))
    changed['beads'][0]['name'] = 'B99'

    with pytest.raises(parameterization.NameConflict) as refusal:
        parameterization.save(changed, revision())
    assert refusal.value.existing == 'DDM'
    assert parameterization.current(first)['revision'] == 1, 'the refused save wrote nothing'

    stored = parameterization.save(changed, revision(), overwrite=True)
    assert stored['revision'] == 1, 'an overwrite replaces the record rather than appending to it'
    assert parameterization.document(changed)['revisions'][0]['mapping_content_hash'] == \
        parameterization.identities(changed)['mapping_content_hash']
    # The record now carries the overwriting model's identity, so the replaced model does not read it.
    with pytest.raises(ValueError, match='belongs to another mapping'):
        parameterization.document(first)


def test_a_legacy_record_with_claims_is_read_by_its_hash_and_by_a_claimed_name():
    """A pre-name record keeps working: its hash answers it, and its claim list names it."""
    candidate = mapping()
    path, content = write_legacy(
        candidate, owners=[{'mapping_hash': mappings.candidate_identity(candidate), 'name': 'DDM'}])

    assert parameterization.one(content)['revision'] == 1
    assert parameterization.one('DDM')['revision'] == 1, 'the claim list still names it before the migration'
    assert parameterization.current(candidate)['revision'] == 1
    assert [entry['name'] for entry in parameterization.owners(parameterization.one(content))] == ['DDM']


def test_releasing_one_claim_from_a_legacy_record_keeps_the_revisions_for_the_other():
    """`release` is the legacy record's deletion half: the revisions go with the last claim, not before."""
    candidate = mapping()
    path, content = write_legacy(
        candidate, owners=[{'mapping_hash': 'a' * 64, 'name': 'DDM'},
                           {'mapping_hash': 'b' * 64, 'name': 'DDM copy'}])

    outcome = parameterization.release(content, name='DDM')
    assert outcome['released'] is True and outcome['deleted'] is False, outcome
    assert outcome['owners'] == ['DDM copy']
    assert path.is_file()

    outcome = parameterization.release(content, name='DDM copy')
    assert outcome['deleted'] is True and outcome['revisions'] == [1]
    assert not path.exists()


def test_a_release_from_a_mapping_that_never_claimed_says_so():
    candidate = mapping()
    _, content = write_legacy(candidate, owners=[{'mapping_hash': 'a' * 64, 'name': 'DDM'}],
                              revisions=[], current=None)

    outcome = parameterization.release(content, mapping=mapping(name='never claimed this'))

    assert outcome == {'content_hash': content, 'deleted': False, 'released': False,
                       'why': 'this mapping had not claimed it'}


def test_a_legacy_record_with_no_claims_answers_why_rather_than_guessing():
    candidate = mapping()
    _, content = write_legacy(candidate)

    outcome = parameterization.release(content, name='DDM')

    assert outcome['released'] is False and outcome['deleted'] is False, outcome
    assert outcome['why'] == 'the record names no mapping'


def test_deleting_the_parameterization_by_name_removes_the_record():
    """The panel's own Delete removes the parameterization, not one mapping's claim on it."""
    parameterization.save(mapping(), revision())

    outcome = parameterization.delete('DDM')

    assert outcome['deleted'] is True and outcome['revisions'] == [1]
    assert outcome['name'] == 'DDM'
    assert parameterization.current(mapping()) is None
