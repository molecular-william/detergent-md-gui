"""Generic coarse-grained workflow adapter, with packaged DDM defaults.

Stages, MDP rewrites and readiness are molecule-agnostic. When a molecule
snapshot is supplied, the CG residue name and topology filenames derive from
that snapshot via CGNames.for_snapshot and the AA stage is consumed from a
coordinator-attached shared reference. The packaged SwissParam source under
molecules/DDM is used only when a caller invokes the adapter without a
snapshot (historical smoke-test paths).
"""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from ... import files, paths
from ...models import bonded, mappings
from ...models.molecules import aa as aa_molecules
from ...models.molecules import draft as draft_model
from .. import protocol, tools
from ..environment import AA_TEMPLATE, FORCE_FIELD, ROOT, TUTORIAL_TEMPLATE, environment, probe_tool, recorded_environment, update_mdp
from ..stages import Stage, stage_tables
from . import aa
from .cg_names import CGNames

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
# What this module offers to the rest of the application: PROTOCOL (the run-type
# surface at the end of this file), stage_contract() for a naming context, and
# SCRIPTS for run preparation. The stage tables, settings bounds and tool report
# in between are read through those three; a name is not part of the interface
# merely because it is importable.

STAGE_DEFS = (
    Stage('AA reference', '1_AA-reference/aa_reference.sh',
          ('molecule.pdb', 'system_EMPTY.top', 'em.mdp', 'eq.mdp', 'run.mdp'),
          ('prod/lig.gro', 'prod/lig.tpr', 'prod/lig.xtc', '3-run.xtc')),
    Stage('trajectory mapping', '2_mapping/map_trajectory.sh',
          ('../1_AA-reference/prod/lig.xtc', '../1_AA-reference/prod/lig.tpr',
           '../1_AA-reference/prod/lig.gro', 'mapping.map'),
          ('mapped.xtc', 'mapped.gro', 'mapping_validation.json')),
    Stage('CG topology (ff_inter)', '3_initial_CG/fit_topology.sh',
          ('../2_mapping/mapped.xtc', '../2_mapping/mapped.gro', 'initial.mdp',
           'topol.top', '{initial_itp}'),
          ('mapped.tpr', '{final_itp}', '*_bonds_distr.dat',
           '*_angles_distr.dat', '*_distances_distr.dat')),
    Stage('CG simulation', '4_CG_sim/cg_simulation.sh',
          ('../2_mapping/mapped.gro', '../3_initial_CG/{final_itp}',
           'system_EMPTY.top', 'inputs/md.mdp'),
          ('prod/lig_CG.gro', 'prod/lig_CG.tpr', 'prod/lig_CG.xtc')),
    Stage('CG assessment (ff_assess)', '5_assessment/assess.sh',
          ('../4_CG_sim/prod/lig_CG.xtc', '../4_CG_sim/prod/lig_CG.tpr',
           '../4_CG_sim/prod/lig_CG.gro', '../3_initial_CG/{initial_itp}',
           '../3_initial_CG/*_bonds_distr.dat',
           '../3_initial_CG/*_distances_distr.dat'),
          ('report_interactions.out', 'report_distances.out', 'validation.json',
           'distance_diagnostics_stratified.json',
           'distance_matrix_stratified_{residue_name}.png')),
    Stage('SASA analysis', '6_SASA/sasa.sh',
          ('../1_AA-reference/prod/lig.xtc', '../4_CG_sim/prod/lig_CG.xtc',
           'AA/vdwradii.dat', 'CG/vdwradii.dat'),
          ('AA/SASA-AA.xvg', 'CG/SASA-CG.xvg')),
)

_DEFAULT_NAMES = CGNames.ddm_defaults()
STAGES, REQUIRED_INPUTS, REQUIRED_OUTPUTS = stage_tables(
    STAGE_DEFS, _DEFAULT_NAMES.env()
)


