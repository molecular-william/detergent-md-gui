"""The protein-detergent complex pipeline. `micelle/` owns the science; this adapter owns the stages.

Only the catalogue and the stage contract live here so far: the placement, sampling, assessment and back-mapping
stages arrive with the phases that implement them, and every one of them belongs to this module rather than to the
route layer.
"""
import json
import re
import shutil
import sys
from pathlib import Path

from ... import files, paths
from .. import protocol, tools
from ..environment import ROOT, TUTORIAL_TEMPLATE
from ..stages import Stage
from . import pdc_import

SCRIPTS = Path(__file__).resolve().parent.parent / 'scripts'
# The coarse-grained parameters a pdc topology has to carry, from the published Martini 3 lipid set: the bead types
# (which the detergent's own beads need defined), the solvents file that defines water as `W`, and the ions file that
# defines `NA` and `CL`. Without them `grompp` refuses a solvated system with an undefined molecule type -- which is
# exactly how the first run that reached solvation failed. The set is recorded by commit and DOI in every manifest.
FORCEFIELD_ROOT = ROOT / 'references' / 'M3-Lipid-Parameters' / 'ITPs'
FORCEFIELD_FILES = ('martini_v3.0.0.itp', 'martini_v3.0.0_solvents_v1.itp', 'martini_v3.0.0_ions_v1.itp')
FORCEFIELD_SOURCE = {
    'repository': 'https://github.com/Martini-Force-Field-Initiative/M3-Lipid-Parameters.git',
    'commit': '2121527',
    'doi': '10.1021/acscentsci.5c00755',
    'citation': 'Pedersen et al., The Martini 3 Lipidome, ACS Central Science (2025)',
    'license': 'Apache-2.0',
}

# The two files the system-preparation stage reads and writes. The adapter owns their names because the stage
# script, the entry point and the tests all have to agree on them.
SETTINGS_NAME = 'pdc-settings.json'
REPORT_NAME = 'prepare_report.json'
# The detergent's derived coarse-grained model: the topology the system includes, and the bead geometry together
# with the provenance of its bonded terms.
DETERGENT_TOPOLOGY = 'detergent_CG.itp'
DETERGENT_GEOMETRY = 'detergent_CG.json'

DEFAULTS = {'salt_molar': 0.15, 'aggregation_number': 150, 'assessment_ns': 100, 'extension_ns': 900,
            'selection_threshold_fraction': 0.10, 'attempts_max': 3, 'box_margin_nm': 2.0,
            'initial_z_nm': 6.0, 'contact_nm': 0.6, 'snapshot_interval_ns': 20.0, 'snapshot_cap': 20,
            'minimisation_steps': 200000, 'nvt_ps': 500, 'npt_ps': 4500,
            # Which generator places the detergents. A string, not a number, so it has no SETTING_SPECS bound and is
            # validated in `validate_payload` instead; its presence here is what lets a caller's choice survive the
            # settings filter and reach the build. `lattice` is the default so no existing run's placement moves.
            'placement_mode': 'lattice',
            # Which subunits go into the simulation, and whether the back-map runs. `protein_chains` is `None` for
            # every chain -- so an existing caller, which never sends it, keeps the whole file -- and a list of ids
            # when a caller chooses; `backmap` is `True` so nothing existing stops comparing its CG system with the
            # atomistic one it came from. Both are choices rather than numbers and are validated in
            # `validate_payload` (shape) and `prepare` (against the file).
            'protein_chains': None, 'backmap': True}
_PROTEIN_LIMIT = 50

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
    'snapshot_interval_ns': ('Snapshot interval (ns)', 0.1, 1000.0),
    'snapshot_cap': ('Snapshots per stage (cap)', 1, 200),
    # The three equilibration legs, in steps of steepest descent and picoseconds of MD. `0` is a request for none of
    # that leg rather than a very short one: the stage has nothing to do, records `skipped`, and the run carries on.
    'pdc_minimisation_steps': ('CG minimisation steps', 0, 1000000),
    'pdc_nvt_ps': ('CG NVT equilibration (ps)', 0, 1000000),
    'pdc_npt_ps': ('CG NPT equilibration (ps)', 0, 1000000),
}

