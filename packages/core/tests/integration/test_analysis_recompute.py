"""The Analysis graphs panel can ask a finished run for the analyses it owes, and gets the rest afterwards.

Two things this pins, and the second is the defect the first was hiding:

* **One kind at a time.** `queue` takes one analysis per run and refuses a second with `RunBusy` while the first holds
  the worker, which is what keeps a person's cancel meaningful. Asking for the whole owed list at once therefore
  started exactly one kind and dropped the others on the floor: run `ce1318485197`, a `cg` run owing
  `bonded-cross-check` and `dihedral-fit`, never reached the second, with no record that it had ever been considered.
* **The rest follow.** What the drain cannot start is named in `owed`, and the next kind starts when one settles --
  which is what makes the button a request rather than a race with whoever is already analysing something.

The analyses themselves are not run: a worker standing in for the subprocess is what makes these fast, and what the
producer does about its sources is pinned where the producer lives.
"""
import json
import re
import time
from pathlib import Path

from tests.harness import support

JID = '123456abcdef'
SOURCES = ('2_mapping/mapped.gro', '2_mapping/mapped.xtc', '2_mapping/model.json',
           '3_initial_CG/SUCR_ff_inter.itp', '3_initial_CG/SUCR_initial.itp')


def seed(dashboard, *, run_type='cg'):
    """A finished AA-to-CG run with the sources its two own kinds are resolved from."""
    coordinator = dashboard.coordinator
    job = {'id': JID, 'label': 'Recompute', 'detergent': 'DDM', 'method': 'fast_forward', 'profile': 'draft-smoke',
           'status': 'completed', 'stage': 'complete', 'run_type': run_type, 'created': coordinator.now(),
           'analyses': []}
    coordinator.database().replace([job])
    run = coordinator.RUNS / JID
    run.mkdir(parents=True, exist_ok=True)
    support.cg_fixture_run(run, [[0., 0., 0.], [.4, 0., 0.], [0., .4, 0.], [0., 0., .4]], frames=3)
    for relative in SOURCES:
        source = run / 'stages' / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text('Where a kind is resolved from, not what it reads: the queue hashes these.\n')
    return coordinator, run


def kinds(coordinator):
    return [task['kind'] for task in coordinator.lookup(JID).get('analyses', [])]


