"""The automatic candidate's algorithms, and the gate that keeps an invalid one from being offered.

Two claims are pinned here. The first is a regression: the branch-aware splitter may only change a
candidate that was already invalid, so the four molecule folders this repository tracks keep the bead
lists they had (LMNG, the molecule the splitter changed, is untracked and is not read here -- its measured
result is in the lane's report). Trehalose's list moved once, deliberately, on 2026-11-09: its 1,1 linkage's
bridging oxygen now belongs to the first ring so the candidate reproduces the published `TREH` entry, which
`test_sucrose_reference_candidate.py` pins as conforming. The second is the gate: the automatic path answers
`{available: false, reasons}` instead of handing back a document `mapping_graph.validate` rejects.
"""
from dashboard.models.mappings import algorithms, identity, schema
from dashboard.models.mappings.algorithms import spectral
from dashboard.models.mappings.context import as_structure, build_context
from dashboard.models.sugars import coords as sugar_coords

from tests.harness.support import PROJECT_ROOT

MOLECULES = PROJECT_ROOT / 'molecules'

#: The four molecule folders in git, with the beads each produced before the splitter changed. None of
#: these candidates was invalid then, so none of them is allowed to move.
PINNED = {
    'DDM': [['S1A', 'S', [13, 14, 34, 35]], ['S1B', 'S', [19, 20, 32, 33]], ['S1C', 'S', [15, 16, 17, 18]],
            ['S1VS', 'T', []], ['S2A', 'S', [21, 30, 31]], ['S2B', 'S', [26, 27, 28, 29]],
            ['S2C', 'S', [22, 23, 24, 25]], ['S2VS', 'T', []],
            ['TAIL1', 'R', [1, 2, 3, 4]], ['TAIL2', 'R', [5, 6, 7, 8]], ['TAIL3', 'R', [9, 10, 11, 12]]],
    'Maltose': [['S1A', 'S', [10, 11, 12, 13]], ['S1B', 'S', [6, 7, 8, 9]], ['S1C', 'S', [14, 15, 16, 17]],
                ['S1VS', 'T', []], ['S2A', 'S', [5, 18, 19]], ['S2B', 'S', [20, 21, 22, 23]],
                ['S2C', 'S', [1, 2, 3, 4]], ['S2VS', 'T', []]],
    'Sucrose': [['S1A', 'S', [5, 6, 7, 8]], ['S1B', 'S', [20, 21, 22, 23]], ['S1C', 'S', [1, 2, 3, 4]],
                ['S1VS', 'T', []], ['S2A', 'S', [9, 18, 19]], ['S2B', 'S', [14, 15, 16, 17]],
                ['S2C', 'S', [10, 11, 12, 13]], ['S2VS', 'T', []]],
    'Trehalose': [['S1A', 'S', [5, 6, 18, 19]], ['S1B', 'S', [20, 21, 22, 23]], ['S1C', 'S', [1, 2, 3, 4]],
                  ['S1VS', 'T', []], ['S2A', 'S', [7, 16, 17]], ['S2B', 'S', [12, 13, 14, 15]],
                  ['S2C', 'S', [8, 9, 10, 11]], ['S2VS', 'T', []]],
}


def context_of(elements, bonds, *, chemical=True):
    """A mapping context for a fixture graph: heavy atoms in a line, bonded as given."""
    atoms = [{'id': index, 'name': f'X{index}', 'residue': 'MOL', 'element': element, 'heavy': True,
              'charge': 0.0, 'xyz': [float(index), 0.0, 0.0], 'display_xy': [float(index), 0.0]}
             for index, element in enumerate(elements, 1)]
    return {'molecule_id': 'fixture', 'name': 'fixture', 'path': 'molecules/fixture', 'atoms': atoms,
            'bonds': [{'a': first, 'b': second, 'order': 1.0,
                       'order_source': 'chemical' if chemical else 'itp'} for first, second in bonds],
            'source_quality': {'bond_order': 'chemical' if chemical else 'fallback', 'chemical_sources': [],
                               'warnings': []},
            'snapshot': {'snapshot_sha256': 'fixture'},
            'capabilities': {'manual': {'available': True, 'reasons': []},
                             'automatic': {'available': True, 'reasons': []}}}


def test_every_tracked_molecule_still_generates_the_candidate_it_had():
    for molecule, pinned in PINNED.items():
        structure = as_structure(build_context(MOLECULES, molecule))
        candidate = schema.automatic_candidate(structure, molecule)
        assert [[bead['name'], bead['size'], bead['atoms']] for bead in candidate['beads']] == pinned, molecule


