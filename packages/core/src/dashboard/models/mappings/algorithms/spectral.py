"""The cg_param_m3 spectral mapping algorithm, its mapping half only.

Ported from cg_param_m3 (`martini3_v3/cg_param_m3.py`, github.com/cgkmw-durham/cg_param_m3): the
weighted adjacency, the eigenvector-centrality ranking, three pairing rounds that join a node to its
most central bonded neighbour while the bead stays inside the cap, and the lone-atom path
contraction. Its parameterisation -- the Delta-G bead types, alogP tuning and the itp/gro writers --
is out of scope and not ported.

Two things differ from upstream on purpose. Rings are the sugar layer's: it produces the ring beads
and their TC4 sites, and only the atoms no ring claimed are partitioned here, so a carbohydrate's
four-bead ring layer is not re-derived by a spectral guess. And the atoms are bound through the
validated chemical projection rather than a SMILES string: that projection accepts a source only
when its atom names equal the topology's name for every atom in order, so RDKit index i is AA atom
id i + 1. A context without one is refused rather than guessed at.
"""
import numpy as np

from ...sugars import coords as sugar_coords
from ..context import chemical_bond_orders

#: Heavy atoms per bead -- the mapping layer's size convention, and with it the path cap: a connected
#: group of k atoms has no shortest path longer than k - 1 bonds, so "under the path cap" is "at most
#: four atoms" and one check states both.
MAX_ATOMS = 4
#: Pairing rounds; upstream calls `mapping(..., n_iter=3, ...)`.
ROUNDS = 3
#: Relative atomic masses for the adjacency's diagonal. The context keeps no atom mass and the weights
#: only order a centrality ranking, so a table by element is enough -- upstream says the weights exist
#: to tell C, N and O apart at the magnitudes the eigenvectors see.
MASSES = {'H': 1.008, 'C': 12.011, 'N': 14.007, 'O': 15.999, 'F': 18.998, 'Si': 28.085,
          'P': 30.974, 'S': 32.06, 'Cl': 35.45, 'Br': 79.904, 'I': 126.904}
PARAMETERS = {'rounds': ROUNDS, 'max_bead_heavy_atoms': MAX_ATOMS, 'bonding': 'spectral-centrality',
              'rings': 'sugar-layer'}


def build(context, structure, _index):
    """The ring layer's beads plus a spectral partition of every atom no ring claimed."""
    layer = sugar_coords.ring_layer(structure, context['molecule_id'])
    if layer is None:
        raise ValueError('The ring layer recognises no ring in this molecule, so the spectral algorithm has no ring '
                         'layer to keep; use the connectivity algorithm.')
    if chemical_bond_orders(context) is None:
        raise ValueError('The spectral algorithm needs a verified chemical graph source (a .mol2 or .sdf whose atom '
                         'names match the topology); this molecule has none.')

    atoms = {atom['id']: atom for atom in context['atoms'] if atom['heavy']}
    adjacency = {atom: set() for atom in atoms}
    for bond in context['bonds']:
        if bond['a'] in adjacency and bond['b'] in adjacency:
            adjacency[bond['a']].add(bond['b'])
            adjacency[bond['b']].add(bond['a'])

    beads, counts = list(layer['beads']), {}
    for component in sugar_coords.components(adjacency, set(atoms) - layer['assigned']):
        prefix = 'LINK' if any(atoms[atom]['element'] != 'C' for atom in component) else 'TAIL'
        for group in partition(atoms, adjacency, component):
            counts[prefix] = counts.get(prefix, 0) + 1
            beads.append(sugar_coords.fragment_bead(atoms, group, prefix, counts[prefix]))
    return {'name': f"{context['molecule_id']} spectral graph draft",
            'beads': beads, 'rings': layer['rings'],
            'connections': sugar_coords.connections_for(beads, structure),
            'schema_version': 3, 'status': 'candidate-unvalidated', 'martini_version': '3',
            'source_structure': context.get('path', ''),
            'reference': layer['reference'],
            'algorithm': 'cg_param_m3 spectral graph partition of every atom no ring claimed, on the validated '
                         'chemical projection',
            'provenance': {'paper_doi': '10.1021/acs.jctc.1c00322',
                           'sugar_topology': 'references/martini_v3.0.0_sugars_v2.itp'},
            'limitations': ['The ring layer is the carbohydrate template layer and this algorithm does not '
                            're-derive it: ring beads and their TC4 sites come from it unchanged',
                            'Bead types come from the fragment rules, not from cg_param_m3 parameterisation, '
                            'which is out of scope'],
            'warnings': layer['warnings']}