# What each equilibration leg's generated script has to know: the mdp it runs, the setting that turns into steps, and
# what the stage says when the run asks for none of it. Keyed by the stage's own name, so the declaration in `STAGES`
# and the script builder cannot name two different legs.
LEGS = {
    'Energy minimisation': {
        'key': 'minimisation', 'mdp': 'minimisation.mdp', 'setting': 'minimisation_steps', 'solvate': True,
        'purpose': 'solvate the built system, add its ions, and relax it before any dynamics',
        'reason': 'the run asks for 0 minimisation steps, so this stage has nothing to do'},
    'NVT equilibration': {
        'key': 'nvt', 'mdp': 'nvt.mdp', 'setting': 'nvt_ps', 'seed_velocities': True,
        'purpose': 'hold the system at fixed volume while the thermostat brings it to 300 K',
        'reason': 'the run asks for a 0 ps NVT equilibration, so this stage has nothing to do'},
    'NPT equilibration': {
        'key': 'npt', 'mdp': 'npt.mdp', 'setting': 'npt_ps', 'checkpoint': '../3_nvt/system.cpt',
        'purpose': 'hold the system at 1 bar so the box reaches its density before production',
        'reason': 'the run asks for a 0 ps NPT equilibration, so this stage has nothing to do'},
}
# The legs' mdp templates, one per leg, under the resources tree with every other template a run copies.
EQUILIBRATION_TEMPLATE = ROOT / 'resources/templates/protein_detergent'

# The protocol's own steps, named as stages so the executor, the manifest and the panel all speak the same words.
# Every stage that is not generated at prepare time runs a script of this workflow's own, named `pdc_...`: the
# assessment leg's directory names are historic and stay -- `pdc_extension.py`, the snapshot scripts and the web
# route all name `1_system`, `2_assessment` and `3_assessment` literally -- while the file inside the directory is
# pdc's: a pdc stage used to be the CG half's script under the CG half's name (`assessment.sh`, `extension.sh`,
# `backmap.sh`, and a stage file literally called `assess.sh`).
STAGES = (
    Stage('System preparation', '1_system/prepare_system.sh',
          ('protein.pdb', 'system_EMPTY.top', 'detergent.itp', *FORCEFIELD_FILES),
          ('system.gro', 'system.top', 'prepare_report.json')),
    # Change 2 of the new-run panel plan: the built system used to go straight into 100 ns of CG MD, and now the
    # standard sequence for a CG system built from a mapping goes in front of it -- minimisation, then NVT, then NPT.
    # A leg the run asks none of records `skipped` (exit 4) rather than leaving the chain.
    Stage('Energy minimisation', '2_minimisation/minimise.sh',
          ('../1_system/system.gro', '../1_system/system.top', '../1_system/' + DETERGENT_TOPOLOGY,
           *('../1_system/' + name for name in FORCEFIELD_FILES), 'minimisation.mdp', 'ions.mdp',
           'inputs/water.gro'),
          ('system.tpr', 'system.gro', 'system.edr', 'system.log', 'solvation.json')),
    Stage('NVT equilibration', '3_nvt/equilibrate.sh',
          ('../2_minimisation/system.gro', '../2_minimisation/system.top', '../2_minimisation/' + DETERGENT_TOPOLOGY,
           *('../2_minimisation/' + name for name in FORCEFIELD_FILES), 'nvt.mdp'),
          ('system.tpr', 'system.gro', 'system.edr', 'system.log', 'system.cpt', 'system.xtc')),
    Stage('NPT equilibration', '4_npt/equilibrate.sh',
          ('../3_nvt/system.gro', '../3_nvt/system.top', '../3_nvt/' + DETERGENT_TOPOLOGY,
           *('../3_nvt/' + name for name in FORCEFIELD_FILES), 'npt.mdp'),
          ('system.tpr', 'system.gro', 'system.edr', 'system.log', 'system.cpt', 'system.xtc')),
    # And the counterpart of change 2: this leg is production only, and it samples the system the NPT leg left. It
    # used to solvate, minimise and equilibrate the built system itself -- the same work the three legs above do, so
    # every run equilibrated twice and the legs' output fed nothing. Its declaration is the NPT leg's own system, so
    # the copy of it is emitted from here like every other stage's.
    Stage('CG assessment MD', '2_assessment/pdc_assessment.sh',
          ('../4_npt/system.gro', '../4_npt/system.top', '../4_npt/' + DETERGENT_TOPOLOGY,
           *('../4_npt/' + name for name in FORCEFIELD_FILES), 'assessment.mdp'),
          ('prod/run.gro', 'prod/run.tpr', 'prod/run.xtc', 'prod/run.cpt')),
    Stage('Micelle assessment', '3_assessment/pdc_assess.sh',
          ('../2_assessment/prod/run.gro', '../2_assessment/prod/run.xtc'),
          ('assessment.json', 'kept.gro', 'removed.json')),
    Stage('CG extension MD', '4_extension/pdc_extension.sh',
          ('../2_assessment/prod/run.tpr', '../2_assessment/prod/run.cpt', '../2_assessment/system.top',
           '../1_system/' + DETERGENT_TOPOLOGY, *('../1_system/' + name for name in FORCEFIELD_FILES),
           'extension.mdp'),
          ('prod/run.gro', 'prod/run.xtc')),
    Stage('Final assessment', '5_assessment/pdc_assess.sh',
          ('../4_extension/prod/run.gro', '../4_extension/prod/run.xtc'),
          ('assessment.json',)),
    Stage('Back-mapping (CG2AT2)', '6_backmap/pdc_backmap.sh',
          ('../4_extension/prod/run.gro', '../1_system/protein.pdb'),
          ('cg2at_input.pdb', 'FINAL/final_cg2at_aligned.pdb', 'backmap.log')),
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


def _stage_directory(run_dir: Path, name: str) -> Path:
    """One stage's directory, named by the stage so a caller cannot count its way to the wrong one."""
    return run_dir / Path(stage_by_name(name).relative).parent


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
    seed = payload.get('seed')
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 1:
        raise ValueError('pdc seed must be a positive integer')
    aggregation = payload.get('aggregation_number', DEFAULTS['aggregation_number'])
    if not isinstance(aggregation, int) or isinstance(aggregation, bool) or aggregation < 1:
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
    from .pdc_placement import DEFAULT_PLACEMENT_MODE, canonical_mode
    placement_mode = canonical_mode(payload.get('placement_mode', DEFAULT_PLACEMENT_MODE))
    backmap = payload.get('backmap', DEFAULTS['backmap'])
    if not isinstance(backmap, bool):
        raise ValueError(f'the pdc back-map setting must be true or false, not {backmap!r}')
    chains = normalize_chains(payload.get('protein_chains'))
    return {'seed': seed, 'aggregation_number': aggregation, 'salt_molar': salt,
            'placement_mode': placement_mode, 'protein_chains': chains, 'backmap': backmap,
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
                                          ['skeleton placeholder template, not a fitted detergent model'])})
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

