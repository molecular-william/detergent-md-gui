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
    """`{topology index: (residue, bead id)}` as the run's own files name them: residue 1, `B01`, `B02`, …

    The generated topology, the `.map`, the `.ndx` and the mapped coordinates all identify a bead by its
    position under a single residue, because that is the identity the run's tools use: `gmx grompp` reconciles a
    topology with a trajectory by atom name, and MDAnalysis — and therefore Fast_Forward's assessment — treats
    every residue as a molecule, so a molecule split across two residues stops being one molecule to it. The
    mapping's own letters and residue numbers stay available, `mapping_currency` reads them, and they are the
    language a report beside the published entry is written in.
    """
    return {index: (1, f'B{index:02d}')
            for index, bead in enumerate(mapping['beads'], 1) if not bead.get('virtual_site')}


#: The mapping's own names, for anything that has to read or label beads the way the entry does.
mapping_currency = ensemble.mapping_currency


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


def cg_samples(cg_run_dir, mapping, stride=1, limit=None, topology_name=None):
    """Per-pair distance samples over a CG run's own trajectory, keyed by the mapping's pairs.

    Units follow the trajectory, which for GROMACS is nanometres — the same unit the atomistic side is
    converted into — so the two series can be compared without a conversion at the comparison site.

    `topology_name` is the topology the run recorded for its simulated molecule. A completed run leaves several
    `.itp` files in the stage directory, and comparing against the wrong one would describe a different
    molecule; a caller that has the run's record passes the name rather than letting the reader guess.
    """
    import MDAnalysis as mda

    cg_run_dir = Path(cg_run_dir)
    trajectory = layout.resolve(cg_run_dir, 'cg_trajectory')
    structure = layout.resolve(cg_run_dir, 'cg_structure')
    topology_path = layout.cg_topology(cg_run_dir, topology_name)
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
        # MDAnalysis holds ångström; this module reports nanometres, as the atomistic side does.
        positions = np.asarray(universe.atoms.positions) / 10.0
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
            # The run's own ids (B01..) were checked above; the mapping's letters are what a report beside
            # the published entry needs, so that is what the samples carry.
            'beads': ensemble.mapping_currency(mapping), 'pairs': pairs,
            'samples': sampled, 'first': first or {}}


def labels_for(measured, pair):
    """The `[residue, bead letter]` names a pair of topology indices carries, sorted.

    Both sides label through this, from the atomistic measurement's own currency, so a row's identity is the
    mapping's language — `(2, 'A') – (2, 'B')` — rather than an index into one run's topology.
    """
    beads = measured['beads']
    return sorted(beads[index] for index in pair)


def physical_indices(mapping):
    """The zero-based positions of the beads that own atoms, which is what a rigid-body fit may use."""
    return [index for index, bead in enumerate(mapping['beads']) if not bead.get('virtual_site')]


def cg_bead_means(cg_run_dir, stride=1, limit=None, topology_name=None):
    """Mean bead positions over a coarse-grained run's trajectory, in nanometres.

    A mean position is the shape half of the comparison: constraint lengths say how big the ring is, and a
    per-bead displacement says which part of it moved. The bead count is checked against the topology,
    because averaging a trajectory read with the wrong topology produces a fluent number about nothing.
    `topology_name` names the file the run recorded for its simulated molecule; see `cg_samples`.
    """
    import MDAnalysis as mda

    cg_run_dir = Path(cg_run_dir)
    trajectory = layout.resolve(cg_run_dir, 'cg_trajectory')
    structure = layout.resolve(cg_run_dir, 'cg_structure')
    topology_path = layout.cg_topology(cg_run_dir, topology_name)
    currency = ensemble.currency(topology_path.read_text())
    universe = mda.Universe(str(structure), str(trajectory))
    if len(universe.atoms) != len(currency):
        universe.trajectory.close()
        raise ValueError(f'{trajectory} holds {len(universe.atoms)} beads but {topology_path} declares '
                         f'{len(currency)}: these are not the same system')
    totals, frames = np.zeros((len(currency), 3)), 0
    for index, _ in enumerate(universe.trajectory):
        if index % stride:
            continue
        if limit is not None and index // stride >= limit:
            break
        frames += 1
        # MDAnalysis holds ångström; this module reports nanometres.
        totals += np.asarray(universe.atoms.positions) / 10.0
    universe.trajectory.close()
    if not frames:
        raise ValueError(f'{trajectory} holds no frame to average')
    return {'run': str(cg_run_dir), 'beads': currency, 'frames': frames, 'mean': totals / frames,
            'trajectory': str(trajectory.relative_to(cg_run_dir))}


