"""Every test gets isolated job, mapping, registry and bonded-state storage."""
from pathlib import Path
import pytest

from dashboard import paths
from dashboard.app import default_coordinator
from tests.dashboard import factory
from tests.dashboard.fixtures import PROJECT_ROOT


@pytest.fixture
def dashboard(tmp_path):
    """An application the test owns, with no shared module state; see tests/dashboard/factory.py."""
    return factory.build(tmp_path)


@pytest.fixture(autouse=True)
def isolated_workspace(tmp_path, monkeypatch):
    """Deprecated: the import-time singleton, patched for tests that still drive it.

    New tests take the `dashboard` fixture instead. This stays until the files that import
    `default_coordinator` have migrated, because it is what keeps them isolated meanwhile.
    """
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
        # Only the directory decides: a name heuristic here would silently pull a future
        # "*_browser*" unit test into the tier that needs Playwright and Chrome.
        if 'browser' in Path(item.path).parts:
            item.add_marker(pytest.mark.browser)