# `genion` fits ions to a topology and needs a tpr, not a trajectory: this is the shortest MDP that makes one, and
# it is written beside the stage so the solvation step cannot depend on a template that moved.
IONS_MDP = """\
; A topology fix-up run for genion: no dynamics, no output, just a tpr the ions can be fitted to.
integrator              = steep
nsteps                  = 0
cutoff-scheme           = Verlet
rlist                   = 1.1
coulombtype             = reaction-field
epsilon_r               = 15
"""


def _mdp_number(path, key: str) -> float:
    """A number from an MDP, so a requested duration can be turned into steps in the template's own units."""
    for raw in Path(path).read_text().splitlines():
        line = raw.split(';', 1)[0].strip()
        if not line or '=' not in line:
            continue
        name, value = (part.strip() for part in line.split('=', 1))
        if name.lower().replace('_', '-') == key:
            try:
                return float(value.split()[0])
            except (ValueError, IndexError) as exc:
                raise ValueError(f'{path}: {key} is not a number: {value!r}') from exc
    raise ValueError(f'{path} does not set {key}')


def _extension_stage(run_dir: Path, settings: dict):
    """The extension phase's inputs: the same MDP as the assessment phase, continuing instead of starting.

    Velocities are not regenerated -- this phase continues the trajectory it was given -- and the duration is
    passed to the stage as picoseconds, which is what `convert-tpr -extend` takes.
    """
    from ..environment import update_mdp

    extension, assessment = stage_by_name('CG extension MD'), stage_by_name('CG assessment MD')
    stage = run_dir / Path(extension.relative).parent
    stage.mkdir(parents=True, exist_ok=True)
    shutil.copy2(run_dir / Path(assessment.relative).parent / 'assessment.mdp', stage / 'extension.mdp')
    update_mdp(stage / 'extension.mdp', {'gen-vel': 'no'})
    shutil.copy2(SCRIPTS / _STAGE_SOURCES[extension.relative], stage / Path(extension.relative).name)
    # The removal path rebuilds the system from the kept coordinates, so this stage needs the same mdps and water the
    # solvation step uses, plus the two helpers that rebuild it.
    for target, source in (('minimization.mdp', 'minimization.mdp'), ('equilibration.mdp', 'eq.mdp'),
                           ('inputs/water.gro', 'water.gro')):
        (stage / target).parent.mkdir(exist_ok=True)
        shutil.copy2(TUTORIAL_TEMPLATE / '4_CG_sim' / 'inputs' / source, stage / target)
    # `ions.mdp` is the fix-up tpr `genion` fits ions to, and the removal path re-solvates, so this stage writes it
    # itself. It used to read the assessment phase's copy, which existed because that phase solvated -- work the
    # equilibration legs do, so the assessment phase is production only now and carries no solvation input at all.
    (stage / 'ions.mdp').write_text(IONS_MDP)
    shutil.copy2(SCRIPTS / 'pdc_extension.py', stage / 'pdc_extension.py')
    shutil.copy2(SCRIPTS / 'pdc_solvate.py', stage / 'pdc_solvate.py')
    extension_ps = round(float(settings['extension_ns']) * 1000)
    (stage / 'extension.ps').write_text(f'{extension_ps}\n')
    return extension_ps


