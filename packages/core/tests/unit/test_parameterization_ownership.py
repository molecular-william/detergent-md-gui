"""What a parameterization belongs to now: the one mapping whose name it carries.

A record used to be addressed by the mapping's content identity, and a claim list (`owners`) said which saved
mappings that content belonged to. The name is the address now: `records/<slug>.json`, one record per mapping, and
the content identities are provenance a run compares rather than a key that selects a file. So a save stamps no
claims, and two names are two records even when their assignments are identical bytes.
"""
import json

import pytest
from dashboard.models import mappings
from dashboard.models.bonded import parameterization

from tests.harness.support import parameterization_mapping as mapping
from tests.harness.support import parameterization_revision as revision


def record_file(candidate):
    return parameterization.records_root() / f'{parameterization.address(candidate)}.json'


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


def test_deleting_the_parameterization_by_name_removes_the_record():
    """The panel's own Delete removes the parameterization, not one mapping's claim on it."""
    parameterization.save(mapping(), revision())

    outcome = parameterization.delete('DDM')

    assert outcome['deleted'] is True and outcome['revisions'] == [1]
    assert outcome['name'] == 'DDM'
    assert parameterization.current(mapping()) is None
