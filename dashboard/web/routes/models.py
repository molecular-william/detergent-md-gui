"""Models HTTP endpoints."""
import io
import json
import re
import zipfile
from pathlib import Path
from flask import abort
from dashboard import files
from ...models import mappings, bonded_states, bonded_generation, model_registry, compositions, cg_models, evidence
from ...models.mappings import depiction, context as mapping_context_model, references as mapping_references, suggestions as mapping_suggestions
from dashboard.models.json_repository import JsonRepository
from dashboard.analysis import carbohydrate_targets
from flask import Blueprint, Response, jsonify, request, send_file
from .common import coordinator

blueprint = Blueprint('models', __name__)


@blueprint.get('/api/compositions/catalog')
def composition_catalog_api():
    try:
        return jsonify(compositions.catalog(coordinator().ROOT))
    except (ValueError, OSError) as exc:
        abort(500, str(exc))


@blueprint.post('/api/compositions/preview')
def composition_preview_api():
    try:
        return jsonify(compositions.preview(_json_object(), coordinator().ROOT))
    except ValueError as exc:
        status = 409 if 'stale' in str(exc).lower() else 400
        abort(status, str(exc))


@blueprint.post('/api/compositions')
def composition_create_api():
    try:
        return jsonify(compositions.create_composition(_json_object(), coordinator().ROOT)), 201
    except ValueError as exc:
        status = 409 if ('stale' in str(exc).lower() or 'already exists' in str(exc).lower()) else 400
        abort(status, str(exc))


@blueprint.get('/api/compositions/<composition_id>')
def composition_detail_api(composition_id):
    try:
        return jsonify(compositions.composition_detail(composition_id, coordinator().ROOT))
    except (ValueError, KeyError, OSError, FileNotFoundError) as exc:
        abort(404, str(exc))


@blueprint.get('/api/cg-models')
def cg_model_list_api():
    return jsonify(models=cg_models.list_models(request.args.get('view', 'summary')))


@blueprint.get('/api/cg-models/<kind>/<identifier>')
def cg_model_detail_api(kind, identifier):
    try:
        return jsonify(cg_models.get_model(kind, identifier))
    except (ValueError, KeyError, OSError, FileNotFoundError) as exc:
        abort(404, str(exc))


def _json_object():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        abort(400, 'Expected an object')
    return payload


def _payload_context(payload, *, require_molecule=False):
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
        context = mapping_context_model.build_context(coordinator().ROOT / 'molecules', payload['molecule_id'])
    except (OSError, ValueError) as exc:
        abort(400, str(exc))
    if payload.get('molecule_snapshot') != context['snapshot']:
        abort(409, 'Molecule sources changed; reload the mapping workspace')
    return context


def _query_context(molecule_id):
    """Resolve a read-only molecule context from a query parameter, or None."""
    if not molecule_id:
        return None
    try:
        return mapping_context_model.build_context(coordinator().ROOT / 'molecules', molecule_id)
    except (OSError, ValueError) as exc:
        abort(400, str(exc))


@blueprint.get('/api/mappings')
def mapping_list():
    context = _query_context(request.args.get('molecule_id'))
    if request.args.get('view') == 'summary':
        return jsonify(candidates=mappings.list_candidates(summary=True, context=context))
    if context:
        return jsonify(candidates=mappings.list_candidates(context=context), context=context,
                       molecule=context, bead_types=mappings.bead_types())
    return jsonify(candidates=mappings.list_candidates(), molecule=mappings.molecule(), bead_types=mappings.bead_types())


@blueprint.get('/api/mappings/context')
def mapping_context():
    context = _query_context(request.args.get('molecule_id'))
    if context is not None:
        scene = depiction.build_scene(context)
        return jsonify(context=context, scene=scene, molecule=context, bead_types=mappings.bead_types())
    return jsonify(molecule=mappings.molecule(), bead_types=mappings.bead_types())


@blueprint.get('/api/mappings/representations')
def mapping_representations():
    return jsonify(representations=mappings.representation_modes(), tiers=[
        {'id': 'setup', 'label': 'Setup check'},
        {'id': 'evidence', 'label': 'Evidence run'},
    ])


@blueprint.get('/api/mappings/validation-targets')
def carbohydrate_validation_targets():
    molecule_id = request.args.get('molecule_id')
    if not molecule_id: abort(400, 'molecule_id is required')
    try:
        return jsonify(carbohydrate_targets.catalog(coordinator().ROOT, molecule_id))
    except ValueError as exc:
        abort(404, str(exc))


@blueprint.get('/api/reference-index')
def reference_index_api():
    """Read-only view over the canonical reference tree for the mapping workspace."""
    return jsonify(mapping_references.load_index(coordinator().ROOT))


@blueprint.get('/api/mappings/<name>')
def mapping_api(name):
    context = _query_context(request.args.get('molecule_id'))
    try:
        data = mappings.get(name, context=context)
    except FileNotFoundError:
        abort(404, 'Unknown mapping candidate')
    response = jsonify(data)
    response.headers['Content-Disposition'] = f'attachment; filename="{name}"'
    return response


