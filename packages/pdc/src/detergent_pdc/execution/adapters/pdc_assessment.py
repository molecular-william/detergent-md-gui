"""Whether the detergents have formed the micelle a run asked for, as one function.

The project's design spec §7 decides this, so it is implemented once here and called at every time point — the
assessment report, the removal decision and the final report read the same numbers from the same code, which is what
stops one stage's verdict from disagreeing with another's.

The rule, as the spec states it: a detergent is *in the micelle* when its **tail beads** are within `contact_nm`
of another detergent's tail beads, and the resulting contact graph's largest connected cluster holds at least the
requested aggregation number. A protein-containing build additionally requires that cluster to touch the protein.
Detergents in smaller clusters are not in the micelle.

Two simplifications, stated rather than hidden:

* the spec says the cluster must touch the protein's *hydrophobic belt*. No belt is defined anywhere in this
  code base yet, so the rule is implemented at its simplest defensible form — a tail bead within `contact_nm` of
  any protein bead — and the report says so. Refining it to a belt is a change to this function and its tests.
* the input is beads, not files. The caller reads the trajectory, so this is testable without a simulation, and a
  reader can re-judge a verdict from the numbers in the artifact.
"""
from __future__ import annotations

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

CONTACT_NM = 0.6
#: A hair past the stated distance, so a KD-tree returns every pair numpy's own distance would call a contact. The
#: tree's C distance is computed in its own order and disagrees with `np.linalg.norm` in the last bits: measured, a
#: point at exactly the cutoff can be dropped by the search and one a few ulps past it can be kept. So the search is
#: a candidate filter and numpy's distance makes the decision -- the one `_within` has always made.
_SLACK = 1.0 + 1e-12


def _points(values) -> np.ndarray:
    array = np.asarray([[float(value) for value in point] for point in values], dtype=float)
    if array.size == 0:
        return array.reshape(0, 3)
    if array.ndim != 2 or array.shape[1] != 3:
        raise ValueError('coordinates must be a list of [x, y, z] points')
    if not np.isfinite(array).all():
        raise ValueError('coordinates must be finite')
    return array


def _within(one: np.ndarray, other: np.ndarray, distance_nm: float) -> bool:
    """Whether any point of `one` lies within `distance_nm` of any point of `other`."""
    if len(one) == 0 or len(other) == 0:
        return False
    distances = np.linalg.norm(one[:, None, :] - other[None, :, :], axis=2)
    return bool(distances.min() <= distance_nm)


def _bead_contacts(cloud: np.ndarray, contact_nm: float) -> np.ndarray:
    """The row pairs of `cloud` within `contact_nm` of each other, found with one KD-tree.

    The tree's search is the candidate filter and `np.linalg.norm` decides, so the answer is the pair of point sets
    `_within` would find; only the search is different. Without the slack the tree would occasionally drop a pair
    lying exactly on the cutoff and keep one a few ulps beyond it, which would move a micelle membership.
    """
    pairs = cKDTree(cloud).query_pairs(contact_nm * _SLACK, output_type='ndarray')
    if len(pairs) == 0:
        return pairs.reshape(0, 2)
    difference = cloud[pairs[:, 0]] - cloud[pairs[:, 1]]
    return pairs[np.linalg.norm(difference, axis=1) <= contact_nm]


def _touching_rows(rows: np.ndarray, protein_points: np.ndarray, reach: float) -> np.ndarray:
    """Which tail-bead rows lie within `reach` of some protein bead, `<=` exactly as `_within` means it.

    One tree for the protein beads and one query for every row; the distance is decided by numpy, not by the tree,
    for the same last-bits reason as `_bead_contacts`. A row with no protein bead in reach gets `False`.
    """
    hits = np.zeros(len(rows), dtype=bool)
    if len(rows) == 0:
        return hits
    found = cKDTree(protein_points).query_ball_point(rows, reach * _SLACK)
    counts = np.fromiter((len(neighbours) for neighbours in found), dtype=int, count=len(found))
    if counts.sum() == 0:
        return hits
    row = np.repeat(np.arange(len(rows)), counts)
    column = np.concatenate([np.asarray(neighbours, dtype=int) for neighbours in found])
    near = row[np.linalg.norm(rows[row] - protein_points[column], axis=1) <= reach]
    hits[np.unique(near)] = True
    return hits


