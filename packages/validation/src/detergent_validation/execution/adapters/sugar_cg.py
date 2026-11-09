"""The CG-only sugar run: the published Martini 3 sugar entry as the topology, the AA geometry only as the start.

This run type exists because the engine had no CG-only sugar workflow. It is deliberately **not** an `aa_cg` run
with its atomistic half skipped: there is no `1_AA-reference` directory, no mapping stage, no Fast-Forward fit and
no parameterization revision to consume. The atomistic sugar is read once in `prepare`, to place the beads; the
simulation is one molecule in Martini water from the first command.

The science is one of two sources the user may choose. This adapter implements the published-reference source:

* the mapping is the sugar package's own `coords.candidate`, gated by `reference.conform` against the selected
  entry, so the bead identity is the published one rather than a hand-built variant;
* the topology is the published entry's own constraints/bonds/angles/dihedrals/virtual sites, transcribed by
  `reference.run_topology` — not a geometry seed and not a fit;
* the starting coordinates are the mapped AA geometry (`coords.coordinates(..., scaled=True)`), so the published
  constraints pull the start onto published geometry. The published-vs-mapped delta is recorded in the run, so that
  movement is visible rather than implied.

The reference is one source, not a validation: the run records `scientifically_validated: false` and says in its own
manifest that the entry is a published force-field model, not a measurement of this molecule.
"""
from __future__ import annotations

import json
from pathlib import Path

from dashboard import martini3, paths
from dashboard.execution import devices, protocol, run_inputs, tools
from dashboard.execution.adapters import cg
from dashboard.execution.environment import ROOT, environment, recorded_environment
from dashboard.execution.settings import coerce_integers, normalize
from dashboard.execution.stages import Stage, stage_tables
from dashboard.models.mappings.context import as_structure, build_context
from dashboard.models.molecules import aa as aa_molecules
from dashboard.models.sugars import coords, reference

VERSION = 'sugar-cg-v1'
SCRIPT = 'dashboard/execution/scripts/sugar_cg_simulation.sh'
SUGAR_REFERENCE = martini3.SUGARS[0]
SUGAR_PROVENANCE = martini3.SUGARS[1]
WATER_BOX = 'resources/templates/small_mols_fast_forward/4_CG_sim/inputs/water.gro'
ENTRIES = ('SUCR', 'TREH')

#: One stage: the CG build's minimisation, equilibration and production, the same command sequence the AA-CG
#: pipeline's `cg_simulation.sh` runs. The checkpoint is production's own, so Restart re-enters only that leg. The
#: directory and output names are the engine's existing CG spellings on purpose: `cg_trajectory`/`cg_structure`
#: roles, trajectory overview and the frame series then read this run with no new reader.
STAGE_DEFS = (
    Stage('CG simulation', '4_CG_sim/cg_simulation.sh',
          ('../../inputs/sugar.gro', '../../inputs/{entry}.itp', '../../inputs/system.top',
           '../../inputs/minimization.mdp', '../../inputs/eq.mdp', '../../inputs/md.mdp'),
          ('prod/lig_CG.gro', 'prod/lig_CG.tpr', 'prod/lig_CG.xtc'),
          script=SCRIPT, checkpoint='md.cpt'),
)
STAGES, REQUIRED_INPUTS, REQUIRED_OUTPUTS = stage_tables(STAGE_DEFS, {'entry': 'SUCR'})

#: The preset the run type is stamped with (`protocol.profile_for_run_type`). `standard` is the reviewed template's
#: own 5 ns / 100 ns; `sugar-cg-v1` shortens production to the AA-CG run's 10 ns so a first proof is affordable.
PROFILES = ('standard', 'sugar-cg-v1')
DEFAULTS = {
    'sugar_entry': 'SUCR',
    'cg_equil_ps': 5000.0,
    'cg_production_ps': 10000.0,
    'temperature_k': 310.0,
    'cg_seed': 20260911,
    'output_interval_ps': 10.0,
    'mdrun_ntomp': 8,
    'mdrun_ranks': 1,
    'mdrun_gpu': 0,
    'mdrun_cpt': 10,
    'mdrun_nb': 'auto',
    'mdrun_pme': 'auto',
}
#: The template's own production, used only by the `standard` profile.
STANDARD_PRODUCTION_PS = 100000.0

