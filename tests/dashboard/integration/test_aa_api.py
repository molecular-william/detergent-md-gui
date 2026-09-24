from dashboard.execution.coordination import coordinator as backend
"""Run-type admission and the fixed AA-source/CG-consumer lifecycle."""
from tests.dashboard.fixtures import PROJECT_ROOT
import json
from pathlib import Path
import shutil
import pytest
from dashboard.app import default_coordinator as web
from dashboard.execution.adapters import aa
from dashboard.models.molecules import aa as aa_molecules
from dashboard.analysis.runs import references as aa_references
from dashboard import files
from dashboard.models import mappings


@pytest.fixture
def service(tmp_path,monkeypatch):
    (tmp_path/'molecules').mkdir()
    shutil.copytree(PROJECT_ROOT/'molecules/DDM',tmp_path/'molecules/DDM')
    for key,value in {'ROOT':tmp_path,'DATA':tmp_path/'jobs.sqlite3','RUNS':tmp_path/'runs','WORKERS':{},'ANALYSIS_WORKERS':{}}.items():monkeypatch.setattr(web,key,value)
    monkeypatch.setitem(web.app.config,'DISABLE_COORDINATOR',True)
    monkeypatch.setattr(backend.threading.Thread,'start',lambda self:None)
    monkeypatch.setattr(aa,'readiness',lambda *a,**k:{'ready':True,'checks':[],'blockers':[]})
    web.save([])
    return web.app.test_client()


def reference_fixture():
    selected=aa_molecules.selection(web.ROOT/'molecules','DDM',run_type='aa_only')
    job={'id':'111111111111','status':'completed','run_type':'aa_only','reference_eligible':True,'molecule_id':'DDM','molecule_snapshot':selected,'settings':aa.DEFAULTS,'layout_version':2}
    directory=web.RUNS/job['id'];(directory/'stages/07_reference').mkdir(parents=True)
    files.atomic_json(directory/'manifest.json',job|{'stages':[]})
    trajectory=directory/'stages/07_reference/lig.xtc';trajectory.write_bytes(b'Immutable fixture trajectory for lifecycle checks')
    data={'reference_eligible':True,'molecule_identity':aa_references.identity(selected),'settings':aa.DEFAULTS,
          'protocol_version':aa.VERSION,'frames':{'count':3},'sha256':{'stages/07_reference/lig.xtc':files.sha256(trajectory)}}
    files.atomic_json(directory/'stages/07_reference/reference.json',data)
    web.database().insert(job)
    return job


def test_aa_launch_and_clone_do_not_require_cg_tools(service,monkeypatch):
    def forbidden(*a,**k):raise AssertionError('AA touched the CG workflow')
    monkeypatch.setattr(backend.workflow,'readiness',forbidden)
    response=service.post('/',json={'run_type':'aa_only','molecule_id':'DDM','aa_nvt_ps':5})
    assert response.status_code==201,response.get_json()
    job=response.get_json();assert job['method']=='gromacs' and len(job['workflow_stages'])==7
    web.WORKERS.clear()
    clone=service.post('/api/jobs/'+job['id']+'/clone',json={})
    assert clone.status_code==201,clone.get_json()
    assert clone.get_json()['run_type']=='aa_only'
    assert clone.get_json()['settings']['aa_nvt_ps']==5
    assert service.post('/api/jobs/'+job['id']+'/clone',json={'run_type':'unknown'}).status_code==400
    assert service.post('/',json={'run_type':'aa_only','molecule_id':'DDM','mapping_candidate':'anything'}).status_code==400


def test_reference_filter_and_hash_tampering(service):
    source=reference_fixture()
    web.database().insert({'id':'222222222222','status':'completed','detergent':'DDM'})
    assert [r['id'] for r in service.get('/api/references?molecule_id=DDM').get_json()['references']]==[source['id']]
    (web.RUNS/source['id']/'stages/07_reference/lig.xtc').write_bytes(b'changed')
    assert service.get('/api/references').get_json()['references']==[]


