"""The micelle criterion (design spec §7), exercised without a simulation.

These tests are the reason the criterion is a function of bead coordinates rather than of a trajectory file: a
verdict that can only be checked by running 100 ns of MD is a verdict nobody checks. Each case here is a geometry
whose answer a reader can see by hand.

The contact search is a KD-tree now, so the tests also hold it to the implementation it replaced: the last section
freezes the old `for left … for right` loop and fuzzes the two against each other over 500 random systems, demanding
the same clusters in the same order and the same assessment mapping -- including pairs lying exactly on a cutoff,
where a tree's own C distance and `np.linalg.norm` disagree in the last bits.
"""
from __future__ import annotations

import numpy as np
import pytest
from detergent_pdc.execution.adapters import pdc_assessment


def detergent(name: str, centre, *, spacing: float = 0.1) -> dict:
    """One detergent: three tail beads in a line around `centre`, 0.1 nm apart."""
    x, y, z = centre
    return {'name': name, 'tail': [[x + index * spacing, y, z] for index in range(3)]}


def far_apart(count: int, gap: float = 5.0) -> list[dict]:
    return [detergent(f'D{index + 1}', (index * gap, 0.0, 0.0)) for index in range(count)]


def test_isolated_detergents_form_no_cluster():
    answer = pdc_assessment.assess_micelle(far_apart(8), aggregation_number=8)

    assert answer['verdict'] is False
    assert answer['cluster_sizes'] == [1] * 8
    assert answer['largest_cluster'] == 1
    assert 'the largest cluster holds 1 of the requested 8 detergents' in answer['reasons']


def test_contacts_chain_through_a_neighbour():
    """A touches B, B touches C, A never comes near C -- all three are one micelle."""
    line = [detergent('A', (0.0, 0.0, 0.0)), detergent('B', (0.5, 0.0, 0.0)), detergent('C', (1.0, 0.0, 0.0))]

    answer = pdc_assessment.assess_micelle(line, contact_nm=0.6, aggregation_number=3)

    assert answer['cluster_sizes'] == [3]
    assert answer['in_micelle'] == ['A', 'B', 'C']
    assert answer['verdict'] is True


def single(name: str, centre) -> dict:
    """One detergent with a single tail bead, for cases where the geometry should be exactly as written."""
    return {'name': name, 'tail': [list(centre)]}


def test_the_contact_distance_is_the_rule_not_an_approximation():
    just_inside = [single('A', (0.0, 0.0, 0.0)), single('B', (0.55, 0.0, 0.0))]
    just_outside = [single('A', (0.0, 0.0, 0.0)), single('B', (0.65, 0.0, 0.0))]

    assert pdc_assessment.assess_micelle(just_inside, contact_nm=0.6, aggregation_number=2)['largest_cluster'] == 2
    assert pdc_assessment.assess_micelle(just_outside, contact_nm=0.6, aggregation_number=2)['largest_cluster'] == 1


def test_a_protein_free_build_needs_only_the_count():
    blob = [detergent(f'D{index + 1}', (0.15 * index, 0.0, 0.0)) for index in range(4)]

    answer = pdc_assessment.assess_micelle(blob, aggregation_number=4)

    assert answer['verdict'] is True and answer['protein_free'] is True
    assert answer['fraction_of_requested'] == 1.0


def test_a_protein_build_needs_the_cluster_to_touch_the_protein():
    blob = [detergent(f'D{index + 1}', (0.15 * index, 0.0, 0.0)) for index in range(3)]

    away = pdc_assessment.assess_micelle(blob, [[5.0, 0.0, 0.0]], aggregation_number=3)
    touching = pdc_assessment.assess_micelle(blob, [[0.2, 0.0, 0.0]], aggregation_number=3)

    assert away['verdict'] is False and 'comes within 0.6 nm of the protein' in away['reasons'][0]
    assert away['protein_contact_count'] == 0
    # All three are inside the contact distance of a protein bead at 0.2 nm, so all three count.
    assert touching['verdict'] is True and touching['protein_contact_count'] == 3


def test_the_membership_is_reported_even_when_the_verdict_fails():
    """The removal step removes what is outside the largest cluster, so membership is a number, not a verdict."""
    partly = far_apart(3, gap=0.3) + [detergent('lonely', (20.0, 0.0, 0.0))]

    answer = pdc_assessment.assess_micelle(partly, aggregation_number=4)

    assert answer['verdict'] is False
    assert answer['largest_cluster'] == 3 and 'lonely' not in answer['in_micelle']
    assert answer['fraction_of_requested'] == 0.75


