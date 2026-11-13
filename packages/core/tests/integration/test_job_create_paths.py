"""The three ways a run is created, held to one contract.

Queue, retry and clone used to pass different arguments to `create_job`, and the difference was not a
decoration: `admission.validate_run_type` requires a parameterization for a `cg` run, so retrying or
cloning one answered 400, and a cloned complex run lost the `protein` and `template` it was built from -- a
different system that happens to share a run type.

These tests do not build those runs. They read what each route hands `create_job`, because that is the seam the
drift was in: a stubbed `create_job` records the call, and a source record states the fields a real one would.
"""
import pytest


def record(**fields):
    """A stored job row, shaped the way the coordinator stores one."""
    base = {'id': 'ab12cd34ef56', 'label': 'a run', 'detergent': 'DDM', 'method': 'bartender',
            'status': 'failed', 'stage': 'complete', 'run_type': 'pdc', 'profile': 'standard',
            'settings': {'pdc_assessment_ns': 100}, 'created': '2026-10-21T02:00:00+00:00'}
    base.update(fields)
    return base


@pytest.fixture
def created(dashboard, monkeypatch):
    """`create_job`, recorded instead of run. Returns the list of calls."""
    calls = []

    def fake(job_or_detergent, method=None, label='', **kwargs):
        calls.append({'detergent': job_or_detergent, 'method': method, 'label': label, **kwargs})
        # Enough of a job row for the route to answer with; no run directory exists, which the view reports.
        return {'id': 'ffeeddccbbaa', 'label': label, 'detergent': job_or_detergent, 'method': method,
                'status': 'queued', 'stage': 'queued', 'run_type': kwargs.get('run_type'),
                'created': '2026-10-21T03:00:00+00:00'}

    monkeypatch.setattr(dashboard.coordinator, 'create_job', fake)
    return calls


MODEL = {'kind': 'composition', 'composition_id': '0123456789abcdef', 'composition_revision': 1,
         'molecule_id': '0123456789abcdef', 'head_molecule_id': 'Trehalose'}
"""A composition CG run's model as the New-run form posts it: the composition's own id, the revision it consumes,
and its head link. A retry or a clone must keep the revision, or it would quietly simulate the derived model."""


def test_cloning_a_composition_run_keeps_the_composition_it_is_a_clone_of(dashboard, created):
    """The 400 this prevents: admission refuses a `cg` payload with no parameterization or composition."""
    dashboard.coordinator.database().insert(record(
        id='ab12cd34ef56', run_type='cg', composition_id=MODEL['composition_id'], method='bartender',
        parameterization=dict(MODEL)))

    response = dashboard.client.post('/api/jobs/ab12cd34ef56/clone', json={'label': 'the clone'})

    assert response.status_code == 201, response.data
    assert len(created) == 1
    assert created[0]['composition_id'] == MODEL['composition_id']
    assert created[0]['run_type'] == 'cg'
    assert created[0]['parameterization'] == MODEL


def test_a_clone_carries_what_a_complex_run_is_built_from(dashboard, created):
    """`protein` and `template` are not settings: without them the clone builds whatever the defaults name."""
    dashboard.coordinator.database().insert(record(id='ab12cd34ef56', run_type='pdc', protein='1AT9',
                                                   template='templates/ddm_belt.json'))

    response = dashboard.client.post('/api/jobs/ab12cd34ef56/clone', json={})

    assert response.status_code == 201, response.data
    assert created[0]['protein'] == '1AT9'
    assert created[0]['template'] == 'templates/ddm_belt.json'


def test_a_retry_carries_the_fields_the_failed_run_was_built_from(dashboard, created):
    """A retry rebuilds the same run. Losing `protein` there rebuilds a different system under the same label."""
    dashboard.coordinator.database().insert(record(id='ab12cd34ef56', run_type='pdc', protein='1AT9',
                                                   template='templates/ddm_belt.json'))

    response = dashboard.client.post('/retry/ab12cd34ef56', json={})

    assert response.status_code == 201, response.data
    call = created[0]
    assert call['protein'] == '1AT9' and call['template'] == 'templates/ddm_belt.json'
    assert call['retry_of'] == 'ab12cd34ef56'
    assert call['run_type'] == 'pdc'


