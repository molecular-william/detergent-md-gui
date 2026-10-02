"""Molecules HTTP endpoints."""
import json

from flask import Blueprint, abort, jsonify, request

from ...analysis.runs import references as aa_references
from ...execution.adapters import aa, cg
from ...models import mappings
from ...models.mappings import context as mapping_context
from ...models.molecules import aa as aa_molecules
from .common import coordinator

blueprint = Blueprint('molecules', __name__)

@blueprint.get('/api/references')
def references_api():
    c = coordinator()
    references = []
    for job in c.database().all():
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


def _requested_profile(default='standard'):
    """The profile a defaults request asks for. A typo is reported, not silently standard."""
    profile = request.args.get('profile') or default
    try:
        aa.validate_profile(profile)
    except ValueError as exc:
        abort(400, str(exc))
    return profile


@blueprint.get('/api/defaults')
def defaults_api():
    run_type=request.args.get('run_type')
    if run_type=='aa_only':return jsonify(_with_force_fields(aa.stage_defaults(_requested_profile())))
    if run_type == 'cg_composition':
        result = cg.stage_defaults(_requested_profile('draft-smoke'))
        result['values'].update({'cg_equil_ps': 10.0, 'cg_production_ps': 50.0})
        return jsonify(_with_force_fields(result))
    if run_type not in (None,'aa_cg'):abort(400,'Unknown run type')
    result=cg.stage_defaults(_requested_profile())
    if run_type=='aa_cg':
        # The AA half at this profile, which is what the run will use: aa_equil_ps is
        # derived from the two AA equilibration durations, so the form shows those.
        result['values'].update(aa.stage_defaults(_requested_profile())['values']);result['values'].pop('aa_equil_ps',None)
        result['sources']['AA']=aa.VERSION
    return jsonify(_with_force_fields(result))


def _with_force_fields(result):
    """The force fields a run may choose, beside the defaults they imply.

    The list comes from the registry rather than from a copy held in the template, so adding an entry there is
    enough for the panel to offer it, and the temperature shown is the one that entry's parameterisation assumes.
    """
    from ...execution import forcefields
    result['force_fields']=[{'name':entry.name,'label':entry.label,'temperature_k':entry.temperature_k,
                             'water':entry.water_file[:-len('.itp')]} for entry in
                            (forcefields.entry(name) for name in forcefields.names())]
    return result


@blueprint.get('/api/readiness')
def readiness_api():
    c = coordinator()
    run_type=request.args.get('run_type')
    if run_type == 'pdc':
        # The complex panel reads this before it queues a build, so a build that cannot start says why in the panel
        # rather than in a run that dies at stage one. An empty micelle is a stated choice, so a missing protein is
        # reported as an absence rather than a blocker.
        from ...execution.adapters import pdc
        return jsonify(pdc.readiness(protein=request.args.get('protein') or None,
                                     template=request.args.get('template') or None,
                                     project_root=c.ROOT))
    if run_type == 'cg_composition':
        from ...execution.adapters.composition import readiness
        composition_id = request.args.get('composition_id')
        if not composition_id: return jsonify(ready=False, checks=[], blockers=['Select a saved composition'])
        return jsonify(readiness(composition_id, c.ROOT))
    if run_type not in (None,'aa_only','aa_cg'):abort(400,'Unknown run type')
    if run_type=='aa_only':return jsonify(aa.readiness(c.ROOT/'molecules',request.args.get('molecule_id')))
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
    ready = cg.readiness(request.args.get('molecule_id') or request.args.get('detergent', 'DDM'),
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
                aa_ready=aa.readiness(c.ROOT/'molecules',request.args.get('molecule_id'))
                ready.setdefault('blockers',[]).extend(aa_ready['blockers'])
        except (OSError,ValueError) as exc:ready.setdefault('blockers',[]).append(str(exc))
        ready['ready']=ready.get('ready',False) and not ready.get('blockers')
    if molecule: ready['molecule'] = molecule
    return jsonify(ready)
