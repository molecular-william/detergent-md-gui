"""The osmotic series endpoint: one condition per molality, queued together, refused together.

A series is only comparable if every condition in it was built the same way, so this route does not queue as it goes.
It checks every molality first and creates nothing if any of them is refused -- a half-queued series would be six runs
whose relationship to each other is a guess.
"""
import json
import uuid
from pathlib import Path

from flask import Blueprint, abort, jsonify, request

from ...execution import protocol
from ...execution.adapters import osmotic, osmotic_box, osmotic_mdp
from ...execution.coordination import admission
from ...models import mappings
from ...models.mappings import context as mapping_context
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


# --- the set-up door: GET /api/osmotic/catalogue ---------------------------------------------------------------
#
# The panel renders this answer; it recomputes none of it. Three things decide whether a carbohydrate can be
# run, and every one of them is a fact about the tree rather than a guess made in JavaScript: the molecule has a
# folder under `molecules/`, so its beads can be mapped at all; a saved CG mapping exists for it, so
# `osmotic.solute_bead_radii` has radii and `prepare` can size the box; and its solute files are present, so
# `prepare` can copy the molecule, its topology and the water tile. What is missing is named.

#: The carbohydrate vocabulary. `resources/validation/carbohydrates/targets-v1.json` is this repository's own
#: list of the sugars it carries a citation for, so the panel's selector is that list -- including a name with no
#: folder, because a list that silently omits one leaves the reader unable to tell a missing mapping from a typo.
CARBOHYDRATE_REGISTRY = Path('resources/validation/carbohydrates/targets-v1.json')

#: Where a molecule's solute files sit: under the selected workspace, beside `runs/`. Resolved here and never
#: typed into a field -- a free-text filesystem path in a browser form is the wrong control for it.
SOLUTE_DIRECTORY = 'osmotic'

#: The mapping facts that are standing decisions rather than measurements, so the panel can say them where the
#: blocker is shown. `AGENTS.md`: the recogniser maps one hexopyranose ring and preserves the rest of the graph
#: as a draft, so a generated Sucrose mapping is a diagnostic input, not an official Martini parameter set.
PROVISIONAL_MAPPINGS = {
    'Sucrose': 'the mapping is provisional: the recogniser maps one hexopyranose ring and preserves the rest as '
               'a draft (AGENTS.md), so a generated Sucrose mapping is a diagnostic input, not an official '
               'Martini parameter set',
}

#: The key the failure choice travels under, and the house ceiling on a condition's retries -- `attempts_max = 3`
#: in `pdc.DEFAULTS`, and the loop bound `pdc_extension.py` uses. The panel shows the number; it is not a control.
FAILURE_KEY = 'series_on_failure'
ATTEMPTS_MAX_DEFAULT = 3

#: What can act on a *stop*. The batch route creates every condition up front and refuses before creating
#: anything, so once the series exists a failed condition does not cancel its siblings -- the stop half is the
#: coordinator's `stop_series`, which ends the conditions that have not run when one ends failed. It is probed on
#: the object that would have to act rather than declared as a flag, so the panel offers the choice enabled
#: exactly when something can honour it, and disabled *with its reason* when nothing can.
SERIES_STOP_METHOD = 'stop_series'


def _carbohydrate_names(root):
    """Every carbohydrate the repository names, in the registry's own order."""
    path = Path(root) / CARBOHYDRATE_REGISTRY
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    names = []
    for dataset in payload.get('datasets') or []:
        molecule_id = dataset.get('molecule_id')
        if molecule_id and molecule_id not in names:
            names.append(molecule_id)
    return names


def _molecule_folders(root):
    """The molecule directories the repository carries, which is where a mapping context can be built from."""
    directory = Path(root) / 'molecules'
    if not directory.is_dir() or directory.is_symlink():
        return []
    return [entry.name for entry in sorted(directory.iterdir()) if entry.is_dir() and not entry.is_symlink()]


