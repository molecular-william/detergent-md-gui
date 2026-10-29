"""The build for one osmotic-pressure condition: the mdps, the groups, the reference bead, and the numbers.

The runner (a stage script, like every other CG stage here) does the GROMACS work. This module decides *what* it works
on, and writes the three things the paper's method needs that no other stage here has:
1. **The mdps** from `osmotic_mdp`, which carry the z-only coupling, the flat-bottomed restraint and the durations.
2. **An index file** naming the two pull groups. `grompp` refuses a `direction` geometry with one group, and the
   groups must be named rather than inferred, so the builder owns the file it will be read from.
3. **The reference bead.** The pull's second group must have its centre of mass *at the box centre*, so it is a single
   bead placed there, frozen, with a **zero-size, zero-charge type**: `sigma = 0` and `epsilon = 0` means no van der
   Waals, no charge means no Coulomb, and frozen means it cannot move off the centre it defines. It is given a real
   mass because GROMACS will not integrate a massless bead, and it is excluded from nothing because it interacts with
   nothing -- which is the whole point of giving it that type.

**And the manifest carries the numbers the analysis divides with.** The dividing area, the water and solute counts,
the requested *and* achieved molality, the confinement and its constant, and the temperature with where it came from.
An analysis that recomputed the area from a trajectory would be dividing a force by a number the build never agreed
to; recording it at build time means the two are the same number by construction.
"""
import json
import math
import shutil
from pathlib import Path

from dashboard import martini3, paths
from dashboard.execution import devices, protocol, run_inputs, tools
from dashboard.execution.environment import ROOT, recorded_environment
from dashboard.execution.settings import coerce_integers, normalize
from dashboard.execution.stages import Stage, stage_tables
from detergent_validation.execution.adapters import osmotic_box, osmotic_mdp

#: The repository file the one stage runs. Recorded in the manifest's `stage_scripts` by path and digest; the stage's
#: directory stays its working directory, and the driver reaches its own condition directories from there.
OSMOTIC_SCRIPT = 'dashboard/execution/scripts/osmotic_simulation.sh'

REFERENCE_TYPE = 'REF'
REFERENCE_MASS = 72.0          # a real mass, because a massless bead has no defined force; it is restrained anyway
#: The bead's position restraint in z (kJ/mol/nm2). Stiff because it is the coordinate's origin and must not move:
#: at the paper's force it is displaced by ~1e-6 nm, and its own restraint force acts on the bead, not on the solute
#: whose force is measured.
REFERENCE_RESTRAINT = 10000.0
REFERENCE_MOLECULE = 'REFC'
MANIFEST = 'osmotic_condition.json'


def reference_bead_itp(*, residue='REFC'):
    """The one-bead molecule the pull measures against: zero size, zero charge, and therefore no interaction.

    **`[ atomtypes ]` comes first, and that is not cosmetic.** GROMACS resolves an atom's type as it reads the
    moleculetype, so a type declared after the `[ atoms ]` that uses it is not found -- the run failed with
    "Atomtype REF not found" while the type sat visible in the same file, eleven lines below. The first version of
    this function had the block last.
    """
    return (
        f'[ atomtypes ]\n'
        f'; the zero-size type: no van der Waals, and the zero charge means no Coulomb either\n'
        f'{REFERENCE_TYPE}  {REFERENCE_MASS:g}  0.0  A  0.0  0.0\n\n'
        f'[ moleculetype ]\n{REFERENCE_MOLECULE}  1\n\n'
        f'; a frozen, non-interacting bead at the box centre, for the pull to measure against\n'
        f'[ atoms ]\n'
        f';id  type  resnr  residu  atom  cgnr  charge  mass\n'
        f' 1   {REFERENCE_TYPE}   1  {residue}  {REFERENCE_TYPE}   1   0.0   {REFERENCE_MASS:g}\n'
        f'\n'
        f'[ position_restraints ]\n'
        f'; the origin of the pull coordinate, held at the box centre. `refcoord-scaling = all` in the mdps scales\n'
        f'; this target with the box, so the bead is the centre for every box size; a frozen atom would not be\n'
        f'; scaled and would stop being the centre as the barostat changes the box. Stiff because it must not move:\n'
        f'; at the paper\'s force the pull displaces it by 1e-6 nm, and its own restraint force is on the bead, not\n'
        f'; on the solute whose force is measured.\n'
        f'; atom  funct  fcx  fcy  fcz\n'
        f' 1       1      0    0    {REFERENCE_RESTRAINT:g}\n'
    )


