"""The CG run over an immutable composition: a real GROMACS simulation of the composed molecule.

A composition run is not an AA-to-CG run with its atomistic half skipped, and it is no longer a screening stub: it
builds one coarse-grained system from the composition's own immutable topology and coordinates and runs the CG
build's minimisation, equilibration and production. There is no AA reference stage, no mapping stage and no
parameterization fit; the model the run consumes is the composition's **derived** parameterization, and the run says
so in its manifest.

The stage plan is two stages:

* ``CG simulation`` -- the repository's ``cg_simulation.sh``, the same command sequence the AA-to-CG CG half and the
  sugar CG run execute. This adapter writes what that script reads: the composition's geometry as
  ``2_mapping/mapped.gro``, its topology as ``3_initial_CG/<residue>.itp``, a Martini 3 system that includes it, and
  the reviewed CG MDPs at the run's own numbers.
* ``CG assessment`` -- records ``skipped`` (exit 4 plus ``skip.json``). A composition has no atomistic reference
  trajectory, so there is no AA reference distribution to score the CG trajectory against; the stage says that
  rather than printing a score of 0.00 that would read like a measurement.

SASA is not offered for the same reason: the engine's SASA analysis compares an AA surface with a CG surface, and
this run has no AA half. The stage plan omits it rather than recording a second skip for one absent reference.
"""
from __future__ import annotations

from pathlib import Path

from ... import martini3, paths
from ...models import compositions
from ...models.compositions import parameterizations as composition_parameterizations
from .. import devices, protocol, run_inputs, tools
from ..environment import ROOT, environment, recorded_environment
from ..mdp import write_mdp
from ..settings import normalize
from ..stages import Stage, stage_tables
from . import aa as aa_adapter
from . import cg

VERSION = 'cg-composition-v2'
SIMULATION_SCRIPT = 'dashboard/execution/scripts/cg_simulation.sh'
ASSESSMENT_SCRIPT = 'dashboard/execution/scripts/composition_assessment.sh'

#: The artifact names a composition run reads. `compositions.artifacts` is the reader; this is the declared vocabulary
#: the stage contract and the readiness checks name.
ARTIFACTS = compositions.ARTIFACTS

#: What a composition does not have, said in the run's own words rather than left to be inferred from an absent file.
NO_REFERENCE = 'no AA reference distribution to score against'

#: One stage runs the CG build; the second states that there is nothing to score. Inputs are spelled relative to each
#: stage's own directory, the way `cg_simulation.sh` opens them.
STAGE_DEFS = (
    Stage('CG simulation', '4_CG_sim/cg_simulation.sh',
          ('../2_mapping/mapped.gro', '../3_initial_CG/{itp}', 'system_EMPTY.top',
           'inputs/minimization.mdp', 'inputs/eq.mdp', 'inputs/md.mdp'),
          ('prod/lig_CG.gro', 'prod/lig_CG.tpr', 'prod/lig_CG.xtc'),
          script=SIMULATION_SCRIPT, checkpoint='md.cpt'),
    # The assessment stage skips before it reads anything, so it declares no input and no output of its own: the
    # one file it writes is `skip.json`, and the executor records the stage `skipped` from the exit code.
    Stage('CG assessment', '5_assessment/assess.sh', (), (), script=ASSESSMENT_SCRIPT),
)
STAGES, REQUIRED_INPUTS, REQUIRED_OUTPUTS = stage_tables(STAGE_DEFS, {'itp': 'composition.itp'})

#: The reviewed MDP profiles this run writes, keyed by their path relative to `stages/` -- the spelling the executor's
#: `mdp_profiles` record uses. The three are the CG half's own, read from `cg` rather than restated.
MDP_PROFILES = {key: value for key, value in cg.MDP_PROFILES.items() if key.startswith('4_CG_sim/')}

#: The composition has no AA half, so it owns cg's CG numbers and the execution keys its scripts read -- not the AA
#: durations `cg.normalize_settings` derives the CG equilibration from for an AA-to-CG run.
AA_HALF = ('aa_equil_ps', 'aa_production_ps', 'sasa_probe_nm')
SETTING_SPECS = {key: spec for key, spec in cg.SETTING_SPECS.items() if key not in AA_HALF}
SETTING_SPECS.update({key: aa_adapter.SETTING_SPECS[key] for key in cg.RUN_EXECUTION_SETTINGS})
CHOICE_SPECS = {key: aa_adapter.CHOICE_SPECS[key]
                for key in ('mdrun_nb', 'mdrun_pme', 'mdrun_pmefft', 'mdrun_update', 'mdrun_tunepme')}
