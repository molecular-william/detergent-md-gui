"""Protein-detergent complex endpoints: the catalogue the panel builds its setup from."""
from flask import Blueprint, jsonify

from ...execution.adapters import pdc
from .common import coordinator

blueprint = Blueprint('pdc', __name__)


@blueprint.get('/api/pdc/catalog')
def pdc_catalog():
    return jsonify(pdc.catalog(coordinator().ROOT))