@blueprint.post('/api/mappings/validate')
def mapping_validate():
    payload = _json_object()
    context = _payload_context(payload)
    result = mappings.validate(payload, context=context, allow_partial=bool(payload.get('schema_version') == 3))
    identity = mappings.mapping_content_identity(payload)
    duplicates = [item for item in mappings.list_candidates(summary=True, context=context)
                  if item.get('mapping_content_hash') == identity]
    result['mapping_content_hash'] = identity
    result['duplicate_file'] = duplicates[0]['file'] if duplicates else None
    return jsonify(result)


@blueprint.post('/api/mappings/automatic/preview')
def automatic_mapping_preview():
    payload = _json_object()
    context = _payload_context(payload, require_molecule=True)
    return jsonify(mapping_suggestions.generate_baseline(context, mapping_references.load_index(coordinator().ROOT)))


@blueprint.post('/api/mappings/suggest-bead')
def mapping_suggest_bead():
    payload = _json_object()
    if not isinstance(payload.get('atom_ids'), list):
        abort(400, 'atom_ids must be a list')
    context = _payload_context(payload, require_molecule=True)
    return jsonify(mapping_suggestions.suggest_bead(context, payload['atom_ids'], mapping_references.load_index(coordinator().ROOT)))


@blueprint.post('/api/mappings/ring-site/preview')
def mapping_ring_site_preview():
    payload = _json_object()
    if not isinstance(payload.get('parents'), list):
        abort(400, 'parents must be a list')
    context = _payload_context(payload, require_molecule=True)
    return jsonify(mappings.ring_site_preview(payload.get('mapping') or {}, context, payload['parents']))


@blueprint.get('/api/bonded-states')
def bonded_state_list():
    mapping_hash = request.args.get('mapping_hash')
    states = bonded_states.all_states()
    if mapping_hash: states = [s for s in states if s.get('mapping_hash') == mapping_hash]
    if request.args.get('view') == 'summary':
        states = [{k:s.get(k) for k in ('state_id','name','revision','mapping_hash')} |
                  {'current': {k:s.get('current',{}).get(k) for k in ('status','origin')}} for s in states]
    return jsonify(states=states)


@blueprint.post('/api/bonded-states')
def bonded_state_create():
    payload = _json_object(); mapping = payload.get('mapping')
    if not isinstance(mapping,dict): abort(400,'A mapping snapshot is required')
    try:
        context = _payload_context(mapping)
        mappings.validate(mapping, context=context)
        topology = payload.get('topology')
        source = payload.get('source')
        status = payload.get('status', 'incomplete')
        if 'interactions' in payload:
            if not isinstance(payload['interactions'], list):
                abort(400, 'interactions must be a list')
            structure = context or mappings.molecule()
            topology = bonded_generation.topology_from_terms(
                mapping, structure, payload['interactions'], title='Manual bonded draft')
            source = {**(source or {}), 'origin': 'manual-editor'}
            status = 'complete'
        record = bonded_states.create(mapping, payload.get('name',''), payload.get('kind','mapping-only'), source, topology, status)
    except (ValueError, OSError) as exc: abort(400,str(exc))
    return jsonify(record), 201


@blueprint.post('/api/bonded-states/automatic')
def bonded_state_automatic():
    payload = _json_object(); mapping = payload.get('mapping')
    if not isinstance(mapping, dict): abort(400, 'A mapping snapshot is required')
    try:
        context = _payload_context(mapping)
        validation = mappings.validate(mapping, context=context)
        blockers = {'missing', 'duplicate', 'unknown', 'hydrogen', 'empty', 'name',
                    'virtual_ring', 'connections', 'disconnected'}
        if any(issue['code'] in blockers for issue in validation['issues']):
            raise ValueError('Mapping is incomplete or structurally invalid: ' +
                             '; '.join(issue['message'] for issue in validation['issues']))
        result = bonded_generation.generate(mapping, context or mappings.molecule(), coordinator().ROOT)
    except (ValueError, OSError) as exc: abort(400, str(exc))
    return jsonify(result)


@blueprint.get('/api/bonded-states/<state_id>')
def bonded_state_get(state_id):
    try: return jsonify(bonded_states.get(state_id, request.args.get('revision', type=int)))
    except (ValueError, KeyError, OSError) as exc: abort(404,str(exc))


@blueprint.get('/api/bonded-states/<state_id>/interactions')
def bonded_state_interactions(state_id):
    """Return parsed bonded terms for the selected state."""
    try:
        state = bonded_states.get(state_id)
    except (ValueError, KeyError, OSError) as exc:
        abort(404, str(exc))
    current = state.get('current', {})
    terms = bonded_states.parse_interactions(current.get('topology'))
    return jsonify(state_id=state_id, revision=state.get('revision'),
                   status=current.get('status'), interactions=terms)


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