def partition(atoms, adjacency, component):
    """One connected group of non-ring atoms as connected beads of at most four heavy atoms each.

    `atoms` maps atom id to the context record (its element sets the weight), `adjacency` is the heavy
    atom bond graph, and `component` is one connected set of atom ids.
    """
    order = sorted(component)
    position = {atom: index for index, atom in enumerate(order)}
    bonds = [{position[other] for other in adjacency[atom] if other in position} for atom in order]
    distances = _distances(bonds)
    masses = [0.5 * MASSES.get((atoms[atom].get('element') or 'C').title(), 12.011) for atom in order]

    beads, graph = [[index] for index in range(len(order))], bonds
    for _round in range(ROUNDS):
        scores, ties = _rank(graph, beads, distances, masses)
        beads, graph = _regroup(_pair(graph, beads, scores, ties), beads, bonds)
    beads = _contract(beads, bonds, distances, masses)
    return [sorted(order[index] for index in bead) for bead in sorted(beads, key=min)]


def _distances(bonds):
    """Bond counts between every pair of atoms -- upstream's `floyd_warshall` on the adjacency."""
    distances = []
    for start in range(len(bonds)):
        row = [len(bonds) + 1] * len(bonds)
        row[start] = 0
        frontier = [start]
        while frontier:
            following = []
            for node in frontier:
                for other in bonds[node]:
                    if row[other] > row[node] + 1:
                        row[other] = row[node] + 1
                        following.append(other)
            frontier = following
        distances.append(row)
    return distances


def _rank(graph, beads, distances, masses):
    """Bead centrality: the principal eigenvector of the weighted adjacency, and the tie order.

    Upstream's `rank_nodes`/`Scale_Scores`: the diagonal carries each bead's weight, the eigenvector of
    the largest eigenvalue is the score, and a vector that is not all one sign within ten orders of
    magnitude has its weights halved and is recomputed.
    """
    matrix = np.zeros((len(beads), len(beads)))
    for node, neighbours in enumerate(graph):
        for other in neighbours:
            matrix[node][other] = 1.0
    weights = [_weight(bead, distances, masses) for bead in beads]
    scores = np.ones(len(beads))
    for _attempt in range(9):
        weighted = matrix.copy()
        np.fill_diagonal(weighted, weights)
        values, vectors = np.linalg.eigh(weighted)
        scores = np.abs(vectors[:, int(np.argmax(values))])
        low, high = float(scores.min()), float(scores.max())
        if low > 0 and high / low < 1e10:
            break
        weights = [weight / 2 for weight in weights]
    low = float(scores.min())
    scores = scores / low if low > 0 else scores + 1.0
    return scores, _ties(scores)


def _weight(bead, distances, masses):
    """A bead's diagonal weight: its average atomic mass times its longest shortest path."""
    longest = max((distances[first][second] for first in bead for second in bead), default=0)
    return sum(masses[atom] for atom in bead) / len(bead) * longest


def _ties(scores):
    """Node indices grouped by equal score, lowest score first -- upstream's `ties` list."""
    order = [int(node) for node in np.argsort(scores)]
    ties, rank = [], [order[0]]
    for node in order[1:]:
        if np.isclose(scores[node], scores[rank[-1]]):
            rank.append(node)
        else:
            ties.append(rank)
            rank = [node]
    ties.append(rank)
    return ties


