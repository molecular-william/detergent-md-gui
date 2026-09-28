"""Protein-detergent complex endpoints: the catalogue the panel builds its setup from, and the system it built."""
from flask import Blueprint, Response, abort, jsonify

from ...execution import workflow
from ...execution.adapters import pdc, pdc_view
from .common import coordinator

blueprint = Blueprint('pdc', __name__)

SETUP_STAGE = '1_system'
SYSTEM_STRUCTURE = 'system.gro'


@blueprint.get('/api/pdc/catalog')
def pdc_catalog():
    return jsonify(pdc.catalog(coordinator().ROOT))


@blueprint.get('/api/pdc/<job_id>/system.pdb')
def pdc_system_pdb(job_id):
    """The built system as a viewer file. 404 with a reason until a build has produced one.

    The panel shows the system as set up rather than as imagined, so this serves the coordinates a stage wrote and
    nothing else. Before that stage has run there is no picture to show, and saying so is better than an empty box.
    """
    c = coordinator()
    try:
        run_dir = c.run_path(c.lookup(job_id))
    except (KeyError, OSError):
        abort(404, 'unknown run')
    structure = workflow.execution_root(run_dir) / SETUP_STAGE / SYSTEM_STRUCTURE
    try:
        atoms = pdc_view.read_gro(structure)
    except (OSError, ValueError) as error:
        abort(404, f'no built system to show yet: {error}')
    return Response(pdc_view.system_pdb(atoms), mimetype='text/plain')
