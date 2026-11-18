"""How an analysis attempt stages its sources: links, never a second copy, and a guard that still holds.

An attempt is handed a temporary work directory. Every source is staged there as a **symbolic link** to the file
the run already holds -- for a source outside the run, to the run's one durable `sources/` copy -- so a 465 MB
trajectory is not written into a temp tree, twice-hashed and deleted on every attempt. The producer must publish
new files and never edit the inputs it was handed, so the worker snapshots their `(size, mtime, mode)` before and
re-stats after: a write through a link moves the target's stat and is refused with the same message the two full
SHA-256 passes used to produce. `files.safe_files` skips links, so what an attempt publishes is unchanged.

The producer used for the guard is a deliberately writing one; the run it writes into is a fixture, as everywhere
else. The outside source is `ff-interactions`' parameterization store, which is the real kind that stages one.
"""
import json
import os
import stat
import subprocess
import sys

import pytest
from dashboard import features
from dashboard.analysis import worker
from dashboard.analysis.kinds import Kind

#: The stable name of the outside source, and the run-relative name the worker records for its one copy.
SHARED = 'shared/parameterizations/records/ddm.revisions/1/B01_B02_bonds_distr.dat'
EXTERNAL = 'sources/' + SHARED


@pytest.fixture(autouse=True)
def _installed_features():
    """`ff-interactions` is the validation feature's kind, so the table is complete before the worker reads it."""
    features.ensure()


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _distribution(rows=('0.0 0.2', '0.5 0.8')):
    return '\n'.join(rows) + '\n'


def _run(tmp_path):
    """An AA-CG run that consumed a revision recording one bond histogram, which lives outside the run."""
    workspace = tmp_path/'workspace'
    run = workspace/'runs'/'bbbbbbbbbbbb'
    store = workspace/'parameterizations'/'records'/'ddm.revisions'/'1'/'B01_B02_bonds_distr.dat'
    _write(store, _distribution())
    _write(run/'stages'/'5_assessment'/'B01_B02_bonds_distr.dat', _distribution(('0.0 0.3', '0.5 0.7')))
    _write(run/'stages'/'5_assessment'/'report_interactions.out',
           'bonds\nB01_B02 : 0.12 (0.88)\nOverall Score : 0.12 ± 0.01\n')
    _write(run/'stages'/'2_mapping'/'model.json',
           json.dumps({'beads': [{'export_name': 'B01'}, {'export_name': 'B02'}]}))
    _write(run/'stages'/'3_initial_CG'/'parameterization_used.json', json.dumps({
        'fitted': False, 'revision': 1, 'engine': 'fast-forward',
        'reference_distributions': [{'name': str(store), 'sha256': 'x'}]}))
    _write(run/'manifest.json', json.dumps({'run_type': 'aa_cg', 'status': 'completed', 'stages': []}))
    return run, store


def _execute(run, kind='ff-interactions', attempt='0001-20261001', payload=None):
    """One worker attempt, through the same entry point the coordinator starts."""
    request = run/'analyses'/kind/attempt/'request.json'
    request.parent.mkdir(parents=True, exist_ok=True)
    request.write_text(json.dumps({'run': str(run), 'kind': kind, 'payload': payload or {}}))
    worker.execute(request)
    return request.parent


def _staging_run(tmp_path):
    """A run whose only source is one file, so the staged link can be inspected from inside the producer."""
    run = tmp_path/'run'
    _write(run/'stages'/'2_mapping'/'model.json', '{"beads": []}\n')
    _write(run/'manifest.json', json.dumps({'run_type': 'aa_cg', 'status': 'completed', 'stages': []}))
    return run


def _register(monkeypatch, produce):
    monkeypatch.setitem(worker.TABLE, 'staging-fixture',
                        Kind('staging-fixture', ('2_mapping/model.json',), produce,
                             'Staging fixture', 'the worker staging shape', 'unit'))


def test_a_staged_source_is_a_link_and_a_produced_output_is_not(tmp_path, monkeypatch):
    """(a) The work directory holds links, and what the producer wrote stays an ordinary file to publish."""
    run = _staging_run(tmp_path)
    seen = {}

    def produce(work, payload):
        staged = work/'2_mapping'/'model.json'
        seen['is_link'] = stat.S_ISLNK(os.lstat(staged).st_mode)
        seen['target'] = os.readlink(staged)
        (work/'produced.json').write_text('{}\n')
        return {'ok': True}

    _register(monkeypatch, produce)
    attempt = _execute(run, 'staging-fixture')

    assert seen['is_link'] is True, 'the attempt copied its source instead of linking it'
    assert os.path.realpath(seen['target']) == os.path.realpath(run/'stages'/'2_mapping'/'model.json')
    produced = list((attempt/'output').rglob('produced.json'))
    assert len(produced) == 1, produced
    assert not stat.S_ISLNK(os.lstat(produced[0]).st_mode), 'a published output was a link'
    assert (run/'stages'/'2_mapping'/'model.json').read_text() == '{"beads": []}\n'


