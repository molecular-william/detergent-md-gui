"""Molecule directory admission: bad inputs never become runnable DDM jobs."""
import dataclasses
import json
import shutil
from unittest.mock import patch

import pytest
from dashboard import paths
from dashboard.execution.adapters import cg
from dashboard.execution.coordination import coordinator as backend
from dashboard.models import mappings
from dashboard.models.mappings import context as mapping_context

from tests.harness.support import PROJECT_ROOT, automatic_mapping


@pytest.fixture
def molecules(dashboard, tmp_path, monkeypatch):
    """A molecule tree this test owns, and the coordinator pointed at it rather than the checkout."""
    root = tmp_path/'root'; monkeypatch.setattr(dashboard.coordinator, 'ROOT', root)
    folder = root/'molecules/example'; folder.mkdir(parents=True)
    (folder/'metadata.json').write_text(json.dumps({'name': 'Example', 'force_field': 'example-ff', 'water_model': 'example-water', 'molecule_type': 'EX', 'net_charge': 0}))
    (folder/'molecule.itp').write_text('[ moleculetype ]\nEX 3\n[ atoms ]\n1 C 1 EX C1 1 0 12\n2 C 1 EX C2 2 0 12\n[ bonds ]\n1 2 1 0.15 1000\n')
    (folder/'molecule.gro').write_text('Example\n2\n' + ''.join(f'{1:5d}{"EX":<5}{name:>5}{i:5d}{x:8.3f}{0:8.3f}{0:8.3f}\n' for i,name,x in [(1,'C1',0),(2,'C2',.15)]) + '1 1 1\n')
    dashboard.coordinator.database().replace([])
    return root, folder


def catalogue(client):
    result=client.get('/api/molecules')
    assert result.status_code==200
    return result.get_json()['molecules']


def test_valid_directory_is_executable_for_any_molecule(dashboard, molecules):
    molecules
    entry=catalogue(dashboard.client)[0]
    assert entry['valid']; assert entry['executable']
    assert entry['adapter'] == 'cg-fast-forward'
    assert entry['atom_count']==2
    assert set(entry['sha256'])=={'metadata.json','molecule.itp','molecule.gro'}
    # An unsupported method is rejected at admission time.
    response=dashboard.client.post('/',json={'detergent':'example','method':'unsupported','molecule_id':'example'})
    assert response.status_code==400
    assert dashboard.coordinator.database().all()==[]


def test_aa_only_rejects_a_cg_parameterizer(dashboard, molecules):
    response = dashboard.client.post('/', json={'run_type': 'aa_only', 'detergent': 'DDM', 'method': 'fast_forward'})
    assert response.status_code == 400
    assert 'AA-only' in response.get_json()['error']


def test_missing_and_mismatched_atoms_are_reported(dashboard, molecules):
    _root, folder = molecules
    (folder/'molecule.gro').unlink()
    entry=catalogue(dashboard.client)[0]; assert not entry['valid']
    assert 'molecule.gro' in ' '.join(entry['issues'])
    (folder/'molecule.gro').write_text('Bad\n1\n    1EX      C9    1   0.000   0.000   0.000\n1 1 1\n')
    entry=catalogue(dashboard.client)[0]; assert not entry['valid']
    assert 'atom' in ' '.join(entry['issues']).lower()


def test_virtual_sites_route_derives_parameters_without_queuing(dashboard, molecules):
    """The per-molecule report reads the ITP's own atom types and inline terms; it never creates a job."""
    _root, folder = molecules
    itp = """[ atomtypes ]
C  6  12.011  0.0  A  0.0  0.0
H  1   1.008  0.0  A  0.0  0.0

[ moleculetype ]
EX 3

[ atoms ]
1 C 1 EX C1 1 0 12.011
2 H 1 EX H1 2 0 1.008
3 H 1 EX H2 3 0 1.008
4 H 1 EX H3 4 0 1.008
5 C 1 EX C2 5 0 12.011

[ bonds ]
1 2 1 0.109 1000
1 3 1 0.109 1000
1 4 1 0.109 1000
1 5 1 0.153 1000

[ angles ]
2 1 5 1 109.5 100
3 1 5 1 109.5 100
4 1 5 1 109.5 100
"""
    gro = """Example
5
""" + ''.join(f'{i:5d}{"EX":<5}{name:>5}{i:5d}{x:8.3f}{0:8.3f}{0:8.3f}\n'
                  for i, name, x in [(1, 'C1', 0), (2, 'H1', .1), (3, 'H2', -.1),
                                     (4, 'H3', .1), (5, 'C2', .153)]) + "1 1 1\n"
    (folder/'molecule.itp').write_text(itp)
    (folder/'molecule.gro').write_text(gro)
    response = dashboard.client.post('/api/molecules/example/virtual-sites')
    assert response.status_code == 200, response.get_data(as_text=True)
    report = response.get_json()
    assert [v['name'] for v in report['vsites']] == ['MCH3_1']
    assert report['vsites'][0]['nH'] == 3
    assert report['forcefield']['vsd']
    assert dashboard.coordinator.database().all() == [], 'the report never queues a run'


