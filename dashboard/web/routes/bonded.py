"""CG bonded endpoints: bonded states, and the parameterizations a model carries.

Two stores answer here. `bonded_states` is the flat list of hand-edited term sets; `parameterization` is the
revision store, whose revisions are what a run stages and simulates from, and `fitting` is the job that
produces one without simulating anything. The parameterization routes are the contract in
`docs/design/2026-10-16-parameterization-and-new-run.md`: the panel sends the four payload keys it names, and
each route is a thin shell over one model call.
"""
from pathlib import Path

from flask import Blueprint, abort, jsonify, request

from ...models import mappings
from ...models.bonded import fitting as bonded_fitting
from ...models.bonded import generation as bonded_generation
from ...models.bonded import parameterization
from ...models.bonded import states as bonded_states
from .common import coordinator, json_object, payload_context

blueprint = Blueprint('bonded', __name__)


@blueprint.get('/api/bonded-states')
def bonded_state_list():
    mapping_hash = request.args.get('mapping_hash')
    content_hash = request.args.get('content_hash')
    states = bonded_states.all_states()
    if mapping_hash or content_hash:
        states = [s for s in states if bonded_states.matches(s, candidate_hash=mapping_hash, content_hash=content_hash)]
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


# --- parameterizations: the revision store and the fit job that writes to it --------------------------
#
# The contract is the design record's `### Routes the panel adds` table. Each route is one model call plus the
# status code it answers with; nothing here decides what a revision is, which engine may run, or what an
# ensemble is -- those are `parameterization`'s and `fitting`'s rules, and a second copy here would be a second
# place to drift.

def _jobs_of(content_hash=None, limit=None):
    """The fit jobs, newest first, narrowed to one mapping's when a content hash is given.

    `fitting.jobs(mapping=None, limit=...)` filters by a *mapping it holds*; a route holds only hashes, and a
    job is queued before any record exists (the record is written when the job saves), so this filters the
    stored jobs by the content identity they carry rather than by whether the panel's mapping can be loaded.
    """
    found = bonded_fitting.jobs(limit=limit)
    if content_hash:
        found = [record for record in found if record.get('mapping_content_hash') == content_hash]
    return found


def _parameterization_record(content_hash=None, mapping_hash=None):
    """The stored record a hash addresses: by content identity first, then by any revision's provenance.

    `parameterization.one` answers an empty document for a well-formed hash with no record, because "this model
    carries no parameterization" is a state a caller asks about and not a fault -- the panel renders it as the
    honest absence (D5). A `mapping_hash` is the *candidate* identity, which a rename changes, so it is answered
    by scanning the history through `parameterization.matches`, exactly as the store's own readers do.
    """
    record = parameterization.one(content_hash) if content_hash else None
    if record is None or not record.get('revisions'):
        for candidate in parameterization.records():
            if parameterization.matches(candidate, candidate_hash=mapping_hash, content_hash=content_hash):
                return candidate
    if record is not None:
        return record
    # No record, and no stored history answers either hash: the empty document the store itself answers with,
    # so the panel renders "this model carries no parameterization" rather than an error it cannot act on.
    return {'mapping_hash': mapping_hash, 'mapping_content_hash': content_hash,
            'revision': 0, 'current': None, 'revisions': []}


def _parameterization_mapping(content_hash, snapshot=None):
    """The saved candidate whose revisions these are, so an earlier one can be made current again.

    `make_current(mapping, revision)` takes a mapping, and a `PATCH` names only a content hash. The panel may
    send the snapshot it already holds (the same `mapping` key every bonded route takes); without it the
    mapping store is asked which of its candidates carries this content identity -- which is what makes the
    re-point work for a candidate that has since been renamed.
    """
    if snapshot is not None:
        if not isinstance(snapshot, dict):
            abort(400, 'mapping must be an object')
        identity = None
        try:
            identity = parameterization.content_identity(snapshot)
        except (TypeError, ValueError) as exc:
            abort(400, str(exc))
        if identity != content_hash:
            abort(400, 'That mapping is not the record this content hash names')
        return snapshot
    for candidate in mappings.list_candidates(summary=True):
        if candidate.get('error') or candidate.get('mapping_content_hash') != content_hash:
            continue
        try:
            return mappings.get(candidate['file'])
        except (OSError, ValueError) as exc:
            abort(400, str(exc))
    abort(404, f'No saved mapping carries content hash {content_hash}')


def _message(error):
    """A failure's own sentence, without the repr quotes a `KeyError` carries into `str`."""
    return error.args[0] if error.args and isinstance(error.args[0], str) else str(error)


def _molecule_root(value=None):
    """The molecule sources a fit reads: this project's, unless the caller names a directory."""
    root = coordinator().ROOT
    if value is None:
        return root / 'molecules'
    if not isinstance(value, str) or not value.strip():
        abort(400, 'molecule_root must be a directory path')
    selected = Path(value).expanduser()
    return selected if selected.is_absolute() else root / selected