def contact_components(tails, contact_nm: float = CONTACT_NM) -> list[list[int]]:
    """The connected components of the detergent contact graph.

    A detergent is connected to another when their tail beads come within `contact_nm`; contacts chain, so a
    detergent touching one end of an aggregate is in the same cluster as the far end even if it never comes near
    it. Returned as indices into `tails`, largest first; equal clusters keep first-member order.

    The union-find is scipy's own connected-components pass over the molecule-level edges: a Python union loop over
    the bead pairs cost 19 ms of a 22 ms frame on a 100-detergent micelle (12 000 contacts), more than the search it
    was supposed to make cheap.
    """
    if contact_nm <= 0:
        raise ValueError('the contact distance must be positive')
    points = [_points(tail) for tail in tails]
    sizes = np.array([len(point) for point in points], dtype=int)
    labels = np.arange(len(points))
    if sizes.sum() >= 2:
        # One tree over every tail bead of every detergent; a pair inside one molecule says nothing about a contact.
        owners = np.repeat(np.arange(len(points)), sizes)
        cloud = np.concatenate(points)
        left, right = _bead_contacts(cloud, contact_nm).T
        one, other = owners[left], owners[right]
        joined = one != other
        one, other = one[joined], other[joined]
        if one.size:
            graph = coo_matrix((np.ones(one.size), (one, other)), shape=(len(points), len(points)))
            _count, labels = connected_components(graph, directed=False)
    groups: dict[int, list[int]] = {}
    for index in range(len(points)):
        groups.setdefault(int(labels[index]), []).append(index)
    return sorted(groups.values(), key=lambda group: (-len(group), group[0]))


def assess_micelle(detergents, protein=None, *, contact_nm: float = CONTACT_NM, aggregation_number: int,
                   protein_contact_nm: float | None = None) -> dict:
    """The picture at one time point, in the numbers the verdict is made of.

    `detergents` is a sequence of `{'name': ..., 'tail': [[x, y, z], ...]}` in nanometres; `protein` is a list of
    protein bead points, or None for a protein-free build. The returned mapping carries the cluster sizes, the
    contact distance actually used, the largest cluster's fraction of the requested count, the protein contact
    count and the names in the micelle — every number a reader needs to disagree with the verdict without
    re-running anything.
    """
    if not detergents:
        raise ValueError('an assessment needs at least one detergent')
    if aggregation_number < 1:
        raise ValueError('the requested aggregation number must be at least one')
    names = [str(detergent.get('name') or f'D{index + 1}') for index, detergent in enumerate(detergents)]
    tails = [_points(detergent.get('tail') or []) for detergent in detergents]
    reach = CONTACT_NM if protein_contact_nm is None else float(protein_contact_nm)

    components = contact_components(tails, contact_nm)
    largest = components[0] if components else []
    protein_points = _points(protein) if protein is not None else None
    protein_free = protein_points is None or len(protein_points) == 0
    touching = []
    if protein_points is not None and len(protein_points):
        # One query for every tail bead of the largest cluster, then the per-molecule answer: a detergent touches
        # the protein when any of its own tail beads does.
        rows = np.concatenate([tails[index] for index in largest]) if largest else np.empty((0, 3))
        hits = _touching_rows(rows, protein_points, reach)
        start = 0
        for index in largest:
            stop = start + len(tails[index])
            if hits[start:stop].any():
                touching.append(index)
            start = stop
    reasons = []
    if len(largest) < aggregation_number:
        reasons.append(f'the largest cluster holds {len(largest)} of the requested {aggregation_number} detergents')
    if not protein_free and not touching:
        reasons.append(f'no detergent in the largest cluster comes within {reach:g} nm of the protein')
    # Membership is the criterion's own definition -- the largest cluster -- and it is reported whether or not the
    # verdict holds, because the removal step removes what is outside it. Ties between equal clusters break by
    # index order, so two reads of the same frame agree.
    in_micelle = [names[index] for index in largest]
    return {
        'verdict': not reasons,
        'reasons': reasons,
        'aggregation_number': aggregation_number,
        'cluster_sizes': [len(component) for component in components],
        'largest_cluster': len(largest),
        'fraction_of_requested': round(len(largest) / aggregation_number, 6),
        'contact_nm': float(contact_nm),
        'protein_contact_nm': reach,
        'protein_contact_count': len(touching),
        'protein_free': protein_free,
        'in_micelle': in_micelle,
        'detergents': names,
        'limitations': ['the protein requirement is "within the contact distance of any protein bead", not a '
                        'hydrophobic-belt test: no belt is defined in this code base yet'],
    }
