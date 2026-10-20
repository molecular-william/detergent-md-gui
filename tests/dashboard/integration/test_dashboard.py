import os

from dashboard.execution.coordination import coordinator as backend

"""Focused API, mapping and worker lifecycle acceptance tests."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

from dashboard import files
from dashboard.execution.adapters import aa, cg
from dashboard.models import mappings
from dashboard.models.mappings import store as mapping_store


class DashboardTests(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def _application(self, dashboard):
        """The application this test owns; its coordinator is the object the test inspects."""
        self.dashboard = dashboard

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'dashboard').mkdir()
        for name, value in [('ROOT', self.root), ('DATA', self.root / 'dashboard/jobs.sqlite3'), ('RUNS', self.root / 'dashboard/runs')]:
            mock = patch.object(self.dashboard.coordinator, name, value); mock.start(); self.addCleanup(mock.stop)
        self.client = self.dashboard.client
        self.job = {'id': '123456abcdef', 'detergent': 'DDM', 'method': 'fast_forward', 'status': 'running', 'stage': 'input', 'created': self.dashboard.coordinator.now()}
        self.dashboard.coordinator.database().replace([self.job])

    def test_readiness_blocks_unconnected_run_before_creation(self):
        response = self.client.get('/api/readiness').get_json()
        self.assertFalse(response['ready'])
        self.assertTrue(response['blockers'])
        self.assertEqual(self.client.post('/', json={'detergent': 'DDM', 'method': 'fast_forward'}).status_code, 409)
        self.assertEqual(len(self.dashboard.coordinator.database().all()), 1)

    def test_never_signal_an_unowned_stored_pid(self):
        self.dashboard.coordinator.database().update(self.job['id'], pid=1)
        with patch.object(os, 'killpg') as signal:
            self.assertEqual(self.client.post('/control/123456abcdef/cancel').status_code, 409)
            signal.assert_not_called()
        self.assertFalse(self.client.get('/api/jobs').get_json()['jobs'][0]['can_cancel'])

    def test_console_cursor_download_and_unknown_run(self):
        path = self.dashboard.coordinator.log_path(self.job); path.write_text('first\n')
        result = self.client.get('/api/jobs/123456abcdef/log').get_json()
        self.assertEqual(result['text'], 'first\n')
        with path.open('a') as fp: fp.write('<script>literal</script>\n')
        result = self.client.get(f'/api/jobs/123456abcdef/log?offset={result["offset"]}').get_json()
        self.assertEqual(result['text'], '<script>literal</script>\n')
        self.assertEqual(self.client.get('/api/jobs/123456abcdef/log?offset=-1').status_code, 400)
        self.assertEqual(self.client.get('/api/jobs/ffffffffffff/log').status_code, 404)
        response = self.client.get('/api/jobs/123456abcdef/log?download=1')
        self.assertIn('attachment', response.headers['Content-Disposition'])
        response.close()

    def test_artifact_index_and_snapshot_preflight_are_explicit(self):
        run_dir = self.dashboard.coordinator.RUNS / self.job['id']; run_dir.mkdir(parents=True)
        (run_dir / 'manifest.json').write_text('{}')
        (run_dir / 'result.gro').write_text('coordinates')
        result = self.client.get('/api/jobs/123456abcdef/artifacts').get_json()
        self.assertEqual([item['path'] for item in result['artifacts']], ['manifest.json', 'result.gro'])
        self.assertEqual(self.client.get('/api/jobs/123456abcdef/artifacts/../jobs.sqlite3').status_code, 404)
        snapshot = self.client.post('/api/jobs/123456abcdef/snapshots', json={'stage': '1_AA-reference'})
        self.assertEqual(snapshot.status_code, 409)
        self.assertIn('stopped run', snapshot.get_json()['error'])

    def test_delete_removes_terminal_run_and_artifacts(self):
        run_dir = self.dashboard.coordinator.RUNS / self.job['id']; run_dir.mkdir(parents=True)
        (run_dir / 'artifact.dat').write_text('data')
        log = self.dashboard.coordinator.log_path(self.job); log.write_text('console')
        self.dashboard.coordinator.database().update(self.job['id'], status='failed')
        response = self.client.delete('/api/jobs/' + self.job['id'])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.dashboard.coordinator.database().all(), [])
        self.assertFalse(run_dir.exists()); self.assertFalse(log.exists())

    def test_delete_keeps_record_when_file_cleanup_fails(self):
        run_dir = self.dashboard.coordinator.RUNS / self.job['id']; run_dir.mkdir(parents=True)
        self.dashboard.coordinator.database().update(self.job['id'], status='failed')
        with patch.object(backend.shutil, 'rmtree', side_effect=PermissionError('locked')):
            response = self.client.delete('/api/jobs/' + self.job['id'])
        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(self.dashboard.coordinator.database().all()), 1)
        self.assertTrue(run_dir.exists())

    def test_delete_rejects_active_owned_run(self):
        worker = self.dashboard.coordinator.Worker(); self.dashboard.coordinator.WORKERS[self.job['id']] = worker
        try:
            response = self.client.delete('/api/jobs/' + self.job['id'])
            self.assertEqual(response.status_code, 409)
        finally:
            self.dashboard.coordinator.WORKERS.pop(self.job['id'], None)

    def test_references_api_excludes_legacy_combined_runs(self):
        response = self.client.get('/api/references')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['references'], [])

    def test_legacy_defaults_api_preserves_tutorial_sources(self):
        response = self.client.get('/api/defaults?profile=draft-smoke')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data['values']['aa_production_ps'], 50)
        self.assertIn('mdps', data['sources']['AA'])

    def test_aa_cg_defaults_are_the_settings_the_run_will_use(self):
        """The form and the run must not disagree, at any profile.

        Before this, a draft-smoke AA-to-CG form showed the full-length AA half while
        the run shortened only the CG half: the profile reached the CG settings and
        stopped, because the AA half had no profile at all.
        """
        for profile in aa.PROFILES:
            data = self.client.get('/api/defaults?run_type=aa_cg&profile=' + profile).get_json()
            settings = cg.normalize_settings(None, profile)
            for key in ('aa_nvt_ps', 'aa_npt_ps', 'aa_production_ps', 'cg_equil_ps', 'cg_production_ps'):
                self.assertEqual(data['values'][key], settings[key], profile + ': ' + key)

        # And a caller that names none -- which is every request the New run panel makes now -- gets the profile the
        # queue will stamp, not this route's own `standard`. Measured before the fix: `standard` answered
        # `cg_equil_ps` 5000 / `cg_production_ps` 100000 against the run's 10 / 10000, and the panel posts those
        # numbers back as explicit settings, so the run would have integrated 100 ns of CG production.
        data = self.client.get('/api/defaults?run_type=aa_cg').get_json()
        settings = cg.normalize_settings(None, cg.AA_CG_PROFILE)
        for key in ('aa_nvt_ps', 'aa_npt_ps', 'aa_production_ps', 'cg_equil_ps', 'cg_production_ps'):
            self.assertEqual(data['values'][key], settings[key], 'no profile named: ' + key)

    def test_aa_only_defaults_shorten_with_the_smoke_profile(self):
        data = self.client.get('/api/defaults?run_type=aa_only&profile=draft-smoke').get_json()
        self.assertEqual(data['values']['aa_production_ps'], 50)
        self.assertEqual(data['values']['aa_nvt_ps'] + data['values']['aa_npt_ps'], 10)

    def test_defaults_reject_an_unknown_profile(self):
        self.assertEqual(self.client.get('/api/defaults?profile=nonsense').status_code, 400)
        self.assertEqual(self.client.get('/api/defaults?run_type=aa_only&profile=nonsense').status_code, 400)

    def test_new_run_rejects_invalid_stage_setting(self):
        with patch.object(cg, 'readiness', return_value={'ready': True}):
            response = self.client.post('/', json={'detergent': 'DDM', 'method': 'fast_forward', 'temperature_k': 100})
        self.assertEqual(response.status_code, 400)

    def test_run_page_contains_table_and_resource_controls(self):
        response = self.client.get('/')
        page = response.get_data(as_text=True)
        self.assertIn('workflow-timeline', page)
        self.assertIn('Molecule</th>', page)
        self.assertIn('job-console', page)
        self.assertNotIn('Capture AA snapshots', page)
        self.assertNotIn('Select for comparison', page)

    def test_mapping_editor_exposes_only_the_compact_authoring_actions(self):
        page = self.client.get('/').get_data(as_text=True)
        self.assertNotIn('Reference and building-block registry', page)
        self.assertIn('id="group-into-bead"', page)
        self.assertIn('id="clear-all-mapping"', page)
        self.assertIn('id="generate-automatic"', page)
        self.assertIn('id="save-mapping-editor"', page)
        self.assertNotIn('Approve mapping', page)
        self.assertNotIn('Download diagram (SVG)', page)
        self.assertNotIn('Mapping exports', page)

    def test_eta_is_latest_and_not_shown_after_finish(self):
        parse = self.dashboard.coordinator.parse_gromacs_eta
        self.assertEqual(parse('remaining wall clock time: 300 s\rremaining wall clock time: 22.5 s')['gromacs_remaining_seconds'], 22.5)
        self.assertEqual(parse('remaining wall clock time: 300 s\nwill finish Fri Sep 11 09:00:00 2026')['gromacs_eta'], 'Fri Sep 11 09:00:00 2026')
        self.assertEqual(parse('remaining wall clock time: 300 s\nFinished mdrun'), {})
        self.dashboard.coordinator.database().update(self.job['id'], status='failed', gromacs_eta='stale')
        self.assertNotIn('gromacs_eta', self.client.get('/api/jobs').get_json()['jobs'][0])

    def test_resumed_eta_does_not_fall_back_to_previous_attempt_log(self):
        job = dict(self.job, layout_version=2, run_type='aa_only', resume_in_place=True, resume_count=1)
        self.dashboard.coordinator.database().update(job['id'], layout_version=2, run_type='aa_only', resume_in_place=True, resume_count=1)
        run = self.dashboard.coordinator.run_path(job)
        (run / 'stages/06_production').mkdir(parents=True)
        (run / 'logs').mkdir()
        (run / 'logs/console.log').write_text('starting mdrun\nwill finish OLD ATTEMPT\n')
        current_log = run / 'logs/resume-0001/06_production.log'
        files.atomic_json(run / 'manifest.json', {
            'run_type': 'aa_only',
            'stages': [{'name': 'AA NPT production', 'status': 'running', 'log': str(current_log)}],
        })

        response = self.client.get('/api/jobs/' + job['id'])

        self.assertNotIn('gromacs_eta', response.get_json())
        current_log.parent.mkdir(parents=True)
        current_log.write_text('starting mdrun\nwill finish CURRENT ATTEMPT\n')
        response = self.client.get('/api/jobs/' + job['id'])
        self.assertEqual(response.get_json()['gromacs_eta'], 'CURRENT ATTEMPT')

    def test_retry_creates_new_id_and_preserves_failed_record(self):
        self.dashboard.coordinator.database().update(self.job['id'], status='failed', error='Original failure')
        before = self.dashboard.coordinator.lookup(self.job['id'])
        with patch.object(cg, 'readiness', return_value={'ready': True}), patch.object(threading.Thread, 'start'):
            response = self.client.post('/retry/123456abcdef')
        self.assertEqual(response.status_code, 201)
        self.assertNotEqual(response.get_json()['id'], self.job['id'])
        self.assertEqual(self.dashboard.coordinator.lookup(self.job['id']), before)


class MappingTests(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def _application(self, dashboard):
        """The application this test owns; the mapping routes are driven through its client."""
        self.dashboard = dashboard

    def test_all_35_heavy_atoms_come_from_matching_coordinate_topology_order(self):
        structure = mappings.molecule()
        self.assertEqual(sum(a['heavy'] for a in structure['atoms']), 35)
        self.assertEqual(len(structure['atoms']), 81)

    def test_reports_missing_duplicate_disconnected_and_size_findings(self):
        result = mappings.validate({'name': 'test', 'beads': [
            {'name': 'a', 'size': 'R', 'atoms': [1, 12]},
            {'name': 'b', 'size': 'S', 'atoms': [12, 36, 999]},
        ]})
        codes = {issue['code'] for issue in result['issues']}
        self.assertTrue({'missing', 'duplicate', 'disconnected', 'size', 'hydrogen', 'unknown', 'mismatch'} <= codes)
        self.assertFalse(result['scientifically_validated'])

    def test_candidate_validation_exposes_nominal_size_mismatch(self):
        from tests.dashboard.support import physical_mapping
        candidate=physical_mapping()
        for bead in candidate['beads']:bead['size']='T'
        validation=mappings.validate(candidate)
        self.assertEqual(validation['mismatch'],2*len(candidate['beads'])-35)
        self.assertFalse(validation['checks_passed'])

    def test_draft_save_does_not_overwrite_source_and_stays_unvalidated(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(mapping_store, 'storage_root', return_value=Path(temp)):
            original=mappings.save_draft(mappings.automatic_candidate(mappings.molecule(), 'DDM'))
            source=Path(temp)/original['file'];before=source.read_bytes()
            draft = json.loads(before); draft['file'] = source.name; draft['status'] = 'approved'
            saved = mappings.save_draft(draft)
            self.assertNotEqual(saved['file'], source.name)
            self.assertEqual(saved['status'], 'candidate-unvalidated')
            self.assertEqual(source.read_bytes(), before)
        with self.dashboard.client as client:
            self.assertEqual(client.get('/api/mappings/identity.json').status_code, 404)
            self.assertEqual(client.post('/api/mappings/validate', json={'name': 'bad', 'beads': [{'name': 'b', 'size': 'R', 'atoms': [1.5]}]}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
