"""Ensemble averaging for the sugar mapping's ring geometry.

A single frame's derived constraint lengths were 0.318-0.427 nm against the reference's published 0.305-0.468, a
spread that is narrower than the published range and about 15% off at the tight end. The question the 200 ns run was
started to answer is whether that is a one-frame artefact: average the same distances over a trajectory and see
whether the mean moves towards the published value and whether the spread reaches it.

The arithmetic is pure and the trajectory is a thin shell around it, so the statistics can be tested without writing
a trajectory file.
"""
import numpy as np


def bead_centres(bead_atoms, points):
    """Centre of geometry per bead: `{bead: [x, y, z]}`, from `{bead: [atom index, ...]}` and one frame's points."""
    return {bead: np.asarray(points)[list(atoms)].mean(axis=0) for bead, atoms in bead_atoms.items() if len(atoms)}


def pair_distances(centres, pairs):
    """Distance in nanometres for each bead pair that both ends of which are present in the frame."""
    distances = {}
    for first, second in pairs:
        if first in centres and second in centres:
            distances[frozenset((first, second))] = float(np.linalg.norm(centres[first] - centres[second]))
    return distances


def summarise(samples):
    """Mean, spread and count over the frames, per pair.

    The spread is the standard deviation *and* the observed range: with a few hundred frames of a constrained ring
    the two say different things, and the published comparison is a range rather than a deviation.
    """
    summary = {}
    for pair, values in samples.items():
        values = [float(value) for value in values]
        if not values:
            continue
        summary[pair] = {'count': len(values), 'mean': float(np.mean(values)), 'std': float(np.std(values)),
                         'min': float(np.min(values)), 'max': float(np.max(values))}
    return summary


def compare(published, samples, single_frame=None):
    """The ensemble beside the reference's published value, with the single-frame number where it is known.

    `published` and `single_frame` are keyed by pair the same way the samples are. A pair the reference does not
    constrain is reported as unconstrained rather than compared against nothing.
    """
    summary = summarise(samples)
    rows = []
    for pair, stats in sorted(summary.items(), key=lambda item: str(sorted(item[0]))):
        reference = published.get(pair)
        row = {'pair': sorted(pair), **stats,
               'published_nm': reference,
               'delta_pct': (100.0 * (stats['mean'] - reference) / reference) if reference else None,
               'spread_covers_published': bool(reference and stats['min'] <= reference <= stats['max']),
               'unconstrained': reference is None}
        if single_frame and pair in single_frame:
            row['single_frame_nm'] = float(single_frame[pair])
        rows.append(row)
    return rows