def index_groups(*, solute_atoms, reference_atom, solute_molecules, solvent_atoms=()):
    """The `.ndx` naming the pull's two groups, plus the solvent for anything that wants it.

    Indices are 1-based, as GROMACS writes them. A group that is empty or that shares an atom with another is refused
    here: `grompp` would take the file happily and the run would measure something other than what was intended.

    **`System` is written too, and it is not decoration.** Passing `-n` replaces GROMACS's own group list rather than
    adding to it, so an index with only the pull groups leaves the mdps' `tc-grps = System` and `comm-grps = System`
    referring to nothing: the minimization, which has no thermostat, passes, and the first *dynamics* step fails with
    "Group System referenced in the .mdp file was not found in the list of index".

    **One group per solute molecule**, because that is the granularity the confinement acts at: each molecule is
    confined by its own flat-bottom coordinate, and the analysis sums the forces. The solute atoms are written
    consecutively -- each molecule's beads together -- which is what makes `MOL<n>` groups possible at all.
    """
    solute = [int(index) for index in solute_atoms]
    solvent = [int(index) for index in solvent_atoms]
    reference = int(reference_atom)
    if not solute and int(solute_molecules):
        raise ValueError('the solute group is empty, so there is nothing to confine or to measure')
    if reference <= 0:
        raise ValueError(f'the reference atom index {reference} is not 1-based')
    overlap = set(solute) & set(solvent)
    if overlap:
        raise ValueError(f'atom {sorted(overlap)[0]} is in both the solute and the solvent group')
    if reference in set(solute) | set(solvent):
        raise ValueError(f'the reference atom {reference} is also in the solute or solvent group')
    per_molecule = (len(solute) // int(solute_molecules)) if int(solute_molecules) else 0
    if per_molecule * int(solute_molecules) != len(solute):
        raise ValueError(f'{len(solute)} solute atoms do not divide into {solute_molecules} molecules, '
                         'so the per-molecule confinement groups cannot be named')
    lines = ['[ System ]', *[str(index) for index in range(1, max([*solute, reference, *solvent]) + 1)], '']
    for molecule in range(1, int(solute_molecules) + 1):
        first = (molecule - 1) * per_molecule
        lines += [f'[ MOL{molecule} ]', *[str(index) for index in solute[first:first + per_molecule]], '']
    if solute:
        lines += ['[ SOLUTE ]', *[str(index) for index in solute], '']
    lines += ['[ REFERENCE ]', str(reference), '']
    if solvent:
        lines += ['[ SOLVENT ]', *[str(index) for index in solvent], '']
    return '\n'.join(lines)


def build(destination, *, plan, temperature, production_ps=osmotic_mdp.DEFAULT_PRODUCTION_PS,
          equilibration_ps=osmotic_mdp.DEFAULT_EQUILIBRATION_PS,
          output_interval_ps=osmotic_mdp.DEFAULT_OUTPUT_INTERVAL_PS,
          solute_atoms=(), reference_atom=None, solvent_atoms=(), input_paths=None):
    """Write one condition's mdp set, reference bead and index file, and return the record to manifest.

    `plan` is `osmotic_box.plan_condition`'s result -- the counts this build is for. The record returned is what the
    manifest and the analysis both read, so the area a force is divided by is the area this build made. `input_paths` is the
    runner's own input record -- the absolute path of every referenced solute file, of the installed Martini force
    field and of its solvents -- and is written into the condition record so the driver reads the files the manifest
    hashed rather than a copy.
    """
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    mdps = osmotic_mdp.osmotic_mdps(temperature=temperature, solute_molecules=plan['solute_molecules'],
                                    production_ps=production_ps,
                                    equilibration_ps=equilibration_ps,
                                    output_interval_ps=output_interval_ps)
    written = {}
    for stage, text in mdps.items():
        name = {'minimization': 'minimization.mdp', 'equilibration': 'eq.mdp', 'production': 'md.mdp'}[stage]
        (destination / name).write_text(text)
        written[stage] = name
    (destination / 'reference.itp').write_text(reference_bead_itp())
    # The index file needs atom indices, and a caller that does not know them yet -- the osmotic runner, which writes
    # them after placement -- passes none. Writing a placeholder with invented indices would be worse than writing
    # nothing: grompp would read it and the pull would measure the wrong atoms.
    index = (index_groups(solute_atoms=solute_atoms, reference_atom=reference_atom,
                          solute_molecules=plan['solute_molecules'], solvent_atoms=solvent_atoms)
             if solute_atoms and reference_atom is not None else None)
    if index is not None:
        (destination / 'index.ndx').write_text(index)

    record = {
        'molality_requested': plan['requested_molality'],
        'molality_achieved': plan['achieved_molality'],
        'box_nm': plan['box_nm'],
        'box_volume_nm3': plan['box_volume_nm3'],
        'dividing_area_nm2': plan['dividing_area_nm2'],
        'water_beads': plan['water_beads'],
        # **The bead mass, which the runner reads back at the end to report the molality it actually built.** It was
        # in `plan_condition`'s output all along and was dropped here, so `built.json` died with
        # `KeyError: 'water_bead_mass'` -- a defect three runs could not reach, because they failed before the last
        # step. Written down because a reader needs it: the count is meaningless without what a bead weighs.
        'water_bead_mass': plan['water_bead_mass'],
        'water_kg': plan.get('water_kg'),
        'solute_molecules': plan['solute_molecules'],
        'solute_beads': plan.get('solute_beads'),
        'confinement_nm': plan['confinement_nm'],
        'confinement_kj_mol_nm2': plan['confinement_kj_mol_nm2'],
        'temperature': float(temperature),
        'temperature_source': plan.get('temperature_source'),
        'production_ps': float(production_ps),
        'equilibration_ps': float(equilibration_ps),
        'output_interval_ps': float(output_interval_ps),
        'restraint': {'mechanism': 'plumed, flat-bottom, on the absolute z of the box centre',
                      'reference_type': REFERENCE_TYPE,
                      'reference_atom': int(reference_atom) if reference_atom is not None else None},
        'groups': {'solute': len(list(solute_atoms)), 'solvent': len(list(solvent_atoms))},
        'files': written,
        'note': 'the analysis recomputes the force from the trajectory and divides by dividing_area_nm2 above; it '
                'must not recompute that area, or the two would be different numbers',
    }
    if input_paths is not None:
        # Every file the runner reads that it did not itself write: the four solute_root files and the Martini ITP.
        # They are *referenced*, so the driver must be told where they are; this generated record is that answer, and
        # it is written beside the numbers for the same reason -- the runner reads one file, not a second convention.
        record['paths'] = {str(name): str(path) for name, path in dict(input_paths).items()}
    (destination / MANIFEST).write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    return record


def plan_and_build(destination, *, molality, temperature, bead_radii_nm=(), solute_beads_per_molecule=None,
                   solute_atoms=(), reference_atom=None, solvent_atoms=(), **durations):
    """`plan_condition` then `build`, so a caller cannot pass a plan that does not match what was written."""
    plan = osmotic_box.plan_condition(molality, bead_radii_nm=bead_radii_nm,
                                      solute_beads_per_molecule=solute_beads_per_molecule)
    return build(destination, plan=plan, temperature=temperature, solute_atoms=solute_atoms,
                 reference_atom=reference_atom, solvent_atoms=solvent_atoms, **durations)


# --- the run type ----------------------------------------------------------------------------------------------

VERSION = 'osmotic-v1'
#: `draft-smoke` is the repository's execution-only profile -- the same name the CG path uses for candidate screening,
#: and the one an unreviewed mapping is enough for. Its meaning is *short execution test*, so its durations are short:
#: the paper's 500 ns under a profile named for smoke-testing would be a series nobody meant to launch.
PROFILES = ('standard', 'draft-smoke')
#: The files one molecule's solver needs, in each condition's own `solute/`. Named rather than discovered, so a
#: missing one is a blocker with its name in it instead of a failure halfway through a build. The Martini solvent
#: definitions the runner's topology includes are *not* here: they come from the installed set (`dashboard.martini3`),
#: which every run reads where it lies.
SOLUTE_FILES = ('solute.gro', 'solute.itp', 'water.gro')

#: **The build's own files, one set per concentration.** A series owns N conditions and each one is built in its
#: own directory: its own mdps (the solute count depends on the molality), its own reference bead, and its own
#: `osmotic_condition.json` -- which is the record the analysis divides a force by and the runner reads its input
#: paths from. `prepare` writes them under `inputs/conditions/<directory>/` -- the run's immutable generated data --
#: and copies them beside the runner, in the stage, because that is the directory the runner works in.
CONDITION_FILES = ('minimization.mdp', 'eq.mdp', 'md.mdp', 'reference.itp', 'osmotic_condition.json')

#: **One stage, and it is the series.** Two things are deliberate here and each has a reason:
#:
#: * **The series is not one stage per concentration.** The policy on a failed condition -- carry on, the
#:   default, or stop -- is a decision the *run* makes once it knows how the condition ended, and a stage
#:   boundary cannot express "and the next one still runs". So the stage is a driver over the condition
#:   directories, and the conditions, not the stages, are what carry checkpoints: each condition's
#:   `min/eq/md.{cpt,...}` and `attempts.json` sit in its own directory, and one that already finished is skipped
#:   by the driver on the next entry into the stage.
#: * **The paper's 500 ns is one mdrun**, and the three mdrun calls of a condition are inside one stage for the
#:   same reason `cg_simulation.sh` keeps its three: a stage boundary copies the placed system between them.
#:
#: The patterns are globs over the conditions the build wrote, because how many of them there are is the caller's
#: answer rather than this module's. The declared inputs are the run's own `inputs/` record -- the series manifest,
#: the mdps, the reference bead and the generated condition records -- one level above the run's `stages/` root. The
#: molecule's files are *not* copied into either tree: they are referenced in the input record and their absolute
#: paths travel in each condition's own record, which is what the driver reads.
STAGE_DEFS = (
    Stage('Osmotic series', '01_simulate/run.sh',
          ('../../inputs/conditions.json',)
          + tuple(f'../../inputs/conditions/*/{name}' for name in CONDITION_FILES),
          tuple(f'conditions/*/{name}' for name in ('built.json', 'system.top', 'prod/md_whole.xtc')),
          script=OSMOTIC_SCRIPT),
)
STAGES, REQUIRED_INPUTS, REQUIRED_OUTPUTS = stage_tables(STAGE_DEFS)

#: The temperature default is maltose's, from Ebrahimi & Sadeghi 2016, and is a *default* here only because a run type
#: must start somewhere. The route that queues a series is expected to set it from the dataset it compares against, and
#: the report records where it came from either way.
#: **`mdrun_ntomp` is 4, not 8, and that is a measurement about this system.** Eight configurations on this system's
#: own `md.tpr` with the confinement loaded put four threads ahead of every other count (4782 ns/day against 4713 at
#: eight, and worse at two and one); a 2502-bead box pays a per-step synchronisation cost that fewer threads do not.
#: The other adapters keep 8 because their systems are a different size -- this number does not generalise, and it is
#: here rather than in the runner's `${MDRUN_FLAGS:-...}` fallback because `workflow.py` exports `MDRUN_FLAGS` from
#: *these* settings, so the fallback is never reached. That cost a cycle: the fallback was edited first and the
#: running mdrun came back with `-ntomp 8` anyway.
DEFAULTS = dict(temperature_k=308.15,
                osmotic_production_ps=osmotic_mdp.DEFAULT_PRODUCTION_PS,
                osmotic_equilibration_ps=osmotic_mdp.DEFAULT_EQUILIBRATION_PS,
                osmotic_output_interval_ps=osmotic_mdp.DEFAULT_OUTPUT_INTERVAL_PS,
                mdrun_ntomp=4, mdrun_ranks=1, mdrun_gpu=0,
                # **The retry ceiling, and a series' policy on a condition that ends failed.** Three is the house
                # ceiling -- `attempts_max = 3` in `pdc.DEFAULTS` and the loop bound in `pdc_extension.py`. Both are
                # advertised because a setting the adapter does not name is dropped by the queueing routes without
                # complaint, and a default the routes do not keep is a capability that never leaves the form.
                osmotic_attempts_max=3, series_on_failure='carry_on')
SETTING_SPECS = {
    'temperature_k': ('Temperature of the experimental dataset', 200, 400),
    'osmotic_production_ps': ('Production duration', 1, 2000000),
    'osmotic_equilibration_ps': ('Equilibration duration', 1, 100000),
    'osmotic_output_interval_ps': ('Trajectory output interval', 0.002, 10000),
    'mdrun_ntomp': ('mdrun OpenMP threads per rank', 1, 72),
    'mdrun_ranks': ('mdrun MPI ranks', 1, 72),
    # An index into the devices the host reports; `0` keeps the command every existing series produces.
    'mdrun_gpu': ('mdrun GPU device', 0, 64),
    # A count, not a duration: an attempt either happened or did not, so a fractional value is refused rather than
    # silently floored (see `normalize_settings`). The runner also carries a default, for a script run by hand.
    'osmotic_attempts_max': ('Attempts before a condition ends failed', 1, 10),
}

#: A condition's series membership is a string, not a number, so it is declared here rather than in
#: `SETTING_SPECS`. It rides in the settings because that is what the coordinator stores and what the resume path
#: already verifies; inventing a second place to keep it would be a second thing to keep in step. `solute_root` is
#: here for the same reason and one more: it is what `prepare` reads to find the molecule's files, and a run whose
#: files could not be found afterwards would be a run type that cannot be resumed.
CHOICE_SPECS = {'series_id': ('The series this condition belongs to', ()),
                'solute_root': ('Directory holding the solute, its topology and the water tile', ()),
                # A series is many runs, so what one condition's failure does to the others is a policy the series
                # carries rather than a property of a condition. `carry_on` is the existing batch route's contract
                # (every condition is created up front, so a failure does not cancel queued siblings); `stop` is the
                # other choice the user asked be offered, and the driver that can honour it is a later task.
                'series_on_failure': ('What a series does when a condition ends failed', ('carry_on', 'stop'))}


# --- the series: one run, N concentrations --------------------------------------------------------------------
#
# A series used to be N `osmotic` *jobs* sharing a `series_id`. With `max_concurrent_runs: 1` that is a
# one-condition series -- `create_job` refuses the second with `CapacityFull`, and nothing starts a job that is
# merely `queued` -- so the shape could not deliver what it promised. The series is the run instead: the settings
# carry the concentrations, `prepare` builds one directory per concentration, and the runner drives them in the
# order the caller gave them, one at a time.

#: The key the concentrations travel under. A *list*, so it is deliberately in neither `SETTING_SPECS` (one
#: bounded scalar) nor `CHOICE_SPECS` (one of an enumerated set): neither shape renders a list, and a form control
#: that silently dropped it is exactly why the series route reads its own body.
SERIES_KEY = 'molalities'
#: The file `prepare` writes for the runner: the ordered conditions and the policy on a failed one. The runner
#: reads it by this name, so the name is the contract between the build and the script.
CONDITIONS_MANIFEST = 'conditions.json'
#: Where a condition's directory sits, relative to the stage directory.
CONDITIONS_DIRECTORY = 'conditions'
#: The carbohydrate registry: this repository's own list of the sugars it carries a citation for.
CARBOHYDRATE_REGISTRY = Path('resources/validation/carbohydrates/targets-v1.json')


# --- the one shape this run type accepts, and how a reader tells the shapes apart -------------------------------
#
# A series used to be N sibling `osmotic` jobs, one concentration each. The series is the run now: ONE run whose
# settings carry `molalities`, the concentrations it owns. The old shape cannot be built again -- `osmotic_molality`
# is not even a setting any more -- and a payload that names no concentrations is refused rather than completed with
# a default, because the default is what made a one-condition run look like a series.

#: The shape, in the words a refusal uses. Named once so the route, the coordinator's admission and the run type's
#: own setting check all refuse a caller with the same sentence -- and a sentence that says what to send instead.
SERIES_SHAPE = 'one run owning N concentrations, listed in `molalities` (e.g. [0.5, 1.0])'
#: The shape it replaced, named in the same refusal so the refusal is not just a no.
SIBLING_SHAPE = 'N sibling `osmotic` jobs, one molality each'


def series_shape_reason():
    """What a payload that names no concentrations is refused with: the shape, and what it is not."""
    return (f'an osmotic run is {SERIES_SHAPE}. It is not {SIBLING_SHAPE} -- the six hand-queued one-condition '
            f'runs on this workspace were made that way, and `max_concurrent_runs: 1` could never run them as a '
            f'series. Queue the whole series as one run, with the concentrations in `{SERIES_KEY}`.')


def refuse_legacy_shape(settings):
    """None when `settings` describe the one shape this run type accepts, otherwise the reason it is refused.

    **How a reader tells an old record from a new one.** One-sided, and that is the point: a record this run type
    builds always carries `molalities`; a record built before the series existed carries a single `osmotic_molality`
    and no `molalities`, and `osmotic_molality` is not a published setting any more. So `molalities` present means
    series, `molalities` absent means the old shape -- and this function is the cheap half a caller can ask
    (`admission.validate_run_type` does, before anything is built). `series_of` below is the reader's half.
    """
    values = (settings or {}).get(SERIES_KEY)
    if values in (None, '', []):
        return series_shape_reason()
    return None


def series_of(settings):
    """The conditions a record's settings name, or None when the record predates the series shape.

    The reader's half of the marker above. `None` means an old single-condition job, never "a series with no
    concentrations": `normalize_settings` refuses to build one of those, so the two states cannot be confused.
    """
    if refuse_legacy_shape(settings):
        return None
    return series_conditions((settings or {})[SERIES_KEY])


def condition_directory(index, molality):
    """The directory one concentration is built and run in, named so a reader can see which it is."""
    return f'{index:02d}_{float(molality):g}molal'


def series_conditions(molalities):
    """The ordered conditions a series owns -- the plan the build, the runner and the reader all read."""
    return [{'index': index, 'molality': float(molality), 'directory': condition_directory(index, molality)}
            for index, molality in enumerate(molalities)]


def conditions_of(settings):
    """The ordered conditions a run's settings describe; a record that names no series is refused, not defaulted."""
    conditions = series_of(settings)
    if conditions is None:
        raise ValueError(series_shape_reason())
    return conditions


def _molalities(requested):
    """The series' concentrations: ordered, each inside the range the box can place, and none repeated.

    A record that names none is refused rather than defaulted to one concentration -- the fallback that used to be
    here is what let a single-condition run look like a series. Two conditions at one molality are refused rather
    than merged: they would be one directory and one measurement reported twice.
    """
    if requested in (None, '', []):
        raise ValueError(series_shape_reason())
    values = requested if isinstance(requested, (list, tuple)) else str(requested).replace(',', ' ').split()
    low, high = osmotic_box.MOLALITY_RANGE
    numbers = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'{SERIES_KEY} must be numeric') from exc
        if not math.isfinite(number) or not low <= number <= high:
            raise ValueError(f'{SERIES_KEY} {number:g} must be between {low} and {high}')
        numbers.append(number)
    if not numbers:
        raise ValueError(f'{SERIES_KEY} must name at least one molality')
    repeated = sorted({value for value in numbers if numbers.count(value) > 1})
    if repeated:
        raise ValueError(f'{SERIES_KEY} names {repeated[0]:g} molal twice, and two conditions at one molality '
                         'would be one directory and one measurement reported twice')
    return numbers


