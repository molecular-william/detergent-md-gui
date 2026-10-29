"""Checks against CGbuilder/FF formats, RDKit chemistry, and real grompp."""
import importlib.util
import io
import json
import unittest
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
import pytest
from dashboard.models import mappings
from dashboard.models.mappings import depiction
from rdkit import Chem

from tests.harness.support import fast_forward_source, physical_mapping


class MappingExportTests(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def _application(self, dashboard):
        """The application this test owns; it is built with its coordinator already disabled."""
        self.dashboard = dashboard

    def setUp(self):
        self.data = physical_mapping()

    def test_fast_forward_parser_reads_names_and_order(self):
        path = fast_forward_source('map_file_parers.py')
        if path is None:
            self.skipTest('Fast_Forward source is not provisioned in this checkout')
        spec = importlib.util.spec_from_file_location('ff_mapping_reader', path)
        reader = importlib.util.module_from_spec(spec); spec.loader.exec_module(reader)
        files = mappings.export_files(self.data)
        parsed = reader.read_mapping(files['mapping.map'].splitlines())[-1]['LIG1']
        self.assertEqual(parsed.to_resname, 'DDM')
        self.assertEqual(parsed.beads, [f'B{i+1:02d}' for i in range(len(self.data['beads']))])
        atoms = {a['id']: a for a in mappings.molecule()['atoms']}
        for alias, bead in zip(parsed.beads, self.data['beads']):
            self.assertEqual(parsed.bead_to_atom[alias], [atoms[i]['name'] for i in sorted(bead['atoms'])])
            self.assertTrue(all(weight == 1 for weight in parsed.atom_weights[alias]))

    def test_index_and_coordinates_match_same_assignments(self):
        files = mappings.export_files(self.data)
        sections = files['mapping.ndx'].strip().split('\n\n')
        xyz = {a['id']: a['xyz'] for a in mappings.molecule()['atoms']}
        lines = files['mapped.gro'].splitlines()
        self.assertEqual(int(lines[1]), len(self.data['beads']))
        for i, bead in enumerate(self.data['beads']):
            self.assertEqual(list(map(int, sections[i].splitlines()[1].split())), sorted(bead['atoms']))
            self.assertEqual(lines[i+2][10:15].strip(), f'B{i+1:02d}')
            expected = np.mean([xyz[a] for a in bead['atoms']], axis=0)/10
            actual = [float(lines[i+2][start:start+8]) for start in (20, 28, 36)]
            np.testing.assert_allclose(actual, expected, atol=.00051)

    def test_export_rejects_missing_or_duplicate_atoms(self):
        self.data['beads'][0]['atoms'].pop()
        with self.assertRaisesRegex(ValueError, 'Missing heavy atoms'):
            mappings.export_files(self.data)
        self.data['beads'][0]['atoms'].append(self.data['beads'][1]['atoms'][0])
        with self.assertRaisesRegex(ValueError, 'Repeated atom'):
            mappings.export_files(self.data)

    def test_diagram_preserves_identity_and_has_one_circle_per_bead(self):
        source = mappings.SOURCE/'results/MMFF'
        _, positions, smiles = depiction._base((source/'lig1.mol2').read_text(), (source/'lig1.pdb').read_text(), (source/'lig1.itp').read_text())
        identity = json.loads((mappings.SOURCE/'identity.json').read_text())
        self.assertEqual(smiles, Chem.MolToSmiles(Chem.MolFromSmiles(identity['input_smiles'])))
        self.assertEqual(set(positions), set(range(1,36)))
        self.data['name'] = '<script>not markup</script>'
        root = ET.fromstring(depiction.render(self.data))
        overlay = root.find(f'{{{depiction.NS}}}g[@class="bead-overlays"]')
        self.assertEqual(len(overlay), len(self.data['beads']))
        self.assertEqual(overlay[0].get('data-atoms'), ' '.join(map(str,self.data['beads'][0]['atoms'])))
        self.assertIsNone(root.find('.//script'))
        self.assertIn('unvalidated', root.find(f'{{{depiction.NS}}}title').text)

    def test_bundle_and_svg_endpoints(self):
        with self.dashboard.client as client:
            response = client.post('/api/mappings/export/bundle', json=self.data)
            self.assertEqual(response.status_code, 200)
            with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
                self.assertEqual(set(archive.namelist()), {'mapping.ndx', 'mapping.map', 'mapped.gro', 'model.json', 'README.txt'})
                self.assertEqual(json.loads(archive.read('model.json'))['status'], 'candidate-unvalidated')
            response.close()
            response = client.post('/api/mappings/diagram', json=self.data)
            self.assertEqual(response.status_code, 200)
            self.assertIn('bead-overlays', response.get_json()['svg'])


if __name__ == '__main__':
    unittest.main()
