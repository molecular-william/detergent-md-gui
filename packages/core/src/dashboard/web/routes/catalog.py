"""Catalogue endpoints: compositions, CG models, references, evidence."""
from pathlib import Path

from flask import Blueprint, abort, jsonify, send_file

from ...models import catalog as cg_models
from ...models import compositions
from ...models.compositions import parameterizations as composition_parameterizations
from ...models.mappings import references as mapping_references
from ...models.molecules import evidence
from .common import coordinator, json_object

blueprint = Blueprint('catalog', __name__)


@blueprint.get('/api/compositions/catalog')
def composition_catalog_api():
    try:
        # No project root: the models resolve the sugar reference from the workspace's installed Martini 3 set, the
        # same bytes a run will simulate with.
        return jsonify(compositions.catalog())
    except (ValueError, OSError) as exc:
        abort(500, str(exc))


@blueprint.post('/api/compositions/preview')
def composition_preview_api():
    try:
        return jsonify(compositions.preview(json_object()))
    except ValueError as exc:
        status = 409 if 'stale' in str(exc).lower() else 400
        abort(status, str(exc))


@blueprint.post('/api/compositions')
def composition_create_api():
    try:
        return jsonify(compositions.create_composition(json_object())), 201
    except ValueError as exc:
        status = 409 if ('stale' in str(exc).lower() or 'already exists' in str(exc).lower()) else 400
        abort(status, str(exc))


@blueprint.get('/api/compositions/<composition_id>/parameterizations')
def composition_parameterizations_api(composition_id):
    """A saved composition's parameterization: the derived revision 0, the edits above it, and the ranges.

    The current revision's topology **text** is in the answer, so the terms card needs no second parse route; the
    ranges come from `dashboard.models.bonded.PARAMETER_RANGES`, which owns them, and are not restated here.
    """
    try:
        return jsonify(composition_parameterizations.view(composition_id))
    except (ValueError, KeyError, OSError, FileNotFoundError) as exc:
        abort(404, str(exc))


@blueprint.post('/api/compositions/<composition_id>/parameterizations')
def composition_parameterization_save_api(composition_id):
    """Append an edited revision seeded from the derived model, and make it current.

    `expected_revision` is the optimistic check the panel sends: a record that moved on answers 409 rather than
    losing the newer edit. A named revision a run consumes is resolved by the adapter, not here.
    """
    data = json_object()
    try:
        saved = composition_parameterizations.save(composition_id, data,
                                                  expected_revision=data.get('expected_revision'))
        return jsonify(saved), 201
    except composition_parameterizations.StaleRevision as exc:
        abort(409, str(exc))
    except (KeyError, FileNotFoundError) as exc:
        abort(404, str(exc))
    except (ValueError, OSError) as exc:
        abort(400, str(exc))


@blueprint.get('/api/cg-models')
def cg_model_list_api():
    return jsonify(models=cg_models.list_models())


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


# Validation-flavoured, still engine-owned pending confirmation of its consumers.
@blueprint.post('/api/evidence/evaluate')
def evidence_evaluate():
    data = json_object()
    try: return jsonify(evidence.evaluate(data.get('profile'), data.get('results')))
    except ValueError as exc: abort(400, str(exc))
