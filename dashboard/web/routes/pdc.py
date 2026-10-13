"""Protein-detergent complex endpoints: the catalogue the panel builds its setup from, and the system it built."""
import json
from pathlib import Path
from urllib.parse import unquote

from flask import Blueprint, Response, abort, current_app, jsonify, request

from ... import paths
from ...execution import workflow
from ...execution.adapters import pdc, pdc_import, pdc_view
from .common import coordinator

blueprint = Blueprint('pdc', __name__)

SETUP_STAGE = '1_system'
SYSTEM_STRUCTURE = 'system.gro'
SNAPSHOT_INDEX = 'snapshots.json'
# The centre of the transmembrane slab along z. An OPM structure arrives already oriented, with the bilayer the
# xy-plane through the origin, so the centre is a property of the coordinate frame rather than a number to measure.
SLAB_CENTRE_NM = 0.0


def setup_root(job_id) -> Path:
    """The execution root of a run, or a 404 that says which run was unknown."""
    c = coordinator()
    try:
        return workflow.execution_root(c.run_path(c.lookup(job_id)))
    except (KeyError, OSError):
        abort(404, 'unknown run')


def snapshot_entries(root: Path) -> list[dict]:
    """Every stage's snapshot index, merged into one series, earliest first.

    The snapshots live in the stage that took them, because that is the stage that can re-derive them; a series is
    what a reader wants, so the merge happens here rather than in each stage's record. The placement has no time and
    sorts first, which is the order the moments happened in.
    """
    entries = []
    for index_path in sorted(Path(root).glob(f'*/{SNAPSHOT_INDEX}')):
        try:
            document = json.loads(index_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for entry in document.get('snapshots') or []:
            if isinstance(entry, dict) and entry.get('pdb'):
                entries.append({**entry, 'stage': index_path.parent.name})
    # `is not None` rather than `is None`: a moment without a time (the placement) is the first moment, and sorting
    # on the truth of "has a time" would put it last.
    return sorted(entries, key=lambda entry: (entry.get('time_ps') is not None,
                                              float(entry.get('time_ps') or 0.0), str(entry.get('name'))))


def snapshot_file(root: Path, relative: str) -> Path:
    """A snapshot inside a run, or a 404: a path that leaves the run is not a snapshot."""
    root = Path(root).resolve()
    target = (root / relative).resolve()
    if root not in target.parents or target.suffix != '.pdb' or not target.is_file():
        abort(404, 'no such snapshot')
    return target


@blueprint.get('/api/pdc/catalog')
def pdc_catalog():
    return jsonify(pdc.catalog(coordinator().ROOT))


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


@blueprint.get('/api/pdc/<job_id>/snapshots')
def pdc_snapshots(job_id):
    """The run's snapshot series: the placement, each phase's end state, and the frames between them.

    Each entry carries the criterion numbers of the moment it was taken at, so a reader compares a picture with the
    verdict it belongs to rather than with their impression of it.
    """
    entries = snapshot_entries(setup_root(job_id))
    return jsonify({'job_id': job_id, 'snapshots': entries,
                    'note': 'derived: each snapshot carries the criterion numbers of its own moment'})


@blueprint.get('/api/pdc/<job_id>/snapshots/<path:relative>')
def pdc_snapshot(job_id, relative):
    return Response(snapshot_file(setup_root(job_id), relative).read_text(), mimetype='text/plain')


def detergent_topology(root: Path):
    """The run's detergent moleculetype, read from the stage that holds the system or from the one that wrote it.

    The location is the snapshot writer's own rule (`pdc_snapshot.topology_path`), so the built-system view and a
    snapshot of the same run draw the same bonds rather than two readings of where a run keeps its topology. A
    moleculetype that cannot be read is reported as none -- a view with coordinates still has something to show, and
    the writer then says the file records no bonds instead of leaving NGL to guess them.
    """
    from ...execution.scripts import pdc_snapshot

    path = pdc_snapshot.topology_path(Path(root) / SETUP_STAGE)
    if path is None:
        return None
    try:
        return pdc_view.read_moleculetype(path)
    except (OSError, ValueError):
        return None


@blueprint.get('/api/pdc/<job_id>/system.pdb')
def pdc_system_pdb(job_id):
    """The built system as a viewer file. 404 with a reason until a build has produced one.

    The panel shows the system as set up rather than as imagined, so this serves the coordinates a stage wrote,
    through the same writer the snapshots use: one residue per molecule, and the run's own moleculetype's bonds as
    CONECT records. Without them the panel falls back to NGL's distance-based guess -- measured at 90 bonds on a
    frame the model bonds 60 ways. Before that stage has run there is no picture to show, and saying so is better
    than an empty box.
    """
    root = setup_root(job_id)
    structure = root / SETUP_STAGE / SYSTEM_STRUCTURE
    try:
        atoms = pdc_view.read_gro(structure)
    except (OSError, ValueError) as error:
        abort(404, f'no built system to show yet: {error}')
    return Response(pdc_view.system_pdb(atoms, topology=detergent_topology(root)), mimetype='text/plain')


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
    from ...models.mappings import store

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
    from ...analysis.runs import encapsulation

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
