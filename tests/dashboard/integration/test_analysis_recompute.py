"""The Analysis graphs panel can ask a finished run for the analyses it owes, and gets the rest afterwards.

Two things this pins, and the second is the defect the first was hiding:

* **One kind at a time.** `queue` takes one analysis per run and refuses a second with `RunBusy` while the first holds
  the worker, which is what keeps a person's cancel meaningful. Asking for the whole owed list at once therefore
  started exactly one kind and dropped the others on the floor: run `ce1318485197`, an `aa_cg` run owing
  `bonded-cross-check` and `dihedral-fit`, never reached the second, with no record that it had ever been considered.
* **The rest follow.** What the drain cannot start is named in `owed`, and the next kind starts when one settles --
  which is what makes the button a request rather than a race with whoever is already analysing something.

The analyses themselves are not run: a worker standing in for the subprocess is what makes these fast, and what the
producer does about its sources is pinned where the producer lives.
"""
import time

from tests.harness import support

JID = '123456abcdef'
SOURCES = ('2_mapping/mapped.gro', '2_mapping/mapped.xtc', '2_mapping/model.json',
           '3_initial_CG/SUCR_ff_inter.itp', '3_initial_CG/SUCR_initial.itp')


def seed(dashboard, *, run_type='aa_cg'):
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
    assert answer['owed'] == ['dihedral-fit']


def test_the_next_kind_starts_when_the_running_one_settles(dashboard, monkeypatch):
    coordinator, _ = seed(dashboard)
    monkeypatch.setattr(coordinator.analysis_coordinator, 'run', lambda *args: None)
    coordinator.analysis_coordinator.drain(JID)

    settle(coordinator, wait_for_a_task(coordinator)[0])
    answer = coordinator.analysis_coordinator.drain(JID)

    assert kinds(coordinator) == ['bonded-cross-check', 'dihedral-fit']
    assert answer['owed'] == []


def test_a_failed_attempt_does_not_chain_because_it_would_queue_itself_again(dashboard, monkeypatch):
    """The kind is not current by signature after a failure, so chaining from it would spin; a person asks instead."""
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
    assert answer['queued'] and answer['owed'] == ['dihedral-fit']


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
                                   'owed': ['dihedral-fit']}


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
    assert kinds(coordinator) == ['bonded-cross-check', 'dihedral-fit']
