"""The protein-detergent complex pipeline. `micelle/` owns the science; this adapter owns the stages.

The catalogue, the stage contract and every stage's script belong here rather than to the route layer. Every stage
runs a repository script under `execution/scripts/` -- recorded in the manifest by path and digest, never copied into
the run -- and the run itself holds only what `prepare` synthesized, in `inputs/`, beside `stages/`.
"""
import json
import re
import shutil
from pathlib import Path

from dashboard import files, martini3, paths
from dashboard.execution import devices, protocol, run_inputs, tools
from dashboard.execution.environment import TUTORIAL_TEMPLATE
from dashboard.execution.mdp import PROFILES, write_mdp
from dashboard.execution.settings import normalize
from dashboard.execution.stages import Stage

from detergent_pdc.execution.adapters import pdc_import, pdc_preparation

# The coarse-grained parameters a pdc topology has to carry, from the published Martini 3 lipid set: the bead types
# (which the detergent's own beads need defined), the solvents file that defines water as `W`, and the ions file that
# defines `NA` and `CL`. Without them `grompp` refuses a solvated system with an undefined molecule type -- which is
# exactly how the first run that reached solvation failed. Every run reads them from the workspace's installed set
# (`dashboard.martini3`), never from a copy in its own stage directories, and the set's commit and DOI are recorded in
# every manifest.
FORCEFIELD_FILES = martini3.REQUIRED
FORCEFIELD_SOURCE = martini3.SOURCE

# The two files the system-preparation stage reads and writes. The adapter owns their names because the stage
# script, the entry point and the tests all have to agree on them.
SETTINGS_NAME = 'pdc-settings.json'
REPORT_NAME = 'prepare_report.json'
# The detergent's derived coarse-grained model: the topology the system includes, and the bead geometry together
# with the provenance of its bonded terms.
DETERGENT_TOPOLOGY = 'detergent_CG.itp'
DETERGENT_GEOMETRY = 'detergent_CG.json'
# Where the protein's own `.itp`s live: martinize2's output directory, which is where its `protein.top` includes them
# from by bare name. `system.top` includes them as `../02_system/cg/<name>.itp` (`pdc_build.write_topologies`) -- the
# build stage is the one directory that carries the tree, and a sibling stage names it from there, so this whole
# directory is a declared input of every leg rather than a copy in each one: martinize2 emits one molecule per chain
# (one for 1AT9's chain A, two for 4IAR's) and no static list can be right for both.
PROTEIN_TOPOLOGY_DIRECTORY = 'cg'

# The run's two trees: `stages/` holds one directory per stage that will run, and `inputs/` holds the data `prepare`
# synthesized plus the record of what the run reads. A directory spelled from a stage is therefore `../NN_*` for the
# phase before it and `../../inputs` for generated data.
STAGES_DIRECTORY = 'stages'
INPUTS_DIRECTORY = run_inputs.INPUTS_DIRECTORY

DEFAULTS = {'salt_molar': 0.15, 'aggregation_number': 150, 'assessment_ns': 100, 'extension_ns': 900,
            'selection_threshold_fraction': 0.10, 'attempts_max': 3, 'box_margin_nm': 2.0,
            'initial_z_nm': 6.0, 'contact_nm': 0.6,
            'minimisation_steps': 200000, 'nvt_ps': 500, 'npt_ps': 4500,
            # The CG production legs' own numbers. They are written from `pdc-assessment-v1`/`pdc-extension-v1`,
            # whose reviewed profile leaves exactly these to the run; the equilibration and restart profiles keep
            # their own reviewed values, so an untouched run is the physics the templates stated.
            'nstlog': 100, 'nstenergy': 100, 'nstxtcout': 100, 'xtc_precision': 1000, 'nstcomm': 100,
            'nstlist': 40, 'verlet_buffer_tolerance': 0.005, 'rlist': 1.35, 'rcoulomb': 1.1, 'rvdw': 1.1,
            'ref_t': 300, 'tau_t': 1.0, 'ref_p': 1.0, 'tau_p': 12.0, 'compressibility': 4.5e-5,
            'mdrun_ntomp': 8, 'mdrun_ranks': 1, 'mdrun_nb': 'auto',
            # Which generator places the detergents. A string, not a number, so it has no SETTING_SPECS bound and is
            # validated in `validate_payload` instead; its presence here is what lets a caller's choice survive the
            # settings filter and reach the build. `lattice` is the default so no existing run's placement moves.
            'placement_mode': 'lattice',
            # Which subunits go into the simulation, and whether the back-map runs. `protein_chains` is `None` for
            # every chain -- so an existing caller, which never sends it, keeps the whole file -- and a list of ids
            # when a caller chooses; `backmap` is `True` so nothing existing stops comparing its CG system with the
            # atomistic one it came from. Both are choices rather than numbers and are validated in
            # `validate_payload` (shape) and `prepare` (against the file).
            #
            # `prepare_protein` is the plan's step 1 and it is **on** by default: a deposited file whose side chains are
            # incomplete coarse-grains into beads with no position, and the placement then refuses the whole build, so
            # the run that skips the step is the exception rather than the rule. A caller that has never heard of the
            # setting gets its protein rebuilt and protonated by PDB2PQR before martinize2 reads it.
            #
            # "On" cannot mean "refuses when the tool is absent", though: a default that no machine is obliged to
            # satisfy would block every run on a box without `pdb2pqr`. The stage therefore skips by name when the
            # tool is not resolvable, and refuses only when a tool it did resolve could not prepare the structure.
            'protein_chains': None, 'backmap': True, 'prepare_protein': True,
            # The removal/assessment pipeline is a choice: on by default so every existing run keeps its chain; off
            # means one plain CG MD leg after NPT, no assessment/removal/extension/final assessment.
            'remove_out_of_micelle': True,
            # The device this run's mdrun uses. Here rather than in the AA half's vocabulary because a pdc run has
            # no AA half and this is the only table its own normalizer reads; the value is one index, and the
            # default keeps every existing run's command byte-identical.
            'mdrun_gpu': 0}
_PROTEIN_LIMIT = 50
# Values a spec allows as a fraction but that the builders use as counts or seeds.
# Canonical settings that are counts, not sizes: a supplied value is stored as an `int`, so the run's record says `120`
# rather than `120.0`. `aggregation_number` was missing here while `validate_payload` refused anything that was not an
# `int`, so the normalizer turned every supplied aggregation number into a float and the validator then rejected the
# record the normalizer had just written -- no pdc build with an aggregation number could get past `prepare`.
_INTEGRAL = ('seed', 'minimisation_steps', 'mdrun_gpu', 'aggregation_number', 'attempts_max',
             'nstlog', 'nstenergy', 'nstxtcout', 'xtc_precision', 'nstcomm', 'nstlist',
             'mdrun_ntomp', 'mdrun_ranks')
# The refusal each count carries, so a fractional value is named rather than floored. `seed` has a spec and no
# default: a run that names none lets the builder choose, so an absent key stays absent.
_INTEGRAL_MESSAGES = {key: f'{key} must be an integer' for key in _INTEGRAL}

