"""Analyses HTTP endpoints."""
import json
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, abort, jsonify, request

from dashboard.execution import workflow
from dashboard.models import mappings

from ...analysis.runs import transferability
from ...analysis.validation import carbohydrate_targets, targets
from .common import coordinator, json_object

blueprint = Blueprint('analyses', __name__)


def newest_comparison(c, job):
    """A run's newest published AA-vs-CG comparison: `(attempt, record, artifact)`.

    Raises `LookupError` with the reason when there is none: "nothing was published" and "the newest record
    names a file that does not exist" are different answers for a reader, and only the second is worth looking
    into. Both readers of a comparison come through here, so they cannot disagree about which attempt answered.
    """
    directory = c.run_path(job) / 'analyses/mapping-consistency'
    records = sorted(directory.glob('*/*/result.json'), key=lambda path: path.stat().st_mtime, reverse=True)
    if not records:
        raise LookupError('No AA vs CG comparison has been published for this run')
    attempt = records[0].parent
    record = json.loads(records[0].read_text())
    artifact = attempt / str(record.get('output_directory') or '') / 'analysis/mapping_consistency.json'
    if not artifact.is_file():
        raise LookupError(f'{attempt.name} names no published comparison file')
    return attempt, record, artifact


def newest_surfaces(c, job):
    """A run's newest published surfaces analysis: `(attempt, published, metadata_path, figure)`, or `None`.

    The solvent-accessible envelope analysis is its own kind with its own attempt, because it needs the atomistic
    trajectory, the mapped one and the simulated one and takes minutes rather than seconds. It publishes SASA
    statistics and a self-contained figure. Most runs have never had one -- it is queued by hand -- and that is a
    state a card has to be able to say, so this answers `None` rather than raising.
    """
    records = sorted((c.run_path(job) / 'analyses/surfaces').glob('*/*/result.json'),
                     key=lambda path: path.stat().st_mtime, reverse=True)
    for record_path in records:
        attempt = record_path.parent
        output = attempt / str(json.loads(record_path.read_text()).get('output_directory') or '')
        metadata = output / 'analysis/surfaces/metadata.json'
        if not metadata.is_file():
            # An attempt that names a file that is no longer there is not a published analysis; an older one
            # that still stands may be.
            continue
        published = json.loads(metadata.read_text())
        figure = output / str(published.get('comparison_html') or '')
        return attempt, published, metadata, (figure if figure.is_file() else None)
    return None


def newest_overlap(c, job):
    """A run's newest published bead-overlap analysis: `(attempt, published, report, figure_or_None)`, or `None`.

    Same shape as `newest_surfaces`, with one deliberate difference: an attempt whose figure is gone does not answer
    *unless nothing better exists*, and then it still answers with `figure=None` so the card can report that the
    analysis published and its figure is no longer on disk -- a sentence a run that was never analysed must not get.
    """
    records = sorted((c.run_path(job) / 'analyses/overlap').glob('*/*/result.json'),
                     key=lambda path: path.stat().st_mtime, reverse=True)
    without_figure = None
    for record_path in records:
        attempt = record_path.parent
        output = attempt / str(json.loads(record_path.read_text()).get('output_directory') or '')
        report = output / 'overlap.json'
        if not report.is_file():
            continue
        published = json.loads(report.read_text())
        figure = output / str(published.get('figure') or '')
        if figure.is_file():
            return attempt, published, report, figure
        if without_figure is None:
            without_figure = (attempt, published, report, None)
    return without_figure


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
    return jsonify({'run': jid, 'attempt': attempt.name,
                    'published_at': datetime.fromtimestamp(attempt.stat().st_mtime, timezone.utc).isoformat(),
                    'source': str(artifact.relative_to(c.RUNS)),
                    'molecule': job.get('molecule_id'), 'run_type': job.get('run_type'),
                    'profile': job.get('profile'), 'reference_run_id': job.get('reference_run_id'),
                    'summary': record.get('result'), 'comparison': json.loads(artifact.read_text()),
                    'surfaces': surfaces, 'overlap': overlap})


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
    return jsonify(json.loads((c.run_path(job)/path).read_text()) if path else targets.read(workflow.execution_root(c.run_path(job))))


@blueprint.get('/api/jobs/<jid>/distance-diagnostics')
def distance_diagnostics_api(jid):
    """Expose the additive Wasserstein/ring diagnostic for the Runs view."""
    c = coordinator()
    job = c.lookup(jid)
    assessment = workflow.execution_root(c.run_path(job)) / '5_assessment'
    path = assessment / 'distance_diagnostics_stratified.json'
    legacy = False
    if not path.is_file():
        # Runs written before the writer stopped emitting the duplicate name. Their pairs may predate
        # the per-pair `kind` classification, so the response says which file answered rather than
        # letting a reader assume the stratified one did.
        path = assessment / 'distance_diagnostics.json'; legacy = True
    if not path.is_file():
        abort(404, 'Distance diagnostics are not available for this run')
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        abort(422, 'Distance diagnostics are invalid')
    return jsonify(data=data, source=str(path.relative_to(c.run_path(job))), legacy=legacy)


@blueprint.get('/api/compare')
def compare_api():
    c = coordinator()
    ids = request.args.get('ids','').split(',')
    if not 2 <= len(ids) <= 4 or len(set(ids)) != len(ids): abort(400, 'Choose 2–4 different runs')
    comparisons = []
    for jid in ids:
        job = c.lookup(jid); root = workflow.execution_root(c.run_path(job)); reports = {}
        for name in ('validation.json','numerical_stability.json','refinement_score.json','experimental_targets.json'):
            candidates = [root/('5_assessment' if name == 'validation.json' else 'analysis')/name]
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

