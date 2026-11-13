"""Who a parameterization belongs to: the saved mappings that claimed its content, and what a delete means.

A record is addressed by the mapping's *content* identity, so two drafts that differ only in name address one record --
that is what makes a renamed candidate keep its revisions. Ownership is the separate question: which saved mappings the
content belongs to. It is recorded on the record, claimed at the first save, and released when a draft is deleted; the
revisions go with the last claim, and a record written before claims existed is answered as `why` so the caller can fall
back to asking the drafts on disk rather than guessing.
"""
import json

import pytest
from dashboard.models import mappings
from dashboard.models.bonded import parameterization

from tests.harness.support import parameterization_mapping as mapping
from tests.harness.support import parameterization_revision as revision


@pytest.fixture
def saved(dashboard):
    """One fitted model: a mapping with a revision and the claim the save made."""
    owner = mapping()
    parameterization.save(owner, revision())
    return owner


def test_a_save_claims_the_mapping_that_made_it(saved):
    record = parameterization.document(saved)

    assert [entry['name'] for entry in record['owners']] == ['DDM'], record['owners']
    assert record['owners'][0]['mapping_hash'] == mappings.candidate_identity(saved)


def test_a_second_claim_on_the_same_content_is_recorded_once(saved):
    twin = mapping(name='DDM copy')          # same beads, same content, another saved name
    parameterization.save(twin, revision())

    record = parameterization.document(saved)
    assert sorted(entry['name'] for entry in record['owners']) == ['DDM', 'DDM copy'], record['owners']
    assert mappings.content_identity(twin) == mappings.content_identity(saved)


def test_releasing_one_claim_keeps_the_revisions_for_the_other(saved):
    twin = mapping(name='DDM copy')
    parameterization.save(twin, revision())

    outcome = parameterization.release(parameterization.content_identity(saved), name='DDM')

    assert outcome['released'] is True and outcome['deleted'] is False, outcome
    assert outcome['owners'] == ['DDM copy']
    assert parameterization.current(twin) is not None


def test_the_last_claim_going_takes_the_revisions_with_it(saved):
    twin = mapping(name='DDM copy')
    parameterization.save(twin, revision())
    parameterization.release(parameterization.content_identity(saved), name='DDM')

    outcome = parameterization.release(parameterization.content_identity(saved), name='DDM copy')

    assert outcome['deleted'] is True, outcome
    assert outcome['revisions'] == [1, 2], outcome
    assert parameterization.current(twin) is None


def test_a_release_from_a_mapping_that_never_claimed_says_so(saved):
    stranger = mapping(name='never claimed this')

    outcome = parameterization.release(parameterization.content_identity(saved), mapping=stranger)

    assert outcome == {'content_hash': parameterization.content_identity(saved), 'deleted': False,
                       'released': False, 'why': 'this mapping had not claimed it'}


def test_a_record_written_before_claims_existed_answers_why_rather_than_guessing(saved):
    path = parameterization.records_root() / f'{parameterization.content_identity(saved)}.json'
    record = json.loads(path.read_text())
    record.pop('owners', None)
    path.write_text(json.dumps(record))

    outcome = parameterization.release(parameterization.content_identity(saved), name='DDM')

    assert outcome['released'] is False and outcome['deleted'] is False, outcome
    assert outcome['why'] == 'the record names no mapping'


def test_deleting_the_parameterization_outright_ignores_claims(saved):
    """The panel's own Delete removes the parameterization, not one mapping's claim on it."""
    parameterization.save(mapping(name='DDM copy'), revision())

    outcome = parameterization.delete(parameterization.content_identity(saved))

    assert outcome['deleted'] is True and outcome['revisions'] == [1, 2], outcome
    assert parameterization.current(saved) is None
