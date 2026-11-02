"""Resolving a library: cache, rebuild, the two modes, and the CLI an operator drives.

A build spec may build, but a reference spec may not: its source runs may live in another workspace, so a missing or
changed copy is a refusal that names itself rather than a rebuild. These tests pin both, plus the cache that makes a
second prepare free and the CLI that prints the operator's record.
"""
import hashlib
import json
import shutil

import pytest
from detergent_pdc import conformations
from detergent_pdc.conformations import available, build, canonical_bytes, resolve
from detergent_pdc.conformations.__main__ import main

from tests.harness.conformation_fixtures import copy_libraries, run_tree

RUN = 'b920391735dd'
SPEC = {'runs': [RUN], 'size': 3, 'seed': 0}


def workspace_run(tmp_path):
    workspace = tmp_path / 'workspace'
    run_tree(workspace, RUN, molecules=4, frames=2)
    return workspace


def reissued(path, mutate):
    """Rewrite a stored library with one change and a matching sidecar; returns the file's new digest."""
    document = json.loads(path.read_text())
    mutate(document)
    payload = canonical_bytes(document)
    path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    (path.parent / 'library.sha256').write_text(digest + '\n')
    return digest


def test_a_build_spec_builds_when_the_store_is_empty(tmp_path):
    workspace = workspace_run(tmp_path)
    library = resolve(workspace, SPEC)
    assert library.path.is_file()
    assert library.path == conformations.store_dir(workspace, 'DDM', library.key) / 'library.json'
    assert [entry['key'] for entry in available(workspace)] == [library.key]
    assert library.document['sources'][0]['run_id'] == RUN
    assert library.document['pool'] == 8


def test_a_second_resolve_is_a_cache_hit(tmp_path, monkeypatch):
    workspace = workspace_run(tmp_path)
    library = resolve(workspace, SPEC)

    def refuse(*_args, **_kwargs):
        raise AssertionError('the cache hit must not rebuild')

    monkeypatch.setattr(conformations.extract, 'candidates', refuse)
    again = resolve(workspace, SPEC)
    assert again.key == library.key and again.sha256 == library.sha256


def test_a_corrupt_copy_is_rebuilt(tmp_path):
    workspace = workspace_run(tmp_path)
    library = resolve(workspace, SPEC)
    library.path.write_text('{}\n')
    again = resolve(workspace, SPEC)
    assert again.key == library.key
    assert json.loads(again.path.read_text())['entries']


def test_build_false_refuses_a_missing_library(tmp_path):
    workspace = workspace_run(tmp_path)
    with pytest.raises(ValueError) as error:
        resolve(workspace, SPEC, build=False)
    assert 'no library for these runs' in str(error.value)
    assert RUN in str(error.value)


def test_build_false_reuses_a_stored_library(tmp_path):
    workspace = workspace_run(tmp_path)
    library = resolve(workspace, SPEC)
    assert resolve(workspace, SPEC, build=False).key == library.key


def test_a_reference_needs_no_source_runs(tmp_path):
    source = workspace_run(tmp_path)
    library = resolve(source, SPEC)
    carried = tmp_path / 'other'
    copy_libraries(source, carried)
    assert not (carried / 'runs').exists()
    reference = {'key': library.key, 'sha256': library.sha256}
    assert resolve(carried, reference).key == library.key
    assert resolve(carried, reference).path.read_bytes() == library.path.read_bytes()


def test_a_reference_never_builds(tmp_path, monkeypatch):
    workspace = workspace_run(tmp_path)
    library = resolve(workspace, SPEC)
    shutil.rmtree(library.path.parent)

    def refuse(*_args, **_kwargs):
        raise AssertionError('a reference must not build')

    monkeypatch.setattr(conformations.extract, 'candidates', refuse)
    with pytest.raises(ValueError) as error:
        resolve(workspace, {'key': library.key, 'sha256': library.sha256})
    assert 'copy the original back' in str(error.value)
    assert library.key in str(error.value)


