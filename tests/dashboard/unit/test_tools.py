"""Tool resolution: the declaration in config/tools.json first, then PATH.

No literal home-directory path may appear in a resolved tool location or in the
PATH handed to a stage subprocess. These tests pin the resolution rules, the
fallback, and the honesty of a declaration that cannot be honoured.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from dashboard import paths
from dashboard.execution import tools


def executable(path, body='#!/bin/sh\nexit 0\n'):
    path.write_text(body)
    path.chmod(0o755)
    return path


def config_file(tmp_path, payload):
    config = tmp_path / 'tools.json'
    config.write_text(json.dumps(payload))
    return config


def test_a_declared_path_wins_over_the_inherited_path(tmp_path):
    declared = executable(tmp_path / 'gmx-declared')
    config = config_file(tmp_path, {'gromacs': str(declared)})
    assert tools.tool_path('gmx', config=config) == str(declared)


def test_a_declaration_of_a_command_name_resolves_on_the_path(tmp_path):
    config = config_file(tmp_path, {'gromacs': 'sh'})
    resolved = tools.tool_path('gmx', config=config)
    assert resolved and Path(resolved).name == 'sh'


def test_an_unresolvable_declaration_is_not_silently_substituted(tmp_path):
    """A declared path that is not there must resolve to nothing, not to some other gmx."""
    config = config_file(tmp_path, {'gromacs': str(tmp_path / 'absent' / 'gmx')})
    assert tools.tool_path('gmx', config=config) is None


def test_a_declared_family_locates_its_siblings(tmp_path):
    """Fast_Forward declares one entry point; the other two resolve beside it."""
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    executable(bindir / 'ff_map')
    executable(bindir / 'ff_inter')
    config = config_file(tmp_path, {'fast_forward': str(bindir / 'ff_map')})
    assert tools.tool_path('ff_inter', config=config) == str(bindir / 'ff_inter')


def test_an_undeclared_command_falls_back_to_the_inherited_path(tmp_path):
    config = config_file(tmp_path, {})
    assert tools.tool_path('sh', config=config) == tools.tool_path('sh')


def test_search_path_introduces_only_the_workspace_and_declared_directories(tmp_path, monkeypatch):
    """The composed PATH is the workspace, the declared directories, then what we inherited.

    Asserted on composition rather than on "no home directory anywhere": a declared
    tool may legitimately live under a home directory, and so may the inherited PATH.
    """
    declared = executable(tmp_path / 'gmx-declared')
    monkeypatch.setattr(tools, 'declared_tools', lambda config=None: {'gromacs': str(declared)})
    composed = tools.search_path()
    inherited = os.environ.get('PATH', '')
    assert composed.endswith(inherited), 'the inherited PATH stays last'
    introduced = [entry for entry in composed[:len(composed) - len(inherited)].split(os.pathsep) if entry]
    assert introduced == [str(paths.current().project_root / 'dashboard/.venv/bin'), str(tmp_path)]


def test_a_provenance_declaration_is_not_treated_as_a_tool(tmp_path, monkeypatch):
    """config/tools.json also says where a tool's source is and which revision it should
    be at. Neither is a command to resolve, nor a directory to put on PATH."""
    source = tmp_path / 'fast_forward'
    source.mkdir()
    monkeypatch.setattr(tools, 'declared_tools', lambda config=None: {
        'fast_forward_source': str(source), 'fast_forward_commit': 'a' * 40})
    checks, blockers = tools.declared_tool_checks()
    assert checks == [] and blockers == []
    assert str(source) not in tools.search_path()


def test_a_relative_declared_path_is_anchored_to_the_workspace():
    """A declaration means one thing wherever the process happened to start."""
    assert (tools.declared_path('resources/parameterizers/fast_forward')
            == paths.current().project_root / 'resources/parameterizers/fast_forward')
    assert tools.declared_path('/opt/tool/bin') == Path('/opt/tool/bin')
    assert tools.declared_path('~/bin') == Path.home() / 'bin'


def test_a_declaration_that_is_not_a_repository_has_no_revision(tmp_path):
    assert tools.vendor_state(tmp_path) == {}
    assert tools.declared_provenance(config=tmp_path / 'absent.json') == {}


def test_a_vendor_revision_and_its_dirtiness_are_read_from_the_tree(tmp_path):
    """Read-only: the pin is only useful if the tree can be asked what it is at."""
    if shutil.which('git') is None:
        pytest.skip('git is not available')
    repo = tmp_path / 'vendor'
    repo.mkdir()
    env = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.com',
           'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@example.com'}
    subprocess.run(['git', 'init', '-q'], cwd=repo, env=env, check=True)
    (repo / 'file.txt').write_text('x\n')
    subprocess.run(['git', 'add', '.'], cwd=repo, env=env, check=True)
    subprocess.run(['git', 'commit', '-qm', 'one'], cwd=repo, env=env, check=True)
    state = tools.vendor_state(repo)
    assert state['dirty'] is False and len(state['commit']) == 40
    (repo / 'file.txt').write_text('changed\n')
    assert tools.vendor_state(repo)['dirty'] is True


def test_no_hard_coded_build_directory_is_introduced():
    """The GROMACS build the code used to assume is gone from the composed PATH."""
    composed = tools.search_path()
    inherited = os.environ.get('PATH', '')
    introduced = composed[:len(composed) - len(inherited)]
    assert 'Downloads/gromacs-2026.0' not in introduced
    assert str(Path.home()) not in introduced


def test_a_declaration_that_cannot_be_honoured_is_reported(tmp_path):
    """Readiness must see a dangling declaration instead of guessing around it."""
    config = config_file(tmp_path, {'gromacs': str(tmp_path / 'absent' / 'gmx')})
    checks, blockers = tools.declared_tool_checks(config=config)
    assert [check['ready'] for check in checks] == [False]
    assert 'gromacs' in checks[0]['label']
    assert blockers == [], 'a tool this run type does not use must not block the run'


def test_a_honoured_declaration_reports_as_ready(tmp_path):
    declared = executable(tmp_path / 'gmx-declared')
    config = config_file(tmp_path, {'gromacs': str(declared)})
    checks, blockers = tools.declared_tool_checks(config=config)
    assert [check['ready'] for check in checks] == [True]
    assert blockers == []


def test_the_real_configuration_resolves_the_toolchain_it_declares():
    """The checked-in config must name tools that exist on this machine."""
    assert tools.tool_path('gmx'), 'config/tools.json must name an executable GROMACS'
    assert tools.tool_path('ff_map') and tools.tool_path('ff_inter') and tools.tool_path('ff_assess')

