"""CG bonded-state endpoints: listing, creation, generation, interaction edits."""
from flask import Blueprint, abort, jsonify, request

from ...models import mappings
from ...models.bonded import generation as bonded_generation
from ...models.bonded import states as bonded_states
from .common import coordinator, json_object, payload_context

blueprint = Blueprint('bonded', __name__)


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
    payload = json_object(); mapping = payload.get('mapping')
    if not isinstance(mapping,dict): abort(400,'A mapping snapshot is required')
    try:
        context = payload_context(mapping)
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
    payload = json_object(); mapping = payload.get('mapping')
    if not isinstance(mapping, dict): abort(400, 'A mapping snapshot is required')
    try:
        context = payload_context(mapping)
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


@blueprint.patch('/api/bonded-states/<state_id>')
def bonded_state_patch(state_id):
    data = json_object(); patch = data.get('patch')
    if not isinstance(patch,dict): abort(400,'State patch must be an object')
    try: return jsonify(bonded_states.revise(state_id,patch,data.get('expected_revision'),bool(data.get('in_place'))))
    except (ValueError, KeyError, OSError) as exc: abort(409,str(exc))


@blueprint.delete('/api/bonded-states/<state_id>')
def bonded_state_delete(state_id):
    c = coordinator()
    if not json_object(optional=True).get('confirm'):
        abort(400,'Deletion requires confirmation')
    try: return jsonify(deleted=bonded_states.delete(state_id,c.database().all()))
    except (ValueError, KeyError, OSError) as exc: abort(409,str(exc))