def test_new_aa_cg_pair_waits_without_taking_second_slot(service,monkeypatch):
    monkeypatch.setattr(backend.workflow,'readiness',lambda *a,**k:{'ready':True})
    with web.app.test_request_context():
        child=web.create_job('DDM','fast_forward',profile='draft-smoke',run_type='aa_cg',molecule_id='DDM',mapping_snapshot=mappings.automatic_candidate(mappings.molecule(), 'DDM'))
    parent=web.lookup(child['reference_run_id'])
    assert child['status']=='waiting' and parent['run_type']=='aa_only'
    assert list(web.WORKERS)==[parent['id']]
    web.update_job(parent['id'],status='failed');web.WORKERS.clear();web.schedule_waiting()
    assert web.lookup(child['id'])['status']=='blocked'


def test_two_completed_consumers_share_source_and_prevent_deletion(service,monkeypatch):
    source=reference_fixture()
    monkeypatch.setattr(backend.workflow,'readiness',lambda *a,**k:{'ready':True})
    consumers=[]
    for _ in range(2):
        with web.app.test_request_context():
            job=web.create_job('DDM','fast_forward',profile='draft-smoke',run_type='aa_cg',molecule_id='DDM',reference_run_id=source['id'],mapping_snapshot=mappings.automatic_candidate(mappings.molecule(), 'DDM'))
        assert job['shared_reference']['source_run_id']==source['id']
        consumers.append(job);web.update_job(job['id'],status='completed');web.WORKERS.clear()
    assert consumers[0]['shared_reference']==consumers[1]['shared_reference']
    assert service.delete('/api/jobs/'+source['id']).status_code==409


def test_cg_worker_does_not_pass_reference_run_id_to_preparation(service, monkeypatch):
    source = reference_fixture()
    monkeypatch.setattr(backend.workflow, 'readiness', lambda *a, **k: {'ready': True})
    captured = {}

    def prepare(root, *, detergent, profile, settings, mapping_candidate,
                bonded_state_snapshot, bonded_intent, shared_reference,
                reference_root, molecule_snapshot, molecule_root):
        captured.update(shared_reference=shared_reference, reference_root=reference_root)
        files.atomic_json(root / 'manifest.json', {'stages': []})

    monkeypatch.setattr(backend.workflow, 'prepare_run', prepare)
    monkeypatch.setattr(backend.workflow, 'run', lambda *args, **kwargs: None)
    with web.app.test_request_context():
        job = web.create_job(
            'DDM', 'fast_forward', profile='draft-smoke', run_type='aa_cg',
            molecule_id='DDM', reference_run_id=source['id'],
            mapping_snapshot=mappings.automatic_candidate(mappings.molecule(), 'DDM'))
    web.WORKERS.clear()

    web.run_job(job['id'])

    assert web.lookup(job['id'])['status'] == 'completed', web.lookup(job['id']).get('error')
    assert captured['shared_reference']['source_run_id'] == source['id']


def test_waiting_consumer_starts_only_after_source_slot_is_released(service):
    source=reference_fixture()
    child={'id':'222222222222','status':'waiting','run_type':'aa_cg','reference_run_id':source['id'],
           'molecule_snapshot':source['molecule_snapshot'],'settings':source['settings']}
    web.database().insert(child)
    web.WORKERS[source['id']]=web.Worker()
    web.schedule_waiting();assert web.lookup(child['id'])['status']=='waiting'
    web.WORKERS.clear();web.schedule_waiting()
    assert web.lookup(child['id'])['status']=='queued'
    assert list(web.WORKERS)==[child['id']]
    assert web.lookup(child['id'])['shared_reference']['source_run_id']==source['id']


def test_aa_retry_rejects_changed_canonical_inputs(service):
    response=service.post('/',json={'run_type':'aa_only','molecule_id':'DDM'})
    job=response.get_json();web.update_job(job['id'],status='failed');web.WORKERS.clear()
    metadata=web.ROOT/'molecules/DDM/metadata.json'
    data=json.loads(metadata.read_text());data['name']='Changed';files.atomic_json(metadata,data)
    response=service.post('/retry/'+job['id'])
    assert response.status_code==409
    assert 'changed' in response.get_json()['error']