def test_the_stat_guard_refuses_a_producer_that_writes_to_a_staged_source(tmp_path, monkeypatch):
    """(b) A write through the link lands in the run's file; the moved stat is caught and named."""
    run = _staging_run(tmp_path)
    source = run/'stages'/'2_mapping'/'model.json'
    before = source.stat().st_size

    def produce(work, payload):
        with (work/'2_mapping'/'model.json').open('ab') as stream:
            stream.write(b'!')
        (work/'produced.json').write_text('{}\n')
        return {'ok': True}

    _register(monkeypatch, produce)

    with pytest.raises(ValueError, match='Analysis modified its source copy: 2_mapping/model.json'):
        _execute(run, 'staging-fixture')

    assert source.stat().st_size == before + 1, 'the staged link did not point at the run file'


def test_a_touched_copy_is_not_an_edit_because_the_digest_decides(tmp_path, monkeypatch):
    """A real copy whose stat moved but bytes did not is not a modification; it is also not an output."""
    run = _staging_run(tmp_path)

    def produce(work, payload):
        os.utime(work/'manifest.json', (0, 0))
        (work/'produced.json').write_text('{}\n')
        return {'ok': True}

    _register(monkeypatch, produce)
    attempt = _execute(run, 'staging-fixture')

    assert (attempt/'output'/'produced.json').is_file()
    assert not list((attempt/'output').rglob('manifest.json')), 'the staged copy was published as an output'


def test_a_second_attempt_stages_the_same_set_and_adds_no_durable_copy(tmp_path):
    """(c) The run keeps one real copy of an outside source; a second attempt links to it and writes nothing."""
    run, store = _run(tmp_path)
    first = _execute(run)
    copy = run/'sources'/SHARED
    stamp, content = copy.stat().st_ino, copy.read_bytes()

    second = _execute(run, attempt='0002-20261002')

    assert json.loads((second/'sources.json').read_text()) == json.loads((first/'sources.json').read_text())
    assert [path for path in (run/'sources').rglob('*') if path.is_file()] == [copy]
    assert copy.stat().st_ino == stamp, 'the second attempt replaced the run copy instead of reusing it'
    assert copy.read_bytes() == content == store.read_bytes()


def test_the_durable_copy_of_an_outside_source_is_a_real_file(tmp_path):
    """(d) The link target inside the run is a file, not a second link: the run directory must travel alone."""
    run, store = _run(tmp_path)
    target = run/EXTERNAL

    worker._stage_source_copy(run, store, EXTERNAL)

    assert target.is_file() and not target.is_symlink()
    assert target.read_bytes() == store.read_bytes()
    stamp = target.stat().st_ino
    worker._stage_source_copy(run, store, EXTERNAL)
    assert target.stat().st_ino == stamp, 'an unchanged source was copied again'


def test_the_attempt_launches_the_application_interpreter_and_records_it(dashboard):
    """(3) The subprocess is `sys.executable`, not a `python` resolved from the stage PATH, and the record names it."""
    coordinator = dashboard.coordinator
    jid, aid = 'aa11bb22cc99', '000000000001'
    task = {'id': aid, 'kind': 'bonded-cross-check', 'payload': {}, 'status': 'queued',
            'directory': f'analysis/{aid}'}
    coordinator.database().replace([{'id': jid, 'label': 'Interpreter run', 'detergent': 'DDM',
                                     'method': 'fast_forward', 'status': 'completed', 'stage': 'complete',
                                     'created': coordinator.now(), 'analyses': [task]}])
    (coordinator.RUNS/jid).mkdir(parents=True)
    seen = {}

    class Recorder:
        run_dir = None
        lease_file = None
        limit_error = None

        def execute(self, command, **kwargs):
            seen['command'] = list(command)
            raise subprocess.CalledProcessError(3, command)

    coordinator.analysis_coordinator.run(jid, aid, Recorder())

    recorded = next(item for item in coordinator.lookup(jid)['analyses'] if item['id'] == aid)
    request = coordinator.run_path({'id': jid})/task['directory']/'request.json'
    assert seen['command'] == [sys.executable, '-m', 'dashboard.analysis', str(request)]
    assert recorded['command'] == seen['command']
    assert recorded['interpreter'] == sys.executable
