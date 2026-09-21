"""Every test gets isolated job, mapping, registry and bonded-state storage."""
from pathlib import Path
import pytest

from dashboard import paths
from dashboard.app import default_coordinator
from tests.dashboard.fixtures import PROJECT_ROOT


@pytest.fixture(autouse=True)
def isolated_workspace(tmp_path, monkeypatch):
    selected = paths.Paths(project_root=PROJECT_ROOT, workspace=tmp_path/'workspace')
    web = default_coordinator
    monkeypatch.setitem(web.app.config, 'PATHS', selected)
    monkeypatch.setitem(web.app.config, 'DISABLE_COORDINATOR', True)
    for name, value in {
        'ROOT': PROJECT_ROOT, 'DATA': selected.database, 'RUNS': selected.runs,
        'UPLOADS': selected.uploads, 'WORKERS': {}, 'ANALYSIS_WORKERS': {},
    }.items():
        monkeypatch.setattr(web, name, value)
    with paths.use(selected):
        yield selected


def pytest_collection_modifyitems(items):
    for item in items:
        if 'browser' in Path(item.path).parts or 'browser' in item.name:
            item.add_marker(pytest.mark.browser)