def stage_contract(names: CGNames | None = None):
    """Return the executable stage contract for one molecule naming context."""
    return stage_tables(STAGE_DEFS, (names or _DEFAULT_NAMES).env())


SETTING_SPECS = {
    'cg_seed': ('CG random seed', 1, 2147483646),
    'aa_equil_ps': ('AA equilibration duration', 1, 1000000),
    'aa_production_ps': ('AA production duration', 1, 1000000),
    'cg_equil_ps': ('CG equilibration duration', 1, 1000000),
    'cg_production_ps': ('CG production duration', 1, 1000000),
    'temperature_k': ('Temperature', 200, 500),
    'sasa_probe_nm': ('SASA probe radius', 0.05, 0.5),
    'output_interval_ps': ('Trajectory output interval', 0.001, 100000),
}


def _mdp_value(path, key):
    for line in path.read_text().splitlines():
        raw = line.split(';', 1)[0].strip()
        if '=' in raw and raw.split('=', 1)[0].strip().lower().replace('-', '_') == key.lower().replace('-', '_'):
            return float(raw.split('=', 1)[1].strip())
    raise ValueError(f'{path}: missing {key}')


def stage_defaults(profile='standard'):
    aa_eqf, aa_mdf = AA_TEMPLATE / 'mdps/eq.mdp', AA_TEMPLATE / 'mdps/md.mdp'
    cg_eqf, cg_mdf = TUTORIAL_TEMPLATE / '4_CG_sim/inputs/eq.mdp', TUTORIAL_TEMPLATE / '4_CG_sim/inputs/md.mdp'
    values = {'aa_equil_ps': _mdp_value(aa_eqf, 'nsteps') * _mdp_value(aa_eqf, 'dt'),
              'aa_production_ps': _mdp_value(aa_mdf, 'nsteps') * _mdp_value(aa_mdf, 'dt'),
              'cg_equil_ps': _mdp_value(cg_eqf, 'nsteps') * _mdp_value(cg_eqf, 'dt'),
              'cg_production_ps': _mdp_value(cg_mdf, 'nsteps') * _mdp_value(cg_mdf, 'dt'),
              'temperature_k': _mdp_value(aa_eqf, 'ref_t'), 'sasa_probe_nm': 0.191, 'output_interval_ps': 10.0, 'cg_seed': 20260911}
    if profile == 'draft-smoke': values.update(aa_equil_ps=10.0, aa_production_ps=50.0, cg_equil_ps=10.0, cg_production_ps=50.0)
    if profile == 'draft-smoke-reference': values.update(cg_equil_ps=10.0, cg_production_ps=10000.0)
    return {'values': values, 'sources': {'AA': 'resources/templates/small_mols_fast_forward/1_AA_reference/mdps/{eq,md}.mdp', 'CG': 'resources/templates/small_mols_fast_forward/4_CG_sim/inputs/{eq,md}.mdp', 'SASA probe': 'Fast_Forward tutorial probe convention (0.191 nm)'}, 'profile': profile}


def _normalize_cg_settings(settings=None, profile='standard'):
    if settings is not None and not isinstance(settings,dict): raise ValueError('Run settings must be an object')
    values = dict(stage_defaults(profile)['values'])
    for key, value in (settings or {}).items():
        if key not in SETTING_SPECS: raise ValueError(f'Unknown run setting: {key}')
        try: number = float(value)
        except (TypeError, ValueError) as exc: raise ValueError(f'{SETTING_SPECS[key][0]} must be numeric') from exc
        if not SETTING_SPECS[key][1] <= number <= SETTING_SPECS[key][2]: raise ValueError(f'{SETTING_SPECS[key][0]} must be between {SETTING_SPECS[key][1]} and {SETTING_SPECS[key][2]}')
        values[key] = number
    if int(values['cg_seed']) != values['cg_seed']: raise ValueError('CG random seed must be an integer')
    values['cg_seed'] = int(values['cg_seed'])
    if values['output_interval_ps'] > min(values['aa_production_ps'], values['cg_production_ps']):
        raise ValueError('Trajectory interval must not exceed either production duration')
    return values


