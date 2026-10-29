
import pytest
from dashboard.models.repository import JsonRepository


def repository(root):
    return JsonRepository(root, '{id}.json', lambda value: value if value.isalnum() else (_ for _ in ()).throw(ValueError('bad id')))


def test_write_get_and_stable_listing(tmp_path):
    repo = repository(tmp_path / 'records')
    repo.write('b2', {'name': 'b'})
    repo.write('a1', {'name': 'a'})
    assert repo.get('a1') == {'name': 'a'}
    assert repo.list() == [{'name': 'a'}, {'name': 'b'}]
    assert not list((tmp_path / 'records').glob('.*.tmp'))


def test_invalid_and_symlink_records_are_rejected(tmp_path):
    repo = repository(tmp_path / 'records')
    with pytest.raises(ValueError):
        repo.path('../escape')
    repo.write('a1', {'ok': True})
    outside = tmp_path / 'outside.json'
    outside.write_text('{}')
    (tmp_path / 'records' / 'b2.json').symlink_to(outside)
    with pytest.raises(ValueError):
        repo.list()
    assert repo.list(skip_invalid=True) == [{'ok': True}]


def test_symlink_root_is_rejected(tmp_path):
    target = tmp_path / 'target'
    target.mkdir()
    alias = tmp_path / 'alias'
    alias.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match='symbolic link'):
        repository(alias).list()


def test_a_name_the_validator_refuses_is_not_listed(tmp_path):
    """A file the writer could never have created is not a record: listing it would hand
    the caller an id nothing else in the store can address."""
    repo = repository(tmp_path / 'records')
    repo.write('a1', {'ok': True})
    (tmp_path / 'records' / 'with space.json').write_text('{"ghost": true}')
    with pytest.raises(ValueError):
        repo.list()
    assert repo.list(skip_invalid=True) == [{'ok': True}]
