"""Where a run keeps the files an analysis reads, across the two stage layouts in use.

An AA-only run publishes its solute reference under `07_reference/`. A CG consumer keeps its own atomistic
reference under `1_AA-reference/prod/`, the trajectory mapped onto the CG bead sets under `2_mapping/`, and
the coarse-grained trajectory under `4_CG_sim/prod/`. Both layouts are live in the workspace at once, so a
reader that wants "this run's atomistic trajectory" has to say which layout it found rather than falling back
to the other one: a run that holds neither, or both, is an error that names what was looked for.

Two roots are read with these roles. A caller reading a run on disk finds them under `stages/`; the work
directory an analysis subprocess is handed holds the same files at its own root, because that is where
`analysis.worker.source_entries` copies them from. Both spellings are searched, and only two spellings of the
*same* role count as an ambiguity. `stage_root` is the one answer to "where does this run keep its stages", so a
reader no longer needs `environment.execution_root`: `stages/` when the run has it, the run root for a legacy run,
and the directory itself for a work directory.

A protein-detergent run also has two spellings of its own: the numbered directories (`02_system/` … `10_backmap/`)
a current run writes, and the names it wrote before that (`1_system/` … `6_backmap/`). `PDC_STAGE_DIRECTORIES` is
the one table that says which directory is which stage, and `pdc_stage_path`/`pdc_stage_dir` read through it.

Nothing here opens a topology file. The roles are paths, and the caller decides whether absence is fatal; the one
record read is the manifest `recorded_topology` searches for the name a run recorded.
"""
import json
from pathlib import Path

#: role -> the relative paths looked for, in order, relative to the execution root. Only one may exist.
CANDIDATES = {
    'aa_trajectory': ('07_reference/lig.xtc', '1_AA-reference/prod/lig.xtc'),
    'aa_structure': ('07_reference/lig.gro', '1_AA-reference/prod/lig.gro'),
    'mapped_trajectory': ('2_mapping/mapped.xtc',),
    'mapped_structure': ('2_mapping/mapped.gro',),
    'cg_trajectory': ('4_CG_sim/prod/lig_CG.xtc',),
    'cg_structure': ('4_CG_sim/prod/lig_CG.gro',),
    #: The CG simulation stage's own output, before the pipeline extracted the solute: the whole box, solvent
    #: included. A current run holds these *and* `cg_trajectory`, which is why a review picks between them by
    #: preference rather than by `resolve`'s exactly-one rule.
    'cg_stage_trajectory': ('4_CG_sim/md.xtc',),
    'cg_stage_structure': ('4_CG_sim/md.gro',),
    'cg_equilibrium_trajectory': ('4_CG_sim/eq.xtc',),
    'cg_equilibrium_structure': ('4_CG_sim/eq.gro',),
    #: A protein-detergent run keeps its stages under names of their own, and its CG production is the extension's: the
    #: final assessment re-declares that same trajectory rather than writing a second one. Two spellings get two roles,
    #: because `resolve` refuses a role spelled twice and this run holds both the whole-box and the raw file. Each role
    #: carries the numbered layout (`08_extension/`, written by the current run) and the legacy one (`4_extension/`).
    'pdc_trajectory': ('08_extension/prod/whole.xtc', '4_extension/prod/whole.xtc'),
    'pdc_raw_trajectory': ('08_extension/prod/run.xtc', '4_extension/prod/run.xtc'),
    'pdc_structure': ('08_extension/prod/run.gro', '4_extension/prod/run.gro'),
    #: The assessment leg's production, for a run that takes no extension (the removal path off): its production MD
    #: is `06_assessment`, and a reader must still find a trajectory to review.
    'pdc_assessment_trajectory': ('06_assessment/prod/whole.xtc', '2_assessment/prod/whole.xtc'),
    'pdc_assessment_structure': ('06_assessment/prod/run.gro', '2_assessment/prod/run.gro'),
    #: Where a consumer run wrote its atomistic half before the reference/consumer split.
    'legacy_aa_trajectory': ('1_AA-reference/3-run.xtc',),
    'legacy_aa_structure': ('1_AA-reference/3-run.tpr',),
    'solute_topology': ('common/molecule/molecule.itp',),
}