def carbohydrate_names(root=None):
    """Every carbohydrate the repository names, in the registry's own order."""
    path = Path(root or ROOT) / CARBOHYDRATE_REGISTRY
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


def refuse_non_sugar(molecule_id, molecule_root=None, root=None):
    """None when `molecule_id` names a sugar, otherwise the reason it is refused.

    **The gate, and why it is two facts rather than one.** The repository's own answer to "is this a sugar" is
    the carbohydrate registry and the sugar recogniser, and neither alone is enough:

    * the registry (`resources/validation/carbohydrates/targets-v1.json`) names the carbohydrates the repository
      carries a citation for. It is the *declared* vocabulary, so a name in it is a sugar -- Glucose is one, and
      it has no molecule folder at all, which is a reason the catalogue cannot *build* it rather than a reason
      this gate refuses it;
    * a molecule with a folder is a sugar when the recogniser can account for the whole of its connectivity:
      `identification.identify` matches the ring sizes and the linkage letters against the reference table and
      says how many heavy atoms are left over.

    **DDM is the case that makes the second condition necessary and a ring test wrong.** DDM is a glucoside: it
    *has* two recognised hexopyranose rings, so "contains a recognised ring" admits it. What it is not is a
    sugar -- twelve heavy atoms of alkyl chain sit outside those rings -- and the leftover count is what says so.
    """
    if molecule_id in carbohydrate_names(root):
        return None
    molecules = Path(molecule_root) if molecule_root is not None else Path(root or ROOT) / 'molecules'
    folder = molecules / str(molecule_id)
    if not str(molecule_id or '') or not folder.is_dir():
        return (f'{molecule_id} is not a carbohydrate: it has no folder under molecules/ and the carbohydrate '
                f'registry ({CARBOHYDRATE_REGISTRY}) does not name it. An osmotic series takes a sugar as its '
                'solute.')
    try:
        from dashboard.models.mappings import context as mapping_context
        from dashboard.models.sugars import identification
        structure = mapping_context.as_structure(mapping_context.build_context(molecules, molecule_id))
        identified = identification.identify(structure) or {}
    except (OSError, ValueError) as exc:
        return f'{molecule_id} is not a carbohydrate: its structure could not be read ({exc})'
    if identified.get('entry') and identified.get('covers_whole_molecule'):
        return None
    outside = identified.get('outside_atoms')
    if outside:
        return (f'{molecule_id} is not a carbohydrate: its structure has {outside} heavy atoms outside the '
                'recognised sugar rings, so it is a molecule with a sugar head group rather than a sugar')
    return f'{molecule_id} is not a carbohydrate: its structure has no recognised pyranose or furanose ring'


