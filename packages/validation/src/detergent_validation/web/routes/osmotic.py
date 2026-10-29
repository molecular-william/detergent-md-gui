"""The osmotic series endpoint: one run that owns every concentration, refused before anything is created.

**The series is the run type.** A series used to be N `osmotic` jobs queued together sharing a `series_id`, which
`max_concurrent_runs: 1` turns into a one-condition series: `create_job` refuses the second with `CapacityFull`,
and nothing starts a job that is merely `queued`. So the route queues *one* job whose settings carry the
concentrations, and the run type builds and runs them one at a time.

A series is only comparable if every condition in it was built the same way, so this route still checks
everything first and creates nothing if anything is refused -- a half-queued series would be conditions whose
relationship to each other is a guess.
"""
import json
import uuid
from pathlib import Path

from dashboard.analysis.runs import layout
from dashboard.execution import protocol
from dashboard.execution.coordination import admission
from dashboard.models import mappings
from dashboard.models.mappings import context as mapping_context
from dashboard.models.molecules import aa as aa_molecules
from dashboard.web.routes.common import coordinator, json_object
from detergent_validation.execution.adapters import osmotic, osmotic_box, osmotic_mdp
from flask import Blueprint, abort, jsonify, request

blueprint = Blueprint('osmotic', __name__)

#: The molalities Ebrahimi & Sadeghi measured -- documentation, and **not a default any more**. The panel's own note
#: in the template names this set as the source of its six rows, and the panel always sends its own five (it skips
#: the 0.0 control, which is the same for every sugar); nothing fills it in behind a caller's back. See
#: `_requested_molalities` for why the default had to go.
PAPER_MOLALITIES = (0.0, 0.5, 1.0, 1.5, 2.0, 2.5)


def _requested_molalities(data):
    """The concentrations the caller named, or a 400 that names the shape this run type accepts.

    **No default, and that is the point.** `PAPER_MOLALITIES` used to be filled in here, which made a payload that
    named none and a payload that asked for those six indistinguishable -- and left behind a series whose
    concentrations nobody had named. A payload with no `molalities` is the shape the hand-queued one-condition runs
    had, so it is refused with the run type's own reason rather than defaulted.
    """
    requested = data.get(osmotic.SERIES_KEY)
    if requested in (None, '', []):
        abort(400, osmotic.series_shape_reason())
    values = requested if isinstance(requested, (list, tuple)) else str(requested).replace(',', ' ').split()
    try:
        return [float(value) for value in values]
    except (TypeError, ValueError):
        abort(400, 'Molalities must be numbers')