# One shape across every run type: (label, lo, hi). Numbers only; a choice would need the registry, so it is
# validated in validate_payload where the templates are actually known.
SETTING_SPECS = {
    'pdc_assessment_ns': ('CG assessment duration (ns)', 1, 100000),
    'pdc_extension_ns': ('CG extension duration (ns)', 1, 1000000),
    'pdc_seed': ('Random seed', 1, 2147483646),
    'aggregation_number': ('Detergent aggregation number', 1, 1000),
    'salt_molar': ('Salt concentration (M)', 0.0, 5.0),
    'box_margin_nm': ('Box margin (nm)', 0.5, 10.0),
    'initial_z_nm': ('Initial z box (nm)', 1.0, 50.0),
    'contact_nm': ('Micelle contact distance (nm)', 0.1, 2.0),
    'selection_threshold_fraction': ('Removal threshold (fraction)', 0.0, 1.0),
    # The CG production legs' output cadence, neighbour search and ensemble targets. The reviewed profiles leave
    # these to the run; the equilibration and restart profiles keep their own values.
    'nstlog': ('Log interval (steps)', 1, 1000000),
    'nstenergy': ('Energy interval (steps)', 1, 1000000),
    'nstxtcout': ('Trajectory interval (steps)', 1, 1000000),
    'xtc_precision': ('Trajectory precision', 1, 1000000),
    'nstcomm': ('Centre-of-mass removal (steps)', 1, 1000000),
    'nstlist': ('Neighbour list rebuild (steps)', 1, 10000),
    'verlet_buffer_tolerance': ('Verlet buffer tolerance', 0.0, 0.1),
    'rlist': ('Neighbour cut-off (nm)', 0.1, 5.0),
    'rcoulomb': ('Coulomb cut-off (nm)', 0.1, 5.0),
    'rvdw': ('van der Waals cut-off (nm)', 0.1, 5.0),
    'ref_t': ('Temperature (K)', 200.0, 500.0),
    'tau_t': ('Thermostat coupling (ps)', 0.01, 100.0),
    'ref_p': ('Pressure (bar)', 0.1, 100.0),
    'tau_p': ('Barostat coupling (ps)', 0.1, 100.0),
    'compressibility': ('Compressibility (bar^-1)', 0.0, 1.0),
    'mdrun_ntomp': ('mdrun OpenMP threads per rank', 1, 72),
    'mdrun_ranks': ('mdrun MPI ranks', 1, 72),
    # The three equilibration legs, in steps of steepest descent and picoseconds of MD. `0` is a request for none of
    # that leg rather than a very short one: `prepare` writes no directory and no script for it, and the manifest
    # records it skipped with its reason.
    'pdc_minimisation_steps': ('CG minimisation steps', 0, 1000000),
    'pdc_nvt_ps': ('CG NVT equilibration (ps)', 0, 1000000),
    'pdc_npt_ps': ('CG NPT equilibration (ps)', 0, 1000000),
    # An index into the devices the host reports, and the check that matters is against those, at prepare.
    'mdrun_gpu': ('mdrun GPU device', 0, 64),
}

# What each equilibration leg's shared script has to know: the mdp it runs, the phase it copies its system from, the
# reviewed profile that mdp is written from, and the setting that turns into steps. Keyed by the stage's own name, so
# the declaration in `STAGES`, the generated `inputs/<stage>.json` record and the script cannot name two different legs.
LEGS = {
    'Energy minimisation': {
        'key': 'minimisation', 'mdp': 'minimisation.mdp', 'profile': 'pdc-minimisation-v1',
        'setting': 'minimisation_steps', 'solvate': True,
        'from': '02_system',
        'purpose': 'solvate the built system, add its ions, and relax it before any dynamics',
        'reason': 'the run asks for 0 minimisation steps, so this stage has nothing to do'},
    'NVT equilibration': {
        'key': 'nvt', 'mdp': 'nvt.mdp', 'profile': 'pdc-nvt-v1', 'setting': 'nvt_ps', 'seed_velocities': True,
        'from': '03_minimisation',
        'purpose': 'hold the system at fixed volume while the thermostat brings it to 300 K',
        'reason': 'the run asks for a 0 ps NVT equilibration, so this stage has nothing to do'},
    'NPT equilibration': {
        'key': 'npt', 'mdp': 'npt.mdp', 'profile': 'pdc-npt-v1', 'setting': 'npt_ps',
        'checkpoint': '../04_nvt/system.cpt',
        'from': '04_nvt',
        'purpose': 'hold the system at 1 bar so the box reaches its density before production',
        'reason': 'the run asks for a 0 ps NPT equilibration, so this stage has nothing to do'},
}
# The legs' reviewed physics is `dashboard/execution/mdp/profiles.py:PDC_LEG_PROFILES`, one profile per leg, keyed in
# `LEGS` by the mdp file name the stage reads.

# The protocol's own steps, numbered in execution order, each in its own directory under `stages/` and each running
# one repository script of this workflow's own. The directory names are the layout (`01_prepare` ... `10_backmap`);
# the human names are the panel's and the manifest's and do not move.
STAGES = (
    # The plan's step 1, and the one step in front of everything else: a structure whose deposited file is missing
    # side-chain atoms coarse-grains into beads with no position, and the placement refuses the whole build for it.
    # PDB2PQR rebuilds them and protonates the protein, and the structure it writes is what `pdc_build` hands to
    # martinize2. Optional: a run that does not ask for it gets no directory at all and the manifest records the skip.
    Stage('Protein preparation', '01_prepare/pdc_prepare.sh',
          ('../../inputs/' + SETTINGS_NAME,),
          (pdc_preparation.PREPARED_NAME, pdc_preparation.RECORD_NAME),
          script='dashboard/execution/scripts/pdc_prepare.sh'),
    # The build reads its own generated inputs from `inputs/` and writes the system the legs run; the protein and the
    # force field are referenced in place and verified through the run's input record.
    Stage('System preparation', '02_system/pdc_system.sh',
          ('../../inputs/' + SETTINGS_NAME, '../../inputs/system_EMPTY.top'),
          ('system.gro', 'system.top', REPORT_NAME, DETERGENT_TOPOLOGY, f'{PROTEIN_TOPOLOGY_DIRECTORY}/'),
          script='dashboard/execution/scripts/pdc_system.sh'),
    # Change 2 of the new-run panel plan: the built system used to go straight into 100 ns of CG MD, and now the
    # standard sequence for a CG system built from a mapping goes in front of it -- minimisation, then NVT, then NPT.
    # A leg the run asks none of gets no directory, and the manifest records it skipped with its reason.
    Stage('Energy minimisation', '03_minimisation/pdc_leg.sh',
          ('../../inputs/03_minimisation.json', '../../inputs/minimisation.mdp', '../../inputs/ions.mdp',
           '../../inputs/water.gro', '../02_system/system.gro', '../02_system/system.top',
           f'../02_system/{PROTEIN_TOPOLOGY_DIRECTORY}/'),
          ('system.tpr', 'system.gro', 'system.top', 'system.edr', 'system.log', 'solvation.json'),
          script='dashboard/execution/scripts/pdc_leg.sh'),
    Stage('NVT equilibration', '04_nvt/pdc_leg.sh',
          ('../../inputs/04_nvt.json', '../../inputs/nvt.mdp', '../03_minimisation/system.gro',
           '../03_minimisation/system.top', f'../02_system/{PROTEIN_TOPOLOGY_DIRECTORY}/'),
          ('system.tpr', 'system.gro', 'system.top', 'system.edr', 'system.log', 'system.cpt', 'system.xtc'),
          script='dashboard/execution/scripts/pdc_leg.sh'),
    Stage('NPT equilibration', '05_npt/pdc_leg.sh',
          ('../../inputs/05_npt.json', '../../inputs/npt.mdp', '../04_nvt/system.gro', '../04_nvt/system.top',
           f'../02_system/{PROTEIN_TOPOLOGY_DIRECTORY}/'),
          ('system.tpr', 'system.gro', 'system.top', 'system.edr', 'system.log', 'system.cpt', 'system.xtc'),
          script='dashboard/execution/scripts/pdc_leg.sh'),
    # The counterpart of change 2: this leg is production only, and it samples the system the NPT leg left.
    Stage('CG assessment MD', '06_assessment/pdc_assessment.sh',
          ('../../inputs/assessment.mdp', '../05_npt/system.gro', '../05_npt/system.top',
           f'../02_system/{PROTEIN_TOPOLOGY_DIRECTORY}/'),
          ('prod/run.gro', 'prod/run.tpr', 'prod/run.xtc', 'prod/run.cpt', 'system.top'),
          script='dashboard/execution/scripts/pdc_assessment.sh'),
    # Judges the production phase that just ran: its script copies `prod/run.gro` from `06_assessment`, because a
    # stage reads the phase before it immutably. A run with out-of-micelle removal off has no decision to make and
    # gets no directory here.
    Stage('Micelle assessment', '07_micelle_assessment/pdc_assess.sh',
          ('../../inputs/' + SETTINGS_NAME, '../06_assessment/prod/run.gro'),
          ('assessment.json', 'kept.gro', 'removed.json'),
          script='dashboard/execution/scripts/pdc_assess.sh'),
    # The extension's `system.top` is the production phase's, so the protein tree it includes is the build stage's --
    # the one directory in the run that carries it; its removal decision is the micelle assessment's.
    Stage('CG extension MD', '08_extension/pdc_extension.sh',
          ('../../inputs/' + SETTINGS_NAME, '../../inputs/extension.mdp', '../../inputs/extension.ps',
           '../../inputs/minimization.mdp', '../../inputs/equilibration.mdp', '../../inputs/ions.mdp',
           '../../inputs/water.gro', '../06_assessment/prod/run.tpr', '../06_assessment/prod/run.cpt',
           '../07_micelle_assessment/removed.json', '../07_micelle_assessment/kept.gro',
           '../06_assessment/system.top', f'../02_system/{PROTEIN_TOPOLOGY_DIRECTORY}/'),
          ('prod/run.gro', 'prod/run.xtc'),
          script='dashboard/execution/scripts/pdc_extension.sh'),
    Stage('Final assessment', '09_final_assessment/pdc_assess.sh',
          ('../../inputs/' + SETTINGS_NAME, '../08_extension/prod/run.gro'),
          ('assessment.json',),
          script='dashboard/execution/scripts/pdc_assess.sh'),
    # The converted complex carries the protein's own net charge -- pdb2gmx's protonation states against the ions the CG
    # system carried -- so the stage's last act is to neutralise it, and `neutralisation.json` is what says it did: the
    # charges before and after, and the ions it took. The 4iar/DDM complex came out at -5, which CG2AT2's own steering
    # leg refused to simulate ("Ewald electrostatics in a system with net charge").
    Stage('Back-mapping (CG2AT2)', '10_backmap/pdc_backmap.sh',
          # The assessment leg's structure is always there; `pdc_backmap.py` reads the extension's final state
          # instead whenever removal ran, so the pair is not declared as an input no skip path could satisfy.
          ('../../inputs/' + SETTINGS_NAME, '../06_assessment/prod/run.gro'),
          ('cg2at_input.gro', 'FINAL/FINAL/final_cg2at_de_novo.pdb', 'FINAL/FINAL/final_cg2at_neutral.pdb',
           'backmap_inputs.json', 'backmap.log', 'neutralisation.json'),
          script='dashboard/execution/scripts/pdc_backmap.sh'),
)


