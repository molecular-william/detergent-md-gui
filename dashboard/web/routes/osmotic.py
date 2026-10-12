"""The osmotic series endpoint: one condition per molality, queued together, refused together.

A series is only comparable if every condition in it was built the same way, so this route does not queue as it goes.
It checks every molality first and creates nothing if any of them is refused -- a half-queued series would be six runs
whose relationship to each other is a guess.
"""
import uuid

from flask import Blueprint, abort, jsonify, request

from ...execution import protocol
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

    # The settings this run type accepts, asked of the run type: the route assembled the same union of two adapter
    # tables the runs route did, which is the answer for a run type only by coincidence.
    adapter = protocol.adapter_for('osmotic')
    base = {key: data.get(key) for key in {**adapter.settings_specs(), **adapter.choice_specs()}
            if data.get(key) not in (None, '')}
    series_id = uuid.uuid4().hex[:12]
    try:
        for molality in molalities:
            adapter.normalize_settings(dict(base, osmotic_molality=molality, series_id=series_id),
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


#: The paper's own measurements for maltose, at 308.15 K, from Ebrahimi & Sadeghi, Fluid Phase Equilibria 417 (2016)
#: 171-180, table 2 -- `(molality, pressure bar, uncertainty bar)`. They are written here rather than read from
#: `resources/validation/carbohydrates/targets-v1.json` because that file is still `metadata_only` for this molecule:
#: it carries the citation and no numbers. That is the honest state, and copying the numbers in beside their citation
#: is more truthful than a reader that silently finds nothing. When the registry gains a measured target the panel
#: should read it from there and this constant should go.
PAPER_MALTOSE = ((0.5, 13.04, 0.04), (1.0, 26.54, 0.08), (1.5, 40.58, 0.12),
                 (2.0, 56.09, 0.16), (2.5, 72.72, 0.20))
PAPER_CITATION = 'Ebrahimi & Sadeghi, Fluid Phase Equilibria 417 (2016) 171-180, doi:10.1016/j.fluid.2016.02.030'


def condition_for(run_dir):
    """One condition as the panel needs it: what was built, what the paper says, and what was measured.

    The measurement is read from the report `osmotic_pressure.publish` wrote beside the run's own outputs. A
    condition with no report is *unmeasured*, which is a different state from measured-and-zero -- and the 0 molal
    control has no report by construction, because there is no solute for a wall to push against.
    """
    import json
    from pathlib import Path

    directory = Path(run_dir) / '01_simulate'
    record_path = directory / 'osmotic_condition.json'
    if not record_path.is_file():
        return None
    record = json.loads(record_path.read_text())
    condition = {'run_id': Path(run_dir).name,
                 'molality_requested': record.get('molality_requested'),
                 'molality_achieved': record.get('molality_achieved'),
                 'solute_molecules': record.get('solute_molecules'),
                 'dividing_area_nm2': record.get('dividing_area_nm2'),
                 'temperature_k': record.get('temperature'),
                 'attempted_at': record_path.stat().st_mtime,
                 'measured': None}
    report_path = directory / 'osmotic-pressure.json'
    if report_path.is_file():
        condition['measured'] = json.loads(report_path.read_text())
    for molality, pressure, uncertainty in PAPER_MALTOSE:
        if condition['molality_requested'] is not None and abs(molality - float(condition['molality_requested'])) < 0.01:
            condition['paper'] = {'pressure_bar': pressure, 'uncertainty_bar': uncertainty}
            condition['ratio'] = (condition['measured']['pressure_bar'] / pressure) if condition['measured'] else None
    return condition


def representative(conditions):
    """One condition per molality: the measured attempt if any, otherwise the most recent one.

    The first version returned every directory that had a condition record, which was 27 rows for six conditions --
    thirteen of them abandoned attempts at 0.5 molal alone, each of them a run that built its box and died. They are
    evidence, and this panel is not their reader: what it shows is the state of the series, so an attempt that was
    superseded by the one which succeeded must not appear beside it. Measured beats recent deliberately -- a
    completed run whose report has been written is the answer for its molality even if a probe was started later --
    and among unmeasured attempts the newest wins, so a running condition shows as *itself*, unmeasured, rather than
    as whichever attempt happened to sort last.
    """
    best = {}
    for condition in conditions:
        key = condition['molality_requested']
        current = best.get(key)
        if current is None:
            best[key] = condition
            continue
        if condition['measured'] and not current['measured']:
            best[key] = condition
        elif bool(condition['measured']) == bool(current['measured']) and \
                condition['attempted_at'] > current['attempted_at']:
            best[key] = condition
    return sorted(best.values(), key=lambda entry: (entry['molality_requested'] is None,
                                                    entry['molality_requested'] or 0.0))


@blueprint.get('/api/osmotic/conditions')
def conditions_api():
    """The series as it stands: one condition per molality, with the paper's own numbers beside them.

    Read from the runs directory rather than from the job store, because what the panel needs is what was *built and
    measured* -- the molality actually achieved and the report -- and both are files. `representative` then collapses
    the abandoned attempts, of which this series has many: thirteen at 0.5 molal and seven at 1.0, from the PLUMED
    work and the thread experiments. Those runs are why the number exists and are readable through their own run
    entries; they are not six extra rows here.

    The directory comes from the coordinator's own `RUNS` -- the path a fixture redirects -- rather than from the
    environment, so a test drives this route against a fixture instead of against whatever the developer's workspace
    happens to hold. That is the rule every other test in this suite follows, and it is the rule this route broke in
    its first draft.
    """
    from .common import coordinator

    runs = coordinator().RUNS
    conditions = [condition for run_dir in sorted(runs.iterdir()) if (condition := condition_for(run_dir))]
    shown = representative(conditions)
    return jsonify({'molecule_id': MOLECULE_FOR_SERIES, 'citation': PAPER_CITATION,
                    'conditions': shown,
                    'measured': sum(1 for entry in shown if entry['measured']),
                    'total': len(shown),
                    'attempts_on_disk': len(conditions)})


#: Which molecule the panel describes. One series exists today; a second molecule's series would make this a
#: parameter rather than a constant, and the condition records already carry enough to group by themselves.
MOLECULE_FOR_SERIES = 'Maltose'
