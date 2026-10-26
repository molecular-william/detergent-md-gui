"""Where a run keeps the files an analysis reads, across the two stage layouts in use.

An AA-only run publishes its solute reference under `07_reference/`. A CG consumer keeps its own atomistic
reference under `1_AA-reference/prod/`, the trajectory mapped onto the CG bead sets under `2_mapping/`, and
the coarse-grained trajectory under `4_CG_sim/prod/`. Both layouts are live in the workspace at once, so a
reader that wants "this run's atomistic trajectory" has to say which layout it found rather than falling back
to the other one: a run that holds neither, or both, is an error that names what was looked for.

Two roots are read with these roles. A caller reading a run on disk finds them under `stages/`; the work
directory an analysis subprocess is handed (`workflow.execution_root`) holds the same files at its own root,
because that is where `analysis.worker.source_entries` copies them from. Both spellings are searched, and only
two spellings of the *same* role count as an ambiguity.

Nothing here opens a file. The roles are paths, and the caller decides whether absence is fatal.
"""
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
    #: because `resolve` refuses a role spelled twice and this run holds both the whole-box and the raw file.
    'pdc_trajectory': ('4_extension/prod/whole.xtc',),
    'pdc_raw_trajectory': ('4_extension/prod/run.xtc',),
    'pdc_structure': ('4_extension/prod/run.gro',),
    #: Where a consumer run wrote its atomistic half before the reference/consumer split.
    'legacy_aa_trajectory': ('1_AA-reference/3-run.xtc',),
    'legacy_aa_structure': ('1_AA-reference/3-run.tpr',),
    'solute_topology': ('common/molecule/molecule.itp',),
}

#: The directory a run directory keeps those stages in, and which a work directory does not have.
STAGES = 'stages'

#: The CG topology is named for the molecule's residue (`CGNames.for_snapshot`), so it is found rather than
#: spelled. System topologies in the same directory are not molecule topologies.
CG_TOPOLOGY_DIR = '3_initial_CG'
CG_TOPOLOGY_PATTERN = '*.itp'
CG_TOPOLOGY_GLOB = f'{CG_TOPOLOGY_DIR}/{CG_TOPOLOGY_PATTERN}'
CG_TOPOLOGY_EXCLUDED = ('system', 'topol')

#: A protein-detergent run's detergent topology, in the directory its build stage writes: `1_system/`. That directory
#: also holds the template's atomistic copy (`detergent.itp`) and the three Martini libraries the stage copies in, so
#: "the only `.itp` here" does not select on a real run -- the build's own filename does, and `PDC_TOPOLOGY_NAME` is
#: `pdc.DETERGENT_TOPOLOGY`, spelled again here because the analysis layer may not import an execution adapter.
PDC_TOPOLOGY_DIR = '1_system'
PDC_TOPOLOGY_NAME = 'detergent_CG.itp'
PDC_TOPOLOGY_GLOB = f'{PDC_TOPOLOGY_DIR}/{CG_TOPOLOGY_PATTERN}'


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


def _itps(root, directory):
    """Every molecule topology in one stage directory, at either root spelling, system files out."""
    return [path for spelling in _spellings(root, directory)
            for path in sorted(spelling.glob(CG_TOPOLOGY_PATTERN))
            if not path.name.startswith(CG_TOPOLOGY_EXCLUDED)]


def cg_topology(root, name=None):
    """The CG consumer's molecule topology under `3_initial_CG/`, named for the residue.

    A fitted run leaves six `.itp` files in that directory — the seeded topology, its coordinate-seeded copy,
    Fast_Forward's annotated copy, the fitted topology the simulation ran with, and two bundled libraries — so
    "the only `.itp` here" stops being a selector as soon as a run completes. `name` is the file the run itself
    recorded (`cg_names` in its manifest, which a mapping snapshot also yields through
    `CGNames.for_snapshot`). Without a name a single `.itp` still answers; anything else is refused rather than
    ranked, because the topology an analysis reads decides which beads exist.
    """
    root = Path(root)
    found = _itps(root, CG_TOPOLOGY_DIR)
    if name is not None:
        chosen = [path for path in found if path.name == name]
        if len(chosen) == 1:
            return chosen[0]
        if not chosen:
            here = ', '.join(path.name for path in found) or 'nothing'
            raise ValueError(f'{root} has no {name}; under {CG_TOPOLOGY_GLOB} it holds {here}')
        raise ValueError(f'{root} holds more than one {name}: ' + ', '.join(str(path) for path in chosen))
    if len(found) == 1:
        return found[0]
    if not found:
        raise ValueError(f'{root} has no CG molecule topology; looked for '
                         f'{CG_TOPOLOGY_GLOB} excluding {CG_TOPOLOGY_EXCLUDED}')
    raise ValueError(f'{root} holds more than one CG molecule topology: '
                     + ', '.join(path.name for path in found))


def pdc_topology(root, name=None):
    """The detergent moleculetype a protein-detergent run simulated, or a refusal naming what it found.

    The run's build stage writes it into `1_system/` under `pdc.DETERGENT_TOPOLOGY`, beside the template's atomistic
    copy and the three Martini libraries it also copies in -- measured on `00b9ae6db23f`: `detergent_CG.itp`,
    `detergent.itp` and three `martini_v3.0.0*.itp`, so a directory of five has no "the only one" to fall back on
    and the build's own name is what is looked for. `name` is the file the run recorded when it recorded one. A
    directory holding no build-name file but exactly one other molecule topology still answers, because an analysis
    subprocess is handed a *staged* directory holding only the sources its kind declares. Anything else is refused
    rather than ranked, for `cg_topology`'s reason: the topology is what decides which beads exist.
    """
    root = Path(root)
    found = _itps(root, PDC_TOPOLOGY_DIR)
    for wanted in (name, PDC_TOPOLOGY_NAME):
        chosen = [path for path in found if path.name == wanted] if wanted else []
        if len(chosen) == 1:
            return chosen[0]
    if name is not None:
        here = ', '.join(path.name for path in found) or 'nothing'
        raise ValueError(f'{root} has no {name}; under {PDC_TOPOLOGY_GLOB} it holds {here}')
    if len(found) == 1:
        return found[0]
    if not found:
        raise ValueError(f'{root} has no detergent topology; looked for '
                         f'{PDC_TOPOLOGY_GLOB} excluding {CG_TOPOLOGY_EXCLUDED}')
    raise ValueError(f'{root} holds more than one candidate detergent topology: '
                     + ', '.join(path.name for path in found))


def coarse_topology(root, run_type=None, name=None):
    """The coarse-grained molecule topology a run simulated, from the directory its own layout keeps it in.

    A protein-detergent run's detergent is under `1_system/`, written by its build stage; a single-molecule CG
    build's molecule is under `3_initial_CG/`, written by the mapping. `run_type` decides when the caller has the
    run's own record -- the structure route does -- and a caller without one gets whichever layout the run wrote,
    because neither run type writes both.
    """
    if run_type is not None:
        return pdc_topology(root, name) if run_type == 'pdc' else cg_topology(root, name)
    try:
        return pdc_topology(root, name)
    except ValueError:
        return cg_topology(root, name)


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
