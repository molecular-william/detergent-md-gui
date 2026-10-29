"""The micelle criterion (design spec §7), exercised without a simulation.

These tests are the reason the criterion is a function of bead coordinates rather than of a trajectory file: a
verdict that can only be checked by running 100 ns of MD is a verdict nobody checks. Each case here is a geometry
whose answer a reader can see by hand.
"""
from __future__ import annotations

import pytest
from dashboard.execution.adapters import pdc_assessment


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
