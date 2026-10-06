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
from ..environment import recorded_environment
from ..stages import Stage, stage_tables
from . import osmotic_box, osmotic_mdp

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'

REFERENCE_TYPE = 'REF'
REFERENCE_MASS = 72.0          # a real mass, because a massless bead has no defined force; it is frozen anyway
REFERENCE_MOLECULE = 'REFC'
MANIFEST = 'osmotic_condition.json'


def reference_bead_itp(*, residue='REFC'):
    """The one-bead molecule the pull measures against: zero size, zero charge, and therefore no interaction."""
    return (
        f'[ moleculetype ]\n{REFERENCE_MOLECULE}  1\n\n'
        f'; a frozen, non-interacting bead at the box centre, for the pull to measure against\n'
        f'[ atoms ]\n'
        f';id  type  resnr  residu  atom  cgnr  charge  mass\n'
        f' 1   {REFERENCE_TYPE}   1  {residue}  {REFERENCE_TYPE}   1   0.0   {REFERENCE_MASS:g}\n\n'
        f'[ atomtypes ]\n'
        f'; the zero-size type: no van der Waals, and the zero charge above means no Coulomb either\n'
        f'{REFERENCE_TYPE}  {REFERENCE_MASS:g}  0.0  A  0.0  0.0\n'
    )


def index_groups(*, solute_atoms, reference_atom, solvent_atoms=()):
    """The `.ndx` naming the pull's two groups, plus the solvent for anything that wants it.

    Indices are 1-based, as GROMACS writes them. A group that is empty or that shares an atom with another is refused
    here: `grompp` would take the file happily and the run would measure something other than what was intended.
    """
    solute = [int(index) for index in solute_atoms]
    solvent = [int(index) for index in solvent_atoms]
    reference = int(reference_atom)
    if not solute:
        raise ValueError('the solute group is empty, so there is nothing to confine or to measure')
    if reference <= 0:
        raise ValueError(f'the reference atom index {reference} is not 1-based')
    overlap = set(solute) & set(solvent)
    if overlap:
        raise ValueError(f'atom {sorted(overlap)[0]} is in both the solute and the solvent group')
    if reference in set(solute) | set(solvent):
        raise ValueError(f'the reference atom {reference} is also in the solute or solvent group')
    lines = ['[ SOLUTE ]', *[str(index) for index in solute], '', '[ REFERENCE ]', str(reference), '']
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
    mdps = osmotic_mdp.osmotic_mdps(temperature=temperature, production_ps=production_ps,
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
    index = (index_groups(solute_atoms=solute_atoms, reference_atom=reference_atom, solvent_atoms=solvent_atoms)
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
        'solute_molecules': plan['solute_molecules'],
        'solute_beads': plan.get('solute_beads'),
        'confinement_nm': plan['confinement_nm'],
        'confinement_kj_mol_nm2': plan['confinement_kj_mol_nm2'],
        'temperature': float(temperature),
        'temperature_source': plan.get('temperature_source'),
        'production_ps': float(production_ps),
        'equilibration_ps': float(equilibration_ps),
        'output_interval_ps': float(output_interval_ps),
        'restraint': {'mechanism': 'pull, flat-bottom, direction z',
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
PROFILES = ('standard',)
#: **One stage, deliberately.** The paper's 500 ns is one mdrun, and splitting minimization, equilibration and
#: production into separate stages would copy the placed system between them -- which is exactly why
#: `cg_simulation.sh` runs its three mdrun calls inside a single stage too. The plan said seven stages before this
#: script existed; this is the table the script actually has.
STAGE_DEFS = (
    Stage('Osmotic condition', '01_simulate/run.sh', ('inputs/',),
          ('prod/md_whole.xtc', 'built.json', 'system.top')),
)
STAGES, REQUIRED_INPUTS, REQUIRED_OUTPUTS = stage_tables(STAGE_DEFS)

#: The temperature default is maltose's, from Ebrahimi & Sadeghi 2016, and is a *default* here only because a run type
#: must start somewhere. The route that queues a series is expected to set it from the dataset it compares against, and
#: the report records where it came from either way.
DEFAULTS = dict(temperature_k=308.15,
                osmotic_production_ps=osmotic_mdp.DEFAULT_PRODUCTION_PS,
                osmotic_equilibration_ps=osmotic_mdp.DEFAULT_EQUILIBRATION_PS,
                osmotic_output_interval_ps=osmotic_mdp.DEFAULT_OUTPUT_INTERVAL_PS,
                osmotic_molality=1.0, mdrun_ntomp=8, mdrun_ranks=1)
SETTING_SPECS = {
    'temperature_k': ('Temperature of the experimental dataset', 200, 400),
    'osmotic_production_ps': ('Production duration', 1, 2000000),
    'osmotic_equilibration_ps': ('Equilibration duration', 1, 100000),
    'osmotic_output_interval_ps': ('Trajectory output interval', 0.002, 10000),
    'osmotic_molality': ('Molality', 0.0, 2.5),
    'mdrun_ntomp': ('mdrun OpenMP threads per rank', 1, 72),
    'mdrun_ranks': ('mdrun MPI ranks', 1, 72),
}
#: The files one molecule's solver needs, in `solute_root`. Named rather than discovered, so a missing one is a
#: blocker with its name in it instead of a failure halfway through a build.
SOLUTE_FILES = ('solute.gro', 'solute.itp', 'water.gro')


def stage_defaults(profile='standard'):
    if profile not in PROFILES:
        raise ValueError(f'unknown osmotic profile: {profile}')
    return {'values': dict(DEFAULTS), 'sources': {'osmotic': VERSION}, 'profile': VERSION}


def normalize_settings(settings=None, profile='standard'):
    if settings is not None and not isinstance(settings, dict):
        raise ValueError('osmotic settings must be an object')
    result = dict(stage_defaults(profile)['values'])
    for key, value in (settings or {}).items():
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
    for key in ('mdrun_ntomp', 'mdrun_ranks'):
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


def readiness(metadata):
    """Whether a condition can be built, in the shared shape: every check stated, every blocker named."""
    checks, blockers = [], []
    molecule_id = metadata.get('molecule_id')
    if molecule_id:
        checks.append({'label': 'Molecule', 'path': str(molecule_id), 'ready': True,
                       'detail': 'The solute is taken from solute_root; this names the molecule the report will.'})
    else:
        blockers.append('molecule_id is required to check an osmotic run')

    solute_root = metadata.get('solute_root')
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
    (stage / 'inputs').mkdir(parents=True, exist_ok=True)
    shutil.copy2(SCRIPTS / 'osmotic_simulation.sh', stage / 'run.sh')
    for name in ('minimization.mdp', 'eq.mdp', 'md.mdp', 'reference.itp', 'osmotic_condition.json'):
        shutil.copy2(run_dir / 'inputs' / name, stage / 'inputs' / name)
    if record['solute_molecules'] == 0:
        # A zero-molality condition is a legitimate control and is stated as one rather than looking like a mistake.
        (run_dir / 'inputs' / 'control.json').write_text(
            json.dumps({'molality': 0.0,
                        'note': 'pure solvent: the osmotic pressure of this condition is zero by construction and it '
                                'exists to show the measurement floor rather than a value'},
                       indent=2, sort_keys=True) + '\n')
    protocol.write_prepared_manifest(
        run_dir, dict(metadata, run_type='osmotic', workflow_version=VERSION), tools=tool_metadata(),
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
)
