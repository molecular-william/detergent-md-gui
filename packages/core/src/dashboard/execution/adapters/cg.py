"""Generic coarse-grained workflow adapter, with packaged DDM defaults.

Stages, MDP profiles and readiness are molecule-agnostic. When a molecule
snapshot is supplied, the CG residue name and topology filenames derive from
that snapshot via CGNames.for_snapshot and the AA stage is consumed from a
coordinator-attached shared reference. The packaged SwissParam source under
molecules/DDM is used only when a caller invokes the adapter without a
snapshot (historical smoke-test paths).
"""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from ... import files, martini3
from ...models import mappings
from ...models.bonded import parameterization as parameterizations
from ...models.molecules import aa as aa_molecules
from ...models.molecules import draft as draft_model
from .. import devices, protocol, run_inputs, tools
from ..environment import AA_TEMPLATE, FORCE_FIELD, ROOT, TUTORIAL_TEMPLATE, environment, probe_tool, recorded_environment
from ..mdp import PROFILES, write_mdp
from ..settings import normalize
from ..stages import Stage, stage_tables
from . import aa
from .cg_names import CGNames

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
# What this module offers to the rest of the application: PROTOCOL (the run-type
# surface at the end of this file), stage_contract() for a naming context, and the
# repository script directory the stages run from. The stage tables, settings bounds
# and tool report in between are read through those; a name is not part of the
# interface merely because it is importable.

#: The CG half's shared inputs, read where they live and named by path and digest in the run's `inputs` record. The
#: Martini names are files of the installed set (`dashboard.martini3`), never repository paths: every run reads the one
#: installed copy, and each topology names it by a path relative to where the topology is written. `water.gro` is the
#: box `gmx solvate` replicates and `cg_simulation.sh` opens in place; `vdwradii_AA.dat` is kept for the convention it
#: is (the CG radii beside it are generated from bead sizes).
TEMPLATE_MDPS = TUTORIAL_TEMPLATE / '4_CG_sim/inputs'
MARTINI_FF = martini3.REQUIRED[0]
MARTINI_SOLVENTS = martini3.REQUIRED[1]
MARTINI_IONS = martini3.REQUIRED[2]
WATER_BOX = TEMPLATE_MDPS / 'water.gro'
SASA_RADII_AA = TUTORIAL_TEMPLATE / '5_SASA/vdwradii_AA.dat'
SUGAR_REFERENCE = martini3.SUGARS[0]
SUGAR_PROVENANCE = martini3.SUGARS[1]

#: The repository modules the stage scripts execute, recorded by path and digest beside the scripts. The helpers are
#: reached as package modules (`"$PYTHON" -m dashboard.execution.scripts.<name>`) so nothing is copied into a run; the
#: executor re-hashes each one before a stage starts and refuses a stage whose code changed since prepare.
MODULES = {
    'dashboard.execution.scripts.sugar_mapping': 'dashboard/execution/scripts/sugar_mapping.py',
    'dashboard.execution.scripts.refine_bonded': 'dashboard/execution/scripts/refine_bonded.py',
    'dashboard.execution.scripts.prepare_ring_constraints': 'dashboard/execution/scripts/prepare_ring_constraints.py',
    'dashboard.execution.scripts.use_parameterization': 'dashboard/execution/scripts/use_parameterization.py',
    'dashboard.execution.scripts.validate_run': 'dashboard/execution/scripts/validate_run.py',
    'dashboard.execution.scripts.distance_diagnostics': 'dashboard/execution/scripts/distance_diagnostics.py',
    'dashboard.models.bonded': 'dashboard/models/bonded/__init__.py',
}

#: The profile an AA-to-CG run is stamped with. Fitting is a property of this run type rather than a per-run
#: choice (D1/D2): the run always fits its own bonded parameters from a full-length AA reference, and a CG run
#: handed a pre-parameterized molecule never fits. So the profile is this run type's default instead of a select
#: on its panel, the manifest records it as it always has, and nothing in `prepare` keys on it. `standard` stays
#: available to `aa_only`, the only run type that has ever used it.
AA_CG_PROFILE = 'draft-smoke-reference'

