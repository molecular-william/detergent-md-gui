"""Application construction and requests never share writable research state."""
from dashboard import files
from dashboard.app import create_app
from dashboard.models import mappings
from dashboard.paths import Paths
from tests.dashboard.support import physical_mapping


def test_two_applications_isolate_jobs_models_and_workers(tmp_path):
    apps = [create_app(Paths(workspace=tmp_path/name), {'TESTING': True, 'DISABLE_COORDINATOR': True})
            for name in ('first', 'second')]
    first, second = [app.extensions['dashboard_coordinator'] for app in apps]
    first.database().insert({'id': '123456abcdef', 'status': 'completed', 'detergent': 'DDM'})
    first.WORKERS['123456abcdef'] = first.Worker()
    with apps[0].app_context():
        mapping = mappings.save_draft(physical_mapping())
        mappings.save_draft({**physical_mapping(), 'name': 'Only first workspace'})
    clients = [app.test_client() for app in apps]
    assert len(clients[0].get('/api/jobs').json['jobs']) == 1
    assert clients[1].get('/api/jobs').json['jobs'] == []
    assert second.WORKERS == {} and second.ANALYSIS_WORKERS == {}
    assert len(clients[0].get('/api/mappings').json['candidates']) == 2
    assert clients[1].get('/api/mappings').json['candidates'] == []
    assert clients[0].get('/api/mappings/'+mapping['file']).status_code == 200
    assert clients[1].get('/api/mappings/'+mapping['file']).status_code == 404
    result = clients[0].post('/api/model-fragments', json={'name': 'First only'})
    assert result.status_code == 201
    assert clients[1].get('/api/model-fragments').json == {'fragments': []}
    with apps[0].app_context():
        assert sorted(m['name'] for m in mappings.list_candidates()) == ['Only first workspace', mapping.get('name')]


def test_relocated_console_reads_stage_log_without_rewriting_manifest(tmp_path):
    app = create_app(Paths(workspace=tmp_path/'relocated'), {'TESTING': True, 'DISABLE_COORDINATOR': True})
    owner = app.extensions['dashboard_coordinator']
    job = {'id': '123456abcdef', 'status': 'completed', 'layout_version': 2}
    owner.database().insert(job)
    run = owner.run_path(job)
    (run/'logs').mkdir(parents=True)
    (run/'logs/console.log').write_text('aggregate console')
    (run/'logs/production.log').write_text('final stage output')
    old_log = '/old/workspace/runs/123456abcdef/logs/production.log'
    files.atomic_json(run/'manifest.json', {'stages': [{'log': old_log}]})
    original = (run/'manifest.json').read_bytes()
    response = app.test_client().get('/api/jobs/123456abcdef/log')
    assert response.json['text'] == 'final stage output'
    assert (run/'manifest.json').read_bytes() == original
    assert owner.stage_log_path(job, '/old/runs/abcdef123456/logs/production.log') is None
    assert owner.stage_log_path(job, '../../outside.log') is None