def test_symlinks_and_traversal_cannot_supply_molecules(dashboard, molecules):
    root, folder = molecules
    (root/'molecules/alias').symlink_to(folder,target_is_directory=True)
    assert [e['id'] for e in catalogue(dashboard.client)]==['example']
    original=folder/'molecule.itp'; original.rename(root/'outside.itp'); original.symlink_to(root/'outside.itp')
    assert not catalogue(dashboard.client)[0]['valid']
    for value in ('../example','/tmp/example','',{},['example']):
        response=dashboard.client.post('/',json={'detergent':'DDM','method':'fast_forward','molecule_id':value})
        assert response.status_code==400,value
    assert dashboard.coordinator.database().all()==[]


def test_readiness_reports_a_missing_molecule_directory(dashboard, molecules):
    # The isolated workspace has no packaged DDM; the readiness endpoint must
    # report the missing-molecule branch through cg.readiness. The tool probes are
    # stubbed to their miss: what is under test is the missing-molecule branch, and
    # really running `gmx -h`, `ff_map`, `ff_inter` and `ff_assess` costs 5.9 s here
    # to reach the same ready=False with the same business-rule blockers.
    with patch.object(backend.aa, 'probe_tool', return_value=(False, 'not installed')), \
         patch.object(cg, 'probe_tool', return_value=(False, 'not installed')):
        response=dashboard.client.get('/api/readiness?molecule_id=example&detergent=example&method=fast_forward&run_type=cg').get_json()
    assert not response['ready']
    assert response['blockers']


def test_new_run_readiness_validates_mapping_against_selected_molecule(dashboard, molecules):
    """The mapping validated here is built in the test, not read out of the developer's workspace.

    It used to copy a candidate from the live drafts directory by filename, so it passed only while that file
    happened to exist and turned red the moment it did not. A test that depends on a developer's data is not
    testing this code.

    The candidate is built from the same context the panel builds one from, and carries that context's snapshot,
    because a candidate is offered to a molecule only when it names that molecule *and* was made against that
    molecule's current source files. Building it from the default structure and leaving the snapshot out is what
    made the list endpoint rightly refuse it.
    """
    root, _folder = molecules
    shutil.copytree(PROJECT_ROOT / 'molecules/Maltose', root / 'molecules/Maltose')
    context = dashboard.client.get('/api/mappings/context?molecule_id=Maltose').get_json()['context']
    # automatic_candidate predates the richer context and takes the adapter built for its consumers, whose
    # bonds are pairs rather than the records the context itself carries.
    candidate = automatic_mapping(mapping_context.as_structure(context), 'Maltose')
    candidate['molecule_id'] = 'Maltose'
    candidate['molecule_snapshot'] = context['snapshot']
    paths.current().mapping_drafts.mkdir(parents=True, exist_ok=True)
    saved = dashboard.client.post('/api/mappings/drafts', json=candidate)
    assert saved.status_code == 201, saved.get_json()      # a new candidate is a created resource
    candidate_name = saved.get_json()['file']
    mappings_response = dashboard.client.get('/api/mappings?view=summary&molecule_id=Maltose')
    response = dashboard.client.get(
        '/api/readiness?run_type=cg&molecule_id=Maltose&detergent=Maltose'
        '&method=fast_forward&profile=draft-smoke&mapping_candidate=' + candidate_name
        + '&parameterization=' + json.dumps({'kind': 'revision', 'mapping_candidate': candidate_name})
    )

    assert mappings_response.status_code == 200, mappings_response.get_json()
    assert [item['file'] for item in mappings_response.get_json()['candidates']] == [candidate_name]
    assert response.status_code == 200, response.get_json()
    answer = response.get_json()
    # The candidate was loaded against Maltose's own source files: the next refusal is that this mapping carries
    # no parameterization revision, not that the molecule changed or that another molecule's model was named.
    assert any('carries no parameterization revision' in blocker for blocker in answer['blockers']), answer['blockers']


def install_ddm(root):
    shutil.copytree(PROJECT_ROOT/'molecules/DDM',root/'molecules/DDM')