#: Every stage runs the repository's own script (`dashboard/execution/scripts/`) with its stage directory as the
#: working directory; the run records that path and its digest instead of carrying a copy. `relative` still names the
#: stage directory and the entry point a legacy run used, so the stage plan a reader resolves does not move -- the
#: file it names no longer has to exist.
STAGE_DEFS = (
    Stage('AA reference', '1_AA-reference/aa_reference.sh',
          ('molecule.pdb', 'system_EMPTY.top', 'em.mdp', 'eq.mdp', 'run.mdp'),
          ('prod/lig.gro', 'prod/lig.tpr', 'prod/lig.xtc', '3-run.xtc'),
          script='dashboard/execution/scripts/aa_reference.sh'),
    Stage('trajectory mapping', '2_mapping/map_trajectory.sh',
          ('../1_AA-reference/prod/lig.xtc', '../1_AA-reference/prod/lig.tpr',
           '../1_AA-reference/prod/lig.gro', 'mapping.map'),
          ('mapped.xtc', 'mapped.gro', 'mapping_validation.json'),
          script='dashboard/execution/scripts/map_trajectory.sh'),
    Stage('CG parameterization', '3_initial_CG/fit_topology.sh',
          ('../2_mapping/mapped.xtc', '../2_mapping/mapped.gro', 'initial.mdp',
           'topol.top', '{initial_itp}'),
          ('mapped.tpr', '{final_itp}', '*_bonds_distr.dat',
           '*_angles_distr.dat', '*_distances_distr.dat'),
          script='dashboard/execution/scripts/fit_topology.sh'),
    # The water box and the template MDPs are named here, not linked into `inputs/`: the script reads the published
    # box from the repository and the MDPs the run generated. `relative` keeps the stage's old entry-point name -- the
    # file a legacy run's own copy still is -- while `script` names the repository file this stage executes.
    Stage('CG simulation', '4_CG_sim/cg_simulation_run.sh',
          ('../2_mapping/mapped.gro', '../3_initial_CG/{final_itp}',
           'system_EMPTY.top', 'inputs/md.mdp'),
          ('prod/lig_CG.gro', 'prod/lig_CG.tpr', 'prod/lig_CG.xtc'),
          script='dashboard/execution/scripts/cg_simulation.sh'),
    Stage('CG assessment (ff_assess)', '5_assessment/assess.sh',
          ('../4_CG_sim/prod/lig_CG.xtc', '../4_CG_sim/prod/lig_CG.tpr',
           '../4_CG_sim/prod/lig_CG.gro', '../3_initial_CG/{initial_itp}',
           '../3_initial_CG/*_bonds_distr.dat',
           '../3_initial_CG/*_distances_distr.dat'),
          ('report_interactions.out', 'report_distances.out', 'validation.json',
           'distance_diagnostics_stratified.json',
           'distance_matrix_stratified_{residue_name}.png'),
          script='dashboard/execution/scripts/assess.sh'),
    Stage('SASA analysis', '6_SASA/sasa.sh',
          ('../1_AA-reference/prod/lig.xtc', '../4_CG_sim/prod/lig_CG.xtc',
           'CG/vdwradii.dat'),
          ('AA/SASA-AA.xvg', 'CG/SASA-CG.xvg'),
          script='dashboard/execution/scripts/sasa.sh'),
)

_DEFAULT_NAMES = CGNames.ddm_defaults()
STAGES, REQUIRED_INPUTS, REQUIRED_OUTPUTS = stage_tables(
    STAGE_DEFS, _DEFAULT_NAMES.env()
)

#: What differs for a run that consumes its model's parameterization (D5 of
#: `docs/design/2026-10-16-parameterization-and-new-run.md`): stage 3's driver and its two artefacts,
#: and the assessment stage's inputs. Stage 3 is a different script rather than a branch inside one --
#: the fit path's script is named for fitting and its outputs include the distributions `ff_inter`
#: measures, and neither is true of a stage that writes the model's own terms and says so. Stage 5 is
#: the consequence of that, named rather than left to fail at its own input check: an atomistic
#: reference distribution is a fit's output, so a run that did not fit has none to be assessed against.
#:
#: Each entry names only the fields that differ: `dataclasses.replace` takes the rest from the
#: declaration above, so stage 5's outputs and every stage not named here are stated once in this
#: module rather than twice.
PARAMETERIZED = {
    'CG parameterization': {
        'relative': '3_initial_CG/use_parameterization.sh',
        'inputs': ('../2_mapping/mapped.xtc', '../2_mapping/mapped.gro', 'initial.mdp',
                   'topol.top', '{initial_itp}', 'parameterization.json'),
        'outputs': ('mapped.tpr', '{final_itp}', 'parameterization_used.json'),
        'script': 'dashboard/execution/scripts/use_parameterization.sh',
    },
    'CG assessment (ff_assess)': {
        # The revision's histograms stay in the parameterization store and are named in the run's `inputs` record;
        # stage 5 reads them through the `references.txt` the run's prepare writes. So the stage keeps `assess.sh` and
        # only its declared inputs differ: an atomistic reference distribution is a fit's output, and this run made
        # none. `relative` keeps the old generated entry's name so a legacy run's own copy is still the fallback the
        # executor reaches for; the repository script it names is the one declaration above.
        'relative': '5_assessment/assess_parameterization.sh',
        'inputs': ('../4_CG_sim/prod/lig_CG.xtc', '../4_CG_sim/prod/lig_CG.tpr',
                   '../4_CG_sim/prod/lig_CG.gro', '../3_initial_CG/{initial_itp}'),
    },
}


def stage_definitions(parameterized=False) -> tuple:
    """This run type's stages, with stage 3 and stage 5 shaped for what the run will do."""
    if not parameterized:
        return STAGE_DEFS
    return tuple(replace(stage, **PARAMETERIZED[stage.name]) if stage.name in PARAMETERIZED else stage
                 for stage in STAGE_DEFS)


def consumes_parameterization(metadata) -> bool:
    """Whether a run uses its model's parameterization instead of fitting in stage 3.

    D5: the choice of fit-or-reuse is a property of the *model*, and the run records which happened.
    `prepare` writes this into the run's manifest, so a reader -- including the stage contract two
    frames up -- resolves the same run shape from the same recorded fact, and a run prepared before
    this field existed reads as a run that fitted, which is what it did.
    """
    bonded = metadata.get('bonded') if isinstance(metadata, dict) else None
    return bool(isinstance(bonded, dict) and bonded.get('consumes_parameterization'))


def stage_contract(names: CGNames | None = None, *, parameterized: bool = False):
    """Return the executable stage contract for one molecule naming context."""
    return stage_tables(stage_definitions(parameterized), (names or _DEFAULT_NAMES).env())


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

