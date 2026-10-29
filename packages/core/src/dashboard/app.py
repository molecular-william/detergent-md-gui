"""Construct the local dashboard with independent application-owned state."""
import sys
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = 'dashboard'

from flask import Flask, jsonify, request, send_from_directory, url_for
from jinja2 import ChoiceLoader, FileSystemLoader
from werkzeug.exceptions import HTTPException, NotFound

from . import paths as path_config
from .constants import HOST, PORT
from .execution.coordination.coordinator import Coordinator
from .web import sections
from .web.routes import analyses, catalog, common, maintenance, mappings, molecules, runs


def create_app(paths=None, config=None):
    selected = paths or path_config.default_paths()
    app = Flask(__name__, template_folder=str(selected.templates), static_folder=str(selected.static), static_url_path='/static')
    app.config.update(MAX_CONTENT_LENGTH=1024 * 1024, TEMPLATES_AUTO_RELOAD=True, PATHS=selected)
    if config: app.config.update(config)
    coordinator = Coordinator(app, app.config['PATHS'])
    app.extensions['dashboard_coordinator'] = coordinator
    app.before_request(coordinator.ensure_service)
    for module in (runs, molecules, catalog, mappings, analyses, maintenance):
        app.register_blueprint(module.blueprint)
    from . import features
    features.register(app)
    # Once, after every installed feature has contributed its workspace: a bad DASHBOARD_TABS fails here with
    # the workspace and its valid panels, instead of answering 400 on the first page that renders.
    sections.validate_tabs()

    # A feature's panels are its own files: its templates join the shell's search path, its static tree is served under
    # one route, and the shell asks the registry -- never a feature name -- which panels and sheets are installed.
    extra_templates = features.template_dirs()
    if extra_templates:
        app.jinja_loader = ChoiceLoader([app.jinja_loader, *[FileSystemLoader(str(directory))
                                                             for directory in extra_templates]])
    asset_roots = {name: str(directory) for name, directory in features.static_dirs().items()}

    @app.get('/feature-assets/<feature>/<path:filename>', endpoint='feature_asset')
    def feature_asset(feature, filename):
        root = asset_roots.get(feature)
        if root is None:
            raise NotFound()
        return send_from_directory(root, filename)

    @app.context_processor
    def feature_assets():
        """The installed panels and stylesheets, as URLs: the shell includes and links them without naming a feature."""
        return dict(
            installed_features=[feature.name for feature in features.ensure()],
            panel_modules={panel: {'url': url_for('feature_asset', feature=owner, filename=path), 'factory': factory}
                           for panel, (owner, path, factory) in features.browser_panels().items()},
            feature_styles=[url_for('feature_asset', feature=owner, filename=name)
                            for owner, name in features.browser_styles()],
            panel_extensions=[url_for('feature_asset', feature=owner, filename=module)
                              for owner, module in features.browser_extensions()],
        )

    @app.errorhandler(ValueError)
    def invalid_value(error):
        return jsonify(error=str(error)), 400

    common.register_error_handlers(app)

    @app.errorhandler(HTTPException)
    def request_error(error):
        """Every failure under `/api` answers JSON, whatever its code.

        The four codes below were registered one by one, so `405`, `422`, `500` and `503` -- all of which routes raise
        with `abort` -- answered Werkzeug's HTML into a client that parses JSON, and `405` is not hypothetical:
        `POST /api/storage` is a wrong method on a real path. A page outside `/api` keeps Werkzeug's own answer, because
        there the reader is a browser looking at a page, not a client reading a body.
        """
        if not request.path.startswith('/api/'):
            return error
        return jsonify(error=error.description), error.code
    return app


app = create_app()
default_coordinator = app.extensions['dashboard_coordinator']

if __name__ == '__main__':
    app.run(host=HOST, port=PORT, debug=False)