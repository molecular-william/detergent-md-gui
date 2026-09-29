"""The coarse-grained side of the comparison: the same pairs, measured on the run that simulated them.

`models/sugars` decides which atoms form which bead, and `sugar_ensemble` measures those beads on the
atomistic reference. Neither reads a coarse-grained run, so nothing in the repository could answer the
question the mapping exists to answer: does the model we simulate hold the geometry it was built from.

This module is that reader. It refuses the two ways it could quietly describe the wrong system — a
trajectory whose bead count disagrees with the topology it is read with, and a topology whose bead names
disagree with the mapping being checked — because either mistake produces a fluent report about a
different molecule.
"""
from pathlib import Path

import numpy as np

from .. import sugar_ensemble as ensemble
from ..sugar_ensemble import pair_distances
from . import layout


def expected_currency(mapping):
    """`{topology index: (residue, bead letter)}` for the physical beads, in the order a writer emits them.

    The generated topology is written from the mapping, so a bead's index is its position in that list;
    that is the bridge between a distance measured on a trajectory and the pair the mapping constrains.
    """
    return {index: (bead.get('residue', 1), bead.get('letter') or bead['name'])
            for index, bead in enumerate(mapping['beads'], 1) if not bead.get('virtual_site')}


def ring_pairs(mapping):
    """The pairs a generated topology constrains, as topology index pairs."""
    from ...models.sugars import ring_pairs as pairs_of
    return list(pairs_of(mapping))


def check_currency(topology_text, mapping, source='the CG topology'):
    """The topology's bead identity must be the mapping's, index for index.

    An empty mismatch list is a claim: the trajectory read with this topology is the system the mapping
    describes. Anything else raises with the first few disagreements, because a silent mismatch would be
    reported as a geometry difference.
    """
    currency = ensemble.currency(topology_text)
    expected = expected_currency(mapping)
    mismatched = {index: (currency.get(index), name) for index, name in expected.items()
                  if currency.get(index) != name}
    if mismatched:
        first = sorted(mismatched.items())[:3]
        raise ValueError(f'{source} does not describe this mapping: '
                         + ', '.join(f'index {index} is {found} where the mapping has {wanted}'
                                     for index, (found, wanted) in first))
    return currency


def cg_samples(cg_run_dir, mapping, stride=1, limit=None):
    """Per-pair distance samples over a CG run's own trajectory, keyed by the mapping's pairs.

    Units follow the trajectory, which for GROMACS is nanometres — the same unit the atomistic side is
    converted into — so the two series can be compared without a conversion at the comparison site.
    """
    import MDAnalysis as mda

    cg_run_dir = Path(cg_run_dir)
    trajectory = layout.resolve(cg_run_dir, 'cg_trajectory')
    structure = layout.resolve(cg_run_dir, 'cg_structure')
    topology_path = layout.cg_topology(cg_run_dir)
    currency = check_currency(topology_path.read_text(), mapping, source=str(topology_path))
    pairs = ring_pairs(mapping)

    universe = mda.Universe(str(structure), str(trajectory))
    beads = len(universe.atoms)
    if beads != len(currency):
        universe.trajectory.close()
        raise ValueError(f'{trajectory} holds {beads} beads but {topology_path} declares {len(currency)}: '
                         'these are not the same system')
    sampled, first, frames = {}, None, 0
    for index, _ in enumerate(universe.trajectory):
        if index % stride:
            continue
        if limit is not None and index // stride >= limit:
            break
        frames += 1
        positions = np.asarray(universe.atoms.positions)
        centres = {bead: positions[bead - 1] for bead in currency}
        distances = pair_distances(centres, pairs)
        if first is None:
            first = dict(distances)
        for pair, distance in distances.items():
            sampled.setdefault(pair, []).append(distance)
    universe.trajectory.close()
    return {'run': str(cg_run_dir), 'frames': frames,
            'trajectory': str(trajectory.relative_to(cg_run_dir)),
            'topology': str(topology_path.relative_to(cg_run_dir)),
            'beads': currency, 'pairs': pairs, 'samples': sampled, 'first': first or {}}
