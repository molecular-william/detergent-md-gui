"""End to end through the dashboard's own candidate route.

The unit tests call the candidate builder directly; this drives the endpoint the Generate automatic
candidate button posts to, so the check covers what a user actually receives.
"""
from dashboard.models.mappings import context as mapping_context
from dashboard.models.sugars import reference


def post_candidate(dashboard, molecule):
    """Post what the page posts: the molecule id and the snapshot the sources currently hash to."""
    context = mapping_context.build_context(dashboard.coordinator.ROOT / 'molecules', molecule)
    return dashboard.client.post('/api/mappings/automatic/preview',
                                 json={'molecule_id': molecule, 'molecule_snapshot': context['snapshot']})


def test_the_automatic_candidate_route_reproduces_the_reference_sucrose_mapping(dashboard):
    response = post_candidate(dashboard, 'Sucrose')
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['available'] is True, payload.get('reasons')
    candidate = payload['candidate']
    assert reference.conform(candidate, 'SUCR') == [], 'the mapping must reproduce the reference entry'
    assert candidate['reference']['entry'] == 'SUCR'
    assert candidate['reference']['stereochemistry'] == 'unresolved'
    assert [bead['name'] for bead in candidate['beads']] == ['S1A', 'S1B', 'S1C', 'S1VS',
                                                             'S2A', 'S2B', 'S2C', 'S2VS']
    assert [bead['type'] for bead in candidate['beads']] == ['SP1r', 'SP4r', 'SP1r', 'TC4',
                                                             'SN6', 'SP4r', 'SP1r', 'TC4']
    assert not any(bead['name'].startswith('TAIL') for bead in candidate['beads'])


def test_the_route_still_serves_a_sugar_carrying_a_chain(dashboard):
    """DDM's sugar part follows the LAC pattern and it keeps its dodecyl tail: not a reference entry."""
    response = post_candidate(dashboard, 'DDM')
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['available'] is True, payload.get('reasons')
    candidate = payload['candidate']
    assert candidate['reference']['covers_whole_molecule'] is False
    assert candidate['reference']['outside_atoms'] > 0
    tails = [bead for bead in candidate['beads'] if bead['name'].startswith('TAIL')]
    assert [len(bead['atoms']) for bead in tails] == [4, 4, 4]
