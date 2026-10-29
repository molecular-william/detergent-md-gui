"""Every test gets isolated job, mapping, registry and bonded-state storage.

Loaded from the repository's root `conftest.py` through `pytest_plugins`, so the fixtures reach every test tree
(`tests/dashboard` today, `packages/<module>/tests` later) without each directory repeating them.
"""
import atexit
import os
import shutil
import tempfile
from pathlib import Path

# Matplotlib writes its font cache under MPLCONFIGDIR. Four distance-plot tests race when every xdist worker shares
# the process default; a private per-process directory removes the race and the 20-45 s rerun it costs.
if 'MPLCONFIGDIR' not in os.environ:
    _mpl = tempfile.mkdtemp(prefix='dashboard-mpl-')
    os.environ['MPLCONFIGDIR'] = _mpl
    atexit.register(shutil.rmtree, _mpl, ignore_errors=True)

# The Martini 3 set is installed once per test session, not once per temporary workspace: it is 18 MB, and a test that
# prepares a run would otherwise copy it for every `tmp_path`. The variable is the same override an operator uses, and
# it also keeps the suite from ever writing into the checkout's live workspace. A test that needs a fresh or a broken
# install points it somewhere else with `monkeypatch.setenv`.
if 'DASHBOARD_MARTINI3' not in os.environ:
    _martini3 = tempfile.mkdtemp(prefix='dashboard-martini3-')
    os.environ['DASHBOARD_MARTINI3'] = _martini3
    atexit.register(shutil.rmtree, _martini3, ignore_errors=True)

import pytest
from dashboard import paths
from dashboard.app import default_coordinator

from tests.dashboard import areas, modules
from tests.harness import factory
from tests.harness.support import PROJECT_ROOT


@pytest.fixture
def dashboard(tmp_path):
    """An application the test owns, with no shared module state; see tests/harness/factory.py.

    Module-level path resolution is pointed at the same workspace for the duration, which is the
    part of the old autouse fixture a built application cannot do for itself: stores that resolve
    their root from `paths` must see the test's workspace, not the default one.
    """
    built = factory.build(tmp_path)
    with paths.use(built.paths):
        yield built


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
        # The area is a second axis, from the table in `tests/dashboard/areas.py`: `-m pdc` runs the protein-detergent
        # tests, `-m 'mapping and not browser'` the mapping ones without a browser. A module the table does not name is
        # a failure in `test_test_areas.py`, not a silently uncategorised file.
        area = areas.area_of(item.path)
        if area:
            item.add_marker(getattr(pytest.mark, area))
        # The ownership axis, from `tests/dashboard/modules.py`: `-m core|validation|pdc` is one distribution's
        # tests. A module the table does not name is core, so a new engine test needs no entry; a new feature test
        # is assigned in the pass that adds it, and `test_test_modules.py` checks the table.
        item.add_marker(getattr(pytest.mark, modules.module_of(item.path)))
