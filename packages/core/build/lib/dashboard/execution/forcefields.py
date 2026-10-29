"""The single-solute force fields a run may be prepared with.

One entry per force field, and one place that decides what choosing it implies: which tree is copied into a run,
which water and ion molecules the topology includes, the temperature its parameterisation assumes, the mdp
settings GROMACS prescribes for it, and where the tree came from. A run records the entry it resolved, so its
manifest cannot later be read against a different set of rules than the one it ran under.

The temperatures follow the reference protocol this project reproduces (Grünewald et al., JCTC 2022,
10.1021/acs.jctc.2c00757, whose constraints are pinned in references/martini_v3.0.0_sugars_v2.source.json).

`constraints` is deliberately **not** the value the GROMACS manual lists for CHARMM36: the manual says
`h-bonds`, the paper says all bonds restrained with LINCS. The manual's value is kept beside the effective one so
that the deviation is visible in the entry rather than buried in an mdp file. If a run is meant to follow the
manual instead, the entry is where that changes, not a caller.
"""
from dataclasses import dataclass
from pathlib import Path

from . import environment

#: The GROMACS manual's recommended settings for CHARMM36, verbatim, minus the constraints line (see the note
#: above): a Verlet neighbour list with a force-switched cut-off and PME.
MANUAL_CHARMM36 = {
    'cutoff-scheme': 'Verlet',
    'vdwtype': 'Cut-off',
    'vdw-modifier': 'Force-switch',
    'rlist': 1.2,
    'rvdw': 1.2,
    'rvdw-switch': 1.0,
    'coulombtype': 'PME',
    'rcoulomb': 1.2,
    'DispCorr': 'no',
}


@dataclass(frozen=True)
class ForceField:
    """What one force field implies. Data only; every accessor below reads it and nothing derives from a name."""

    name: str
    label: str
    directory: str
    water_file: str
    water_molecule: str
    cation: str
    anion: str
    temperature_k: float
    constraints: str
    manual_constraints: str
    mdp: dict
    source: str
    archive_sha256: str | None
    parameterizations: tuple

    def tree(self) -> Path:
        return environment.AA_TEMPLATE / self.directory


ENTRIES = {
    # The February 2026 port, CGenFF 4.6 variant: the one our solutes can be paired with, since the MacKerell Lab
    # warns the CGenFF file version must match the version that generated a solute's topology.
    'charmm36-feb2026_cgenff-4.6': ForceField(
        name='charmm36-feb2026_cgenff-4.6',
        label='CHARMM36m (Feb 2026, CGenFF 4.6)',
        directory='charmm36-feb2026_cgenff-4.6.ff',
        water_file='tip3p.itp', water_molecule='SOL', cation='SOD', anion='CLA',
        temperature_k=303.15, constraints='all-bonds', manual_constraints='h-bonds',
        mdp=dict(MANUAL_CHARMM36),
        source='http://mackerell.umaryland.edu/download.php?filename=CHARMM_ff_params_files/charmm36-feb2026_cgenff-4.6.ff.tgz',
        archive_sha256='7041529806f849b7f2f0b68b0be211a7d93103e38f0b4f2d2b6168e84c9cc6a9',
        parameterizations=('cgenff-4.6',),
    ),
    # Kept so the completed 200 ns run stays interpretable: it ran with this tree, and a manifest naming it should
    # still resolve to a real entry rather than to an error.
    'charmm36-jul2022': ForceField(
        name='charmm36-jul2022',
        label='CHARMM36 (Jul 2022)',
        directory='charmm36-jul2022.ff',
        water_file='tip3p.itp', water_molecule='SOL', cation='SOD', anion='CLA',
        temperature_k=303.15, constraints='all-bonds', manual_constraints='h-bonds',
        mdp=dict(MANUAL_CHARMM36),
        source='http://mackerell.umaryland.edu/charmm_ff.shtml',
        archive_sha256=None,
        parameterizations=('cgenff-4.6',),
    ),
}

#: The entry a run uses when the request does not name one.
DEFAULT = 'charmm36-feb2026_cgenff-4.6'


def names():
    """Every force field a run may ask for, in a stable order."""
    return tuple(ENTRIES)


def entry(name=None):
    """The entry for `name`, or the default.

    An unknown name is an error rather than a fallback: silently running one force field when another was asked
    for would make two incomparable runs look comparable.
    """
    resolved = DEFAULT if name in (None, '') else name
    try:
        return ENTRIES[resolved]
    except KeyError:
        raise ValueError(f'unknown force field {resolved!r}; known: {", ".join(names())}') from None
