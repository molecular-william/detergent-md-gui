"""Protein-detergent complex endpoints: the catalogue the panel builds its setup from, and the system it built."""
import json
import uuid
from pathlib import Path
from urllib.parse import unquote

from dashboard import paths
from dashboard.analysis.runs import layout, structures
from dashboard.execution.adapters.micelle import run_micelle_job
from dashboard.web.routes.common import coordinator, json_object
from detergent_pdc.execution.adapters import pdc, pdc_import
from flask import Blueprint, Response, abort, current_app, jsonify, request

blueprint = Blueprint('pdc', __name__)

SETUP_STAGE = 'system'
SYSTEM_STRUCTURE = 'system.gro'
# The centre of the transmembrane slab along z. An OPM structure arrives already oriented, with the bilayer the
# xy-plane through the origin, so the centre is a property of the coordinate frame rather than a number to measure.
SLAB_CENTRE_NM = 0.0


def setup_root(job_id) -> Path:
    """A run's stage root -- `stages/` when it exists, the run root for a legacy run -- or a 404.

    The stage root is what every pdc built-system path is relative to, in both layouts: the numbered `02_system/` of a
    current run and the root-level `1_system/` of the two runs written before the numbering.
    """
    c = coordinator()
    try:
        return layout.stage_root(c.run_path(c.lookup(job_id)))
    except (KeyError, OSError):
        abort(404, 'unknown run')


@blueprint.get('/api/pdc/catalog')
def pdc_catalog():
    return jsonify(pdc.catalog(coordinator().ROOT))


def model_entry(record):
    """One saved mapping as a model the picker can offer, or `None` for one a build could not reuse.

    A model is a mapping *and* the parameterization fitted to it. The mapping decides the beads and where they sit;
    its parameterization decides the bonded terms when it carries one, and a mapping without one is built on terms
    derived from the Martini 3 references. The join is by **content hash and never by name**: a revision is keyed by
    the mapping's content identity, so a renamed candidate keeps its fit -- and the record's `owners` list is inferred
    from those hashes rather than being an address that could be matched on.

    `can_reuse` is the only reason a saved mapping is left out. It is the same verdict the CG half's picker reads and
    `models/molecules/draft.py` refuses a build on, so this list cannot offer a mapping the build would reject at
    preparation -- and the rule is not restated anywhere else.

    `label` is the sentence the picker shows, built here so that what a model carries has one home: JavaScript
    renders it and never decides fitted from derived. `terms` is `total_terms` (which excludes `virtual_sitesn`, the
    count a panel prints) while `term_kinds` is the full row of counts `pdc.prepare` records.
    """
    from dashboard.models.bonded import parameterization

    if not isinstance(record, dict) or record.get('error'):
        return None
    if (record.get('validation') or {}).get('can_reuse') is not True:
        return None
    content_hash = parameterization.content_identity(record)
    current = parameterization.one(content_hash).get('current') or {}
    fitted = None
    if current:
        fitted = {'revision': current.get('revision'), 'terms': parameterization.total_terms(current),
                  'term_kinds': parameterization.term_counts(current), 'engine': current.get('engine'),
                  'created_at': current.get('created_at'),
                  'scientifically_validated': bool(current.get('scientifically_validated'))}
    beads = len(record.get('beads') or [])
    name = record.get('name') or record.get('file')
    label = (f'{name} \u00b7 revision {fitted["revision"]} \u00b7 {beads} beads \u00b7 {fitted["terms"]} terms \u00b7 '
             f'fitted {str(fitted["created_at"] or "")[:10]}') if fitted else f'{name} \u00b7 {beads} beads \u00b7 derived terms'
    return {'file': record.get('file'), 'name': record.get('name'), 'beads': beads, 'content_hash': content_hash,
            'fitted': fitted, 'label': label}