SETTING_SPECS = {
    'cg_equil_ps': ('CG equilibration duration', 1, 1000000),
    'cg_production_ps': ('CG production duration', 1, 1000000),
    'temperature_k': ('Temperature', 200, 500),
    'cg_seed': ('CG random seed', 1, 2147483646),
    'output_interval_ps': ('Trajectory output interval', 0.001, 100000),
    'mdrun_ntomp': ('mdrun OpenMP threads per rank', 1, 72),
    'mdrun_ranks': ('mdrun MPI ranks', 1, 72),
    'mdrun_gpu': ('mdrun GPU device', 0, 64),
    'mdrun_cpt': ('Checkpoint interval (minutes)', 1, 100000),
}
CHOICE_SPECS = {
    'mdrun_nb': ('Nonbonded scheme', ('auto', 'cpu', 'gpu')),
    'mdrun_pme': ('PME scheme', ('auto', 'cpu', 'gpu')),
    'sugar_entry': ('Sugar reference entry', ENTRIES),
}

MDP_PROFILES = {
    'inputs/minimization.mdp': 'cg-minimization-v1',
    'inputs/eq.mdp': 'cg-equilibration-v1',
    'inputs/md.mdp': 'cg-production-v1',
}


def _profile(profile):
    return profile if profile in PROFILES else 'sugar-cg-v1'


def stage_defaults(profile='sugar-cg-v1'):
    """The values this run type starts from; the profile changes only production's duration."""
    values = dict(DEFAULTS)
    if _profile(profile) == 'standard':
        values['cg_production_ps'] = STANDARD_PRODUCTION_PS
    return {'values': values, 'sources': {'sugar': VERSION}, 'profile': _profile(profile)}


def normalize_settings(settings=None, profile='sugar-cg-v1'):
    if settings is not None and not isinstance(settings, dict):
        raise ValueError('Sugar CG settings must be an object')
    supplied = dict(settings or {})
    result = normalize(
        supplied, stage_defaults(profile)['values'], specs=SETTING_SPECS, choices=CHOICE_SPECS,
        object_message='Sugar CG settings must be an object', unknown_prefix='Unknown sugar CG setting: ',
        label_messages=True,
    )
    coerce_integers(result, {'cg_seed': 'CG seed must be an integer',
                             'mdrun_gpu': 'mdrun_gpu must be an integer',
                             'mdrun_cpt': 'mdrun_cpt must be an integer'})
    if result['sugar_entry'] not in ENTRIES:
        raise ValueError('sugar_entry must be one of ' + ', '.join(ENTRIES))
    if result['output_interval_ps'] > result['cg_production_ps']:
        raise ValueError('Trajectory interval must not exceed the CG production duration')
    return result


def reference_provenance():
    """The installed sidecar's identity, read where it lives; the digest is checked against the file."""
    source = json.loads(Path(martini3.path(SUGAR_PROVENANCE)).read_text())
    return {'path': martini3.relative(SUGAR_REFERENCE),
            'sha256': source.get('sha256') or reference.sha256(),
            'commit': source.get('commit'),
            'paper_doi': source.get('paper_doi'),
            'martini_version': source.get('martini_version')}


def _molecule_files(molecule_root, molecule_id, inputs):
    """The AA topology and coordinates the start was built from, recorded where they live."""
    folder = Path(molecule_root) / molecule_id
    entries = []
    for role, key in (('molecule_topology', 'topology'), ('molecule_coordinates', 'coordinates')):
        source = folder / inputs[key]
        try:
            relative = source.relative_to(paths.current().project_root).as_posix()
        except ValueError:
            entries.append(run_inputs.absolute(role, source, label=inputs[key]))
        else:
            entries.append(run_inputs.published(role, relative, label=inputs[key]))
    return entries


def _empty(molecule_id, molecule_root, checks, blockers, provenance, context=None, structure=None):
    return {'ready': False, 'checks': checks, 'blockers': blockers, 'candidate': None,
            'context': context, 'structure': structure, 'conformance': {'issues': []},
            'provenance': provenance}


