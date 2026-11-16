"""Focused API, mapping and worker lifecycle acceptance tests."""
import json
import os
import re
import threading
from unittest.mock import patch

import pytest
from dashboard import files
from dashboard.execution.adapters import aa, cg
from dashboard.execution.coordination import coordinator as backend
from dashboard.models import mappings
from dashboard.models.mappings import store as mapping_store
from dashboard.web import views

from tests.harness.support import automatic_mapping

JOB = {'id': '123456abcdef', 'detergent': 'DDM', 'method': 'fast_forward', 'status': 'running', 'stage': 'input'}


@pytest.fixture
def job(dashboard):
    """The run this test owns, inserted the way the queue inserts one."""
    record = dict(JOB, created=dashboard.coordinator.now())
    dashboard.coordinator.database().replace([record])
    return record


def test_readiness_blocks_unconnected_run_before_creation(dashboard, job):
    response = dashboard.client.get('/api/readiness').get_json()
    assert not response['ready']
    assert response['blockers']
    # A payload that names no run type is refused before a job exists: the historical combined job is retired.
    assert dashboard.client.post('/', json={'detergent': 'DDM', 'method': 'fast_forward'}).status_code == 400
    assert len(dashboard.coordinator.database().all()) == 1


def test_never_signal_an_unowned_stored_pid(dashboard, job):
    dashboard.coordinator.database().update(job['id'], pid=1)
    with patch.object(os, 'killpg') as signal:
        assert dashboard.client.post('/control/123456abcdef/cancel').status_code == 409
        signal.assert_not_called()
    assert not dashboard.client.get('/api/jobs').get_json()['jobs'][0]['can_cancel']


def test_console_cursor_download_and_unknown_run(dashboard, job):
    path = dashboard.coordinator.log_path(job); path.write_text('first\n')
    result = dashboard.client.get('/api/jobs/123456abcdef/log').get_json()
    assert result['text'] == 'first\n'
    with path.open('a') as fp: fp.write('<script>literal</script>\n')
    result = dashboard.client.get(f'/api/jobs/123456abcdef/log?offset={result["offset"]}').get_json()
    assert result['text'] == '<script>literal</script>\n'
    assert dashboard.client.get('/api/jobs/123456abcdef/log?offset=-1').status_code == 400
    assert dashboard.client.get('/api/jobs/ffffffffffff/log').status_code == 404
    response = dashboard.client.get('/api/jobs/123456abcdef/log?download=1')
    assert 'attachment' in response.headers['Content-Disposition']
    response.close()


def test_artifact_index_is_explicit(dashboard, job):
    run_dir = dashboard.coordinator.RUNS / job['id']; run_dir.mkdir(parents=True)
    (run_dir / 'manifest.json').write_text('{}')
    (run_dir / 'result.gro').write_text('coordinates')
    result = dashboard.client.get('/api/jobs/123456abcdef/artifacts').get_json()
    assert [item['path'] for item in result['artifacts']] == ['manifest.json', 'result.gro']
    assert dashboard.client.get('/api/jobs/123456abcdef/artifacts/../jobs.sqlite3').status_code == 404


def test_delete_removes_terminal_run_and_artifacts(dashboard, job):
    run_dir = dashboard.coordinator.RUNS / job['id']; run_dir.mkdir(parents=True)
    (run_dir / 'artifact.dat').write_text('data')
    log = dashboard.coordinator.log_path(job); log.write_text('console')
    dashboard.coordinator.database().update(job['id'], status='failed')
    response = dashboard.client.delete('/api/jobs/' + job['id'])
    assert response.status_code == 200
    assert dashboard.coordinator.database().all() == []
    assert not run_dir.exists(); assert not log.exists()


def test_delete_keeps_record_when_file_cleanup_fails(dashboard, job):
    run_dir = dashboard.coordinator.RUNS / job['id']; run_dir.mkdir(parents=True)
    dashboard.coordinator.database().update(job['id'], status='failed')
    with patch.object(backend.shutil, 'rmtree', side_effect=PermissionError('locked')):
        response = dashboard.client.delete('/api/jobs/' + job['id'])
    assert response.status_code == 409
    assert len(dashboard.coordinator.database().all()) == 1
    assert run_dir.exists()


