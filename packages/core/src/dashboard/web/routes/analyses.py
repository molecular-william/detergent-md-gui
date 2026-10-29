"""Analyses HTTP endpoints."""
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from dashboard.execution import assessment_rescore
from dashboard.models import mappings
from flask import Blueprint, abort, jsonify, request

from ...analysis.runs import layout, transferability
from ...analysis.validation import carbohydrate_targets, targets
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
    """A run's newest published surfaces analysis: `(attempt, published, metadata_path, figure)`, or `None`.

    The solvent-accessible envelope analysis is its own kind with its own attempt, because it needs the atomistic
    trajectory, the mapped one and the simulated one and takes minutes rather than seconds. It publishes SASA
    statistics and a self-contained figure. Most runs have never had one -- it is queued by hand -- and that is a
    state a card has to be able to say, so this answers `None` rather than raising.
    """
    return newest_published(c, job, 'surfaces', 'analysis/surfaces/metadata.json',
                            figure_key='comparison_html')


def newest_overlap(c, job):
    """A run's newest published bead-overlap analysis: `(attempt, published, report, figure_or_None)`, or `None`.

    Same shape as `newest_surfaces`, with one deliberate difference: an attempt whose figure is gone does not answer
    *unless nothing better exists*, and then it still answers with `figure=None` so the card can report that the
    analysis published and its figure is no longer on disk -- a sentence a run that was never analysed must not get.
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
    if kind == 'carbohydrate-validation':
        c = coordinator(); job = c.lookup(jid)
        if job.get('status') != 'completed': abort(409, 'Carbohydrate validation requires a completed source run')
        if payload.get('tier') not in ('setup', 'evidence'):
            abort(400, 'Validation tier must be setup or evidence')
        if payload.get('representation_mode') not in ('tc4', 'physical_only_ring_constrained'):
            abort(400, 'Unknown carbohydrate representation')
        mapping = payload.get('mapping_snapshot')
        molecule_id = payload.get('molecule_id') or job.get('molecule_id')
        dataset_id = payload.get('target_dataset_id')
        if not isinstance(mapping, dict) or not molecule_id or not dataset_id:
            abort(400, 'Validation requires molecule_id, mapping_snapshot, and target_dataset_id')
        try:
            mappings.validate_representation(mapping, payload['representation_mode'])
            dataset = carbohydrate_targets.validate_selection(c.ROOT, molecule_id, dataset_id)
        except (ValueError, OSError) as exc:
            abort(400, str(exc))
        payload = {**payload, 'molecule_id': molecule_id, 'target_dataset': dataset}
    task, status = coordinator().analysis_coordinator.queue(jid, kind, payload)
    return jsonify(task), status


@blueprint.get('/api/jobs/<jid>/mapping-consistency')
def mapping_consistency_api(jid):
    """The newest published AA-vs-CG comparison for one coarse-grained run.

    A published analysis writes into the output directory its attempt content-addressed, so this reads that
    record rather than recomputing anything: the panel shows what was published, and `attempt` plus
    `published_at` say which record answered. A run with no completed attempt is a 404 carrying the reason,
    because "not run yet" and "ran and failed" are different answers for a reader, and only the second one is
    worth looking into.
    """
    c = coordinator(); job = c.lookup(jid)
    try:
        attempt, record, artifact = newest_comparison(c, job)
    except LookupError as exc:
        abort(404, str(exc))
    # The envelope analysis is a separate kind on the same run, so it is read separately and its absence is
    # reported as a state rather than left for the card to discover as a broken frame.
    published_surfaces = newest_surfaces(c, job)
    if published_surfaces is None:
        surfaces = {'available': False,
                    'reason': 'No solvent-accessible surfaces analysis has been published for this run. It is '
                              'queued by hand, and it reads the atomistic, the mapped and the simulated '
                              'trajectories together.'}
    else:
        surfaces_attempt, published, metadata, figure = published_surfaces
        surfaces = {'available': True,
                    'attempt': surfaces_attempt.name,
                    'published_at': datetime.fromtimestamp(
                        surfaces_attempt.stat().st_mtime, timezone.utc).isoformat(),
                    'statistics': published.get('statistics') or {},
                    'rendering': published.get('rendering'),
                    'probe_nm': published.get('probe_nm'),
                    'validated': bool(published.get('scientifically_validated')),
                    # Relative to the run directory: the panel builds the artifact URL from this, and the route
                    # that serves it resolves against the run too.
                    'figure': str(figure.relative_to(c.run_path(job))) if figure else None,
                    'source': str(metadata.relative_to(c.RUNS))}
    # The bead-overlap analysis is another separate kind on the same run, read the same way and absent for the same
    # reason most runs have no surfaces analysis at all.
    published_overlap = newest_overlap(c, job)
    if published_overlap is None:
        overlap = {'available': False,
                   'reason': 'No bead-overlap analysis has been published for this run. It compares the coarse-grained '
                             'simulation with the atomistic reference it was built from, bead pair by bead pair, '
                             'and it is queued by hand.'}
    else:
        overlap_attempt, overlap_published, overlap_report, overlap_figure = published_overlap
        overlap = {'available': True,
                   'attempt': overlap_attempt.name,
                   'published_at': datetime.fromtimestamp(
                       overlap_attempt.stat().st_mtime, timezone.utc).isoformat(),
                   'residue': overlap_published.get('residue'),
                   'bead_names': overlap_published.get('bead_names') or [],
                   'pairs': overlap_published.get('pairs') or [],
                   'overlaps': overlap_published.get('overlaps') or [],
                   'per_bead_mean': overlap_published.get('per_bead_mean') or [],
                   'range_nm': overlap_published.get('range_nm'),
                   'frames': overlap_published.get('frames') or {},
                   'limitations': overlap_published.get('limitations') or [],
                   'validated': bool(overlap_published.get('scientifically_validated')),
                   'figure': str(overlap_figure.relative_to(c.run_path(job))) if overlap_figure else None,
                   'source': str(overlap_report.relative_to(c.RUNS))}
    # The bonded cross-check is a third separate kind on the same run, read the same way.
    published_cross_check = newest_cross_check(c, job)
    if published_cross_check is None:
        bonded_cross_check = {'available': False,
                              'reason': 'No bonded cross-check has been published for this run. It compares the run\'s '
                                        'own fitted topology with an independent equipartition estimate taken from '
                                        'the same frames, and it is queued by hand.'}
    else:
        check_attempt, check_published, check_report = published_cross_check
        bonded_cross_check = {'available': True,
                              'attempt': check_attempt.name,
                              'published_at': datetime.fromtimestamp(
                                  check_attempt.stat().st_mtime, timezone.utc).isoformat(),
                              'molecule': check_published.get('molecule'),
                              'temperature': check_published.get('temperature'),
                              'temperature_source': check_published.get('temperature_source'),
                              'threshold': check_published.get('threshold'),
                              'threshold_source': check_published.get('threshold_source'),
                              'ours_from': check_published.get('ours_from'),
                              'ours_provenance': check_published.get('ours_provenance'),
                              'frames_measured': check_published.get('frames_measured'),
                              'rows': check_published.get('rows') or [],
                              'unmeasured': check_published.get('unmeasured') or [],
                              'disagreements': check_published.get('disagreements') or [],
                              'limitations': check_published.get('limitations') or [],
                              'validated': bool(check_published.get('scientifically_validated')),
                              'source': str(check_report.relative_to(c.RUNS))}
    # The dihedral fit is a fourth separate kind on the same run, read the same way again.
    published_dihedral_fit = newest_dihedral_fit(c, job)
    if published_dihedral_fit is None:
        dihedral = {'available': False,
                    'reason': 'No dihedral fit has been published for this run. It fits every proper dihedral the '
                              'topology declares and lets a criterion choose how many harmonics each needs, and it '
                              'is queued by hand.'}
    else:
        fit_attempt, fit_published, fit_report = published_dihedral_fit
        dihedral = {'available': True,
                    'attempt': fit_attempt.name,
                    'published_at': datetime.fromtimestamp(
                        fit_attempt.stat().st_mtime, timezone.utc).isoformat(),
                    'molecule': fit_published.get('molecule'),
                    'temperature': fit_published.get('temperature'),
                    'temperature_source': fit_published.get('temperature_source'),
                    'criterion': fit_published.get('criterion'),
                    'ours_from': fit_published.get('ours_from'),
                    'ours_provenance': fit_published.get('ours_provenance'),
                    'frames_measured': fit_published.get('frames_measured'),
                    'rows': fit_published.get('rows') or [],
                    'unmeasured': fit_published.get('unmeasured') or [],
                    'disagreements': fit_published.get('disagreements') or [],
                    'limitations': fit_published.get('limitations') or [],
                    'validated': bool(fit_published.get('scientifically_validated')),
                    'source': str(fit_report.relative_to(c.RUNS))}
    return jsonify({'run': jid, 'attempt': attempt.name,
                    'published_at': datetime.fromtimestamp(attempt.stat().st_mtime, timezone.utc).isoformat(),
                    'source': str(artifact.relative_to(c.RUNS)),
                    'molecule': job.get('molecule_id'), 'run_type': job.get('run_type'),
                    'profile': job.get('profile'), 'reference_run_id': job.get('reference_run_id'),
                    'summary': record.get('result'), 'comparison': json.loads(artifact.read_text()),
                    'surfaces': surfaces, 'overlap': overlap, 'bonded_cross_check': bonded_cross_check,
                    'dihedral_fit': dihedral})


@blueprint.get('/api/runs/transferability')
def transferability_api():
    """The same bead-type pair side by side across molecules, from the comparisons already published.

    Nothing is recomputed: each run's own published comparison is the input, and the mapping it used comes from
    its own manifest, so every row here can be checked against the artifact it came from. The reader keys its
    rows by molecule, so two runs of one molecule are refused rather than silently merged. This compares our
    model across molecules and never against experiment, which the payload says in its own field.
    """
    c = coordinator()
    ids = [part for part in request.args.get('ids', '').split(',') if part]
    if not 2 <= len(ids) <= 8 or len(set(ids)) != len(ids):
        abort(400, 'Choose 2-8 different runs')
    entries, sources = {}, {}
    for jid in ids:
        job = c.lookup(jid)
        try:
            attempt, _, artifact = newest_comparison(c, job)
        except LookupError:
            abort(404, f'{jid} has no published AA vs CG comparison to compare across molecules')
        molecule = job.get('molecule_id') or job.get('detergent') or jid
        if molecule in entries:
            abort(400, f'{molecule} is in this comparison twice; choose one run per molecule')
        entries[molecule] = {'candidate': c.manifest_data(job).get('mapping_candidate') or {},
                             'report': json.loads(artifact.read_text())}
        sources[molecule] = {
            'run': jid, 'label': job.get('label'), 'attempt': attempt.name,
            'published_at': datetime.fromtimestamp(artifact.stat().st_mtime, timezone.utc).isoformat(),
            'source': str(artifact.relative_to(c.RUNS))}
    return jsonify({**transferability.compare(entries), 'sources': sources, 'runs': ids,
                    'diagnostic_only': True, 'scientifically_validated': False})


@blueprint.get('/api/jobs/<jid>/carbohydrate-validation')
def carbohydrate_validation_api(jid):
    c = coordinator(); job = c.lookup(jid)
    return jsonify([task for task in job.get('analyses', []) if task.get('kind') == 'carbohydrate-validation'])


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


@blueprint.get('/api/jobs/<jid>/analyses')
def analyses_api(jid):
    c = coordinator()
    job = c.lookup(jid); tasks = job.get('analyses', [])
    for task in tasks:
        if task['status'] == 'running':
            try: task['progress'] = json.loads((c.run_path(job)/task['directory']/'progress.json').read_text())['phase']
            except (OSError, ValueError): pass
    return jsonify(tasks)


@blueprint.get('/api/jobs/<jid>/targets')
def targets_get(jid):
    c = coordinator()
    job = c.lookup(jid); path = c.analysis_coordinator.dependencies(job).get('experimental_targets.json')
    return jsonify(json.loads((c.run_path(job)/path).read_text()) if path else targets.read(layout.stage_root(c.run_path(job))))


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


def assessment_directory(root):
    """The assessment stage directory a run wrote, newest layout first, or its CG spelling when neither is there."""
    for name in layout.ASSESSMENT_DIRECTORIES:
        path = Path(root) / name
        if path.is_dir():
            return path
    return Path(root) / layout.ASSESSMENT_DIRECTORIES[-1]


@blueprint.get('/api/jobs/<jid>/distance-diagnostics')
def distance_diagnostics_api(jid):
    """Expose the additive Wasserstein/ring diagnostic for the Runs view.

    Read from the newest assessment attempt that wrote one: a re-score's `5_assessment@1/` holds the diagnostics of the
    references it was scored against, and answering from the first attempt would show the panel the numbers the
    re-score replaced. An attempt that wrote none falls through to the one before it, so a re-score that failed in the
    tool leaves the run's own publication standing rather than turning the panel blank.
    """
    c = coordinator()
    job = c.lookup(jid)
    root = layout.stage_root(c.run_path(job))
    found = None
    for attempt, assessment in assessment_directories(root):
        strat = assessment / 'distance_diagnostics_stratified.json'
        legacy_path = assessment / 'distance_diagnostics.json'
        if strat.is_file():
            found = (attempt, strat, False)
            break
        if legacy_path.is_file():
            # Runs written before the writer stopped emitting the duplicate name. Their pairs may predate the
            # per-pair `kind` classification, so the response says which file answered rather than letting a
            # reader assume the stratified one did.
            found = (attempt, legacy_path, True)
            break
    if found is None:
        abort(404, 'Distance diagnostics are not available for this run')
    attempt, path, legacy = found
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        abort(422, 'Distance diagnostics are invalid')
    return jsonify(data=data, source=str(path.relative_to(c.run_path(job))), legacy=legacy, attempt=attempt)


@blueprint.get('/api/compare')
def compare_api():
    c = coordinator()
    ids = request.args.get('ids','').split(',')
    if not 2 <= len(ids) <= 4 or len(set(ids)) != len(ids): abort(400, 'Choose 2–4 different runs')
    comparisons = []
    for jid in ids:
        job = c.lookup(jid); root = layout.stage_root(c.run_path(job)); reports = {}
        for name in ('validation.json','numerical_stability.json','refinement_score.json','experimental_targets.json'):
            candidates = [(assessment_directory(root) if name == 'validation.json' else root/'analysis')/name]
            candidates += [c.run_path(job)/p for t in job.get('analyses',[]) if t['status']=='completed' for p in t.get('outputs',[]) if Path(p).name==name]
            for path in reversed(candidates):
                if path.is_file():
                    try: reports[name] = {'source':str(path.relative_to(c.run_path(job))), 'data':json.loads(path.read_text())}
                    except (OSError, ValueError): pass
                    break
        sasa = {}
        for label in ('AA','CG'):
            path = root/f'6_SASA/{label}/SASA-{label}.xvg'
            if path.is_file():
                try:
                    import math
                    count, mean = 0, 0.0
                    with path.open() as stream:
                        for line in stream:
                            if not line.strip() or line.lstrip().startswith(('#','@')): continue
                            value = float(line.split()[1])
                            if not math.isfinite(value) or value < 0: raise ValueError('Invalid SASA measurement')
                            count += 1; mean += (value-mean)/count
                    if count: sasa[label] = {'mean_nm2':mean,'frames':count, 'source':str(path.relative_to(c.run_path(job)))}
                except (ValueError, IndexError): pass
        comparisons.append({'id':jid,'label':job.get('label',jid),'status':job['status'],'settings':job.get('settings',{}),'reports':reports,'sasa':sasa,'scientifically_validated':False})
    return jsonify(runs=comparisons, interpretation='Native units only. Different settings and sampling durations are not directly comparable. Missing values remain missing.')

