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

from tests.harness.support import PROJECT_ROOT, automatic_mapping


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
    data={'reference_eligible':True,'edition':1,'molecule':'DDM','molecule_identity':aa_references.identity(selected),'settings':settings,
          'protocol_version':aa.VERSION,'frames':{'count':3},'sha256':{'stages/07_reference/lig.xtc':files.sha256(trajectory)}}
    files.atomic_json(directory/'stages/07_reference/reference.json',data)
    dashboard.coordinator.database().insert(job)
    return job


def cg_job(dashboard, monkeypatch, source=None, **overrides):
    """A revision-kind CG job whose model is the one this fixture's AA reference was fitted against.

    The store boundary is stubbed: `cg.chosen_revision` answers the revision the mapping would carry, so the test
    exercises the coordinator's derivation of `shared_reference` from that revision rather than a fit.
    """
    source = source or reference_fixture(dashboard, 'draft-smoke')
    mapping_snapshot = {**automatic_mapping(mappings.molecule(), 'DDM'), 'file': 'ddm.map'}
    revision = {'revision': 1, 'engine': 'fast-forward', 'options': {},
                'aa_reference': {'run_id': source['id'], 'reference_edition': 1}}
    monkeypatch.setattr(cg, 'chosen_revision', lambda *args, **kwargs: revision)
    monkeypatch.setattr(cg, 'parameterization_readiness',
                        lambda *args, **kwargs: {'ready': True, 'checks': [], 'blockers': []})
    with dashboard.app.test_request_context():
        return dashboard.coordinator.create_job(
            'DDM', 'fast_forward', profile='draft-smoke', run_type='cg', molecule_id='DDM',
            mapping_snapshot=mapping_snapshot,
            parameterization={'kind': 'revision', 'mapping_candidate': 'ddm.map',
                              'starting_coordinates': 'remap'}, **overrides)


def test_aa_launch_and_clone_do_not_require_cg_tools(dashboard, service,monkeypatch):
    def forbidden(*a,**k):raise AssertionError('AA touched the CG workflow')
    monkeypatch.setattr(cg,'parameterization_readiness',forbidden)
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


def test_the_queue_route_refuses_a_nonbonded_combination_gromacs_refuses(service):
    """The shared section's refusals are the queue's, not a grompp surprise after the run is admitted."""
    response = service.post('/', json={'run_type': 'aa_only', 'molecule_id': 'DDM', 'rcoulomb': 1.0})
    assert response.status_code == 409, response.get_json()
    assert 'rcoulomb' in response.get_json()['error']
    assert service.post('/', json={'run_type': 'aa_only', 'molecule_id': 'DDM',
                                   'nsttcouple': 10.5}).status_code == 409


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
    # An edition record is trusted by its edition, so a changed byte is not re-hashed (the approved trade). What
    # still refuses is a missing artifact, and the listing excludes that run.
    (dashboard.coordinator.RUNS/source['id']/'stages/07_reference/lig.xtc').unlink()
    assert service.get('/api/references').get_json()['references']==[]


def test_a_cg_revision_run_carries_its_shared_reference_and_creates_no_aa_parent(dashboard, service, monkeypatch):
    """The CG run type reuses the reference its revision was fitted against; it never builds an AA parent."""
    source = reference_fixture(dashboard, 'draft-smoke')
    child = cg_job(dashboard, monkeypatch, source)
    assert child['status'] == 'queued', 'a revision run starts directly; nothing is waiting for an AA parent'
    assert child['run_type'] == 'cg' and child['reference_run_id'] == source['id']
    assert child['shared_reference'] == {'source_run_id': source['id'], 'edition': 1}
    assert 'sha256' not in child['shared_reference'], 'the job pins the edition, never the digest map'
    assert list(dashboard.coordinator.WORKERS) == [child['id']]


def test_two_completed_consumers_share_source_and_prevent_deletion(dashboard, service,monkeypatch):
    source=reference_fixture(dashboard, 'draft-smoke')
    consumers=[]
    for _ in range(2):
        job=cg_job(dashboard, monkeypatch, source)
        assert job['shared_reference']['source_run_id']==source['id']
        consumers.append(job);dashboard.coordinator.database().update(job['id'],status='completed');dashboard.coordinator.WORKERS.clear()
    assert consumers[0]['shared_reference']==consumers[1]['shared_reference']
    assert service.delete('/api/jobs/'+source['id']).status_code==409