def stage_by_name(name: str) -> Stage:
    """One stage of this protocol, by name.

    The plan's positions are data and they move: this module reached the assessment and extension stages as
    `STAGES[1]` and `STAGES[3]` until three equilibration legs landed in front of them and moved every index. A
    caller that knows *which* stage it means should say so rather than count.
    """
    for stage in STAGES:
        if stage.name == name:
            return stage
    raise KeyError(f'this protocol has no stage named {name!r}')


def normalize_chains(value):
    """A chain selection as a list of ids, or `None` for every chain.

    Two spellings reach here: the panel sends a list, and a query or a form may send `"A,B"`. An empty selection, or
    none at all, is `None` -- every chain -- which is what keeps an existing caller's build unchanged. Anything else
    is refused rather than coerced: a number or a dict is not a chain, and a dropped one would build a system the
    caller did not ask for.
    """
    if value is None:
        return None
    if isinstance(value, str):
        value = [part.strip() for part in value.split(',')]
    if not isinstance(value, (list, tuple)):
        raise ValueError(f'a protein chain selection must be a list of chain ids, not {value!r}')
    chains = [str(chain).strip() for chain in value]
    if not all(chains):
        raise ValueError('a protein chain selection cannot name an empty chain id')
    return chains or None


def protein_chains_of(path):
    """The chain ids a protein file names, read through the importer's own reader.

    One reader for the catalogue, the estimate and the build, so no two of them can disagree about what a file's
    chains are.
    """
    return pdc_import.structure_chains(Path(path).read_text(errors='replace'))


def validate_chains(protein_path, requested):
    """The validated selection, or a refusal naming every chain the file does not have.

    A chain the file does not name is refused rather than dropped: a run built from the rest of the structure would
    look like the selection the reader made, and a trimer runnable as a monomer is exactly the case where the two
    must not be confused.
    """
    if not requested:
        return None
    available = protein_chains_of(protein_path)
    missing = [str(chain) for chain in requested if str(chain) not in set(available)]
    if missing:
        named = ', '.join(available) or 'none'
        raise ValueError(f'the protein {Path(protein_path).name} names no chain(s) {", ".join(missing)}; it names '
                         f'{named}')
    return [str(chain) for chain in requested]


