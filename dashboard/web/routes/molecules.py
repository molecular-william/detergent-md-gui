"""Molecules HTTP endpoints."""
import json
from flask import abort
from dashboard.execution import aa_workflow, workflow
from dashboard.models import aa_molecules, mappings, mapping_context, compositions
from dashboard.analysis import aa_references
from flask import Blueprint, jsonify, request
from .common import coordinator

blueprint = Blueprint('molecules', __name__)

@blueprint.get('/api/references')
def references_api():
    c = coordinator()
    references = []
    for job in c.load():
        if job.get('status') != 'completed' or job.get('run_type')!='aa_only' or not job.get('reference_eligible'):
            continue
        molecule_id=request.args.get('molecule_id')
        if molecule_id and job.get('molecule_id')!=molecule_id:continue
        try:
            selected=aa_molecules.selection(c.ROOT/'molecules',molecule_id,run_type='aa_only') if molecule_id else None
            data=aa_references.verify(c.run_path(job),molecule_snapshot=selected)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        references.append({'id': job['id'], 'label': job.get('label') or job['id'], 'created': job.get('created'), 'run_type':'aa_only','settings':data['settings'],'protocol_version':data['protocol_version'],'frames':data['frames'],'scientifically_validated':False,'reference_eligible':True})
    return jsonify(references=references)


@blueprint.get('/api/molecules')
def molecules_api():
    c = coordinator()
    return jsonify(molecules=aa_molecules.catalogue(c.ROOT/'molecules'))


@blueprint.get('/api/defaults')
def defaults_api():
    run_type=request.args.get('run_type')
    if run_type=='aa_only':return jsonify(aa_workflow.stage_defaults())
    if run_type == 'cg_composition':
        result = workflow.stage_defaults(request.args.get('profile','draft-smoke'))
        result['values'].update({'cg_equil_ps': 10.0, 'cg_production_ps': 50.0})
        return jsonify(result)
    if run_type not in (None,'aa_cg'):abort(400,'Unknown run type')
    result=workflow.stage_defaults(request.args.get('profile','standard'))
    if run_type=='aa_cg':
        result['values'].update(aa_workflow.DEFAULTS);result['values'].pop('aa_equil_ps',None)
        result['sources']['AA']=aa_workflow.VERSION
    return jsonify(result)


@blueprint.get('/api/readiness')
def readiness_api():
    c = coordinator()
    run_type=request.args.get('run_type')
    if run_type == 'cg_composition':
        from dashboard.execution.composition_workflow import readiness
        composition_id = request.args.get('composition_id')
        if not composition_id: return jsonify(ready=False, checks=[], blockers=['Select a saved composition'])
        return jsonify(readiness(composition_id, c.ROOT))
    if run_type not in (None,'aa_only','aa_cg'):abort(400,'Unknown run type')
    if run_type=='aa_only':return jsonify(aa_workflow.readiness(c.ROOT/'molecules',request.args.get('molecule_id')))
    molecule = None
    if 'molecule_id' in request.args:
        try: molecule = aa_molecules.inspect(c.ROOT/'molecules', request.args['molecule_id'])
        except (OSError, ValueError) as exc: abort(400, str(exc))
        if not molecule['executable']:
            return jsonify(ready=False, checks=[], blockers=molecule['blockers'], molecule=molecule)
    name = request.args.get('mapping_candidate')
    try:
        context = (mapping_context.build_context(c.ROOT / 'molecules', request.args['molecule_id'])
                   if request.args.get('molecule_id') else None)
        candidate = mappings.get(name, context=context) if name else None
    except FileNotFoundError: abort(400, 'Selected mapping is unavailable')
    except (OSError, ValueError) as exc: abort(400, str(exc))
    c = coordinator()
    ready = workflow.readiness(request.args.get('molecule_id') or request.args.get('detergent', 'DDM'),
                               request.args.get('method', 'fast_forward'),
                               request.args.get('profile', 'standard'),
                               candidate,
                               molecule_root=c.ROOT / 'molecules')
    if run_type=='aa_cg':
        try:
            if request.args.get('reference_run_id'):
                selected=aa_molecules.selection(c.ROOT/'molecules',request.args.get('molecule_id'))
                aa_references.resolve(c.RUNS,request.args['reference_run_id'],molecule_snapshot=selected)
            else:
                aa_ready=aa_workflow.readiness(c.ROOT/'molecules',request.args.get('molecule_id'))
                ready.setdefault('blockers',[]).extend(aa_ready['blockers'])
        except (OSError,ValueError) as exc:ready.setdefault('blockers',[]).append(str(exc))
        ready['ready']=ready.get('ready',False) and not ready.get('blockers')
    if molecule: ready['molecule'] = molecule
    return jsonify(ready)
