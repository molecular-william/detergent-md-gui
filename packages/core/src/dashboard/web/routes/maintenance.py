"""Maintenance HTTP endpoints."""
import time

from flask import Blueprint, current_app, jsonify, request

from .common import coordinator

blueprint = Blueprint('maintenance', __name__)

@blueprint.get('/api/storage')
def storage_api():
    c = coordinator()
    key = str(c.RUNS)
    cached = current_app.extensions.get('storage_display')
    if request.args.get('refresh') == '1' or not cached or cached[0] != key or time.monotonic()-cached[1] > 10:
        cached = (key, time.monotonic(), c.storage_report())
        current_app.extensions['storage_display'] = cached
    return jsonify(cached[2])
