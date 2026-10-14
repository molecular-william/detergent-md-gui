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
    found = [path for directory in _spellings(root, CG_TOPOLOGY_DIR)
             for path in sorted(directory.glob(CG_TOPOLOGY_PATTERN))
             if not path.name.startswith(CG_TOPOLOGY_EXCLUDED)]
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
    ('aa_trajectory', 'aa_structure'),
    ('legacy_aa_trajectory', 'legacy_aa_structure'),
)


def frame_source(root):
    """`(trajectory, structure, role)` for the one trajectory this run offers to review, by the order above.

    Which layout the run was written in is the run's own answer and not a stage name a caller supplies: an AA-only
    run publishes under `07_reference/`, a CG consumer keeps its output under `4_CG_sim/`, and the work directory
    an analysis subprocess is handed holds the same files at its root rather than under `stages/`. A run with no
    trajectory at all is an error that names every spelling it looked for, so a report can say what is missing
    instead of drawing nothing. Nothing here opens a file; the caller does.
    """
    root = Path(root)
    for trajectory_role, structure_role in REVIEW_SOURCES:
        if not _any_present(root, trajectory_role):
            continue
        return resolve(root, trajectory_role), resolve(root, structure_role), trajectory_role
    raise ValueError(f'{root} offers no trajectory to review; looked for '
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
