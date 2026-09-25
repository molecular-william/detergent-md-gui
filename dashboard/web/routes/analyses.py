"""Analyses HTTP endpoints."""
import json
from pathlib import Path

from flask import Blueprint, abort, jsonify, request

from dashboard.execution import workflow
from dashboard.models import mappings

from ...analysis.validation import carbohydrate_targets, targets
from .common import coordinator, json_object

blueprint = Blueprint('analyses', __name__)

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
    if not path.is_file(): path = assessment / 'distance_diagnostics.json'
    if not path.is_file():
        abort(404, 'Distance diagnostics are not available for this run')
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        abort(422, 'Distance diagnostics are invalid')
    return jsonify(data=data, source=str(path.relative_to(c.run_path(job))))


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