@blueprint.get('/api/pdc/models')
def pdc_models():
    """The detergent's saved mappings as the models a build can choose between, fitted ones first.

    This is what the panel's picker reads, and it exists because the picker used to offer mapping *files*: a reader
    chose an opaque name and could not see that one of the candidates carried a fitted parameterization while another
    would be built on derived terms. So the list is filtered to the chosen detergent (a belt is built from that
    detergent's own beads), joined to the parameterization store by content hash, and labelled with what each model
    carries -- `fitted` first, newest first, because a model with a fit is the one a run should consume.

    A missing or unknown `molecule_id` is a **400** that names it: the list is one detergent's models, and there is no
    honest default for which detergent a caller meant.
    """
    from dashboard.models import mappings
    from dashboard.models.molecules import detergent_registry
    from dashboard.web.routes.common import query_context

    root = coordinator().ROOT
    molecule = (request.args.get('molecule_id') or '').strip()
    if not molecule:
        return jsonify({'error': 'molecule_id is required: the models offered are one detergent\u2019s own saved '
                                 'mappings, so the list cannot be answered without one'}), 400
    if not detergent_registry.is_detergent(molecule, root):
        return jsonify({'error': f'{molecule} is not a detergent in {detergent_registry.REGISTRY_FILE}, so it has no '
                                 f'model this panel can build a belt from: a belt is made of the detergent\u2019s '
                                 f'own beads'}), 400
    if not (Path(root) / 'molecules' / molecule).is_dir():
        return jsonify({'error': f'{molecule} has no folder under molecules/, so it has no saved CG mapping and no '
                                 f'model to offer'}), 400
    # The same context `/api/mappings?view=summary&molecule_id=` scopes its list by, so the two agree about which
    # candidates belong to this molecule -- including the source snapshot each one was saved against.
    rows = []
    for record in mappings.list_candidates(context=query_context(molecule)):
        entry = model_entry(record)
        if entry is not None:
            rows.append((entry, record.get('created_at') or ''))
    # Fitted models first, each group newest first. A fitted model is dated by the fit it carries (a mapping fitted
    # yesterday is the newer model however old the mapping is); a derived one by when its mapping was saved.
    fitted = sorted((row for row in rows if row[0]['fitted']), key=lambda row: row[0]['fitted']['created_at'] or '',
                    reverse=True)
    derived = sorted((row for row in rows if not row[0]['fitted']), key=lambda row: row[1], reverse=True)
    return jsonify({'molecule': molecule, 'models': [entry for entry, _ in fitted + derived]})


@blueprint.post('/api/pdc/proteins/import')
def pdc_import_structure():
    """Fetch one structure from OPM into the workspace, where it stays local.

    The id becomes a file name, so it is validated before anything else happens -- including before the network is
    touched, which a test pins. A structure that is already here is answered from disk rather than fetched again: a
    second import is a question about a file, and the sidecar it came with is not overwritten either.
    """
    payload = request.get_json(silent=True) or {}
    destination = paths.current().proteins
    try:
        pdbid = pdc_import.canonical_id(payload.get('pdbid') or '')
    except ValueError as error:
        return jsonify({'error': str(error)}), 400

    structure = pdc_import.structure_path(destination, pdbid)
    if structure.is_file():
        record = pdc_import.read_sidecar(structure) or {'pdbid': pdbid, 'half_thickness_nm': None}
        return jsonify({**record, 'already_present': True}), 200
    try:
        record = pdc_import.import_structure(pdbid, destination, fetcher=current_app.config.get('PDC_FETCHER'))
    except (OSError, ValueError) as error:
        # A fetch that failed is upstream's problem, not the caller's bad request -- and nothing was written.
        return jsonify({'error': f'{pdbid} could not be fetched: {error}'}), 502
    return jsonify(record), 201


def detergent_topology(root: Path):
    """The run's detergent moleculetype, read from the stage that holds the system or from the one that wrote it.

    The location is the build's own rule -- beside the stage, or in the stage that wrote it -- so the built-system
    view draws the bonds the run simulated. A moleculetype that cannot be read is reported as none; a view with
    coordinates still has something to show.
    """
    directory = layout.stage_dir(root, SETUP_STAGE)
    path = None
    if directory is not None:
        candidates = [directory / pdc.DETERGENT_TOPOLOGY,
                      *sorted(directory.resolve().parent.glob(f'*/{pdc.DETERGENT_TOPOLOGY}'))]
        path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        return None
    try:
        return structures.read_moleculetype(path)
    except (OSError, ValueError):
        return None


