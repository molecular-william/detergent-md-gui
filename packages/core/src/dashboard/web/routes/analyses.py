"""Analyses HTTP endpoints."""
import json
import threading
from pathlib import Path

from dashboard.execution import assessment_rescore
from flask import Blueprint, abort, jsonify, request

from ...analysis.runs import layout
from .common import coordinator, json_object

blueprint = Blueprint('analyses', __name__)


def newest_published(c, job, kind, artifact, *, figure_key=None, require_figure=False,
                     tolerate_missing_figure=False, fall_through=True):
    """The newest attempt of `kind` whose published file still stands. `(attempt, published, path)`, or `None`.

    Every analysis publishes into `analyses/<kind>/<signature>/<attempt>/`: its `result.json` names the
    content-addressed output directory, and the file a reader wants is relative to that. An attempt whose file is
    gone is not a published analysis and is skipped for an older one that still stands. `fall_through=False`
    answers the newest attempt instead, with `published=None`, so a caller can name the attempt that went missing.

    `figure_key` names a field in the published file that holds a figure path; the figure then joins the answer as
    a fourth element, `None` when that file is gone. `require_figure` skips attempts whose figure is gone and
    `tolerate_missing_figure` remembers the newest of those, so an analysis that published and lost its figure
    still answers -- with `None` -- rather than reading as never published.
    """
    records = sorted((c.run_path(job) / 'analyses' / kind).glob('*/*/result.json'),
                     key=lambda path: path.stat().st_mtime, reverse=True)
    if not records:
        return None
    without_figure = None
    for record_path in records:
        attempt = record_path.parent
        output = attempt / str(json.loads(record_path.read_text()).get('output_directory') or '')
        published_path = output / artifact
        if not published_path.is_file():
            if not fall_through:
                return attempt, None, published_path
            continue
        published = json.loads(published_path.read_text())
        if figure_key is None:
            return attempt, published, published_path
        figure = output / str(published.get(figure_key) or '')
        if figure.is_file():
            return attempt, published, published_path, figure
        if not require_figure:
            return attempt, published, published_path, None
        if tolerate_missing_figure and without_figure is None:
            without_figure = (attempt, published, published_path, None)
    return without_figure


def newest_comparison(c, job):
    """A run's newest published AA-vs-CG comparison: `(attempt, record, artifact)`.

    Raises `LookupError` with the reason when there is none: "nothing was published" and "the newest record
    names a file that does not exist" are different answers for a reader, and only the second is worth looking
    into. Both readers of a comparison come through here, so they cannot disagree about which attempt answered.
    """
    found = newest_published(c, job, 'mapping-consistency', 'analysis/mapping_consistency.json',
                             fall_through=False)
    if found is None:
        raise LookupError('No AA vs CG comparison has been published for this run')
    attempt, published, artifact = found
    if published is None:
        raise LookupError(f'{attempt.name} names no published comparison file')
    return attempt, json.loads((attempt / 'result.json').read_text()), artifact


def newest_surfaces(c, job):
    """A run's newest published surfaces analysis: `(attempt, published, metadata_path)`, or `None`.

    The solvent-accessible envelope analysis is its own kind with its own attempt, because it needs the atomistic
    trajectory, the mapped one and the simulated one and takes minutes rather than seconds. It publishes SASA
    statistics and the AA-vs-Simulated-CG pair the Shape pane draws; it writes no figure of its own. Most runs have
    never had one -- it is queued by hand -- and that is a state a card has to be able to say, so this answers `None`
    rather than raising.
    """
    return newest_published(c, job, 'surfaces', 'analysis/surfaces/metadata.json')


def newest_overlap(c, job):
    """A run's newest published bead-overlap analysis: `(attempt, published, report, figure_or_None)`, or `None`.

    Unlike `newest_surfaces`, this one has a figure, and the attempt's figure is read with it: an attempt whose figure
    is gone does not answer *unless nothing better exists*, and then it still answers with `figure=None` so the card
    can report that the analysis published and its figure is no longer on disk -- a sentence a run that was never
    analysed must not get.
    """
    return newest_published(c, job, 'overlap', 'overlap.json', figure_key='figure',
                            require_figure=True, tolerate_missing_figure=True)


def newest_cross_check(c, job):
    """A run's newest published bonded cross-check: `(attempt, published, report)`, or `None`.

    Unlike the overlap reader, there is no figure to require: this analysis publishes numbers and the list of terms
    the two sides disagree about, so a report that is on disk is the whole artifact.
    """
    return newest_published(c, job, 'bonded-cross-check', 'bonded-cross-check.json')


def newest_dihedral_fit(c, job):
    """A run's newest published dihedral fit: `(attempt, published, report)`, or `None`.

    The same shape as `newest_cross_check` and for the same reason: this analysis publishes numbers and a list of
    terms, with no figure to lose, so a report on disk is the whole artifact.
    """
    return newest_published(c, job, 'dihedral-fit', 'dihedral-fit.json')


