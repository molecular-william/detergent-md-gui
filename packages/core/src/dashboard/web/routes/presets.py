"""Named stage-setting presets: one per-workspace store, read and written as JSON.

The store and its rules live in `models/setting_presets`; this module is the HTTP surface. There is no
user identity -- a preset is the workspace's -- so every route reads the workspace from the app's paths.
"""
from flask import Blueprint, abort, current_app, jsonify, request

from ...models import setting_presets
from .common import json_object

blueprint = Blueprint('presets', __name__)


def _paths():
    return current_app.config['PATHS']


def _answer(call):
    """Map the store's refusals to their status codes: absent 404, duplicate 409, otherwise 400."""
    try:
        return call()
    except setting_presets.UnknownPreset as error:
        abort(404, str(error))
    except setting_presets.DuplicatePreset as error:
        abort(409, str(error))
    except ValueError as error:
        abort(400, str(error))


@blueprint.get('/api/setting-presets')
def list_presets():
    """One run type's presets, each marked `is_default`, and which id is its default (or null)."""
    return jsonify(_answer(lambda: setting_presets.for_run_type(_paths(), request.args.get('run_type', ''))))


@blueprint.post('/api/setting-presets')
def create_preset():
    """Save the current stage settings under a name; a duplicate name within the run type is a 409.

    'kind' is the parameterization kind the form was showing ('cg' serves three): the store normalizes the
    settings in that kind's own dialect, so a reference preset keeps the sugar entry the form carries.
    """
    payload = json_object()
    kind = payload.get('kind')
    if kind is None and isinstance(payload.get('parameterization'), dict):
        kind = payload['parameterization'].get('kind')
    if kind is not None and not isinstance(kind, str):
        abort(400, 'kind must be a string')
    preset = _answer(lambda: setting_presets.create(
        _paths(), name=payload.get('name'), run_type=payload.get('run_type'),
        settings=payload.get('settings'), kind=kind))
    return jsonify(preset=preset), 201


@blueprint.patch('/api/setting-presets/<preset_id>')
def update_preset(preset_id):
    """Rename a preset, or move its run type's default marker onto it (or off it)."""
    payload = json_object()
    if 'is_default' in payload and not isinstance(payload['is_default'], bool):
        abort(400, 'is_default must be a boolean')
    preset, defaults = _answer(lambda: setting_presets.update(
        _paths(), preset_id, name=payload.get('name'), is_default=payload.get('is_default')))
    return jsonify(preset=preset, defaults=defaults)


@blueprint.delete('/api/setting-presets/<preset_id>')
def delete_preset(preset_id):
    """Remove a preset; a default that named it is cleared with it."""
    return jsonify(deleted=_answer(lambda: setting_presets.delete(_paths(), preset_id)))
