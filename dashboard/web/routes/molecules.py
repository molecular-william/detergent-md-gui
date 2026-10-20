"""Molecules HTTP endpoints."""
import json

from flask import Blueprint, abort, jsonify, request

from ...analysis.runs import references as aa_references
from ...execution.adapters import aa, cg
from ...execution.protocol import adapter_for
from ...models import mappings
from ...models.mappings import context as mapping_context
from ...models.molecules import aa as aa_molecules
from ...models.molecules import detergent_registry
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


@blueprint.get('/api/detergents')
def detergents_api():
    """The molecules the detergent registry names, for the protein-detergent panel's list.

    `molecules/` ships DDM beside Maltose, Sucrose and Trehalose, and the pdc pipeline builds its belt out of a
    detergent's own beads: a sugar offered here would be a run that cannot be built. The filter is the registry's
    own file (`detergents.json`), read at request time, so the list cannot drift from the file it comes from --
    and so adding an entry to that file is enough for the panel to offer it.
    """
    c = coordinator()
    return jsonify(detergents=detergent_registry.select(aa_molecules.catalogue(c.ROOT/'molecules'), c.ROOT))


def _profile_argument():
    """The profile the request names, validated; `None` when it names none.

    A typo is reported, not silently standard. `None` is a real answer for a caller that wants the run type to
    choose: the readiness list is asked about the profile that run type actually runs under, and the adapter owns
    that string (`cg.AA_CG_PROFILE`), so a route-level `standard` here would put a blocker in front of a run type
    that has never run under it.
    """
    profile = request.args.get('profile')
    if not profile:
        return None
    try:
        aa.validate_profile(profile)
    except ValueError as exc:
        abort(400, str(exc))
    return profile


def _requested_profile(default='standard'):
    """The profile a defaults request asks for, with this route's own fallback when it names none."""
    return _profile_argument() or default


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
    """Can this run start, asked of the run type rather than of each adapter in turn.

    This route used to reach past the protocol: `pdc.readiness(...)`, `composition.readiness(...)`,
    `aa.readiness(...)`, `cg.readiness(...)`, and for `aa_cg` it collected two of those answers and merged them by
    hand. That put a run type's prerequisites in a page, and gave the same question two places to drift apart. Every
    branch now builds the metadata a run carries and asks the protocol once.

    Two things stay here because they are the page's business and not the run type's: the *molecule* it inspects, so
    a reader sees which structure was judged, and the *mapping candidate* it loads from a name, because that is a
    lookup in the mapping store rather than a rule about runs.
    """
    c = coordinator()
    run_type = request.args.get('run_type') or 'aa_cg'
    if run_type not in ('aa_only', 'aa_cg', 'cg_composition', 'pdc'):
        abort(400, 'Unknown run type')

    molecule = None
    if run_type in ('aa_only', 'aa_cg') and 'molecule_id' in request.args:
        try: molecule = aa_molecules.inspect(c.ROOT / 'molecules', request.args['molecule_id'])
        except (OSError, ValueError) as exc: abort(400, str(exc))
        if not molecule['executable']:
            return jsonify(ready=False, checks=[], blockers=molecule['blockers'], molecule=molecule)

    candidate = None
    name = request.args.get('mapping_candidate')
    if name:
        try:
            context = (mapping_context.build_context(c.ROOT / 'molecules', request.args['molecule_id'])
                       if request.args.get('molecule_id') else None)
            candidate = mappings.get(name, context=context)
        except FileNotFoundError: abort(400, 'Selected mapping is unavailable')
        except (OSError, ValueError) as exc: abort(400, str(exc))

    metadata = {
        # The molecule the coarse-grained half checks, with the same DDM fallback the route has always had: a caller
        # that asks about a profile rather than a specific molecule is asking about the reference example, and the
        # protocol requires *some* molecule because a run cannot be checked without one.
        'molecule_id': request.args.get('molecule_id') or request.args.get('detergent') or 'DDM',
        'method': request.args.get('method', 'fast_forward'),
        # No route-level default: the run type's own adapter names the profile it runs under, and a `standard`
        # here is what put the standard-parameterization blocker in front of every AA-to-CG run.
        'profile': _profile_argument(),
        'mapping_candidate': candidate,
        'molecule_root': c.ROOT / 'molecules',
        'runs_root': c.RUNS,
        'reference_run_id': request.args.get('reference_run_id'),
        'composition_id': request.args.get('composition_id'),
        'protein': request.args.get('protein') or None,
        'template': request.args.get('template') or None,
        'project_root': c.ROOT,
    }
    # A copy, so decorating the answer for this page cannot reach back into whatever the adapter returned -- an
    # adapter that hands out a module-level dict would otherwise accumulate a molecule from every request.
    answer = dict(adapter_for(run_type).readiness(metadata))
    if molecule: answer['molecule'] = molecule
    return jsonify(answer)
