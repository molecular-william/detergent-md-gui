"""The bonded terms of a mapping, measured on both ensembles.

A ring distance can agree while an angle is wrong: the generated topology carries bonds, angles and
dihedrals, and only measuring each one on both ensembles says whether the model reproduces the shape it was
fitted to. The term list comes from the coarse-grained topology that will be simulated; the values come from
the mapped atomistic trajectory and from the coarse-grained trajectory, so both sides are the same terms,
sampled twice.

Two metrics are reported and they are not interchangeable. Wasserstein is in the term's native unit and is
the project's existing distance metric (`distance_diagnostics.py` uses scipy's for the same purpose).
`overlap` is the fraction of a shared histogram the two series occupy: a plain, plainly-named number. It is
*not* the weighted modified Hellinger that Fast_Forward's assessment stage computes, which belongs to the
mapped-versus-fitted comparison and is reported there; saying they are the same number would be wrong.

The parameters beside each term are what the generated topology defines. Which reference or consensus source
supplied them lives in the bonded-state record the topology was written from, not in the ITP, and is not
claimed here.
"""
import math

import numpy as np

#: section -> how many atoms a term names, and whether its atom order is sorted (a bond has no direction).
SECTIONS = {'bonds': (2, True), 'angles': (3, False), 'dihedrals': (4, False), 'proper-dihedrals': (4, False)}


def read_terms(text):
    """A topology as `{section: [{'atoms': (...), 'function': int, 'parameters': (...)}]}`.

    Atom indices are converted to zero-based, which is what a trajectory's position array wants, and the
    parse is the one the observables analysis already used: lifted here so both callers share it rather than
    keeping two parsers that drift apart.
    """
    terms = {section: [] for section in SECTIONS}
    section = None
    for line in text.splitlines():
        body = line.split(';', 1)[0].strip()
        if body.startswith('['):
            section = body.strip('[] ').strip()
            continue
        if not body or body.startswith('#'):
            continue
        if section not in SECTIONS:
            continue
        count, sorted_atoms = SECTIONS[section]
        fields = body.split()
        try:
            atoms = tuple(int(field) - 1 for field in fields[:count])
            if len(atoms) != count or min(atoms) < 0:
                raise ValueError
        except ValueError as error:
            raise ValueError(f'Invalid {section} atom indices') from error
        try:
            function = int(fields[count])
            parameters = tuple(float(field) for field in fields[count + 1:])
        except (IndexError, ValueError):
            function, parameters = None, ()
        terms[section].append({'atoms': tuple(sorted(atoms)) if sorted_atoms else atoms,
                               'function': function, 'parameters': parameters})
    return terms


def term_sets(terms):
    """`{'bonds': set, 'angles': set, 'dihedrals': set}` — the shape a "what is missing" caller wants."""
    return {'bonds': {row['atoms'] for row in terms['bonds']},
            'angles': {row['atoms'] for row in terms['angles']},
            'dihedrals': {row['atoms'] for row in terms['dihedrals']}
                         | {row['atoms'] for row in terms['proper-dihedrals']}}


def distance_nm(positions, atoms):
    """The distance between two beads, in nanometres (GROMACS positions are angstroms)."""
    return float(np.linalg.norm(positions[atoms[0]] - positions[atoms[1]]) / 10)


def angle_deg(positions, atoms):
    """The angle at the middle bead, in degrees."""
    first, middle, last = (positions[index] for index in atoms)
    one, two = first - middle, last - middle
    cosine = float(np.dot(one, two) / (np.linalg.norm(one) * np.linalg.norm(two)))
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def dihedral_deg(positions, atoms):
    """The proper dihedral along four beads, in degrees, in the range (-180, 180]."""
    first, second, third, fourth = (positions[index] for index in atoms)
    axis = -(second - first)
    middle = third - second
    middle = middle / np.linalg.norm(middle)
    plane = axis - np.dot(axis, middle) * middle
    other = fourth - third
    other = other - np.dot(other, middle) * middle
    return math.degrees(math.atan2(float(np.dot(np.cross(middle, plane), other)), float(np.dot(plane, other))))


def measure(trajectory, structure, terms, stride=1, limit=None):
    """Every term's values over a trajectory: `{section: {atoms: [value, ...]}}`.

    One pass over the frames, because reading a trajectory twice costs seconds per hundred frames and buys
    nothing. Units are the term's own: nanometres for a bond, degrees for an angle or a dihedral.
    """
    import MDAnalysis as mda

    calculate = {'bonds': distance_nm, 'angles': angle_deg, 'dihedrals': dihedral_deg,
                 'proper-dihedrals': dihedral_deg}
    universe = mda.Universe(str(structure), str(trajectory))
    values = {section: {row['atoms']: [] for row in rows} for section, rows in terms.items()}
    frames = 0
    for index, _ in enumerate(universe.trajectory):
        if index % stride:
            continue
        if limit is not None and index // stride >= limit:
            break
        frames += 1
        positions = np.asarray(universe.atoms.positions, dtype=float)
        for section, rows in terms.items():
            for row in rows:
                atoms = row['atoms']
                if max(atoms) >= len(positions):
                    continue
                values[section][atoms].append(calculate[section](positions, atoms))
    universe.trajectory.close()
    return {'frames': frames, 'values': values,
            'source': {'trajectory': str(trajectory), 'structure': str(structure)}}


