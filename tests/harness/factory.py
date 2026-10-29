"""Build a dashboard application against an isolated workspace.

The suite used to drive the import-time `default_coordinator` singleton and patch six of its
attributes from an autouse fixture, which meant every test in the process shared one application
and one set of module globals. A test that wants an application builds one: the factory takes the
same Paths the fixture takes, disables the background coordinator, and hands back the client and
the coordinator whose state the test owns.
"""
from dataclasses import dataclass

from dashboard import paths as path_config
from dashboard.app import create_app

PROJECT_ROOT = path_config.PROJECT_ROOT


@dataclass
class Dashboard:
    """An application, its client, the coordinator behind it, and the paths it was built with."""
    app: object
    client: object
    coordinator: object
    paths: object


def build(tmp_path, **config):
    """An application with its own workspace, database and run directories."""
    selected = path_config.Paths(project_root=PROJECT_ROOT, workspace=tmp_path / 'workspace')
    app = create_app(selected, {'DISABLE_COORDINATOR': True} | config)
    return Dashboard(app, app.test_client(), app.extensions['dashboard_coordinator'], selected)