def wait_for_a_task(coordinator, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if kinds(coordinator):
            return coordinator.lookup(JID)['analyses']
        time.sleep(.02)
    return coordinator.lookup(JID).get('analyses', [])


def settle(coordinator, task, status='completed'):
    """One attempt finishing: the record is written and the worker is let go, which is what `finish` does."""
    coordinator.analysis_coordinator.update(JID, task['id'], status=status)
    with coordinator.JOBS_LOCK:
        coordinator.ANALYSIS_WORKERS.pop((JID, task['id']), None)


def test_draining_starts_one_kind_and_names_the_ones_waiting(dashboard, monkeypatch):
    coordinator, _ = seed(dashboard)
    monkeypatch.setattr(coordinator.analysis_coordinator, 'run', lambda *args: None)

    answer = coordinator.analysis_coordinator.drain(JID)

    assert kinds(coordinator) == ['bonded-cross-check'], 'queue takes one analysis per run; the rest are owed, not queued'
    assert answer['queued'] == [coordinator.lookup(JID)['analyses'][0]['id']]
    assert answer['owed'] == ['dihedral-fit', 'energy-conservation', 'ff-interactions']


def test_the_next_kind_starts_when_the_running_one_settles(dashboard, monkeypatch):
    coordinator, _ = seed(dashboard)
    monkeypatch.setattr(coordinator.analysis_coordinator, 'run', lambda *args: None)
    coordinator.analysis_coordinator.drain(JID)

    settle(coordinator, wait_for_a_task(coordinator)[0])
    answer = coordinator.analysis_coordinator.drain(JID)

    # One analysis per run at a time: settling the first starts the second, and the third waits its turn.
    assert kinds(coordinator) == ['bonded-cross-check', 'dihedral-fit']
    assert answer['owed'] == ['energy-conservation', 'ff-interactions']


def test_a_failed_attempt_does_not_chain_because_it_would_queue_itself_again(dashboard, monkeypatch):
    """The kind is not current by identity after a failure, so chaining from it would spin; a person asks instead."""
    coordinator, _ = seed(dashboard)
    monkeypatch.setattr(coordinator.analysis_coordinator, 'run', lambda *args: None)
    coordinator.analysis_coordinator.drain(JID)
    failed = wait_for_a_task(coordinator)[0]
    settle(coordinator, failed, status='failed')

    assert coordinator.analysis_coordinator.chain(JID, failed['id']) == {'queued': [], 'owed': []}
    assert kinds(coordinator) == ['bonded-cross-check'], 'nothing was started after the failure'


def test_recompute_offers_a_failed_kind_again(dashboard, monkeypatch):
    """What the button is for: a producer that failed is retried on request, and it is the first thing offered."""
    coordinator, _ = seed(dashboard)
    monkeypatch.setattr(coordinator.analysis_coordinator, 'run', lambda *args: None)
    coordinator.analysis_coordinator.drain(JID)
    settle(coordinator, wait_for_a_task(coordinator)[0], status='failed')

    answer = coordinator.analysis_coordinator.drain(JID)

    assert kinds(coordinator) == ['bonded-cross-check', 'bonded-cross-check'], 'a second attempt beside the failed one'
    first, second = coordinator.lookup(JID)['analyses']
    assert re.fullmatch(r'analyses/bonded-cross-check/0001-\d{8}', first['directory']), first['directory']
    assert re.fullmatch(r'analyses/bonded-cross-check/0002-\d{8}', second['directory']), second['directory']
    assert answer['queued'] and answer['owed'] == ['dihedral-fit', 'energy-conservation', 'ff-interactions']


def test_recompute_is_refused_while_the_run_is_still_working(dashboard):
    coordinator, _ = seed(dashboard)
    coordinator.database().update(JID, status='running')

    response = dashboard.client.post(f'/api/jobs/{JID}/analyses/recompute', json={})

    assert response.status_code == 409
    assert 'stopped' in response.get_json()['error']


def test_recompute_queues_the_run_and_says_what_is_still_waiting(dashboard, monkeypatch):
    coordinator, _ = seed(dashboard)
    monkeypatch.setattr(coordinator.analysis_coordinator, 'run', lambda *args: None)

    response = dashboard.client.post(f'/api/jobs/{JID}/analyses/recompute', json={})

    assert response.status_code == 202
    assert response.get_json() == {'queued': [coordinator.lookup(JID)['analyses'][0]['id']],
                                   'owed': ['dihedral-fit', 'energy-conservation', 'ff-interactions']}


def test_recompute_twice_with_nothing_changed_queues_nothing(dashboard, monkeypatch):
    """`queue` fingerprints the analysis code: what is current is not recomputed, so a second press is free."""
    coordinator, _ = seed(dashboard)
    monkeypatch.setattr(coordinator.analysis_coordinator, 'run', lambda *args: None)
    dashboard.client.post(f'/api/jobs/{JID}/analyses/recompute', json={})
    # Work the list through the way completion does: settle what is queued, `chain` the next, stop when none is left.
    while True:
        queued = [task for task in coordinator.lookup(JID)['analyses'] if task['status'] == 'queued']
        if not queued:
            break
        for task in queued:
            settle(coordinator, task)
            coordinator.analysis_coordinator.chain(JID, task['id'])

    answer = coordinator.analysis_coordinator.drain(JID)

    assert answer == {'queued': [], 'owed': []}
    assert kinds(coordinator) == ['bonded-cross-check', 'dihedral-fit', 'energy-conservation',
                             'ff-interactions']


def test_an_attempt_is_named_by_its_sequence_and_its_date(dashboard, monkeypatch):
    """`analyses/<kind>/<NNNN>-<YYYYMMDD>/`: the record names the directory a reader opens."""
    coordinator, _ = seed(dashboard)
    monkeypatch.setattr(coordinator.analysis_coordinator, 'run', lambda *args: None)

    task, status = coordinator.analysis_coordinator.queue(JID, 'bonded-cross-check', {})

    assert status == 202
    assert re.fullmatch(r'analyses/bonded-cross-check/0001-\d{8}', task['directory']), task['directory']


def test_the_next_number_is_read_from_the_disk_as_well_as_the_record(dashboard, monkeypatch):
    """A number already on disk is never minted over, even when the record that named it is gone."""
    coordinator, run = seed(dashboard)
    monkeypatch.setattr(coordinator.analysis_coordinator, 'run', lambda *args: None)
    (run / 'analyses' / 'bonded-cross-check' / '0007-20260101').mkdir(parents=True)

    task, status = coordinator.analysis_coordinator.queue(JID, 'bonded-cross-check', {})

    assert status == 202
    assert re.fullmatch(r'analyses/bonded-cross-check/0008-\d{8}', task['directory']), task['directory']


def test_a_source_rewritten_in_place_is_the_same_attempt(dashboard, monkeypatch):
    """The identity names the source and never reads it, so replaced bytes are not a new analysis."""
    coordinator, run = seed(dashboard)
    monkeypatch.setattr(coordinator.analysis_coordinator, 'run', lambda *args: None)
    first, status = coordinator.analysis_coordinator.queue(JID, 'bonded-cross-check', {})
    assert status == 202
    settle(coordinator, first)

    (run / 'stages' / SOURCES[0]).write_text('re-written under the same name\n')
    again, status = coordinator.analysis_coordinator.queue(JID, 'bonded-cross-check', {})

    assert status == 200, 'the same source name is the same attempt'
    assert again['id'] == first['id']
    assert kinds(coordinator) == ['bonded-cross-check']


def test_an_edited_payload_mints_the_next_attempt_number(dashboard, monkeypatch):
    """"What it was asked" is part of the identity: another payload is another answer, named in order."""
    coordinator, _ = seed(dashboard)
    monkeypatch.setattr(coordinator.analysis_coordinator, 'run', lambda *args: None)
    first, _ = coordinator.analysis_coordinator.queue(JID, 'bonded-cross-check', {'threshold': 0.1})
    settle(coordinator, first)

    second, status = coordinator.analysis_coordinator.queue(JID, 'bonded-cross-check', {'threshold': 0.2})

    assert status == 202
    assert second['id'] != first['id']
    assert re.fullmatch(r'analyses/bonded-cross-check/0002-\d{8}', second['directory']), second['directory']
    assert kinds(coordinator) == ['bonded-cross-check', 'bonded-cross-check']



def test_the_published_reader_answers_the_newest_attempt_whose_file_stands(dashboard, monkeypatch):
    """The sequenced attempt holds its record at its root, and an attempt whose published file is gone falls
    through to the older one that still stands."""
    from dashboard.web.routes.analyses import newest_cross_check

    coordinator, run = seed(dashboard)
    monkeypatch.setattr(coordinator.analysis_coordinator, 'run', lambda *args: None)
    report = {'molecule': 'DDM', 'disagreements': [['B01', 'B02']]}
    older, _ = coordinator.analysis_coordinator.queue(JID, 'bonded-cross-check', {})
    settle(coordinator, older)
    _publish(run / older['directory'], report)
    newer, _ = coordinator.analysis_coordinator.queue(JID, 'bonded-cross-check', {'threshold': 0.2})
    settle(coordinator, newer)
    _publish(run / newer['directory'], report)

    found = newest_cross_check(coordinator, coordinator.lookup(JID))
    assert found is not None and found[0].name == Path(newer['directory']).name, 'the newer attempt is the answer'

    (run / newer['directory'] / 'output' / 'key' / 'bonded-cross-check.json').unlink()
    found = newest_cross_check(coordinator, coordinator.lookup(JID))

    assert found is not None and found[0].name == Path(older['directory']).name,         'the older attempt that still stands is the answer'


def _publish(attempt, report):
    """One attempt's record and published report, the way the worker leaves them: the output directory is named."""
    output = attempt / 'output' / 'key'
    output.mkdir(parents=True, exist_ok=True)
    (attempt / 'result.json').write_text(json.dumps({'output_directory': 'output/key'}))
    (output / 'bonded-cross-check.json').write_text(json.dumps(report))

