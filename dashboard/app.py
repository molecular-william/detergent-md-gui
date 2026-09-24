"""Construct the local dashboard with independent application-owned state."""
from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = 'dashboard'

from flask import Flask, jsonify
from . import paths as path_config
from .constants import HOST, PORT
from .execution.coordination.coordinator import Coordinator
from .web.routes import analyses, bonded, catalog, common, maintenance, mappings, molecules, refinement, runs


def create_app(paths=None, config=None):
    selected = paths or path_config.default_paths()
    app = Flask(__name__, template_folder=str(selected.templates), static_folder=str(selected.static), static_url_path='/static')
    app.config.update(MAX_CONTENT_LENGTH=1024 * 1024, TEMPLATES_AUTO_RELOAD=True, PATHS=selected)
    if config: app.config.update(config)
    coordinator = Coordinator(app, app.config['PATHS'])
    app.extensions['dashboard_coordinator'] = coordinator
    app.before_request(coordinator.ensure_service)
    for module in (runs, molecules, catalog, mappings, bonded, refinement, analyses, maintenance):
        app.register_blueprint(module.blueprint)

    @app.errorhandler(ValueError)
    def invalid_value(error):
        return jsonify(error=str(error)), 400

    common.register_error_handlers(app)

    def request_error(error):
        return jsonify(error=error.description), error.code
    for code in (400, 404, 409, 413):
        app.register_error_handler(code, request_error)
    return app


app = create_app()
default_coordinator = app.extensions['dashboard_coordinator']

if __name__ == '__main__':
    app.run(host=HOST, port=PORT, debug=False)