def test_the_gate_refuses_a_candidate_its_own_validator_rejects(monkeypatch):
    """A disconnected bead and a one-atom bead are the two defects the automatic path will not return."""
    broken = {'name': 'broken', 'rings': [], 'connections': [],
              'beads': [{'name': 'B1', 'size': 'T', 'type': 'C1', 'atoms': [1, 3]},
                        {'name': 'B2', 'size': 'T', 'type': 'C1', 'atoms': [2]}]}
    monkeypatch.setattr(algorithms.connectivity, 'build', lambda *args: broken)
    answer = algorithms.generate(context_of(['C', 'C', 'C'], [[1, 2], [2, 3]]), {})
    assert answer['available'] is False and answer['candidate'] is None
    assert any('connected' in reason for reason in answer['reasons']), answer['reasons']


def test_an_unknown_algorithm_is_refused_and_names_the_ones_offered():
    answer = algorithms.generate(context_of(['C'], []), {}, 'nowhere')
    assert answer['available'] is False and answer['candidate'] is None
    assert 'nowhere' in answer['reasons'][0]
    assert 'connectivity' in answer['reasons'][0] and 'spectral' in answer['reasons'][0]


def test_an_algorithm_that_cannot_map_this_molecule_answers_with_its_reason():
    """Spectral keeps the ring layer, so a molecule with no ring has nothing for it to keep."""
    answer = algorithms.generate(context_of(['C', 'C', 'C'], [[1, 2], [2, 3]]), {}, 'spectral')
    assert answer['available'] is False and answer['candidate'] is None
    assert 'ring layer recognises no ring' in answer['reasons'][0]


def test_spectral_is_unavailable_without_a_verified_chemical_projection():
    context = build_context(MOLECULES, 'DDM')
    context['source_quality'] = {'bond_order': 'fallback', 'chemical_sources': [], 'warnings': []}
    answer = algorithms.generate(context, {}, 'spectral')
    assert answer['available'] is False
    assert 'verified chemical graph source' in answer['reasons'][0]


def test_the_two_algorithms_partition_the_same_branched_graph_differently():
    """The spectral pairing and the branch-aware chunker are two answers, not one renamed.

    LMNG's remainder graph by connectivity: the quaternary carbon 11, its two ten-atom chains and the two
    one-atom linkers. The branch-aware splitter closes 11 with both linkers; the spectral rounds pair by
    centrality, so their beads are not the same groups -- while both keep every bead connected and inside
    the four-atom cap.
    """
    bonds = [(11, 10), (11, 12), (11, 22), (11, 23)]
    bonds += [(index, index + 1) for index in range(1, 10)]
    bonds += [(index, index + 1) for index in range(12, 21)]
    atoms = {index: {'id': index, 'element': 'C', 'heavy': True} for index in range(1, 24)}
    adjacency = {index: set() for index in atoms}
    for first, second in bonds:
        adjacency[first].add(second)
        adjacency[second].add(first)

    connectivity, _notes = sugar_coords.remainder_beads(atoms, adjacency, set())
    groups = [bead['atoms'] for bead in connectivity] + spectral.partition(atoms, adjacency, set(atoms))

    assert sorted(bead['atoms'] for bead in connectivity) != sorted(spectral.partition(atoms, adjacency, set(atoms)))
    for group in groups:
        assert 1 <= len(group) <= 4, group
        seen, pending = {group[0]}, [group[0]]
        while pending:
            for neighbour in adjacency[pending.pop()] & set(group) - seen:
                seen.add(neighbour)
                pending.append(neighbour)
        assert seen == set(group), group


def test_the_documents_differ_in_what_produced_them_not_in_identity_alone():
    """Identity is the bead assignment; the algorithm is provenance, so identity must not carry it."""
    context = build_context(MOLECULES, 'DDM')
    first = algorithms.generate(context, {}, 'connectivity')['candidate']
    second = algorithms.generate(context, {}, 'spectral')['candidate']
    assert first['provenance']['algorithm'] == 'connectivity'
    assert second['provenance']['algorithm'] == 'spectral'
    assert first['name'] != second['name']
    renamed = {**second, 'name': first['name']}
    assert identity.candidate_identity(first) == identity.candidate_identity(renamed), (
        'the same beads in the same order must hash alike whatever algorithm built them')