@blueprint.get('/api/pdc/<job_id>/system.pdb')
def pdc_system_pdb(job_id):
    """The built system as a viewer file. 404 with a reason until a build has produced one.

    The panel shows the system as set up rather than as imagined, so this serves the coordinates a stage wrote,
    through `structures.system_pdb`: one residue per molecule, and the run's own moleculetype's bonds as CONECT
    records. Without them the panel falls back to NGL's distance-based guess -- measured at 90 bonds on a frame the
    model bonds 60 ways. Before that stage has run there is no picture to show, and saying so is better than an
    empty box.
    """
    root = setup_root(job_id)
    structure = layout.stage_path(root, SETUP_STAGE, SYSTEM_STRUCTURE)
    try:
        atoms = structures.read_gro(structure)
    except (OSError, ValueError, TypeError) as error:
        abort(404, f'no built system to show yet: {error}')
    return Response(structures.system_pdb(atoms, topology=detergent_topology(root)), mimetype='text/plain')


def catalogue_protein(root, entry):
    """One protein from the catalogue, by whichever of its names the caller used, or a refusal that says which.

    An entry's id and path are file paths, and a path is not a natural URL segment: an absolute one loses its
    leading slash on the way through a URL -- `%2F` is decoded before routing, so the doubled slash is redirected
    away -- which is why the comparison ignores a leading slash on either side. The stem resolves too, which is
    what a caller who has not read the catalogue will reach for. Two entries that answer to the same name are
    refused rather than picked between: they are two different structures, and a slab read from the wrong one would
    be indistinguishable from a right one.
    """
    wanted = unquote(entry).lstrip('/')
    matches = [item for item in pdc.catalog(root)['proteins']
               if wanted in (str(item.get('id') or '').lstrip('/'), str(item.get('path') or '').lstrip('/'),
                             item.get('name'))]
    if not matches:
        abort(404, f'no protein entry named {entry!r} in the catalogue')
    if len(matches) > 1:
        abort(400, f'{len(matches)} catalogue entries answer to {entry!r}; name the protein by its id')
    return matches[0]


def saved_mappings(molecule_id):
    """Every saved CG mapping for a molecule, as `(file name, record)`.

    Read the way a run reads one -- `pdc.prepare` resolves a mapping through the same store, by file name -- and
    without the mapping validator: this is a question about a bead's size class, and an unrelated validation finding
    must not hide the mapping that would actually build a run.
    """
    from dashboard.models.mappings import store

    found = []
    for name, path in store.candidate_paths().items():
        try:
            record = json.loads(Path(path).read_text())
        except (OSError, ValueError):
            continue
        if isinstance(record, dict) and record.get('molecule_id') == molecule_id:
            found.append((name, record))
    return found


