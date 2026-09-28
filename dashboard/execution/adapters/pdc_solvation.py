"""Solvent and ions: the two commands whose exact options decide the composition a run records.

Martini water is inserted at a bead radius rather than a solvent radius, and the ions are added by replacing water
beads in a named group after neutralising the system. Both details are load-bearing: the wrong radius packs too
little water, and an unconstrained `genion` can replace a protein or detergent group. `genion` asks for its group
interactively, so the stage script pipes the water group in; these builders return the command, not the pipeline.
"""
MARTINI_WATER_RADIUS_NM = 0.21
WATER_BEADS = 'W'
ION_NAMES = ('NA', 'CL')


def solvation_commands(topology, structure, tpr, *, salt_molar=0.15, water='inputs/water.gro',
                       radius_nm=MARTINI_WATER_RADIUS_NM, water_group=WATER_BEADS, intermediate='solvated.gro'):
    """Fill the box with Martini water, then add NaCl to the requested concentration.

    Returns the three commands in order: solvate, the `grompp` that makes the ions topology, and `genion`. The
    concentration is molar, which is what `genion -conc` means, and `-neutral` runs before it so the final count is
    the reported one rather than a count the salt then changes.
    """
    if salt_molar < 0:
        raise ValueError('salt concentration cannot be negative')
    if radius_nm <= 0:
        raise ValueError('the water bead radius must be positive')
    if not topology or not structure:
        raise ValueError('solvation needs a topology and a structure')
    return [
        ['gmx', 'solvate', '-cp', structure, '-cs', water, '-p', topology, '-radius', str(radius_nm),
         '-o', intermediate],
        ['gmx', 'grompp', '-f', 'ions.mdp', '-c', intermediate, '-p', topology, '-o', tpr, '-maxwarn', '1'],
        # The group is piped in by the stage: genion asks which solvent to replace, and an unanswered prompt is a
        # hung stage rather than a failed one.
        ['gmx', 'genion', '-s', tpr, '-o', 'system.gro', '-p', topology, '-pname', ION_NAMES[0],
         '-nname', ION_NAMES[1], '-neutral', '-conc', str(salt_molar), '-g', 'ions.log'],
    ]


def ion_group_selection(group=WATER_BEADS):
    """The stdin a stage must pipe into `genion` so it replaces water beads and nothing else."""
    return f'{group}\n'
