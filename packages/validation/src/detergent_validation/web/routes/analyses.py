"""The validation panel's endpoints: the comparison and its diagnostics, and the carbohydrate queue read.

The body contract for a carbohydrate-validation request lives here too. Readers and helpers are the engine's
(`dashboard.web.routes.analyses`): both readers of a published comparison come through `newest_comparison`, and the
engine keeps them because the engine's own route module registers first.
"""
import json
from datetime import datetime, timezone

from dashboard.analysis.runs import layout
from dashboard.analysis.validation import carbohydrate_targets
from dashboard.models import mappings
from dashboard.web.routes.analyses import assessment_directories, newest_comparison, newest_cross_check, newest_dihedral_fit, newest_overlap, newest_surfaces
from dashboard.web.routes.common import coordinator
from detergent_validation.analysis.runs import transferability
from flask import Blueprint, abort, jsonify, request

blueprint = Blueprint('validation_analyses', __name__)


def payload(c, jid, body):
    """Validate and derive one carbohydrate-validation request; abort with the reason it cannot run."""
    job = c.lookup(jid)
    if job.get('status') != 'completed':
        abort(409, 'Carbohydrate validation requires a completed source run')
    if body.get('tier') not in ('setup', 'evidence'):
        abort(400, 'Validation tier must be setup or evidence')
    if body.get('representation_mode') not in ('tc4', 'physical_only_ring_constrained'):
        abort(400, 'Unknown carbohydrate representation')
    mapping = body.get('mapping_snapshot')
    molecule_id = body.get('molecule_id') or job.get('molecule_id')
    dataset_id = body.get('target_dataset_id')
    if not isinstance(mapping, dict) or not molecule_id or not dataset_id:
        abort(400, 'Validation requires molecule_id, mapping_snapshot, and target_dataset_id')
    try:
        mappings.validate_representation(mapping, body['representation_mode'])
        dataset = carbohydrate_targets.validate_selection(c.ROOT, molecule_id, dataset_id)
    except (ValueError, OSError) as exc:
        abort(400, str(exc))
    return {**body, 'molecule_id': molecule_id, 'target_dataset': dataset}


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