def queue_ddm(dashboard, root):
    """A revision-kind CG job; the model lookup is stubbed at the store boundary.

    The run type consumes a saved revision and reuses the AA reference that revision recorded, so a fixture that
    is about molecule selection provenance supplies both rather than building a fit.
    """
    owner = dashboard.coordinator
    source = {'id': '111111111111', 'status': 'completed', 'run_type': 'aa_only'}
    owner.database().insert(source)
    (owner.RUNS / source['id'] / 'stages/07_reference').mkdir(parents=True, exist_ok=True)
    mapping = {**automatic_mapping(mappings.molecule(), 'DDM'), 'file': 'ddm.map'}
    revision = {'revision': 1, 'engine': 'fast-forward', 'options': {},
                'aa_reference': {'run_id': source['id'], 'reference_sha256': None}}
    with patch.object(cg, 'chosen_revision', return_value=revision), \
            patch.object(backend.aa_references, 'resolve',
                         return_value=(owner.RUNS / source['id'] / 'stages/07_reference', {'sha256': {}})), \
            patch.object(cg, 'parameterization_readiness',
                         return_value={'ready': True, 'checks': [], 'blockers': []}), \
            patch.object(backend.threading.Thread, 'start'):
        job = owner.create_job('DDM', 'fast_forward', profile='draft-smoke', run_type='cg',
                               molecule_id='DDM', mapping_snapshot=mapping,
                               parameterization={'kind': 'revision', 'mapping_candidate': 'ddm.map',
                                                 'starting_coordinates': 'remap'})
    return job


def test_queued_job_fails_if_molecule_files_change(dashboard, molecules):
    root, _folder = molecules
    install_ddm(root); job=queue_ddm(dashboard, root)
    path=root/'molecules/DDM/metadata.json'
    data=json.loads(path.read_text()); data['name']='Changed after queue';path.write_text(json.dumps(data))
    with patch.object(cg, 'parameterization_readiness',
                      return_value={'ready': True, 'checks': [], 'blockers': []}):
        dashboard.coordinator.run_job(job['id'],dashboard.coordinator.WORKERS[job['id']])
    finished=dashboard.coordinator.lookup(job['id'])
    assert finished['status']=='failed'
    assert 'changed' in finished['error']
    assert not (dashboard.coordinator.RUNS/job['id']/'stages').exists()
    manifest=json.loads((dashboard.coordinator.RUNS/job['id']/'manifest.json').read_text())
    assert manifest['molecule_snapshot']==job['molecule_snapshot']


def test_modified_ddm_remains_valid_and_executable_but_loses_packaged_provenance(dashboard, molecules):
    root, _folder = molecules
    install_ddm(root)
    path=root/'molecules/DDM/results/MMFF/lig1.pdb'
    lines=path.read_text().splitlines()
    index=next(i for i,line in enumerate(lines) if line.startswith(('ATOM  ', 'HETATM')))
    lines[index]=lines[index][:30]+f'{-99.0:8.3f}'+lines[index][38:]
    path.write_text('\n'.join(lines)+'\n')
    entry=next(e for e in catalogue(dashboard.client) if e['id']=='DDM')
    assert entry['valid']
    assert entry['executable']
    assert entry['adapter'] == 'cg-fast-forward'
    assert 'adapter_sources' not in entry


def test_cloning_ignores_a_missing_molecule_selection(dashboard, molecules):
    root, _folder = molecules
    install_ddm(root); job=queue_ddm(dashboard, root); dashboard.coordinator.WORKERS.clear()
    response=dashboard.client.post('/api/jobs/'+job['id']+'/clone',json={'molecule_id':'nonexistent'})
    # Nonexistent molecule id is rejected as a bad request.
    assert response.status_code==409
    assert len(dashboard.coordinator.database().all())==2, 'the failed run and its reference remain'


def test_mismatched_prepared_source_fails_and_keeps_selection_provenance(dashboard, molecules):
    from dashboard import files
    root, _folder = molecules
    install_ddm(root); job=queue_ddm(dashboard, root)
    def prepare(directory, metadata):
        aa=directory/'stages/1_AA-reference'; aa.mkdir(parents=True)
        (aa/'molecule.pdb').write_text('wrong source')
        files.atomic_json(directory/'manifest.json',{'stages':[]})
    with patch.object(cg,'parameterization_readiness',return_value={'ready':True,'checks':[],'blockers':[]}), patch.object(cg,'PROTOCOL',dataclasses.replace(cg.PROTOCOL,prepare=prepare)):
        dashboard.coordinator.run_job(job['id'],dashboard.coordinator.WORKERS[job['id']])
    manifest=json.loads((dashboard.coordinator.RUNS/job['id']/'manifest.json').read_text())
    assert manifest['status']=='failed'
    assert manifest.get('molecule_snapshot')==job['molecule_snapshot']