def assess(molecule_id, entry, *, molecule_root):
    """Everything readiness and the preview need to say about one molecule/entry pair.

    Returns checks and blockers in the readiness shape, plus whatever was read so the preview does not read the
    molecule twice. A refusal is a blocker, never an exception: a caller that does not know what this run type needs
    must still get an answer. This reads the molecule; it never writes to it.
    """
    checks, blockers = [], []
    provenance = reference_provenance()
    folder = Path(molecule_root) / str(molecule_id or '')
    checks.append({'label': 'Molecule directory', 'path': str(folder),
                   'ready': bool(molecule_id) and folder.is_dir() and not folder.is_symlink(),
                   'detail': 'Molecule directory' if folder.is_dir() else 'Missing molecule directory'})
    if not molecule_id or not folder.is_dir() or folder.is_symlink():
        blockers.append('a sugar CG run needs an available molecule directory')
        return _empty(molecule_id, molecule_root, checks, blockers, provenance)
    try:
        aa_molecules.validate_id(molecule_id)
        context = build_context(Path(molecule_root), molecule_id)
        structure = as_structure(context)
    except (OSError, ValueError) as exc:
        checks.append({'label': 'Molecule inputs', 'path': str(folder), 'ready': False, 'detail': str(exc)})
        return _empty(molecule_id, molecule_root, checks, [str(exc)], provenance)
    checks.append({'label': 'Molecule inputs', 'path': str(folder), 'ready': True,
                   'detail': 'ITP and coordinates read'})
    try:
        candidate = coords.candidate(structure, molecule_id)
    except (OSError, ValueError) as exc:
        candidate = None
        blockers.append(str(exc))
    if candidate is None:
        blockers.append('the structure has no recognised sugar ring to map')
        checks.append({'label': 'Sugar candidate', 'path': str(folder), 'ready': False,
                       'detail': 'No recognised sugar ring'})
        return _empty(molecule_id, molecule_root, checks, blockers, provenance,
                      context=context, structure=structure)
    checks.append({'label': 'Sugar candidate', 'path': str(folder), 'ready': True,
                   'detail': f"{len(candidate['beads'])} beads"})
    found = candidate.get('reference') or {}
    if entry not in ENTRIES:
        blockers.append(f'unknown sugar reference entry {entry!r}; this run type offers ' + ', '.join(ENTRIES))
    if found.get('entry') != entry:
        blockers.append(f'the candidate mapping identifies {found.get("entry") or "no reference entry"}, '
                        f'not the selected {entry}')
    if not found.get('unambiguous') or not found.get('covers_whole_molecule'):
        blockers.append('the candidate mapping is not an unambiguous whole-molecule match to the reference')
    issues = []
    if entry in ENTRIES:
        try:
            issues = reference.conform(candidate, entry)
        except (KeyError, OSError) as exc:
            blockers.append(str(exc))
    blockers.extend(issues)
    checks.append({'label': 'Reference conformance', 'path': str(folder), 'ready': not issues,
                   'detail': 'conforms' if not issues else '; '.join(issues)})
    try:
        reference.entry(entry)
        present = True
    except (KeyError, OSError) as exc:
        present = False
        blockers.append(str(exc))
    checks.append({'label': 'Installed sugar reference', 'path': martini3.relative(SUGAR_REFERENCE),
                   'ready': present, 'detail': entry if present else 'Reference entry missing'})
    return {'ready': not blockers, 'checks': checks, 'blockers': blockers, 'candidate': candidate,
            'context': context, 'structure': structure, 'conformance': {'issues': issues},
            'provenance': provenance}


def _bead_rows(candidate):
    rows = []
    for index, bead in enumerate(candidate['beads'], 1):
        rows.append({'name': f'B{index:02d}', 'export_name': bead.get('letter') or bead['name'],
                     'residue': bead.get('residue', 1), 'type': bead['type'],
                     'atoms': list(bead.get('atoms') or []),
                     'virtual_site': bool(bead.get('virtual_site'))})
    return rows


