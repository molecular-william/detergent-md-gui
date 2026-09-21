import json
import pytest
from dashboard.cli import screen_candidates as screen


def test_resume_reuses_accepted_job_and_stops_on_failure(tmp_path, monkeypatch):
    path=tmp_path/'plan.json'
    path.write_text(json.dumps({'runs':[{'request':{'label':'first'}},{'request':{'label':'second'}},{'request':{'label':'third'}}]}))
    submissions=[]
    def api(route,payload=None):
        if route=='/api/jobs': return [{'id':'existing','label':'first'}]
        if route=='/api/jobs/existing': return {'status':'completed'}
        if route=='/': submissions.append(payload);return {'id':'new'}
        if route=='/api/jobs/new': return {'status':'failed','error':'test failure'}
        raise AssertionError(route)
    monkeypatch.setattr(screen,'api',api)
    with pytest.raises(RuntimeError,match='test failure'): screen.run(path)
    state=json.loads(path.read_text())
    assert state['status']=='stopped'
    assert submissions==[{'label':'second'}]
    assert [r.get('id') for r in state['runs']]==['existing','new',None]


def test_resume_completed_plan_does_not_submit_again(tmp_path, monkeypatch):
    path=tmp_path/'plan.json';path.write_text(json.dumps({'runs':[{'id':'existing','request':{'label':'first'}}]}))
    def api(route,payload=None):
        assert route=='/api/jobs/existing' and payload is None
        return {'status':'completed'}
    monkeypatch.setattr(screen,'api',api)
    screen.run(path)
    assert json.loads(path.read_text())['status']=='completed'
