"""HTTP-only request helpers shared by every route module.

Coordinator lookup, pagination, JSON body parsing, and the molecule-context
protocol live here: every route module derives the caller's context through the
same two functions, so a schema-3 payload is rejected the same way wherever it
arrives.
"""
from flask import abort, current_app, request

from ...models.mappings import context as mapping_context


def coordinator():
    return current_app.extensions["dashboard_coordinator"]


def pagination():
    try:
        page = int(request.args.get('page', 1)); limit = int(request.args.get('limit', 20))
        if page < 1 or not 1 <= limit <= 100: raise ValueError()
    except ValueError: abort(400, 'Page must be positive; limit must be 1–100')
    return page, limit


def json_object():
    """Return the request body as an object, or abort 400."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        abort(400, 'Expected an object')
    return payload


def payload_context(payload, *, require_molecule=False):
    """Resolve and validate the molecule context embedded in a schema-3 payload.

    Returns None when the payload carries no molecule binding. Aborts 400 when
    a schema-3 payload omits molecule_id, when a required molecule_id is not a
    string, or when the context cannot be read. Aborts 409 when the caller's
    snapshot does not match the current source files.
    """
    if payload.get('schema_version') == 3 and not payload.get('molecule_id'):
        abort(400, 'schema 3 mappings require molecule_id')
    if require_molecule and not isinstance(payload.get('molecule_id'), str):
        abort(400, 'molecule_id is required')
    if not payload.get('molecule_id'):
        return None
    try:
        context = mapping_context.build_context(coordinator().ROOT / 'molecules', payload['molecule_id'])
    except (OSError, ValueError) as exc:
        abort(400, str(exc))
    if payload.get('molecule_snapshot') != context['snapshot']:
        abort(409, 'Molecule sources changed; reload the mapping workspace')
    return context


def query_context(molecule_id):
    """Resolve a read-only molecule context from a query parameter, or None."""
    if not molecule_id:
        return None
    try:
        return mapping_context.build_context(coordinator().ROOT / 'molecules', molecule_id)
    except (OSError, ValueError) as exc:
        abort(400, str(exc))