_INTEGRALS = {'cg_seed': 'CG random seed must be an integer', 'mdrun_gpu': 'mdrun_gpu must be an integer',
              'mdrun_cpt': 'mdrun_cpt must be an integer', 'nstlog': 'nstlog must be an integer',
              'nstenergy': 'nstenergy must be an integer', 'nstxtcout': 'nstxtcout must be an integer',
              'nstcomm': 'nstcomm must be an integer', 'nstlist': 'nstlist must be an integer'}


def _profile(profile):
    return profile or 'standard'


def stage_defaults(profile='standard'):
    """The values a composition run starts from: the CG profile's own numbers plus the execution defaults.

    Read from `cg.stage_defaults` rather than restated, so a review that moves a duration moves the form and the run
    together. The AA durations that function also carries are dropped: this run has no atomistic half.
    """
    values = cg.stage_defaults(_profile(profile))['values']
    result = {key: values[key] for key in SETTING_SPECS if key in values}
    result.update({key: aa_adapter.DEFAULTS[key] for key in cg.RUN_EXECUTION_SETTINGS})
    result.update({key: aa_adapter.DEFAULTS[key] for key in CHOICE_SPECS if key in aa_adapter.DEFAULTS})
    return {'values': result, 'sources': {'CG': 'cg.stage_defaults', 'composition': VERSION},
            'profile': _profile(profile)}


def normalize_settings(settings=None, profile='standard'):
    """Normalize the run's numbers in the CG-only dialect, at the profile the run is stamped with."""
    if settings is not None and not isinstance(settings, dict):
        raise ValueError('Composition CG settings must be an object')
    values = normalize(
        settings, stage_defaults(_profile(profile))['values'], specs=SETTING_SPECS, choices=CHOICE_SPECS,
        object_message='Composition CG settings must be an object',
        unknown_prefix='Unknown composition CG setting: ', label_messages=True, integrals=_INTEGRALS)
    if values['output_interval_ps'] > values['cg_production_ps']:
        raise ValueError('Trajectory interval must not exceed the CG production duration')
    return values


def _composition_id(metadata):
    payload = metadata.get('parameterization') if isinstance(metadata, dict) else None
    return (payload.get('composition_id') if isinstance(payload, dict) else None) \
        or (metadata.get('composition_id') if isinstance(metadata, dict) else None)


def _record(metadata):
    composition_id = _composition_id(metadata)
    if not composition_id:
        raise ValueError('composition_id is required to check a composition run')
    return compositions.get(composition_id)


def _revision(metadata):
    """The composition revision the payload names, or None for "the current one".

    A run that names no revision consumes the record's current revision (revision 0, the derived model, when no
    edit has been saved); a run that names one gets exactly that revision. The value is checked here, at the
    adapter boundary, so a route and a direct caller cannot disagree about what a legal revision is.
    """
    payload = metadata.get('parameterization') if isinstance(metadata, dict) else None
    value = payload.get('composition_revision') if isinstance(payload, dict) else None
    if value is None and isinstance(metadata, dict):
        value = metadata.get('composition_revision')
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError('composition_revision must be a non-negative integer')
    return value


def _context(metadata):
    """The placeholders the stage contract resolves with: the topology file the run will write."""
    names = metadata.get('cg_names') if isinstance(metadata, dict) else None
    if not isinstance(names, dict):
        try:
            names = compositions.names(_record(metadata))
        except (OSError, ValueError, KeyError, FileNotFoundError):
            names = None
    return {'itp': (names or {}).get('final_itp') or 'composition.itp'}


def stage_contract(metadata):
    """The stage plan and its declared inputs/outputs, resolved for the composition's residue name."""
    return stage_tables(STAGE_DEFS, _context(metadata))


def stages(metadata):
    return tuple(stage.resolve(_context(metadata)) for stage in STAGE_DEFS)


