"""Molecules HTTP endpoints."""
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from flask import Blueprint, abort, jsonify, request

from ...analysis.runs import references as aa_references
from ...execution import protocol
from ...execution.adapters import aa, cg
from ...execution.protocol import adapter_for, profile_for_run_type
from ...models import mappings
from ...models.mappings import context as mapping_context
from ...models.molecules import aa as aa_molecules
from ...models.molecules import detergent_registry
from .common import coordinator

blueprint = Blueprint('molecules', __name__)

#: The import contract: at most 8 MiB per submitted file, a plain file name, and a folder id the catalogue accepts.
IMPORT_LIMIT = 8 * 1024 * 1024
IMPORT_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_. -]{0,99}')
#: A CG folder's files are its contract's names -- `molecule.itp` + `molecule.gro` -- so the submitted names are
#: provenance rather than the spellings on disk. An AA folder keeps the names it was given, because discovery pairs
#: an `.itp` with its coordinates by name and there is no reason to rewrite a user's file.
CG_TOPOLOGY = 'molecule.itp'
CG_COORDINATES = 'molecule.gro'


def _import_file(payload, *, field, suffixes):
    """One submitted file: its validated name, its text and its bytes.

    The name is a name, not a path: a separator, a `..` anywhere or a leading dot is refused before the file is
    written, and the extension is checked against the kind so a `.pdb` is never read as a CG structure. The size is
    the decoded text's, because that is the bytes on disk; the request body may be larger only by JSON quoting.
    """
    if not isinstance(payload, dict):
        raise ValueError(f'{field} must be an object with name and text')
    name, text = payload.get('name'), payload.get('text')
    if (not isinstance(name, str) or not IMPORT_NAME.fullmatch(name) or '..' in name
            or Path(name).name != name):
        raise ValueError(f'{field}.name must be a plain file name, not a path')
    if Path(name).suffix.lower() not in suffixes:
        raise ValueError(f'{field}.name must end in ' + ' or '.join(suffixes))
    if not isinstance(text, str):
        raise ValueError(f'{field}.text must be the file\'s text')
    data = text.encode('utf-8')
    if len(data) > IMPORT_LIMIT:
        raise ValueError(f'{field}: {name} is {len(data)} bytes, over the 8 MiB input limit')
    return name, text, data


def _import_metadata(payload, *, kind, molecule_id, sources):
    """The `metadata.json` an import writes, or `None` when an AA import leaves generation to the catalogue.

    A CG import always writes one: `kind` is what classifies the folder, and the sources it records are the only
    place the submitted file names and digests survive the canonical folder names. An AA import with no metadata
    writes none, so the catalogue's own `ensure_metadata` produces the record it produces for any unlabelled folder.
    """
    metadata = payload.get('metadata')
    if metadata is None:
        return None if kind == 'aa' else {'kind': 'cg', 'name': molecule_id, 'sources': sources}
    if not isinstance(metadata, dict):
        raise ValueError('metadata must be a JSON object when given')
    if metadata.get('kind', kind) != kind:
        raise ValueError(f"metadata.kind says {metadata.get('kind')!r}, but this import is {kind!r}")
    record = {**metadata, 'kind': kind}
    if kind == 'cg':
        record.setdefault('name', molecule_id)
        record['sources'] = sources
    text = json.dumps(record, indent=2, allow_nan=False)
    if len(text.encode('utf-8')) > IMPORT_LIMIT:
        raise ValueError('metadata.json exceeds the 8 MiB input limit')
    return record