def test_a_reference_with_the_wrong_digest_is_refused(tmp_path):
    workspace = workspace_run(tmp_path)
    library = resolve(workspace, SPEC)
    with pytest.raises(ValueError) as error:
        resolve(workspace, {'key': library.key, 'sha256': '0' * 64})
    assert 'not the recorded' in str(error.value)


def test_a_reference_with_the_wrong_size_is_refused(tmp_path):
    workspace = workspace_run(tmp_path)
    library = resolve(workspace, SPEC)
    digest = reissued(library.path, lambda document: document['entries'].pop())
    with pytest.raises(ValueError) as error:
        resolve(workspace, {'key': library.key, 'sha256': digest})
    assert 'states 3 entries but holds 2' in str(error.value)


def test_a_reference_with_a_changed_signature_is_refused(tmp_path):
    workspace = workspace_run(tmp_path)
    library = resolve(workspace, SPEC)
    digest = reissued(library.path, lambda document: document['detergent'].update(beads=[]))
    with pytest.raises(ValueError) as error:
        resolve(workspace, {'key': library.key, 'sha256': digest})
    assert 'names no beads' in str(error.value)


def test_a_misfiled_copy_is_refused(tmp_path):
    workspace = workspace_run(tmp_path)
    library = resolve(workspace, SPEC)
    misfiled = conformations.store_dir(workspace, 'DDM', 'f' * 16)
    shutil.copytree(library.path.parent, misfiled)
    with pytest.raises(ValueError) as error:
        resolve(workspace, {'key': 'f' * 16, 'sha256': library.sha256})
    assert f'filed as {"f" * 16}' in str(error.value)
    assert library.key in str(error.value)


def test_a_library_from_two_runs_names_both(tmp_path):
    workspace = tmp_path / 'workspace'
    run_tree(workspace, 'one', molecules=2, frames=1)
    run_tree(workspace, 'two', molecules=2, frames=1)
    library = resolve(workspace, {'runs': ['one', 'two'], 'size': 2, 'seed': 0})
    assert [source['run_id'] for source in library.sources] == ['one', 'two']
    assert library.document['pool'] == 4
    assert {entry['source']['run'] for entry in library.entries} == {0}
    pooled = resolve(workspace, {'runs': ['one', 'two'], 'size': 4, 'seed': 0})
    assert {entry['source']['run'] for entry in pooled.entries} == {0, 1}


def test_a_pool_smaller_than_the_size_is_refused(tmp_path):
    workspace = workspace_run(tmp_path)
    with pytest.raises(ValueError) as error:
        resolve(workspace, {'runs': [RUN], 'size': 9, 'seed': 0})
    assert 'pool holds 8 molecules' in str(error.value)
    assert RUN in str(error.value)


def test_the_cli_builds_and_shows(tmp_path, capsys):
    workspace = workspace_run(tmp_path)
    assert main(['build', '--workspace', str(workspace), '--runs', RUN, '--size', '3', '--seed', '0']) == 0
    record = json.loads(capsys.readouterr().out)
    assert set(record) == {'key', 'path', 'sha256', 'size', 'pool', 'sources', 'kept', 'broken', 'non_finite',
                           'seconds', 'producer'}
    assert record['size'] == 3 and record['pool'] == 8 and record['kept'] == 8
    assert set(record['producer']) == {'numpy', 'mdanalysis'}

    assert main(['show', record['key'], '--workspace', str(workspace)]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary['key'] == record['key'] and summary['size'] == 3
    assert 'entries' not in summary
    assert summary['sources'][0]['run_id'] == RUN

    assert main(['show', record['path'], '--workspace', str(workspace)]) == 0
    assert json.loads(capsys.readouterr().out)['key'] == record['key']

    with pytest.raises(SystemExit):
        main(['build', '--workspace', str(workspace), '--runs', 'deleted', '--size', '3'])
    with pytest.raises(SystemExit):
        main(['show', 'not-a-key', '--workspace', str(workspace)])


def test_build_directly_refuses_a_reference_spec(tmp_path):
    workspace = workspace_run(tmp_path)
    library = resolve(workspace, SPEC)
    with pytest.raises(ValueError, match='built from source runs'):
        build(workspace, {'key': library.key, 'sha256': library.sha256})
