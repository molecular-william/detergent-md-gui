"""Adopting a run directory copied in by hand, over HTTP.

A pasted `runs/<id>/` has no job row, so the Runs list cannot see it. `GET /api/runs/unregistered` names such
directories, `POST /api/runs/adopt` builds the row from the manifest, and `GET /api/references` offers the adopted
AA run -- or names the reason it cannot -- so Bond Interactions can use a reference that was published elsewhere.
"""
import json

from dashboard import files

RUN = 'a1b2c3d4e5f6'


def pasted(dashboard):
    """A run directory in the test's workspace with a manifest and no job row."""
    run = dashboard.paths.workspace / 'runs' / RUN
    (run / 'inputs').mkdir(parents=True)
    document = {'inputs': []}
    (run / 'inputs' / 'inputs.json').write_text(json.dumps(document))
    manifest = {'id': RUN, 'run_type': 'aa_only', 'status': 'completed', 'layout_version': 2,
                'molecule_id': 'Fixture', 'stage_plan': ['AA solvation'], 'stages': [],
                'inputs': [], 'input_snapshot_sha256': files.json_sha256(document)}
    (run / 'manifest.json').write_text(json.dumps(manifest))
    return run


def published_elsewhere(run, *, foreign=True):
    """The reference record a run published from another checkout carries: no in-run artifacts to hash, one source
    recorded by an absolute path that does not exist here."""
    source = ({'role': 'molecule', 'kind': 'file', 'label': 'molecule.itp',
               'path': '/nonexistent/other-checkout/molecules/Fixture/molecule.itp',
               'sha256': '0' * 64} if foreign else
              {'role': 'molecule', 'kind': 'file', 'label': 'missing', 'path': str(run / 'nope'),
               'root': 'absolute', 'sha256': '0' * 64})
    (run / 'stages/07_reference').mkdir(parents=True, exist_ok=True)
    (run / 'stages/07_reference/reference.json').write_text(json.dumps(
        {'schema_version': 1, 'reference_eligible': True, 'sha256': {}, 'referenced_sources': [source]}))


def test_a_pasted_directory_is_listed_adopted_and_listed_as_a_run(dashboard):
    pasted(dashboard)

    listing = dashboard.client.get('/api/runs/unregistered').get_json()['runs']
    assert [run['id'] for run in listing] == [RUN]

    response = dashboard.client.post('/api/runs/adopt', json={'run': RUN})
    assert response.status_code == 201, response.get_json()
    assert response.get_json()['applied'] is True

    jobs = dashboard.client.get('/api/jobs?view=full').get_json()['jobs']
    assert [job['id'] for job in jobs] == [RUN]
    assert dashboard.client.get('/api/runs/unregistered').get_json()['runs'] == []

    assert dashboard.client.post('/api/runs/adopt', json={'run': RUN}).status_code == 409


def test_the_adopt_route_refuses_a_missing_id_and_an_unknown_directory(dashboard):
    assert dashboard.client.post('/api/runs/adopt', json={}).status_code == 400
    assert dashboard.client.post('/api/runs/adopt', json={'run': 'nope'}).status_code == 404


def test_an_adopted_aa_run_is_offered_with_the_provenance_it_could_not_recheck(dashboard):
    run = pasted(dashboard)
    published_elsewhere(run)
    dashboard.client.post('/api/runs/adopt', json={'run': RUN})

    answer = dashboard.client.get('/api/references').get_json()
    assert [reference['id'] for reference in answer['references']] == [RUN]
    assert answer['references'][0]['warnings'], 'the foreign source is stated, not hidden'
    assert 'not present on this host' in answer['references'][0]['warnings'][0]['reason']


def test_a_reference_that_fails_verification_is_named_not_dropped(dashboard):
    run = pasted(dashboard)
    published_elsewhere(run)
    dashboard.client.post('/api/runs/adopt', json={'run': RUN})
    (run / 'stages/07_reference/reference.json').write_text(json.dumps(
        {'schema_version': 1, 'reference_eligible': False, 'sha256': {}, 'referenced_sources': []}))

    answer = dashboard.client.get('/api/references').get_json()
    assert answer['references'] == []
    assert [item['id'] for item in answer['unavailable']] == [RUN]
    assert 'failed technical checks' in answer['unavailable'][0]['reason']