def test_every_number_a_reader_needs_is_in_the_record():
    answer = pdc_assessment.assess_micelle(far_apart(2), aggregation_number=2)

    assert set(answer) >= {'verdict', 'reasons', 'aggregation_number', 'cluster_sizes', 'largest_cluster',
                           'fraction_of_requested', 'contact_nm', 'protein_contact_nm', 'protein_contact_count',
                           'protein_free', 'in_micelle', 'detergents', 'limitations'}
    assert answer['contact_nm'] == 0.6
    assert answer['detergents'] == ['D1', 'D2']


def test_the_protein_requirement_states_what_it_simplifies():
    answer = pdc_assessment.assess_micelle(far_apart(1), [[0.0, 0.0, 0.0]], aggregation_number=1)

    assert any('hydrophobic-belt' in line for line in answer['limitations'])


@pytest.mark.parametrize('detergents, aggregation, message', [
    ([], 1, 'at least one detergent'),
    (far_apart(1), 0, 'aggregation number'),
])
def test_the_criterion_refuses_what_it_cannot_judge(detergents, aggregation, message):
    with pytest.raises(ValueError, match=message):
        pdc_assessment.assess_micelle(detergents, aggregation_number=aggregation)


def test_coordinates_that_are_not_points_are_refused():
    with pytest.raises(ValueError, match='x, y, z'):
        pdc_assessment.assess_micelle([{'name': 'A', 'tail': [[0.0, 0.0]]}], aggregation_number=1)
    with pytest.raises(ValueError, match='finite'):
        pdc_assessment.assess_micelle([{'name': 'A', 'tail': [[0.0, float('nan'), 0.0]]}],
                                      aggregation_number=1)
    with pytest.raises(ValueError, match='contact distance'):
        pdc_assessment.contact_components([[[0.0, 0.0, 0.0]]], contact_nm=0.0)


# ------------------------------------------------------------------------------------ the implementation it replaced
# Frozen before the KD-tree change: a Python loop over every pair of detergents, one `_within` broadcast per pair, the
# union-find, and the stable sort. Nothing below may be rewritten to "improve" it -- it is the oracle.

def _reference_within(one: np.ndarray, other: np.ndarray, distance_nm: float) -> bool:
    if len(one) == 0 or len(other) == 0:
        return False
    distances = np.linalg.norm(one[:, None, :] - other[None, :, :], axis=2)
    return bool(distances.min() <= distance_nm)


def _reference_contact_components(tails, contact_nm: float = pdc_assessment.CONTACT_NM) -> list[list[int]]:
    if contact_nm <= 0:
        raise ValueError('the contact distance must be positive')
    points = [pdc_assessment._points(tail) for tail in tails]
    parent = list(range(len(points)))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for left in range(len(points)):
        for right in range(left + 1, len(points)):
            if _reference_within(points[left], points[right], contact_nm):
                parent[root(right)] = root(left)
    groups: dict[int, list[int]] = {}
    for index in range(len(points)):
        groups.setdefault(root(index), []).append(index)
    return sorted(groups.values(), key=len, reverse=True)


def _reference_assess_micelle(detergents, protein=None, *, contact_nm: float = pdc_assessment.CONTACT_NM,
                              aggregation_number: int, protein_contact_nm: float | None = None) -> dict:
    if not detergents:
        raise ValueError('an assessment needs at least one detergent')
    if aggregation_number < 1:
        raise ValueError('the requested aggregation number must be at least one')
    names = [str(detergent.get('name') or f'D{index + 1}') for index, detergent in enumerate(detergents)]
    tails = [pdc_assessment._points(detergent.get('tail') or []) for detergent in detergents]
    reach = pdc_assessment.CONTACT_NM if protein_contact_nm is None else float(protein_contact_nm)
    components = _reference_contact_components(tails, contact_nm)
    largest = components[0] if components else []
    protein_points = pdc_assessment._points(protein) if protein is not None else None
    protein_free = protein_points is None or len(protein_points) == 0
    touching = []
    if protein_points is not None and len(protein_points):
        touching = [index for index in largest if _reference_within(tails[index], protein_points, reach)]
    reasons = []
    if len(largest) < aggregation_number:
        reasons.append(f'the largest cluster holds {len(largest)} of the requested {aggregation_number} detergents')
    if not protein_free and not touching:
        reasons.append(f'no detergent in the largest cluster comes within {reach:g} nm of the protein')
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
        'in_micelle': [names[index] for index in largest],
        'detergents': names,
        'limitations': ['the protein requirement is "within the contact distance of any protein bead", not a '
                        'hydrophobic-belt test: no belt is defined in this code base yet'],
    }


