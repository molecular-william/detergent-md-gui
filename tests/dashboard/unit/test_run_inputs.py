"""The input record: what a run names, and what it refuses."""
import json

import pytest

from dashboard import files
from dashboard.execution import run_inputs


def test_a_published_file_is_named_by_its_path_and_digest(tmp_path):
    repo = tmp_path / 'repo'
    (repo / 'resources').mkdir(parents=True)
    source = repo / 'resources' / 'ff.itp'
    source.write_text('force field\n')

    entry = run_inputs.published('force_field', 'resources/ff.itp', label='Test force field', repo_root=repo)

    assert entry['kind'] == 'published' and entry['root'] == 'repo'
    assert entry['path'] == 'resources/ff.itp'
    assert entry['sha256'] == files.sha256(source)
    assert entry['bytes'] == len('force field\n')
    assert run_inputs.verify_entry(entry, repo_root=repo) == source.resolve()


def test_a_changed_published_file_is_refused_by_name(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / 'a.itp').write_text('one\n')
    entry = run_inputs.published('force_field', 'a.itp', label='A', repo_root=repo)
    (repo / 'a.itp').write_text('two\n')

    with pytest.raises(ValueError, match='force_field changed since this run was prepared'):
        run_inputs.verify_entry(entry, repo_root=repo)


def test_a_published_symlink_is_refused(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / 'real.itp').write_text('x\n')
    (repo / 'link.itp').symlink_to(repo / 'real.itp')

    with pytest.raises(ValueError, match='not a regular file'):
        run_inputs.published('force_field', 'link.itp', label='Link', repo_root=repo)


def test_a_published_tree_is_one_entry_with_a_digest_over_its_files(tmp_path):
    repo = tmp_path / 'repo'
    tree = repo / 'ff'
    (tree / 'nested').mkdir(parents=True)
    (tree / 'forcefield.itp').write_text('a\n')
    (tree / 'nested' / 'ffbonded.itp').write_text('b\n')

    entry = run_inputs.published_tree('force_field', 'ff', label='Tree', repo_root=repo)

    assert entry['files'] == 2
    assert entry['sha256'] == files.json_sha256(files.hashes(tree))
    assert run_inputs.verify_entry(entry, repo_root=repo) == tree.resolve()
    (tree / 'forcefield.itp').write_text('changed\n')
    with pytest.raises(ValueError, match='force_field changed'):
        run_inputs.verify_entry(entry, repo_root=repo)


def test_the_record_covers_generated_data_and_round_trips_through_the_manifest(tmp_path):
    run = tmp_path / 'run'
    (run / 'inputs').mkdir(parents=True)
    (run / 'inputs' / 'context.json').write_text('{"a": 1}\n')
    (run / 'inputs' / 'nested').mkdir()
    (run / 'inputs' / 'nested' / 'solute.ndx').write_text('[ water ]\n')

    entries = run_inputs.write(run)
    manifest = {'inputs': entries, 'input_snapshot_sha256': run_inputs.digest(entries)}

    assert [entry['path'] for entry in entries] == ['inputs/context.json', 'inputs/nested/solute.ndx']
    assert all(entry['kind'] == 'generated' for entry in entries)
    assert run_inputs.verify_manifest(run, manifest) == entries


def test_an_edited_record_is_refused(tmp_path):
    run = tmp_path / 'run'
    (run / 'inputs').mkdir(parents=True)
    (run / 'inputs' / 'a.txt').write_text('a\n')
    entries = run_inputs.write(run)
    manifest = {'inputs': entries, 'input_snapshot_sha256': run_inputs.digest(entries)}
    record = json.loads((run / 'inputs' / 'inputs.json').read_text())
    record['inputs'][0]['label'] = 'edited'
    (run / 'inputs' / 'inputs.json').write_text(json.dumps(record))

    with pytest.raises(ValueError, match='does not match'):
        run_inputs.verify_manifest(run, manifest)


def test_a_legacy_manifest_still_verifies_its_input_directory(tmp_path):
    run = tmp_path / 'run'
    (run / 'inputs').mkdir(parents=True)
    (run / 'inputs' / 'a.txt').write_text('a\n')
    manifest = {'input_snapshot_sha256': files.hashes(run / 'inputs')}

    assert run_inputs.verify_manifest(run, manifest) is None
    (run / 'inputs' / 'a.txt').write_text('b\n')
    with pytest.raises(ValueError, match='changed or missing'):
        run_inputs.verify_manifest(run, manifest)


def test_an_entry_cannot_escape_its_root(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    entry = {'role': 'x', 'label': 'x', 'kind': 'published', 'root': 'repo',
             'path': '../outside', 'sha256': '0' * 64, 'bytes': 0}

    with pytest.raises(ValueError, match='escapes its root'):
        run_inputs.resolve(entry, repo_root=repo)