@blueprint.patch('/api/bonded-states/<state_id>')
def bonded_state_patch(state_id):
    data=_json_object(); patch=data.get('patch')
    if not isinstance(patch,dict): abort(400,'State patch must be an object')
    try: return jsonify(bonded_states.revise(state_id,patch,data.get('expected_revision'),bool(data.get('in_place'))))
    except (ValueError, KeyError, OSError) as exc: abort(409,str(exc))


@blueprint.delete('/api/bonded-states/<state_id>')
def bonded_state_delete(state_id):
    c = coordinator()
    if request.get_json(silent=True) is None or not request.get_json(silent=True).get('confirm'):
        abort(400,'Deletion requires confirmation')
    try: return jsonify(deleted=bonded_states.delete(state_id,c.load()))
    except (ValueError, KeyError, OSError) as exc: abort(409,str(exc))


@blueprint.post('/api/mappings/drafts')
def mapping_save():
    payload = _json_object()
    context = _payload_context(payload)
    return jsonify(mappings.save_draft(payload, context=context)), 201


@blueprint.post('/api/mappings/review')
def mapping_review():
    payload = _json_object()
    state = payload.get('state')
    if state not in ('draft', 'needs-review', 'approved'):
        abort(400, 'Review state must be draft, needs-review, or approved')
    context = _payload_context(payload)
    try:
        record = mappings.record_review(payload, state, payload.get('reviewer', ''), payload.get('notes', ''), context=context)
    except (ValueError, OSError) as exc:
        return jsonify(error=str(exc)), 409
    return jsonify(**record)


@blueprint.get('/api/refinement/reviews')
def refinement_reviews():
    directory = mappings.storage_root() / 'reviews'
    records = JsonRepository(directory, '{id}.json', lambda value: value).list(skip_invalid=True) if directory.is_dir() else []
    return jsonify(reviews=records)


@blueprint.post('/api/refinement/variants')
def refinement_variants():
    data = _json_object()
    try:
        result = mappings.generate_variants(data, int(data.get('limit', 8)))
    except (ValueError, TypeError, OSError) as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(variants=result)


@blueprint.delete('/api/mappings/drafts/<name>')
def mapping_delete_draft(name):
    if not re.fullmatch(r'mapping_candidate_[A-Za-z0-9_.-]+\.json', name):
        abort(400, 'Invalid draft candidate name')
    path = mappings.storage_root() / name
    if not path.is_file(): abort(404, 'Unknown draft candidate')
    path.unlink(); return jsonify(deleted=name)


@blueprint.post('/api/mappings/diagram')
def mapping_diagram():
    payload = _json_object()
    context = _payload_context(payload)
    return jsonify(svg=depiction.render(payload, context=context))


@blueprint.post('/api/mappings/export/<format>')
def mapping_export(format):
    if format not in {'ndx', 'map', 'gro', 'bundle'}:
        abort(404, 'Unknown mapping export format')
    payload = _json_object()
    context = _payload_context(payload)
    try:
        files = mappings.export_files(payload, context=context)
    except ValueError as exc:
        abort(409, str(exc))
    if format == 'bundle':
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, content in files.items():
                archive.writestr(name, content)
        buffer.seek(0)
        return send_file(buffer, mimetype='application/zip', as_attachment=True, download_name='ddm-mapping-candidate.zip')
    name = {'ndx': 'mapping.ndx', 'map': 'mapping.map', 'gro': 'mapped.gro'}[format]
    return Response(files[name], mimetype='text/plain', headers={'Content-Disposition': f'attachment; filename="{name}"'})


@blueprint.get('/api/model-references')
def model_reference_list():
    records = model_registry.references()
    return jsonify(references=records, integrity=[model_registry.check_reference(r) | {'id': r['id']} for r in records])


@blueprint.post('/api/model-references')
def model_reference_create():
    try: return jsonify(model_registry.register_reference(_json_object())), 201
    except (ValueError, OSError) as exc: abort(400, str(exc))


@blueprint.get('/api/model-fragments')
def model_fragment_list():
    return jsonify(fragments=model_registry.fragments())


@blueprint.post('/api/model-fragments')
def model_fragment_create():
    try: return jsonify(model_registry.register_fragment(_json_object())), 201
    except (ValueError, OSError) as exc: abort(400, str(exc))


@blueprint.get('/api/compositions')
def composition_list():
    return jsonify(compositions=compositions.all_compositions())


@blueprint.post('/api/compositions')
def composition_create():
    try: return jsonify(compositions.create(_json_object())), 201
    except (ValueError, OSError) as exc: abort(400, str(exc))


@blueprint.post('/api/evidence/evaluate')
def evidence_evaluate():
    data=_json_object()
    try: return jsonify(evidence.evaluate(data.get('profile'), data.get('results')))
    except ValueError as exc: abort(400, str(exc))
