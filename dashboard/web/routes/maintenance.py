"""Maintenance HTTP endpoints."""
from flask import abort, current_app
import time
from ...execution.coordination import temporary
from dashboard.cli import migration
from flask import Blueprint, jsonify, request
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


@blueprint.post('/api/temporary/cleanup')
def temporary_cleanup():
    c = coordinator()
    with c.JOBS_LOCK:
        result=temporary.cleanup(c.load(), c.RUNS, c.database())
    return jsonify(results=result)


@blueprint.post('/api/migration/inventory')
def migration_inventory():
    data=request.get_json() or {}; root=data.get('root')
    if not isinstance(root, str): abort(400, 'root is required')
    try: return jsonify(migration.inventory(root))
    except (OSError, ValueError) as exc: abort(400, str(exc))


@blueprint.post('/api/migration/delete-obsolete')
def migration_delete_obsolete():
    data=request.get_json() or {}
    try: return jsonify(migration.delete_approved(data.get('report') or {}, data.get('root'), bool(data.get('confirm'))))
    except (OSError, ValueError) as exc: abort(409, str(exc))


@blueprint.post('/api/bonded-states/import-legacy')
def import_legacy_bonded_states():
    c = coordinator()
    with c.JOBS_LOCK:
        return jsonify(imported=c.import_legacy_bonded_states())