def test_cg_worker_does_not_pass_reference_run_id_to_preparation(dashboard, service, monkeypatch):
    source = reference_fixture(dashboard, 'draft-smoke')
    captured = {}

    def prepare(root, metadata):
        captured.update(shared_reference=metadata.get('shared_reference'),
                        reference_root=metadata.get('reference_root'),
                        parameterization=metadata.get('parameterization'))
        root.mkdir(parents=True, exist_ok=True)
        files.atomic_json(root / 'manifest.json', {'stages': []})

    # The protocol object is what the coordinator resolves, and its `prepare` is bound when the adapter builds it,
    # so patching the adapter's private function would have no effect. Replacing the protocol replaces the door.
    job = cg_job(dashboard, monkeypatch, source)
    monkeypatch.setattr(cg, 'PROTOCOL', dataclasses.replace(cg.PROTOCOL, prepare=prepare))
    monkeypatch.setattr(backend.workflow, 'run', lambda *args, **kwargs: None)
    dashboard.coordinator.WORKERS.clear()

    dashboard.coordinator.run_job(job['id'])

    assert dashboard.coordinator.lookup(job['id'])['status'] == 'completed', dashboard.coordinator.lookup(job['id']).get('error')
    assert captured['shared_reference']['source_run_id'] == source['id']
    assert captured['parameterization']['kind'] == 'revision'


def test_aa_retry_rejects_changed_canonical_inputs(dashboard, service):
    response=service.post('/',json={'run_type':'aa_only','molecule_id':'DDM'})
    job=response.get_json();dashboard.coordinator.database().update(job['id'],status='failed');dashboard.coordinator.WORKERS.clear()
    metadata=dashboard.coordinator.ROOT/'molecules/DDM/v1/metadata.json'
    data=json.loads(metadata.read_text());data['name']='Changed';files.atomic_json(metadata,data)
    response=service.post('/retry/'+job['id'])
    assert response.status_code==409
    assert 'changed' in response.get_json()['error']


@pytest.mark.parametrize('run_type', ['aa_only', 'cg'])
@pytest.mark.parametrize('action', ['clone', 'retry', 'resume'])
def test_new_attempt_preserves_run_type_and_shared_source(dashboard, service, monkeypatch, run_type, action):
    if run_type == 'aa_only':
        job = service.post('/', json={'run_type': run_type, 'molecule_id': 'DDM'}).get_json()
    else:
        source = reference_fixture(dashboard, 'draft-smoke')
        job = cg_job(dashboard, monkeypatch, source)
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
    if run_type == 'cg':
        assert new['shared_reference'] == job['shared_reference']
        assert new['reference_run_id'] == source['id']
        assert new['parameterization'] == job['parameterization']
        assert len([j for j in dashboard.coordinator.database().all() if j['run_type'] == 'aa_only']) == 1, \
            'the reference fixture is the only AA run; the CG run creates no parent'
    else:
        assert new['reference_eligible'] is False
        assert not new.get('mapping_snapshot')


def test_a_shared_source_that_changed_is_refused(dashboard, service, monkeypatch):
    """The revision records the reference's edition, and the reference is verified against it.

    A reference whose edition changed under the revision that consumed it is refused before a job exists, exactly as
    the AA-CG pair used to refuse a consumer whose inherited settings disagreed with its source.
    """
    source = reference_fixture(dashboard, 'draft-smoke')
    reference_path = dashboard.coordinator.RUNS / source['id'] / 'stages/07_reference/reference.json'
    record = json.loads(reference_path.read_text())
    files.atomic_json(reference_path, record | {'edition': 1})
    mapping_snapshot = {**automatic_mapping(mappings.molecule(), 'DDM'), 'file': 'ddm.map'}
    revision = {'revision': 1, 'engine': 'fast-forward',
                'aa_reference': {'run_id': source['id'], 'reference_edition': 2}}
    monkeypatch.setattr(cg, 'chosen_revision', lambda *args, **kwargs: revision)
    monkeypatch.setattr(cg, 'parameterization_readiness',
                        lambda *args, **kwargs: {'ready': True, 'checks': [], 'blockers': []})
    with dashboard.app.test_request_context():
        with pytest.raises(backend.SourceUnavailable):
            dashboard.coordinator.create_job(
                'DDM', 'fast_forward', profile='draft-smoke', run_type='cg', molecule_id='DDM',
                mapping_snapshot=mapping_snapshot,
                parameterization={'kind': 'revision', 'mapping_candidate': 'ddm.map'})
    assert len(dashboard.coordinator.database().all()) == 1


