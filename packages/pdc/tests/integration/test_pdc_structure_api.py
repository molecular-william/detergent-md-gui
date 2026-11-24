"""The `pdc-structure` read route: the record plus its figures as run-relative artifact paths.

The producer's schema is pinned by the unit tests; this file pins the seam the PDC analysis tab reads. A v2 record
names its per-metric PNGs, and the route answers each as `{name, path}` where `path` is what
`GET /api/jobs/<id>/artifacts/<path>?inline=1` fetches -- so the tab never guesses a sibling of the JSON. A v1 record
predates the figures and answers an empty list. The old Complexes system viewer is retired with its route.

The attempt is written here the way `analysis.worker` leaves one behind -- an immutable attempt under
`analyses/pdc-structure/<NNNN-YYYYMMDD>/` whose `result.json` names the content-addressed output directory.
"""
import json

JOB = '0000000000c1'

FIGURES = ['pdc-structure-rdf.png', 'pdc-structure-contacts-protein.png',
           'pdc-structure-contacts-water.png', 'pdc-structure-shape.png',
           'pdc-structure-aggregation.png']

RECORD = {
    'kind': 'pdc-structure',
    'schema_version': 2,
    'figures': FIGURES,
    'rdf': [{'first': 'protein', 'second': 'tail', 'first_peak_nm': 0.47, 'first_peak_g': 2.1}],
    'scientifically_validated': False,
    'protein_present': True,
}
PNG = b'\x89PNG\r\n\x1a\n' + b'pixels'


def seed(dashboard):
    """A completed pdc run with no attempt yet, registered the way the store registers one."""
    dashboard.coordinator.database().insert({'id': JOB, 'run_type': 'pdc', 'status': 'completed',
                                             'stage': 'complete', 'molecule_id': 'DDM',
                                             'created': '2026-11-24T00:00:00+00:00'})


def publish(dashboard, record=RECORD, *, with_figures=True):
    """One published attempt, its record and the PNGs the record names."""
    attempt = dashboard.coordinator.RUNS / JOB / 'analyses/pdc-structure/0001-20261124'
    output = attempt / 'output/abc123'
    output.mkdir(parents=True)
    (attempt / 'result.json').write_text(json.dumps({'output_directory': 'output/abc123'}))
    (output / 'pdc-structure.json').write_text(json.dumps(record))
    if with_figures:
        for name in record.get('figures') or []:
            (output / name).write_bytes(PNG)


def test_each_figure_is_answered_as_its_run_relative_artifact_path(dashboard):
    seed(dashboard)
    publish(dashboard)

    response = dashboard.client.get(f'/api/jobs/{JOB}/pdc-structure')

    assert response.status_code == 200
    body = response.get_json()
    directory = 'analyses/pdc-structure/0001-20261124/output/abc123'
    assert body['figures'] == [{'name': name, 'path': f'{directory}/{name}'} for name in FIGURES]
    assert body['source'] == f'{JOB}/{directory}/pdc-structure.json'
    assert body['schema_version'] == 2 and body['rdf'] == RECORD['rdf'], 'the record is answered beside its figures'


def test_the_derived_path_is_what_the_artifact_route_serves_inline(dashboard):
    seed(dashboard)
    publish(dashboard)
    path = dashboard.client.get(f'/api/jobs/{JOB}/pdc-structure').get_json()['figures'][0]['path']

    response = dashboard.client.get(f'/api/jobs/{JOB}/artifacts/{path}?inline=1')

    assert response.status_code == 200
    assert response.data == PNG
    assert 'attachment' not in response.headers.get('Content-Disposition', '')


def test_a_v1_record_names_no_figures_and_answers_an_empty_list(dashboard):
    seed(dashboard)
    v1 = {key: value for key, value in RECORD.items() if key != 'figures'}
    v1['schema_version'] = 1
    publish(dashboard, v1)

    body = dashboard.client.get(f'/api/jobs/{JOB}/pdc-structure').get_json()

    assert body['figures'] == []
    assert body['schema_version'] == 1


def test_the_retired_complexes_system_viewer_route_is_gone(dashboard):
    seed(dashboard)
    publish(dashboard)

    rules = {rule.rule for rule in dashboard.app.url_map.iter_rules()}
    assert '/api/pdc/<job_id>/system.pdb' not in rules
    assert dashboard.client.get(f'/api/pdc/{JOB}/system.pdb').status_code == 404
