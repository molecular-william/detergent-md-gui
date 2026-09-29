"""Ensemble averaging for the sugar mapping's ring geometry.

A single frame's derived constraint lengths sit within about 15% of the reference's published ones, but a single
frame of a trajectory is a noisy estimator: a bond that is constrained in the coarse-grained model still
fluctuates in the atomistic reference. This module averages the derived lengths over a whole trajectory and reports
each one beside the published value, with the spread and the observed range, so the question "is the disagreement
sampling or definition?" can be answered with numbers rather than with one frame.

The arithmetic is pure and the trajectory is a thin shell around it, so the statistics are tested without writing a
trajectory file. Everything the shell needs comes from the run's own immutable inputs -- its copy of the solute
topology and its published reference trajectory -- rather than from a mutable molecule directory, so a report can
be reproduced from an archived run alone.
"""
from pathlib import Path

import numpy as np

#: Monoisotopic-ish masses, rounded to the nearest whole number, mapped to element symbols. A nearest-mass match
#: rather than thresholds: oxygen at 15.999 is a whisker under 16, and a threshold that puts it on the wrong side
#: silently turns every alcohol into an amine -- which is exactly how a first attempt at this reported a sucrose
#: with eleven nitrogens in place of its eleven oxygens.
ELEMENTS = {1: 'H', 12: 'C', 14: 'N', 16: 'O', 31: 'P', 32: 'S'}


def element_for(mass):
    """The element whose rounded mass is nearest: unambiguous for the elements a carbohydrate contains."""
    return ELEMENTS.get(round(float(mass)), 'C')


def bead_centres(bead_atoms, points):
    """Centre of geometry per bead: `{bead: [x, y, z]}`, from `{bead: [atom index, ...]}` and one frame's points."""
    return {bead: np.asarray(points)[list(atoms)].mean(axis=0) for bead, atoms in bead_atoms.items() if len(atoms)}


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


def compare(published, samples, labels=None, single_frame=None):
    """The ensemble beside the reference's published value, one row per pair.

    `published` is keyed by pair. A pair the reference does not constrain is reported as unconstrained rather than
    compared against nothing, and a pair whose published length the observed range contains is marked, because that
    is the question a range is being asked. `single_frame` carries the same quantity from one frame where the
    caller has it: the question this started from was whether a single frame was an outlier.
    """
    summary = summarise(samples)
    rows = []
    for pair, stats in sorted(summary.items(), key=lambda item: str(sorted(item[0]))):
        reference = published.get(pair)
        row = {'pair': sorted(pair), 'label': (labels or {}).get(pair), **stats,
               'published_nm': reference,
               'delta_pct': (100.0 * (stats['mean'] - reference) / reference) if reference else None,
               'spread_covers_published': bool(reference and stats['min'] <= reference <= stats['max']),
               'unconstrained': reference is None}
        if single_frame and pair in single_frame:
            row['single_frame_nm'] = float(single_frame[pair])
        rows.append(row)
    return rows


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


def read_solute(run_dir):
    """The solute's atoms, bonds and one frame of coordinates, in Angstrom, from the run's own inputs.

    Coordinates come from the published reference's `lig.gro` (nanometres, so scaled by ten) and the connectivity
    from the run's copy of the molecule topology. The two are the same atom order -- the run built one from the
    other -- and that is checked rather than assumed, because a silent mismatch would produce a report about a
    different molecule.
    """
    stages = Path(run_dir) / 'stages'
    topology = stages / 'common/molecule/molecule.itp'
    text = topology.read_text()
    if '[ atoms ]' not in text:
        # The prepared entry point may be a one-line include of the molecule's own topology; the first token of
        # that line is the directive, so the filename is what follows it.
        include = next((line.split(maxsplit=1)[1].strip().strip('"') for line in text.splitlines()
                        if line.strip().startswith('#include')), None)
        if include:
            topology = topology.parent / include
            text = topology.read_text()
    table = sections(text)
    gro = stages / '07_reference/lig.gro'
    lines = gro.read_text().splitlines()
    count = int(lines[1].split()[0])
    if count != len(table['atoms']):
        raise ValueError(f'{gro} holds {count} atoms but {topology} declares {len(table["atoms"])}: '
                         'these are not the same molecule')
    coordinates = [[float(line[20:28]) * 10.0, float(line[28:36]) * 10.0, float(line[36:44]) * 10.0]
                   for line in lines[2:2 + count]]
    atoms = [{'id': int(row[0]), 'element': element_for(row[7]), 'heavy': float(row[7]) >= 2.0, 'xyz': xyz}
             for row, xyz in zip(table['atoms'], coordinates)]
    return {'atoms': atoms, 'bonds': [[int(row[0]), int(row[1])] for row in table.get('bonds', [])]}


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
    from ..models.sugars import reference
    record = reference.entry(entry_name)
    atoms = {atom['index']: (atom['residue'], atom['name']) for atom in record['atoms']}
    return {frozenset((atoms[item['i']], atoms[item['j']])): float(item['length'])
            for item in record.get('constraints', [])}


