"""Refinement endpoints: recorded reviews and variant generation."""
from flask import Blueprint, jsonify

from ...models import mappings
from .common import json_object

blueprint = Blueprint('refinement', __name__)


@blueprint.get('/api/refinement/reviews')
def refinement_reviews():
    return jsonify(reviews=mappings.list_reviews())


@blueprint.post('/api/refinement/variants')
def refinement_variants():
    data = json_object()
    try:
        result = mappings.generate_variants(data, int(data.get('limit', 8)))
    except (ValueError, TypeError, OSError) as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(variants=result)
