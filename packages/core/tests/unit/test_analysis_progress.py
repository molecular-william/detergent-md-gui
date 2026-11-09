"""The analysis progress seam: a producer reports a phase, and the worker exposes the file to it and clears up."""
import json
import os

import pytest
from dashboard.analysis import progress, worker
from dashboard.analysis.kinds import Kind


def test_report_writes_the_phase_when_the_worker_named_a_file(tmp_path, monkeypatch):
    path = tmp_path / 'progress.json'
    monkeypatch.setenv(progress.ENV, str(path))

    progress.report('Surfaces: extracting AA')

    assert json.loads(path.read_text()) == {'phase': 'Surfaces: extracting AA'}


def test_report_is_a_silent_no_op_without_the_variable(tmp_path, monkeypatch):
    monkeypatch.delenv(progress.ENV, raising=False)
    monkeypatch.setattr(progress.files, 'atomic_json',
                        lambda *args, **kwargs: pytest.fail('reported a phase nobody asked for'))

    assert progress.report('Surfaces: extracting AA') is None


def test_worker_exposes_the_attempt_progress_file_to_the_producer_and_restores_it(tmp_path, monkeypatch):
    run = tmp_path / 'run'
    (run / 'stages').mkdir(parents=True)
    seen = {}

    def produce(work, payload):
        seen['path'] = os.environ.get(progress.ENV)
        progress.report('fake phase')
        return {'ok': True}

    monkeypatch.setitem(worker.TABLE, 'progress-fixture',
                        Kind('progress-fixture', (), produce, 'Progress fixture', 'a phase', 'unit'))
    monkeypatch.setenv(progress.ENV, 'before-worker')
    request = run / 'analyses' / 'progress-fixture' / 'request.json'
    request.parent.mkdir(parents=True)
    request.write_text(json.dumps({'run': str(run), 'kind': 'progress-fixture', 'payload': {}}))

    worker.execute(request)

    attempt = request.parent
    assert seen['path'] == str(attempt / 'progress.json')
    assert os.environ[progress.ENV] == 'before-worker', 'execute must restore the variable, not leak its own value'


def test_worker_leaves_the_variable_unset_when_it_started_unset(tmp_path, monkeypatch):
    run = tmp_path / 'run'
    (run / 'stages').mkdir(parents=True)

    def produce(work, payload):
        assert os.environ.get(progress.ENV), 'the producer must see the attempt progress file'
        return {'ok': True}

    monkeypatch.setitem(worker.TABLE, 'progress-fixture',
                        Kind('progress-fixture', (), produce, 'Progress fixture', 'a phase', 'unit'))
    monkeypatch.delenv(progress.ENV, raising=False)
    request = run / 'analyses' / 'progress-fixture' / 'request.json'
    request.parent.mkdir(parents=True)
    request.write_text(json.dumps({'run': str(run), 'kind': 'progress-fixture', 'payload': {}}))

    worker.execute(request)

    assert progress.ENV not in os.environ
