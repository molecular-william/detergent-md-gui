from dashboard.execution.coordination import coordinator as backend
from dashboard.execution.adapters import cg
"""Molecule directory admission: bad inputs never become runnable DDM jobs."""
from tests.dashboard.fixtures import PROJECT_ROOT
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from dashboard import paths
from dashboard.app import default_coordinator as web


class MoleculeDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root/'molecules/example'; self.folder.mkdir(parents=True)
        (self.folder/'metadata.json').write_text(json.dumps({'name': 'Example', 'force_field': 'example-ff', 'water_model': 'example-water', 'molecule_type': 'EX', 'net_charge': 0}))
        (self.folder/'molecule.itp').write_text('[ moleculetype ]\nEX 3\n[ atoms ]\n1 C 1 EX C1 1 0 12\n2 C 1 EX C2 2 0 12\n[ bonds ]\n1 2 1 0.15 1000\n')
        (self.folder/'molecule.gro').write_text('Example\n2\n' + ''.join(f'{1:5d}{"EX":<5}{name:>5}{i:5d}{x:8.3f}{0:8.3f}{0:8.3f}\n' for i,name,x in [(1,'C1',0),(2,'C2',.15)]) + '1 1 1\n')
        for name, value in [('ROOT',self.root),('DATA',self.root/'jobs.sqlite3'),('RUNS',self.root/'runs'),('WORKERS',{}),('ANALYSIS_WORKERS',{})]:
            p=patch.object(web,name,value); p.start(); self.addCleanup(p.stop)
        p=patch.dict(web.app.config,DISABLE_COORDINATOR=True); p.start(); self.addCleanup(p.stop)
        web.save([]); self.client=web.app.test_client()

    def catalogue(self):
        result=self.client.get('/api/molecules')
        self.assertEqual(result.status_code,200)
        return result.get_json()['molecules']

    def test_valid_directory_is_executable_for_any_molecule(self):
        entry=self.catalogue()[0]
        self.assertTrue(entry['valid']); self.assertTrue(entry['executable'])
        self.assertEqual(entry['adapter'], 'cg-fast-forward')
        self.assertEqual(entry['atom_count'],2)
        self.assertEqual(set(entry['sha256']),{'metadata.json','molecule.itp','molecule.gro'})
        # An unsupported method is rejected at admission time.
        response=self.client.post('/',json={'detergent':'example','method':'unsupported','molecule_id':'example'})
        self.assertEqual(response.status_code,400)
        self.assertEqual(web.load(),[])

    def test_aa_only_rejects_a_cg_parameterizer(self):
        response = self.client.post('/', json={'run_type': 'aa_only', 'detergent': 'DDM', 'method': 'fast_forward'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('AA-only', response.get_json()['error'])

    def test_missing_and_mismatched_atoms_are_reported(self):
        (self.folder/'molecule.gro').unlink()
        entry=self.catalogue()[0]; self.assertFalse(entry['valid'])
        self.assertIn('molecule.gro',' '.join(entry['issues']))
        (self.folder/'molecule.gro').write_text('Bad\n1\n    1EX      C9    1   0.000   0.000   0.000\n1 1 1\n')
        entry=self.catalogue()[0]; self.assertFalse(entry['valid'])
        self.assertIn('atom',' '.join(entry['issues']).lower())

    def test_symlinks_and_traversal_cannot_supply_molecules(self):
        (self.root/'molecules/alias').symlink_to(self.folder,target_is_directory=True)
        self.assertEqual([e['id'] for e in self.catalogue()],['example'])
        original=self.folder/'molecule.itp'; original.rename(self.root/'outside.itp'); original.symlink_to(self.root/'outside.itp')
        self.assertFalse(self.catalogue()[0]['valid'])
        for value in ('../example','/tmp/example','',{},['example']):
            response=self.client.post('/',json={'detergent':'DDM','method':'fast_forward','molecule_id':value})
            self.assertEqual(response.status_code,400,value)
        self.assertEqual(web.load(),[])

    def test_readiness_reports_a_missing_molecule_directory(self):
        # The isolated workspace has no packaged DDM; the readiness endpoint must
        # report the missing-molecule branch through cg.readiness.
        response=self.client.get('/api/readiness?molecule_id=example&detergent=example&method=fast_forward&run_type=aa_cg').get_json()
        self.assertFalse(response['ready'])
        self.assertTrue(response['blockers'])

    def test_new_run_readiness_validates_mapping_against_selected_molecule(self):
        shutil.copytree(PROJECT_ROOT / 'molecules/Maltose', self.root / 'molecules/Maltose')
        source = PROJECT_ROOT / 'workspace/dashboard/mapping_drafts/mapping_candidate_75a9442a2f88484d91c3b397b386d5fb.json'
        candidate_name = source.name
        paths.current().mapping_drafts.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, paths.current().mapping_drafts / candidate_name)
        seen = {}

        def readiness(*args, **kwargs):
            seen['candidate'] = args[3]
            return {'ready': True, 'checks': [], 'blockers': []}

        with patch.object(cg, 'readiness', side_effect=readiness), \
             patch.object(backend.aa, 'readiness', return_value={'ready': True, 'blockers': []}):
            mappings_response = self.client.get('/api/mappings?view=summary&molecule_id=Maltose')
            response = self.client.get(
                '/api/readiness?run_type=aa_cg&molecule_id=Maltose&detergent=Maltose'
                '&method=fast_forward&profile=draft-smoke&mapping_candidate=' + candidate_name
            )

        self.assertEqual(mappings_response.status_code, 200, mappings_response.get_json())
        self.assertEqual([item['file'] for item in mappings_response.get_json()['candidates']], [candidate_name])
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(seen['candidate']['molecule_id'], 'Maltose')
        self.assertEqual(seen['candidate']['validation']['issues'], [])

    def install_ddm(self):
        import shutil
        shutil.copytree(PROJECT_ROOT/'molecules/DDM',self.root/'molecules/DDM')

    def queue_ddm(self):
        with patch.object(cg,'readiness',return_value={'ready':True}), patch.object(backend.threading.Thread,'start'):
            response=self.client.post('/',json={'detergent':'DDM','method':'fast_forward','profile':'draft-smoke','molecule_id':'DDM'})
        self.assertEqual(response.status_code,201,response.get_json())
        return web.load()[0]

    def test_queued_job_fails_if_molecule_files_change(self):
        self.install_ddm(); job=self.queue_ddm()
        path=self.root/'molecules/DDM/metadata.json'
        data=json.loads(path.read_text()); data['name']='Changed after queue';path.write_text(json.dumps(data))
        web.run_job(job['id'],web.WORKERS[job['id']])
        finished=web.lookup(job['id'])
        self.assertEqual(finished['status'],'failed')
        self.assertIn('changed',finished['error'])
        self.assertFalse((web.RUNS/job['id']/'stages').exists())
        manifest=json.loads((web.RUNS/job['id']/'manifest.json').read_text())
        self.assertEqual(manifest['molecule_snapshot'],job['molecule_snapshot'])

    def test_modified_ddm_remains_valid_and_executable_but_loses_packaged_provenance(self):
        self.install_ddm()
        path=self.root/'molecules/DDM/results/MMFF/lig1.pdb'
        lines=path.read_text().splitlines()
        index=next(i for i,line in enumerate(lines) if line.startswith(('ATOM  ', 'HETATM')))
        lines[index]=lines[index][:30]+f'{-99.0:8.3f}'+lines[index][38:]
        path.write_text('\n'.join(lines)+'\n')
        entry=next(e for e in self.catalogue() if e['id']=='DDM')
        self.assertTrue(entry['valid'])
        self.assertTrue(entry['executable'])
        self.assertEqual(entry['adapter'], 'cg-fast-forward')
        self.assertNotIn('adapter_sources', entry)

    def test_cloning_ignores_a_missing_molecule_selection(self):
        self.install_ddm(); job=self.queue_ddm(); web.WORKERS.clear()
        response=self.client.post('/api/jobs/'+job['id']+'/clone',json={'molecule_id':'nonexistent'})
        # Nonexistent molecule id is rejected as a bad request.
        self.assertEqual(response.status_code,409)
        self.assertEqual(len(web.load()),1)

    def test_mismatched_prepared_source_fails_and_keeps_selection_provenance(self):
        from dashboard import files
        self.install_ddm(); job=self.queue_ddm()
        def prepare(directory, **kwargs):
            aa=directory/'stages/1_AA-reference'; aa.mkdir(parents=True)
            (aa/'molecule.pdb').write_text('wrong source')
            files.atomic_json(directory/'manifest.json',{'stages':[]})
        with patch.object(cg,'readiness',return_value={'ready':True}), patch.object(backend.workflow,'prepare_run',prepare):
            web.run_job(job['id'],web.WORKERS[job['id']])
        manifest=json.loads((web.RUNS/job['id']/'manifest.json').read_text())
        self.assertEqual(manifest['status'],'failed')
        self.assertEqual(manifest.get('molecule_snapshot'),job['molecule_snapshot'])