@blueprint.get('/api/pdc/proteins/<path:entry>/encapsulation')
def pdc_encapsulation(entry):
    """The hydrophobic-surface sizing aid: the numbers, with the method and caveat they came from.

    The panel renders what the server decided rather than repeating the arithmetic in JavaScript. A protein whose
    structure states no membrane has no slab and is refused with that reason; a detergent with no saved mapping has
    no head bead size class and is refused with that one. `molecule_id` is the detergent, `aggregation_number` the
    count the reader asked for, and `chains` (comma-separated, or repeated) the subunits to size -- so the number
    describes the object that will be simulated rather than the whole deposited file. A chain the structure does not
    have is refused, not dropped.
    """
    from detergent_pdc.analysis.runs import encapsulation

    root = coordinator().ROOT
    protein = catalogue_protein(root, entry)
    half_thickness = protein.get('half_thickness_nm')
    if half_thickness is None:
        return jsonify({'error': f'{protein["name"]} states no membrane annotation, so it has no transmembrane slab '
                                 'to size a belt against'}), 400
    molecule_id = (request.args.get('molecule_id') or '').strip()
    if not molecule_id:
        return jsonify({'error': 'molecule_id is required: the estimate needs the detergent whose head bead it '
                                 'sizes'}), 400
    requested = request.args.get('aggregation_number', '')
    try:
        requested = int(requested)
    except (TypeError, ValueError):
        return jsonify({'error': f'aggregation_number must be a whole number of detergents, not {requested!r}'}), 400
    if requested < 1:
        return jsonify({'error': 'aggregation_number must be at least 1'}), 400

    mappings = saved_mappings(molecule_id)
    if not mappings:
        return jsonify({'error': f'{molecule_id} has no saved CG mapping, so its head bead\u2019s size class -- and '
                                 'with it the area one detergent covers -- cannot be resolved'}), 400
    head_radii, footprints = [], {}
    for name, record in mappings:
        try:
            radii = encapsulation.mapping_head_radii(record)
        except ValueError as error:
            return jsonify({'error': f'the saved mapping {name} names no head bead this can size: {error}'}), 400
        head_radii.extend(radii)
        footprints[name] = max(radii)
    # Only the largest head bead sets the footprint, so two mappings that agree about it can both be used; two that
    # disagree leave the estimate with no single radius, and picking one would hide a real disagreement.
    if len(set(footprints.values())) != 1:
        detail = '; '.join(f'{name} says {radius:.3f} nm' for name, radius in sorted(footprints.items()))
        return jsonify({'error': f'the saved mappings for {molecule_id} disagree about the head bead\u2019s size '
                                 f'class: {detail}'}), 400

    chains = requested_chains(request)
    location = Path(protein['path'])
    structure = location if location.is_absolute() else Path(root) / location
    try:
        atoms = encapsulation.read_structure(structure, chains=chains)
    except (OSError, ValueError) as error:
        return jsonify({'error': f'{protein["name"]} could not be read: {error}'}), 400
    # A chain that is not in the file would size a different object than the one asked for. `chains_available` is the
    # whole file's chain list, so this is answered even when the selection came back empty.
    if chains is not None:
        missing = encapsulation.unknown_chains(atoms['chains_available'], chains)
        if missing:
            available = ', '.join(atoms['chains_available']) or 'none'
            return jsonify({'error': f'{protein["name"]} names no chain(s) {", ".join(missing)}; it names '
                                     f'{available}'}), 400
    try:
        numbers = encapsulation.estimate(atoms['positions_nm'], atoms['radii_nm'],
                                         encapsulation.apolar_mask(atoms['residues']),
                                         centre_nm=SLAB_CENTRE_NM, half_thickness_nm=half_thickness,
                                         head_radii_nm=head_radii, requested=requested,
                                         residues=atoms['residues'])
    except (OSError, ValueError) as error:
        return jsonify({'error': f'{protein["name"]} could not be sized: {error}'}), 400
    return jsonify({'protein': {'name': protein['name'], 'id': protein['id'], 'source': protein.get('source'),
                                'half_thickness_nm': half_thickness},
                    'molecule_id': molecule_id,
                    'mappings': sorted(name for name, _ in mappings),
                    'chains': {'selected': chains or 'all', 'available': atoms['chains_available'],
                               'narrowed': atoms['narrowed']},
                    'slab': {'axis': 'z', 'centre_nm': SLAB_CENTRE_NM, 'half_thickness_nm': half_thickness},
                    'atoms': numbers['atoms'], 'apolar_area_nm2': numbers['apolar_area_nm2'],
                    'head_radius_nm': numbers['head_radius_nm'], 'head_area_nm2': numbers['head_area_nm2'],
                    'requested': numbers['requested'], 'needed': numbers['needed'],
                    'fraction': numbers['fraction'],
                    'method': encapsulation.ESTIMATE_METHOD, 'caveat': encapsulation.ESTIMATE_CAVEAT})


def requested_chains(source):
    """The subunits a caller asked the estimate to size, or `None` for the whole structure.

    `chains` is the panel's name and `protein_chains` the run's, accepted so the estimate and the build are asked the
    same question; the value is comma-separated or repeated. Absent is `None`, and `None` is every chain, which is
    what keeps an existing caller's number unchanged.
    """
    raw = source.args.getlist('chains') or source.args.getlist('protein_chains')
    chains = [part.strip() for value in raw for part in value.split(',') if part.strip()]
    return chains or None


def requested_preparation(source) -> bool:
    """The prepare step's own choice, as a form spells a boolean, or a refusal for a value that is neither.

    Absent is the adapter's own default -- off, because the plan calls the step optional -- so an existing caller
    that has never heard of it asks for exactly what it asked for before. A value that is neither a yes nor a no is a
    malformed request rather than a yes: reading `"maybe"` as one of them is how a control comes to mean the opposite
    of what it says.
    """
    raw = (source.args.get('prepare_protein') or '').strip().lower()
    if raw in ('', 'false', '0', 'no', 'off'):
        return False
    if raw in ('true', '1', 'yes', 'on'):
        return True
    raise ValueError(f'prepare_protein must be true or false, not {raw!r}')