@blueprint.post('/api/osmotic/series')
def series_api():
    """Queue the series: one run, N concentrations, one directory each.

    Nothing is created until everything has been checked: the molecule is a sugar, the solvent files are there, the
    run type accepts the payload and every molality can be placed. The alternative -- creating what it can and
    reporting the rest -- leaves a series whose conditions do not correspond to each other.
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

    # The sugar gate at the door. `osmic.refuse_non_sugar` is the run type's own rule -- the carbohydrate registry
    # or the recogniser on the molecule's own structure -- and it is enforced here so the reason is a 400 the
    # caller reads rather than a failure inside a stage. The same function is the adapter's `readiness` blocker
    # and its `prepare` refusal, so a payload that reaches the coordinator without this route is refused too.
    refused = osmotic.refuse_non_sugar(molecule_id, molecule_root=c.ROOT / 'molecules', root=c.ROOT)
    if refused:
        abort(400, refused)

    solute_root = str(data.get('solute_root') or '').strip()
    if not solute_root:
        abort(400, 'solute_root is required: the directory holding ' + ', '.join(osmotic.SOLUTE_FILES))

    try:
        admission.validate_run_type(dict(data, run_type='osmotic'))
    except ValueError as exc:
        abort(400, str(exc))

    molalities = _requested_molalities(data)
    if not molalities:
        abort(400, osmotic.series_shape_reason())

    # The settings this run type accepts, asked of the run type: the route assembled the same union of two adapter
    # tables the runs route did, which is the answer for a run type only by coincidence.
    adapter = protocol.adapter_for('osmotic')
    base = {key: data.get(key) for key in {**adapter.settings_specs(), **adapter.choice_specs()}
            if data.get(key) not in (None, '')}
    series_id = uuid.uuid4().hex[:12]
    # The concentrations travel as the run's own list, and the whole setting set is checked once -- by the run type
    # that will read it -- before a job exists. `normalize_settings` is also where a value outside the box's range
    # is refused with the bound named, which is the refusal the panel shows at the row.
    settings = dict(base, **{osmotic.SERIES_KEY: molalities, 'series_id': series_id})
    try:
        adapter.normalize_settings(settings, data.get('profile', 'standard'))
    except ValueError as exc:
        abort(400, str(exc))

    mapping_candidate = data.get('mapping_candidate')
    reference_run_id = data.get('reference_run_id') or None
    profile = data.get('profile', 'standard')
    # The method is how the CG topology was fitted, not which workflow this is -- `pdc` posts `method: 'bartender'`
    # with `run_type: 'pdc'`. Fast_Forward is the method this repository's CG path fits with, so it is the default
    # here; a caller whose reference was fitted some other way names it.
    method = str(data.get('method') or 'fast_forward')
    label = f'{molecule_id} osmotic series · {len(molalities)} condition' + ('' if len(molalities) == 1 else 's')
    job = c.create_job(molecule_id, method, label, profile=profile, settings=settings,
                       reference_run_id=reference_run_id, mapping_candidate=mapping_candidate,
                       molecule_id=molecule_id, run_type='osmotic')

    return jsonify({'series_id': series_id, 'run_id': job['id'], 'label': job.get('label', ''),
                    'molecule_id': molecule_id, 'solute_root': solute_root,
                    'molalities': molalities, 'count': len(molalities)}), 201


#: The paper's own measurements for maltose, at 308.15 K, from Ebrahimi & Sadeghi, Fluid Phase Equilibria 417 (2016)
#: 171-180, table 2 -- `(molality, pressure bar, uncertainty bar)`. They are written here rather than read from
#: `resources/validation/carbohydrates/targets-v1.json` because that file is still `metadata_only` for this molecule:
#: it carries the citation and no numbers. That is the honest state, and copying the numbers in beside their citation
#: is more truthful than a reader that silently finds nothing. When the registry gains a measured target the panel
#: should read it from there and this constant should go.
PAPER_MALTOSE = ((0.5, 13.04, 0.04), (1.0, 26.54, 0.08), (1.5, 40.58, 0.12),
                 (2.0, 56.09, 0.16), (2.5, 72.72, 0.20))
PAPER_CITATION = 'Ebrahimi & Sadeghi, Fluid Phase Equilibria 417 (2016) 171-180, doi:10.1016/j.fluid.2016.02.030'


def condition_for(directory, run_id=None):
    """One condition as the panel needs it: what was built, what the paper says, and what was measured.

    The measurement is read from the report `osmotic_pressure.publish` wrote beside the condition's own outputs. A
    condition with no report is *unmeasured*, which is a different state from measured-and-zero -- and the 0 molal
    control has no report by construction, because there is no solute for a wall to push against. `state` is the
    condition's own terminal record (`condition.json`), which is how a condition that *failed* is shown as failed
    rather than as one nobody has got to yet.
    """
    directory = Path(directory)
    record_path = directory / 'osmotic_condition.json'
    if not record_path.is_file():
        return None
    record = json.loads(record_path.read_text())
    condition = {'run_id': run_id or directory.parent.parent.name,
                 'condition': directory.name,
                 'molality_requested': record.get('molality_requested'),
                 'molality_achieved': record.get('molality_achieved'),
                 'solute_molecules': record.get('solute_molecules'),
                 'dividing_area_nm2': record.get('dividing_area_nm2'),
                 'temperature_k': record.get('temperature'),
                 'attempted_at': record_path.stat().st_mtime,
                 'state': None, 'measured': None}
    outcome_path = directory / 'condition.json'
    if outcome_path.is_file():
        try:
            condition['state'] = json.loads(outcome_path.read_text()).get('status')
        except (OSError, ValueError):
            condition['state'] = None
    report_path = directory / 'osmotic-pressure.json'
    if report_path.is_file():
        condition['measured'] = json.loads(report_path.read_text())
    for molality, pressure, uncertainty in PAPER_MALTOSE:
        if condition['molality_requested'] is not None and abs(molality - float(condition['molality_requested'])) < 0.01:
            condition['paper'] = {'pressure_bar': pressure, 'uncertainty_bar': uncertainty}
            condition['ratio'] = (condition['measured']['pressure_bar'] / pressure) if condition['measured'] else None
    return condition


def conditions_for(run_dir):
    """Every condition a run directory holds, in whichever of the two layouts it was built in.

    **Both are real and both are read.** The series layout this run type owns now is one run with one directory per
    concentration under `stages/01_simulate/conditions/`; the layout every run made before it has is a run whose
    `01_simulate/` *is* its one condition, at the run root. The completed six-condition series on this workspace's
    disk is the second, and a reader that stopped reading it would drop the record this panel exists to show.
    """
    run_dir = Path(run_dir)
    # `stages/` when the run has it, the run root for a legacy run -- the same answer every analysis reader uses.
    stage = layout.stage_root(run_dir) / '01_simulate'
    conditions = []
    series = stage / osmotic.CONDITIONS_DIRECTORY
    if series.is_dir():
        conditions = [condition for directory in sorted(series.iterdir()) if directory.is_dir()
                      and (condition := condition_for(directory, run_dir.name))]
    if conditions:
        return conditions
    condition = condition_for(stage, run_dir.name)
    return [condition] if condition else []


def representative(conditions):
    """One condition per molality: the measured attempt if any, otherwise the most recent one.

    The first version returned every directory that had a condition record, which was 27 rows for six conditions --
    thirteen of them abandoned attempts at 0.5 molal alone, each of them a run that built its box and died. They are
    evidence, and this panel is not their reader: what it shows is the state of the series, so an attempt that was
    superseded by the one which succeeded must not appear beside it. Measured beats recent deliberately -- a
    completed run whose report has been written is the answer for its molality even if a probe was started later --
    and among unmeasured attempts the newest wins, so a running condition shows as *itself*, unmeasured, rather than
    as whichever attempt happened to sort last.

    A series' own conditions and a hand-queued single condition for the same molality are the same row here, which
    is the point: the panel shows one row per concentration, however many attempts produced it.
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
    from dashboard.web.routes.common import coordinator

    runs = coordinator().RUNS
    conditions = [condition for run_dir in sorted(runs.iterdir()) for condition in conditions_for(run_dir)]
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