def _count(value):
    """A whole number from a payload that may carry it as a float, or `None` if it is not one.

    A JSON number arrives as `int` when the panel sends `Number('120')`, but a record written before the normalizer kept
    counts integral carries `120.0`, and a value that came through a float is still the integer the builders want. A
    string is not: the payload states numbers, and `'120'` would reach an MDP as text.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def validate_payload(payload):
    """The choices a build must carry, checked where the protocol can see them.

    Numbers that also appear in SETTING_SPECS are range-checked there; this validates what they mean: a seed that
    is a positive integer rather than a float, an aggregation number that is a count rather than a size, and the two
    choices that are not numbers -- which generator places the detergents, which subunits go into the system, and
    whether the back-map runs. The chain list's ids are checked against the file in `prepare`, which is the first
    place the file is resolved.
    """
    if not isinstance(payload, dict):
        raise ValueError('pdc payload must be an object')
    # The builder's own policy: every build requires an integer seed, so a missing one is an error rather than a
    # default that would make two builds look comparable when they are not.
    seed = _count(payload.get('seed'))
    if seed is None or seed < 1:
        raise ValueError('pdc seed must be a positive integer')
    aggregation = _count(payload.get('aggregation_number', DEFAULTS['aggregation_number']))
    if aggregation is None or aggregation < 1:
        raise ValueError('pdc aggregation number must be a positive integer')
    try:
        salt = float(payload.get('salt_molar', DEFAULTS['salt_molar']))
    except (TypeError, ValueError) as exc:
        raise ValueError('pdc salt concentration must be a number') from exc
    if salt < 0:
        raise ValueError('pdc salt concentration cannot be negative')
    # Which generator places the detergents: a choice, so it is checked where the builder's own vocabulary is known
    # rather than in a numeric SETTING_SPECS bound. The import is lazy because `pdc_placement` pulls `micelle/__init__`
    # (the builder CLI, ~115 ms) and the route layer imports this module at startup; the placement module is otherwise
    # only reached through `prepare`.
    from detergent_pdc.execution.adapters.pdc_placement import DEFAULT_PLACEMENT_MODE, canonical_mode
    placement_mode = canonical_mode(payload.get('placement_mode', DEFAULT_PLACEMENT_MODE))
    backmap = payload.get('backmap', DEFAULTS['backmap'])
    if not isinstance(backmap, bool):
        raise ValueError(f'the pdc back-map setting must be true or false, not {backmap!r}')
    remove_out = payload.get('remove_out_of_micelle', DEFAULTS['remove_out_of_micelle'])
    if not isinstance(remove_out, bool):
        raise ValueError(f'the pdc removal setting must be true or false, not {remove_out!r}')
    # The plan's step 1 is a choice too, and it is checked here for the same reason: a string that means "yes" to a
    # caller would silently mean "no" to the builder.
    # The default is the adapter's -- on -- but a step *about a protein* cannot be on for a build that has none: an empty
    # micelle asked for protein preparation would be recorded as having prepared a structure that does not exist. So the
    # default is applied only where there is something to prepare, and an explicit request is still refused below.
    if 'prepare_protein' in payload:
        prepare_protein = payload['prepare_protein']
    else:
        prepare_protein = bool(DEFAULTS['prepare_protein'] and payload.get('protein'))
    if not isinstance(prepare_protein, bool):
        raise ValueError(f'the pdc protein-preparation setting must be true or false, not {prepare_protein!r}')
    chains = normalize_chains(payload.get('protein_chains'))
    return {'seed': seed, 'aggregation_number': aggregation, 'salt_molar': salt,
            'placement_mode': placement_mode, 'protein_chains': chains, 'backmap': backmap,
            'prepare_protein': prepare_protein, 'remove_out_of_micelle': remove_out,
            'template': payload.get('template'), 'protein': payload.get('protein') or None}


def catalog(project_root):
    """What this workflow can build, from the files on disk.

    A template is listed with the state of the files it names, because the shipped DDM template is a skeleton --
    its bead type is `registered-template` and its headgroup is zeroed -- and a panel that offered it without
    saying so would be promising a fitted detergent model that does not exist yet.
    """
    root = Path(project_root)
    return {'templates': _templates(root), 'proteins': _proteins(root), 'defaults': dict(DEFAULTS)}


def _templates(root):
    templates = []
    for path in sorted(root.glob('molecules/*/micelle_template.json')):
        try:
            record = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        molecule = path.parent.name
        missing = [name for name in ('coordinates', 'topology')
                   if not (path.parent / str(record.get(name, ''))).is_file()]
        beads = record.get('beads') or [{}]
        templates.append({'id': f'{molecule}:{record.get("residue") or molecule}',
                          'name': record.get('name') or molecule,
                          'residue': record.get('residue') or molecule,
                          'molecule': molecule,
                          'template': str(path.relative_to(root)),
                          'registered_type': str(beads[0].get('type') or ''),
                          'files_present': not missing,
                          'missing_files': missing,
                          'limitations': (['the template names files that are missing: ' + ', '.join(missing)]
                                          if missing else
                                          ['the template states one bead at its own origin and no bead shape: a build '
                                           'with a mapping takes its beads from the mapping, and a build without one '
                                           'places one centre per molecule'])})
    return templates


def _proteins(root):
    """Protein inputs a build can name, from the packaged molecules and from the workspace's own imports.

    Two roots now. The repository's own `molecules/*/` structures, and the local imports under the workspace -- which
    `.gitignore` ignores, so a downloaded structure can never be committed. Capped across both, because the
    references tree is large and nobody asked to see it in full, and every entry says which root answered: where a
    protein came from is a question the run's manifest has to be able to answer.
    """
    proteins = []
    for path in sorted(root.glob('molecules/*/*.pdb')):
        if len(proteins) >= _PROTEIN_LIMIT:
            break
        proteins.append(_protein_entry(path, root, 'packaged'))
    for path in sorted(paths.current().proteins.glob('*.pdb')):
        if len(proteins) >= _PROTEIN_LIMIT:
            break
        proteins.append(_protein_entry(path, root, 'imported'))
    return proteins


def _protein_entry(path, root, source):
    """One entry, with the same keys whatever the source.

    `half_thickness_nm` is present on every entry and `None` when the structure states nothing, because a key that
    sometimes exists is a key every reader has to guess about -- and "states nothing" is a real answer that has to be
    distinguishable from "nobody looked". `chains` is read the same way and at the same time -- the list the import
    recorded from the file's own coordinate records -- with one fallback: an imported sidecar written before chains
    were recorded, or a hand-made one, has the file read for them rather than the entry reporting none, because a
    picker that is dead for every existing import is worse than reading the file the estimate and the build read
    anyway. A packaged protein has no sidecar and stays unread, exactly as its thickness does; an empty list is a
    file that names no chain, which is stated rather than invented.
    """
    sidecar = pdc_import.read_sidecar(path) if source == 'imported' else None
    location = _portable(path, root)
    chains = (sidecar or {}).get('chains')
    if source == 'imported' and chains is None:
        try:
            chains = pdc_import.structure_chains(path.read_text(errors='replace'))
        except OSError:
            chains = None
    return {'id': location, 'name': path.stem, 'path': location, 'source': source,
            'half_thickness_nm': (sidecar or {}).get('half_thickness_nm'),
            'chains': chains}


def _portable(path, root):
    """The path as `prepare` wants it: project-relative when it sits under the repository, absolute when it does not.

    `prepare` resolves `root / protein`, and pathlib lets an absolute right-hand side win, so both spellings reach the
    same file. A configured workspace can live outside the repository, and a path with no relative spelling has to be
    listed rather than dropped for being unspellable.
    """
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def protein_frame(entry):
    """The membrane frame a catalogue entry states, or `None` when it states none.

    `None` rather than a default frame: a build with no stated membrane keeps the box and the placement it had, which
    is every packaged protein, every import whose file states nothing, and a protein-free build that has no entry at
    all. The `source` names the file that stated the thickness, so a frame in a manifest is traceable to what claimed
    it.

    The import sits inside the function the way this module's `registry` imports do: `micelle/__init__` pulls its own
    CLI, which measures about 115 ms, and the route layer imports this module at startup.
    """
    half = (entry or {}).get('half_thickness_nm')
    if half is None:
        return None
    from micelle.frame import frame_from_structure

    path = (entry or {}).get('path') or (entry or {}).get('name') or 'protein'
    return frame_from_structure(half, source=f'REMARK of {path}')


# The panel sends its own field names (`pdc_seed`), the adapter's settings use the builders' (`seed`); one small
# map keeps that translation out of the dispatch. The placement mode is a choice, so the panel's spelling of it
# translates here too and `validate_payload` is where it is checked.
_ALIASES = {'pdc_seed': 'seed', 'pdc_assessment_ns': 'assessment_ns', 'pdc_extension_ns': 'extension_ns',
            'pdc_placement_mode': 'placement_mode',
            'pdc_minimisation_steps': 'minimisation_steps', 'pdc_nvt_ps': 'nvt_ps', 'pdc_npt_ps': 'npt_ps'}

# The reviewed physics profile behind each MDP this adapter writes, keyed by the file name in `inputs/` that a stage
# reads. `prepare` records it in the manifest as `mdp_profiles`, so a reader can name the physics without opening the
# file, and a file is recorded only when `prepare` wrote it -- a skipped leg leaves no file to explain.
MDP_PROFILES = {
    'assessment.mdp': 'pdc-assessment-v1',
    'extension.mdp': 'pdc-extension-v1',
    'minimization.mdp': 'pdc-restart-minimization-v1',
    'equilibration.mdp': 'pdc-restart-equilibration-v1',
    'ions.mdp': 'pdc-ions-v1',
    **{leg['mdp']: leg['profile'] for leg in LEGS.values()},
}


def _profile_dt(profile: str) -> float:
    """The timestep a reviewed profile states, so a duration becomes steps in that file's own units."""
    return float(PROFILES[profile].settings['dt'])


