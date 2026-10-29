"""Maintenance HTTP endpoints."""
import time

from dashboard.cli import migration
from flask import Blueprint, abort, current_app, jsonify, request

from ...execution.coordination import temporary
from .common import coordinator, json_object

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


@blueprint.post('/api/temporary/cleanup')
def temporary_cleanup():
    c = coordinator()
    with c.JOBS_LOCK:
        result=temporary.cleanup(c.database().all(), c.RUNS, c.database())
    return jsonify(results=result)


@blueprint.post('/api/migration/inventory')
def migration_inventory():
    data=json_object(optional=True); root=data.get('root')
    if not isinstance(root, str): abort(400, 'root is required')
    try: return jsonify(migration.inventory(root))
    except (OSError, ValueError) as exc: abort(400, str(exc))


@blueprint.post('/api/migration/delete-obsolete')
def migration_delete_obsolete():
    data=json_object(optional=True)
    try: return jsonify(migration.delete_approved(data.get('report') or {}, data.get('root'), bool(data.get('confirm'))))
    except (OSError, ValueError) as exc: abort(409, str(exc))