@blueprint.post('/api/molecules/import')
def import_molecule_api():
    """Write one validated molecule folder from submitted topology/coordinate text.

    The body is `{id, kind: 'aa'|'cg', topology: {name, text}, coordinates: {name, text}, metadata?}`. Validation
    happens in a hidden directory under `molecules/` through the catalogue's own `inspect`, so an import is accepted
    exactly when the catalogue would list it; only then is the folder renamed into `molecules/<id>`. A refusal names
    the issue and leaves the tree as it was: the temporary folder is removed, and an existing `molecules/<id>` is
    never replaced.
    """
    # The application's 1 MiB body cap is for form posts; two submitted molecules are up to 8 MiB each, plus JSON
    # quoting. The per-file limit is enforced on the decoded text above, so this only has to admit the envelope.
    request.max_content_length = 5 * IMPORT_LIMIT
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        abort(400, 'Expected a JSON object describing the molecule to import')
    try:
        molecule_id = aa_molecules.validate_id(payload.get('id'))
        kind = payload.get('kind')
        if kind not in ('aa', 'cg'):
            raise ValueError("kind must be 'aa' or 'cg'")
        topology_name, topology_text, topology_bytes = _import_file(
            payload.get('topology'), field='topology', suffixes=('.itp',))
        coordinates_name, coordinates_text, coordinates_bytes = _import_file(
            payload.get('coordinates'), field='coordinates', suffixes=('.gro', '.pdb') if kind == 'aa' else ('.gro',))
        sources = {'topology': {'name': topology_name, 'sha256': hashlib.sha256(topology_bytes).hexdigest()},
                   'coordinates': {'name': coordinates_name, 'sha256': hashlib.sha256(coordinates_bytes).hexdigest()}}
        metadata = _import_metadata(payload, kind=kind, molecule_id=molecule_id, sources=sources)
    except ValueError as exc:
        abort(400, str(exc))
    root = coordinator().ROOT / 'molecules'
    root.mkdir(parents=True, exist_ok=True)
    target = root / molecule_id
    if target.exists() or target.is_symlink():
        abort(409, f'molecules/{molecule_id} already exists: an import never replaces a molecule folder')
    # The temporary folder is a sibling of the target so the rename is one filesystem operation. Its name is hidden
    # and refuses the catalogue's id shape, so a crash before the rename leaves nothing the catalogue would list.
    temporary = Path(tempfile.mkdtemp(prefix='.import-', dir=root))
    try:
        folder = temporary / molecule_id
        folder.mkdir()
        if kind == 'cg':
            topology_name, coordinates_name = CG_TOPOLOGY, CG_COORDINATES
        (folder / topology_name).write_text(topology_text)
        (folder / coordinates_name).write_text(coordinates_text)
        if metadata is not None:
            (folder / 'metadata.json').write_text(json.dumps(metadata, indent=2, allow_nan=False))
        record = aa_molecules.inspect(temporary, molecule_id, generate_metadata=(kind == 'aa' and metadata is None))
        required = record['capabilities']['cg']['executable'] if kind == 'cg' else record['executable']
        if not record['valid'] or not required:
            issue = '; '.join(record['issues']) or '; '.join(record['capabilities'][
                'cg' if kind == 'cg' else 'aa_cg']['blockers'])
            raise ValueError(issue or 'the imported files did not validate')
        try:
            os.replace(folder, target)
        except OSError as exc:
            abort(409, f'molecules/{molecule_id} was not imported: {exc}')
    except ValueError as exc:
        abort(400, f'molecules/{molecule_id} was not imported: {exc}')
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return jsonify(molecule=record), 201


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


def _parameterization_argument():
    """The CG run's parameterization, from one JSON query parameter or from its individual fields.

    The panel names a saved mapping, a revision number, a starting-coordinate choice, a sugar entry or a
    composition. The queue route takes the same object in the request body; this spelling exists because readiness
    is a GET.
    """
    raw = request.args.get('parameterization')
    if raw:
        try:
            value = json.loads(raw)
        except ValueError:
            abort(400, 'parameterization must be a JSON object')
        if not isinstance(value, dict):
            abort(400, 'parameterization must be a JSON object')
        return value
    kind = request.args.get('parameterization_kind') or request.args.get('kind') or 'revision'
    value = {'kind': kind}
    if kind == 'revision':
        value['mapping_candidate'] = request.args.get('mapping_candidate')
        revision = request.args.get('revision')
        value['revision'] = int(revision) if revision not in (None, '') else None
        value['starting_coordinates'] = request.args.get('starting_coordinates') or 'stored'
    elif kind == 'reference':
        value['sugar_entry'] = request.args.get('sugar_entry') or 'SUCR'
    elif kind == 'composition':
        value['composition_id'] = request.args.get('composition_id')
    return value


def _requested_profile(default='standard'):
    """The profile a defaults request asks for, with this route's own fallback when it names none."""
    return _profile_argument() or default


@blueprint.get('/api/defaults')
def defaults_api():
    run_type=request.args.get('run_type')
    # The fallback is the run type's own profile, not this route's opinion (`protocol.profile_for_run_type`): the
    # panel fills every field from this answer and posts it back as explicit settings, so a default that differed from
    # the profile the run is stamped with would queue a different simulation than the one the form showed.
    if run_type=='aa_only':return jsonify(_with_force_fields(aa.stage_defaults(_requested_profile(profile_for_run_type(run_type)))))
    if run_type not in (None,'cg'):abort(400,'Unknown run type')
    kind = request.args.get('parameterization_kind') or request.args.get('kind')
    if run_type == 'cg' and kind in ('reference', 'composition'):
        from ...execution.adapters import cg_run
        try:
            return jsonify(_with_force_fields(cg_run.defaults_for(kind)))
        except ValueError as exc:
            abort(400, str(exc))
    profile = _requested_profile(profile_for_run_type(run_type or 'cg'))
    result=cg.stage_defaults(profile)
    if run_type=='cg':
        # The CG run's revision kind reuses an AA reference, so the AA half's durations are shown as the reference's
        # own and `aa_equil_ps` (whose halves are the AA equilibration stages) is dropped.
        result['values'].update(aa.stage_defaults(profile)['values']);result['values'].pop('aa_equil_ps',None)
        result['sources']['AA']=aa.VERSION
    return jsonify(_with_force_fields(result))


