"""Solvent and ions: the two commands whose exact options decide the composition a run records.

Insane places the water; these are the two commands that follow it: the `grompp` that makes the ions topology and
`genion`, which replaces water beads in a named group after neutralising the system. The group is load-bearing -- an
unconstrained `genion` can replace a protein or detergent group -- and it asks interactively, so the stage script
pipes the water group in; these builders return the command, not the pipeline.
"""
WATER_BEADS = 'W'
ION_NAMES = ('NA', 'CL')
# The names a *structure* gives the solvent, which are not the names a topology does: GROMACS writes every inserted
# ion under the one residue name `ION`, whatever the species, while `[ molecules ]` names them `NA` and `CL`. Both
# spellings here, in one place, so a reader of either file agrees about what the solvent is.
SOLVENT_RESIDUES = (WATER_BEADS, 'ION', *ION_NAMES)


def solvation_commands(topology, structure, tpr, *, salt_molar=0.15, water_group=WATER_BEADS,
                       intermediate='solvated.gro'):
    """Add NaCl to the requested concentration after the water is in place.

    Returns the two commands in order: the `grompp` that makes the ions topology and `genion`. The concentration is
    molar, which is what `genion -conc` means, and `-neutral` runs before it so the final count is the reported one
    rather than a count the salt then changes.
    """
    if salt_molar < 0:
        raise ValueError('salt concentration cannot be negative')
    if not topology or not structure:
        raise ValueError('solvation needs a topology and a structure')
    return [
        ['gmx', 'grompp', '-f', 'ions.mdp', '-c', intermediate, '-p', topology, '-o', tpr, '-maxwarn', '1'],
        # The group is piped in by the stage: genion asks which solvent to replace, and an unanswered prompt is a
        # hung stage rather than a failed one.
        # No `-g`: the genion of this GROMACS (2026.3) has no such option and aborts before reading anything, which
        # is a stage that stops after solvation has already succeeded. Its output goes to the stage's own log.
        ['gmx', 'genion', '-s', tpr, '-o', 'system.gro', '-p', topology, '-pname', ION_NAMES[0],
         '-nname', ION_NAMES[1], '-neutral', '-conc', str(salt_molar)],
    ]


def ion_group_selection(group=WATER_BEADS):
    """The stdin a stage must pipe into `genion` so it replaces water beads and nothing else."""
    return f'{group}\n'