#: The reviewed MDP names the run supplies, mapped to the settings key the panel sends. The production profiles
#: leave exactly these `None`; every other profile keeps its own values, so this table is the one place a run number
#: becomes an MDP option.
_MDP_RUN_SETTINGS = {
    'nstlog': 'nstlog', 'nstenergy': 'nstenergy', 'nstxtcout': 'nstxtcout', 'xtc-precision': 'xtc_precision',
    'nstcomm': 'nstcomm', 'nstlist': 'nstlist', 'verlet-buffer-tolerance': 'verlet_buffer_tolerance',
    'rlist': 'rlist', 'rcoulomb': 'rcoulomb', 'rvdw': 'rvdw',
    'ref-t': 'ref_t', 'tau-t': 'tau_t', 'ref-p': 'ref_p', 'tau-p': 'tau_p', 'compressibility': 'compressibility',
}


def _mdp_run_values(profile: str, settings: dict, extra: dict | None = None) -> dict:
    """The run's numbers for one profile, plus whatever the adapter computes (a step count, a seed).

    A profile's `None` entries are the numbers it leaves to the run. Every one is supplied here from the panel's
    settings, so the writer never renders a file with a missing value -- and a profile that owns a number keeps it.
    """
    values = dict(extra or {})
    for key, default in PROFILES[profile].settings.items():
        if default is None and key not in values:
            setting = _MDP_RUN_SETTINGS.get(key)
            if setting is not None and setting in settings:
                values[key] = settings[setting]
    return values


def _write_leg_record(inputs: Path, stage: Stage, leg: dict) -> None:
    """The numbers one equilibration leg's shared script reads: its mdp, the phase it copies from, and its checkpoint.

    Written per leg into `inputs/` and named for the leg's directory, because one script body serves all three and
    the stage directory it is run in is the only thing that says which leg it is.
    """
    record = {'label': stage.name, 'purpose': leg['purpose'], 'mdp': leg['mdp'],
              'from': '../' + leg['from'], 'solvate': bool(leg.get('solvate')),
              'checkpoint': leg.get('checkpoint')}
    name = Path(stage.relative).parent.name + '.json'
    (inputs / name).write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')


def _assessment_mdp(inputs: Path, settings: dict) -> int:
    """The assessment phase's mdp, for the requested duration: production only.

    The three legs in front of this stage are what solvates, minimises and equilibrates, so this phase reads the
    system the NPT leg left. Without removal there is no second leg to extend, so the requested sampling is one
    plain CG MD leg and both durations are folded into this one.

    The duration is converted into steps with the reviewed profile's own `dt`, and the profile states the integration
    settings `cg.mdp_integration` used to patch in, so the coarse-grained half of a solved CG run and this stage cannot
    disagree about the timestep.
    """
    profile = 'pdc-assessment-v1'
    duration_ns = float(settings['assessment_ns'])
    if not settings.get('remove_out_of_micelle', True):
        duration_ns += float(settings['extension_ns'])
    steps = round(duration_ns * 1000 / _profile_dt(profile))
    write_mdp(profile, inputs / 'assessment.mdp', _mdp_run_values(profile, settings, {'nsteps': steps}))
    return steps


def _extension_inputs(inputs: Path, settings: dict, skipped: dict, assessment_steps: int) -> int:
    """The extension phase's data: the assessment profile continuing instead of starting, and the restart's own pieces.

    Velocities are not regenerated -- this phase continues the trajectory it was given, which is the profile's
    `gen-vel = no` -- and the duration travels as picoseconds, which is what `convert-tpr -extend` takes. A run with
    removal off has no extension stage and gets none of this data.
    """
    extension_ps = round(float(settings['extension_ns']) * 1000)
    if 'CG extension MD' in skipped:
        return extension_ps
    write_mdp('pdc-extension-v1', inputs / 'extension.mdp',
              _mdp_run_values('pdc-extension-v1', settings, {'nsteps': assessment_steps}))
    # The removal path rebuilds the system from the kept coordinates, so this stage needs the same mdps and water the
    # solvation step uses. They are the unpatched CG templates: nothing in this run's numbers reaches them.
    write_mdp('pdc-restart-minimization-v1', inputs / 'minimization.mdp')
    write_mdp('pdc-restart-equilibration-v1', inputs / 'equilibration.mdp')
    (inputs / 'extension.ps').write_text(f'{extension_ps}\n')
    return extension_ps


def _equilibration_mdps(inputs: Path, settings: dict, skipped: dict) -> dict:
    """The three legs' mdps, written from their profiles at the run's own numbers, and the record each leg reads.

    Each profile is the reviewed physics of `resources/templates/protein_detergent/`: the timestep, the couplings,
    the cut-offs and the thermostat are not restated here. The adapter supplies only the run's own numbers -- the
    duration, and for the velocity-drawing leg the seed those velocities come from. A leg the run asks none of gets
    no mdp, no record and no directory; its step count is recorded as zero.

    Returns each leg's step count, so the run's record carries what the chain costs before it costs it.
    """
    steps = {}
    for name, leg in LEGS.items():
        stage = stage_by_name(name)
        if name in skipped:
            steps[leg['key']] = 0
            continue
        wanted = int(float(settings[leg['setting']]))
        # The profile decides the unit: a duration becomes steps at *its* own dt, so lowering a profile's dt cannot
        # silently shorten the leg the run asked for. The minimisation's setting is already a step count.
        count = (wanted if leg['setting'] == 'minimisation_steps'
                 else round(wanted / _profile_dt(leg['profile'])))
        values = {'nsteps': count}
        if leg.get('seed_velocities'):
            values['gen-seed'] = int(settings['seed'])
        write_mdp(leg['profile'], inputs / leg['mdp'], values)
        _write_leg_record(inputs, stage, leg)
        steps[leg['key']] = count
    return steps


# The specs are keyed by the panel's spelling; the builders work in short names. One map from the name a value is
# *stored* under to the spec that governs it, so a bound is stated once and checked whether the caller used either.
_SPEC_BY_NUMBER = {(_ALIASES.get(key) or key): spec for key, spec in SETTING_SPECS.items()}


def settings_from(payload: dict) -> dict:
    """A build's numbers: the adapter's defaults, then whatever the caller supplied under either spelling.

    `ignore_unknown` because a payload is not only settings: a build is handed the whole record, and `label` or
    `protein` are not values this function has an opinion about.
    """
    return _numbers(payload or {}, ignore_unknown=True)


def _numbers(supplied: dict, *, ignore_unknown: bool) -> dict:
    """One reader for both spellings, enforcing the bounds `SETTING_SPECS` publishes.

    The bounds used to be decoration: `normalize_settings` copied any advertised key and dropped any other, so a
    negative duration became `nsteps = -...` three stages into a build and a typo became a default with no word. The
    other four adapters raise for both; this is the same rule, in one place, for the two entry points here.
    """
    numbers = normalize(
        supplied, DEFAULTS, specs=_SPEC_BY_NUMBER, choices=CHOICE_SPECS, aliases=_ALIASES,
        ignore_unknown=ignore_unknown, object_message='PDC settings must be an object',
        unknown_prefix='Unknown PDC setting: ', bool_message='PDC settings must be numeric',
        integrals=_INTEGRAL_MESSAGES, integral_in_loop=True)
    return numbers


