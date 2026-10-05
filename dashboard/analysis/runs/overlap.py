"""How faithfully a coarse-grained model reproduces its atomistic reference, per bead pair.

The coefficient here is the **overlap coefficient** -- the intersection of two probability densities -- and not the
Bhattacharyya coefficient or a Kullback-Leibler divergence. The three are routinely confused by name, and only the
overlap coefficient is bounded by 1 and symmetric, which is what lets a matrix of it be read as a matrix at all.

The method is shaker's (`Martini-Force-Field-Initiative/shaker`, LGPL-2.1, `shaker/overlap.py`), reimplemented from
its definition rather than imported: the arithmetic is a histogram intersection, and depending on that package would
bring nglview and rdkit -- its whole stack -- for about fifty lines. `docs/design/2026-10-05-shaker-and-taster-
assessment.md` records why, and the comparison that validated this against shaker's own output.
"""
import itertools
import json
from pathlib import Path

import MDAnalysis as mda
import numpy as np


def overlap_coefficient(histogram_a, histogram_b, bins):
    """The overlap coefficient of two densities over the same bins: `sum(min(a, b)) * bin_width`.

    Both sides must be densities (`numpy.histogram(..., density=True)`), not counts: the coefficient is the shared
    *probability*, so counts answer a different question and inflate with the sample size. The two are required to
    have the same shape rather than being broadcast, because a comparison between different bin sets reads exactly
    like a comparison between the same one.
    """
    a = np.asarray(histogram_a, dtype=float)
    b = np.asarray(histogram_b, dtype=float)
    edges = np.asarray(bins, dtype=float)
    if edges.size < 2:
        raise ValueError('an overlap needs at least two bin edges to read a width from')
    if a.shape != b.shape:
        raise ValueError(f'both sides must be measured on the same bins, not {a.shape} against {b.shape}')
    if a.size != edges.size - 1:
        raise ValueError(f'{a.size} values cannot be read against {edges.size - 1} bins')
    return float(np.sum(np.minimum(a, b)) * (edges[1] - edges[0]))


def intra_bead_distances(universe, residue_name, *, bins=None, bin_count=40, **window):
    """The series and its densities in one call, for a measurement that is not being compared with another.

    A comparison wants `bead_distance_series` twice and `densities` over one shared range; see `publish`.
    """
    return densities(bead_distance_series(universe, residue_name, **window), bins=bins, bin_count=bin_count)


def bead_distance_series(universe, residue_name, *, bead_names=None, start=0, stop=None, stride=1):
    """Every pairwise intra-residue bead distance, per frame, from one read of the trajectory.

    Split from the binning so that a caller comparing two ensembles reads each of them **once**: the bins have to span
    both, and deriving them from one side while measuring the other is exactly the mistake this split avoids.

    Distances are nanometres. MDAnalysis reports angstroms, and the conversion happens here rather than at each
    reader: a beads file read in angstroms is a factor-of-ten error that looks like a model that is merely loose.
    """
    residues = universe.select_atoms(f'resname {residue_name}').residues
    if not len(residues):
        raise ValueError(f'no residue named {residue_name} in this trajectory')
    available = list(residues[0].atoms.names)
    names = list(bead_names) if bead_names else list(dict.fromkeys(available))
    missing = [name for name in names if name not in available]
    if missing:
        raise ValueError(f'{residue_name} has no bead named {", ".join(missing)}; it has {", ".join(available)}')
    pairs = list(itertools.combinations(names, 2))
    if not pairs:
        raise ValueError('an overlap needs at least two beads before there is a pair to measure')
    position = {name: i for i, name in enumerate(available)}
    wanted = [position[name] for name in names]
    endpoints = [(names.index(a), names.index(b)) for a, b in pairs]

    frames = list(range(*slice(start, stop, stride).indices(len(universe.trajectory))))
    collected = {pair: [] for pair in pairs}
    for frame in frames:
        universe.trajectory[frame]
        for residue in residues:
            # MDAnalysis reports angstroms; every length in this repository is nanometres.
            positions = np.asarray(residue.atoms.positions, dtype=float)[wanted] / 10.0
            for pair, (i, j) in zip(pairs, endpoints):
                collected[pair].append(float(np.linalg.norm(positions[i] - positions[j])))

    series = {pair: np.asarray(values, dtype=float) for pair, values in collected.items()}
    return {'bead_names': names, 'pairs': pairs, 'series': series,
            'range_nm': (float(min(v.min() for v in series.values())), float(max(v.max() for v in series.values()))),
            'frames': len(frames), 'residues': len(residues)}


