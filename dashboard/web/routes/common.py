"""HTTP-only request helpers."""
from flask import current_app, request, abort

def coordinator():
    return current_app.extensions["dashboard_coordinator"]

def pagination():
    try:
        page = int(request.args.get('page', 1)); limit = int(request.args.get('limit', 20))
        if page < 1 or not 1 <= limit <= 100: raise ValueError()
    except ValueError: abort(400, 'Page must be positive; limit must be 1–100')
    return page, limit