#: The directory a run directory keeps those stages in, and which a work directory does not have.
STAGES = 'stages'

#: A protein-detergent run's stage directories, newest layout first, keyed by the stage itself. `01_prepare` …
#: `10_backmap` are the numbered layout, one directory per stage; the names after each key are the legacy spelling of
#: the same stage and are still read because two runs in this workspace predate the numbering.
PDC_STAGE_DIRECTORIES = {
    'prepare': ('01_prepare', '0_prepare'),
    'system': ('02_system', '1_system'),
    'minimisation': ('03_minimisation', '2_minimisation'),
    'nvt': ('04_nvt', '3_nvt'),
    'npt': ('05_npt', '4_npt'),
    'assessment': ('06_assessment', '2_assessment'),
    'micelle_assessment': ('07_micelle_assessment', '3_assessment'),
    'extension': ('08_extension', '4_extension'),
    'final_assessment': ('09_final_assessment', '5_assessment'),
    'backmap': ('10_backmap', '6_backmap'),
}

#: Stage directory name -> the stage it means, across both layouts.
PDC_STAGE_KEYS = {name: stage for stage, names in PDC_STAGE_DIRECTORIES.items() for name in names}

#: An assessment attempt's directory, newest layout first: a pdc run's final assessment is `09_final_assessment`
#: and a CG run's assessment is `5_assessment` (which a legacy pdc run's final assessment also uses).
ASSESSMENT_DIRECTORIES = ('09_final_assessment', '5_assessment')


def stage_root(root):
    """Where a run keeps its stage directories: `stages/` when it exists, the run root for a legacy run.

    The one answer every reader uses instead of `environment.execution_root`: a current run -- of any type -- keeps
    its stages under `stages/`, and the two pdc runs written before that keep them at the run root. A staged analysis
    work directory has no `stages/` of its own, so its files are at its root; that spelling is the same case as a
    legacy run and needs no separate branch.
    """
    root = Path(root)
    stages = root / STAGES
    return stages if stages.is_dir() else root


def _stage_bases(root):
    """The directories a stage-relative path may sit under, stage root first, then the directory itself."""
    root = Path(root)
    return (root / STAGES, root) if (root / STAGES).is_dir() else (root,)


def pdc_stage_directories(stage):
    """Every directory name that can hold the pdc stage `stage`, newest layout first."""
    try:
        return PDC_STAGE_DIRECTORIES[stage]
    except KeyError as error:
        raise ValueError(f'Unknown pdc stage {stage!r}; known stages are {sorted(PDC_STAGE_DIRECTORIES)}') from error


def pdc_stage_key(directory):
    """The stage a pdc stage directory name means, or `None` for a directory that is not one."""
    return PDC_STAGE_KEYS.get(str(directory))


def pdc_stage_path(root, stage, relative, *, directory=False):
    """One path inside a pdc stage, in either layout; `None` when neither spelling holds it.

    `root` may be the run directory, its `stages/` root, or an analysis work directory: the candidates are the
    layout's own names under `root/stages/` and under `root`, which is the same pair `_spellings` searches.
    """
    relative = Path(relative)
    for name in pdc_stage_directories(stage):
        for base in _stage_bases(root):
            path = base / name / relative
            if path.is_dir() if directory else path.is_file():
                return path
    return None


def pdc_stage_dir(root, stage):
    """The directory a pdc stage wrote, in either layout, or `None` when neither is there."""
    for name in pdc_stage_directories(stage):
        for base in _stage_bases(root):
            path = base / name
            if path.is_dir():
                return path
    return None

#: The CG topology is named for the molecule's residue (`CGNames.for_snapshot`), so it is found rather than
#: spelled. System topologies in the same directory are not molecule topologies.
CG_TOPOLOGY_DIR = '3_initial_CG'
CG_TOPOLOGY_PATTERN = '*.itp'
CG_TOPOLOGY_EXCLUDED = ('system', 'topol')

