"""Protein-detergent complex endpoints: the catalogue the panel builds its setup from, and the system it built."""
import json
from pathlib import Path

from flask import Blueprint, Response, abort, jsonify

from ...execution import workflow
from ...execution.adapters import pdc, pdc_view
from .common import coordinator

blueprint = Blueprint('pdc', __name__)

SETUP_STAGE = '1_system'
SYSTEM_STRUCTURE = 'system.gro'
SNAPSHOT_INDEX = 'snapshots.json'


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


@blueprint.get('/api/pdc/<job_id>/system.pdb')
def pdc_system_pdb(job_id):
    """The built system as a viewer file. 404 with a reason until a build has produced one.

    The panel shows the system as set up rather than as imagined, so this serves the coordinates a stage wrote and
    nothing else. Before that stage has run there is no picture to show, and saying so is better than an empty box.
    """
    structure = setup_root(job_id) / SETUP_STAGE / SYSTEM_STRUCTURE
    try:
        atoms = pdc_view.read_gro(structure)
    except (OSError, ValueError) as error:
        abort(404, f'no built system to show yet: {error}')
    return Response(pdc_view.system_pdb(atoms), mimetype='text/plain')