@blueprint.get('/api/bonded-parameterizations/engines')
def parameterization_engines():
    """The engines a fit may run, with the one fact the panel's reference picker needs.

    `needs_reference` is what makes the AA-reference select required: an engine that fits to an ensemble
    cannot run without one, and an engine that reads the mapping alone must not be asked for one.
    """
    return jsonify(engines=parameterization.published())


@blueprint.get('/api/bonded-parameterizations/jobs')
def parameterization_jobs():
    """The job box's list: newest first, optionally one mapping's, which it polls while a fit runs."""
    limit = request.args.get('limit', type=int)
    if limit is not None and limit < 1:
        abort(400, 'limit must be positive')
    return jsonify(jobs=_jobs_of(request.args.get('content_hash'), limit))


@blueprint.post('/api/bonded-parameterizations/jobs/<job_id>/cancel')
def parameterization_job_cancel(job_id):
    """Ask a fit to stop. A job that already ended answers with its own record, unchanged."""
    try:
        return jsonify(bonded_fitting.cancel(job_id))
    except (KeyError, ValueError) as exc:
        abort(404, _message(exc))


@blueprint.get('/api/bonded-parameterizations')
def parameterization_list():
    """One record with its whole history, or every record when the caller names no mapping.

    Addressed by `content_hash` (compatibility: a renamed candidate keeps its revisions) or by `mapping_hash`
    (provenance: which saved candidate a revision was made for). `revisions` is the stored history itself and
    not a summary of it, because a revision's terms are what the panel's compare view reads and no other route
    carries them.
    """
    content_hash = request.args.get('content_hash')
    mapping_hash = request.args.get('mapping_hash')
    if not content_hash and not mapping_hash:
        return jsonify(records=parameterization.records())
    record = _parameterization_record(content_hash, mapping_hash)
    return jsonify(summary=parameterization.view(record),
                   revisions=list(record.get('revisions') or []),
                   jobs=_jobs_of(record.get('mapping_content_hash')))


@blueprint.post('/api/bonded-parameterizations')
def parameterization_start():
    """Queue a fit and answer `201` with the job record the panel polls.

    The AA reference comes in as the twelve-hex run id the panel's picker carries, and is resolved here through
    `fitting.resolve_reference` -- the same resolution every other consumer of an AA reference goes through
    (`analysis.runs.references.resolve`, which verifies the run, its hashes and its eligibility) -- so the job is
    handed the reference it must measure against rather than a name it would resolve four minutes later.
    """
    payload = json_object()
    mapping = payload.get('mapping')
    if not isinstance(mapping, dict):
        abort(400, 'A mapping snapshot is required')
    engine = payload.get('engine')
    if engine not in parameterization.ENGINES:
        abort(400, f'Unknown fitting engine: {engine!r}')
    options = payload.get('options')
    if options is not None and not isinstance(options, dict):
        abort(400, 'options must be an object')
    timeout = payload.get('timeout')
    if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0):
        abort(400, 'timeout must be a positive number of seconds')
    needs_reference = next(item['needs_reference'] for item in parameterization.published()
                           if item['value'] == engine)
    aa_reference = payload.get('aa_reference')
    if needs_reference and not aa_reference:
        abort(400, 'This engine fits to an ensemble; link an AA reference or choose another engine')
    reference = None
    if aa_reference:
        try:
            reference = bonded_fitting.resolve_reference(aa_reference)
        except ValueError as exc:
            abort(400, str(exc))
        except FileNotFoundError:
            abort(404, f'No AA reference run {aa_reference} in this workspace')
    # `start` refuses an unknown option value or an unloadable mapping with a `ValueError`, which `app.py` already
    # answers as `400`: a second translation here would be a second place to keep the two agree.
    job = bonded_fitting.start(mapping, engine=engine, reference=reference, options=options,
                               molecule_root=_molecule_root(payload.get('molecule_root')), timeout=timeout)
    return jsonify(job), 201


@blueprint.patch('/api/bonded-parameterizations/<content_hash>')
def parameterization_current(content_hash):
    """Point a model at an earlier revision, without rewriting the history that came after it.

    `confirm: true` is required because the next run prepared from this model stages the revision this call
    chooses: it is a decision about what gets simulated, not a view preference.
    """
    payload = json_object()
    if payload.get('confirm') is not True:
        abort(400, 'Making a revision current requires confirmation')
    revision = payload.get('current')
    if isinstance(revision, bool) or not isinstance(revision, int):
        abort(400, 'A revision number is required')
    mapping = _parameterization_mapping(content_hash, payload.get('mapping'))
    try:
        parameterization.make_current(mapping, revision)
    except (KeyError, ValueError) as exc:
        abort(404, _message(exc))
    return jsonify(parameterization.one(content_hash))
