from dashboard.execution.coordination import coordinator as backend

"""Run-type admission and the fixed AA-source/CG-consumer lifecycle."""
import dataclasses
import json
import shutil

import pytest
from dashboard import files
from dashboard.analysis.runs import references as aa_references
from dashboard.execution.adapters import aa, cg
from dashboard.models import mappings
from dashboard.models.molecules import aa as aa_molecules

from tests.dashboard.support import PROJECT_ROOT


@pytest.fixture
def service(tmp_path,monkeypatch,dashboard):
    (tmp_path/'molecules').mkdir()
    shutil.copytree(PROJECT_ROOT/'molecules/DDM',tmp_path/'molecules/DDM')
    monkeypatch.setattr(dashboard.coordinator,'ROOT',tmp_path)
    monkeypatch.setattr(backend.threading.Thread,'start',lambda self:None)
    monkeypatch.setattr(aa,'readiness',lambda *a,**k:{'ready':True,'checks':[],'blockers':[]})
    dashboard.coordinator.database().replace([])
    return dashboard.client


def reference_fixture(dashboard, profile='standard'):
    """A completed, reference-eligible AA run whose recorded settings are its own.

    The profile matters: a consumer inherits the AA half of the run it attaches, and
    references.resolve refuses a consumer whose inherited AA settings differ from the
    reference's, so a draft-smoke consumer needs a reference built at draft-smoke.
    """
    selected=aa_molecules.selection(dashboard.coordinator.ROOT/'molecules','DDM',run_type='aa_only')
    settings=aa.normalize_settings(None,profile)
    job={'id':'111111111111','status':'completed','run_type':'aa_only','reference_eligible':True,'molecule_id':'DDM','molecule_snapshot':selected,'settings':settings,'layout_version':2}
    directory=dashboard.coordinator.RUNS/job['id'];(directory/'stages/07_reference').mkdir(parents=True)
    files.atomic_json(directory/'manifest.json',job|{'stages':[]})
    trajectory=directory/'stages/07_reference/lig.xtc';trajectory.write_bytes(b'Immutable fixture trajectory for lifecycle checks')
    data={'reference_eligible':True,'molecule_identity':aa_references.identity(selected),'settings':settings,
          'protocol_version':aa.VERSION,'frames':{'count':3},'sha256':{'stages/07_reference/lig.xtc':files.sha256(trajectory)}}
    files.atomic_json(directory/'stages/07_reference/reference.json',data)
    dashboard.coordinator.database().insert(job)
    return job


def test_aa_launch_and_clone_do_not_require_cg_tools(dashboard, service,monkeypatch):
    def forbidden(*a,**k):raise AssertionError('AA touched the CG workflow')
    monkeypatch.setattr(cg,'readiness',forbidden)
    response=service.post('/',json={'run_type':'aa_only','molecule_id':'DDM','aa_nvt_ps':5})
    assert response.status_code==201,response.get_json()
    job=response.get_json();assert job['method']=='gromacs' and len(job['workflow_stages'])==7
    dashboard.coordinator.WORKERS.clear()
    clone=service.post('/api/jobs/'+job['id']+'/clone',json={})
    assert clone.status_code==201,clone.get_json()
    assert clone.get_json()['run_type']=='aa_only'
    assert clone.get_json()['settings']['aa_nvt_ps']==5
    assert service.post('/api/jobs/'+job['id']+'/clone',json={'run_type':'unknown'}).status_code==400
    assert service.post('/',json={'run_type':'aa_only','molecule_id':'DDM','mapping_candidate':'anything'}).status_code==400


def test_an_aa_only_job_at_the_smoke_profile_records_short_settings(service):
    """The AA-only half of the same rule: a draft profile shortens an AA-only run too,
    and the job records what it will use."""
    response=service.post('/',json={'run_type':'aa_only','molecule_id':'DDM','profile':'draft-smoke'})
    assert response.status_code==201,response.get_json()
    settings=response.get_json()['settings']
    assert settings['aa_production_ps']==50
    assert settings['aa_nvt_ps']+settings['aa_npt_ps']==10