def bin_edges(anchor, bins=40, margin=0.1):
    """The shared histogram's edges, from one series padded by `margin` of its span.

    They come from the *atomistic* series rather than from both, because that series is the comparison's
    target and is the same across the runs being compared. Taking the edges from both series makes the metric
    move with the sample: a coarse-grained run with 1,001 frames has narrower observed extremes than the same
    model sampled over 20,001, the shared range shrinks with it, and a run of 10 ns scores 0.98 where the same
    model at 200 ns scores 0.62 — for the model, not for the sampling.
    """
    anchor = np.asarray(anchor, dtype=float)
    span = float(anchor.max() - anchor.min())
    return np.linspace(float(anchor.min() - margin * span), float(anchor.max() + margin * span), bins + 1)


def overlap(first, second, bins=40, anchor=None, margin=0.1):
    """The fraction of a shared histogram two series occupy: 1.0 identical, 0.0 disjoint.

    `anchor` fixes the range (see `bin_edges`); without one the first series is used. Each series gets two
    extra bins, one below and one above that range, so a value outside it is counted as outside — sharing
    nothing with the anchor's mass — rather than being folded onto the edge or dropped from the sample.
    """
    first, second = np.asarray(first, dtype=float), np.asarray(second, dtype=float)
    if not first.size or not second.size:
        raise ValueError('Overlap needs two non-empty series')
    source = first if anchor is None else np.asarray(anchor, dtype=float)
    if not source.size or float(source.max() - source.min()) <= 0:
        return 1.0
    edges = np.concatenate(([-np.inf], bin_edges(source, bins, margin), [np.inf]))
    counts_first, _ = np.histogram(first, bins=edges)
    counts_second, _ = np.histogram(second, bins=edges)
    shared = float(np.minimum(counts_first, counts_second).sum())
    return shared / max(1, min(int(counts_first.sum()), int(counts_second.sum())))


def label_for(currency, atoms):
    """A term's beads in the mapping's own names, so a row reads as `(1,A) - (1,B)`."""
    return ' - '.join(f"({currency.get(index + 1, ('?', '?'))[0]},{currency.get(index + 1, ('?', '?'))[1]})"
                      for index in atoms)


def compare_terms(aa, cg, currency=None, block_count=10, bins=40):
    """One row per term the topology defines, with the two ensembles and the two metrics.

    A term either side holds no sample for is reported as not compared rather than scored against zero, and
    the definition the topology states rides along so a disagreement can be read against the parameter that
    produced it.
    """
    from scipy.stats import wasserstein_distance

    from ..validation.geometry import block_summary

    currency = currency or {}
    rows = []
    for section in sorted(set(aa['values']) | set(cg['values'])):
        aa_terms, cg_terms = aa['values'].get(section, {}), cg['values'].get(section, {})
        for atoms in sorted(set(aa_terms) | set(cg_terms)):
            aa_values, cg_values = aa_terms.get(atoms, []), cg_terms.get(atoms, [])
            row = {'section': section, 'atoms': list(atoms), 'beads': label_for(currency, atoms),
                   'aa': None, 'cg': None, 'compared': False,
                   'delta': None, 'wasserstein': None, 'overlap': None}
            if aa_values:
                summary = block_summary(aa_values, block_count)
                row['aa'] = {'count': len(aa_values), 'mean': float(np.mean(aa_values)),
                             'std': float(np.std(aa_values)), 'stderr': summary['stderr'],
                             'min': float(np.min(aa_values)), 'max': float(np.max(aa_values))}
            if not cg_values:
                row['note'] = 'the coarse-grained run holds no sample for this term; nothing is scored'
                rows.append(row)
                continue
            summary = block_summary(cg_values, block_count)
            row['cg'] = {'count': len(cg_values), 'mean': float(np.mean(cg_values)),
                         'std': float(np.std(cg_values)), 'stderr': summary['stderr'],
                         'min': float(np.min(cg_values)), 'max': float(np.max(cg_values))}
            if not aa_values:
                row['compared'] = True
                row['note'] = 'the atomistic mapping holds no sample for this term'
                rows.append(row)
                continue
            row['compared'] = True
            row['delta'] = round(row['cg']['mean'] - row['aa']['mean'], 4)
            row['wasserstein'] = float(wasserstein_distance(aa_values, cg_values))
            if len(aa_values) > 1 and len(cg_values) > 1:
                row['overlap'] = overlap(aa_values, cg_values, bins, anchor=aa_values)
                edges = bin_edges(aa_values, bins)
                # The range the overlap was measured on, so two runs can be read against each other: with the
                # same atomistic reference it is the same range, and a reader does not have to assume that.
                row['overlap_range'] = [round(float(edges[0]), 4), round(float(edges[-1]), 4)]
            rows.append(row)
    return rows