# ---------------------------------------------------------------------------------------------------- the fuzz corpus

def _random_system(rng, molecules: int, bead_cap: int) -> list[list[list[float]]]:
    """A random detergent system with everything the two implementations can disagree about.

    Every molecule gets 0-`bead_cap` tail beads in a crowded cloud (so contacts chain), one molecule may duplicate
    another's bead, and -- when two beads exist -- two of them are placed *exactly* `CONTACT_NM` apart on x, in two
    different molecules when there are two. That last pair is the one a bare tree search gets wrong in the last bits.
    """
    tails = []
    for _ in range(molecules):
        count = int(rng.integers(0, bead_cap + 1))
        centre = rng.normal(0.0, 0.4, 3)
        tails.append(centre + rng.normal(0.0, 0.12, size=(count, 3)))
    slots = [(molecule, bead) for molecule, tail in enumerate(tails) for bead in range(len(tail))]
    if len(slots) >= 2 and rng.random() < 0.5:
        source, target = (int(value) for value in rng.choice(len(slots), size=2, replace=False))
        tails[slots[target][0]][slots[target][1]] = tails[slots[source][0]][slots[source][1]].copy()
    if len(slots) >= 2:
        first, second = _two_slots(rng, tails)
        y, z = float(rng.normal(0.0, 0.3)), float(rng.normal(0.0, 0.3))
        tails[first[0]][first[1]] = np.array([0.0, y, z])
        tails[second[0]][second[1]] = np.array([pdc_assessment.CONTACT_NM, y, z])
    return [tail.tolist() for tail in tails]


def _two_slots(rng, tails) -> tuple[tuple[int, int], tuple[int, int]]:
    """Two beads to move onto the exact cutoff: from two different molecules when two hold a bead."""
    holding = [(molecule, list(range(len(tail)))) for molecule, tail in enumerate(tails) if len(tail)]
    if len(holding) >= 2:
        first, second = (int(value) for value in rng.choice(len(holding), size=2, replace=False))
        return ((holding[first][0], int(rng.choice(holding[first][1]))),
                (holding[second][0], int(rng.choice(holding[second][1]))))
    molecule, beads = holding[0]
    one, other = (int(value) for value in rng.choice(beads, size=2, replace=False))
    return (molecule, one), (molecule, other)


def _fuzz_systems(rng) -> list[list[list[list[float]]]]:
    """500+ systems: 1 to 800 molecules, 0-8 tail beads, empty/single-bead/duplicate/exact-cutoff geometry."""
    systems = []
    for molecules, bead_cap, count in ((1, 8, 10), (2, 8, 10), (3, 8, 10), (8, 8, 15), (16, 8, 15),
                                       (64, 6, 8), (200, 4, 4), (400, 2, 2), (800, 1, 1)):
        systems.extend(_random_system(rng, molecules, bead_cap) for _ in range(count))
    while len(systems) < 500:
        systems.append(_random_system(rng, min(1 + int(rng.exponential(10.0)), 800), 8))
    return systems


def _detergents(tails):
    return [{'name': f'D{index + 1}', 'tail': tail} for index, tail in enumerate(tails)]


def test_the_contact_graph_is_the_frozen_loop_on_500_random_systems():
    rng = np.random.default_rng(20261118)
    systems = _fuzz_systems(rng)

    assert len(systems) >= 500
    assert max(len(tails) for tails in systems) == 800 and min(len(tails) for tails in systems) == 1
    for tails in systems:
        assert pdc_assessment.contact_components(tails) == _reference_contact_components(tails), tails