def stage_defaults(profile='standard'):
    if profile not in PROFILES:
        raise ValueError(f'unknown osmotic profile: {profile}')
    values = dict(DEFAULTS)
    if profile != 'standard':
        values.update(osmotic_production_ps=1000.0, osmotic_equilibration_ps=1000.0)
    return {'values': values, 'sources': {'osmotic': VERSION}, 'profile': profile}


def normalize_settings(settings=None, profile='standard'):
    if settings is not None and not isinstance(settings, dict):
        raise ValueError('osmotic settings must be an object')
    requested = dict(settings or {})
    # **The shape, before anything else.** A payload that names no concentrations is refused here rather than
    # completed with a default -- and refused before the vocabulary loop, so the reason is the shape's rather than
    # "Unknown osmotic setting" for whatever key the old shape happened to use.
    refused = refuse_legacy_shape(requested)
    if refused:
        raise ValueError(refused)
    # **The concentrations come out first, and the shape is why.** `molalities` is a list, and a list has no
    # place in the published vocabulary -- a bounded scalar or one of an enumerated set -- so the loop below
    # would answer it with "Unknown osmotic setting" rather than with anything about the values in it.
    molalities = requested.pop(SERIES_KEY, None)
    result = normalize(
        requested, stage_defaults(profile)['values'], specs=SETTING_SPECS, choices=CHOICE_SPECS,
        unknown_prefix='Unknown osmotic setting: ', choice_text=True)
    # The series, in the caller's order: the run type's own check, so a value outside the box's range is refused
    # with the bound named and a record that names no series is refused with the shape named.
    result[SERIES_KEY] = _molalities(molalities)
    # An attempt count and a device index are counts: 2.5 of either is refused rather than floored, because
    # three-and-a-half attempts is not a thing a reader can reconcile with `attempts.json`, and a floored device
    # index would run on one nobody chose. Checked after the series, so a ragged series is refused first -- the
    # order these checks have always had.
    coerce_integers(result, {'osmotic_attempts_max': 'osmotic_attempts_max must be a whole number of attempts',
                             'mdrun_gpu': 'mdrun_gpu must be a whole device index'})
    # Threads and ranks are counts too, but they have always been floored rather than refused; only the attempt
    # ceiling and the device index carry a message.
    for key in ('mdrun_ntomp', 'mdrun_ranks'):
        result[key] = int(result[key])
    # The mdps refuse a duration that is not a whole number of output intervals, and so does this: two conditions with
    # different averaging windows are not comparable, and the earlier the refusal the cheaper it is.
    ratio = result['osmotic_production_ps'] / result['osmotic_output_interval_ps']
    if abs(ratio - round(ratio)) > 1e-9:
        raise ValueError('osmotic_production_ps must be a whole number of output intervals')
    return result