def _empty_topology() -> str:
    """The pre-detergent topology the stage starts from.

    The includes and the `[ molecules ]` names belong to the two `.itp` files, and the protein's own only exists
    after martinize2 has run and named it, so they are written by the stage rather than guessed here.
    """
    return ('; the system before the detergent arrives, written by the pdc adapter\n'
            '; the includes and the [ molecules ] names are written by the system-preparation stage, which is the\n'
            '; first thing that can read them (see pdc_build.py)\n\n'
            '[ system ]\n'
            'protein-detergent complex, CG protein\n\n'
            '[ molecules ]\n')


def _contains(root, path) -> bool:
    """Whether `path` sits under `root`, so the input record can spell it relative to that root."""
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def _skipped_stages(numbers: dict, protein_path) -> dict:
    """The stages the run's own settings say will not run, with the reason each records.

    A stage here gets no directory, no script and no `skip.json`: `workflow.run` records it `skipped` from the
    manifest's `skipped_stages` and carries on. Only the settings decide this -- a stage script never decides a
    settings-driven skip at run time, because deciding it there would leave a stage directory nothing runs.
    """
    skipped = {}
    if protein_path is None:
        skipped['Protein preparation'] = 'the run has no protein, so there is nothing to prepare'
    elif not numbers['prepare_protein']:
        skipped['Protein preparation'] = 'the run does not ask for protein preparation, so this stage has nothing to do'
    for name in ('Energy minimisation', 'NVT equilibration', 'NPT equilibration'):
        if int(float(numbers[LEGS[name]['setting']])) == 0:
            skipped[name] = LEGS[name]['reason']
    if not numbers.get('remove_out_of_micelle', True):
        for name in ('Micelle assessment', 'CG extension MD', 'Final assessment'):
            skipped[name] = ('the run switched out-of-micelle removal off, so there is no assessment to make'
                             if name == 'Micelle assessment' else
                             'the run switched out-of-micelle removal off, so there is nothing to extend or assess')
    if protein_path is None:
        skipped['Back-mapping (CG2AT2)'] = 'the run has no protein, so there is nothing to align'
    elif not numbers.get('backmap', True):
        skipped['Back-mapping (CG2AT2)'] = 'the run switched back-mapping off, so this stage has nothing to do'
    return skipped


def _limitations(model):
    """What a build does not claim, said by what it actually did.

    Two sentences used to be written into every run -- that the detergent is one centre per molecule, and that the
    assessment, removal, extension and back-mapping stage scripts are unimplemented. Both read as "this pipeline is not
    there yet": the first is false for a build given a mapping (its beads, topology and bonds come from the mapping),
    and the second is false outright, because those scripts are copied into every run. A record that misstates what a
    run did is worse than one that says nothing.

    And a detergent simulated with its *fitted* bonded terms and one whose terms were looked up in the Martini 3
    references are different systems, so the sentence names which was built and, for a fit, the revision it came from:
    a reader must never have to open `detergent_CG.itp` to find out whether it holds fitted or reference terms.
    """
    if not model.get('mapping'):
        return ['the detergent is one centre per molecule: no mapping was given, and the shipped templates carry no bead '
                'shape']
    mapping = Path(str(model['mapping'])).name
    recorded = model.get('parameterization') or {}
    if recorded:
        reference = (recorded.get('aa_reference') or {}).get('run_id') or 'no AA reference'
        validated = ('its record marks it scientifically validated' if recorded.get('scientifically_validated')
                     else 'its record marks it not scientifically validated')
        return [f"the detergent's bonded terms are the mapping's own parameterization, revision "
                f"{recorded.get('revision')} of content hash {recorded.get('content_hash')}, fitted "
                f"{_day(recorded.get('created_at'))} by {recorded.get('engine')} from AA run {reference}; {validated}",
                f"its beads and their positions are {mapping}, the mapping this run was given; the template supplied "
                'no bead shape']
    counts = ''
    if 'reference_terms' in model and 'fallback_terms' in model:
        counts = f", with {model['reference_terms']} reference terms and {model['fallback_terms']} fallbacks"
    return [f"the detergent's beads, topology and bonds are derived from {mapping}, the mapping this run was given"
            f'{counts}; the template supplied no bead shape']


def _day(value):
    """The date part of a recorded timestamp, for a sentence that says when something was made."""
    return str(value or '')[:10] or 'an unrecorded date'