def test_the_assessment_is_the_frozen_one_on_the_same_systems():
    """Protein None, empty, small and 8 000-bead, and the aggregation-number edges, on the fuzz corpus.

    The whole mapping is compared, so the order of `in_micelle` and of `cluster_sizes` is part of the assertion. The
    three aggregation edges (1, past the molecule count, the largest cluster) take turns over the corpus rather than
    being crossed with every system: each edge is exercised on a third of it, and every protein shape on the systems
    small enough for the oracle's per-molecule loop.
    """
    rng = np.random.default_rng(20261118)
    systems = _fuzz_systems(rng)
    large = np.random.default_rng(7).uniform(0.0, 6.0, size=(8000, 3)).tolist()
    small = np.array([[0.0, 0.0, 0.0], [0.5, 0.5, 0.5], [3.0, 3.0, 3.0]]).tolist()
    seen = {'one': 0, 'beyond': 0, 'largest': 0, 'empty': 0, 'small': 0, 'large': 0}

    for position, tails in enumerate(systems):
        detergents = _detergents(tails)
        largest = len(pdc_assessment.contact_components(tails)[0])
        edge = ('one', 'beyond', 'largest')[position % 3]
        aggregation = {'one': 1, 'beyond': len(tails) + 3, 'largest': largest}[edge]
        seen[edge] += 1
        assert pdc_assessment.assess_micelle(detergents, None, aggregation_number=aggregation) == \
            _reference_assess_micelle(detergents, None, aggregation_number=aggregation), (edge, tails)
        if position % 3:
            continue
        for name, protein in (('empty', []), ('small', small)):
            seen[name] += 1
            assert pdc_assessment.assess_micelle(detergents, protein, aggregation_number=aggregation) == \
                _reference_assess_micelle(detergents, protein, aggregation_number=aggregation), (name, edge, tails)
        if position % 30 == 0 and len(tails) <= 32:
            # 8 000 protein beads: the case the tree exists for, on systems small enough for the oracle to answer.
            seen['large'] += 1
            for aggregation in sorted({1, largest}):
                assert pdc_assessment.assess_micelle(detergents, large, aggregation_number=aggregation) == \
                    _reference_assess_micelle(detergents, large, aggregation_number=aggregation), tails

    assert all(seen.values()), seen


def test_equal_clusters_keep_the_frozen_order():
    """Today's stable sort over groups inserted in index order breaks ties by first member; so does the tree path."""
    tails = [single(name, (index * 5.0, 0.0, 0.0))['tail'] for index, name in enumerate('abcdefgh')]
    # (0, 1) touch and (3, 4) touch; 2, 5, 6, 7 are alone. Both pairs hold two detergents.
    tails[1] = [[pdc_assessment.CONTACT_NM * 0.5, 0.0, 0.0]]
    tails[4] = [[15.0 + pdc_assessment.CONTACT_NM * 0.5, 0.0, 0.0]]

    assert pdc_assessment.contact_components(tails) == [[0, 1], [3, 4], [2], [5], [6], [7]]
    assert pdc_assessment.contact_components(tails) == _reference_contact_components(tails)


def test_a_pair_exactly_on_the_cutoff_is_a_contact_and_a_hair_past_it_is_not():
    exactly = [[0.0, 0.0, 0.0], [pdc_assessment.CONTACT_NM, 0.0, 0.0]]
    past = [[0.0, 0.0, 0.0], [float(np.nextafter(pdc_assessment.CONTACT_NM, np.inf)), 0.0, 0.0]]

    assert np.linalg.norm(np.subtract(exactly[1], exactly[0])) == pdc_assessment.CONTACT_NM, 'the geometry is exact'
    assert pdc_assessment.contact_components([[exactly[0]], [exactly[1]]]) == [[0, 1]]
    assert pdc_assessment.contact_components([[past[0]], [past[1]]]) == [[0], [1]]
    assert _reference_contact_components([[exactly[0]], [exactly[1]]]) == [[0, 1]]


def test_a_tail_bead_exactly_on_the_protein_reach_is_a_contact_and_a_hair_past_it_is_not():
    detergents = [{'name': 'A', 'tail': [[0.0, 0.0, 0.0]]}, {'name': 'B', 'tail': [[10.0, 0.0, 0.0]]}]
    exactly = [[pdc_assessment.CONTACT_NM, 0.0, 0.0]]
    past = [[float(np.nextafter(pdc_assessment.CONTACT_NM, np.inf)), 0.0, 0.0]]

    assert np.linalg.norm(np.subtract(exactly[0], detergents[0]['tail'][0])) == pdc_assessment.CONTACT_NM
    assert pdc_assessment.assess_micelle(detergents, exactly, aggregation_number=1)['protein_contact_count'] == 1
    assert pdc_assessment.assess_micelle(detergents, past, aggregation_number=1)['protein_contact_count'] == 0
    assert _reference_assess_micelle(detergents, exactly, aggregation_number=1)['protein_contact_count'] == 1
    assert _reference_assess_micelle(detergents, past, aggregation_number=1)['protein_contact_count'] == 0


def test_empty_tails_and_an_empty_protein_keep_returning_no_contact():
    empty = [[], [], []]

    assert pdc_assessment.contact_components(empty) == [[0], [1], [2]]
    assert pdc_assessment.contact_components(empty) == _reference_contact_components(empty)
    answer = pdc_assessment.assess_micelle(_detergents(empty), [], aggregation_number=1)
    assert answer['protein_free'] is True and answer['protein_contact_count'] == 0
    assert answer['cluster_sizes'] == [1, 1, 1]
    assert answer == _reference_assess_micelle(_detergents(empty), [], aggregation_number=1)