def mirror_aa_settings(aa_settings):
    """The AA view a CG run needs, derived from the AA settings it was given."""
    return {'aa_equil_ps': aa_settings['aa_nvt_ps'] + aa_settings['aa_npt_ps'],
            'aa_production_ps': aa_settings['aa_production_ps'],
            'temperature_k': aa_settings['temperature_k'],
            'output_interval_ps': aa_settings['output_interval_ps']}


def mdp_integration(folder, aa_dir, steps):
    """The per-file MDP changes for one half of the run, as one place that decides the timestep.

    The atomistic half integrates at 2 fs, which is its template's own dt. The coarse-grained half keeps
    Martini's timestep from *its* template: stamping the atomistic dt on both is what made a 10 ns
    coarse-grained production 5,000,000 steps — ten times the work for the same trajectory — and left the run's
    own record reading as an atomistic timestep (measured on run `abd5bf461c49`: 2863 ns/day, 0.060 ms/step).

    What this does **not** decide is the pressure coupling. It used to stamp `pcoupl = no` over both halves,
    and the CG templates ask for C-rescale while equilibrating and Parrinello-Rahman at 1 bar in production —
    the protocol both the Martini 3 paper and the carbohydrate paper describe. The stamp meant every CG run
    this project has done was NVT with `ref_p` and `compressibility` dead keys and the published protocol
    never executed. A template states its own coupling; this leaves it alone.
    """
    changes = {'nsteps': steps, 'nstlog': 100, 'nstenergy': 100, 'gen-seed': 20260911}
    if folder == aa_dir:
        changes.update({'dt': 0.002, 'nstxout-compressed': 100})
    else:
        changes.update({'nstxtcout': 100, 'xtc-precision': 1000})
    return changes


def fit_temperature(text, temperature_k):
    """Rewrite the CG topology stage's `ff_inter -temperature` anchor to the run's temperature.

    `ff_inter` declares `-temperature` as an `int` and feeds it to a Boltzmann inversion, so a fractional
    run temperature (303.15 K) is rounded for that one argument — passing it through as written makes the
    tool exit with `ff_inter: error: argument -temperature: invalid int value: '303.15'`, and the whole CG
    topology stage fails with it. The run's own temperature stays fractional in the manifest and in the
    MDPs. This is a function rather than an inline `replace` so that a template which no longer carries the
    anchor fails a test instead of silently fitting at the template's own temperature.
    """
    return text.replace('-temperature 300', f'-temperature {round(float(temperature_k))}')


def normalize_settings(settings=None, profile='standard'):
    """Normalize an AA-to-CG run's settings: both halves, composed in one place.

    This run type accepts the AA settings (its AA reference is prepared from them)
    and the CG settings, derives the one duration the CG half needs from the AA
    halves instead of asking for it, and rejects a key neither half owns. Where
    both tables bound the same key, the AA bound decides -- output_interval_ps is
    tighter there -- so a value cannot be acceptable to one half and invalid to
    the other.
    """
    if settings is not None and not isinstance(settings, dict):
        raise ValueError('Run settings must be an object')
    supplied = dict(settings or {})
    unknown = set(supplied) - set(SETTING_SPECS) - set(aa.SETTING_SPECS) - set(aa.CHOICE_SPECS)
    if unknown:
        raise ValueError('Unknown run settings: ' + ', '.join(sorted(unknown)))
    aa_settings = aa.normalize_settings({key: value for key, value in supplied.items() if key in aa.SETTING_SPECS or key in aa.CHOICE_SPECS}, profile)
    cg_settings = _normalize_cg_settings(
        {key: value for key, value in supplied.items() if key in SETTING_SPECS} | mirror_aa_settings(aa_settings),
        profile)
    return cg_settings | aa_settings