def densities(measured, bins=None, bin_count=40):
    """Density histograms of a measured series, over `bins` or over a range spanning what was measured."""
    pairs = list(measured['pairs'])
    edges = (np.asarray(bins, dtype=float) if bins is not None
             else np.linspace(measured['range_nm'][0], measured['range_nm'][1] or 1.0, bin_count + 1))
    if edges.size < 2 or np.any(np.diff(edges) <= 0):
        raise ValueError('bins must be increasing edges, or the density cannot be read')
    histogram = np.vstack([np.histogram(measured['series'][pair], bins=edges, density=True)[0] for pair in pairs])
    if not np.isfinite(histogram).all():
        # A pair whose distance never varies over a zero-width range: refused here rather than carried into a
        # coefficient as a nan, which would silently poison a whole matrix cell.
        raise ValueError('a pair has no measurable spread over these bins')
    return {'bead_names': list(measured['bead_names']), 'pairs': pairs, 'bins': edges, 'hist': histogram,
            'mean_nm': [float(measured['series'][pair].mean()) for pair in pairs],
            'range_nm': measured['range_nm'], 'frames': measured['frames'], 'residues': measured['residues']}


def overlap_matrix(reference, model):
    """The overlap coefficient for every measured pair, as a symmetric matrix, and a mean per bead.

    `reference` and `model` are two measurements from `intra_bead_distances`, over the same beads, the same pairs and
    the same bins. Anything else is refused rather than intersected or broadcast: an intersection compares a subset of
    the pairs and reports the result under the whole name, and a broadcast compares values never measured against
    those edges.

    Reading it: 1 is two distributions that coincide over these bins, 0 is two that share no bin at all. The diagonal
    is 1 by construction -- a bead against itself -- so it is left out of every per-bead mean, and each mean is taken
    over the pairs that bead actually appears in rather than over every cell, so an unmeasured pair cannot read as a
    zero and drag a bead down.
    """
    names = list(reference['bead_names'])
    if names != list(model['bead_names']):
        raise ValueError(f'the two sides must name the same beads in the same order, not {names} against '
                         f'{list(model["bead_names"])}')
    if list(reference['pairs']) != list(model['pairs']):
        raise ValueError(f'the two sides must be measured over the same pairs, not {len(reference["pairs"])} '
                         f'against {len(model["pairs"])}')
    if np.shape(reference['bins']) != np.shape(model['bins']) or not np.allclose(reference['bins'], model['bins']):
        raise ValueError('the two sides must be measured over the same bins')

    position = {name: i for i, name in enumerate(names)}
    matrix = np.eye(len(names))
    overlaps = []
    incident = {name: [] for name in names}
    for pair, reference_histogram, model_histogram in zip(reference['pairs'], reference['hist'], model['hist']):
        coefficient = overlap_coefficient(reference_histogram, model_histogram, reference['bins'])
        overlaps.append(coefficient)
        incident[pair[0]].append(coefficient)
        incident[pair[1]].append(coefficient)
        i, j = position[pair[0]], position[pair[1]]
        matrix[i, j] = matrix[j, i] = coefficient
    return {'matrix': matrix, 'overlaps': overlaps, 'pairs': list(reference['pairs']), 'bead_names': names,
            'per_bead_mean': [{'bead': name, 'mean': float(np.mean(incident[name])) if incident[name] else None}
                              for name in names]}


REFERENCE = ('1_AA-reference/prod/lig.gro', '1_AA-reference/prod/lig.xtc')
MODEL = '2_mapping/model.json'
SIMULATION = ('4_CG_sim/prod/lig_CG.gro', '4_CG_sim/prod/lig_CG.xtc')
REPORT = 'overlap.json'
FIGURE = 'overlap.html'
BIN_COUNT = 40