#: The carbohydrate vocabulary now lives in the run type itself (`osmic.carbohydrate_names`), because it is the
#: gate that decides whether a molecule may be a series' solute as well as the list the panel offers. This route
#: renders the answer; it does not own the list, so there is no second copy to disagree with the gate.
CARBOHYDRATE_REGISTRY = osmotic.CARBOHYDRATE_REGISTRY

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

#: The half that acts on the failure choice, named so the catalogue can say where it lives: the run type's own
#: driver script. `prepare` writes the run's ceiling and policy into the run beside it, and the driver reads them.
SERIES_DRIVER = 'osmotic_simulation.sh'


def _carbohydrate_names(root):
    """Every carbohydrate the repository names, in the registry's own order, from the run type that gates on it."""
    return osmotic.carbohydrate_names(root)


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


def failure_policy(adapter):
    """Which of the two choices after a condition fails can act, and the reason when one cannot.

    **Both act, and the acting half is the run type's own driver.** `series_on_failure` is carried in the run's
    settings, and `osmic_simulation.sh` reads it from the manifest `prepare` writes beside the conditions: one
    driver loop that either enters the next condition after a failure (the default, recording the gap) or ends the
    series at it. Nothing outside the run has to exist for that to be true, so the question left for this answer to
    check is the one the queue routes ask -- is the key in the run type's vocabulary, or would it be dropped before
    the job was built?

    That is why there is no longer a probe of `Coordinator.stop_series` here. `stop_series` still ends a series
    *made of sibling runs* -- the shape a batch created by hand, and the only shape it can act on -- and the series
    this route queues is one run, whose policy is its driver's.
    """
    vocabulary = set(adapter.settings_specs()) | set(adapter.choice_specs())
    advertised = FAILURE_KEY in vocabulary
    reason = None if advertised else (
        f'Not available: the run type does not carry a {FAILURE_KEY} setting, so the choice would be dropped '
        'before the job was built and nothing would act on it.')
    return {'key': FAILURE_KEY, 'default': 'carry_on', 'advertised': advertised,
            'driver': SERIES_DRIVER,
            'attempts_max': int(_adapter_defaults(adapter).get('osmotic_attempts_max', ATTEMPTS_MAX_DEFAULT)),
            'options': [
                {'value': 'carry_on', 'available': advertised, 'reason': reason,
                 'label': 'Carry on — the remaining conditions run; a gap is reported'},
                {'value': 'stop', 'available': advertised, 'reason': reason,
                 'label': 'Stop the series on the first failed condition — the conditions after it are not run'},
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
            'mdrun_gpu': osmotic.DEFAULTS['mdrun_gpu'],
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
        'failure_policy': failure_policy(adapter),
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
