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
