"""Path selection is scoped; importing modules never creates workspace state."""
from pathlib import Path
import pytest
from dashboard import paths


def test_relative_workspace_and_nested_scopes(tmp_path):
    first = paths.Paths(project_root=tmp_path, workspace='one')
    second = paths.Paths(project_root=tmp_path, workspace='two')
    assert first.database == tmp_path/'one/jobs.sqlite3'
    with paths.use(first):
        assert paths.current() == first
        with paths.use(second):
            assert paths.current() == second
        assert paths.current() == first
    assert not first.workspace.exists()
    assert not second.workspace.exists()


def test_workspace_symlink_is_rejected(tmp_path):
    target = tmp_path/'target'; target.mkdir()
    alias = tmp_path/'alias'; alias.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match='symbolic link'):
        paths.Paths(workspace=alias)


def test_environment_workspace_is_resolved_when_requested(tmp_path, monkeypatch):
    monkeypatch.setenv('DASHBOARD_WORKSPACE', str(tmp_path/'first'))
    assert paths.default_paths().workspace == tmp_path/'first'
    monkeypatch.setenv('DASHBOARD_WORKSPACE', str(tmp_path/'second'))
    assert paths.default_paths().workspace == tmp_path/'second'