def _saved_mappings(root, molecule_id):
    """A molecule's saved CG mapping candidates, or an empty list when there is no context to scope them by."""
    try:
        context = mapping_context.build_context(Path(root) / 'molecules', molecule_id)
    except (OSError, ValueError):
        return []
    return [{'file': item['file'], 'name': item.get('name') or item['file']}
            for item in mappings.list_candidates(context=context) if not item.get('error')]


def solute_root_for(coordinator_object, molecule_id):
    """The directory `prepare` copies a molecule's files out of, resolved for the selected workspace."""
    return Path(coordinator_object.RUNS).parent / SOLUTE_DIRECTORY / str(molecule_id).lower()


def _sugar_record(coordinator_object, molecule_id, folder_exists):
    """One carbohydrate as the panel needs it: what is there, what is missing, and whether a run can be built."""
    root = coordinator_object.ROOT
    blockers = []
    saved = _saved_mappings(root, molecule_id) if folder_exists else []
    if not folder_exists:
        blockers.append(f'No saved CG mapping: {molecule_id} has no folder under molecules/, so it has no '
                        'mapping candidate and its beads have no radii to size the box from')
    elif not saved:
        blockers.append(f'No saved CG mapping: {molecule_id} has no mapping candidate in the mapping store, so '
                        'its beads have no radii to size the box from')

    solute_root = solute_root_for(coordinator_object, molecule_id)
    missing = [name for name in osmotic.SOLUTE_FILES if not (solute_root / name).is_file()]
    present = [name for name in osmotic.SOLUTE_FILES if name not in missing]
    if missing:
        blockers.append(f'Solute files not prepared: {solute_root} is missing ' + ', '.join(missing))

    provisional = PROVISIONAL_MAPPINGS.get(molecule_id)
    if provisional and saved:
        blockers.append(provisional[0].upper() + provisional[1:])

    # The state is decided here, not in the browser: whether a box can be sized at all (no mapping -> refused),
    # or whether the mapping is there and a file is not (blocked), or neither (ready).
    state = 'ready' if (folder_exists and saved and not missing) else ('refused' if not saved else 'blocked')
    return {'molecule_id': molecule_id, 'label': molecule_id, 'molecule_folder': bool(folder_exists),
            'mappings': saved,
            'solute_root': str(solute_root),
            'solute_files': list(osmotic.SOLUTE_FILES),
            'solute_files_present': len(present), 'solute_files_missing': missing,
            'ready': state == 'ready', 'state': state,
            'blockers': blockers,
            'provisional': bool(provisional)}


def _adapter_defaults(adapter):
    """A run type's own defaults, in whichever shape it publishes them."""
    try:
        published = adapter.stage_defaults('standard')
    except TypeError:
        published = adapter.stage_defaults()
    published = published or {}
    if isinstance(published.get('values'), dict):
        return dict(published['values'])
    return dict(published)


def failure_policy(adapter, coordinator_object):
    """Which of the two choices after a condition fails can actually act, and the reason when one cannot.

    Both halves of the stop option are checked rather than declared: the run type has to carry the key, so the
    choice survives the queue route's settings filter, and the coordinator has to have the method that ends the
    remaining conditions. Until they do, the honest answer for that choice is its reason -- so a panel can offer
    it disabled with the reason on it instead of offering something that silently does nothing.
    """
    vocabulary = set(adapter.settings_specs()) | set(adapter.choice_specs())
    advertised = FAILURE_KEY in vocabulary
    can_stop = callable(getattr(coordinator_object, SERIES_STOP_METHOD, None))
    reasons = []
    if not advertised:
        reasons.append(f'the run type does not carry a {FAILURE_KEY} setting yet')
    if not can_stop:
        reasons.append('the coordinator cannot end a series\' remaining conditions when one ends failed '
                       '(`stop_series`), so the batch route leaves a failed condition\'s siblings to run')
    stop_reason = None if advertised and can_stop else (
        'Not available yet: ' + ' and '.join(reasons) + '. Until then a series is queued as one batch and a '
        'failed condition\'s siblings carry on.')
    return {'key': FAILURE_KEY, 'default': 'carry_on', 'advertised': advertised,
            'attempts_max': int(_adapter_defaults(adapter).get('osmotic_attempts_max', ATTEMPTS_MAX_DEFAULT)),
            'options': [
                {'value': 'carry_on', 'available': True, 'reason': None,
                 'label': 'Carry on — the remaining conditions run; a gap is reported'},
                {'value': 'stop', 'available': bool(advertised and can_stop), 'reason': stop_reason,
                 'label': 'Stop the series on the first failed condition — queues one condition at a time'},
            ]}