def tool_metadata():
    return tools.record_versions('gmx', missing=lambda name: ValueError('GROMACS executable is unavailable'))


def solute_bead_radii(mapping_snapshot):
    """The radii a mapping's beads imply, from the type letters the sugar recogniser already uses.

    Imported rather than restated: `RADII_NM` is this repository's own table, and a second copy would be a second
    answer to the same question.
    """
    from dashboard.models.sugars import recognition
    beads = []
    for bead in (mapping_snapshot or {}).get('beads') or []:
        if not isinstance(bead, dict) or bead.get('virtual_site') or not bead.get('atoms'):
            continue                      # a massless TC4 site has no volume to leave room for
        letter = str(bead.get('type') or bead.get('size') or '')[:1].upper()
        if letter in recognition.RADII_NM:
            beads.append(recognition.RADII_NM[letter])
    return beads


def _protocol_stage_contract(metadata):
    return STAGES, REQUIRED_INPUTS, REQUIRED_OUTPUTS


def _protocol_stages(metadata):
    return tuple(STAGE_DEFS)


def _protocol_readiness(metadata):
    return readiness(metadata)


def _protocol_prepare(run_dir, metadata):
    prepare(run_dir, metadata)


def _solute_root(metadata):
    """Where the solute's files are.

    A setting, because settings are what the coordinator stores and what the resume path verifies -- but a top-level
    key is honoured too, so a direct caller can pass either spelling. A run that could not find its own inputs
    afterwards would be a run type that cannot be resumed.
    """
    settings = metadata.get('settings') or {}
    return str(metadata.get('solute_root') or settings.get('solute_root') or '').strip()