@blueprint.post('/api/jobs/<jid>/<kind>')
def queue_analysis(jid, kind):
    payload = json_object(optional=True)
    from ... import features

    validator = features.kind_payload_for(kind)
    if validator is not None:
        payload = validator(coordinator(), jid, payload)
    task, status = coordinator().analysis_coordinator.queue(jid, kind, payload)
    return jsonify(task), status


@blueprint.post('/api/jobs/<jid>/analyses/<aid>/cancel')
def cancel_analysis(jid, aid):
    return jsonify(coordinator().analysis_coordinator.cancel(jid, aid)), 202


@blueprint.post('/api/jobs/<jid>/analyses/recompute')
def recompute_analyses(jid):
    """Queue every analysis the run owes that this code has not already produced for it.

    The Analysis graphs panel's button, and the same list the completion event drains: `automatic_analyses` is the one
    place a run's owed kinds are decided, so the button cannot ask for a set the run does not owe. `queue` fingerprints
    the analysis code itself, so pressing it after a change starts fresh attempts for every owed kind, and pressing it
    with nothing changed starts none. `owed` names what is waiting behind an analysis that is already running.
    """
    c = coordinator()
    job = c.lookup(jid)
    if job.get('status') not in ('completed', 'failed', 'cancelled'):
        abort(409, 'Analyses are queued once the run has stopped')
    return jsonify(c.analysis_coordinator.drain(jid)), 202


@blueprint.post('/api/jobs/<jid>/assessment/rescore')
def rescore_assessment(jid):
    """Re-score a finished run's stage 5 against its model's current references, as a second attempt.

    The Analysis graphs panel's second control, and not the same request as Recompute: that one re-queues analyses,
    which are derived from the run's outputs, while the score matrix and the distance distributions are the assessment
    *stage's* own outputs and were written once when the run ran. A run whose model carried no pairwise references
    therefore has nothing that Recompute could fix -- so this stages a new attempt beside the first (the attempt is
    prepared here, because its reference count and revision are the answer), starts it in a background thread the way
    the analysis queue starts a worker, and answers 202 with what it will score against.

    Every refusal is a `RunConflict` (409) or `RunBusy` (409) with its own sentence: no assessment stage, a run that
    has not finished, no CG trajectory, no current parameterization revision, a revision with no pairwise family, or an
    attempt already running for this run.
    """
    c = coordinator()
    attempt = assessment_rescore.prepare(c, jid)
    try:
        threading.Thread(target=assessment_rescore.run, args=(c, jid, attempt), daemon=True).start()
    except RuntimeError:
        # A thread that could not be started would otherwise leave the run claimed for the life of the process.
        assessment_rescore.release(jid)
        abort(503, 'The re-score could not be started; try again')
    return jsonify({'attempt': attempt['attempt'], 'directory': attempt['relative'],
                    'references': attempt['references']['files'],
                    'pairs': (attempt['references'].get('pairs') or {}).get('files'),
                    'revision': attempt['revision']['revision']}), 202


#: What a 2 s poller reads: the same attempt records with the heavy fields left out (`result`, `environment`,
#: `tools`, `command`). `payload` and `outputs` stay -- the Trajectory block needs them for a frame series -- and
#: `progress` is what makes a running attempt readable. The default answer is the whole record.
ANALYSIS_SUMMARY_FIELDS = ('id', 'kind', 'status', 'created_at', 'started_at', 'ended_at', 'error', 'directory',
                           'progress', 'payload', 'outputs', 'stable')


@blueprint.get('/api/jobs/<jid>/analyses')
def analyses_api(jid):
    c = coordinator()
    job = c.lookup(jid); tasks = job.get('analyses', [])
    for task in tasks:
        if task['status'] == 'running':
            try: task['progress'] = json.loads((c.run_path(job)/task['directory']/'progress.json').read_text())['phase']
            except (OSError, ValueError): pass
    if request.args.get('view') == 'summary':
        return jsonify([{key: task[key] for key in ANALYSIS_SUMMARY_FIELDS if key in task} for task in tasks])
    return jsonify(tasks)


def assessment_directories(root):
    """Every attempt of a run's assessment, newest first: `(attempt, directory)`.

    `5_assessment` is a CG run's first attempt, numbered 0, and `5_assessment@<n>` is a re-score's; a numbered pdc
    run's final assessment is `09_final_assessment` (and its re-score would be `09_final_assessment@<n>`). Both
    prefixes are read, so a run of either type -- or of the older pdc layout -- is answered. The number is what
    orders them, because a lexicographic order puts attempt 10 before attempt 9; anything else in the directory that
    merely starts with the same name is not an attempt and is not read.
    """
    attempts = []
    for prefix in layout.ASSESSMENT_DIRECTORIES:
        for path in Path(root).glob(f'{prefix}*'):
            if not path.is_dir():
                continue
            suffix = path.name[len(prefix):]
            if suffix == '':
                attempts.append((0, path))
            elif suffix.startswith('@') and suffix[1:].isdigit():
                attempts.append((int(suffix[1:]), path))
    return sorted(attempts, reverse=True)
