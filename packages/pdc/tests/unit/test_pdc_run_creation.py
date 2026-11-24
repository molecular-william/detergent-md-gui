"""A protein-detergent job keeps the run type it was queued with.

Every question the coordinator asks about a job -- its readiness, its stage plan, which adapter writes its files --
is answered by its run type, and the creation path used to stamp every non-AA-only job as a CG run. The symptom was
not a wrong label: the CG adapter's readiness check answered a pdc payload, and "this method is not connected to an
executable workflow" is what a reader saw.
"""
import pytest
from dashboard.app import create_app
from dashboard.paths import Paths
from detergent_pdc.execution.adapters.pdc import STAGES as PDC_STAGES


def test_a_pdc_payload_keeps_its_run_type_and_plan(tmp_path):
    app = create_app(Paths(workspace=tmp_path / 'pdc'), {'TESTING': True, 'DISABLE_COORDINATOR': True})
    client = app.test_client()

    response = client.post('/', json={'molecule_id': 'DDM', 'run_type': 'pdc', 'method': 'bartender',
                                     'template': 'molecules/DDM/v1/micelle_template.json',
                                     'label': 'an empty micelle, for the test'})

    assert response.status_code == 201, response.get_data(as_text=True)
    job = response.json
    assert job['run_type'] == 'pdc'
    assert job['stage_plan'] == [stage.name for stage in PDC_STAGES]
    assert job['template'] == 'molecules/DDM/v1/micelle_template.json'
    assert job['settings']['prepare_protein'] is False, \
        'an empty-micelle job must not carry the protein-only preparation default'


def test_the_panel_can_read_what_a_complex_build_needs_before_it_queues_one(tmp_path):
    """`GET /api/readiness?run_type=pdc` answers the shape every other run type answers with.

    The panel reads it before the POST, so a build that cannot start says why in the panel rather than in a run that
    dies at stage one. An empty micelle is a stated choice, so a missing protein is an absence, not a blocker.
    """
    app = create_app(Paths(workspace=tmp_path / 'pdc-readiness'), {'TESTING': True, 'DISABLE_COORDINATOR': True})
    client = app.test_client()

    response = client.get('/api/readiness', query_string={
        'run_type': 'pdc', 'template': 'molecules/DDM/v1/micelle_template.json', 'protein': ''})

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
                                      'template': 'molecules/DDM/v1/micelle_template.json', 'protein': str(protein),
                                      'pdc_seed': 20261013, 'pdc_assessment_ns': 100, 'pdc_extension_ns': 900,
                                      'aggregation_number': 150})

    assert response.status_code == 201, response.get_data(as_text=True)
    job = response.json
    assert job['protein'] == str(protein), 'the route reads `protein`; `protein_free` would reach nothing'
    assert job['settings']['seed'] == 20261013, 'the adapter requires a seed'
    assert job['settings']['assessment_ns'] == 100 and job['settings']['extension_ns'] == 900


def queue_pdc(tmp_path, name='queue', **extra):
    app = create_app(Paths(workspace=tmp_path / name), {'TESTING': True, 'DISABLE_COORDINATOR': True})
    payload = {'molecule_id': 'DDM', 'run_type': 'pdc', 'method': 'bartender',
               'template': 'molecules/DDM/v1/micelle_template.json', 'pdc_seed': 20261013,
               'aggregation_number': 150, 'pdc_placement_mode': 'lattice'}
    payload.update(extra)
    return app.test_client().post('/', json=payload)


def stub_preview(monkeypatch, notes):
    from detergent_pdc.execution import pdc_preview
    calls = []

    def fake(**kwargs):
        calls.append(kwargs)
        return {'valid': True, 'reasons': [], 'basis': {'box_notes': list(notes)},
                'pdb': '', 'cost': {}}

    monkeypatch.setattr(pdc_preview, 'preview', fake)
    return calls


def test_a_starting_box_that_cannot_hold_the_system_is_refused_at_the_queue(tmp_path, monkeypatch):
    """A run the reader asked a cell for and cannot have is not admitted, and the sentence says which axis.

    The question is the preview's own: the same placement measures the belt's reach, so admission and the picture
    cannot disagree about whether the stated box fits.
    """
    note = 'the stated x box (14 nm) is smaller than this system needs (18.2193 nm); the cell is written at 18.2193 nm'
    calls = stub_preview(monkeypatch, [note])

    response = queue_pdc(tmp_path, initial_x_nm=14, initial_y_nm=14, initial_z_nm=12)

    assert response.status_code == 400, response.get_data(as_text=True)
    assert 'the starting box cannot hold this system' in response.json['error']
    assert 'stated x box (14 nm)' in response.json['error']
    assert 'Clear the box fields' in response.json['error']
    assert len(calls) == 1
    assert calls[0]['initial_x_nm'] == 14.0 and calls[0]['initial_y_nm'] == 14.0
    assert calls[0]['initial_z_nm'] == 12.0
    assert calls[0]['seed'] == 20261013, 'the queue spelling pdc_seed reaches the placement as seed'
    assert calls[0]['placement_mode'] == 'lattice'


def test_a_payload_with_no_stated_box_asks_the_box_question_nowhere(tmp_path, monkeypatch):
    calls = stub_preview(monkeypatch, ['never asked'])

    response = queue_pdc(tmp_path, name='no-box')

    assert response.status_code == 201, response.get_data(as_text=True)
    assert calls == [], 'a blank box is derived, so there is no fit question to ask'


def test_a_stated_box_the_system_fits_is_admitted(tmp_path, monkeypatch):
    calls = stub_preview(monkeypatch, [])

    response = queue_pdc(tmp_path, name='fits', initial_x_nm=30, initial_y_nm=31, initial_z_nm=40)

    assert response.status_code == 201, response.get_data(as_text=True)
    assert len(calls) == 1



def test_a_retry_carries_the_job_settings_into_the_same_admission_rule(tmp_path, monkeypatch):
    """A retry is a queue: the job's own box is checked before it is re-queued.

    The carried payload is the job record in admission's spelling -- settings (including the stated box), the run
    type, the protein and the template -- so a failed run whose box cannot hold its system is not restarted by Retry.
    """
    note = 'the stated y box (14 nm) is smaller than this system needs (18.2193 nm); the cell is written at 18.2193 nm'
    stub_preview(monkeypatch, [note])
    from dashboard.execution.coordination import admission
    from dashboard.web.routes.runs import _carried_payload

    job = {'run_type': 'pdc', 'method': 'bartender', 'molecule_id': 'DDM',
           'template': 'molecules/DDM/v1/micelle_template.json', 'protein': None,
           'settings': {'seed': 20261013, 'aggregation_number': 150, 'placement_mode': 'lattice',
                        'initial_x_nm': 14.0, 'initial_y_nm': 14.0, 'initial_z_nm': 12.0}}

    carried = _carried_payload(job)
    assert carried['run_type'] == 'pdc' and carried['initial_y_nm'] == 14.0
    assert carried['seed'] == 20261013 and carried['placement_mode'] == 'lattice'
    with pytest.raises(ValueError, match='starting box cannot hold this system'):
        admission.validate_run_type(carried)