def test_a_retry_of_a_composition_run_keeps_its_composition(dashboard, created):
    """The same drift on the retry path, which answers 400 without it."""
    dashboard.coordinator.database().insert(record(
        id='ab12cd34ef56', run_type='cg', composition_id=MODEL['composition_id'], parameterization=dict(MODEL)))

    response = dashboard.client.post('/retry/ab12cd34ef56', json={})

    assert response.status_code == 201, response.data
    assert created[0]['composition_id'] == MODEL['composition_id']
    assert created[0]['parameterization'] == MODEL


def test_a_protein_detergent_payload_reaches_its_own_readiness(dashboard, monkeypatch):
    """The method allow-list used to refuse every pdc job before its adapter was asked.

    A pdc payload names no method at all -- its topology comes from a mapping, and the panel has no field to fill --
    so the old check answered 400 "Unsupported method" for a run whose own adapter was ready. The rule now asks only
    the run types that map atoms; this test stops at the adapter's readiness, with a stub that refuses, so no run is
    created and the assertion is about which refusal came back.
    """
    from dashboard.execution import protocol

    asked = []

    def readiness(payload):
        asked.append(payload)
        return {'ready': False, 'blockers': ['stub: no protein was given']}

    real = protocol.adapter_for('pdc')

    class Stub:
        """The real adapter with only its readiness replaced: the route and the coordinator ask it several things."""

        def __getattr__(self, name):
            return getattr(real, name)

        def readiness(self, payload):
            return readiness(payload)

    monkeypatch.setitem(protocol._BUILDERS, 'pdc', lambda: Stub())
    # Job creation is `POST /` (`routes/runs.py`), the endpoint the panel's own form posts to; `/api/jobs` is the
    # list and answers 405 to a POST, which is a different refusal and would prove nothing about this one.
    response = dashboard.client.post('/', json={'run_type': 'pdc',
                                               'template': 'molecules/DDM/micelle_template.json',
                                               'protein': 'nowhere/absent.pdb'})

    assert b'Unsupported method' not in response.data
    assert asked, response.data
    assert b'stub: no protein was given' in response.data


def test_queue_keeps_the_transferable_mdp_options_and_the_box_shape(dashboard, created):
    """Every control the New run form offers has a spec, so the queue hands the adapter the value it showed.

    The five families the form's Other run options and Seeds groups add are one claim: the route keeps an advertised
    key. A field without a spec is dropped silently (`SETTING_SPECS`/`CHOICE_SPECS` is what the route filters by), so
    this posts each family through the panel's own endpoint and reads what reached `create_job`.
    """
    response = dashboard.client.post('/', json={
        'molecule_id': 'DDM', 'method': 'fast_forward', 'run_type': 'cg',
        'parameterization': {'kind': 'revision', 'mapping_candidate': 'ddm.map',
                             'starting_coordinates': 'remap'},
        'nstlog': 500, 'nstenergy': 250, 'nstxtcout': 400, 'xtc_precision': 750, 'nstcomm': 50,
        'nstlist': 30, 'verlet_buffer_tolerance': 0.002, 'rlist': 1.25, 'rcoulomb': 1.0, 'rvdw': 1.0,
        'tau_t': 0.5, 'tau_p': 8.0, 'compressibility': 4.0e-5,
        'cg_seed': 7, 'box_shape': 'dodecahedron',
        'mdrun_pmefft': 'cpu', 'mdrun_update': 'cpu', 'mdrun_tunepme': 'off'})

    assert response.status_code == 201, response.data
    settings = created[0]['settings']
    assert settings['nstlog'] == 500 and settings['nstenergy'] == 250
    assert settings['nstxtcout'] == 400 and settings['xtc_precision'] == 750
    assert settings['nstcomm'] == 50 and settings['nstlist'] == 30
    assert settings['verlet_buffer_tolerance'] == 0.002
    assert settings['rlist'] == 1.25 and settings['rcoulomb'] == 1.0 and settings['rvdw'] == 1.0
    assert settings['tau_t'] == 0.5 and settings['tau_p'] == 8.0 and settings['compressibility'] == 4.0e-5
    assert settings['cg_seed'] == 7
    assert settings['box_shape'] == 'dodecahedron'
    assert settings['mdrun_pmefft'] == 'cpu' and settings['mdrun_update'] == 'cpu'
    assert settings['mdrun_tunepme'] == 'off'