def test_delete_rejects_active_owned_run(dashboard, job):
    worker = dashboard.coordinator.Worker(); dashboard.coordinator.WORKERS[job['id']] = worker
    try:
        response = dashboard.client.delete('/api/jobs/' + job['id'])
        assert response.status_code == 409
    finally:
        dashboard.coordinator.WORKERS.pop(job['id'], None)


def test_references_api_excludes_legacy_combined_runs(dashboard):
    response = dashboard.client.get('/api/references')
    assert response.status_code == 200
    assert response.get_json()['references'] == []


def test_legacy_defaults_api_preserves_tutorial_sources(dashboard):
    response = dashboard.client.get('/api/defaults?profile=draft-smoke')
    assert response.status_code == 200
    data = response.get_json()
    assert data['values']['aa_production_ps'] == 50
    assert 'mdps' in data['sources']['AA']


def test_cg_defaults_are_the_settings_the_run_will_use(dashboard):
    """The form and the run must not disagree, at any profile.

    Before this, a draft-smoke AA-to-CG form showed the full-length AA half while
    the run shortened only the CG half: the profile reached the CG settings and
    stopped, because the AA half had no profile at all.
    """
    for profile in aa.PROFILES:
        data = dashboard.client.get('/api/defaults?run_type=cg&profile=' + profile).get_json()
        settings = cg.normalize_settings(None, profile)
        for key in ('aa_nvt_ps', 'aa_npt_ps', 'aa_production_ps', 'cg_equil_ps', 'cg_production_ps'):
            assert data['values'][key] == settings[key], profile + ': ' + key

    # And a caller that names none -- which is every request the New run panel makes now -- gets the profile the
    # queue will stamp, not this route's own `standard`. Measured before the fix: `standard` answered
    # `cg_equil_ps` 5000 / `cg_production_ps` 100000 against the run's 10 / 10000, and the panel posts those
    # numbers back as explicit settings, so the run would have integrated 100 ns of CG production.
    data = dashboard.client.get('/api/defaults?run_type=cg').get_json()
    settings = cg.normalize_settings(None, cg.AA_CG_PROFILE)
    for key in ('aa_nvt_ps', 'aa_npt_ps', 'aa_production_ps', 'cg_equil_ps', 'cg_production_ps'):
        assert data['values'][key] == settings[key], 'no profile named: ' + key


def test_aa_only_defaults_shorten_with_the_smoke_profile(dashboard):
    data = dashboard.client.get('/api/defaults?run_type=aa_only&profile=draft-smoke').get_json()
    assert data['values']['aa_production_ps'] == 50
    assert data['values']['aa_nvt_ps'] + data['values']['aa_npt_ps'] == 10


def test_defaults_reject_an_unknown_profile(dashboard):
    assert dashboard.client.get('/api/defaults?profile=nonsense').status_code == 400
    assert dashboard.client.get('/api/defaults?run_type=aa_only&profile=nonsense').status_code == 400


def test_new_run_rejects_invalid_stage_setting(dashboard):
    with patch.object(cg, 'parameterization_readiness', return_value={'ready': True}):
        response = dashboard.client.post('/', json={'detergent': 'DDM', 'method': 'fast_forward', 'temperature_k': 100})
    assert response.status_code == 400


def test_run_page_contains_table_and_resource_controls(dashboard):
    response = dashboard.client.get('/')
    page = response.get_data(as_text=True)
    assert 'workflow-timeline' in page
    assert 'Molecule</th>' in page
    assert 'job-stage-settings' in page
    assert 'job-console' not in page
    assert 'Capture AA snapshots' not in page
    assert 'Select for comparison' not in page


def test_mapping_editor_exposes_only_the_compact_authoring_actions(dashboard):
    page = dashboard.client.get('/').get_data(as_text=True)
    assert 'Reference and building-block registry' not in page
    assert 'id="group-into-bead"' not in page
    assert 'id="clear-all-mapping"' in page
    assert 'id="generate-automatic"' in page
    assert 'id="save-mapping-editor"' in page
    assert 'Approve mapping' not in page
    assert 'Download diagram (SVG)' not in page
    assert 'Mapping exports' not in page