def readiness(metadata):
    """Whether a series can be built, in the shared shape: every check stated, every blocker named."""
    checks, blockers = [], []
    molecule_id = metadata.get('molecule_id')
    if molecule_id:
        # The run type's own first rule, and the reason it is here rather than only in the route: a payload can
        # reach the coordinator without passing through a route, so the gate has to hold on this path too.
        refused = refuse_non_sugar(molecule_id, molecule_root=metadata.get('molecule_root'),
                                   root=metadata.get('project_root'))
        checks.append({'label': 'Solute is a carbohydrate', 'path': str(molecule_id), 'ready': refused is None,
                       'detail': refused or 'Named by the carbohydrate registry, or its structure is accounted '
                                            'for entirely by recognised sugar rings.'})
        if refused:
            blockers.append(refused)
    else:
        blockers.append('molecule_id is required to check an osmotic run')

    # The concentrations: the list is the run's own plan, so a value the box cannot place is refused here as
    # well as in the setting's own range check -- which only the route applies.
    settings = metadata.get('settings') or {}
    molalities = []
    conditions = []
    try:
        molalities = _molalities(settings.get(SERIES_KEY))
        conditions = series_conditions(molalities)
    except ValueError as exc:
        molalities = []
        blockers.append(str(exc))
    checks.append({'label': 'Concentrations',
                   'path': ', '.join(f'{value:g}' for value in molalities) + ' molal' if molalities else 'none',
                   'ready': bool(conditions),
                   'detail': (f'{len(conditions)} condition(s), one directory each: '
                              + ', '.join(condition['directory'] for condition in conditions))
                   if conditions else 'No concentration is set, so there is no series to run'})

    # The box is sized from the mapping's own beads -- `plan_condition` subtracts the solute's volume, and a
    # mapping with no beads leaves it with none. Without this check a run would build at the right molality *of
    # water* and quietly get the solute volume wrong, which no internal consistency check would notice.
    mapping = metadata.get('mapping_snapshot') or metadata.get('mapping_candidate') or {}
    radii = solute_bead_radii(mapping)
    checks.append({'label': 'CG mapping', 'path': str(mapping.get('file') or 'selected snapshot'),
                   'ready': bool(radii),
                   'detail': (f"{len(radii)} bead radii, which size the volume the solute occupies"
                              if radii else "No beads: the box is sized from the mapping's bead radii "
                                            '(`osmic.solute_bead_radii`)')})
    if not radii:
        blockers.append("a saved CG mapping is required: the box's solute volume is sized from its beads' radii, "
                        'and a mapping with no beads leaves the solute with no volume to displace')

    solute_root = _solute_root(metadata)
    if not solute_root or not Path(str(solute_root)).is_dir():
        blockers.append('solute_root is required: a directory holding ' + ', '.join(SOLUTE_FILES))
    else:
        missing = [name for name in SOLUTE_FILES if not (Path(str(solute_root)) / name).is_file()]
        checks.append({'label': 'Solute', 'path': str(solute_root), 'ready': not missing,
                       'detail': ('One molecule with its topology and the water tile.'
                                  if not missing else 'Missing: ' + ', '.join(missing))})
        if missing:
            blockers.append('solute_root is missing ' + ', '.join(missing))

    executable = tools.tool_path('gmx')
    available = bool(executable)
    checks.append({'label': 'GROMACS', 'path': executable or 'gmx', 'ready': available,
                   'detail': (str(executable) if available else 'Executable not found')})
    if not available:
        blockers.append('GROMACS executable is unavailable')
    return {'ready': not blockers, 'checks': checks, 'blockers': blockers, 'scientifically_validated': False}