def readiness(composition_id, molecule_id=None, revision=None):
    """Can this composition run start? Its artifacts, the named revision, the molecule binding and GROMACS.

    A refusal is a blocker, never an exception: a caller that does not know what this run type needs must still get
    an answer. Nothing here writes to the store.
    """
    checks, blockers = [], []
    try:
        record = compositions.get(composition_id)
        root = compositions.artifact_root(record)
        bound = compositions.molecule_id(record)
        artifacts = compositions.artifacts(record)
        parameterization = composition_parameterizations.revision(composition_id, revision)
    except (OSError, ValueError, KeyError, FileNotFoundError) as exc:
        return {'ready': False, 'checks': [], 'blockers': [str(exc)]}
    for name in ARTIFACTS:
        checks.append({'label': name, 'path': str(artifacts[name]), 'ready': True,
                       'detail': 'Immutable composition artifact'})
    checks.append({'label': f"parameterization revision {parameterization['revision']}",
                   'path': f"composition_revision={parameterization['revision']}",
                   'ready': True,
                   'detail': ('Derived from the recipe and the head reference'
                              if parameterization['revision'] == 0
                              else f"Edited terms seeded from {parameterization.get('base_sha256', '')[:12]}")})
    if molecule_id and bound != molecule_id:
        blockers.append(f'This composition belongs to {bound}, not {molecule_id}')
        checks.append({'label': 'Molecule binding', 'path': str(root), 'ready': False,
                       'detail': f'bound to {bound}'})
    executable = tools.tool_path('gmx')
    checks.append({'label': 'gmx', 'path': executable or 'gmx', 'ready': bool(executable),
                   'detail': 'GROMACS executable resolved' if executable else 'Executable not found'})
    if not executable:
        blockers.append('gmx: Executable not found')
    return {'ready': not blockers, 'checks': checks, 'blockers': blockers}


def tool_metadata():
    """The tools a composition run executes: GROMACS, and nothing else."""
    return tools.record_versions('gmx', env=environment(),
                                 missing=lambda name: ValueError('GROMACS executable is unavailable'))


def _artifact_entries(record, names):
    """The immutable artifacts named in place, by workspace-relative path where the store is inside it."""
    workspace = paths.current().workspace.resolve()
    entries = []
    for name in ARTIFACTS:
        source = names[name]
        try:
            relative = source.relative_to(workspace).as_posix()
        except ValueError:
            entries.append(run_inputs.absolute('composition_artifact', source, label=name))
        else:
            entries.append(run_inputs.store('composition_artifact', relative, label=name,
                                            workspace_root=workspace))
    return entries