#: Settings from the AA half that describe *this run's* execution rather than the AA reference it consumes: the device
#: and the CPU budget. A reference is prepared under its own settings; these are the run's own, on both halves.
RUN_EXECUTION_SETTINGS = ('mdrun_gpu', 'mdrun_ntomp', 'mdrun_ranks')


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
    values = normalize(
        settings, stage_defaults(profile)['values'], specs=SETTING_SPECS,
        object_message='Run settings must be an object', unknown_prefix='Unknown run setting: ',
        label_messages=True, integrals={'cg_seed': 'CG random seed must be an integer'})
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


#: The reviewed profile each MDP this run writes uses, keyed by its path relative to `stages/` -- the path the stage
#: scripts already read.
MDP_PROFILES = {'3_initial_CG/initial.mdp': 'cg-initial-v1',
                '4_CG_sim/inputs/minimization.mdp': 'cg-minimization-v1',
                '4_CG_sim/inputs/eq.mdp': 'cg-equilibration-v1',
                '4_CG_sim/inputs/md.mdp': 'cg-production-v1'}


def mdp_values(settings, profile):
    """The numbers one CG dynamics profile leaves to the run, at the profile's own timestep.

    The step count and the output stride are the arithmetic `cg.prepare` has always used; only the timestep moved,
    from a template read back after patching to the reviewed profile the file is rendered from.
    """
    dt = PROFILES[profile].settings['dt']
    duration = settings['cg_equil_ps' if profile == 'cg-equilibration-v1' else 'cg_production_ps']
    return {'nsteps': round(duration / dt),
            'nstxtcout': max(1, round(settings['output_interval_ps'] / dt)),
            'ref-t': settings['temperature_k'], 'gen-temp': settings['temperature_k'],
            'gen-seed': settings['cg_seed'], 'ld-seed': settings['cg_seed']}


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


def stage_mapping(directory: Path, data, *, names) -> None:
    """Write `2_mapping/`: the export, the one mapper, and nothing that is a run's own.

    One definition for the two callers that need it -- a run's `prepare` and the panel's fit job --
    because a fit whose frames were mapped by a different exporter than the run's would be fitting a
    trajectory the run cannot reproduce. The mapper itself stays in the repository: both callers run
    `dashboard.execution.scripts.sugar_mapping` as a package module.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    exports = mappings.export_files(data)
    for filename in ('mapping.map', 'mapping.ndx', 'model.json', 'README.txt'):
        (directory / filename).write_text(exports[filename])


def stage_parameterization(directory: Path, data, *, names, molecule_root=None) -> None:
    """Write `3_initial_CG/`: everything stage 3 reads, for either of its two shapes.

    The seeded topology, the ring pass, the refinement and the cooperative topology `gmx grompp`
    reads are the same files whether this stage goes on to fit or goes on to write the model's own
    terms; only the driver and its outputs differ. Staged together for that reason, and shared with
    the panel's fit job so a fit produced there is produced by the files a run would have used.

    What it does **not** write is code or a copy of anything the repository already publishes: the
    helpers are package modules the shared script runs from the checkout, and `topol.top` includes the
    installed Martini force field by a path relative to this directory, so the tree is read where it
    lives and the include resolves here, from a stage directory, or from the fit job's scratch tree.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / names.initial_itp).write_text(
        draft_model.initial_topology(data, molecule_root=molecule_root, residue_name=names.residue_name))
    write_mdp('cg-initial-v1', directory / 'initial.mdp')
    (directory / 'topol.top').write_text(
        f'#include "{martini3.include(MARTINI_FF, directory)}"\n#include "{names.initial_itp}"\n'
        f'[ system ]\n{names.residue_name} draft\n[ molecules ]\n{names.residue_name} 1\n')


def _recorded_histograms(mapping_candidate=None, beads=None, recorded=None):
    """The revision's recorded reference histograms as `(inventory, [(absolute path, name, digest)])`.

    Read, never written: the files stay in the parameterization store, which is immutable per revision and
    hashed by the run's `inputs` record. Returns no files, with the reason, when the revision records none.
    """
    if recorded is None:
        recorded = parameterizations.distributions(mapping_candidate)
    if not recorded:
        engine = (parameterizations.current(mapping_candidate) or {}).get('engine')
        if engine == 'bartender':
            return _inventory([], [], beads, "BARTENDER measured no reference histograms when this model was fitted, "
                              "and its own analysis is not built yet (D6a of "
                              'docs/design/2026-10-16-parameterization-and-new-run.md), so the CG '
                              'assessment has nothing to score this run against.'), []
        return _inventory([], [], beads, 'This model records no AA reference histograms -- it predates them being '
                          'recorded -- so the CG assessment has nothing to score this run against. A re-fit (Fit this '
                          'model) records them.'), []
    listing, files = [], []
    for entry in recorded['files']:
        path = recorded['directory'] / entry['name']
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != entry['sha256']:
            raise ValueError(f'The recorded reference distribution {entry["name"]} does not match its digest; '
                             'the parameterization store has been changed under it')
        listing.append({'name': entry['name'], 'sha256': digest})
        files.append((path, entry['name'], digest))
    pairs = [entry for entry in listing if parameterizations.PAIR_DISTRIBUTION.match(entry['name'])]
    reason = None
    if not pairs:
        reason = (f'This model records {len(listing)} AA reference histogram(s) for its bonded terms and none of the '
                  'pairwise distance histograms the CG assessment scores ('
                  f'{_pair_count(beads)} expected, one `<resid>_<a>_<resid>_<b>_distances_distr.dat` per bead pair), '
                  'so it has nothing to score this run against: `ff_assess` skips a pair with no reference file and '
                  'leaves its cell at 0.00, which reads identical. A re-fit (Fit this model) records them.')
    return _inventory(listing, pairs, beads, reason), files