#: A protein-detergent run's detergent topology, in the directory its build stage writes: `02_system/` in the
#: numbered layout, `1_system/` before it. That directory also holds the template's atomistic copy (`detergent.itp`)
#: and the three Martini libraries the stage copies in, so "the only `.itp` here" does not select on a real run -- the
#: build's own filename does, and `PDC_TOPOLOGY_NAME` is `pdc.DETERGENT_TOPOLOGY`, spelled again here because the
#: analysis layer may not import an execution adapter.
PDC_TOPOLOGY_DIRS = PDC_STAGE_DIRECTORIES['system']
PDC_TOPOLOGY_DIR = PDC_TOPOLOGY_DIRS[0]
PDC_TOPOLOGY_NAME = 'detergent_CG.itp'


def candidates(role):
    """The relative paths that would satisfy one role, as the execution root spells them."""
    try:
        return tuple(Path(path) for path in CANDIDATES[role])
    except KeyError as error:
        raise ValueError(f'Unknown run role {role!r}; known roles are {sorted(CANDIDATES)}') from error


def _spellings(root, relative):
    """Every path that could satisfy `relative` under this root: at its root, and under `stages/`."""
    root = Path(root)
    return (root / relative, root / STAGES / relative)


def _present(root, relative):
    return tuple(path for path in _spellings(root, relative) if path.is_file())


def _looked_for(role):
    return ' or '.join([f'{path} (or {STAGES}/{path})' for path in candidates(role)])


def resolve(root, role):
    """The one path that satisfies a role, or a `ValueError` naming every candidate and which were present.

    Absence is not silence: the message carries the paths, so a report about a run can say the stage is
    missing instead of producing an empty comparison.
    """
    found = [path for relative in candidates(role) for path in _present(root, relative)]
    if len(found) == 1:
        return found[0]
    if not found:
        raise ValueError(f'{root} has no {role}; looked for ' + _looked_for(role))
    raise ValueError(f'{root} holds more than one {role}: '
                     + ', '.join(str(path) for path in found))


def _directories(directory):
    """One stage directory name, or the tuple of spellings a pdc stage may be kept under."""
    return (directory,) if isinstance(directory, str) else tuple(directory)


def _itps(root, directory):
    """Every molecule topology in one stage directory, at either root spelling, system files out."""
    return [path for name in _directories(directory)
            for spelling in _spellings(root, name)
            for path in sorted(spelling.glob(CG_TOPOLOGY_PATTERN))
            if not path.name.startswith(CG_TOPOLOGY_EXCLUDED)]


def _molecule_topology(root, directory, default_name, label, ambiguous_label, name):
    """One stage directory's molecule topology, selected by recorded name, default name, then uniqueness.

    The two run types differ only in the directory their build writes, whether a default filename answers when
    the run recorded none, and what the refusal calls the file. A recorded name the directory does not hold is
    refused naming what it does hold; a recorded name it holds twice is itself the refusal when there is no
    default name to fall back to, which is the CG consumer's case. Only a directory with one candidate and no
    recorded answer is selected by count.
    """
    root = Path(root)
    pattern = ' or '.join(f'{name}/{CG_TOPOLOGY_PATTERN}' for name in _directories(directory))
    found = _itps(root, directory)
    duplicate = None
    for wanted in (name, default_name):
        if not wanted:
            continue
        chosen = [path for path in found if path.name == wanted]
        if len(chosen) == 1:
            return chosen[0]
        if len(chosen) > 1 and duplicate is None:
            duplicate = (wanted, chosen)
    if name is not None:
        if duplicate is not None and duplicate[0] == name and default_name is None:
            raise ValueError(f'{root} holds more than one {name}: '
                             + ', '.join(str(path) for path in duplicate[1]))
        here = ', '.join(path.name for path in found) or 'nothing'
        raise ValueError(f'{root} has no {name}; under {pattern} it holds {here}')
    if len(found) == 1:
        return found[0]
    if not found:
        raise ValueError(f'{root} has no {label}; looked for {pattern} excluding {CG_TOPOLOGY_EXCLUDED}')
    raise ValueError(f'{root} holds more than one {ambiguous_label}: '
                     + ', '.join(path.name for path in found))


