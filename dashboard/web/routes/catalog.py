"""Catalogue endpoints: compositions, CG models, references, fragments, evidence."""
from pathlib import Path

from flask import Blueprint, abort, jsonify, request, send_file

from ...models import compositions, catalog as cg_models
from ...models.molecules import registry as model_registry, evidence
from ...models.mappings import references as mapping_references
from .common import coordinator, json_object

blueprint = Blueprint('catalog', __name__)


@blueprint.get('/api/compositions/catalog')
def composition_catalog_api():
    try:
        return jsonify(compositions.catalog(coordinator().ROOT))
    except (ValueError, OSError) as exc:
        abort(500, str(exc))


@blueprint.post('/api/compositions/preview')
def composition_preview_api():
    try:
        return jsonify(compositions.preview(json_object(), coordinator().ROOT))
    except ValueError as exc:
        status = 409 if 'stale' in str(exc).lower() else 400
        abort(status, str(exc))


@blueprint.post('/api/compositions')
def composition_create_api():
    try:
        return jsonify(compositions.create_composition(json_object(), coordinator().ROOT)), 201
    except ValueError as exc:
        status = 409 if ('stale' in str(exc).lower() or 'already exists' in str(exc).lower()) else 400
        abort(status, str(exc))


@blueprint.get('/api/compositions/<composition_id>')
def composition_detail_api(composition_id):
    try:
        return jsonify(compositions.composition_detail(composition_id, coordinator().ROOT))
    except (ValueError, KeyError, OSError, FileNotFoundError) as exc:
        abort(404, str(exc))


@blueprint.get('/api/compositions')
def composition_list():
    return jsonify(compositions=compositions.all_compositions())


@blueprint.post('/api/compositions')
def composition_create():
    try: return jsonify(compositions.create(json_object())), 201
    except (ValueError, OSError) as exc: abort(400, str(exc))


@blueprint.get('/api/cg-models')
def cg_model_list_api():
    return jsonify(models=cg_models.list_models(request.args.get('view', 'summary')))


@blueprint.get('/api/cg-models/<kind>/<identifier>')
def cg_model_detail_api(kind, identifier):
    try:
        return jsonify(cg_models.get_model(kind, identifier))
    except (ValueError, KeyError, OSError, FileNotFoundError) as exc:
        abort(404, str(exc))


@blueprint.get('/api/reference-index')
def reference_index_api():
    """Read-only view over the canonical reference tree for the mapping workspace."""
    return jsonify(mapping_references.load_index(coordinator().ROOT))


@blueprint.get('/api/assets/plotly.min.js')
def plotly_asset():
    try:
        import plotly
        package_root = Path(plotly.__file__).parent
        path = package_root / 'package_data' / 'plotly.min.js'
        if package_root.is_symlink() or path.is_symlink() or not path.is_file():
            abort(503, 'The local Plotly bundle is unavailable')
    except (ImportError, OSError, RuntimeError):
        abort(503, 'The local Plotly bundle is unavailable')
    return send_file(path, mimetype='application/javascript', max_age=3600)


@blueprint.get('/api/model-references')
def model_reference_list():
    records = model_registry.references()
    return jsonify(references=records, integrity=[model_registry.check_reference(r) | {'id': r['id']} for r in records])


@blueprint.post('/api/model-references')
def model_reference_create():
    try: return jsonify(model_registry.register_reference(json_object())), 201
    except (ValueError, OSError) as exc: abort(400, str(exc))


@blueprint.get('/api/model-fragments')
def model_fragment_list():
    return jsonify(fragments=model_registry.fragments())


@blueprint.post('/api/model-fragments')
def model_fragment_create():
    try: return jsonify(model_registry.register_fragment(json_object())), 201
    except (ValueError, OSError) as exc: abort(400, str(exc))


@blueprint.post('/api/evidence/evaluate')
def evidence_evaluate():
    data = json_object()
    try: return jsonify(evidence.evaluate(data.get('profile'), data.get('results')))
    except ValueError as exc: abort(400, str(exc))
