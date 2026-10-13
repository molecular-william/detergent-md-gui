"""A protein-detergent job keeps the run type it was queued with.

Every question the coordinator asks about a job -- its readiness, its stage plan, which adapter writes its files --
is answered by its run type, and the creation path used to stamp every non-AA-only job as a CG run. The symptom was
not a wrong label: the CG adapter's readiness check answered a pdc payload, and "this method is not connected to an
executable workflow" is what a reader saw.
"""
from dashboard.app import create_app
from dashboard.execution.adapters.pdc import STAGES as PDC_STAGES
from dashboard.paths import Paths


def test_a_pdc_payload_keeps_its_run_type_and_plan(tmp_path):
    app = create_app(Paths(workspace=tmp_path / 'pdc'), {'TESTING': True, 'DISABLE_COORDINATOR': True})
    client = app.test_client()

    response = client.post('/', json={'molecule_id': 'DDM', 'run_type': 'pdc', 'method': 'bartender',
                                     'template': 'molecules/DDM/micelle_template.json',
                                     'label': 'an empty micelle, for the test'})

    assert response.status_code == 201, response.get_data(as_text=True)
    job = response.json
    assert job['run_type'] == 'pdc'
    assert job['stage_plan'] == [stage.name for stage in PDC_STAGES]
    assert job['template'] == 'molecules/DDM/micelle_template.json'


def test_the_panel_can_read_what_a_complex_build_needs_before_it_queues_one(tmp_path):
    """`GET /api/readiness?run_type=pdc` answers the shape every other run type answers with.

    The panel reads it before the POST, so a build that cannot start says why in the panel rather than in a run that
    dies at stage one. An empty micelle is a stated choice, so a missing protein is an absence, not a blocker.
    """
    app = create_app(Paths(workspace=tmp_path / 'pdc-readiness'), {'TESTING': True, 'DISABLE_COORDINATOR': True})
    client = app.test_client()

    response = client.get('/api/readiness', query_string={
        'run_type': 'pdc', 'template': 'molecules/DDM/micelle_template.json', 'protein': ''})

    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.json
    assert payload['ready'] is True, payload['blockers']
    labels = {check['label']: check for check in payload['checks']}
    assert labels['Protein']['ready'] is True
    assert 'no protein by choice' in labels['Protein']['detail']
    assert labels['Detergent template']['ready'] is True


def test_a_complex_build_with_no_template_is_not_ready_and_says_so(tmp_path):
    app = create_app(Paths(workspace=tmp_path / 'pdc-readiness-empty'), {'TESTING': True, 'DISABLE_COORDINATOR': True})
    client = app.test_client()

    response = client.get('/api/readiness', query_string={'run_type': 'pdc'})

    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.json['ready'] is False
    assert any('Detergent template' in blocker for blocker in response.json['blockers'])


def test_the_complex_build_payload_is_the_one_the_queue_route_reads(tmp_path):
    """The Complexes panel's build posts the shape `queue()` reads: `protein` (a path or null), a seed the adapter
    requires, and settings under the adapter's own names -- not `protein_free`, which nothing consumes.

    The panel used to POST `/api/jobs`, which registers GET only and answers 405, so this pins the route and the
    payload it can actually accept."""
    app = create_app(Paths(workspace=tmp_path / 'pdc-build'), {'TESTING': True, 'DISABLE_COORDINATOR': True})
    client = app.test_client()
    protein = tmp_path / 'prot.pdb'
    protein.write_text('ATOM      1  CA  ALA A   1       0.000   0.000   0.000\n')

    response = client.post('/', json={'molecule_id': 'DDM', 'run_type': 'pdc', 'method': 'bartender',
                                      'template': 'molecules/DDM/micelle_template.json', 'protein': str(protein),
                                      'pdc_seed': 20261013, 'pdc_assessment_ns': 100, 'pdc_extension_ns': 900,
                                      'aggregation_number': 150})

    assert response.status_code == 201, response.get_data(as_text=True)
    job = response.json
    assert job['protein'] == str(protein), 'the route reads `protein`; `protein_free` would reach nothing'
    assert job['settings']['seed'] == 20261013, 'the adapter requires a seed'
    assert job['settings']['assessment_ns'] == 100 and job['settings']['extension_ns'] == 900
