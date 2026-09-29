"""Where a run keeps the files an analysis reads, across the two stage layouts in use.

An AA-only run publishes its solute reference under `stages/07_reference/`. A CG consumer keeps its own
atomistic reference under `stages/1_AA-reference/prod/`, the trajectory mapped onto the CG bead sets under
`stages/2_mapping/`, and the coarse-grained trajectory under `stages/4_CG_sim/prod/`. Both layouts are live
in the workspace at once, so a reader that wants "this run's atomistic trajectory" has to say which layout
it found rather than falling back to the other one: a run that holds neither, or both, is an error that
names what was looked for.

Nothing here opens a file. The roles are paths, and the caller decides whether absence is fatal.
"""
from pathlib import Path

#: role -> the relative paths looked for, in order. Only one may exist.
CANDIDATES = {
    'aa_trajectory': ('stages/07_reference/lig.xtc', 'stages/1_AA-reference/prod/lig.xtc'),
    'aa_structure': ('stages/07_reference/lig.gro', 'stages/1_AA-reference/prod/lig.gro'),
    'mapped_trajectory': ('stages/2_mapping/mapped.xtc',),
    'mapped_structure': ('stages/2_mapping/mapped.gro',),
    'cg_trajectory': ('stages/4_CG_sim/prod/lig_CG.xtc',),
    'cg_structure': ('stages/4_CG_sim/prod/lig_CG.gro',),
    'solute_topology': ('stages/common/molecule/molecule.itp',),
}

#: The CG topology is named for the molecule's residue (`CGNames.for_snapshot`), so it is found rather than
#: spelled. System topologies in the same directory are not molecule topologies.
CG_TOPOLOGY_GLOB = 'stages/3_initial_CG/*.itp'
CG_TOPOLOGY_EXCLUDED = ('system', 'topol')


def candidates(role):
    """The relative paths that would satisfy one role."""
    try:
        return tuple(Path(path) for path in CANDIDATES[role])
    except KeyError as error:
        raise ValueError(f'Unknown run role {role!r}; known roles are {sorted(CANDIDATES)}') from error


def resolve(run_dir, role):
    """The one path that satisfies a role, or a `ValueError` naming every candidate and which were present.

    Absence is not silence: the message carries the paths, so a report about a run can say the stage is
    missing instead of producing an empty comparison.
    """
    run_dir = Path(run_dir)
    found = [path for path in candidates(role) if (run_dir / path).is_file()]
    if len(found) == 1:
        return run_dir / found[0]
    if not found:
        raise ValueError(f'{run_dir} has no {role}; looked for '
                         + ', '.join(str(path) for path in candidates(role)))
    raise ValueError(f'{run_dir} holds more than one {role}: '
                     + ', '.join(str(path) for path in found))


def cg_topology(run_dir):
    """The CG consumer's molecule topology under `stages/3_initial_CG/`, named for the residue.

    Two matches are refused rather than ranked: the topology an analysis reads decides which beads exist,
    and picking the first glob hit is how a comparison ends up describing a different molecule.
    """
    run_dir = Path(run_dir)
    found = sorted(path for path in run_dir.glob(CG_TOPOLOGY_GLOB)
                   if not path.name.startswith(CG_TOPOLOGY_EXCLUDED))
    if len(found) == 1:
        return found[0]
    if not found:
        raise ValueError(f'{run_dir} has no CG molecule topology; looked for '
                         f'{CG_TOPOLOGY_GLOB} excluding {CG_TOPOLOGY_EXCLUDED}')
    raise ValueError(f'{run_dir} holds more than one CG molecule topology: '
                     + ', '.join(path.name for path in found))


def summary(run_dir):
    """What a run offers, by role, without raising: `{role: path or None}`, plus the CG topology.

    A panel that has to render "why is this empty" needs the absences as data, so this is the tolerant
    reader and `resolve` is the strict one.
    """
    run_dir = Path(run_dir)
    report = {}
    for role in CANDIDATES:
        try:
            report[role] = str(resolve(run_dir, role).relative_to(run_dir))
        except ValueError:
            report[role] = None
    try:
        report['cg_topology'] = str(cg_topology(run_dir).relative_to(run_dir))
    except ValueError:
        report['cg_topology'] = None
    return report
