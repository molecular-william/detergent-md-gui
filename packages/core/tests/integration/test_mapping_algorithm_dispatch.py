"""The automatic preview dispatches on `algorithm`, and records what produced the candidate.

The route keeps its answer shape: `{available, candidate, reasons}`. An algorithm that is unknown or
cannot map this molecule answers `available: false` with its reasons, which is what the editor already
reads, so an unavailable choice is shown disabled with its reason rather than failing the request.
"""


def preview(client, molecule='DDM', **body):
    """Post the automatic preview the way the editor does: the molecule and the snapshot it is looking at."""
    snapshot = client.get(f'/api/mappings/context?molecule_id={molecule}').json['context']['snapshot']
    return client.post('/api/mappings/automatic/preview',
                       json={'molecule_id': molecule, 'molecule_snapshot': snapshot, **body})


def test_the_preview_defaults_to_the_connectivity_algorithm(dashboard):
    default = preview(dashboard.client)
    explicit = preview(dashboard.client, algorithm='connectivity')
    assert default.status_code == 200
    assert default.json == explicit.json
    assert default.json['available'] is True
    assert default.json['candidate']['provenance']['algorithm'] == 'connectivity'


def test_an_unknown_algorithm_is_refused_with_the_reason_and_no_candidate(dashboard):
    response = preview(dashboard.client, algorithm='nowhere')
    assert response.status_code == 200, 'an unavailable algorithm is an answer, not a failed request'
    body = response.json
    assert body['available'] is False and body['candidate'] is None
    assert 'nowhere' in body['reasons'][0] and 'connectivity' in body['reasons'][0]


def test_an_algorithm_name_that_is_not_a_string_is_a_bad_request(dashboard):
    assert preview(dashboard.client, algorithm=7).status_code == 400


def test_the_spectral_algorithm_keeps_the_ring_layer_and_records_itself(dashboard):
    body = preview(dashboard.client, algorithm='spectral').json
    assert body['available'] is True, body['reasons']
    candidate = body['candidate']
    assert candidate['provenance']['algorithm'] == 'spectral'
    assert candidate['schema_version'] == 3 and candidate['molecule_id'] == 'DDM'
    assert candidate['molecule_snapshot']['snapshot_sha256']
    assert len(candidate['rings']) == 2, 'the sugar layer still owns the rings'
    assert any(bead.get('virtual_site') for bead in candidate['beads']), 'and their TC4 sites'


def test_the_two_algorithms_answer_for_the_same_molecule_and_are_not_the_same_document(dashboard):
    """DDM's straight tail is cut into the same four-atom pieces by both, so the documents differ in what
    produced them -- the algorithm, the parameters and the name -- and not in their identity inputs."""
    first = preview(dashboard.client, algorithm='connectivity').json['candidate']
    second = preview(dashboard.client, algorithm='spectral').json['candidate']
    assert first['provenance']['algorithm'] != second['provenance']['algorithm']
    assert first['provenance']['parameters'] != second['provenance']['parameters']
    assert first['name'] != second['name']
    assert [bead['atoms'] for bead in first['beads']] == [bead['atoms'] for bead in second['beads']]


def test_the_preview_still_requires_a_molecule(dashboard):
    """The guard the route had before the algorithm key: a preview needs to know what it is mapping."""
    assert dashboard.client.post('/api/mappings/automatic/preview', json={}).status_code == 400