def prepare(run_dir, *, protein=None, template=None, settings=None, project_root=None, mapping=None, **kwargs):
    """Write the run: one directory per stage that will run, the data they read, and the manifest naming both.

    `stages/` holds only stages the settings say will run; `inputs/` holds what this function synthesized, recorded
    in `inputs.json`. Everything the run reads that already existed -- the published Martini libraries, the template,
    the protein, the mapping -- is named by path and digest in the manifest rather than copied, and every stage's
    script is a repository file recorded in `stage_scripts`.

    `protein` and `template` are paths relative to `project_root` -- the spelling `catalog` reports, so the panel's
    own choice can be handed straight in. `mapping` is a saved CG mapping for the detergent: with it, the run's
    detergent is a real coarse-grained molecule (its beads' centres computed from the atomistic structure, and its
    topology either the mapping's own current parameterization -- when it was fitted -- or the terms derived from the
    Martini 3 references and the geometry); without it, the build records that it is centres-only and the stage stops
    where it always did, rather than pretending a dot is a molecule.

    A build with a template and no protein is the design spec's empty micelle: the protein stages are skipped, so an
    absence that is a choice is told apart from one that is an oversight -- an oversight has no template at all.
    """
    if not template:
        raise ValueError('a pdc build needs a detergent template')
    # The panel's spelling is translated before validation, because `validate_payload` reads the builders' names
    # and would otherwise see a missing seed where the caller sent one.
    supplied = {_ALIASES.get(key) or key: value
                for key, value in {**(settings or {}), **kwargs}.items()}
    choices = validate_payload({'protein': protein, 'template': template, **supplied})
    numbers = settings_from(supplied)
    # The device must be one this host reports, refused here rather than by mdrun three stages in. A host with no
    # devices is not a refusal (`devices.require`), and the index travels to the stage scripts as MDRUN_FLAGS.
    devices.require(numbers['mdrun_gpu'])
    from detergent_pdc.execution.adapters.pdc_placement import DEFAULT_RADIUS_NM
    numbers.update({'seed': choices['seed'], 'aggregation_number': choices['aggregation_number'],
                    'salt_molar': choices['salt_molar'], 'backmap': choices['backmap'],
                    'radius_nm': numbers.get('radius_nm') or round(float(DEFAULT_RADIUS_NM), 6)})

    run_dir = Path(run_dir)
    root = Path(project_root or Path.cwd()).resolve()
    protein_path = (root / str(protein)) if protein else None
    template_path = root / str(template)
    if protein_path is not None and not protein_path.is_file():
        raise ValueError(f'the pdc protein is not a file: {protein_path}')
    if not template_path.is_file():
        raise ValueError(f'the pdc template is not a file: {template_path}')
    # The chain selection is checked against the file it selects from, which is the first place the file is resolved:
    # a chain the structure does not name is refused here, with the file's own list, rather than reaching the build
    # and quietly simulating something else. A protein-free build has nothing to select and records no selection.
    selected_chains = validate_chains(protein_path, choices['protein_chains']) if protein_path is not None else None
    numbers['protein_chains'] = selected_chains
    numbers['prepare_protein'] = choices['prepare_protein']
    numbers['remove_out_of_micelle'] = choices['remove_out_of_micelle']
    # The plan's step 1 is a step *about a protein*: a run with none has nothing for it to rebuild, and a run that
    # asked for it anyway would be recorded as having prepared a structure that does not exist. Refused here, where
    # the protein is resolved, rather than as a stage that skips what the caller asked for.
    if numbers['prepare_protein'] and protein_path is None:
        raise ValueError('a protein-free build has no protein to prepare: protein preparation (PDB2PQR) needs a '
                         'structure, and this run is an empty micelle')

    from micelle import registry
    record = registry.load_template(template_path)
    template_issues = list(registry.validate_template(record))
    # Which beads form the hydrophobic core is the template's to say (a bead role of "tail"), because only the
    # assignment knows it. A template that does not say is not refused here -- the criterion refuses when it has
    # nothing to judge, which is the stage that actually needs the answer.
    numbers['tail_beads'] = [str(bead.get('name')) for bead in record.beads
                             if str(bead.get('role') or '').lower() == 'tail']
    numbers['tail_beads_source'] = 'the template, from its bead roles'

    # The stages the run's own settings say will not run. They get no directory, no script and no `skip.json`: the
    # executor records each one `skipped` from this mapping, with its reason, and the run carries on.
    skipped = _skipped_stages(numbers, protein_path)
    inputs = run_dir / INPUTS_DIRECTORY
    inputs.mkdir(parents=True, exist_ok=True)
    stage_root = run_dir / STAGES_DIRECTORY
    for stage in STAGES:
        if stage.name in skipped:
            continue
        (stage_root / Path(stage.relative).parent).mkdir(parents=True, exist_ok=True)

    # What the run reads that already existed is named by path and digest rather than copied: the workspace's installed
    # Martini 3 libraries, the detergent template's own topology, the protein and the mapping. The force field's record
    # keeps the same digests, read from the same files, so the manifest and the input record cannot disagree.
    references = []
    forced = {}
    for name in FORCEFIELD_FILES:
        source = martini3.path(name)
        references.append(run_inputs.installed('force_field', source, label=name))
        forced[name] = {'sha256': files.sha256(source), 'bytes': source.stat().st_size}
    numbers['force_field'] = {**FORCEFIELD_SOURCE, 'files': forced, 'root': str(martini3.root())}
    references.append(run_inputs.published('detergent_template', template_path.parent / record.topology,
                                           label=str(record.topology), repo_root=root))
    if protein_path is not None:
        resolved_protein = protein_path.resolve()
        if _contains(root, resolved_protein):
            references.append(run_inputs.published('protein', resolved_protein, label=str(protein), repo_root=root))
        else:
            # An imported structure outside the repository: recorded absolutely, because it has no relative spelling.
            references.append(run_inputs.absolute('protein', resolved_protein, label=str(protein)))
    else:
        (inputs / 'protein.pdb').write_text('; no protein: this is an empty-micelle build\n')
    (inputs / 'system_EMPTY.top').write_text(_empty_topology())
    # The detergent's coarse-grained model, derived from the run's own mapping: the topology the system will include
    # and the bead geometry the placement stamps. A build without a mapping is recorded as centres-only.
    model = {'mapping': None, 'terms': 0, 'reference_terms': 0, 'fallback_terms': 0,
             'source': 'no mapping: the detergent is one centre per molecule'}
    mapping_tail_beads = []
    if mapping is not None:
        from dashboard.models.mappings import store

        from detergent_pdc.models.molecules import detergent_cg
        # A saved candidate arrives by name, not by path: the panel offers the names the store lists, and the run's
        # own record keeps that name, so it is resolved here rather than demanded as a path.
        source = Path(str(mapping))
        if not source.is_file():
            candidate = store.candidate_paths().get(source.name)
            source = Path(candidate) if candidate else (root / str(mapping))
        if not source.is_file():
            raise ValueError(f'the detergent mapping is not a file: {mapping}')
        source = source.resolve()
        workspace = paths.current().workspace
        if _contains(workspace, source):
            references.append(run_inputs.store('mapping', source, label=source.name, workspace_root=workspace))
        else:
            references.append(run_inputs.absolute('mapping', source, label=source.name))
        draft = detergent_cg.derive(source, root / 'molecules', root)
        # The mapping's own fit, when it has one: the run simulates the terms that were fitted against an AA
        # reference, and only falls back to the references-and-geometry derivation when the mapping carries no
        # current revision. The geometry stays the mapping's in both cases -- the fit decides the terms, the
        # mapping decides where the beads are -- so the placement is unchanged by which one this is. The resolver
        # is `detergent_cg`'s own, because the New run preview makes the same claim about the same build.
        adopted = detergent_cg.adopt_stored(draft, detergent_cg.candidate(source))
        (inputs / DETERGENT_TOPOLOGY).write_text(adopted['topology'] if adopted else draft['topology'])
        (inputs / DETERGENT_GEOMETRY).write_text(json.dumps(draft, indent=2, sort_keys=True))
        model = {'mapping': str(source), 'residue': draft['residue'], 'beads': len(draft['beads'])}
        if adopted:
            model.update({'terms': adopted['total'], 'term_kinds': adopted['terms'],
                          'parameterization': adopted['parameterization'],
                          'source': detergent_cg.terms_source(adopted, draft)})
        else:
            model.update({'terms': draft['terms'], 'reference_terms': draft['reference_terms'],
                          'fallback_terms': draft['fallback_terms'],
                          'source': detergent_cg.terms_source(None, draft)})
        # The mapping answers for itself when the template cannot: a bead of the aliphatic carbon series is a tail
        # bead, and the sugar and polar series are not. This is what lets the criterion judge a run whose template is
        # still the skeleton -- one bead, no roles -- instead of refusing it.
        mapping_tail_beads = [str(bead['name']) for bead in draft.get('beads', [])
                              if re.fullmatch(r'C[1-5][a-z]?', str(bead.get('type') or ''))]
    numbers['detergent_model'] = model
    if not numbers['tail_beads'] and mapping_tail_beads:
        # The template is the long-term home for this, but the skeleton names no roles: the run's own mapping answers
        # instead, and the settings record which source was used so a reader knows what the criterion was told.
        numbers['tail_beads'] = mapping_tail_beads
        numbers['tail_beads_source'] = ("the run's own mapping: beads of the aliphatic carbon series, because the "
                                        'template names no tail roles')
    # The run's own decisions, in the file every stage reads them from. Written after the mapping resolved, because
    # the model and the tail beads are part of what the criterion is told.
    (inputs / SETTINGS_NAME).write_text(json.dumps(
        {'project_root': str(root), 'protein': str(protein) if protein else '', 'template': str(template),
         **numbers},
        indent=2, sort_keys=True))
    assessment_steps = _assessment_mdp(inputs, numbers)
    extension_ps = _extension_inputs(inputs, numbers, skipped, assessment_steps)
    equilibration_steps = _equilibration_mdps(inputs, numbers, skipped)
    if 'Energy minimisation' not in skipped or 'CG extension MD' not in skipped:
        # Solvation's fix-up mdp and the water it packs, for the first leg and for the extension's restart alike.
        write_mdp('pdc-ions-v1', inputs / 'ions.mdp')
        shutil.copy2(TUTORIAL_TEMPLATE / '4_CG_sim' / 'inputs' / 'water.gro', inputs / 'water.gro')
    # A tool that is not resolvable is recorded as unresolved rather than raising here, because readiness is the layer
    # that blocks a run for it.
    recorded_tools = {}
    for name in ('gmx', 'martinize2', pdc_preparation.TOOL):
        found = tools.tool_path(name)
        recorded_tools[name] = ({'path': found, 'sha256': files.sha256(found)} if found
                                else {'path': name, 'ready': False,
                                      'detail': ('not declared or not executable: the optional protein-preparation '
                                                 'step refuses by name when a run asks for it'
                                                 if name == pdc_preparation.TOOL
                                                 else 'not declared or not executable')})
    # The record is merged into whatever the coordinator already wrote rather than replacing it: a run's manifest
    # carries the executor's own keys, and replacing the file left the worker reading a manifest with no `stages`.
    manifest = {}
    if (run_dir / 'manifest.json').is_file():
        try:
            manifest = json.loads((run_dir / 'manifest.json').read_text())
        except ValueError:
            manifest = {}
    metadata = {**manifest,
                'run_type': 'pdc', 'settings': numbers,
                'protein': str(protein) if protein else '', 'template': str(template),
                'template_issues': template_issues, 'assessment_steps': assessment_steps,
                'extension_ps': extension_ps, 'equilibration_steps': equilibration_steps,
                # The reviewed physics behind each MDP `prepare` wrote, so the run can be read without opening them.
                'mdp_profiles': {name: profile for name, profile in MDP_PROFILES.items()
                                 if (inputs / name).is_file()},
                'limitations': _limitations(model)}
    protocol.write_prepared_manifest(
        run_dir, metadata, tools=recorded_tools, plan=_plan(), skipped=skipped,
        environment=devices.environment_record(manifest.get('environment')), references=references,
        scripts={stage.name: stage.script for stage in STAGES})