def prepare(run_dir, metadata):
    """Write the series: one directory per concentration, and the runner that drives them in order.

    **One stage, N condition directories.** Each concentration gets its own everything -- its mdps (the solute
    count is the molality's), its reference bead, its `osmotic_condition.json`, and the directory its
    `min/eq/md.{cpt,...}` and `attempts.json` will be written into. That directory is what a retry of that condition
    continues from, and it is why a second entry into the series resumes rather than restarts.

    **The layout is every other run type's**: the stages under `stages/` and the generated data under `inputs/`.
    What the run *reads* -- the molecule's three files and the installed Martini force field and solvents -- already
    existed when prepare ran, so it is recorded by path and digest and never copied into the run. Each condition's
    `osmotic_condition.json` carries the absolute path of every referenced file, which is what the driver reads; a copy
    in the stage would be a second answer to where the file is.

    `solute_atoms` and `reference_atom` are left empty on purpose: the pull's groups are atom indices, and those
    do not exist until the runner has placed the molecules. The runner writes the real index file from these mdps.
    """
    run_dir = Path(run_dir)
    settings = normalize_settings(metadata.get('settings'), metadata.get('profile', 'standard'))
    # The device must be one this host reports, before any condition directory is written. A host with no devices
    # is not a refusal (`devices.require`).
    devices.require(settings['mdrun_gpu'])
    molecule_id = metadata.get('molecule_id')
    # The sugar gate, at the build as well as at the door: without it a non-sugar reaches GROMACS and the failure
    # is a GROMACS error rather than the answer to "what did you ask me to run a series with".
    refused = refuse_non_sugar(molecule_id, molecule_root=metadata.get('molecule_root'))
    if refused:
        raise ValueError(refused)

    # The molecule's files, checked once and recorded where they already are. A missing one is a refusal here, where
    # its name is known, rather than a failure inside GROMACS.
    root = _solute_root(metadata)
    if not root:
        raise ValueError('solute_root is required: a directory holding ' + ', '.join(SOLUTE_FILES))
    references, solute_paths = _solute_references(Path(root), SOLUTE_FILES)
    force_field = martini3.path('martini_v3.0.0.itp')
    force_field_entry = run_inputs.installed('force_field', force_field, label=force_field.name)
    references.append(force_field_entry)
    solvents = martini3.path('martini_v3.0.0_solvents_v1.itp')
    solvents_entry = run_inputs.installed('martini_solvents', solvents, label=solvents.name)
    references.append(solvents_entry)
    # The runner reads these absolute paths rather than a copy: the molecule's own files come from `solute_root`, and the
    # force field and solvent definitions from the installed Martini set; all of them are named by the run's own input
    # record. The solvents key keeps the name the stage script has always read.
    input_paths = {**solute_paths,
                   'force_field': str(run_inputs.resolve(force_field_entry)),
                   'martini_v3.0.0_solvents_v1.itp': str(run_inputs.resolve(solvents_entry))}

    conditions = series_conditions(settings[SERIES_KEY])
    mapping_snapshot = metadata.get('mapping_snapshot') or {}
    bead_radii = solute_bead_radii(mapping_snapshot)
    beads_per_molecule = len([bead for bead in (mapping_snapshot.get('beads') or [])
                              if isinstance(bead, dict) and bead.get('atoms')]) or None

    inputs = run_dir / 'inputs'
    stage = run_dir / 'stages' / '01_simulate'
    records = []
    for condition in conditions:
        directory = condition['directory']
        destination = inputs / CONDITIONS_DIRECTORY / directory
        plan = osmotic_box.plan_condition(condition['molality'], bead_radii_nm=bead_radii,
                                          solute_beads_per_molecule=beads_per_molecule)
        record = build(destination, plan=plan, temperature=settings['temperature_k'],
                       production_ps=settings['osmotic_production_ps'],
                       equilibration_ps=settings['osmotic_equilibration_ps'],
                       output_interval_ps=settings['osmotic_output_interval_ps'], input_paths=input_paths)
        records.append(dict(record, directory=directory, molality=condition['molality']))
        if record['solute_molecules'] == 0:
            # A zero-molality condition is a legitimate control and is stated as one, per condition, rather than
            # looking like a run whose solute count went missing.
            (destination / 'control.json').write_text(
                json.dumps({'molality': 0.0,
                            'note': 'pure solvent: the osmotic pressure of this condition is zero by construction '
                                    'and it exists to show the measurement floor rather than a value'},
                           indent=2, sort_keys=True) + '\n')

    # The series' own manifest -- the ordered conditions plus the policy on a failed one. It is the only place the
    # order is written down, and the runner reads it from its own directory, so both halves read one file.
    series = {'series_id': settings.get('series_id'), 'molecule_id': molecule_id,
              'series_on_failure': settings.get('series_on_failure', 'carry_on'),
              'attempts_max': int(settings['osmotic_attempts_max']), 'conditions': conditions}
    inputs.mkdir(parents=True, exist_ok=True)
    (inputs / CONDITIONS_MANIFEST).write_text(json.dumps(series, indent=2, sort_keys=True) + '\n')

    # The runner works *in* the stage directory, so the generated per-condition data is copied beside it -- the mdps,
    # the reference bead and the record with the input paths. Only generated bytes are staged: the molecule files and
    # the force field stay where the input record names them, so the run holds no copy of a pre-existing store file.
    stage.mkdir(parents=True, exist_ok=True)
    shutil.copy2(inputs / CONDITIONS_MANIFEST, stage / CONDITIONS_MANIFEST)
    for condition in conditions:
        directory = condition['directory']
        source = inputs / CONDITIONS_DIRECTORY / directory
        target = stage / CONDITIONS_DIRECTORY / directory
        target.mkdir(parents=True, exist_ok=True)
        for name in (*CONDITION_FILES, 'control.json'):
            if (source / name).is_file():
                shutil.copy2(source / name, target / name)

    protocol.write_prepared_manifest(
        run_dir, {'molecule_id': molecule_id, 'settings': dict(settings),
                  'run_type': 'osmotic', 'workflow_version': VERSION, 'series': series},
        tools=tool_metadata(), plan=[name for name, _ in STAGES], environment=recorded_environment(),
        references=references, scripts={'Osmotic series': OSMOTIC_SCRIPT},
        modules={'osmotic': 'dashboard/execution/adapters/osmotic.py',
                 'osmotic_mdp': 'dashboard/execution/adapters/osmotic_mdp.py',
                 'tools': 'dashboard/execution/tools.py'})
    return {'series_id': settings.get('series_id'), 'molalities': list(settings[SERIES_KEY]),
            'conditions': records}