def test_the_queue_keeps_the_aa_vsite_choice(dashboard, created):
    """The topology choice is advertised as a choice; an unadvertised key would be dropped silently."""
    response = dashboard.client.post('/', json={
        'molecule_id': 'DDM', 'method': 'gromacs', 'run_type': 'aa_only', 'vsite': 'aromatics'})

    assert response.status_code == 201, response.data
    assert created[0]['settings']['vsite'] == 'aromatics'


def test_the_queue_keeps_the_aa_stage_settings_the_form_offers(dashboard, created):
    """The per-stage timestep, neighbour list, buffer tolerance and coupling are advertised, so the queue keeps them.

    Each has a spec; a field without one is dropped silently and the run would use the default. Posting the families
    through the panel's own endpoint is what proves the values the form showed reach `create_job`. The timestep goes
    above the retired 4 fs ceiling and the hydrogen-mass factor is the one run-wide option, not a stage's.
    """
    response = dashboard.client.post('/', json={
        'molecule_id': 'DDM', 'method': 'gromacs', 'run_type': 'aa_only',
        'aa_nvt_dt_fs': 1, 'aa_npt_dt_fs': 3, 'aa_production_dt_fs': 5,
        'aa_nvt_nstlist': 10, 'aa_npt_nstlist': 40, 'aa_production_nstlist': 100,
        'aa_nvt_verlet_buffer_tolerance': 0.01, 'aa_npt_verlet_buffer_tolerance': 0.05,
        'aa_production_verlet_buffer_tolerance': -1,
        'mass_repartition_factor': 3,
        'aa_nvt_tcoupl': 'Nose-Hoover', 'aa_nvt_tau_t': 2,
        'aa_npt_tcoupl': 'Berendsen', 'aa_npt_pcoupl': 'C-rescale', 'aa_npt_pcoupltype': 'semiisotropic',
        'aa_npt_tau_p': 4, 'aa_npt_compressibility': 2e-5,
        'aa_production_tcoupl': 'V-rescale', 'aa_production_pcoupl': 'Parrinello-Rahman',
        'aa_production_tau_p': 7})

    assert response.status_code == 201, response.data
    settings = created[0]['settings']
    assert (settings['aa_nvt_dt_fs'], settings['aa_npt_dt_fs'], settings['aa_production_dt_fs']) == (1, 3, 5)
    assert (settings['aa_nvt_nstlist'], settings['aa_npt_nstlist'],
            settings['aa_production_nstlist']) == (10, 40, 100)
    assert (settings['aa_nvt_verlet_buffer_tolerance'], settings['aa_npt_verlet_buffer_tolerance'],
            settings['aa_production_verlet_buffer_tolerance']) == (0.01, 0.05, -1)
    assert settings['mass_repartition_factor'] == 3
    assert (settings['aa_nvt_tcoupl'], settings['aa_nvt_tau_t']) == ('Nose-Hoover', 2)
    assert (settings['aa_npt_tcoupl'], settings['aa_npt_pcoupl'], settings['aa_npt_pcoupltype']) == (
        'Berendsen', 'C-rescale', 'semiisotropic')
    assert (settings['aa_npt_tau_p'], settings['aa_npt_compressibility']) == (4, 2e-5)
    assert settings['aa_production_pcoupl'] == 'Parrinello-Rahman' and settings['aa_production_tau_p'] == 7