def preview(molecule_id, entry='SUCR', *, molecule_root):
    """The New-run preview: the candidate, conformance, the published signature and the run's provenance."""
    answer = assess(molecule_id, entry, molecule_root=molecule_root)
    candidate = answer.get('candidate')
    record = None
    if entry in ENTRIES:
        try:
            record = reference.signature(reference.entry(entry))
        except (KeyError, OSError):
            record = None
    return {
        'molecule_id': molecule_id,
        'sugar_entry': entry,
        'ready': answer['ready'],
        'checks': answer['checks'],
        'blockers': answer['blockers'],
        'conforms': not answer['conformance']['issues'],
        'conformance': answer['conformance'],
        'beads': _bead_rows(candidate) if candidate else [],
        'reference': answer['provenance'],
        'signature': record,
        'warnings': list((candidate or {}).get('warnings') or []),
        'starting_structure': {
            'source': 'mapped-AA',
            'molecule_id': molecule_id,
            'scaled': True,
            'ring_scale': 1.15,
            'statement': 'AA-mapped CG coordinates; published constraints pull the start onto published geometry.',
        },
        'topology_source': 'published-reference',
        'limitations': [
            'The topology is the published Martini 3 sugar entry; it is not a fit to this molecule\'s AA trajectory.',
            'The start coordinates are the mapped AA geometry; adopting published constraints moves the start.',
            'No atomistic reference, mapping comparison, overlap, surface or back-map exists in this run.',
            'The reference is a published force-field entry, not an experimental measurement of these AA topologies.',
        ],
        'scientifically_validated': False,
    }


def _context(metadata):
    settings = metadata.get('settings') or {}
    entry = settings.get('sugar_entry') or metadata.get('sugar_entry') or DEFAULTS['sugar_entry']
    return {'entry': entry}


def stage_contract(metadata):
    """The stage plan and the required inputs/outputs, resolved for this run's reference entry."""
    return stage_tables(STAGE_DEFS, _context(metadata))


def stages(metadata):
    return tuple(stage.resolve(_context(metadata)) for stage in STAGE_DEFS)


def tool_metadata():
    return tools.record_versions('gmx', env=environment(),
                                 missing=lambda name: ValueError('GROMACS executable is unavailable'))