def test_reference_filter_and_hash_tampering(dashboard, service):
    source=reference_fixture(dashboard)
    dashboard.coordinator.database().insert({'id':'222222222222','status':'completed','detergent':'DDM'})
    assert [r['id'] for r in service.get('/api/references?molecule_id=DDM').get_json()['references']]==[source['id']]
    (dashboard.coordinator.RUNS/source['id']/'stages/07_reference/lig.xtc').write_bytes(b'changed')
    assert service.get('/api/references').get_json()['references']==[]


def test_new_aa_cg_pair_waits_without_taking_second_slot(dashboard, service,monkeypatch):
    monkeypatch.setattr(cg,'readiness',lambda *a,**k:{'ready':True})
    with dashboard.app.test_request_context():
        child=dashboard.coordinator.create_job('DDM','fast_forward',profile='draft-smoke',run_type='aa_cg',molecule_id='DDM',mapping_snapshot=mappings.automatic_candidate(mappings.molecule(), 'DDM'))
    parent=dashboard.coordinator.lookup(child['reference_run_id'])
    assert child['status']=='waiting' and parent['run_type']=='aa_only'
    assert list(dashboard.coordinator.WORKERS)==[parent['id']]
    dashboard.coordinator.database().update(parent['id'],status='failed');dashboard.coordinator.WORKERS.clear();dashboard.coordinator.schedule_waiting()
    assert dashboard.coordinator.lookup(child['id'])['status']=='blocked'


def test_two_completed_consumers_share_source_and_prevent_deletion(dashboard, service,monkeypatch):
    source=reference_fixture(dashboard, 'draft-smoke')
    monkeypatch.setattr(cg,'readiness',lambda *a,**k:{'ready':True})
    consumers=[]
    for _ in range(2):
        with dashboard.app.test_request_context():
            job=dashboard.coordinator.create_job('DDM','fast_forward',profile='draft-smoke',run_type='aa_cg',molecule_id='DDM',reference_run_id=source['id'],mapping_snapshot=mappings.automatic_candidate(mappings.molecule(), 'DDM'))
        assert job['shared_reference']['source_run_id']==source['id']
        consumers.append(job);dashboard.coordinator.database().update(job['id'],status='completed');dashboard.coordinator.WORKERS.clear()
    assert consumers[0]['shared_reference']==consumers[1]['shared_reference']
    assert service.delete('/api/jobs/'+source['id']).status_code==409


def test_cg_worker_does_not_pass_reference_run_id_to_preparation(dashboard, service, monkeypatch):
    source = reference_fixture(dashboard, 'draft-smoke')
    monkeypatch.setattr(cg, 'readiness', lambda *a, **k: {'ready': True})
    captured = {}

    def prepare(root, metadata):
        captured.update(shared_reference=metadata.get('shared_reference'),
                        reference_root=metadata.get('reference_root'))
        root.mkdir(parents=True, exist_ok=True)
        files.atomic_json(root / 'manifest.json', {'stages': []})

    # The protocol object is what the coordinator resolves, and its `prepare` is bound when the adapter builds it,
    # so patching the adapter's private function would have no effect. Replacing the protocol replaces the door.
    monkeypatch.setattr(cg, 'PROTOCOL', dataclasses.replace(cg.PROTOCOL, prepare=prepare))
    monkeypatch.setattr(backend.workflow, 'run', lambda *args, **kwargs: None)
    with dashboard.app.test_request_context():
        job = dashboard.coordinator.create_job(
            'DDM', 'fast_forward', profile='draft-smoke', run_type='aa_cg',
            molecule_id='DDM', reference_run_id=source['id'],
            mapping_snapshot=mappings.automatic_candidate(mappings.molecule(), 'DDM'))
    dashboard.coordinator.WORKERS.clear()

    dashboard.coordinator.run_job(job['id'])

    assert dashboard.coordinator.lookup(job['id'])['status'] == 'completed', dashboard.coordinator.lookup(job['id']).get('error')
    assert captured['shared_reference']['source_run_id'] == source['id']


