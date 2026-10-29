"""CG bonded endpoints: the parameterization a bead mapping carries.

One store answers here. `parameterization` is the revision store, whose revisions are what a run stages and
simulates from, and `fitting` is the job that produces one without simulating anything. The flat `bonded_states`
store and its seven routes went on 2026-10-21: a parameterization belongs to a mapping, and a hand-edited term set
that belonged to nothing was a second way to say the same thing with no run behind it.

The routes are the contract in `docs/design/2026-10-16-parameterization-and-new-run.md`: the panel sends the
payload keys it names, and each route is a thin shell over one model call.
"""

from pathlib import Path

from dashboard.models import mappings
from dashboard.models.bonded import fitting as bonded_fitting
from dashboard.models.bonded import parameterization
from dashboard.web.routes.common import coordinator, json_object
from flask import Blueprint, abort, jsonify, request

blueprint = Blueprint('bonded', __name__)


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


def _parameterization_mapping(content_hash):
    """The saved candidate whose revisions these are, so an earlier one can be made current again.

    `make_current(mapping, revision)` takes a mapping, and a `PATCH` names only a content hash: the mapping
    store is asked which of its candidates carries this content identity, which is what makes the re-point
    work for a candidate that has since been renamed.
    """
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
    """The job box's list: newest first, optionally one mapping's, which it polls while a fit runs.

    Which jobs are this mapping's is `fitting.jobs`'s question; the content hash this request carries is
    handed to it, and a hash no stored job carries answers the empty list, never every job.
    """
    return jsonify(jobs=bonded_fitting.jobs(content_hash=request.args.get('content_hash'),
                                            job_id=request.args.get('job_id')))


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
    # The jobs are the model's this request named, not whatever the record happens to carry: the store's
    # empty document has no content identity when only a candidate hash was asked about, and an absent
    # hash is no filter at all. `fitting.jobs` owns the matching (content = compatibility, candidate =
    # provenance) and applies its limit after it.
    return jsonify(summary=parameterization.view(record),
                   revisions=list(record.get('revisions') or []),
                   jobs=bonded_fitting.jobs(
                       content_hash=content_hash or record.get('mapping_content_hash'),
                       mapping_hash=mapping_hash or record.get('mapping_hash')))


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


@blueprint.delete('/api/bonded-parameterizations/<content_hash>')
def parameterization_delete(content_hash):
    """Remove a model's parameterization, and nothing else.

    The *mapping* is not this route's to remove: it is the user's model, the file a run is queued from, and this panel
    edits models rather than deleting them -- the editor's own Delete still does that, through
    `DELETE /api/mappings/drafts/<name>`. What goes here is what this panel is about: the revisions, the fit jobs that
    produced them, the frames and working directories those jobs built, and the reference histograms recorded with the
    revisions.

    `confirm: true` is required because revisions are history: the terms are recoverable only by fitting again. A
    caller that names `revision` says which one it believed was current, and a record that has moved on since answers
    409 rather than deleting a newer model's work -- the same optimistic check `save` keeps.
    """
    payload = json_object(optional=True)
    if payload.get('confirm') is not True:
        abort(400, 'Deleting a parameterization requires confirmation')
    try:
        record = parameterization.one(content_hash)
    except ValueError as exc:
        abort(400, _message(exc))
    expected = payload.get('revision')
    if expected is not None:
        if isinstance(expected, bool) or not isinstance(expected, int):
            abort(400, 'A revision number is required when one is named')
        if (record.get('current') or {}).get('revision') != expected:
            abort(409, 'This parameterization changed; reload it before deleting')
    return jsonify(parameterization.delete(content_hash))


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
    mapping = _parameterization_mapping(content_hash)
    try:
        parameterization.make_current(mapping, revision)
    except (KeyError, ValueError) as exc:
        abort(404, _message(exc))
    return jsonify(parameterization.one(content_hash))
