"""The candidate store owns its own layout.

Two routes stepped around it. The refinement reader built its own repository over the
reviews directory with `lambda value: value` as the record-id validator -- the store's own
validator there checks nothing but the shape of a name, and a permissive one replaced it.
The draft delete route carried a route-level regex and unlinked a path it built from the
storage root itself, so what may be deleted was decided in two places.

Both go through the store now: list_reviews() and delete_draft() are the only doors, and
they use the same validator and the same containment check as every other record.
"""
import json

import pytest

from dashboard.models.mappings import store as candidate_store


@pytest.fixture
def drafts(tmp_path, monkeypatch):
    monkeypatch.setattr(candidate_store, 'storage_root', lambda: tmp_path)
    return tmp_path


def test_a_hostile_draft_name_is_refused_by_the_store(drafts):
    (drafts / 'keep.json').write_text('keep')
    for name in ('../escape.json', 'a/b.json', '..', ''):
        with pytest.raises(ValueError):
            candidate_store.delete_draft(name)
    assert (drafts / 'keep.json').read_text() == 'keep'


def test_a_symbolic_link_is_not_deleted_through_the_store(drafts):
    """The repository refuses links; the route's own unlink did not consult it."""
    outside = drafts.parent / 'outside.json'
    outside.write_text('outside')
    (drafts / 'link.json').symlink_to(outside)
    with pytest.raises(ValueError):
        candidate_store.delete_draft('link.json')
    assert outside.read_text() == 'outside'


def test_delete_draft_removes_a_draft_inside_the_root(drafts):
    draft = drafts / 'mapping_candidate_x.json'
    draft.write_text('{}')
    result = candidate_store.delete_draft('mapping_candidate_x.json')
    assert result['deleted'] == 'mapping_candidate_x.json'
    # An empty draft carries no bond interactions, so nothing was there to remove.
    assert result['parameterization']['deleted'] is False
    assert not draft.exists()
    with pytest.raises(KeyError):
        candidate_store.delete_draft('mapping_candidate_x.json')


def test_reviews_are_read_through_the_store_validator(drafts):
    reviews = candidate_store.reviews_root()
    reviews.mkdir()
    (reviews / 'good-19.json').write_text(json.dumps({'candidate': 'a', 'state': 'draft'}))
    (reviews / 'with space.json').write_text('{}')
    (reviews / 'broken.json').write_text('not json')
    assert [record['candidate'] for record in candidate_store.list_reviews()] == ['a']


def test_no_reviews_directory_is_an_empty_list_not_an_error(drafts):
    assert candidate_store.list_reviews() == []