def cg_topology(root, name=None):
    """The CG consumer's molecule topology under `3_initial_CG/`, named for the residue.

    A fitted run leaves six `.itp` files in that directory — the seeded topology, its coordinate-seeded copy,
    Fast_Forward's annotated copy, the fitted topology the simulation ran with, and two bundled libraries — so
    "the only `.itp` here" stops being a selector as soon as a run completes. `name` is the file the run itself
    recorded (`cg_names` in its manifest, which a mapping snapshot also yields through
    `CGNames.for_snapshot`). Without a name a single `.itp` still answers; anything else is refused rather than
    ranked, because the topology an analysis reads decides which beads exist.
    """
    return _molecule_topology(root, CG_TOPOLOGY_DIR, None, 'CG molecule topology', 'CG molecule topology', name)


def pdc_topology(root, name=None):
    """The detergent moleculetype a protein-detergent run simulated, or a refusal naming what it found.

    The run's build stage writes it into `02_system/` (numbered layout) or `1_system/` (before it) under
    `pdc.DETERGENT_TOPOLOGY`, beside the template's atomistic copy and the three Martini libraries it also copies in
    -- measured on `00b9ae6db23f`: `detergent_CG.itp`, `detergent.itp` and three `martini_v3.0.0*.itp`, so a directory
    of five has no "the only one" to fall back on and the build's own name is what is looked for. `name` is the file
    the run recorded when it recorded one. A directory holding no build-name file but exactly one other molecule
    topology still answers, because an analysis subprocess is handed a *staged* directory holding only the sources
    its kind declares. Anything else is refused rather than ranked, for `cg_topology`'s reason: the topology is what
    decides which beads exist.
    """
    return _molecule_topology(root, PDC_TOPOLOGY_DIRS, PDC_TOPOLOGY_NAME, 'detergent topology',
                              'candidate detergent topology', name)


def coarse_topology(root, run_type=None, name=None):
    """The coarse-grained molecule topology a run simulated, from the directory its own layout keeps it in.

    A protein-detergent run's detergent is under `02_system/` (numbered layout) or `1_system/`, written by its build
    stage; a single-molecule CG build's molecule is under `3_initial_CG/`, written by the mapping. `run_type` decides
    when the caller has the run's own record -- the structure route does -- and a caller without one gets whichever
    layout the run wrote, because neither run type writes both.
    """
    if run_type is not None:
        return pdc_topology(root, name) if run_type == 'pdc' else cg_topology(root, name)
    try:
        return pdc_topology(root, name)
    except ValueError:
        return cg_topology(root, name)


def recorded_topology(run_dir, run_type=None, manifest=None):
    """The topology a run's own record names, or `None` when it names none that the run holds.

    `FINAL_ITP` -- recorded by every CG stage in its environment -- is the file the simulation ran with, which
    matters because a fitted run leaves several copies of the moleculetype in one directory. The manifest is
    loaded from `run_dir` when the caller does not supply it; a missing or unreadable record leaves the build's
    own default filename to answer, through `coarse_topology`. Every absent or ambiguous case is `None` rather
    than a ranked guess, because the topology is what decides which beads exist.
    """
    run_dir = Path(run_dir)
    if manifest is None:
        try:
            manifest = json.loads((run_dir / 'manifest.json').read_text())
        except (OSError, ValueError):
            manifest = {}
    name = None
    for stage in manifest.get('stages') or []:
        name = (stage.get('environment') or {}).get('FINAL_ITP')
        if name:
            break
    try:
        return coarse_topology(run_dir, run_type, name)
    except ValueError:
        return None


def rank_model(paths):
    """The CG model among a run's ITPs, best first: the fitted interaction topology, the draft, then the rest.

    A fitted stage directory holds several -- the reference the mapping was fitted against, a coordinate seed, and the
    model the simulation was built from -- and taking the first by name has already picked a seed, silently fitting
    against a different parameter set. One ranking, because three modules used to spell it out and only one of them
    also handled the names this does not know.
    """
    return sorted(paths, key=lambda path: (0 if path.stem.endswith('_ff_inter') else
                                           1 if path.stem.endswith('_initial') else 2, path.name))