def _solute_references(root, names):
    """The molecule's files, recorded by where they already live and resolved to the paths the runner reads.

    Under the workspace a file is spelled relative to it (`store`); outside every configured root it is recorded
    absolutely. The absolute path goes into the condition record because the runner executes with a stage directory
    as its working directory and a relative spelling would be read from the wrong place.
    """
    workspace = paths.current().workspace.resolve()
    references, resolved = [], {}
    for name in names:
        source = Path(root) / name
        if not source.is_file():
            raise ValueError(f'solute_root is missing {name}: {root}')
        source = source.resolve()
        entry = (run_inputs.store('solute', source, label=name, workspace_root=workspace)
                 if source.is_relative_to(workspace) else run_inputs.absolute('solute', source, label=name))
        references.append(entry)
        resolved[name] = str(run_inputs.resolve(entry))
    return references, resolved


PROTOCOL = protocol.Protocol(
    name='osmotic',
    stage_contract=_protocol_stage_contract,
    stages=_protocol_stages,
    settings_specs=lambda: SETTING_SPECS,
    stage_defaults=stage_defaults,
    normalize_settings=lambda settings=None, profile='standard': normalize_settings(settings, profile),
    readiness=_protocol_readiness,
    prepare=_protocol_prepare,
    tool_report=tool_metadata,
    choice_specs=lambda: CHOICE_SPECS,
)
