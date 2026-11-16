"""The installed Martini 3 set: one copy per version that every run reads.

The checks here are the module's promises, not its file list: an install that records its version and upstream, a
version that is never rewritten (a second ensure, a moved upstream and a refresh all leave its bytes alone), a
named version that is refused rather than substituted, and an include that is a *relative* path resolving from the
directory the topology is read in -- which is the whole reason the install exists rather than a copy per stage. A
flat install from before version directories is read as its own version and keeps its own digest claim.
"""
import json
import shutil

import pytest
from dashboard import files, martini3, paths
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
def installation(tmp_path, monkeypatch):
    monkeypatch.setattr(martini3, '_verified', set())
    monkeypatch.setattr(martini3, '_expected_cache', {})
    return tmp_path / 'martini3'


def test_the_set_is_installed_once_at_its_version_and_records_its_witness(upstream, installation):
    directory = martini3.ensure(installation=installation, project_root=upstream)

    assert directory.parent == installation and directory.name == martini3.VERSION
    record = json.loads((directory / martini3.MANIFEST_NAME).read_text())
    assert record['version'] == martini3.VERSION and record['source'] == martini3.SOURCE
    assert record['installed_at'] and list(record['files']) == list(martini3.names(upstream))
    for name in LIBRARIES:
        assert (directory / name).read_text() == (upstream / 'references/M3-Lipid-Parameters/ITPs' / name).read_text()

    before = {path.name: path.stat().st_mtime_ns for path in directory.iterdir()}
    assert martini3.ensure(installation=installation, project_root=upstream) == directory
    assert martini3.resolve(installation=installation) == directory
    assert {path.name: path.stat().st_mtime_ns for path in directory.iterdir()} == before, \
        'a second ensure rewrote the install'
    assert martini3.versions(installation=installation) == (martini3.VERSION,)


def test_a_version_that_is_not_installed_is_refused_rather_than_substituted(upstream, installation):
    martini3.ensure(installation=installation, project_root=upstream)

    with pytest.raises(ValueError, match='has no version'):
        martini3.resolve(installation=installation, version='v9.9.9')
    with pytest.raises(ValueError, match='has no version'):
        martini3.ensure(installation=installation, project_root=upstream, version='v9.9.9')


def test_a_witness_that_names_another_version_or_upstream_is_refused(upstream, installation):
    directory = martini3.ensure(installation=installation, project_root=upstream)
    witness = json.loads((directory / martini3.MANIFEST_NAME).read_text())

    (directory / martini3.MANIFEST_NAME).write_text(json.dumps({**witness, 'version': 'v0.0.1'}))
    with pytest.raises(ValueError, match='states version'):
        martini3.ensure(installation=installation, project_root=upstream)

    (directory / martini3.MANIFEST_NAME).write_text(
        json.dumps({**witness, 'source': {**martini3.SOURCE, 'commit': 'other'}}))
    with pytest.raises(ValueError, match='different upstream'):
        martini3.ensure(installation=installation, project_root=upstream)


def test_a_file_the_witness_names_that_is_missing_is_refused(upstream, installation):
    directory = martini3.ensure(installation=installation, project_root=upstream)
    (directory / 'martini_v3.0.0_ions_v1.itp').unlink()

    with pytest.raises(ValueError, match='missing'):
        martini3.ensure(installation=installation, project_root=upstream)


def test_an_installed_version_is_never_rewritten_by_a_moved_upstream(upstream, installation):
    """The version is the claim: new upstream bytes need a new version, so this install's bytes stay what they are."""
    directory = martini3.ensure(installation=installation, project_root=upstream)
    (upstream / 'references/M3-Lipid-Parameters/ITPs/martini_v3.0.0.itp').write_text('; a new release\n')

    assert martini3.ensure(installation=installation, project_root=upstream) == directory
    assert martini3.ensure(installation=installation, project_root=upstream, refresh=True) == directory
    assert (directory / 'martini_v3.0.0.itp').read_text() != '; a new release\n', 'an installed version was rewritten'


def test_a_flat_install_from_before_versions_is_read_as_its_own_version(upstream, installation):
    """The old shape: the files sit directly under martini3/ and its manifest is a digest map. It still verifies."""
    installation.mkdir()
    expected = martini3._expected(upstream)
    for name, record in expected.items():
        shutil.copyfile(upstream / record['source'], installation / name)
    files.atomic_json(installation / martini3.MANIFEST_NAME,
                      {'source': martini3.SOURCE, 'files': expected, 'installed_at': '2026-01-01T00:00:00+00:00'})

    assert martini3.versions(installation=installation) == (martini3.LEGACY_VERSION,)
    assert martini3.ensure(installation=installation, project_root=upstream) == installation
    assert martini3.resolve(installation=installation) == installation
    assert martini3.relative('martini_v3.0.0.itp', installation=installation,
                             project_root=upstream) == 'martini3/martini_v3.0.0.itp'

    (installation / 'martini_v3.0.0.itp').write_text('; somebody edited the installed set\n')
    martini3._verified.clear()
    with pytest.raises(ValueError, match='changed since it was installed'):
        martini3.resolve(installation=installation)


def test_a_flat_install_that_the_upstream_moved_past_refuses_and_only_a_refresh_adopts_it(upstream, installation):
    installation.mkdir()
    expected = martini3._expected(upstream)
    for name, record in expected.items():
        shutil.copyfile(upstream / record['source'], installation / name)
    files.atomic_json(installation / martini3.MANIFEST_NAME,
                      {'source': martini3.SOURCE, 'files': expected, 'installed_at': '2026-01-01T00:00:00+00:00'})
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
    assert (stage / include).resolve() == martini3.path('martini_v3.0.0.itp', installation=installation,
                                                        project_root=upstream).resolve()
    assert martini3.VERSION in include, 'the include names the version it reads'


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
            ('workspace', f'martini3/{martini3.VERSION}/martini_v3.0.0.itp', 'published')
        assert absolute['root'] == 'absolute'
        for entry in (stored, absolute):
            assert run_inputs.verify_entry(entry).name == 'martini_v3.0.0.itp'


def test_the_published_set_is_tracked_so_a_clone_can_install_it():
    """A clone must install the force field without a download; the upstream benchmark stays out of git.

    The set lives under `references/`, which is mostly untracked upstream reading, so its presence on a developer's
    disk proves nothing about a clone. This reads git's own index -- `.gitignore`'s exceptions are the contract.
    """
    import subprocess

    root = paths.PROJECT_ROOT
    if not (root / '.git').exists():
        pytest.skip('not a git checkout')
    tracked = set(subprocess.run(['git', '-C', str(root), 'ls-files', '--', 'references'],
                                 capture_output=True, text=True, check=True).stdout.splitlines())
    required = [f'references/M3-Lipid-Parameters/ITPs/{name}' for name in martini3.REQUIRED]
    required += ['references/M3-Lipid-Parameters/ITPs/martini_v3.0.0_ffbonded_v2.itp',
                 'references/M3-Lipid-Parameters/ITPs/README.md',
                 'references/M3-Lipid-Parameters/LICENSE.txt',
                 'references/martini_v3.0.0_sugars_v2.itp',
                 'references/martini_v3.0.0_sugars_v2.source.json']
    missing = [path for path in required if path not in tracked]
    assert not missing, f'not tracked, so a clone cannot install the force field: {missing}'
    assert not [path for path in tracked if 'Benchmark' in path or 'autobuild' in path], (
        'the upstream benchmark material and property workbook stay untracked by decision')