def static_setup():
    """The physical setup the pipeline reads, each value from the module that decides it, so nothing is restated."""
    return {'box_nm': list(osmotic_box.BOX_NM),
            'box_volume_nm3': osmotic_box.box_volume_nm3(),
            'dividing_area_nm2': osmotic_box.dividing_area_nm2(),
            'confinement_nm': osmotic_box.CONFINEMENT_NM,
            'confinement_kj_mol_nm2': osmotic_box.CONFINEMENT_KJ_MOL_NM2,
            'molality_range': list(osmotic_box.MOLALITY_RANGE),
            # PLUMED writes the wall as V = KAPPA*(x-AT)^2, so the constant it is given is half the paper's.
            'kappa': osmotic_mdp.DEFAULT_CONFINEMENT_KJ_MOL_NM2 / 2,
            'restraint_kj_mol_nm2': osmotic.REFERENCE_RESTRAINT,
            'salt': False,
            'seed': 20261006,
            'mdrun_ntomp': osmotic.DEFAULTS['mdrun_ntomp'],
            'mdrun_ranks': osmotic.DEFAULTS['mdrun_ranks'],
            'temperature_source': 'the experimental dataset\'s own temperature; 308.15 K for maltose'}


@blueprint.get('/api/osmotic/catalogue')
def catalogue_api():
    """The sugars this repository can build a series for, and what each one is missing.

    The list is the registry's own carbohydrate names, ordered so the ones the repository carries a folder for
    come first -- which is the order that puts what can be built above what cannot. Nothing about readiness is
    decided in the browser: a name with no folder, no mapping or no solute file is returned with its blocker, so
    the panel can refuse with the reason rather than omitting the molecule.
    """
    c = coordinator()
    adapter = protocol.adapter_for('osmotic')
    folders = _molecule_folders(c.ROOT)
    names = _carbohydrate_names(c.ROOT)
    known = set(names)
    # The folder order first -- `molecules/` is alphabetical, which puts what can be built above what cannot --
    # then the names the registry carries without a folder.
    ordered = [name for name in folders if name in known] + [name for name in names if name not in set(folders)]
    defaults = _adapter_defaults(adapter)
    return jsonify({
        'sugars': [_sugar_record(c, name, name in folders) for name in ordered],
        'solute_files': list(osmotic.SOLUTE_FILES),
        'molality_range': list(osmotic_box.MOLALITY_RANGE),
        'ns_per_day': 2400.0,
        'failure_policy': failure_policy(adapter, c),
        'defaults': {'duration_ns': int(float(defaults.get('osmotic_production_ps',
                                                          osmotic_mdp.DEFAULT_PRODUCTION_PS)) / 1000),
                     'production_ps': float(defaults.get('osmotic_production_ps',
                                                        osmotic_mdp.DEFAULT_PRODUCTION_PS)),
                     'equilibration_ps': float(defaults.get('osmotic_equilibration_ps',
                                                            osmotic_mdp.DEFAULT_EQUILIBRATION_PS)),
                     'output_interval_ps': float(defaults.get('osmotic_output_interval_ps',
                                                              osmotic_mdp.DEFAULT_OUTPUT_INTERVAL_PS)),
                     'temperature_k': float(defaults.get('temperature_k', osmotic.DEFAULTS['temperature_k']))},
        'setup': static_setup(),
        # The route's own answer, repeated where the panel can show it: a completed series is execution and
        # measurement, and agreement with the paper's points is evidence about the model and the mapping at once.
        'scientifically_validated': False,
    })
