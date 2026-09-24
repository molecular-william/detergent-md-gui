"""Refinement endpoints: recorded reviews and variant generation."""
from flask import Blueprint, jsonify

from ...models import mappings
from ...models.repository import JsonRepository
from .common import json_object

blueprint = Blueprint('refinement', __name__)


@blueprint.get('/api/refinement/reviews')
def refinement_reviews():
    directory = mappings.storage_root() / 'reviews'
    records = JsonRepository(directory, '{id}.json', lambda value: value).list(skip_invalid=True) if directory.is_dir() else []
    return jsonify(reviews=records)


@blueprint.post('/api/refinement/variants')
def refinement_variants():
    data = json_object()
    try:
        result = mappings.generate_variants(data, int(data.get('limit', 8)))
    except (ValueError, TypeError, OSError) as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(variants=result)