def preview_choices(source):
    """The panel's numbers, in the builder's spelling and by the builder's own rules.

    Everything a preview and a run must agree about: a seed (the placement is deterministic in it, so a run without
    one is not comparable with another), a count, a style, the chains, and whether the prepare step runs. The semantic
    checks are `pdc.validate_payload`'s -- the adapter's own admission, called rather than restated -- and only the
    spelling is translated here. So a preview refuses the same inputs a run refuses, in the same terms.
    """
    from detergent_pdc.execution.adapters import pdc

    def whole(name, default=None):
        raw = (source.args.get(name) or '').strip()
        if not raw:
            if default is None:
                raise ValueError(f'{name} is required: the placement is deterministic in the seed the run will '
                                 f'place with, so a preview without one is not this run')
            return default
        try:
            return int(raw)
        except ValueError:
            raise ValueError(f'{name} must be a whole number, not {raw!r}') from None

    def number(name, default):
        raw = (source.args.get(name) or '').strip()
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError:
            raise ValueError(f'{name} must be a number, not {raw!r}') from None

    supplied = {'seed': whole('pdc_seed'),
                'aggregation_number': whole('aggregation_number', pdc.DEFAULTS['aggregation_number']),
                'placement_mode': (source.args.get('placement_mode') or '').strip()
                                  or pdc.DEFAULTS['placement_mode'],
                'prepare_protein': requested_preparation(source),
                'protein_chains': requested_chains(source)}
    choices = pdc.validate_payload(supplied)
    choices['box_margin_nm'] = number('box_margin_nm', float(pdc.DEFAULTS['box_margin_nm']))
    choices['initial_z_nm'] = number('initial_z_nm', float(pdc.DEFAULTS['initial_z_nm']))
    return choices


def preview_cache_root():
    """Where a preview keeps its coarse-grained protein: the workspace's own scratch area.

    Not a run's directory, and nothing any stage reads: the preview derives its own frame and keeps only the
    coarse-grained protein, so its cache can never be mistaken for a run's input. `Paths` always resolves a workspace
    (the
    configured one, or the repository's own directory), so the missing case is a refusal rather than a fallback to
    somewhere a preview has no business writing.
    """
    from detergent_pdc.execution import pdc_preview

    workspace = paths.current().workspace
    if workspace is None:
        abort(500, 'this workspace has nowhere writable to keep a coarse-grained protein')
    return Path(workspace) / pdc_preview.CACHE_DIRECTORY


@blueprint.get('/api/pdc/preview/protein')
def pdc_preview_protein():
    """The all-atom protein the preview's frame was coarse-grained from, for the card's ribbon.

    The other half of the picture the placement route answers with: `basis['protein_structure']` names a cache entry
    and this URL, and this serves the structure inside it -- the file martinize2 was handed, unchanged, because it is
    already in the frame the beads were written in. The client is told the URL rather than building one, so the two
    halves of the answer cannot spell the same file differently.

    `key` is a cache entry's name and nothing else: `pdc_preview.CACHE_KEY_PATTERN` is hex of the key's own length,
    which is also what keeps a key from naming a path outside the cache root -- there is no separator to escape
    with. Anything that is not one is a **400** (a malformed request, the spelling the routes beside it use), and a
    well-formed key the cache does not hold is a **404** that names it: a preview whose entry was removed is a
    missing file, not a bad question. Nothing here writes, and nothing here is a run's input.
    """
    from detergent_pdc.execution import pdc_preview

    key = (request.args.get('key') or '').strip()
    if not pdc_preview.CACHE_KEY_PATTERN.fullmatch(key):
        return jsonify({'error': f'key must be a preview cache entry name ({pdc_preview.CACHE_KEY_LENGTH} hex '
                                 f'characters), not {key!r}'}), 400
    structure = pdc_preview.protein_structure_path(preview_cache_root() / key)
    if structure is None:
        abort(404, f'the preview cache holds no all-atom protein for {key}: derive the preview again, and the entry '
                   f'it builds will hold the structure its beads came from')
    return Response(structure.read_text(errors='replace'), mimetype='text/plain')