def model_topology(work, name=None):
    """The topology an analysis reads out of a job's working directory, with where it came from.

    `name` is the file the run recorded (`cg_names`), which is the answer when there is one. Without it, the ranking
    above decides and the provenance says which step produced the file; a directory holding neither a fit nor a draft
    falls back to the one-topology rule, which refuses ambiguity by naming what it found rather than guessing.
    """
    work = Path(work)
    if name is not None:
        return cg_topology(work, name), 'the topology this run recorded'
    found = [path for directory in _spellings(work, CG_TOPOLOGY_DIR)
             for path in sorted(directory.glob(CG_TOPOLOGY_PATTERN))
             if not path.name.startswith(CG_TOPOLOGY_EXCLUDED)]
    ranked = rank_model(found)
    if ranked:
        best = ranked[0]
        provenance = ('the Fast_Forward fit' if best.stem.endswith('_ff_inter')
                      else 'the draft geometry, because no fit has been run for this job')
        return best, provenance
    # The sentence the two readers already answered with, kept: it says what is missing from the run, not from a glob.
    raise ValueError('no topology to compare: neither a fit nor a draft is in this run')


def _any_present(root, role):
    return any(_present(root, relative) for relative in candidates(role))


#: The trajectory a run offers for frame-by-frame review, most preferred first, as `(trajectory, structure)`
#: role pairs. A current CG run holds two of these at once -- the stage's raw `md.xtc` (system and solvent) and
#: the solute the pipeline extracted from it (`prod/lig_CG.xtc`) -- because they are two generations of one
#: artifact rather than two spellings of one, and `resolve`'s exactly-one rule would refuse such a run outright.
#: So the preference is stated here instead of ranked at runtime: the extracted solute is what a frame should
#: draw, then the stage's own production output, then its equilibration, and only then the atomistic reference
#: the model was built from. A run spelling *one* of these roles two ways is still the ambiguity `resolve` refuses.
REVIEW_SOURCES = (
    ('cg_trajectory', 'cg_structure'),
    ('cg_stage_trajectory', 'cg_stage_structure'),
    ('cg_equilibrium_trajectory', 'cg_equilibrium_structure'),
    # A protein-detergent run's CG production, whole-box first: a frame read raw shows molecules broken across the
    # periodic boundary, which is a picture of the box rather than of the system.
    ('pdc_trajectory', 'pdc_structure'),
    ('pdc_raw_trajectory', 'pdc_structure'),
    # A pdc run whose removal path is off (or that never reached the extension) still has production MD to review.
    ('pdc_assessment_trajectory', 'pdc_assessment_structure'),
    ('aa_trajectory', 'aa_structure'),
    ('legacy_aa_trajectory', 'legacy_aa_structure'),
)


class NoTrajectory(ValueError):
    """A run offers no trajectory for a caller to review.

    A subclass of `ValueError`, so a reader that refused such a run as a value error still does -- and so a caller
    that has something else to say about it can say it. The analysis layer catches *this* type to record a **skip**
    rather than a failure: a run with nothing to sample has not failed at sampling, and `frame_source`'s own message
    is what the record carries.
    """


def frame_source(root):
    """`(trajectory, structure, role)` for the one trajectory this run offers to review, by the order above.

    Which layout the run was written in is the run's own answer and not a stage name a caller supplies: an AA-only
    run publishes under `07_reference/`, a CG consumer keeps its output under `4_CG_sim/`, and the work directory
    an analysis subprocess is handed holds the same files at its root rather than under `stages/`. A run with no
    trajectory at all is a `NoTrajectory` that names every spelling it looked for, so a report can say what is
    missing instead of drawing nothing. Nothing here opens a file; the caller does.
    """
    root = Path(root)
    for trajectory_role, structure_role in REVIEW_SOURCES:
        if not _any_present(root, trajectory_role):
            continue
        return resolve(root, trajectory_role), resolve(root, structure_role), trajectory_role
    raise NoTrajectory(f'{root} offers no trajectory to review; looked for '
                       + ', then '.join(_looked_for(trajectory) for trajectory, _ in REVIEW_SOURCES))


def summary(root, topology_name=None):
    """What a run offers, by role, without raising: `{role: path or None}`, plus the CG topology.

    A panel that has to render "why is this empty" needs the absences as data, so this is the tolerant
    reader and `resolve` is the strict one.
    """
    root = Path(root)
    report = {}
    for role in CANDIDATES:
        try:
            report[role] = str(resolve(root, role).relative_to(root))
        except ValueError:
            report[role] = None
    try:
        report['cg_topology'] = str(cg_topology(root, topology_name).relative_to(root))
    except ValueError:
        report['cg_topology'] = None
    return report