def _assessment_stage(run_dir: Path, settings: dict):
    """The assessment phase's inputs: one mdp, for the requested duration, and nothing else.

    Production only, because the three legs in front of this stage are what solvates, minimises and equilibrates.
    It used to carry the solvation, minimisation and equilibration mdps and the water they run on, and to run them
    itself -- which equilibrated every run twice and left the legs' own output feeding nothing. What it reads
    instead is the system the NPT leg left, named on its own declaration, so the copy of it is emitted from that
    declaration like every other stage's.

    The duration is converted into steps with the *template's* own `dt`, and the integration settings come from
    `cg.mdp_integration`, so the coarse-grained half of a solved CG run and this stage cannot disagree about the
    timestep. Its `aa_dir` argument cannot equal this stage -- a pdc run has no atomistic half -- so the
    coarse-grained branch is the one that applies.
    """
    from ..environment import update_mdp
    from . import cg as cg_adapter

    assessment = stage_by_name('CG assessment MD')
    stage = run_dir / Path(assessment.relative).parent
    stage.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TUTORIAL_TEMPLATE / '4_CG_sim' / 'inputs' / 'md.mdp', stage / 'assessment.mdp')
    steps = round(float(settings['assessment_ns']) * 1000 / _mdp_number(stage / 'assessment.mdp', 'dt'))
    update_mdp(stage / 'assessment.mdp', cg_adapter.mdp_integration(stage, stage / '1_AA-reference', steps))
    shutil.copy2(SCRIPTS / _STAGE_SOURCES[assessment.relative], stage / Path(assessment.relative).name)
    return steps

_STAGE_SCRIPT = """#!/bin/sh
# {label} for a protein-detergent complex run.
#
# Generated by the pdc adapter, which owns the numbers below; the work is the entry point's, and it applies the
# tested builders (pdc_box, pdc_placement, pdc_protein) rather than a private copy of their rules.
#
# Exit 0 built. Exit 2 a gate refused and {report} says which. Exit 3 a step whose rules do not exist yet.
set -eu

cd "$(dirname "$0")"
PYTHONPATH={root}${{PYTHONPATH:+:$PYTHONPATH}} {python} -m dashboard.execution.scripts.pdc_build --stage .
"""

