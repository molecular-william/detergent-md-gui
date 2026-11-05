import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dashboard.cli import migration
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

    def test_composition_is_immutable_and_attachment_is_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'x'; source.write_text('x')
            with patch.object(model_registry, 'storage_root', return_value=root/'registry'), patch.object(compositions, 'storage_root', return_value=root/'compositions'):
                fragments=root/'registry'/'fragments'; fragments.mkdir(parents=True)
                a={'id':'a'*16,'name':'head','topology':{'beads':['A']}}
                b={'id':'b'*16,'name':'tail','topology':{'beads':['B']}}
                (fragments/f"{a['id']}.json").write_text(json.dumps(a)); (fragments/f"{b['id']}.json").write_text(json.dumps(b))
                record=compositions.create({'fragments':[a['id'],b['id']], 'attachments':[{'left_fragment':a['id'],'right_fragment':b['id'],'left_atom':1,'right_atom':2}]})
                before=json.loads((root/'compositions'/f"{record['id']}.json").read_text())
                self.assertEqual(before['snapshot_hash'], record['snapshot_hash'])
                with self.assertRaises(ValueError): compositions.create({'fragments':[a['id'],b['id']], 'attachments':[{'left_fragment':a['id'],'right_fragment':a['id'],'left_atom':1,'right_atom':2}]})

    def test_class_specific_evidence(self):
        self.assertFalse(evidence.evaluate('detergent', {})['validated'])
        result={k:{'passed':True} for k in evidence.PROFILES['detergent']}
        self.assertTrue(evidence.evaluate('detergent', result)['validated'])

    def test_obsolete_deletion_requires_hash_and_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); path=root/'old'; path.write_text('old')
            report=migration.mark_obsolete(migration.inventory(root), ['old'])
            with self.assertRaises(ValueError): migration.delete_approved(report, root)
            self.assertEqual(migration.delete_approved(report, root, True)['count'], 1)

if __name__ == '__main__': unittest.main()
