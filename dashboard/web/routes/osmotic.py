"""The osmotic series endpoint: one condition per molality, queued together, refused together.

A series is only comparable if every condition in it was built the same way, so this route does not queue as it goes.
It checks every molality first and creates nothing if any of them is refused -- a half-queued series would be six runs
whose relationship to each other is a guess.
"""
import uuid

from flask import Blueprint, abort, jsonify, request

from ...execution.adapters import osmotic
from ...execution.coordination import admission
from ...models.molecules import aa as aa_molecules
from .common import coordinator, json_object

blueprint = Blueprint('osmotic', __name__)

#: The molalities Ebrahimi & Sadeghi measured, which is what a series exists to compare against. A caller may name
#: others; the default is the paper's own set so the common case needs no argument.
PAPER_MOLALITIES = (0.0, 0.5, 1.0, 1.5, 2.0, 2.5)


def _requested_molalities(data):
    requested = data.get('molalities')
    if requested in (None, ''):
        return list(PAPER_MOLALITIES)
    values = requested if isinstance(requested, (list, tuple)) else str(requested).replace(',', ' ').split()
    try:
        return [float(value) for value in values]
    except (TypeError, ValueError):
        abort(400, 'Molalities must be numbers')


@blueprint.post('/api/osmotic/series')
def series_api():
    """Queue one job per molality, all sharing a series id, and return what was created.

    Nothing is created until everything has been checked: the molecule, the solvent files, the run type and every
    molality. The alternative -- creating what it can and reporting the rest -- leaves a series whose conditions do
    not correspond to each other.
    """
    c = coordinator()
    data = json_object() or request.form

    molecule_id = str(data.get('molecule_id') or '').strip()
    if not molecule_id:
        abort(400, 'molecule_id is required: a series belongs to one solute')
    try:
        aa_molecules.validate_id(molecule_id)
    except ValueError as exc:
        abort(400, str(exc))

    solute_root = str(data.get('solute_root') or '').strip()
    if not solute_root:
        abort(400, 'solute_root is required: the directory holding ' + ', '.join(osmotic.SOLUTE_FILES))

    try:
        admission.validate_run_type(dict(data, run_type='osmotic'))
    except ValueError as exc:
        abort(400, str(exc))

    molalities = _requested_molalities(data)
    if not molalities:
        abort(400, 'A series needs at least one molality')

    base = {key: data.get(key) for key in set(osmotic.SETTING_SPECS) | set(osmotic.CHOICE_SPECS)
            if data.get(key) not in (None, '')}
    series_id = uuid.uuid4().hex[:12]
    try:
        for molality in molalities:
            osmotic.normalize_settings(dict(base, osmotic_molality=molality, series_id=series_id),
                                       data.get('profile', 'standard'))
    except ValueError as exc:
        abort(400, str(exc))

    mapping_candidate = data.get('mapping_candidate')
    reference_run_id = data.get('reference_run_id') or None
    profile = data.get('profile', 'standard')
    # The method is how the CG topology was fitted, not which workflow this is -- `pdc` posts `method: 'bartender'`
    # with `run_type: 'pdc'`. Fast_Forward is the method this repository's CG path fits with, so it is the default
    # here; a caller whose reference was fitted some other way names it.
    method = str(data.get('method') or 'fast_forward')
    created = []
    for molality in molalities:
        job = c.create_job(molecule_id, method, f'{molecule_id} osmotic {molality:g} molal',
                           profile=profile,
                           settings=dict(base, osmotic_molality=molality, series_id=series_id),
                           reference_run_id=reference_run_id, mapping_candidate=mapping_candidate,
                           molecule_id=molecule_id, run_type='osmotic')
        created.append({'id': job['id'], 'molality': molality, 'label': job.get('label', '')})

    return jsonify({'series_id': series_id, 'molecule_id': molecule_id, 'solute_root': solute_root,
                    'molalities': molalities, 'count': len(created), 'jobs': created}), 201