# The template each equilibration leg's script is generated from. Every leg is the same work -- grompp, then mdrun --
# so the three differences are filled in rather than written three times. `_stamp_interpreter` points the `python`
# line at this application's interpreter and puts the project root on the import path, and `_stage_declared_inputs`
# inserts the copies of the leg's declared inputs, both at prepare time.
_LEG_SCRIPT = """#!/bin/bash
# {label} for a protein-detergent complex run: {purpose}.
#
# The mdrun budget and the scheme choices arrive as environment -- MDRUN_LAUNCHER is an mpirun prefix or empty,
# MDRUN_FLAGS the flags -- because this stage is a script rather than a generated command. No -ntmpi appears in the
# executed lines: this host's `gmx` is an MPI-only build where that flag aborts mdrun before the first step, while
# -ntomp is valid for every build.
#
# The contract's fourth outcome is `skipped`, and for a leg it is a real answer: a run may ask for none of it, and the
# adapter stamps the step count into {mdp}, so the number this stage acts on is the number in the file it runs.
set -euxo pipefail

# Nothing to do says so, and why, in `skip.json` beside the script -- which is where the executor reads the reason.
STEPS=$(awk -F= '/^[[:space:]]*nsteps[[:space:]]*=/ {{print $2+0; exit}}' {mdp})
if [ "${{STEPS:-0}}" -eq 0 ]; then
  echo '{{"skipped": true, "reason": "{reason}"}}' > skip.json
  echo "skipped: {reason}" >&2
  exit 4
fi

{solvation}{checkpoint}gmx grompp -f {mdp} -p system.top -c system.gro{checkpoint_flag} -o system.tpr -maxwarn 1
${{MDRUN_LAUNCHER:-}}gmx mdrun -deffnm system ${{MDRUN_FLAGS:--ntomp 8 -gpu_id 0 -nb gpu -pin on}} -v
"""

# The first leg's opening act: the system the build leaves is dry, and these are the commands that fill it. They come
# from `pdc_solvation` -- the tested place that decides the water bead radius, the ion names and the group `genion` may
# replace -- rather than from this script.
_LEG_SOLVATION = """# The built system is dry, so solvation and ions are this leg's opening act.
python pdc_solvate.py --topology system.top --structure system.gro --salt-molar {salt}

"""
# The last leg carries the velocities the NVT leg equilibrated. A leg the run asked none of leaves no checkpoint, so
# the file is read when it is there rather than declared as an input that no skip path could satisfy.
_LEG_CHECKPOINT = """# The checkpoint the leg before this one left, when it left one: those are the velocities the thermostat equilibrated.
if [ -f {checkpoint} ]; then CHECKPOINT="-t {checkpoint}"; else CHECKPOINT=""; fi

"""


def _equilibration_scripts(run_dir: Path, settings: dict) -> dict:
    """The three legs that equilibrate the built system, before the assessment leg samples it.

    Each leg runs *its template's own mdp*: the timestep, the couplings, the cut-offs and the thermostat all come from
    `resources/templates/protein_detergent/`, so a leg's physics is checkable without reading this module. The adapter
    writes only the run's own numbers into the copy it hands the stage -- the duration, and for the velocity-drawing
    leg the seed those velocities come from -- and `0` is a request for none of that leg, which the stage records as
    `skipped` rather than as a run of zero steps.

    The first leg solvates, because the system a build leaves is dry and solvation is what every stage after it needs.
    Returns each leg's step count, so the run's record carries what the chain costs before it costs it.
    """
    from ..environment import update_mdp

    steps = {}
    for name, leg in LEGS.items():
        stage = stage_by_name(name)
        directory = _stage_directory(run_dir, name)
        directory.mkdir(parents=True, exist_ok=True)
        shutil.copy2(EQUILIBRATION_TEMPLATE / leg['mdp'], directory / leg['mdp'])
        wanted = int(float(settings[leg['setting']]))
        # The template decides the unit: a duration becomes steps at *the template's* own dt, so lowering a template's
        # dt cannot silently shorten the leg the run asked for. The minimisation's setting is already a step count.
        count = (wanted if leg['setting'] == 'minimisation_steps'
                 else round(wanted / _mdp_number(directory / leg['mdp'], 'dt')))
        changes = {'nsteps': count}
        if leg.get('seed_velocities'):
            changes['gen-seed'] = int(settings['seed'])
        update_mdp(directory / leg['mdp'], changes)
        solvation, checkpoint, checkpoint_flag = '', '', ''
        if leg.get('solvate'):
            shutil.copy2(SCRIPTS / 'pdc_solvate.py', directory / 'pdc_solvate.py')
            (directory / 'ions.mdp').write_text(IONS_MDP)
            (directory / 'inputs').mkdir(exist_ok=True)
            shutil.copy2(TUTORIAL_TEMPLATE / '4_CG_sim' / 'inputs' / 'water.gro',
                         directory / 'inputs' / 'water.gro')
            solvation = _LEG_SOLVATION.format(salt=float(settings['salt_molar']))
        if leg.get('checkpoint'):
            checkpoint = _LEG_CHECKPOINT.format(checkpoint=leg['checkpoint'])
            checkpoint_flag = ' $CHECKPOINT'
        (directory / Path(stage.relative).name).write_text(_LEG_SCRIPT.format(
            label=name, purpose=leg['purpose'], mdp=leg['mdp'], reason=leg['reason'],
            solvation=solvation, checkpoint=checkpoint, checkpoint_flag=checkpoint_flag))
        steps[leg['key']] = count
    return steps