def prepare(run_dir: Path, structure: Path | None = None, detergent: str = 'DDM', profile='standard', settings=None, mapping_candidate=None, bonded_state_snapshot=None, bonded_intent='fit_and_simulate', shared_reference=None, reference_root=None, molecule_snapshot=None, molecule_root=None):
    aa.validate_profile(profile)
    if molecule_snapshot is None or not shared_reference:
        raise ValueError('CG preparation requires a molecule snapshot and shared AA reference')
    names = CGNames.for_snapshot(molecule_snapshot)
    stage_plan, _, _ = stage_contract(names)

    aa_dir = run_dir / '1_AA-reference'
    aa_dir.mkdir()
    from ...analysis.runs import references as aa_references
    aa_references.resolve(reference_root, shared_reference['source_run_id'], shared_reference['sha256'])

    shutil.copytree(FORCE_FIELD, run_dir / FORCE_FIELD.name)
    inline_aa = False

    for name, relative in stage_plan:
        path = run_dir / relative
        path.parent.mkdir(exist_ok=True)
        shutil.copy2(SCRIPTS / path.name, path)

    if profile in ('draft-smoke','draft-smoke-reference'):
        data = draft_model.load(mapping_candidate, molecule_root=molecule_root)
        exports = mappings.export_files(data)
        for filename in ('mapping.map', 'mapping.ndx', 'model.json', 'README.txt'):
            (run_dir / '2_mapping' / filename).write_text(exports[filename])
        (run_dir / '2_mapping/draft-source.json').write_text(json.dumps(data, indent=2))
        cg = run_dir / '3_initial_CG'
        shutil.copy2(Path(bonded.__file__), cg/'bonded.py')
        shutil.copy2(SCRIPTS/'refine_bonded.py', cg/'refine_bonded.py')
        (cg / names.initial_itp).write_text(
            draft_model.initial_topology(
                data, molecule_root=molecule_root, residue_name=names.residue_name
            )
        )
        if bonded_intent == 'reuse_state' and bonded_state_snapshot and isinstance(bonded_state_snapshot.get('topology'), str):
            (cg / 'BOND_STATE.itp').write_text(bonded_state_snapshot['topology'])
            source_id = bonded_state_snapshot.get('source', {}).get('run_id')
            source_dir = paths.current().runs/source_id/'stages/3_initial_CG' if source_id else None
            if source_dir and source_dir.is_dir():
                for source_file in source_dir.glob('*_distr.dat'):
                    shutil.copy2(source_file, cg/source_file.name)
        # The one mapper, copied for every mapping rather than only the ringed ones: a mapping with no rings has
        # nothing to expand and writes no ring targets, and the branch that called ff_map instead is gone with it.
        shutil.copy2(SCRIPTS/'sugar_mapping.py', run_dir/'2_mapping/sugar_mapping.py')
        if data.get('rings'):
            shutil.copy2(SCRIPTS/'prepare_ring_constraints.py', cg/'prepare_ring_constraints.py')
            for suffix in ('.itp', '.source.json'):
                shutil.copy2(ROOT/'references'/('martini_v3.0.0_sugars_v2'+suffix), cg/('reference_sugars_v2'+suffix))

        shutil.copy2(TUTORIAL_TEMPLATE / '3_initial_CG/martini_v3.0.0.itp', cg / 'martini_v3.0.0.itp')
        shutil.copy2(TUTORIAL_TEMPLATE / '3_initial_CG/initial.mdp', cg / 'initial.mdp')
        update_mdp(cg / 'initial.mdp', {'nsteps': 0})
        (cg / 'topol.top').write_text(f'#include "martini_v3.0.0.itp"\n#include "{names.initial_itp}"\n[ system ]\n{names.residue_name} draft\n[ molecules ]\n{names.residue_name} 1\n')
        sim = run_dir / '4_CG_sim'
        shutil.copytree(TUTORIAL_TEMPLATE / '4_CG_sim/inputs', sim / 'inputs')
        (sim / 'system_EMPTY.top').write_text(f'#include "inputs/martini_v3.0.0.itp"\n#include "inputs/martini_v3.0.0_solvents_v1.itp"\n#include "{names.final_itp}"\n[ system ]\n{names.residue_name} draft in pure water\n[ molecules ]\n{names.residue_name} 1\n')
        for folder, mdp_names in ((aa_dir, ('em.mdp','eq.mdp','run.mdp')), (sim / 'inputs', ('minimization.mdp','eq.mdp','md.mdp'))):
            if folder == aa_dir and not inline_aa: continue
            update_mdp(folder / mdp_names[0], {'nsteps': 20000, 'define': ''})
            for filename, steps in zip(mdp_names[1:], (5000, 25000)):
                update_mdp(folder / filename, mdp_integration(folder, aa_dir, steps))
        shutil.copy2(SCRIPTS / 'validate_run.py', run_dir / '5_assessment/validate_run.py')
        shutil.copy2(SCRIPTS / 'distance_diagnostics.py', run_dir / '5_assessment/distance_diagnostics.py')
        sasa = run_dir / '6_SASA'
        (sasa / 'AA').mkdir(); (sasa / 'CG').mkdir()
        shutil.copy2(TUTORIAL_TEMPLATE / '5_SASA/vdwradii_AA.dat', sasa / 'AA/vdwradii.dat')
        (sasa / 'CG/vdwradii.dat').write_text(''.join(f'{names.residue_name} B{i:02d} { {"R":0.264,"S":0.230,"T":0.191}[b["size"]]}\n' for i,b in enumerate(data['beads'],1)))

    settings = normalize_settings(settings, profile)
    if inline_aa:
        aa_dt_eq = _mdp_value(aa_dir / 'eq.mdp', 'dt'); aa_dt_prod = _mdp_value(aa_dir / 'run.mdp', 'dt')
        update_mdp(aa_dir / 'eq.mdp', {'nsteps': round(settings['aa_equil_ps'] / aa_dt_eq), 'ref_t': settings['temperature_k'], 'nstxout-compressed': max(1, round(settings['output_interval_ps'] / aa_dt_eq))})
        update_mdp(aa_dir / 'run.mdp', {'nsteps': round(settings['aa_production_ps'] / aa_dt_prod), 'ref_t': settings['temperature_k'], 'nstxout-compressed': max(1, round(settings['output_interval_ps'] / aa_dt_prod))})
    if (run_dir / '4_CG_sim/inputs/eq.mdp').is_file():
        cg_eq = run_dir / '4_CG_sim/inputs/eq.mdp'; cg_md = run_dir / '4_CG_sim/inputs/md.mdp'
        eq_dt = _mdp_value(cg_eq, 'dt'); md_dt = _mdp_value(cg_md, 'dt')
        for path in (cg_eq, cg_md):
            update_mdp(path, {'gen-seed': settings['cg_seed'], 'ld-seed': settings['cg_seed'], 'gen-temp': settings['temperature_k']})
        update_mdp(cg_eq, {'nsteps': round(settings['cg_equil_ps'] / eq_dt), 'ref_t': settings['temperature_k'], 'nstxtcout': max(1, round(settings['output_interval_ps'] / eq_dt))})
        update_mdp(cg_md, {'nsteps': round(settings['cg_production_ps'] / md_dt), 'ref_t': settings['temperature_k'], 'nstxtcout': max(1, round(settings['output_interval_ps'] / md_dt))})
    fit_script = run_dir / '3_initial_CG/fit_topology.sh'
    if fit_script.is_file():
        fit_script.write_text(fit_temperature(fit_script.read_text(), settings['temperature_k']))
    sasa_script = run_dir / '6_SASA/sasa.sh'
    if sasa_script.is_file(): sasa_script.write_text('SASA_PROBE=' + f'{settings["sasa_probe_nm"]:.6g}\n' + sasa_script.read_text())

    manifest = run_dir / 'manifest.json'
    metadata = json.loads(manifest.read_text()) if manifest.exists() else {'stages': []}
    if mapping_candidate is not None:
        metadata['mapping_candidate'] = mapping_candidate
        metadata['mapping_sha256'] = hashlib.sha256(json.dumps(mapping_candidate, sort_keys=True).encode()).hexdigest()
    metadata.update(profile=profile, scientifically_validated=False, settings=settings, stage_plan=[[name, relative] for name, relative in stage_plan])
    metadata['cg_names'] = {'residue_name': names.residue_name, 'initial_itp': names.initial_itp, 'final_itp': names.final_itp}
    if shared_reference:
        metadata.update(shared_reference=shared_reference, reference_reused=True, reference_run_id=shared_reference['source_run_id'])
    metadata['force_field'] = {'name': FORCE_FIELD.name, 'source': str(FORCE_FIELD.relative_to(ROOT)), 'staged_path': FORCE_FIELD.name,
        'sha256': {str(p.relative_to(FORCE_FIELD)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(FORCE_FIELD.rglob('*')) if p.is_file()}}
    metadata['inputs_sha256'] = {str(p.relative_to(run_dir)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(run_dir.rglob('*')) if p.is_file() and p != manifest}
    metadata['environment'] = recorded_environment()
    if profile == 'draft-smoke':
        metadata['analysis_topology'] = 'GRO atom/residue order + explicit ITP interactions; MDAnalysis 2.10 does not support GROMACS 2026 TPR 138. Trajectories made whole with gmx trjconv.'
        metadata['limitations'] = ['Draft mapping and nonbonded bead types, not scientifically validated', f'AA production {settings["aa_production_ps"]} ps; CG production {settings["cg_production_ps"]} ps; pure water', 'Bonded parameters fit to the recorded AA reference; no convergence or thermodynamic validation']
    metadata['tools'] = tool_metadata()
    files.atomic_json(manifest, metadata)


def tool_metadata():
    result = {}
    commands = [('gmx',['--version']), ('python',['-c', 'import fast_forward,MDAnalysis,hashlib,pathlib; import fast_forward.interaction_fit as fitter; print("Fast_Forward",fast_forward.__version__); print("MDAnalysis",MDAnalysis.__version__); print("Fitter",fitter.__file__,hashlib.sha256(pathlib.Path(fitter.__file__).read_bytes()).hexdigest())'])]
    for exe,args in commands:
        executable = tools.tool_path(exe)
        if not executable: raise FileNotFoundError(f'Missing tool: {exe}')
        proc = subprocess.run([executable,*args],env=environment(),capture_output=True,text=True,check=True,timeout=30)
        result[exe] = {'path':executable,'version_output':proc.stdout,'sha256':files.sha256(executable)}
    for exe in ('ff_inter','ff_assess'):
        executable = tools.tool_path(exe)
        if executable: result[exe] = {'path':executable,'sha256':files.sha256(executable)}
    # Which source produced those entry points: their version output cannot say.
    provenance = tools.declared_provenance()
    if provenance:
        result['fast_forward_source'] = provenance
    return result


def readiness(molecule_id, method, profile='standard', mapping_candidate=None, molecule_root=None):
    """Check AA inputs, CG tools, and mapping for any molecule id."""
    aa.validate_profile(profile)
    if method != 'fast_forward':
        return {'ready': False, 'checks': [], 'blockers': ['This method is not connected to an executable workflow.']}
    molecule_root = Path(molecule_root) if molecule_root is not None else ROOT / 'molecules'
    checks = []
    try:
        molecule = aa_molecules.inspect(molecule_root, molecule_id)
    except ValueError as exc:
        return {'ready': False, 'checks': [], 'blockers': [str(exc)], 'profile': profile,
                'scientific_gate': {'scientifically_validated': False, 'production_allowed': False,
                                    'reason': 'No scientifically validated CG model is registered.'}}
    checks.append({'label': 'Molecule',
                   'path': molecule['path'],
                   'ready': molecule['valid'],
                   'detail': 'Input consistency checked' if molecule['valid'] else '; '.join(molecule['issues'])})
    checks.append({'label': 'CG workflow support',
                   'path': molecule.get('adapter', 'cg-fast-forward'),
                   'ready': bool(molecule.get('executable')),
                   'detail': ('Any valid AA molecule runs through the generic CG workflow; '
                              'the AA stage is reused from an AA-only source.'
                              if molecule.get('executable')
                              else '; '.join(molecule.get('blockers') or molecule.get('issues') or []))})
    checks.append({'label': 'Force field used by workflow',
                   'path': str(FORCE_FIELD.relative_to(ROOT)),
                   'ready': (FORCE_FIELD / 'forcefield.itp').is_file(),
                   'detail': 'Copied into each run with checksums'})
    for tool in ('gmx','ff_inter','ff_assess'):
        executable = tools.tool_path(tool)
        ok, detail = probe_tool(executable) if executable else (False, 'Executable not found')
        checks.append({'label': tool, 'path': executable or tool, 'ready': ok, 'detail': detail})
    if profile in ('draft-smoke','draft-smoke-reference'):
        try:
            draft_model.load(mapping_candidate, molecule_root=molecule_root)
            detail, ok = 'Connected heavy-atom draft; bead types uncalibrated. Short execution test only.', True
        except (ValueError, OSError) as exc:
            detail, ok = ('Select a saved CG mapping before launching candidate screening'
                          if mapping_candidate is None and isinstance(exc, FileNotFoundError)
                          else str(exc)), False
        checks.append({'label': 'CG mapping',
                       'path': (mapping_candidate.get('file', 'selected snapshot')
                                if mapping_candidate is not None else 'none selected'),
                       'ready': ok, 'detail': detail})
    blockers = [x['label'] + ': ' + x['detail'] for x in checks if not x['ready']]
    # Tools a stage never invokes (bartender, xtb) are reported here, not turned into
    # blockers: the blockers above already come from the commands this run type resolves.
    declared_checks, _ = tools.declared_tool_checks()
    checks.extend(declared_checks)
    if profile == 'standard':
        blockers.append('A reviewed CG model is required for standard parameterization. Choose candidate screening to test execution only.')
    return {'ready': not blockers, 'checks': checks, 'blockers': blockers, 'profile': profile,
            'scientific_gate': {'scientifically_validated': False, 'production_allowed': False,
                                'reason': 'No scientifically validated CG model is registered; reviewer approval of a mapping alone cannot authorize production.'}}


def _protocol_stage_contract(metadata):
    """Resolve a naming context from the metadata a caller holds."""
    snapshot = metadata.get('molecule_snapshot')
    names = CGNames.for_snapshot(snapshot) if snapshot else metadata.get('names')
    return stage_contract(names)


def _protocol_stages(metadata):
    """Resolve the named stage declarations for the metadata's molecule."""
    snapshot = metadata.get('molecule_snapshot')
    names = CGNames.for_snapshot(snapshot) if snapshot else CGNames.ddm_defaults()
    return tuple(stage.resolve(names.env()) for stage in STAGE_DEFS)


def _protocol_readiness(metadata):
    molecule_id = metadata.get('molecule_id')
    if not molecule_id:
        return protocol.blocked('molecule_id is required to check an AA to CG run')
    ready = readiness(molecule_id, metadata.get('method') or 'gromacs',
                      metadata.get('profile') or 'standard',
                      metadata.get('mapping_candidate'), metadata.get('molecule_root'))
    # An AA-to-CG run needs everything the atomistic half needs, because its own reference is built from a molecule
    # that has to be simulatable. The web route used to collect both answers and merge them by hand, which put a run
    # type's prerequisites inside a page that happened to ask about it; the rule belongs with the run type, and the
    # route now asks this one question like every other caller.
    molecule_root = metadata.get('molecule_root')
    try:
        from ...analysis.runs import references as aa_references
        from ...models.molecules import aa as aa_molecules
        reference_run_id = metadata.get('reference_run_id')
        if reference_run_id:
            selection = aa_molecules.selection(molecule_root, molecule_id)
            aa_references.resolve(metadata.get('runs_root'), reference_run_id, molecule_snapshot=selection)
        else:
            from . import aa
            ready.setdefault('blockers', []).extend(aa.readiness(molecule_root, molecule_id)['blockers'])
    except (OSError, ValueError) as exc:
        ready.setdefault('blockers', []).append(str(exc))
    ready['ready'] = ready.get('ready', False) and not ready.get('blockers')
    return ready


def _protocol_prepare(run_dir, metadata):
    """Prepare an AA-to-CG run the way every other run type is prepared: fill `stages/`, then finish the run.

    This used to be two steps in two modules -- the coordinator assembled the arguments, and `workflow.prepare_run`
    built the stage directory, copied it to `inputs/` and wrote the manifest. Both halves live here now, which is what
    makes `adapter_for('aa_cg').prepare(run_dir, metadata)` mean the same thing as it does for every other run type:
    a run directory in, a prepared run out.
    """
    keys = ('structure', 'detergent', 'profile', 'settings', 'mapping_candidate',
            'bonded_state_snapshot', 'bonded_intent', 'shared_reference',
            'reference_root', 'molecule_snapshot', 'molecule_root')
    values = {key: metadata[key] for key in keys if key in metadata}
    # The CG settings dialect is its own vocabulary. A key from the AA half that this run type does not use is dropped
    # rather than refused, because those settings describe the reference it consumes instead of the run it builds --
    # `normalize_settings` would otherwise take them, since it accepts both dialects by design. The coordinator applied
    # this filter before calling the old entry point; it belongs with the run type that declares the dialect.
    if values.get('settings'):
        values['settings'] = {key: value for key, value in values['settings'].items() if key in SETTING_SPECS}
    stages = Path(run_dir) / 'stages'
    stages.mkdir(parents=True, exist_ok=True)
    prepare(stages, **values)
    # `prepare` leaves its record beside the stages, including the tool versions it used; the run's manifest is written
    # from that record, and the record itself is not a stage input.
    record = json.loads((stages / 'manifest.json').read_text())
    return protocol.finish_prepared_run(run_dir, stages, metadata=record, tools=record.get('tools', {}),
                                        plan=protocol.plan_pairs(record),
                                        environment=record.get('environment'))


def protocol_settings_specs():
    """The vocabulary this run type accepts, both halves of it, published as one mapping.

    An AA-to-CG run prepares its own atomistic reference from the AA settings and its coarse-grained stages from the
    CG ones, and `normalize_settings` takes a key from either half. So a caller that reads what this run type
    publishes has to see both -- it was the *caller's* job to merge the two dialects, and the queue route did exactly
    that with a set union in a web handler.

    Where both halves bound the same key the AA entry wins, which is the same precedence `normalize_settings` applies
    when it merges the halves, and the tighter bound: the AA half's `output_interval_ps` floor is 0.002 against the CG
    half's 0.001, so a form offering the CG one would take a value the normalizer then refuses.
    """
    return {**SETTING_SPECS, **aa.SETTING_SPECS}


PROTOCOL = protocol.Protocol(
    name='aa_cg',
    stage_contract=_protocol_stage_contract,
    stages=_protocol_stages,
    settings_specs=protocol_settings_specs,
    stage_defaults=lambda: stage_defaults(),
    normalize_settings=lambda settings=None, profile='standard': normalize_settings(settings, profile),
    readiness=_protocol_readiness,
    prepare=_protocol_prepare,
    tool_report=tool_metadata,
    # The AA half's choices travel with it: this run type accepts `force_field` and `mdrun_nb` because it prepares an
    # atomistic reference of its own, and `normalize_settings` takes them from the AA half.
    choice_specs=lambda: aa.CHOICE_SPECS,
)
