"""Mapping workspace endpoints: candidates, drafts, review, exports, diagrams."""
import io
import zipfile

from flask import Blueprint, Response, abort, jsonify, request, send_file

from ...analysis.validation import carbohydrate_targets
from ...models import mappings
from ...models.mappings import (
    depiction,
)
from ...models.mappings import (
    references as mapping_references,
)
from ...models.mappings import (
    suggestions as mapping_suggestions,
)
from .common import coordinator, json_object, payload_context, query_context

blueprint = Blueprint('mappings', __name__)


@blueprint.get('/api/mappings')
def mapping_list():
    context = query_context(request.args.get('molecule_id'))
    if request.args.get('view') == 'summary':
        return jsonify(candidates=mappings.list_candidates(summary=True, context=context))
    if context:
        return jsonify(candidates=mappings.list_candidates(context=context), context=context,
                       molecule=context, bead_types=mappings.bead_types())
    return jsonify(candidates=mappings.list_candidates(), molecule=mappings.molecule(), bead_types=mappings.bead_types())


@blueprint.get('/api/mappings/context')
def mapping_context():
    context = query_context(request.args.get('molecule_id'))
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


@blueprint.get('/api/mappings/<name>')
def mapping_api(name):
    context = query_context(request.args.get('molecule_id'))
    try:
        data = mappings.get(name, context=context)
    except FileNotFoundError:
        abort(404, 'Unknown mapping candidate')
    response = jsonify(data)
    response.headers['Content-Disposition'] = f'attachment; filename="{name}"'
    return response


@blueprint.post('/api/mappings/validate')
def mapping_validate():
    payload = json_object()
    context = payload_context(payload)
    result = mappings.validate(payload, context=context, allow_partial=bool(payload.get('schema_version') == 3))
    identity = mappings.content_identity(payload)
    duplicates = [item for item in mappings.list_candidates(summary=True, context=context)
                  if item.get('mapping_content_hash') == identity]
    result['mapping_content_hash'] = identity
    result['duplicate_file'] = duplicates[0]['file'] if duplicates else None
    return jsonify(result)


@blueprint.post('/api/mappings/automatic/preview')
def automatic_mapping_preview():
    payload = json_object()
    context = payload_context(payload, require_molecule=True)
    return jsonify(mapping_suggestions.generate_baseline(context, mapping_references.load_index(coordinator().ROOT)))


@blueprint.post('/api/mappings/suggest-bead')
def mapping_suggest_bead():
    payload = json_object()
    if not isinstance(payload.get('atom_ids'), list):
        abort(400, 'atom_ids must be a list')
    context = payload_context(payload, require_molecule=True)
    return jsonify(mapping_suggestions.suggest_bead(context, payload['atom_ids'], mapping_references.load_index(coordinator().ROOT)))


@blueprint.post('/api/mappings/ring-site/preview')
def mapping_ring_site_preview():
    payload = json_object()
    if not isinstance(payload.get('parents'), list):
        abort(400, 'parents must be a list')
    context = payload_context(payload, require_molecule=True)
    return jsonify(mappings.ring_site_preview(payload.get('mapping') or {}, context, payload['parents']))


@blueprint.post('/api/mappings/drafts')
def mapping_save():
    payload = json_object()
    context = payload_context(payload)
    return jsonify(mappings.save_draft(payload, context=context)), 201


@blueprint.post('/api/mappings/review')
def mapping_review():
    payload = json_object()
    state = payload.get('state')
    if state not in ('draft', 'needs-review', 'approved'):
        abort(400, 'Review state must be draft, needs-review, or approved')
    context = payload_context(payload)
    try:
        record = mappings.record_review(payload, state, payload.get('reviewer', ''), payload.get('notes', ''), context=context)
    except (ValueError, OSError) as exc:
        return jsonify(error=str(exc)), 409
    return jsonify(**record)


@blueprint.delete('/api/mappings/drafts/<name>')
def mapping_delete_draft(name):
    try:
        return jsonify(deleted=mappings.delete_draft(name))
    except KeyError:
        abort(404, 'Unknown draft candidate')
    except ValueError:
        abort(400, 'Invalid draft candidate name')


@blueprint.post('/api/mappings/diagram')
def mapping_diagram():
    payload = json_object()
    context = payload_context(payload)
    return jsonify(svg=depiction.render(payload, context=context))


@blueprint.post('/api/mappings/export/<format>')
def mapping_export(format):
    if format not in {'ndx', 'map', 'gro', 'bundle'}:
        abort(404, 'Unknown mapping export format')
    payload = json_object()
    context = payload_context(payload)
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