# The stages whose script is written at prepare time rather than copied from `scripts/`: stage 1's, because it has
# to carry the interpreter and the project root the run was prepared with, and the three equilibration legs',
# because they are the same three commands with the run's own numbers in them.
GENERATED_STAGES = ('1_system/prepare_system.sh', '2_minimisation/minimise.sh', '3_nvt/equilibrate.sh',
                    '4_npt/equilibrate.sh')

# Which file in `scripts/` each stage's script comes from. A stage that is not generated runs a script of this
# workflow's own, so the file carries the stage's own name -- derived rather than listed, because a translation
# table between two names is a place the two can disagree.
_STAGE_SOURCES = {stage.relative: Path(stage.relative).name for stage in STAGES
                  if stage.relative not in GENERATED_STAGES}


def settings_from(payload: dict) -> dict:
    """A build's numbers: the adapter's defaults, then whatever the caller supplied under either spelling."""
    numbers = dict(DEFAULTS)
    for key, value in (payload or {}).items():
        if key in SETTING_SPECS or key in _ALIASES or key in numbers:
            numbers[_ALIASES.get(key) or key] = value
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


def _stage_declared_inputs(script, stage):
    """Copy the stage's declared inputs from the phase before it into its own directory.

    A stage's artefacts are immutable and the scripts are written against that: solvation edits the topology in place
    and an assessment reads the phase's trajectory, so both need a local copy. The copy is emitted from the stage's
    own declaration, which is the one place the contract is stated -- the alternative is what the first run did,
    where the script named `system.top` and nothing had ever put one there.
    """
    lines = []
    for entry in stage.inputs:
        source = str(entry)
        if not source.startswith('../'):
            continue
        target = re.sub(r'^(?:\.\./[^/]+/)+', '', source)
        parent = str(Path(target).parent)
        prefix = f'mkdir -p {parent} && ' if parent != '.' else ''
        lines.append(f'{prefix}cp -f {source} {target}')
    if not lines:
        return
    text = script.read_text()
    if lines[0] in text:
        return
    prelude = ('# The phase before this one stays immutable, so its declared inputs are copied in rather than\n'
               '# edited where they lie. Emitted from the stage declaration itself.\n' + '\n'.join(lines) + '\n')
    marker = '\nset -'
    if marker in text:
        head, _, tail = text.partition(marker)
        script.write_text(f'{head}\n{prelude}{marker}{tail}')
    else:
        script.write_text(prelude + text)


def _stamp_interpreter(script, root):
    """Point a copied stage script at the interpreter this application runs under, and at this repository.

    Two things the generated stage-1 script does and the scripts written by hand did not. `python` on PATH is a
    different interpreter, and the one carrying this repository is this one. And a stage script runs from its own
    directory, so the repository is not on the import path: stage 1 sets PYTHONPATH, and without it the first import
    of `dashboard` fails after the tools have been resolved and before anything is built.
    """
    text = script.read_text()
    if not text.startswith('#!'):
        return
    rewritten = re.sub(r'(?m)^(\s*)python(?=\s|$)', lambda match: f'{match.group(1)}{sys.executable}', text)
    if 'PYTHONPATH=' not in rewritten:
        rewritten = rewritten.replace('\nset -', f'\nexport PYTHONPATH={root}${{PYTHONPATH:+:$PYTHONPATH}}\nset -', 1)
    if rewritten != text:
        script.write_text(rewritten)