def test_waiting_consumer_starts_only_after_source_slot_is_released(dashboard, service):
    source=reference_fixture(dashboard)
    child={'id':'222222222222','status':'waiting','run_type':'aa_cg','reference_run_id':source['id'],
           'molecule_snapshot':source['molecule_snapshot'],'settings':source['settings']}
    dashboard.coordinator.database().insert(child)
    dashboard.coordinator.WORKERS[source['id']]=dashboard.coordinator.Worker()
    dashboard.coordinator.schedule_waiting();assert dashboard.coordinator.lookup(child['id'])['status']=='waiting'
    dashboard.coordinator.WORKERS.clear();dashboard.coordinator.schedule_waiting()
    assert dashboard.coordinator.lookup(child['id'])['status']=='queued'
    assert list(dashboard.coordinator.WORKERS)==[child['id']]
    assert dashboard.coordinator.lookup(child['id'])['shared_reference']['source_run_id']==source['id']


def test_aa_retry_rejects_changed_canonical_inputs(dashboard, service):
    response=service.post('/',json={'run_type':'aa_only','molecule_id':'DDM'})
    job=response.get_json();dashboard.coordinator.database().update(job['id'],status='failed');dashboard.coordinator.WORKERS.clear()
    metadata=dashboard.coordinator.ROOT/'molecules/DDM/metadata.json'
    data=json.loads(metadata.read_text());data['name']='Changed';files.atomic_json(metadata,data)
    response=service.post('/retry/'+job['id'])
    assert response.status_code==409
    assert 'changed' in response.get_json()['error']


@pytest.mark.parametrize('run_type', ['aa_only', 'aa_cg'])
@pytest.mark.parametrize('action', ['clone', 'retry', 'resume'])
def test_new_attempt_preserves_run_type_and_shared_source(dashboard, service, monkeypatch, run_type, action):
    monkeypatch.setattr(cg, 'readiness', lambda *a, **k: {'ready': True})
    if run_type == 'aa_only':
        job = service.post('/', json={'run_type': run_type, 'molecule_id': 'DDM'}).get_json()
    else:
        source = reference_fixture(dashboard, 'draft-smoke')
        with dashboard.app.test_request_context():
            job = dashboard.coordinator.create_job('DDM', 'fast_forward', profile='draft-smoke',
                                 run_type=run_type, molecule_id='DDM',
                                 reference_run_id=source['id'],
                                 mapping_snapshot=mappings.automatic_candidate(mappings.molecule(), 'DDM'))
    dashboard.coordinator.database().update(job['id'], status='failed')
    dashboard.coordinator.WORKERS.clear()
    stage = job['stage_plan'][0]
    if action == 'resume':
        # The HTTP test covers routing/admission; test_aa_workflow covers actual
        # upstream checksum verification and preparation of resumed inputs.
        directory = dashboard.coordinator.RUNS/job['id']
        (directory/'inputs').mkdir(parents=True)
        (directory/'inputs/source.txt').write_text('immutable input')
        files.atomic_json(directory/'manifest.json', job | {
            'status': 'failed', 'stages': [],
            'input_snapshot_sha256': files.hashes(directory/'inputs')})
        with dashboard.coordinator.lease(directory/'.worker.lock'):
            blocked = service.post(f"/api/jobs/{job['id']}/resume", json={'stage': stage})
            assert blocked.status_code == 409
            assert 'worker still holds' in blocked.get_json()['error']
        if action == 'resume':
            # Same-run resume admission and completion are covered by the
            # dedicated in-place resume integration fixture.
            return
    endpoint = '/retry/'+job['id'] if action == 'retry' else f"/api/jobs/{job['id']}/{action}"
    response = service.post(endpoint, json={'stage': stage} if action == 'resume' else {})
    assert response.status_code == 201, response.get_json()
    new = response.get_json()
    assert new['id'] != job['id']
    assert new['run_type'] == run_type
    assert new['settings'] == job['settings']
    assert dashboard.coordinator.lookup(job['id'])['status'] == 'failed'
    assert new['scientifically_validated'] is False
    if run_type == 'aa_cg':
        assert new['shared_reference'] == job['shared_reference']
        assert new['reference_run_id'] == source['id']
        assert len([j for j in dashboard.coordinator.database().all() if j['run_type'] == 'aa_only']) == 1
    else:
        assert new['reference_eligible'] is False
        assert not new.get('mapping_snapshot')


