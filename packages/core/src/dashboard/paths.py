"""Application paths: canonical inputs and one explicitly selected writable workspace."""
import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

#: The data root: the checkout that holds `config/`, `molecules/`, `references/` and `resources/`. The package
#: lives at `packages/core/src/dashboard` in this repository and in site-packages once installed, so the root is
#: named by `DASHBOARD_ROOT` when it is set and derived from the repository layout otherwise.
PROJECT_ROOT = (Path(os.environ['DASHBOARD_ROOT']).expanduser().resolve() if os.environ.get('DASHBOARD_ROOT')
                else Path(__file__).resolve().parents[4])
PACKAGE_ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Paths:
    project_root: Path = PROJECT_ROOT
    workspace: Path | None = None

    def __post_init__(self):
        root = Path(self.project_root).expanduser().resolve()
        workspace = Path(self.workspace).expanduser() if self.workspace is not None else root/'dashboard'
        if not workspace.is_absolute():
            workspace = root/workspace
        if workspace.is_symlink():
            raise ValueError('Workspace must not be a symbolic link')
        object.__setattr__(self, 'project_root', root)
        object.__setattr__(self, 'workspace', workspace.resolve())

    @property
    def database(self): return self.workspace/'jobs.sqlite3'
    @property
    def runs(self): return self.workspace/'runs'
    @property
    def martini3(self): return self.workspace/'martini3'
    @property
    def uploads(self): return self.workspace/'uploads'
    @property
    def proteins(self): return self.workspace/'proteins'
    @property
    def mapping_drafts(self): return self.workspace/'mapping_drafts'
    @property
    def model_registry(self): return self.workspace/'model_registry'
    @property
    def compositions(self): return self.workspace/'compositions'
    @property
    def templates(self): return PACKAGE_ROOT/'web/templates'
    @property
    def static(self): return PACKAGE_ROOT/'web/static'


def default_paths():
    """Resolve configuration at application construction, without creating state."""
    workspace = os.environ.get('DASHBOARD_WORKSPACE')
    config = PROJECT_ROOT/'config/dashboard-paths.json'
    if not workspace and config.is_file():
        payload = json.loads(config.read_text())
        if not isinstance(payload, dict) or set(payload)-{'workspace'}:
            raise ValueError('Unknown dashboard path configuration')
        workspace = payload.get('workspace')
    return Paths(workspace=workspace)


DEFAULT = Paths()
_selected = ContextVar('dashboard_paths', default=None)


def current():
    from flask import current_app, has_app_context
    if has_app_context() and 'PATHS' in current_app.config:
        return current_app.config['PATHS']
    return _selected.get() or default_paths()


@contextmanager
def use(selected):
    """Scope non-HTTP model operations, CLI commands and isolated tests."""
    token = _selected.set(selected)
    try:
        yield selected
    finally:
        _selected.reset(token)