def test_a_digest_is_not_a_reference_pin(dashboard, service):
    """A consumer pins the edition; the digest shapes older attachments carried are refused, not compared.

    The one-digest spelling and the artifact map were both accepted while the edition was being introduced. A pin
    that is not an edition now says so, rather than re-hashing a 466 MB trajectory on every readiness check.
    """
    source = reference_fixture(dashboard, 'draft-smoke')
    root = dashboard.coordinator.RUNS / source['id']
    pin = files.sha256(root / 'stages/07_reference/reference.json')

    with pytest.raises(ValueError, match='must be an edition'):
        aa_references.verify(root, pin)
    with pytest.raises(ValueError, match='must be an edition'):
        aa_references.verify(root, {'stages/07_reference/lig.xtc': '0' * 64})


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
            'source_run_id': source['id'], 'edition': verified['edition']}})
    expected = {f'1_AA-reference/prod/{name}': root/'stages/07_reference'/name
                for name in ('lig.gro', 'lig.xtc')}
    assert analysis.source_entries(root/'stages', 'bartender-fit') == expected
    assert analysis.source_entries(consumer/'stages', 'bartender-fit') == expected
    assert not list((consumer/'stages').rglob('*.xtc'))
    (root/'stages/07_reference/lig.xtc').unlink()
    with pytest.raises((OSError, ValueError)):
        analysis.source_entries(consumer/'stages', 'bartender-fit')


def test_an_edition_is_the_reference_pin_and_artifacts_are_not_rehashed(dashboard):
    """A current publication is pinned by `edition`; its artifact map is evidence, not a gate re-read on every use."""
    from dashboard.models.bonded import fitting

    source = reference_fixture(dashboard, 'draft-smoke')
    root = dashboard.coordinator.RUNS / source['id']
    record = json.loads((root / 'stages/07_reference/reference.json').read_text())
    record.update(edition=3, molecule='DDM')
    files.atomic_json(root / 'stages/07_reference/reference.json', record)
    # The recorded map no longer matches the bytes on disk; an edition record is not re-hashed by `verify`.
    (root / 'stages/07_reference/lig.xtc').write_bytes(b'different bytes' * 1000)

    assert aa_references.verify(root, 3)['edition'] == 3
    with pytest.raises(ValueError, match='edition changed since attachment'):
        aa_references.verify(root, 4)
    # A run is addressed by its name, and a fit records the edition it measured against.
    assert aa_references.resolve(dashboard.coordinator.RUNS, source['id'], 3)[1]['edition'] == 3
    resolved = fitting.resolve_reference(source['id'], runs_root=dashboard.coordinator.RUNS)
    assert resolved['edition'] == 3 and resolved['record']['aa_reference']['reference_edition'] == 3


def test_a_cg_run_records_the_choice_settings_it_was_given(dashboard, monkeypatch):
    """The AA choices stay on the CG run's record: they are the reference's provenance, not a parent's job."""
    job = cg_job(dashboard, monkeypatch, settings={'force_field': 'charmm36-jul2022', 'constraints': 'h-bonds'})

    assert job['run_type'] == 'cg'
    assert job['settings']['force_field'] == 'charmm36-jul2022'
    assert job['settings']['constraints'] == 'h-bonds'
    assert len([j for j in dashboard.coordinator.database().all() if j['run_type'] == 'aa_only']) == 1, \
        'the reference fixture is the only AA run; the CG run creates no parent'