def prepare(run_dir, *, protein=None, template=None, settings=None, project_root=None, mapping=None, **kwargs):
    """Write the stage directories and everything the first stage needs to start.

    `protein` and `template` are paths relative to `project_root` -- the spelling `catalog` reports, so the panel's
    own choice can be handed straight in. `mapping` is a saved CG mapping for the detergent: with it, the run's
    detergent is a real coarse-grained molecule (its topology derived from the mapping, its beads' centres computed
    from the atomistic structure); without it, the build records that it is centres-only and the stage stops where it
    always did, rather than pretending a dot is a molecule.

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
    from .pdc_placement import DEFAULT_RADIUS_NM
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

    from micelle import registry
    record = registry.load_template(template_path)
    template_issues = list(registry.validate_template(record))
    # Which beads form the hydrophobic core is the template's to say (a bead role of "tail"), because only the
    # assignment knows it. A template that does not say is not refused here -- the criterion refuses when it has
    # nothing to judge, which is the stage that actually needs the answer.
    numbers['tail_beads'] = [str(bead.get('name')) for bead in record.beads
                             if str(bead.get('role') or '').lower() == 'tail']
    numbers['tail_beads_source'] = 'the template, from its bead roles'

    # Every stage directory the contract names, and every one gets its script. The map is explicit because two
    # stage file names are not the name of a file in `scripts/`: stage 1's script is generated below, and both
    # assessment stages run `pdc_assess.sh` (the legacy `assess.sh` belongs to the AA and CG run types).
    for stage in STAGES:
        directory = run_dir / Path(stage.relative).parent
        directory.mkdir(parents=True, exist_ok=True)
        source = _STAGE_SOURCES.get(stage.relative)
        if source:
            shutil.copy2(SCRIPTS / source, directory / Path(stage.relative).name)
    for name in ('Micelle assessment', 'Final assessment'):
        shutil.copy2(SCRIPTS / 'pdc_assess.py', _stage_directory(run_dir, name) / 'pdc_assess.py')
    # The frame sampler is copied beside every stage that has a trajectory to read.
    for name in ('CG assessment MD', 'Micelle assessment', 'CG extension MD', 'Final assessment'):
        shutil.copy2(SCRIPTS / 'pdc_snapshot.py', _stage_directory(run_dir, name) / 'pdc_snapshot.py')

    system = run_dir / Path(STAGES[0].relative).parent
    forced = {}
    for name in FORCEFIELD_FILES:
        source = FORCEFIELD_ROOT / name
        if not source.is_file():
            continue
        shutil.copy2(source, system / name)
        forced[name] = {'sha256': files.sha256(source), 'bytes': source.stat().st_size}
    numbers['force_field'] = {**FORCEFIELD_SOURCE, 'files': forced, 'root': str(FORCEFIELD_ROOT)}
    if protein_path is not None:
        (system / 'protein.pdb').write_bytes(protein_path.read_bytes())
    else:
        (system / 'protein.pdb').write_text('; no protein: this is an empty-micelle build\n')
    (system / Path(STAGES[0].inputs[2]).name).write_bytes((template_path.parent / record.topology).read_bytes())
    (system / Path(STAGES[0].inputs[1]).name).write_text(_empty_topology())
    # The detergent's coarse-grained model, derived from the run's own mapping: the topology the system will include
    # and the bead geometry the placement stamps. A build without a mapping is recorded as centres-only.
    model = {'mapping': None, 'terms': 0, 'reference_terms': 0, 'fallback_terms': 0}
    mapping_tail_beads = []
    if mapping is not None:
        from ...models.mappings import store
        from ...models.molecules import detergent_cg
        # A saved candidate arrives by name, not by path: the panel offers the names the store lists, and the run's
        # own record keeps that name, so it is resolved here rather than demanded as a path.
        source = Path(str(mapping))
        if not source.is_file():
            candidate = store.candidate_paths().get(source.name)
            source = Path(candidate) if candidate else (root / str(mapping))
        if not source.is_file():
            raise ValueError(f'the detergent mapping is not a file: {mapping}')
        draft = detergent_cg.derive(source, root / 'molecules', root)
        (system / DETERGENT_TOPOLOGY).write_text(draft['topology'])
        (system / DETERGENT_GEOMETRY).write_text(json.dumps(draft, indent=2, sort_keys=True))
        model = {'mapping': str(source), 'residue': draft['residue'], 'beads': len(draft['beads']),
                 'terms': draft['terms'], 'reference_terms': draft['reference_terms'],
                 'fallback_terms': draft['fallback_terms']}
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
    (system / SETTINGS_NAME).write_text(json.dumps(
        {'project_root': str(root), 'protein': str(protein) if protein else '', 'template': str(template),
         **numbers},
        indent=2, sort_keys=True))
    (system / Path(STAGES[0].relative).name).write_text(_STAGE_SCRIPT.format(
        label=STAGES[0].name, report=REPORT_NAME, root=str(root), python=sys.executable))
    assessment_steps = _assessment_stage(run_dir, numbers)
    extension_ps = _extension_stage(run_dir, numbers)
    equilibration_steps = _equilibration_scripts(run_dir, numbers)
    # One record, and it is the one the pipeline reads: `workflow.prepare_run` takes this manifest, adds the run's
    # snapshots and tools, and moves it to the run root. A tool that is not resolvable is recorded as unresolved
    # rather than raising here, because readiness is the layer that blocks a run for it.
    recorded_tools = {}
    for name in ('gmx', 'martinize2'):
        found = tools.tool_path(name)
        recorded_tools[name] = ({'path': found, 'sha256': files.sha256(found)} if found
                                else {'path': name, 'ready': False,
                                      'detail': 'not declared or not executable'})
    for stage in STAGES:
        script = run_dir / Path(stage.relative)
        if not script.is_file():
            continue
        _stamp_interpreter(script, root)
        _stage_declared_inputs(script, stage)
    # The record is merged into whatever the coordinator already wrote rather than replacing it: a run's manifest
    # carries the executor's own keys -- the stage ledger above all -- and replacing the file left the worker reading
    # a manifest with no `stages`, which failed the run with a KeyError instead of a build.
    manifest = {}
    if (run_dir / 'manifest.json').is_file():
        try:
            manifest = json.loads((run_dir / 'manifest.json').read_text())
        except ValueError:
            manifest = {}
    manifest.update(
        {'run_type': 'pdc', 'stage_plan': _plan(), 'settings': numbers,
         'protein': str(protein) if protein else '', 'template': str(template),
         'template_issues': template_issues,
         'assessment_steps': assessment_steps, 'extension_ps': extension_ps,
         'equilibration_steps': equilibration_steps, 'tools': recorded_tools,
         'limitations': ['the detergent is one centre per molecule: the shipped templates carry no bead shape',
                         'the assessment, removal, extension and back-mapping stage scripts are task B7b']})
    manifest.setdefault('stages', [])
    (run_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True))


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
    """The panel's payload in the builders' spelling. The profile has no pdc meaning yet and is not recorded."""
    return settings_from(settings or {})


def readiness(protein=None, template=None, project_root=None, **kwargs):
    """What a protein-detergent build needs, in the shape every run type answers with.

    The template is checked by its own reader and validator, because those are the two things that decide whether
    it can build a system at all; the executables are resolved through the declared tools, so a build that names a
    tool the machine does not have is blocked here rather than in the middle of a stage. An empty micelle is a
    choice the caller states, so a missing protein is reported as an absence rather than a blocker when it is one.
    """
    from micelle import registry

    from ..environment import probe_tool

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
    return {'ready': not blockers, 'checks': checks, 'blockers': blockers}


def tool_metadata():
    """The tools a pdc run resolves and records: the executables its stages call."""
    result = {}
    for name in ('gmx', 'martinize2'):
        executable = tools.tool_path(name)
        if not executable:
            raise FileNotFoundError(f'Missing tool: {name}')
        result[name] = {'path': executable, 'sha256': files.sha256(executable)}
    return result


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
                'protein_chains': ('Protein chains', ()),
                'backmap': ('Back-mapping (CG2AT2)', (True, False))}

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
