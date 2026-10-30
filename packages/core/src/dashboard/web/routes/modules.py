"""The installed modules this workspace shows, and the switch that changes it.

Hiding a module is a view decision, not an unload: its blueprints, run types, analysis kinds and recorded-code
resolvers stay registered, so a run made under a module keeps opening and analysing after it is switched off. What
changes on the next page load is the workspace navigation and, with it, which workspaces offer their run types.
"""
from flask import Blueprint, current_app, jsonify, request

from ... import features
from .. import sections

blueprint = Blueprint('modules', __name__)


def _state():
    paths = current_app.config['PATHS']
    return {'modules': sections.module_rows(paths),
            'failures': [{'name': name, 'error': message} for name, message in features.failures()]}


@blueprint.get('/api/modules')
def modules_api():
    return jsonify(_state())


@blueprint.put('/api/modules')
def update_modules():
    payload = request.get_json(silent=True) or {}
    names = payload.get('enabled')
    if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
        return jsonify(error='"enabled" must be a list of module names'), 400
    installed = [feature.name for feature in features.ensure()]
    unknown = sorted(set(names) - set(installed))
    if unknown:
        return jsonify(error=f'unknown module(s) {unknown}; installed modules are {installed}'), 400
    sections.set_enabled(current_app.config['PATHS'], names)
    return jsonify(_state())