def reference_distributions(mapping_candidate=None, beads=None):
    """The revision's histograms named in place, as `(inventory, store entries, [(path, name, digest)])`.

    `ff_assess` does not measure the reference: it reads `<group>_<type>_<distr>.dat` files from its `-d` directory and
    scores the CG trajectory against them. A run that *fits* in-house leaves them in `3_initial_CG` as a by-product of
    fitting -- `ff_inter -dists -dist-matrix` measures both families on the tool's own bins -- and a run that *consumes*
    a parameterization reads them from the revision that recorded them. What it does not do is copy them: the store's
    revision directory is immutable and already hashed, so the run names each file by path and digest, and the stage
    that scores against them is handed that directory.

    A revision that records none is **not** a reason to refuse the run. It is a reason to say, in the stage that has
    nothing to do, that it had nothing to do: the simulation is still worth running (D6a keeps BARTENDER's analysis
    separate, and it is unbuilt), and the run records `skipped` with this reason rather than a number it did not measure.

    Two counts decide that, and they are counted separately because only the second one decides. `pairs` is the family
    the score matrix is built from (`parameterization.PAIR_DISTRIBUTION`), one histogram per bead pair, with the count a
    molecule of `beads` atoms needs beside it; `interactions` is bonds, angles and dihedrals. A revision carrying only
    the second family is *not* scorable and does not say so: `ff_assess` skips a pair whose reference is missing and
    leaves that cell at 0.00, so the run would print a perfect matrix for a comparison that never happened.
    """
    recorded = parameterizations.distributions(mapping_candidate)
    inventory, files = _recorded_histograms(mapping_candidate, beads, recorded=recorded)
    entries = [run_inputs.store('reference_distribution', path, label=name) for path, name, _ in files]
    return inventory, entries, files


def stage_distributions(directory, mapping_candidate=None, beads=None):
    """Copy the revision's histograms into `directory`, for the one caller that stages its own attempt.

    A re-score (`assessment_rescore`) is not a run being prepared: it makes a new attempt directory beside the first
    assessment and hands `assess.sh` that directory as `-d`. That directory is the attempt's own, so the files are
    copied into it; a prepared run references them instead.
    """
    inventory, files = _recorded_histograms(mapping_candidate, beads)
    directory = Path(directory)
    for path, name, _ in files:
        (directory / name).write_bytes(path.read_bytes())
    return inventory


def _pair_count(beads):
    """How many pairwise distance histograms a molecule of `beads` atoms needs, or `None` when the count is not known.

    `score.py` scores every unordered pair of a molecule's atoms, virtual sites included, so the family is
    `n(n-1)/2` files. This is arithmetic rather than a naming rule: the names are the tool's, and nothing here invents
    one it cannot name.
    """
    return beads * (beads - 1) // 2 if beads else None


def _inventory(listing, pairs, beads, reason):
    """The run's reference-histogram record, and the shape a reader can count from."""
    return {'files': listing,
            'pairs': {'files': len(pairs), 'expected': _pair_count(beads)},
            'interactions': {'files': len(listing) - len(pairs)},
            'reason': reason}


def _published(role, path, label):
    """One repository file this run names in its `inputs` record instead of copying into the run."""
    path = Path(path)
    return run_inputs.published(role, path.relative_to(ROOT), label=label, repo_root=ROOT)


def shared_inputs(*, data):
    """What this run reads in place: the installed Martini set, the water box, the radii convention, and a ringed model's
    sugar reference. Named by path and digest rather than copied -- the atomistic force field tree is absent on purpose:
    its own `topol.top` is only read by the atomistic reference stage, which this run type always reuses."""
    references = [
        run_inputs.installed('martini_force_field', martini3.path(MARTINI_FF),
                             label='Martini 3 force field (martini_v3.0.0.itp)'),
        run_inputs.installed('martini_solvents', martini3.path(MARTINI_SOLVENTS),
                             label='Martini 3 solvents (martini_v3.0.0_solvents_v1.itp)'),
        run_inputs.installed('martini_ions', martini3.path(MARTINI_IONS),
                             label='Martini 3 ions (martini_v3.0.0_ions_v1.itp)'),
        _published('martini_water', WATER_BOX, 'Martini 3 water box (water.gro)'),
        _published('sasa_radii_aa', SASA_RADII_AA, 'AA SASA radii (Fast_Forward vdwradii_AA.dat)'),
    ]
    if data.get('rings'):
        # The mapping's ring constraints were derived from this reference; the run records it as the convention its
        # seeds came from. No stage opens it, so it is named and left where it lives.
        references += [
            run_inputs.installed('sugar_reference', martini3.path(SUGAR_REFERENCE),
                                 label='Martini 3 sugar reference (martini_v3.0.0_sugars_v2.itp)'),
            run_inputs.installed('sugar_reference_provenance', martini3.path(SUGAR_PROVENANCE),
                                 label='Martini 3 sugar reference provenance'),
        ]
    return references