def _plan():
    """Every stage as `(name, relative)` pairs, in the order they run, the spelling a run's manifest records."""
    return [[stage.name, stage.relative] for stage in STAGES]


def stage_contract(metadata=None):
    """The contract in the shape the other run types publish: `(plan, inputs, outputs)`.

    The pdc stages are the same for every payload -- nothing here is per molecule yet -- so the metadata is
    accepted and unused, rather than the caller having to know which run types need it.
    """
    return (_plan(),
            {stage.name: list(stage.inputs) for stage in STAGES},
            {stage.name: list(stage.outputs) for stage in STAGES})


def stages(metadata=None):
    """The stage records themselves, for a caller that wants more than the plan."""
    return tuple(STAGES)


def stage_defaults():
    return dict(DEFAULTS)


def normalize_settings(settings=None, profile='standard'):
    """The panel's payload in the builders' spelling, validated. The profile has no pdc meaning yet."""
    # `ignore_unknown=False`: a settings payload is settings. A typo reaching this point used to vanish into the
    # defaults, which is how a run came to be built with a number nobody chose.
    return _numbers(settings or {}, ignore_unknown=False)


def readiness(protein=None, template=None, project_root=None, **kwargs):
    """What a protein-detergent build needs, in the shape every run type answers with.

    The template is checked by its own reader and validator, because those are the two things that decide whether
    it can build a system at all; the executables are resolved through the declared tools, so a build that names a
    tool the machine does not have is blocked here rather than in the middle of a stage. An empty micelle is a
    choice the caller states, so a missing protein is reported as an absence rather than a blocker when it is one.
    """
    from dashboard.execution.environment import probe_tool

    from micelle import registry

    checks, blockers = [], []
    root = Path(project_root or Path.cwd())
    paths_named = {}
    for label, value in (('Protein', protein), ('Detergent template', template)):
        if not value:
            if label == 'Protein' and template:
                checks.append({'label': label, 'path': 'none (empty micelle)', 'ready': True,
                               'detail': 'no protein by choice: the protein stages are skipped'})
            else:
                blockers.append(f'{label}: none selected')
            continue
        path = Path(value) if Path(value).is_absolute() else root / str(value)
        paths_named[label] = path
        found = path.is_file()
        checks.append({'label': label, 'path': str(value), 'ready': found,
                       'detail': 'found' if found else f'not a file: {path}'})
        if not found:
            blockers.append(f'{label}: not a file: {path}')

    template_path = paths_named.get('Detergent template')
    if template_path is not None and template_path.is_file():
        try:
            record = registry.load_template(template_path)
            issues = list(registry.validate_template(record))
            detail = '; '.join(issues) or 'coordinates and topology present'
        except (ValueError, OSError) as exc:
            issues, detail = [str(exc)], str(exc)
        checks.append({'label': 'Template files',
                       'path': f'{template_path.name}', 'ready': not issues, 'detail': detail})
        blockers.extend(issues)

    for name in ('gmx', 'martinize2'):
        executable = tools.tool_path(name)
        ok, detail = probe_tool(executable) if executable else (False, 'Executable not found')
        checks.append({'label': name, 'path': executable or name, 'ready': ok, 'detail': detail})
        if not ok:
            blockers.append(f'{name}: {detail}')
    # The preparer the optional Prepare step runs. A **check**, not a blocker, and that is the rule for a tool a run
    # type may not invoke at all: a run that does not ask for protein preparation does not need `pdb2pqr`, and the
    # step itself refuses by name when one does ask and the tool is not there. The row is here so the reader can see
    # whether their machine has it before they switch the step on.
    executable = tools.tool_path(pdc_preparation.TOOL)
    ok, detail = probe_tool(executable) if executable else (False, 'Executable not found')
    checks.append({'label': pdc_preparation.TOOL, 'path': executable or pdc_preparation.TOOL, 'ready': ok,
                   'detail': (f'{detail} -- the optional Prepare step rebuilds and protonates with it' if ok else
                              'not resolvable: a run that asks for protein preparation -- which is the default where '
                              'there is a protein -- skips that step and coarse-grains the structure as deposited')})
    return {'ready': not blockers, 'checks': checks, 'blockers': blockers}


def tool_metadata():
    """The tools a pdc run resolves and records: the executables its stages call."""
    return tools.record_versions('gmx', 'martinize2', version=False)


def _protocol_readiness(metadata):
    return readiness(protein=metadata.get('protein'), template=metadata.get('template'),
                     project_root=metadata.get('project_root'))


def _protocol_prepare(run_dir, metadata):
    """The run's own inputs, in the spellings the builders take: a saved mapping arrives as the job's candidate."""
    values = {'protein': metadata.get('protein'), 'template': metadata.get('template'),
              'settings': metadata.get('settings'), 'project_root': metadata.get('project_root'),
              'mapping': metadata.get('mapping_candidate') or metadata.get('mapping')}
    prepare(run_dir, **{key: value for key, value in values.items() if value})


# The choices a panel offers as a select rather than a number. `runs.py:queue` keeps only the keys an adapter
# advertises here or in `SETTING_SPECS`, so a choice the panel sends and the adapter does not advertise is dropped
# before the job is created -- silently, with no error, only a job built on the default. That is what happened to the
# placement mode: the panel sent `pdc_placement_mode: 'self-assembly'`, the route kept it out, and every run was built
# on the lattice whatever the reader chose. The values are the ones `pdc_placement.canonical_mode` accepts.
#
# `protein_chains` and `backmap` are choices with no enumerable domain here -- the first is the chains the chosen
# protein happens to name, the second is a boolean -- so their options are declared empty or as the two booleans, and
# their values are checked in `validate_payload` and `prepare` where the protein and the builder are known.
CHOICE_SPECS = {'pdc_placement_mode': ('Initialisation', ('lattice', 'self-assembly')),
                'mdrun_nb': ('Nonbonded scheme', ('auto', 'cpu', 'gpu')),
                'protein_chains': ('Protein chains', ()),
                'backmap': ('Back-mapping (CG2AT2)', (True, False)),
                'prepare_protein': ('Protein preparation (PDB2PQR)', (True, False)),
                'remove_out_of_micelle': ('Remove out-of-micelle detergents', (True, False))}

PROTOCOL = protocol.Protocol(
    name='pdc',
    stage_contract=stage_contract,
    stages=stages,
    settings_specs=lambda: SETTING_SPECS,
    choice_specs=lambda: CHOICE_SPECS,
    stage_defaults=stage_defaults,
    normalize_settings=normalize_settings,
    readiness=_protocol_readiness,
    prepare=_protocol_prepare,
    tool_report=tool_metadata,
)