@pytest.mark.parametrize('run_type', ['aa_only', 'aa_cg'])
@pytest.mark.parametrize('action', ['clone', 'retry', 'resume'])
def test_new_attempt_preserves_run_type_and_shared_source(service, monkeypatch, run_type, action):
    monkeypatch.setattr(backend.workflow, 'readiness', lambda *a, **k: {'ready': True})
    if run_type == 'aa_only':
        job = service.post('/', json={'run_type': run_type, 'molecule_id': 'DDM'}).get_json()
    else:
        source = reference_fixture()
        with web.app.test_request_context():
            job = web.create_job('DDM', 'fast_forward', profile='draft-smoke',
                                 run_type=run_type, molecule_id='DDM',
                                 reference_run_id=source['id'],
                                 mapping_snapshot=mappings.automatic_candidate(mappings.molecule(), 'DDM'))
    web.update_job(job['id'], status='failed')
    web.WORKERS.clear()
    stage = job['stage_plan'][0]
    if action == 'resume':
        # The HTTP test covers routing/admission; test_aa_workflow covers actual
        # upstream checksum verification and preparation of resumed inputs.
        directory = web.RUNS/job['id']
        (directory/'inputs').mkdir(parents=True)
        (directory/'inputs/source.txt').write_text('immutable input')
        files.atomic_json(directory/'manifest.json', job | {
            'status': 'failed', 'stages': [],
            'input_snapshot_sha256': files.hashes(directory/'inputs')})
        with web.lease(directory/'.worker.lock'):
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
    assert web.lookup(job['id'])['status'] == 'failed'
    assert new['scientifically_validated'] is False
    if run_type == 'aa_cg':
        assert new['shared_reference'] == job['shared_reference']
        assert new['reference_run_id'] == source['id']
        assert len([j for j in web.load() if j['run_type'] == 'aa_only']) == 1
    else:
        assert new['reference_eligible'] is False
        assert not new.get('mapping_snapshot')


def test_shared_source_rejects_changed_inherited_temperature(service, monkeypatch):
    source = reference_fixture()
    monkeypatch.setattr(backend.workflow, 'readiness', lambda *a, **k: {'ready': True})
    response = service.post('/', json={
        'run_type': 'aa_cg', 'molecule_id': 'DDM', 'profile': 'draft-smoke',
        'method': 'fast_forward', 'reference_run_id': source['id'], 'temperature_k': 310})
    assert response.status_code == 409
    assert 'temperature_k' in response.get_json()['error']
    assert len(web.load()) == 1


def test_cancelled_source_cancels_waiting_consumer(service):
    source = reference_fixture()
    web.update_job(source['id'], status='cancelled')
    child = {'id': '222222222222', 'run_type': 'aa_cg', 'status': 'waiting',
             'reference_run_id': source['id']}
    web.database().insert(child)
    web.schedule_waiting()
    assert web.lookup(child['id'])['status'] == 'cancelled'
    assert not web.WORKERS


def test_snapshot_analysis_resolves_aa_only_and_shared_source(service):
    from dashboard.analysis import worker as analysis
    source = reference_fixture()
    root = web.RUNS/source['id']
    coordinates = root/'stages/07_reference/lig.gro'
    coordinates.write_text('Lifecycle fixture; no trajectory parsing in this test')
    reference_path = root/'stages/07_reference/reference.json'
    reference = json.loads(reference_path.read_text())
    reference['sha256']['stages/07_reference/lig.gro'] = files.sha256(coordinates)
    files.atomic_json(reference_path, reference)
    verified = aa_references.verify(root)
    consumer = web.RUNS/'222222222222'
    (consumer/'stages').mkdir(parents=True)
    files.atomic_json(consumer/'manifest.json', {
        'run_type': 'aa_cg', 'shared_reference': {
            'source_run_id': source['id'], 'sha256': verified['sha256']}})
    expected = {f'1_AA-reference/prod/{name}': root/'stages/07_reference'/name
                for name in ('lig.gro', 'lig.xtc')}
    assert analysis.source_entries(root/'stages', 'snapshots') == expected
    assert analysis.source_entries(consumer/'stages', 'snapshots') == expected
    assert not list((consumer/'stages').rglob('*.xtc'))
    (root/'stages/07_reference/lig.xtc').unlink()
    with pytest.raises((OSError, ValueError)):
        analysis.source_entries(consumer/'stages', 'snapshots')
