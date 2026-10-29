"""Deleting a saved mapping's draft takes its bond interactions with it, and the route says so.

The owner's rule: "when a CG mapping is deleted, all its corresponding bond interactions are also
deleted." The read side of that rule is `GET /api/bonded-parameterizations?content_hash=`, which is
what the CG Bond Interactions panel asks: after the last draft holding a content hash is deleted it
must answer nothing for that hash, and while another saved draft still carries the content it must
still answer the revisions.

These tests drive the real store and the real route -- no stubbed deletion -- in the workspace the
`dashboard` fixture built under `tmp_path`; the developer's `workspace/` is never read.
"""
import pytest
from dashboard.models.bonded import parameterization

TOPOLOGY = ('[ moleculetype ]\nDDM 1\n\n[ atoms ]\n'
            '1 C1 1 DDM B01 1 0 72\n2 C1 1 DDM B02 2 0 72\n\n'
            '[ bonds ]\n1 2 1 0.31 5000\n')


def revision(**overrides):
    payload = {'engine': 'fast-forward', 'topology': TOPOLOGY,
               'options': {'constraints_threshold': 10000.0, 'temperature_k': 300.0,
                           'torsion_model': 'legacy', 'torsion_scale': 1.0},
               'ensemble': {'frames': 20001, 'trajectory': '2_mapping/mapped.xtc',
                            'source': 'the mapped AA frames'},
               'aa_reference': None,
               'terms': {'bonds': 1},
               'engine_default_source': 'ff_inter',
               'checks': {}}
    payload.update(overrides)
    return payload


@pytest.fixture
def client(dashboard):
    return dashboard.client


def payload(client, name='DDM'):
    """The assignment as the editor posts it, before the store has minted a file name."""
    context = client.get('/api/mappings/context?molecule_id=DDM').json['context']
    preview = client.post('/api/mappings/automatic/preview', json={
        'molecule_id': 'DDM', 'molecule_snapshot': context['snapshot']}).json['candidate']
    return {**preview, 'name': name}


def save(client, name='DDM'):
    """A saved draft through the route the panel posts to, so the store minted its own file name."""
    saved = client.post('/api/mappings/drafts', json=payload(client, name))
    assert saved.status_code == 201
    return saved.json


def parameterization_of(client, content_hash):
    response = client.get('/api/bonded-parameterizations', query_string={'content_hash': content_hash})
    assert response.status_code == 200
    return response.json


def test_the_delete_route_removes_the_parameterization_and_the_read_side_answers_nothing(client):
    """(d) The route reaches the deletion, and the hash-addressed reader is emptied afterwards."""
    draft = save(client)
    content = draft['mapping_content_hash']
    parameterization.save(draft, revision())
    assert parameterization_of(client, content)['summary']['parameterized'] is True

    response = client.delete('/api/mappings/drafts/' + draft['file'])

    assert response.status_code == 200
    assert response.json['deleted'] == draft['file']
    assert response.json['parameterization']['deleted'] is True
    assert response.json['parameterization']['content_hash'] == content
    assert response.json['parameterization']['revisions'] == [1]

    after = parameterization_of(client, content)
    assert after['summary']['parameterized'] is False
    assert after['revisions'] == []
    assert after['jobs'] == []


def test_a_second_save_of_the_same_assignment_is_refused_naming_the_first(client):
    """One content identity is one model, so the copy is refused rather than given a second name.

    The guard this replaces kept two drafts' revisions alive when either was deleted. There is no second draft to keep
    them for now: the delete that remains is the one that takes the revisions when the mapping goes, which the next test
    pins. What this pins is that the refusal names the mapping to open instead of answering a bare 409.
    """
    first = save(client, 'DDM')

    duplicate = client.post('/api/mappings/drafts', json=payload(client, 'DDM copy'))

    assert duplicate.status_code == 409
    assert duplicate.json['existing'] == first['file']
    assert duplicate.json['error'] == f"An identical mapping already exists: {first['file']}"
    listed = client.get('/api/mappings?view=summary').json['candidates']
    assert [item['file'] for item in listed] == [first['file']], 'the refusal wrote nothing'

    parameterization.save(first, revision())
    assert parameterization_of(client, first['mapping_content_hash'])['summary']['parameterized'] is True


def test_a_mapping_hash_does_not_answer_for_a_deleted_draft_either(client):
    """`mapping_hash` is answered by scanning stored history, so it must not outlive the record."""
    draft = save(client)
    parameterization.save(draft, revision())
    before = client.get('/api/bonded-parameterizations',
                        query_string={'mapping_hash': draft['mapping_hash']}).json
    assert before['summary']['parameterized'] is True

    client.delete('/api/mappings/drafts/' + draft['file'])

    after = client.get('/api/bonded-parameterizations',
                       query_string={'mapping_hash': draft['mapping_hash']}).json
    assert after['summary']['parameterized'] is False
    assert after['revisions'] == []
