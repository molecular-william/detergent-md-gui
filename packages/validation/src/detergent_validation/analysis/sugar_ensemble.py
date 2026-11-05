"""Ensemble arithmetic for the sugar mapping's ring geometry.

A single frame of a trajectory is a noisy estimator: a bond that is constrained in the coarse-grained model still
fluctuates in the atomistic reference. This module holds the pure arithmetic the consistency analyses share --
distances between bead centres, the spread over a trajectory's frames -- and the readers that turn a run's own
topology into the bead currency a published constraint is keyed by. A report can be reproduced from an archived
run alone because everything comes from the run's immutable inputs rather than a mutable molecule directory.
"""
import numpy as np


def pair_distances(centres, pairs):
    """Distance in nanometres for each bead pair both of whose ends are present in the frame."""
    distances = {}
    for first, second in pairs:
        if first in centres and second in centres:
            distances[frozenset((first, second))] = float(np.linalg.norm(centres[first] - centres[second]))
    return distances


def summarise(samples):
    """Mean, spread and count over the frames, per pair.

    The spread is the standard deviation *and* the observed range: over a few hundred frames of a constrained ring
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




def sections(text):
    """A GROMACS topology as `{section: [row, ...]}`, comments stripped and fields split.

    The topology this project generates is written by one function, so a small reader is enough and avoids a
    dependency on the force-field machinery for a file whose shape is ours.
    """
    parsed, current = {}, None
    for line in text.splitlines():
        stripped = line.split(';')[0].strip()
        if not stripped:
            continue
        if stripped.startswith('['):
            current = stripped.strip('[] ').lower()
            parsed.setdefault(current, [])
            continue
        if current is not None:
            parsed[current].append(stripped.split())
    return parsed




def currency(topology_text):
    """The generated topology's own bead currency: bead index -> (residue number, bead name).

    This is the bridge between the distances measured on the trajectory, which are keyed by bead index, and the
    published constraints, which are keyed by residue and bead letter. Both sides of the generated topology use
    these keys, so nothing has to be inferred from a name.
    """
    table = sections(topology_text)
    return {int(row[0]): (int(row[2]), row[4]) for row in table.get('atoms', [])}


def published_constraints(entry_name):
    """The reference entry's constraint lengths, keyed by (residue name, bead letter)."""
    from dashboard.models.sugars import reference
    record = reference.entry(entry_name)
    atoms = {atom['index']: (atom['residue'], atom['name']) for atom in record['atoms']}
    return {frozenset((atoms[item['i']], atoms[item['j']])): float(item['length'])
            for item in record.get('constraints', [])}


def mapping_currency(mapping, physical_only=False):
    """`{topology index: (residue, bead letter)}` as the mapping declares it.

    The letters are read from the mapping rather than from a generated topology: every file a run consumes
    names its beads `B01..` (so that one bead has one identity across the run's files, and so that
    `gmx grompp` finds the topology and the mapped coordinates in agreement), while a report beside the
    published entry speaks the entry's language, `(2, 'A') – (2, 'B')`. This is that translation, in one
    place.
    """
    return {index: (bead.get('residue', 1), bead.get('letter') or bead['name'])
            for index, bead in enumerate(mapping['beads'], 1)
            if not (physical_only and bead.get('virtual_site'))}