def _with_force_fields(result):
    """The force fields a run may choose, beside the defaults they imply.

    The list comes from the registry rather than from a copy held in the template, so adding an entry there is
    enough for the panel to offer it, and the temperature shown is the one that entry's parameterisation assumes.

    The help map travels with every defaults answer for the same reason: it is one server-side map keyed by setting
    name (`execution.settings_help`), quoted from the GROMACS manual and `gmx mdrun -h`, so the template states no
    help text of its own and the panel renders the same sentences the run type accepts.
    """
    from ...execution import forcefields, settings_help
    result['force_fields']=[{'name':entry.name,'label':entry.label,'temperature_k':entry.temperature_k,
                             'water':entry.water_file[:-len('.itp')]} for entry in
                            (forcefields.entry(name) for name in forcefields.names())]
    result['help'] = dict(settings_help.HELP)
    result['help_sources'] = dict(settings_help.SOURCES)
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
    run_type = request.args.get('run_type') or 'cg'
    if run_type not in ('aa_only', 'cg') and run_type not in protocol.RUN_TYPES:
        abort(400, 'Unknown run type')

    molecule = None
    # What a `cg` run will consume, read before the molecule is inspected: a composition's molecule is the saved CG
    # model, not an `molecules/` folder, so asking the atomistic catalogue about it would refuse a well-formed
    # selection as a missing molecule.
    parameterization = _parameterization_argument() if run_type == 'cg' else {}
    composition_model = run_type == 'cg' and (parameterization or {}).get('kind') == 'composition'
    if run_type in ('aa_only', 'cg') and 'molecule_id' in request.args and not composition_model:
        try: molecule = aa_molecules.inspect(c.ROOT / 'molecules', request.args['molecule_id'])
        except (OSError, ValueError) as exc: abort(400, str(exc))
        if not molecule['executable']:
            return jsonify(ready=False, checks=[], blockers=molecule['blockers'], molecule=molecule)

    candidate = None
    name = request.args.get('mapping_candidate')
    if name:
        try:
            context = (mapping_context.build_context(c.ROOT / 'molecules', request.args.get('molecule_id'))
                       if request.args.get('molecule_id') else None)
            candidate = mappings.get(name, context=context)
        except FileNotFoundError: abort(400, 'Selected mapping is unavailable')
        except (OSError, ValueError) as exc: abort(400, str(exc))

    # A composition names its own molecule; a caller that sends none is asking about the model it selected.
    selected_molecule = (request.args.get('molecule_id')
                         or (parameterization.get('composition_id') if composition_model else None)
                         or request.args.get('detergent') or 'DDM')
    metadata = {
        # The molecule the coarse-grained half checks, with the same DDM fallback the route has always had: a caller
        # that asks about a profile rather than a specific molecule is asking about the reference example, and the
        # protocol requires *some* molecule because a run cannot be checked without one.
        'molecule_id': selected_molecule,
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
    if run_type == 'cg':
        # The one user-facing CG run type carries the parameterization it will consume. The panel may send it as one
        # JSON query parameter or as its individual fields; both name the same payload the queue route accepts.
        parameterization = _parameterization_argument()
        metadata['parameterization'] = parameterization
        if parameterization.get('kind') == 'revision':
            name = parameterization.get('mapping_candidate') or parameterization.get('mapping')
            if name and not candidate:
                try:
                    context = (mapping_context.build_context(c.ROOT / 'molecules', request.args['molecule_id'])
                               if request.args.get('molecule_id') else None)
                    candidate = mappings.get(name, context=context)
                except FileNotFoundError: abort(400, 'Selected mapping is unavailable')
                except (OSError, ValueError) as exc: abort(400, str(exc))
                metadata['mapping_candidate'] = candidate
        if parameterization.get('kind') == 'reference':
            metadata['sugar_entry'] = parameterization.get('sugar_entry') or request.args.get('sugar_entry') or 'SUCR'
            metadata['settings'] = {'sugar_entry': metadata['sugar_entry']}
        if parameterization.get('kind') == 'composition':
            metadata['composition_id'] = parameterization.get('composition_id')
    # A copy, so decorating the answer for this page cannot reach back into whatever the adapter returned -- an
    # adapter that hands out a module-level dict would otherwise accumulate a molecule from every request.
    answer = dict(adapter_for(run_type).readiness(metadata))
    if molecule: answer['molecule'] = molecule
    return jsonify(answer)