def test_eta_is_latest_and_not_shown_after_finish(dashboard, job):
    parse = views.parse_gromacs_eta
    assert parse('remaining wall clock time: 300 s\rremaining wall clock time: 22.5 s')['gromacs_remaining_seconds'] == 22.5
    assert parse('remaining wall clock time: 300 s\nwill finish Fri Sep 11 09:00:00 2026')['gromacs_eta'] == 'Fri Sep 11 09:00:00 2026'
    assert parse('remaining wall clock time: 300 s\nFinished mdrun') == {}
    dashboard.coordinator.database().update(job['id'], status='failed', gromacs_eta='stale')
    assert 'gromacs_eta' not in dashboard.client.get('/api/jobs').get_json()['jobs'][0]


def test_resumed_eta_does_not_fall_back_to_previous_attempt_log(dashboard, job):
    run = dashboard.coordinator.run_path({**job, 'layout_version': 2, 'run_type': 'aa_only', 'resume_in_place': True, 'resume_count': 1})
    dashboard.coordinator.database().update(job['id'], layout_version=2, run_type='aa_only', resume_in_place=True, resume_count=1)
    (run / 'stages/06_production').mkdir(parents=True)
    (run / 'logs').mkdir()
    (run / 'logs/console.log').write_text('starting mdrun\nwill finish OLD ATTEMPT\n')
    current_log = run / 'logs/resume-0001/06_production.log'
    files.atomic_json(run / 'manifest.json', {
        'run_type': 'aa_only',
        'stages': [{'name': 'AA NPT production', 'status': 'running', 'log': str(current_log)}],
    })

    response = dashboard.client.get('/api/jobs/' + job['id'])

    assert 'gromacs_eta' not in response.get_json()
    current_log.parent.mkdir(parents=True)
    current_log.write_text('starting mdrun\nwill finish CURRENT ATTEMPT\n')
    response = dashboard.client.get('/api/jobs/' + job['id'])
    assert response.get_json()['gromacs_eta'] == 'CURRENT ATTEMPT'


def test_retry_creates_new_id_and_preserves_failed_record(dashboard, job):
    """A retry carries the model the failed run consumed; a composition-kind run needs only its composition."""
    from dashboard.execution.adapters import composition

    dashboard.coordinator.database().update(
        job['id'], status='failed', error='Original failure', run_type='cg',
        parameterization={'kind': 'composition', 'composition_id': '0' * 16})
    before = dashboard.coordinator.lookup(job['id'])
    with patch.object(composition, 'readiness', return_value={'ready': True, 'checks': [], 'blockers': []}), \
            patch.object(threading.Thread, 'start'):
        response = dashboard.client.post('/retry/123456abcdef')
    assert response.status_code == 201
    assert response.get_json()['parameterization']['kind'] == 'composition'
    assert response.get_json()['id'] != job['id']
    assert dashboard.coordinator.lookup(job['id']) == before


def test_all_35_heavy_atoms_come_from_matching_coordinate_topology_order():
    structure = mappings.molecule()
    assert sum(a['heavy'] for a in structure['atoms']) == 35
    assert len(structure['atoms']) == 81


def test_reports_missing_duplicate_disconnected_and_size_findings():
    result = mappings.validate({'name': 'test', 'beads': [
        {'name': 'a', 'size': 'R', 'atoms': [1, 12]},
        {'name': 'b', 'size': 'S', 'atoms': [12, 36, 999]},
    ]})
    codes = {issue['code'] for issue in result['issues']}
    assert {'missing', 'duplicate', 'disconnected', 'size', 'hydrogen', 'unknown', 'mismatch'} <= codes
    assert not result['scientifically_validated']


def test_candidate_validation_exposes_nominal_size_mismatch():
    from tests.harness.support import physical_mapping
    candidate=physical_mapping()
    for bead in candidate['beads']:bead['size']='T'
    validation=mappings.validate(candidate)
    assert validation['mismatch']==2*len(candidate['beads'])-35
    assert not validation['checks_passed']


