"""The installed Martini 3 set: one copy that every run reads, and the guarantees that make it one.

The checks here are the module's promises, not its file list: an install that records its upstream, an install whose
bytes changed refused rather than adopted, an upstream changed under an install refused rather than silently followed,
and an include that is a *relative* path resolving from the directory the topology is read in -- which is the whole
reason the install exists rather than a copy per stage.
"""
import json

import pytest
from dashboard import martini3, paths
from dashboard.execution import run_inputs

LIBRARIES = ('martini_v3.0.0.itp', 'martini_v3.0.0_solvents_v1.itp', 'martini_v3.0.0_ions_v1.itp')


@pytest.fixture
def upstream(tmp_path):
    """A repository-shaped upstream: the lipidome's ITPs, the sugar reference and their licences."""
    root = tmp_path / 'repo'
    itps = root / 'references/M3-Lipid-Parameters/ITPs'
    itps.mkdir(parents=True)
    for name in LIBRARIES:
        (itps / name).write_text(f'; {name}\n[ moleculetype ]\nW 1\n')
    (itps / 'README.md').write_text('put martini_v3.0.0_ffbonded_v2.itp before any other lipid topology\n')
    (root / 'references/M3-Lipid-Parameters/LICENSE.txt').write_text('Apache-2.0\n')
    (root / 'references/martini_v3.0.0_sugars_v2.itp').write_text('; the published sugar reference\n')
    (root / 'references/martini_v3.0.0_sugars_v2.source.json').write_text('{"martini_version": 3}\n')
    return root


@pytest.fixture
def installation(tmp_path):
    return tmp_path / 'martini3'


def test_the_set_is_installed_once_and_records_its_upstream(upstream, installation, monkeypatch):
    monkeypatch.setattr(martini3, '_verified', set())
    directory = martini3.ensure(installation=installation, project_root=upstream)

    record = json.loads((directory / martini3.MANIFEST_NAME).read_text())
    assert record['source'] == martini3.SOURCE
    assert set(record['files']) == set(martini3.names(upstream))
    for name in LIBRARIES:
        assert record['files'][name]['source'].startswith('references/')
        assert (directory / name).read_text() == (upstream / record['files'][name]['source']).read_text()

    first = sorted(p.name for p in directory.iterdir())
    martini3.ensure(installation=installation, project_root=upstream)
    assert sorted(p.name for p in directory.iterdir()) == first, 'a second ensure rewrote the install'


def test_an_installed_file_that_changed_is_refused_rather_than_used(upstream, installation, monkeypatch):
    martini3.ensure(installation=installation, project_root=upstream)
    changed = installation / 'martini_v3.0.0.itp'
    changed.write_text('; somebody edited the installed set\n')
    monkeypatch.setattr(martini3, '_verified', set())

    with pytest.raises(ValueError, match='changed since it was installed'):
        martini3.ensure(installation=installation, project_root=upstream)


def test_a_missing_installed_file_is_noticed_even_within_one_process(upstream, installation):
    martini3.ensure(installation=installation, project_root=upstream)
    (installation / 'martini_v3.0.0_ions_v1.itp').unlink()

    with pytest.raises(ValueError, match='missing'):
        martini3.ensure(installation=installation, project_root=upstream)


def test_an_upstream_that_moved_refuses_and_only_a_refresh_adopts_it(upstream, installation):
    martini3.ensure(installation=installation, project_root=upstream)
    (upstream / 'references/M3-Lipid-Parameters/ITPs/martini_v3.0.0.itp').write_text('; a new release\n')

    with pytest.raises(ValueError, match='no longer matches the set installed'):
        martini3.ensure(installation=installation, project_root=upstream)

    martini3.ensure(installation=installation, project_root=upstream, refresh=True)
    assert (installation / 'martini_v3.0.0.itp').read_text() == '; a new release\n'


def test_an_include_is_a_relative_path_that_resolves_where_the_topology_is_read(tmp_path, upstream, installation):
    stage = tmp_path / 'runs' / 'abcdef' / 'stages' / '03_minimisation'
    stage.mkdir(parents=True)

    include = martini3.include('martini_v3.0.0.itp', stage, installation=installation, project_root=upstream)

    assert not include.startswith('/'), 'an absolute include does not survive the workspace moving'
    assert (stage / include).resolve() == (installation / 'martini_v3.0.0.itp').resolve()


def test_a_name_the_set_does_not_hold_is_refused(upstream, installation):
    with pytest.raises(ValueError, match='not a file of the installed Martini 3 set'):
        martini3.path('martini_v9.9.9.itp', installation=installation, project_root=upstream)


def test_an_installed_input_is_recorded_under_the_workspace_or_absolutely(tmp_path, upstream):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    inside = martini3.path('martini_v3.0.0.itp', installation=workspace / 'martini3', project_root=upstream)
    outside = martini3.path('martini_v3.0.0.itp', installation=tmp_path / 'elsewhere', project_root=upstream)

    with paths.use(paths.Paths(project_root=upstream, workspace=workspace)):
        stored = run_inputs.installed('force_field', inside, label='martini_v3.0.0.itp')
        absolute = run_inputs.installed('force_field', outside, label='martini_v3.0.0.itp')
        assert (stored['root'], stored['path'], stored['kind']) == \
            ('workspace', 'martini3/martini_v3.0.0.itp', 'published')
        assert absolute['root'] == 'absolute'
        for entry in (stored, absolute):
            assert run_inputs.verify_entry(entry).name == 'martini_v3.0.0.itp'
