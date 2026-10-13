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
import subprocess
from pathlib import Path

from ... import files
from .. import protocol, tools
from ..environment import ROOT, TUTORIAL_TEMPLATE, recorded_environment
from ..stages import Stage, stage_tables
from . import osmotic_box, osmotic_mdp

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'

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
          solute_atoms=(), reference_atom=None, solvent_atoms=()):
    """Write one condition's mdp set, reference bead and index file, and return the record to manifest.

    `plan` is `osmotic_box.plan_condition`'s result -- the counts this build is for. The record returned is what the
    manifest and the analysis both read, so the area a force is divided by is the area this build made.
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
#: **One stage, deliberately.** The paper's 500 ns is one mdrun, and splitting minimization, equilibration and
#: production into separate stages would copy the placed system between them -- which is exactly why
#: `cg_simulation.sh` runs its three mdrun calls inside a single stage too. The plan said seven stages before this
#: script existed; this is the table the script actually has.
#: The build's own files, named relative to the stage directory (`../inputs/x`, the way `aa.py` names
#: `../01_solvation/system.gro`): these are what `prepare` writes into the run's `inputs/`, and what the executor
#: checks before the stage runs. The molecule's files are *not* here -- they come from `solute_root` into the stage's
#: own `solute/`, which is the layout the runner reads, and declaring them here as well is what a first version of
#: this tuple got wrong twice.
STAGE_FILES = ('minimization.mdp', 'eq.mdp', 'md.mdp', 'reference.itp', 'osmotic_condition.json')
STAGE_DEFS = (
    Stage('Osmotic condition', '01_simulate/run.sh',
          tuple(f'../inputs/{name}' for name in STAGE_FILES),
          ('prod/md_whole.xtc', 'built.json', 'system.top')),
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
                osmotic_molality=1.0, mdrun_ntomp=4, mdrun_ranks=1,
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
    'osmotic_molality': ('Molality', 0.0, 2.5),
    'mdrun_ntomp': ('mdrun OpenMP threads per rank', 1, 72),
    'mdrun_ranks': ('mdrun MPI ranks', 1, 72),
    # A count, not a duration: an attempt either happened or did not, so a fractional value is refused rather than
    # silently floored (see `normalize_settings`). The runner also carries a default, for a script run by hand.
    'osmotic_attempts_max': ('Attempts before a condition ends failed', 1, 10),
}
#: The files one molecule's solver needs, in `solute_root`. Named rather than discovered, so a missing one is a
#: blocker with its name in it instead of a failure halfway through a build. The last is the Martini solvent
#: definitions the runner's topology includes, from beside the molecule in the stage's own `solute/` directory.
SOLUTE_FILES = ('solute.gro', 'solute.itp', 'water.gro', 'martini_v3.0.0_solvents_v1.itp')


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
    result = dict(stage_defaults(profile)['values'])
    for key, value in (settings or {}).items():
        if key in CHOICE_SPECS:
            label, allowed = CHOICE_SPECS[key]
            text = str(value)
            if allowed and text not in allowed:
                raise ValueError(f'{key} must be one of ' + ', '.join(allowed))
            result[key] = text
            continue
        if key not in SETTING_SPECS:
            raise ValueError('Unknown osmotic setting: ' + key)
        try:
            value = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(key + ' must be numeric') from exc
        label, low, high = SETTING_SPECS[key]
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'{key} must be between {low} and {high}')
        result[key] = value
    # An attempt count is a count. `2.5` is refused rather than floored: three-and-a-half attempts is not a thing a
    # reader can reconcile with the `attempts.json` the runner writes.
    if result['osmotic_attempts_max'] != int(result['osmotic_attempts_max']):
        raise ValueError('osmotic_attempts_max must be a whole number of attempts')
    for key in ('mdrun_ntomp', 'mdrun_ranks', 'osmotic_attempts_max'):
        result[key] = int(result[key])
    # The mdps refuse a duration that is not a whole number of output intervals, and so does this: two conditions with
    # different averaging windows are not comparable, and the earlier the refusal the cheaper it is.
    ratio = result['osmotic_production_ps'] / result['osmotic_output_interval_ps']
    if abs(ratio - round(ratio)) > 1e-9:
        raise ValueError('osmotic_production_ps must be a whole number of output intervals')
    return result


def tool_metadata():
    executable = tools.tool_path('gmx')
    if not executable:
        raise ValueError('GROMACS executable is unavailable')
    result = subprocess.run([executable, '--version'], capture_output=True, text=True, check=True, timeout=30)
    return {'gmx': {'path': executable, 'version_output': result.stdout, 'sha256': files.sha256(executable)}}


def solute_bead_radii(mapping_snapshot):
    """The radii a mapping's beads imply, from the type letters the sugar recogniser already uses.

    Imported rather than restated: `RADII_NM` is this repository's own table, and a second copy would be a second
    answer to the same question.
    """
    from ...models.sugars import recognition
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
    """Whether a condition can be built, in the shared shape: every check stated, every blocker named."""
    checks, blockers = [], []
    molecule_id = metadata.get('molecule_id')
    if molecule_id:
        checks.append({'label': 'Molecule', 'path': str(molecule_id), 'ready': True,
                       'detail': 'The solute is taken from solute_root; this names the molecule the report will.'})
    else:
        blockers.append('molecule_id is required to check an osmotic run')

    solute_root = _solute_root(metadata)
    if not solute_root or not Path(str(solute_root)).is_dir():
        blockers.append('solute_root is required: a directory holding ' + ', '.join(SOLUTE_FILES))
    else:
        missing = [name for name in SOLUTE_FILES if not (Path(str(solute_root)) / name).is_file()]
        checks.append({'label': 'Solute', 'path': str(solute_root), 'ready': not missing,
                       'detail': ('One molecule with its topology, the water tile and the solvent itp.'
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
    """Write the condition's inputs and stage its script, the way every other run type prepares a run.

    `solute_atoms` and `reference_atom` are left empty on purpose: the pull's groups are atom indices, and those do
    not exist until the runner has placed the molecules. The runner writes the real index file from these mdps.
    """
    run_dir = Path(run_dir)
    settings = normalize_settings(metadata.get('settings'), metadata.get('profile', 'standard'))
    mapping_snapshot = metadata.get('mapping_snapshot') or {}
    plan = osmotic_box.plan_condition(settings['osmotic_molality'],
                                      bead_radii_nm=solute_bead_radii(mapping_snapshot),
                                      solute_beads_per_molecule=len([
                                          bead for bead in (mapping_snapshot.get('beads') or [])
                                          if isinstance(bead, dict) and bead.get('atoms')]) or None)
    record = build(run_dir / 'inputs', plan=plan, temperature=settings['temperature_k'],
                   production_ps=settings['osmotic_production_ps'],
                   equilibration_ps=settings['osmotic_equilibration_ps'],
                   output_interval_ps=settings['osmotic_output_interval_ps'])
    stage = run_dir / '01_simulate'
    (stage / 'solute').mkdir(parents=True, exist_ok=True)
    # **The stage's working directory is the stage directory**, so a script that imports this repository's own modules
    # cannot find them from `.`. The root is written in, the way the CG templates get theirs, rather than assumed from
    # the environment, which does not set it: the first real run placed its molecules and then died with
    # `ModuleNotFoundError: No module named 'dashboard'` on the very next line.
    script = (SCRIPTS / 'osmotic_simulation.sh').read_text()
    # The retry ceiling reaches the runner the way `REPO_ROOT` does: a stage script is a file read at prepare time, so
    # a per-run value is written into it here. The runner keeps its own `${OSMOTIC_ATTEMPTS_MAX:-3}` for a script run
    # by hand; this replaces the whole assignment so the run's own setting is the one it uses.
    script = script.replace('OSMOTIC_ATTEMPTS_MAX="${OSMOTIC_ATTEMPTS_MAX:-3}"',
                            f'OSMOTIC_ATTEMPTS_MAX="{int(settings["osmotic_attempts_max"])}"')
    (stage / 'run.sh').write_text(script.replace('REPO_ROOT="${REPO_ROOT:-.}"', f'REPO_ROOT="{ROOT}"'))
    # The molecule's files go to **both** places, and each has a reason: `inputs/` is what the prepared manifest
    # hashes, so the run's own record covers which molecule was simulated; `solute/` beside the stage is the layout
    # the runner documents and reads. A missing molecule file is a refusal here, where the name is known, rather
    # than a failure inside GROMACS.
    root = _solute_root(metadata)
    if root:
        for name in SOLUTE_FILES:
            if not (Path(root) / name).is_file():
                raise ValueError(f'solute_root is missing {name}: {root}')
            shutil.copy2(Path(root) / name, run_dir / 'inputs' / name)
            shutil.copy2(Path(root) / name, stage / 'solute' / name)
    for name in ('minimization.mdp', 'eq.mdp', 'md.mdp', 'reference.itp', 'osmotic_condition.json'):
        shutil.copy2(run_dir / 'inputs' / name, stage / name)
    # The force field the topology includes at its top level, from the source the CG path copies it from. It is not a
    # molecule file and did not come from `solute_root`, so it is staged here -- and grompp's refusal to find it is
    # what a run looks like when it is missing, one step before minimization.
    force_field = TUTORIAL_TEMPLATE / '3_initial_CG' / 'martini_v3.0.0.itp'
    if not force_field.is_file():
        raise ValueError(f'the Martini force field is missing: {force_field}')
    shutil.copy2(force_field, stage / 'martini_v3.0.0.itp')
    if record['solute_molecules'] == 0:
        # A zero-molality condition is a legitimate control and is stated as one rather than looking like a mistake.
        (run_dir / 'inputs' / 'control.json').write_text(
            json.dumps({'molality': 0.0,
                        'note': 'pure solvent: the osmotic pressure of this condition is zero by construction and it '
                                'exists to show the measurement floor rather than a value'},
                       indent=2, sort_keys=True) + '\n')
    protocol.write_prepared_manifest(
        run_dir, {'molecule_id': metadata.get('molecule_id'), 'settings': dict(metadata.get('settings') or {}),
                  'run_type': 'osmotic', 'workflow_version': VERSION}, tools=tool_metadata(),
        plan=[name for name, _ in STAGES], environment=recorded_environment())
    return record


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
