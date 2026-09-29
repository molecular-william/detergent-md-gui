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


def labels_for(measured, pair):
    """The `[residue, bead letter]` names a pair of topology indices carries, sorted.

    Both sides label through this, from the atomistic measurement's own currency, so a row's identity is the
    mapping's language — `(2, 'A') – (2, 'B')` — rather than an index into one run's topology.
    """
    beads = measured['beads']
    return sorted(beads[index] for index in pair)


def _summary(values, block_count):
    """Mean, spread, observed range and the block standard error the comparison is judged on."""
    from ..validation.geometry import block_summary
    summary = ensemble.summarise({0: values})[0]
    blocks = block_summary(values, block_count)
    return {'count': summary['count'], 'mean': summary['mean'], 'std': summary['std'],
            'min': summary['min'], 'max': summary['max'],
            'blocks': blocks['blocks'], 'stderr': blocks['stderr']}


def compare(aa, cg, reference=None, block_count=10):
    """One row per constrained pair: the two ensembles, their difference, and the two claims we may badge.

    `reference` is keyed by the pair's labels and is context: it sets no boolean, and a pair the pinned entry
    does not constrain is reported as unconstrained rather than compared against nothing. The two claims are
    both internal — the CG mean inside the AA observed range, and the CG mean inside the AA mean ± two block
    standard errors of it — because those are the only comparisons our own data can support.
    """
    reference = reference or {}
    rows = []
    for pair, values in sorted(aa['samples'].items(), key=lambda item: sorted(labels_for(aa, item[0]))):
        labels = labels_for(aa, pair)
        key = frozenset(labels)
        published = reference.get(key)
        row = {'pair': [list(label) for label in labels],
               'aa': _summary(values, block_count),
               'cg': None, 'delta_pct': None, 'compared': False,
               'inside_range': None, 'inside_spread': None,
               'reference_nm': published, 'unconstrained': published is None,
               'delta_vs_reference_pct': None}
        if published is not None:
            row['delta_vs_reference_pct'] = round(100 * (row['aa']['mean'] - published) / published, 3)
        cg_values = cg['samples'].get(pair)
        if not cg_values:
            row['note'] = 'the coarse-grained run holds no sample for this pair; nothing is scored'
            rows.append(row)
            continue
        row['cg'] = _summary(cg_values, block_count)
        row['compared'] = True
        row['delta_pct'] = round(100 * (row['cg']['mean'] - row['aa']['mean']) / row['aa']['mean'], 3)
        row['inside_range'] = bool(row['aa']['min'] <= row['cg']['mean'] <= row['aa']['max'])
        spread = 2 * row['aa']['stderr']
        row['inside_spread'] = bool(abs(row['cg']['mean'] - row['aa']['mean']) <= spread)
        rows.append(row)
    return rows


def report(aa, cg, reference=None, entry=None, block_count=10):
    """The comparison as one immutable result, saying what was compared with what.

    `comparison` names the two ensembles rather than leaving it to the reader: the same numbers appear
    beside the pinned reference in other reports, and the two are not the same claim.
    """
    rows = compare(aa, cg, reference, block_count)
    compared = [row for row in rows if row['compared']]
    outside = [row for row in compared if row['inside_range'] is False]
    return {'schema_version': 1,
            'comparison': 'AA vs CG',
            'molecule': aa.get('molecule'),
            'entry': entry,
            'aa': {'run': aa.get('run'), 'frames': max((row['aa']['count'] for row in rows), default=0)},
            'cg': {'run': cg.get('run'), 'frames': cg.get('frames'),
                   'trajectory': cg.get('trajectory'), 'topology': cg.get('topology')},
            'rows': rows,
            'counts': {'pairs': len(rows), 'compared': len(compared),
                       'cg_outside_aa_range': len(outside)},
            'reference_role': "the pinned entry's own constraint lengths, as context: they set no verdict",
            'definition': "AA is the mapping's own bead centres on the atomistic reference, dilated by the "
                          "mapping's ring scale exactly as the generated constraints are; CG is the bead "
                          "positions the simulated trajectory holds. Both are nanometres.",
            'diagnostic_only': True,
            'scientifically_validated': False,
            'interpretation': 'Agreement here says the model reproduces the structure it was built from, '
                              'which is a statement about our own system; it is not experimental evidence.'}