def publish(work, payload=None):
    """Compare a run's coarse-grained simulation with the atomistic reference it was built from, pair by pair.

    `work` is the analysis's own directory, holding what the worker's `PATTERNS` staged: the reference, the model and
    the CG trajectory. Writes `overlap.json` and a self-contained `overlap.html`, and returns the record.

    Each side is read once, and both are then binned over **one range spanning the two**. A range that stopped at the
    reference's longest distance would drop every model distance beyond it, and a dropped sample reads as a model that
    does not overlap rather than as a range that was too short.

    The metric is the overlap coefficient -- the histogram intersection -- and the report says so, because
    "overlap 0.6" means something different again as a Bhattacharyya coefficient and a reader deserves to know which
    one they have.
    """
    work = Path(work)
    payload = payload or {}
    beads = [bead['export_name'] for bead in json.loads((work / MODEL).read_text())['beads']]
    window = {'start': int(payload.get('start', 0)), 'stop': payload.get('stop'),
              'stride': int(payload.get('stride', 1))}
    universes = {'reference': mda.Universe(str(work / REFERENCE[0]), str(work / REFERENCE[1])),
                 'model': mda.Universe(str(work / SIMULATION[0]), str(work / SIMULATION[1]))}
    residue = str(universes['model'].residues[0].resname)

    series = {side: bead_distance_series(universe, residue, bead_names=beads, **window)
              for side, universe in universes.items()}
    edges = np.linspace(min(data['range_nm'][0] for data in series.values()),
                        max(data['range_nm'][1] for data in series.values()), BIN_COUNT + 1)
    measured = {side: densities(data, bins=edges) for side, data in series.items()}
    comparison = overlap_matrix(measured['reference'], measured['model'])

    paths = {'reference': {'gro': REFERENCE[0], 'xtc': REFERENCE[1]},
             'model': {'gro': SIMULATION[0], 'xtc': SIMULATION[1]}}
    record = {
        'residue': residue,
        'bead_names': comparison['bead_names'],
        'pairs': [list(pair) for pair in comparison['pairs']],
        'matrix': comparison['matrix'].tolist(),
        'overlaps': comparison['overlaps'],
        'per_bead_mean': comparison['per_bead_mean'],
        'bins': edges.tolist(),
        'range_nm': [float(edges[0]), float(edges[-1])],
        'mean_nm': {side: data['mean_nm'] for side, data in measured.items()},
        'frames': {side: data['frames'] for side, data in series.items()},
        'residues': {side: data['residues'] for side, data in series.items()},
        'trajectories': {side: {**paths[side], 'frames': series[side]['frames'],
                                'residues': series[side]['residues']} for side in series},
        'method': 'overlap coefficient (histogram intersection) of intra-residue bead distance densities, '
                  'assessed against the atomistic reference the model was built from',
        'figure': FIGURE,
        'report': REPORT,
        'limitations': [
            'Intra-residue bead distances only: a pair whose beads sit in different residues is not measured, so the '
            'interaction that spans two residues is outside this report.',
            'One bin range spans every pair, so a short pair is binned more coarsely than a long one. The range is '
            'the union of both ensembles, not either one of them.',
            'The comparison is against the atomistic reference this model was built from, not against experiment: '
            'agreement here is internal consistency and cannot make the model experimentally right.',
            'A model can agree here and still be wrong where the reference itself is wrong, which this analysis '
            'cannot see.',
        ],
        'scientifically_validated': False,
    }
    (work / REPORT).write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    _figure(comparison, work / FIGURE)
    return record


def _figure(comparison, path):
    """A self-contained heatmap, because a matrix of numbers is read as a picture or not at all."""
    import plotly.graph_objects as go

    names = comparison['bead_names']
    figure = go.Figure(go.Heatmap(z=comparison['matrix'], x=names, y=names, zmin=0.0, zmax=1.0, colorscale='Blues',
                                  hovertemplate='%{y} – %{x}: %{z:.3f}<extra></extra>',
                                  colorbar={'title': 'overlap'}))
    figure.update_layout(title='AA/CG bead overlap · 1 = the two distributions coincide',
                         height=max(460, 36 * len(names)), margin={'l': 70, 'r': 20, 't': 60, 'b': 60},
                         xaxis_title='bead', yaxis_title='bead')
    figure.write_html(str(path), include_plotlyjs=True)