def prepare(run_dir: Path, structure: Path | None = None, detergent: str = 'DDM', profile=AA_CG_PROFILE, settings=None, mapping_candidate=None, shared_reference=None, reference_root=None, molecule_snapshot=None, molecule_root=None):
    """Prepare one AA-to-CG run's stage directory.

    What this run type stages, it stages for every AA-to-CG run: the mapping export, the seeded
    topology and the scripts stage 3 drives. The two controls that made any of that a per-run choice
    are gone (D1): a caller cannot hand this run a pre-fitted bonded state, and there is no "fit
    only" stop. The profile is a duration preset recorded in the manifest and keyed on by nothing
    here.

    **What stage 3 does is a property of the model, and this is where the two answers part.** A
    mapping whose parameterization has a current revision is consumed: the terms are staged as
    `parameterization.json`, stage 3 writes them and says in its own artefact that it did not fit,
    and the manifest records that this run did not fit either (D5). A mapping with no current
    revision is fitted here, exactly as every AA-to-CG run used to be, and the manifest records that
    it was. Nothing on the run panel chooses which -- its absence is the point.
    """
    aa.validate_profile(profile)
    if molecule_snapshot is None or not shared_reference:
        raise ValueError('CG preparation requires a molecule snapshot and shared AA reference')
    names = CGNames.for_snapshot(molecule_snapshot)
    # A caller that names no mapping has no model to read a parameterization from; the mapping is
    # loaded below and that is where the absence is refused, in the order this function has always
    # refused it (the reference first, then the mapping).
    revision = parameterizations.current(mapping_candidate) if isinstance(mapping_candidate, dict) else None
    stage_plan, _, _ = stage_contract(names, parameterized=revision is not None)

    aa_dir = run_dir / '1_AA-reference'
    aa_dir.mkdir()
    from ...analysis.runs import references as aa_references
    aa_references.resolve(reference_root, shared_reference['source_run_id'], shared_reference['sha256'])

    # The stage directories exist before anything is staged into them; nothing executable is written: each stage runs
    # the repository's own script, recorded in the manifest by path and digest.
    for _, relative in stage_plan:
        (run_dir / relative).parent.mkdir(parents=True, exist_ok=True)

    # Everything below is what an AA-to-CG run stages, and none of it is a per-run choice: the run
    # type takes its bonded terms from the model it was handed, fitting them itself only when the
    # model carries none (D1/D5). It used to sit inside `if profile in ('draft-smoke', ...)`, which
    # made "is a mapping staged at all" a property of a duration preset.
    data = draft_model.load(mapping_candidate, molecule_root=molecule_root)
    # What already existed when prepare ran is named, by path and digest, and read where it lives: the installed Martini
    # set, the water box, the radii convention and a ringed model's sugar reference (the atomistic force-field tree is
    # not among them -- see `shared_inputs`). The generated topologies below include these by a path relative to
    # themselves.
    references = shared_inputs(data=data)
    stage_mapping(run_dir / '2_mapping', data, names=names)
    (run_dir / '2_mapping/draft-source.json').write_text(json.dumps(data, indent=2))
    cg = run_dir / '3_initial_CG'
    stage_parameterization(cg, data, names=names, molecule_root=molecule_root)
    recorded, unscored = None, None
    inventory = None
    # Where stage 5's `-d` directory is. A run that fits leaves its histograms in stage 3, which the script defaults
    # to; a run that consumes a model reads them from the revision that recorded them. Both answers are data the run
    # writes down (`references.txt`), never a script: the shared `assess.sh` reads the directory it is told.
    reference_directory = '../3_initial_CG'
    if revision is not None:
        # The model's own terms, and the driver that writes them instead of fitting. The revision's reference
        # histograms are *named*, not staged: `ff_assess` scores a CG trajectory against pre-computed
        # `<group>_<type>_distr.dat` files in its `-d` directory and never makes them, and a run that consumes a model
        # reads them from the revision that recorded them. A run that reaches stage 5 with nothing to score records
        # `skipped`, with the reason in the inventory below, rather than a matrix of zeros.
        inventory, histogram_entries, histograms = reference_distributions(mapping_candidate, beads=len(data['beads']))
        references += histogram_entries
        recorded, unscored = inventory['files'], inventory['reason']
        # The run's own inventory: the store files it reads in place, by absolute path, so the consuming stage checks
        # their digests where they live rather than beside itself. The two counts say which families it has, and a
        # `reason` says in the run's own words why stage 5 cannot score -- either none at all or, the quiet case, none
        # of the pairwise family the score matrix is built from.
        absolute = [{'name': str(path), 'sha256': digest} for path, _, digest in histograms]
        (cg / 'distributions.json').write_text(
            json.dumps({'directory': '.', **{**inventory, 'files': absolute}, 'source':
                        f"revision {(revision or {}).get('revision')} of this mapping's parameterization"},
                       indent=2, sort_keys=True) + '\n')
        (cg / 'parameterization.json').write_text(json.dumps(revision, indent=2, sort_keys=True) + '\n')
        recorded_distributions = parameterizations.distributions(mapping_candidate)
        if recorded_distributions is not None and (inventory.get('pairs') or {}).get('files'):
            # The store's revision directory holds the histograms and is immutable (its files are named in the run's
            # `inputs` record), so stage 5 is pointed at it instead of at a farm of links inside the run. A revision
            # with none of the pairwise family is left pointing at stage 3, where the run's own inventory carries the
            # reason stage 5 will record when it skips.
            reference_directory = str(recorded_distributions['directory'])
    (run_dir / '5_assessment/references.txt').write_text(reference_directory + '\n')
    sim = run_dir / '4_CG_sim'
    (sim / 'inputs').mkdir(parents=True, exist_ok=True)
    # The MDPs are rendered from reviewed profiles at the run's own numbers; the installed Martini ITPs and the water box
    # are not copied at all: the topology includes the ITPs by a path relative to itself, and `cg_simulation.sh` reads
    # the published water box where it lives.
    write_mdp('cg-minimization-v1', sim / 'inputs/minimization.mdp')
    (sim / 'system_EMPTY.top').write_text(
        f'#include "{martini3.include(MARTINI_FF, sim)}"\n'
        f'#include "{martini3.include(MARTINI_SOLVENTS, sim)}"\n'
        f'#include "{names.final_itp}"\n[ system ]\n{names.residue_name} draft in pure water\n'
        f'[ molecules ]\n{names.residue_name} 1\n')
    sasa = run_dir / '6_SASA'
    (sasa / 'AA').mkdir(); (sasa / 'CG').mkdir()
    (sasa / 'CG/vdwradii.dat').write_text(''.join(f'{names.residue_name} B{i:02d} { {"R":0.264,"S":0.230,"T":0.191}[b["size"]]}\n' for i,b in enumerate(data['beads'],1)))

    settings = normalize_settings(settings, profile)
    # The device this run names has to be one this host reports: refused at prepare, rather than by mdrun three
    # stages in. A host that reports no devices is not a refusal (`devices.require`).
    devices.require(settings['mdrun_gpu'])
    write_mdp('cg-equilibration-v1', sim / 'inputs/eq.mdp', mdp_values(settings, 'cg-equilibration-v1'))
    write_mdp('cg-production-v1', sim / 'inputs/md.mdp', mdp_values(settings, 'cg-production-v1'))
    # The run's numbers travel as data and as `RUN_SETTING_*` environment variables, so the repository scripts are one
    # file for every run: stage 3 reads `RUN_SETTING_TEMPERATURE_K`, stage 5 reads `references.txt`, and stage 6 reads
    # `RUN_SETTING_SASA_PROBE_NM`. Nothing is stamped into a copy.

    manifest = run_dir / 'manifest.json'
    metadata = json.loads(manifest.read_text()) if manifest.exists() else {'stages': []}
    if mapping_candidate is not None:
        metadata['mapping_candidate'] = mapping_candidate
        metadata['mapping_sha256'] = hashlib.sha256(json.dumps(mapping_candidate, sort_keys=True).encode()).hexdigest()
    metadata.update(profile=profile, scientifically_validated=False, settings=settings, stage_plan=[[name, relative] for name, relative in stage_plan],
                    mdp_profiles=dict(MDP_PROFILES))
    metadata['cg_names'] = {'residue_name': names.residue_name, 'initial_itp': names.initial_itp, 'final_itp': names.final_itp}
    # Which of the two stage-3 shapes this run has, recorded as one fact the stage contract and every
    # later reader resolve the run's own plan from (D5). `fitted` is the run type's old behaviour and
    # stays the answer for a mapping with no parameterization: the run fits in stage 3 and this says so.
    metadata['bonded'] = {
        'consumes_parameterization': revision is not None,
        'fitted': revision is None,
        'revision': (revision or {}).get('revision'),
        'engine': (revision or {}).get('engine'),
        'torsion_model': ((revision or {}).get('options') or {}).get('torsion_model'),
        'terms': parameterizations.total_terms(revision) if revision else None,
        'revision_sha256': parameterizations.revision_sha256(revision) if revision else None,
        'aa_reference': (revision or {}).get('aa_reference'),
        # The baseline stage 5 scores against, read from the revision's record: named here so a reader can see which
        # histograms a run's numbers were measured against without opening the store.
        'reference_distributions': [entry['name'] for entry in (recorded or [])],
        # Of those, the pairwise family the score matrix is built from: one file per bead pair, beside the count a
        # molecule of this many beads needs. The count is what says whether stage 5 can score at all, so it is recorded
        # rather than left to be counted out of a 68-name list. A run that fits records `None` here: nothing was staged,
        # and its own stage 3 is what measures them.
        'reference_pairs': ((inventory or {}).get('pairs') if revision is not None else None),
        # Whether this run's assessment can score anything. Recorded so a reader knows before the simulation ends
        # that stage 5 will be `skipped`, and why -- D6a's deferred BARTENDER analysis is one reason it happens, a
        # revision whose record carries no pairwise histograms is the other. A run that fits leaves its own histograms
        # in stage 3 (`ff_inter -dists -dist-matrix` measures them while fitting), so it is scored however little the
        # mapping recorded; a consuming run is scored only if the model brought a scorable baseline.
        'assessment': ({'scored': bool(((inventory or {}).get('pairs') or {}).get('files')), 'reason': unscored}
                       if revision is not None else {'scored': True, 'reason': None}),
        'source': ("the mapping's current parameterization"
                   if revision else 'fitted by this run, in stage 3, from the AA reference it consumes'),
    }
    if shared_reference:
        metadata.update(shared_reference=shared_reference, reference_reused=True, reference_run_id=shared_reference['source_run_id'])
    # The force field is the *atomistic* half's and is not copied into this run: the AA reference stage is always
    # reused from the run that built it, so nothing here reads this tree. It is still recorded -- the version a run
    # was prepared under is provenance -- and the CG half's installed files are named in `input_references` below.
    metadata['force_field'] = {'name': FORCE_FIELD.name, 'source': str(FORCE_FIELD.relative_to(ROOT)),
        'sha256': {str(p.relative_to(FORCE_FIELD)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(FORCE_FIELD.rglob('*')) if p.is_file()}}
    # The inputs that already existed when prepare ran, for `finish_prepared_run` to write as the manifest's `inputs`
    # record. It is a channel between the two halves of prepare, not a manifest key: `_protocol_prepare` pops it.
    metadata['input_references'] = references
    metadata['inputs_sha256'] = {str(p.relative_to(run_dir)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(run_dir.rglob('*')) if p.is_file() and p != manifest}
    metadata['environment'] = recorded_environment()
    # What this run is, recorded for every AA-to-CG run rather than only the `draft-smoke` profile: the mapping and
    # the fitted terms are the run type's own (D1), so the two caveats belong to the run type. `analysis_topology`
    # names how a reader may read the run at all -- MDAnalysis 2.10 cannot read this GROMACS build's TPR.
    metadata['analysis_topology'] = 'GRO atom/residue order + explicit ITP interactions; MDAnalysis 2.10 does not support GROMACS 2026 TPR 138. Trajectories made whole with gmx trjconv.'
    metadata['limitations'] = ['Draft mapping and nonbonded bead types, not scientifically validated', f'AA production {settings["aa_production_ps"]} ps; CG production {settings["cg_production_ps"]} ps; pure water', 'Bonded parameters fit to the recorded AA reference; no convergence or thermodynamic validation']
    if revision is not None:
        # The consequence of consuming rather than fitting, said in the run's own words: the atomistic reference
        # distributions stage 5 compares against are a fit's output, and this stage produced none of its own -- the ones
        # it will score against came from the revision's record, and the run says how many or says there are none.
        # Stated here rather than discovered as a stage that failed or, worse, as a matrix of 0.00 that reads perfect.
        pairs = ((inventory or {}).get('pairs') or {})
        staged = (f"its record carries {pairs.get('files')} pairwise distance histograms, read from the store"
                  if pairs.get('files') else
                  'its record carries no pairwise distance histograms, so the assessment stage has no atomistic '
                  'reference to score against and records `skipped`')
        metadata['limitations'].append(
            "Stage 3 used the model's parameterization (revision "
            f"{revision['revision']}) and fitted nothing while writing the terms: "
            f'{staged}.')
        linked = (revision.get('aa_reference') or {}).get('run_id')
        if linked and linked != shared_reference['source_run_id']:
            metadata['limitations'].append(
                f"The model's parameterization was fitted against AA reference {linked}, and this run "
                f"consumes {shared_reference['source_run_id']}: the fit and the run do not share a reference.")
    metadata['tools'] = tool_metadata()
    files.atomic_json(manifest, metadata)


def tool_metadata():
    probe = ['-c', 'import fast_forward,MDAnalysis,hashlib,pathlib; import fast_forward.interaction_fit as fitter; print("Fast_Forward",fast_forward.__version__); print("MDAnalysis",MDAnalysis.__version__); print("Fitter",fitter.__file__,hashlib.sha256(pathlib.Path(fitter.__file__).read_bytes()).hexdigest())']
    result = tools.record_versions('gmx', ('python', probe), env=environment())
    for exe in ('ff_inter','ff_assess'):
        executable = tools.tool_path(exe)
        if executable: result[exe] = {'path':executable,'sha256':files.sha256(executable)}
    # Which source produced those entry points: their version output cannot say.
    provenance = tools.declared_provenance()
    if provenance:
        result['fast_forward_source'] = provenance
    return result


#: The tools a CG readiness checks, in the order its checks are written: the order a stage calls
#: them in, which is what the panel shows and what a reader compares between two machines.
READINESS_TOOLS = ('gmx', 'ff_inter', 'ff_assess')


def _probe_tools(names):
    """`(executable, ready, detail)` for each name, in the order named, measured at the same time.

    One probe is a subprocess that imports a whole scientific stack: measured 2026-10-20, the three
    a CG readiness asks about took 4.8-5.1 s one after another and 1.9-2.0 s together, and readiness
    is asked of a route while somebody watches a "checking requirements" line. The wait is therefore
    the slowest tool rather than the sum of them. `pool.map` keeps the order, which is what keeps
    the checks list -- and so the panel -- reading `gmx`, `ff_inter`, `ff_assess`.
    """
    resolved = [(name, tools.tool_path(name)) for name in names]

    def ask(resolved_tool):
        executable = resolved_tool[1]
        # A tool that does not resolve is an answer, not a skipped check: the same sentence a
        # sequential probe gave, so a caller cannot tell which route produced it.
        return probe_tool(executable) if executable else (False, 'Executable not found')

    with ThreadPoolExecutor(max_workers=max(len(resolved), 1),
                            thread_name_prefix='readiness-probe') as pool:
        answers = list(pool.map(ask, resolved))
    return [(executable, ready, detail)
            for (_, executable), (ready, detail) in zip(resolved, answers)]


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
                   'detail': 'Referenced from the repository by path and digest'})
    for tool, (executable, ok, detail) in zip(READINESS_TOOLS, _probe_tools(READINESS_TOOLS)):
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
    return stage_contract(names, parameterized=consumes_parameterization(metadata))