def test_shared_source_rejects_changed_inherited_temperature(dashboard, service, monkeypatch):
    source = reference_fixture(dashboard, 'draft-smoke')
    monkeypatch.setattr(cg, 'readiness', lambda *a, **k: {'ready': True})
    response = service.post('/', json={
        'run_type': 'aa_cg', 'molecule_id': 'DDM', 'profile': 'draft-smoke',
        'method': 'fast_forward', 'reference_run_id': source['id'], 'temperature_k': 310})
    assert response.status_code == 409
    assert 'temperature_k' in response.get_json()['error']
    assert len(dashboard.coordinator.database().all()) == 1


def test_a_full_length_reference_cannot_serve_a_smoke_consumer(dashboard, service, monkeypatch):
    """The consumer's inherited AA half has to be the reference's own.

    A draft profile shortens the AA half, so attaching a full-length reference would
    record AA settings the reference was never produced with. The profile is what
    makes the two disagree; the reference is the authority.
    """
    source = reference_fixture(dashboard)
    monkeypatch.setattr(cg, 'readiness', lambda *a, **k: {'ready': True})
    response = service.post('/', json={
        'run_type': 'aa_cg', 'molecule_id': 'DDM', 'profile': 'draft-smoke',
        'method': 'fast_forward', 'reference_run_id': source['id']})
    assert response.status_code == 409
    assert 'aa_nvt_ps' in response.get_json()['error']


def test_cancelled_source_cancels_waiting_consumer(dashboard, service):
    source = reference_fixture(dashboard)
    dashboard.coordinator.database().update(source['id'], status='cancelled')
    child = {'id': '222222222222', 'run_type': 'aa_cg', 'status': 'waiting',
             'reference_run_id': source['id']}
    dashboard.coordinator.database().insert(child)
    dashboard.coordinator.schedule_waiting()
    assert dashboard.coordinator.lookup(child['id'])['status'] == 'cancelled'
    assert not dashboard.coordinator.WORKERS


def test_analysis_sources_resolve_aa_only_and_shared_reference(dashboard, service):
    from dashboard.analysis import worker as analysis
    source = reference_fixture(dashboard)
    root = dashboard.coordinator.RUNS/source['id']
    coordinates = root/'stages/07_reference/lig.gro'
    coordinates.write_text('Lifecycle fixture; no trajectory parsing in this test')
    reference_path = root/'stages/07_reference/reference.json'
    reference = json.loads(reference_path.read_text())
    reference['sha256']['stages/07_reference/lig.gro'] = files.sha256(coordinates)
    files.atomic_json(reference_path, reference)
    verified = aa_references.verify(root)
    consumer = dashboard.coordinator.RUNS/'222222222222'
    (consumer/'stages').mkdir(parents=True)
    files.atomic_json(consumer/'manifest.json', {
        'run_type': 'aa_cg', 'shared_reference': {
            'source_run_id': source['id'], 'sha256': verified['sha256']}})
    expected = {f'1_AA-reference/prod/{name}': root/'stages/07_reference'/name
                for name in ('lig.gro', 'lig.xtc')}
    assert analysis.source_entries(root/'stages', 'bartender-fit') == expected
    assert analysis.source_entries(consumer/'stages', 'bartender-fit') == expected
    assert not list((consumer/'stages').rglob('*.xtc'))
    (root/'stages/07_reference/lig.xtc').unlink()
    with pytest.raises((OSError, ValueError)):
        analysis.source_entries(consumer/'stages', 'bartender-fit')