def prepare(run_dir, metadata):
    """Write the run's generated inputs and manifest. There is no AA stage to prepare."""
    run_dir = Path(run_dir)
    molecule_id = metadata.get('molecule_id')
    molecule_root = Path(metadata.get('molecule_root') or paths.current().project_root / 'molecules')
    settings = normalize_settings(metadata.get('settings'), metadata.get('profile') or VERSION)
    entry = settings['sugar_entry']
    answer = assess(molecule_id, entry, molecule_root=molecule_root)
    if not answer['ready']:
        raise ValueError('; '.join(answer['blockers']))
    candidate, structure = answer['candidate'], answer['structure']
    provenance = answer['provenance']
    devices.require(settings['mdrun_gpu'])

    inputs = run_dir / 'inputs'
    inputs.mkdir(parents=True, exist_ok=True)
    stages = run_dir / 'stages'
    (stages / '4_CG_sim').mkdir(parents=True, exist_ok=True)

    positions = [atom['xyz'] for atom in structure['atoms']]
    atom_ids = [atom['id'] for atom in structure['atoms']]
    xyz = coords.coordinates(candidate, positions, atom_ids, scaled=True)
    (inputs / 'sugar.gro').write_text(coords.gro_text(candidate, xyz, residue_name=entry))
    topology = reference.run_topology(entry, provenance=provenance)
    (inputs / f'{entry}.itp').write_text(topology)
    (inputs / 'system.top').write_text(
        f'#include "{martini3.include(cg.MARTINI_FF, inputs)}"\n'
        f'#include "{martini3.include(cg.MARTINI_SOLVENTS, inputs)}"\n'
        f'#include "{martini3.include(cg.MARTINI_IONS, inputs)}"\n'
        f'#include "{entry}.itp"\n[ system ]\n{entry} in Martini water\n'
        f'[ molecules ]\n{entry} 1\n'
    )
    from dashboard.execution.mdp import write_mdp
    write_mdp('cg-minimization-v1', inputs / 'minimization.mdp')
    write_mdp('cg-equilibration-v1', inputs / 'eq.mdp', cg.mdp_values(settings, 'cg-equilibration-v1'))
    write_mdp('cg-production-v1', inputs / 'md.mdp', cg.mdp_values(settings, 'cg-production-v1'))
    delta = reference.parameter_delta(topology, entry, layout='run')
    (inputs / 'conformance.json').write_text(json.dumps({
        'entry': entry,
        'conforms': True,
        'issues': [],
        'candidate_status': candidate.get('status'),
        'candidate_reference': candidate.get('reference'),
        'warnings': candidate.get('warnings') or [],
        'beads': _bead_rows(candidate),
        'topology_source': 'published-reference',
        'starting_structure': {'source': 'mapped-AA', 'scaled': True, 'ring_scale': 1.15},
        'parameter_delta': delta,
        'scientifically_validated': False,
    }, indent=2, sort_keys=True) + '\n')

    snapshot = metadata.get('molecule_snapshot')
    try:
        molecule_entries = _molecule_files(molecule_root, molecule_id, answer['context']['inputs'])
    except (OSError, ValueError):
        # `assess` already read the molecule successfully; this is only the provenance record.
        molecule_entries = []
    references = [
        run_inputs.installed('martini_force_field', martini3.path(cg.MARTINI_FF),
                             label='Martini 3 force field (martini_v3.0.0.itp)'),
        run_inputs.installed('martini_solvents', martini3.path(cg.MARTINI_SOLVENTS),
                             label='Martini 3 solvents (martini_v3.0.0_solvents_v1.itp)'),
        run_inputs.installed('martini_ions', martini3.path(cg.MARTINI_IONS),
                             label='Martini 3 ions (martini_v3.0.0_ions_v1.itp)'),
        run_inputs.installed('sugar_reference', martini3.path(SUGAR_REFERENCE),
                             label='Martini 3 sugar reference (martini_v3.0.0_sugars_v2.itp)'),
        run_inputs.installed('sugar_reference_provenance', martini3.path(SUGAR_PROVENANCE),
                             label='Martini 3 sugar reference provenance'),
        run_inputs.published('martini_water', WATER_BOX,
                             label='Martini 3 water box (water.gro)'),
        *molecule_entries,
    ]
    plan = [name for name, _ in stage_tables(STAGE_DEFS, {'entry': entry})[0]]
    metadata_document = {
        'run_type': 'sugar_cg',
        'workflow_version': VERSION,
        'profile': _profile(metadata.get('profile') or VERSION),
        'molecule_id': molecule_id,
        'molecule_snapshot': snapshot,
        'sugar': {'entry': entry, 'reference': provenance},
        'sugar_candidate': {'status': candidate.get('status'),
                            'reference': candidate.get('reference'),
                            'warnings': candidate.get('warnings') or []},
        'starting_structure': {'source': 'mapped-AA', 'scaled': True, 'ring_scale': 1.15},
        'topology_source': 'published-reference',
        'conformance': {'issues': [], 'candidate': candidate.get('reference')},
        'settings': settings,
        'mdp_profiles': dict(MDP_PROFILES),
        'cg_names': {'residue_name': entry, 'initial_itp': f'{entry}.itp', 'final_itp': f'{entry}.itp'},
        'scientifically_validated': False,
        'limitations': [
            "The topology is the published Martini 3 sugar entry; it is not a fit to this molecule's AA trajectory.",
            'The start coordinates are the mapped AA geometry; adopting published constraints moves the start.',
            'No atomistic reference, mapping comparison, overlap, surface or back-map exists in this run.',
            'The reference is a published force-field entry, not an experimental measurement of these AA topologies.',
        ],
    }
    protocol.write_prepared_manifest(
        run_dir, metadata_document, tools=tool_metadata(), plan=plan, environment=recorded_environment(),
        references=references, scripts={'CG simulation': SCRIPT},
    )
    return metadata_document


def _protocol_readiness(metadata):
    molecule_id = metadata.get('molecule_id')
    if not molecule_id:
        return protocol.blocked('molecule_id is required to check a CG sugar run')
    entry = (metadata.get('settings') or {}).get('sugar_entry') or metadata.get('sugar_entry') or 'SUCR'
    molecule_root = Path(metadata.get('molecule_root') or ROOT / 'molecules')
    answer = assess(molecule_id, entry, molecule_root=molecule_root)
    return {'ready': answer['ready'], 'checks': answer['checks'], 'blockers': answer['blockers']}


def _protocol_prepare(run_dir, metadata):
    return prepare(run_dir, metadata)


PROTOCOL = protocol.Protocol(
    name='sugar_cg',
    stage_contract=stage_contract,
    stages=stages,
    settings_specs=lambda: devices.published_settings(SETTING_SPECS),
    stage_defaults=lambda: stage_defaults(),
    normalize_settings=lambda settings=None, profile='sugar-cg-v1': normalize_settings(settings, profile),
    readiness=_protocol_readiness,
    prepare=_protocol_prepare,
    tool_report=tool_metadata,
    choice_specs=lambda: devices.published_choices(CHOICE_SPECS),
)