def samples(run_dir, molecule='Sucrose', stride=1, limit=None):
    """Per-pair distance samples over a run's own atomistic trajectory, before any comparison.

    Split out of `run` so a second consumer can reuse the measurement instead of copying its loop: the
    comparison against a coarse-grained run needs the same pairs, measured on the same assignment, and two
    copies of this loop would eventually disagree. The trajectory and structure are resolved by role, so
    this reads an AA-only run's published reference and a CG consumer's own atomistic reference alike.
    """
    import MDAnalysis as mda

    from ..models.sugars import candidate, coordinates, ring_pairs, topology
    from .runs import layout

    run_dir = Path(run_dir)
    solute = read_solute(run_dir)
    mapping = candidate(solute, molecule)
    text = topology(mapping, solute)
    beads = currency(text)
    pairs = list(ring_pairs(mapping))

    universe = mda.Universe(str(layout.resolve(run_dir, 'aa_structure')),
                            str(layout.resolve(run_dir, 'aa_trajectory')))
    sampled, first = {}, None
    for index, _ in enumerate(universe.trajectory):
        if index % stride:
            continue
        if limit is not None and index // stride >= limit:
            break
        xyz = np.asarray(coordinates(mapping, universe.atoms.positions.tolist(), scaled=True)) / 10.0
        centres = {bead: xyz[bead - 1] for bead in beads}
        distances = pair_distances(centres, pairs)
        if first is None:
            first = dict(distances)
        for pair, distance in distances.items():
            sampled.setdefault(pair, []).append(distance)
    universe.trajectory.close()
    return {'molecule': molecule, 'run': str(run_dir), 'beads': beads, 'pairs': pairs,
            'samples': sampled, 'first': first or {}}


def run(run_dir, molecule='Sucrose', entry_name='SUCR', stride=1, limit=None):
    """Average a completed run's ring geometry and report it beside the published constraints.

    One recognition and one topology are enough for the whole trajectory: the atom assignment does not change
    between frames, so only the distances are recomputed, which is what makes a few hundred frames cheap.

    The reference entry is named by the caller rather than guessed from the molecule's identity: matching a
    candidate's bead pairs against every entry would be a heuristic, and a report that says which entry it compared
    against is worth more than one that silently picked the closest name.
    """
    measured = samples(run_dir, molecule, stride, limit)
    beads, sampled = measured['beads'], measured['samples']
    published = published_constraints(entry_name)
    translated = {pair: published.get(frozenset(beads[index] for index in pair)) for pair in sampled}
    labels = {pair: sorted(beads[index] for index in pair) for pair in sampled}
    return {'molecule': molecule, 'entry': entry_name,
            'frames': max((len(values) for values in sampled.values()), default=0),
            'rows': compare(translated, sampled, labels, measured['first'])}


def format_report(result):
    """The report as plain text, one line per constraint."""
    lines = [f"{result['molecule']} · {result['frames']} frames · reference entry {result['entry']}",
             f'{"constraint":>18s} {"published":>10s} {"mean":>9s} {"std":>7s} {"range":>17s} {"delta":>8s} covered']
    for row in result['rows']:
        label = row['label'] or row['pair']
        published = '—' if row['published_nm'] is None else f"{row['published_nm']:.3f}"
        delta = '—' if row['delta_pct'] is None else f"{row['delta_pct']:+.1f}%"
        lines.append(f"{str(label):>18s} {published:>10s} {row['mean']:9.4f} {row['std']:7.4f} "
                     f"{row['min']:8.4f}-{row['max']:8.4f} {delta:>8s} {str(row['spread_covers_published'])}")
    return '\n'.join(lines)