def aa_samples(aa_run_dir, mapping, molecule='Sucrose', stride=1, limit=None):
    """Per-pair samples over an atomistic reference, measured through a mapping the caller supplies.

    The mapping is supplied rather than recognised here. An analysis compares a *saved* mapping with the
    model built from it, and re-recognising would silently compare a different assignment the day the
    recognizer changes. The trailer counts are checked, because a mapping whose beads index atoms the
    trajectory does not have would otherwise be reported as a geometry difference.
    """
    import MDAnalysis as mda

    from ...models.sugars import coordinates

    aa_run_dir = Path(aa_run_dir)
    pairs = ring_pairs(mapping)
    currency = mapping_currency(mapping)
    universe = mda.Universe(str(layout.resolve(aa_run_dir, 'aa_structure')),
                            str(layout.resolve(aa_run_dir, 'aa_trajectory')))
    atoms = len(universe.atoms)
    highest = max((max(bead.get('atoms') or [0]) for bead in mapping['beads']), default=0)
    if highest > atoms:
        universe.trajectory.close()
        raise ValueError(f'the mapping names atom {highest} but {aa_run_dir} holds {atoms} atoms: '
                         'these are not the same molecule')
    sampled, first, frames = {}, None, 0
    for index, _ in enumerate(universe.trajectory):
        if index % stride:
            continue
        if limit is not None and index // stride >= limit:
            break
        frames += 1
        # The dilation the generated constraints carry is applied here too, and ångström becomes nanometres.
        xyz = np.asarray(coordinates(mapping, universe.atoms.positions.tolist(), scaled=True)) / 10.0
        centres = {bead: xyz[bead - 1] for bead in currency}
        distances = pair_distances(centres, pairs)
        if first is None:
            first = dict(distances)
        for pair, distance in distances.items():
            sampled.setdefault(pair, []).append(distance)
    universe.trajectory.close()
    return {'run': str(aa_run_dir), 'molecule': molecule, 'frames': frames, 'beads': currency,
            'pairs': pairs, 'samples': sampled, 'first': first or {}}


def aa_bead_means(aa_run_dir, mapping, stride=1, limit=None):
    """Mean bead centres over an atomistic run, through the same assignment, in nanometres.

    The dilation the generated constraints carry is applied here too, so a mean bead position and a generated
    constraint length are the same kind of number and can be read in one table.
    """
    import MDAnalysis as mda

    from ...models.sugars import coordinates

    aa_run_dir = Path(aa_run_dir)
    universe = mda.Universe(str(layout.resolve(aa_run_dir, 'aa_structure')),
                            str(layout.resolve(aa_run_dir, 'aa_trajectory')))
    totals, frames = np.zeros((len(mapping['beads']), 3)), 0
    for index, _ in enumerate(universe.trajectory):
        if index % stride:
            continue
        if limit is not None and index // stride >= limit:
            break
        frames += 1
        totals += np.asarray(coordinates(mapping, universe.atoms.positions.tolist(), scaled=True)) / 10.0
    universe.trajectory.close()
    if not frames:
        raise ValueError(f'{aa_run_dir} holds no frame to average')
    return {'run': str(aa_run_dir), 'beads': mapping_currency(mapping), 'frames': frames,
            'mean': totals / frames}


def displacement(aa, cg, physical=None):
    """Per-bead displacement and RMSD after fitting the CG means onto the AA means, in nanometres.

    The fit uses the beads that own atoms, because a virtual site is an arithmetic mean of its parents and
    fitting on it would count one constraint twice and flatter the result. The per-bead list still covers
    every bead, so a virtual site that has drifted is visible rather than hidden by the fit.
    """
    from .surfaces import align

    aa_mean, cg_mean = np.asarray(aa['mean'], dtype=float), np.asarray(cg['mean'], dtype=float)
    if aa_mean.shape != cg_mean.shape:
        raise ValueError(f'the two runs hold different bead counts: {aa_mean.shape[0]} '
                         f'against {cg_mean.shape[0]}')
    physical = list(range(aa_mean.shape[0])) if physical is None else list(physical)
    if not physical:
        raise ValueError('a rigid-body fit needs at least one bead that owns atoms')
    fitted = align(cg_mean, aa_mean, physical)
    deltas = np.linalg.norm(fitted - aa_mean, axis=1)
    labels = aa['beads']
    return {'comparison': 'AA vs CG, rigid-body fitted on the beads that own atoms',
            'rmsd_nm': float(np.sqrt(np.mean(deltas[physical] ** 2))),
            'max_nm': float(deltas.max()),
            'fit_beads': [list(labels.get(index + 1, (None, None))) for index in physical],
            'aa_frames': aa['frames'], 'cg_frames': cg['frames'],
            'per_bead': [{'bead': list(labels.get(index + 1, (None, None))),
                          'displacement_nm': float(value)} for index, value in enumerate(deltas)]}


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