def test_draft_save_does_not_overwrite_source_and_stays_unvalidated(dashboard, tmp_path):
    with patch.object(mapping_store, 'storage_root', return_value=tmp_path):
        original=mappings.save_draft(automatic_mapping(mappings.molecule(), 'DDM'))
        source=tmp_path/original['file'];before=source.read_bytes()
        draft = json.loads(before); draft['file'] = source.name; draft['status'] = 'approved'
        # One bead's label moves, so this is a *different* assignment: a save that repeats one verbatim is refused
        # as a duplicate (`test_a_second_save_of_the_same_assignment_is_refused_naming_the_first`).
        draft['beads'][0]['label'] = 'd' if draft['beads'][0].get('label') != 'd' else 'a'
        saved = mappings.save_draft(draft)
        assert saved['file'] != source.name
        assert saved['status'] == 'candidate-unvalidated'
        assert source.read_bytes() == before
    with dashboard.client as client:
        assert client.get('/api/mappings/identity.json').status_code == 404
        assert client.post('/api/mappings/validate', json={'name': 'bad', 'beads': [{'name': 'b', 'size': 'R', 'atoms': [1.5]}]}).status_code == 400


def test_defaults_return_one_help_map_quoted_from_the_manual(dashboard):
    """The form renders help from the server, not from the template: one map, one source, every run type.

    A second copy in `dashboard.html` would drift the moment a value or a flag moved, so the template carries no
    sentence -- and the map is returned with the same answer that fills the fields.
    """
    from dashboard.execution import settings_help

    data = dashboard.client.get('/api/defaults?run_type=cg').get_json()
    assert data['help'] == settings_help.HELP
    assert data['help_sources']['mdp'] == 'https://manual.gromacs.org/2026-rc/user-guide/mdp-options.html'
    for key in ('nstlog', 'nstenergy', 'nstxtcout', 'xtc_precision', 'nstcomm', 'nstlist',
                'verlet_buffer_tolerance', 'rlist', 'rcoulomb', 'rvdw', 'tau_t', 'tau_p', 'compressibility',
                'mdrun_pmefft', 'mdrun_update', 'mdrun_tunepme'):
        assert data['help'].get(key), key
    # A composition-kind CG run writes no engine MDP, so it neither offers nor defaults the CG production
    # overrides; the revision kind, which is the one this route answers, does.


def test_new_run_form_groups_the_options_and_exposes_box_shape(dashboard):
    """The markup the lane owns: visible sampling/ensemble/seeds, one folded Other run options, and the controls the
    specs already advertised (`box_shape`, `cg_seed`, `constraints`) actually rendered."""
    from dashboard.execution.adapters import aa, aa_box

    page = dashboard.client.get('/').get_data(as_text=True)
    for name in ('aa_nvt_ps', 'cg_seed', 'box_shape', 'constraints', 'nstlog', 'nstenergy', 'nstxtcout',
                 'xtc_precision', 'nstcomm', 'nstlist', 'verlet_buffer_tolerance', 'rlist', 'rcoulomb',
                 'rvdw', 'tau_t', 'tau_p', 'compressibility', 'mdrun_pmefft', 'mdrun_update',
                 'mdrun_tunepme'):
        assert f'name="{name}"' in page, name
    assert 'id="new-advanced"' in page and 'Other run options' in page
    assert '>Sampling<' in page and '>Ensemble and box<' in page and '>Seeds<' in page
    assert '>Constraints<' in page
    # The constraint control offers the adapter's own choice vocabulary, not a second list that could drift. The
    # markup puts the protocol default first (it is the option a select shows when nothing has chosen), so the
    # lists are compared as sets, not in the spec's own order.
    offered = re.search(r'<select name="constraints">(.*?)</select>', page, re.S).group(1)
    assert set(re.findall(r'value="([^"]+)"', offered)) == set(aa.CHOICE_SPECS['constraints'][1])
    # The box shape's offered values are the adapter's own shapes, not a second list that could drift.
    select = re.search(r'<select name="box_shape">(.*?)</select>', page, re.S).group(1)
    assert re.findall(r'value="([^"]+)"', select) == list(aa_box.SHAPES)