def _pair(graph, beads, scores, ties):
    """One round: every node joins its most central bonded neighbour while the union stays in the cap.

    Upstream's `spectral_grouping`. A bead may take a second partner only when that partner scores the
    same as the first, which is how a symmetric branch closes into one bead.
    """
    groups = []
    for rank in ties:
        fresh = []
        for node in rank:
            if any(node in group for group in groups) or any(node in group for group in fresh):
                continue
            group = [node]
            bonded = sorted((other for other in graph[node] if not any(other in taken for taken in groups)),
                            key=lambda other: scores[other])
            for other in bonded:
                if len(group) == 1:
                    if len(beads[node]) + len(beads[other]) <= MAX_ATOMS:
                        group.append(other)
                        score = scores[other]
                elif np.isclose(score, scores[other]):
                    group.append(other)
                else:
                    break
            fresh.append(group)
        # Two nodes of one rank may both choose the same partner. Upstream resolves that by merging
        # every group that shares a node; without it the partner lands in two beads and `_regroup`
        # carries the same atom id twice into one bead.
        merged = [list(group) for group in fresh]
        while True:
            result = []
            for group in merged:
                for existing in result:
                    if set(group) & set(existing):
                        existing.extend(node for node in group if node not in existing)
                        break
                else:
                    result.append(list(group))
            if len(result) == len(merged):
                break
            merged = result
        for group in merged:
            # Upstream reverses a combination that grew past the cap: its nodes go back to being alone.
            if sum(len(beads[node]) for node in group) <= MAX_ATOMS:
                groups.append(group)
            else:
                groups.extend([node] for node in group)
    return groups


def _regroup(groups, beads, bonds):
    """The next level's beads and their connectivity."""
    regrouped = [[atom for node in group for atom in beads[node]] for group in groups]
    return regrouped, _cg(regrouped, bonds)


def _cg(beads, bonds):
    """Two beads are bonded when any atom bond crosses between them."""
    owner = {atom: index for index, bead in enumerate(beads) for atom in bead}
    graph = [set() for _ in beads]
    for atom, neighbours in enumerate(bonds):
        for other in neighbours:
            first, second = owner[atom], owner[other]
            if first != second:
                graph[first].add(second)
                graph[second].add(first)
    return graph


def _contract(beads, bonds, distances, masses):
    """Upstream's path contraction: a one-atom bead takes atoms from its most central bonded neighbour.

    A one-atom bead is not a fragment -- a lone heavy atom has no Martini bead -- so each pass ranks the
    current beads again and folds every lone atom into the neighbour the ranking puts first: the whole
    atom while the merge still fits the cap, otherwise one atom of that neighbour that it is bonded to.
    """
    beads = [list(bead) for bead in beads]
    for _attempt in range(8):
        lone = [index for index, bead in enumerate(beads) if len(bead) == 1]
        if not lone:
            break
        graph = _cg(beads, bonds)
        scores, _ranking = _rank(graph, beads, distances, masses)
        folded = False
        for index in sorted(lone, key=lambda position: scores[position]):
            if len(beads[index]) != 1:
                continue
            atom = beads[index][0]
            partners = sorted((other for other in graph[index] if other != index and beads[other]),
                              key=lambda other: (scores[other], beads[other][0]))
            if not partners:
                continue
            partner = partners[0]
            if len(beads[partner]) + 1 <= MAX_ATOMS:
                beads[partner].append(atom)
                beads[index] = []
            else:
                stolen = [member for member in beads[partner] if member in bonds[atom]]
                if not stolen:
                    continue
                beads[partner].remove(stolen[0])
                beads[index].append(stolen[0])
            folded = True
        beads = [bead for bead in beads if bead]
        if not folded:
            break
    return beads