def _protocol_stages(metadata):
    """Resolve the named stage declarations for the metadata's molecule."""
    snapshot = metadata.get('molecule_snapshot')
    names = CGNames.for_snapshot(snapshot) if snapshot else CGNames.ddm_defaults()
    return tuple(stage.resolve(names.env())
                 for stage in stage_definitions(consumes_parameterization(metadata)))


def _protocol_readiness(metadata):
    molecule_id = metadata.get('molecule_id')
    if not molecule_id:
        return protocol.blocked('molecule_id is required to check an AA to CG run')
    # This adapter *is* the AA-CG run type, so its own profile is the fallback rather than `standard`: the panel
    # offers no profile choice for this run type and sends none, and a `standard` fallback silently skipped the
    # mapping check below (`if profile in ('draft-smoke','draft-smoke-reference')`) while asking the readiness list
    # about a profile no AA-CG run has ever run under.
    ready = readiness(molecule_id, metadata.get('method') or 'gromacs',
                      metadata.get('profile') or AA_CG_PROFILE,
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
    # D5's read-only bonded step, published as the run type's own answer rather than assembled on the
    # panel: the model either carries a parameterization this run will use and not re-fit, or it
    # carries none and the run fits it in stage 3 and records that it did. A top-level key and not a
    # `checks` entry, because neither state is a prerequisite -- but a record this run *cannot read* is
    # one, because `prepare` would refuse it and saying "the run will fit it" would be a promise the
    # run cannot keep.
    state = _parameterization_state(metadata)
    ready['parameterization'] = state
    if state.get('error'):
        ready.setdefault('blockers', []).append('CG parameterization: ' + state['error'])
    ready['ready'] = ready.get('ready', False) and not ready.get('blockers')
    return ready


def _parameterization_state(metadata) -> dict:
    """What the run panel prints about the model's bonded terms, in the shape it prints them in.

    Both sentences are the run type's: the panel renders them rather than composing them, so the
    promise a run makes about fitting is stated in one place, next to the code that keeps it.
    """
    mapping = metadata.get('mapping_candidate')
    if not isinstance(mapping, dict):
        return {'parameterized': False, 'revision': None, 'engine': None, 'engine_label': None,
                'terms': None, 'torsion_model': None, 'checks': [], 'aa_reference': None,
                'revision_sha256': None, 'statement': 'No mapping is selected, so there is nothing to fit.'}
    try:
        state = parameterizations.summary(mapping)
    except (OSError, ValueError) as exc:
        return {'parameterized': False, 'revision': None, 'engine': None, 'engine_label': None,
                'terms': None, 'torsion_model': None, 'checks': [], 'aa_reference': None,
                'revision_sha256': None, 'error': str(exc),
                'statement': f"This model's parameterization cannot be read: {exc}"}
    revision = parameterizations.current(mapping)
    state['statement'] = (f'this model is parameterized -- {parameterizations.describe(revision)}; the run '
                          'uses it and does not re-fit' if revision is not None else
                          'this model carries no parameterization -- the run will fit it in stage 3 and record '
                          'that it did')
    return state


def run_settings(settings):
    """The settings an AA-to-CG run keeps for its own build: its CG dialect and its own execution keys.

    The CG dialect is its own vocabulary. A key from the AA half that this run type does not use is dropped rather
    than refused, because those settings describe the *reference* it consumes instead of the run it builds --
    `normalize_settings` would otherwise take them, since it accepts both dialects by design.

    `mdrun_gpu`, `mdrun_ntomp` and `mdrun_ranks` are the exceptions on purpose: they name how *this run's* mdrun
    executes -- the device and the CPU budget -- on the atomistic half and the coarse-grained half alike, so they are
    properties of the run rather than of the reference. Dropping them here left a run recording and executing the
    defaults while the panel showed the numbers that had been posted: an AA-to-CG form asking for 16 threads ran 8.
    The reference's own recorded budget stays provenance -- what it cost -- not an instruction to this run.
    """
    return {key: value for key, value in (settings or {}).items()
            if key in SETTING_SPECS or key in RUN_EXECUTION_SETTINGS}


def _protocol_prepare(run_dir, metadata):
    """Prepare an AA-to-CG run the way every other run type is prepared: fill `stages/`, then finish the run.

    This used to be two steps in two modules -- the coordinator assembled the arguments, and `workflow.prepare_run`
    built the stage directory, copied it to `inputs/` and wrote the manifest. Both halves live here now, which is what
    makes `adapter_for('aa_cg').prepare(run_dir, metadata)` mean the same thing as it does for every other run type:
    a run directory in, a prepared run out.
    """
    keys = ('structure', 'detergent', 'profile', 'settings', 'mapping_candidate',
            'shared_reference', 'reference_root', 'molecule_snapshot', 'molecule_root')
    values = {key: metadata[key] for key in keys if key in metadata}
    # The coordinator applied this filter before calling the old entry point; it belongs with the run type that
    # declares the dialect.
    if values.get('settings'):
        values['settings'] = run_settings(values['settings'])
    stages = Path(run_dir) / 'stages'
    stages.mkdir(parents=True, exist_ok=True)
    prepare(stages, **values)
    # `prepare` leaves its record beside the stages, including the tool versions it used; the run's manifest is written
    # from that record, and the record itself is not a stage input. The inputs that already existed are named there for
    # this call: `finish_prepared_run` writes them as the manifest's `inputs` record and mirrors the generated data into
    # `inputs/`, which is what makes the run layout-3.
    record = json.loads((stages / 'manifest.json').read_text())
    references = record.pop('input_references', None)
    # The code this run executes, in one record: the repository script of every stage, and every project module those
    # scripts import. The executor re-hashes each file before its stage starts, so a helper changed under a prepared
    # run refuses the stage instead of silently running code the run did not record.
    scripts = {stage.name: stage.script
               for stage in stage_definitions(consumes_parameterization(record)) if stage.script}
    return protocol.finish_prepared_run(run_dir, stages, metadata=record, tools=record.get('tools', {}),
                                        plan=protocol.plan_pairs(record),
                                        environment=record.get('environment'), references=references,
                                        scripts=scripts, modules=MODULES)


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