def test_a_cg_verlet_buffer_tolerance_of_zero_is_refused_through_the_route(dashboard):
    """GROMACS refuses exactly 0, and the CG production domain now starts above it.

    The refusal comes from the adapter's normalizer before a job record is written, so the route answers 400.
    """
    response = dashboard.client.post('/', json={
        'run_type': 'cg', 'molecule_id': '0123456789abcdef', 'detergent': '0123456789abcdef',
        'parameterization': {'kind': 'composition', 'composition_id': '0123456789abcdef',
                             'composition_revision': 1},
        'verlet_buffer_tolerance': 0})

    assert response.status_code == 400, response.data
    assert b'must be between 0.001 and 0.1' in response.data


def test_the_queue_keeps_the_aa_constraint_set_the_form_offers(dashboard, created):
    """`constraints` is a choice spec, and the route keeps only advertised keys.

    An AA-to-CG run takes it from the AA half; an AA-only run is the simplest proof that it reaches `create_job`
    rather than being dropped silently, where the adapter would then run the force field's default.
    """
    response = dashboard.client.post('/', json={'molecule_id': 'DDM', 'method': 'gromacs',
                                               'run_type': 'aa_only', 'constraints': 'h-bonds'})

    assert response.status_code == 201, response.data
    assert created[0]['settings']['constraints'] == 'h-bonds'


def test_a_composition_run_names_its_own_molecule_and_never_the_atomistic_catalogue(dashboard, monkeypatch):
    """A composition's `molecule_id` is the saved CG model, not an `molecules/` folder.

    The queue used to pass every `molecule_id` through the atomistic selection, which refused a well-formed
    composition run as a missing molecule. The run type is what validates the binding, so the coordinator keeps the
    id on the record and lets the composition adapter judge it.
    """
    from dashboard.execution import tools
    from dashboard.models import compositions

    monkeypatch.setattr(tools, 'tool_path', lambda name, **kwargs: f'/injected/{name}')
    record_ = compositions.create_composition({
        'head_fragment_id': 'builtin:martini-sugars-v2:GLC', 'tail_recipe_id': 'linear-c1',
        'carbon_count': 12, 'head_endpoint': {'bead': 'C'}, 'tail_endpoint': {'bead': 'C01'},
        'linkage_profile_id': 'sugar-alkyl-ether-ddm-transfer', 'molecule_name': 'GLC-C12'})
    # Admission and the worker are the queue's business, not this test's: the job record and its readiness are what
    # is being read, so the device check is answered and the worker thread does nothing.
    monkeypatch.setattr(dashboard.coordinator, 'admit_device', lambda job: None)
    monkeypatch.setattr(dashboard.coordinator, 'run_job', lambda *args, **kwargs: None)

    job = dashboard.coordinator.create_job(
        record_['id'], None, 'a composition run', run_type='cg', composition_id=record_['id'],
        molecule_id=record_['id'], parameterization={'kind': 'composition', 'composition_id': record_['id'],
                                                     'molecule_id': record_['id']})

    assert job['status'] == 'queued', 'the run reached the queue rather than being refused as a missing molecule'
    assert job['run_type'] == 'cg' and job['molecule_id'] == record_['id']
    assert job['parameterization']['kind'] == 'composition'
    assert job['stage_plan'] == ['CG simulation', 'CG assessment']


def test_the_queue_keeps_the_composition_revision_a_run_names(dashboard, created):
    """The form posts the revision it showed; the run record must name the same one."""
    response = dashboard.client.post('/', json={
        'run_type': 'cg', 'molecule_id': '0123456789abcdef', 'detergent': '0123456789abcdef',
        'parameterization': {'kind': 'composition', 'composition_id': '0123456789abcdef',
                             'composition_revision': 1}})
    assert response.status_code == 201, response.data
    assert created[0]['parameterization']['composition_revision'] == 1


def test_the_queue_refuses_a_composition_revision_that_is_not_a_number(dashboard, created):
    response = dashboard.client.post('/', json={
        'run_type': 'cg', 'molecule_id': '0123456789abcdef', 'detergent': '0123456789abcdef',
        'parameterization': {'kind': 'composition', 'composition_id': '0123456789abcdef',
                             'composition_revision': -1}})
    assert response.status_code == 400
    assert not created