@blueprint.get('/api/pdc/preview/placement')
def pdc_preview_placement():
    """The frame these inputs would build, derived from the build's own placement step and nothing else.

    A GET, because it is a derived read-only answer about the inputs -- the same shape as
    `GET /api/pdc/proteins/<entry>/encapsulation` beside it. The picture is `structures.system_pdb`'s own output: one
    residue per molecule, the mapping's beads, and the model's own bonds as `CONECT` records.

    **A refusal is an answer, not a bad request.** A template the builder's validator refuses, and a placement that
    fails the clearance gate, come back as `200` with `valid: false` and the builder's own sentences -- the panel
    renders them instead of inventing a message, and draws nothing. A *malformed* request (an unknown protein, a chain
    the file does not name, a seed that is not a whole number, a template that is not a file) is a 400 with `{error}`,
    exactly as `pdc_encapsulation` refuses.

    Nothing a run reads is written and no run is created: the only thing this route leaves on disk is a
    coarse-grained protein under the workspace's preview cache (see `execution/pdc_preview.py`), which no stage reads.
    `basis['protein_structure']` names that entry and `pdc_preview_protein` beside it, so the card can draw the
    all-atom structure the beads were coarse-grained from under them -- and it names neither for a build with no
    protein.
    """
    from dashboard.execution import tools
    from detergent_pdc.execution import pdc_preview
    from detergent_pdc.execution.adapters import pdc_preparation

    root = coordinator().ROOT
    try:
        choices = preview_choices(request)
        protein = None
        entry = (request.args.get('protein') or '').strip()
        if entry:
            # The catalogue's own spelling of the entry, so a caller naming it by id, by path or by stem gets the one
            # structure it means -- and an entry the catalogue does not hold is a 404 that says so.
            protein = catalogue_protein(root, entry)['path']
        template = (request.args.get('template') or '').strip()
        if not template:
            raise ValueError('template is required: the preview places the detergent the template names')
        answer = pdc_preview.preview(
            project_root=root, cache_root=preview_cache_root(),
            template=template, protein=protein, chains=choices['protein_chains'],
            mapping=(request.args.get('mapping_candidate') or '').strip() or None,
            molecule_id=(request.args.get('molecule_id') or '').strip() or None,
            aggregation_number=choices['aggregation_number'], placement_mode=choices['placement_mode'],
            seed=choices['seed'], box_margin_nm=choices['box_margin_nm'], initial_z_nm=choices['initial_z_nm'],
            prepare_protein=choices['prepare_protein'],
            # The preparer the optional Prepare step runs, resolved where every other tool is: the route resolves it
            # and the service reports the refusal its absence produces, with the tool named.
            prepare_executable=tools.tool_path(pdc_preparation.TOOL),
            # The tool the build shells out to, resolved where every other tool is: a declaration that cannot be
            # honoured resolves to nothing rather than to a substitute, and the refusal then names what is missing.
            executable=tools.tool_path('martinize2'))
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
    return jsonify(answer)


@blueprint.post('/api/micelle/build')
def micelle_build_api():
    """Thin adapter for the native micelle CLI; reports are ordinary run artifacts."""
    from dashboard.web.routes.runs import view_of

    c = coordinator()
    payload = json_object()
    jid = uuid.uuid4().hex[:12]
    job = {'id': jid, 'label': payload.get('label') or 'Micelle build', 'detergent': payload.get('detergent','DDM'),
           'method': 'micelle', 'status': 'running', 'stage': 'micelle build', 'created': c.now(), 'profile': 'micelle', 'settings': payload}
    with c.JOBS_LOCK:
        c.database().insert(job)
    directory = c.RUNS / jid; directory.mkdir(parents=True, exist_ok=False)
    try:
        result = run_micelle_job(payload, directory)
        c.database().update(jid, status='completed' if result['status']=='completed' else 'failed', stage='complete' if result['status']=='completed' else 'micelle build', ended_at=c.now(), error=result.get('error'), command=' '.join(result['command']))
    except Exception as exc:
        c.database().update(jid, status='failed', stage='micelle build', ended_at=c.now(), error=str(exc))
    return jsonify(view_of(c, c.lookup(jid))), 201
