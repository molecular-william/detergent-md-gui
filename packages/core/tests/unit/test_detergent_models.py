import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dashboard.models import compositions
from dashboard.models.molecules import evidence
from dashboard.models.molecules import registry as model_registry


class DetergentModelTests(unittest.TestCase):
    def test_reference_hash_matches_the_recorded_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'x.itp'; source.write_text('model')
            first={'id':'a'*16, 'source_path':str(source), 'sha256':model_registry.files.sha256(source)}
            with patch.object(model_registry, 'storage_root', return_value=root/'registry'):
                self.assertTrue(model_registry.check_reference(first)['ok'])
                source.write_text('changed')
                self.assertFalse(model_registry.check_reference(first)['ok'])

    def test_composition_is_immutable_and_its_linkage_is_checked(self):
        """One content identity is one saved composition, and its linkage joins the two bead families.

        The record's snapshot hash is the saved file's, so the same fragments, tail and linkage saved again are the
        same composition and are refused rather than duplicated. The linkage is an attachment between distinct bead
        families -- a physical sugar bead on the head and a generated tail bead -- so an endpoint that names neither
        is refused before any record is written.
        """
        payload = {'head_fragment_id': 'builtin:martini-sugars-v2:GLC', 'tail_recipe_id': 'linear-c1',
                   'carbon_count': 12, 'head_endpoint': {'bead': 'C'}, 'tail_endpoint': {'bead': 'C01'},
                   'linkage_profile_id': 'sugar-alkyl-ether-ddm-transfer', 'molecule_name': 'GLC-C12'}
        record = compositions.create_composition(dict(payload))

        stored = json.loads((compositions.storage_root() / f"{record['id']}.json").read_text())
        self.assertEqual(stored['snapshot_hash'], record['snapshot_hash'])
        with self.assertRaisesRegex(ValueError, 'already exists'):
            compositions.create_composition(dict(payload))
        with self.assertRaisesRegex(ValueError, 'physical sugar bead'):
            compositions.preview({**payload, 'head_endpoint': {'bead': 'not-a-sugar-bead'}})
        with self.assertRaisesRegex(ValueError, 'generated tail bead'):
            compositions.preview({**payload, 'tail_endpoint': {'bead': 'not-a-tail-bead'}})

    def test_class_specific_evidence(self):
        self.assertFalse(evidence.evaluate('detergent', {})['validated'])
        result={k:{'passed':True} for k in evidence.PROFILES['detergent']}
        self.assertTrue(evidence.evaluate('detergent', result)['validated'])

if __name__ == '__main__': unittest.main()