def prepare(run_dir, metadata):
    """Write the CG build's inputs and the run's manifest. There is no AA stage and no mapping stage to prepare."""
    run_dir = Path(run_dir)
    composition_id = _composition_id(metadata)
    record = _record(metadata)
    names = compositions.names(record)
    bound = compositions.molecule_id(record)
    selected = metadata.get('molecule_id')
    if selected and selected != bound:
        raise ValueError(f'This composition belongs to {bound}, not {selected}')
    settings = normalize_settings(metadata.get('settings'), metadata.get('profile'))
    devices.require(settings['mdrun_gpu'])
    artifacts = compositions.artifacts(record)

    stages = run_dir / 'stages'
    mapping = stages / '2_mapping'
    initial = stages / '3_initial_CG'
    sim = stages / '4_CG_sim'
    for directory in (mapping, initial, sim / 'inputs', stages / '5_assessment'):
        directory.mkdir(parents=True, exist_ok=True)
    # The composition's own geometry, and the topology of the revision this run consumes: revision 0 is the
    # immutable derived `.itp`, a saved edit is the revision's own text seeded from it. The copies are the run's
    # generated data; the store stays the immutable original the input record names.
    (mapping / 'mapped.gro').write_bytes(artifacts['composition.gro'].read_bytes())
    item = composition_parameterizations.revision(composition_id, _revision(metadata))
    if item['revision'] == 0:
        (initial / names['final_itp']).write_bytes(artifacts['composition.itp'].read_bytes())
    else:
        (initial / names['final_itp']).write_text(item['topology'])
    (sim / 'system_EMPTY.top').write_text(
        f'#include "{martini3.include(cg.MARTINI_FF, sim)}"\n'
        f'#include "{martini3.include(cg.MARTINI_SOLVENTS, sim)}"\n'
        f'#include "{names["final_itp"]}"\n'
        f'[ system ]\n{names["residue_name"]} composition in Martini water\n'
        f'[ molecules ]\n{names["residue_name"]} 1\n')
    write_mdp('cg-minimization-v1', sim / 'inputs/minimization.mdp')
    write_mdp('cg-equilibration-v1', sim / 'inputs/eq.mdp', cg.mdp_values(settings, 'cg-equilibration-v1'))
    write_mdp('cg-production-v1', sim / 'inputs/md.mdp', cg.mdp_values(settings, 'cg-production-v1'))

    references = [
        run_inputs.installed('martini_force_field', martini3.path(cg.MARTINI_FF),
                             label='Martini 3 force field (martini_v3.0.0.itp)'),
        run_inputs.installed('martini_solvents', martini3.path(cg.MARTINI_SOLVENTS),
                             label='Martini 3 solvents (martini_v3.0.0_solvents_v1.itp)'),
        run_inputs.published('martini_water', cg.WATER_BOX.relative_to(ROOT),
                             label='Martini 3 water box (water.gro)'),
        *_artifact_entries(record, artifacts),
    ]
    profile = _profile(metadata.get('profile'))
    head = record.get('head_molecule_id')
    # The provenance copy: which revision the run consumed, what it was seeded from, and the digest of the topology
    # the run actually stages. A reader can prove the run simulated the edited terms and not revision 0.
    parameterization = {'kind': 'composition', 'composition_id': composition_id,
                        'composition_revision': item['revision'],
                        'base': 'derived' if item['revision'] == 0 else 'derived-revision-0',
                        'base_sha256': item.get('base_sha256') or item['topology_sha256'],
                        'topology_sha256': item['topology_sha256'],
                        'molecule_id': bound, 'head_molecule_id': head}
    document = {
        'run_type': 'cg', 'workflow_version': VERSION, 'profile': profile,
        'execution_kind': 'cg-simulation',
        'composition_id': composition_id,
        'composition_snapshot_sha256': record.get('snapshot_hash'),
        'composition_identity': record.get('identity'),
        'molecule_id': bound,
        'molecule_name': compositions.molecule_name(record),
        'head_molecule_id': head,
        'status': record.get('status', 'candidate-unvalidated'),
        'parameterization': parameterization,
        'cg_names': names,
        'settings': settings,
        'mdp_profiles': dict(MDP_PROFILES),
        'scientifically_validated': False,
        'limitations': [
            "The parameterization is derived from the tail recipe and the head fragment's published Martini 3 "
            'reference terms; it is not fitted to an atomistic trajectory of this molecule.',
            'The starting coordinates are the composition\'s own generated geometry, not a mapped AA trajectory.',
            f'The CG assessment records skipped: {NO_REFERENCE}. No score and no SASA curve are produced.',
        ],
    }
    plan = [name for name, _ in STAGES]
    return protocol.finish_prepared_run(
        run_dir, stages, metadata=document, tools=tool_metadata(), plan=plan,
        environment=recorded_environment(), references=references,
        scripts={'CG simulation': SIMULATION_SCRIPT, 'CG assessment': ASSESSMENT_SCRIPT})


def _protocol_readiness(metadata):
    composition_id = _composition_id(metadata)
    if not composition_id:
        return protocol.blocked('composition_id is required to check a composition run')
    try:
        revision = _revision(metadata)
    except ValueError as exc:
        return protocol.blocked(str(exc))
    return readiness(composition_id, metadata.get('molecule_id'), revision)


def _protocol_prepare(run_dir, metadata):
    return prepare(run_dir, metadata)


PROTOCOL = protocol.Protocol(
    name='cg_composition',
    stage_contract=stage_contract,
    stages=stages,
    settings_specs=lambda: devices.published_settings(SETTING_SPECS),
    stage_defaults=lambda: stage_defaults(),
    normalize_settings=lambda settings=None, profile='standard': normalize_settings(settings, profile),
    readiness=_protocol_readiness,
    prepare=_protocol_prepare,
    tool_report=tool_metadata,
    choice_specs=lambda: devices.published_choices(CHOICE_SPECS),
)
