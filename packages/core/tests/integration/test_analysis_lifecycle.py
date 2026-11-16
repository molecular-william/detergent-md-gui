"""The analysis attempt lifecycle: what a failure and a cancellation record.

Adopting coordination/attempt.py here replaced a try/except/finally that recorded a failure and then
let the worker thread end quietly. attempt() re-raises on purpose, so this site has to swallow it
*after* the record is written -- and nothing tested that: the first version leaked
PytestUnhandledThreadExceptionWarning under -n 4, which is only visible because the warning is not a
failure. The plan's named gate for the adoption covers the worker's report, not this path.

The two things worth pinning are the two the shared lifecycle exists for: a cancellation is recorded
as cancelled, not failed, and a failed command keeps its exit code.
"""
import fcntl
import subprocess
import threading

from dashboard.execution import workflow
from dashboard.execution.coordination import analysis_coordinator


class FailingWorker:
    """Stands in for Worker: raises like a subprocess that exited nonzero."""
    run_dir = None
    lease_file = None
    limit_error = None

    def execute(self, command, **kwargs):
        raise subprocess.CalledProcessError(3, ['dashboard.analysis'])


class CancellingWorker(FailingWorker):
    def execute(self, command, **kwargs):
        raise workflow.Cancelled('Cancelled by user')


def seed(dashboard, jid, aid='000000000001'):
    job = {'id': jid, 'label': 'Analysis run', 'detergent': 'DDM', 'method': 'fast_forward',
           'status': 'completed', 'stage': 'complete', 'created': dashboard.coordinator.now(),
           'analyses': [{'id': aid, 'kind': 'bonded-cross-check', 'payload': {}, 'signature': 'sig',
                         'directory': 'analysis/' + aid, 'status': 'queued'}]}
    coordinator = dashboard.coordinator
    coordinator.database().replace([job])
    (coordinator.RUNS / jid).mkdir(parents=True)
    return coordinator, jid, aid


def record(coordinator, jid, aid='000000000001'):
    return next(task for task in coordinator.lookup(jid)['analyses'] if task['id'] == aid)


def test_a_failed_analysis_is_recorded_with_its_exit_code_and_does_not_escape(dashboard):
    coordinator, jid, aid = seed(dashboard, 'aa11bb22cc55')
    # No pytest.raises here on purpose: the caller is a worker thread, so the failure must come back
    # as a record rather than as an exception nobody catches.
    coordinator.analysis_coordinator.run(jid, aid, FailingWorker())

    task = record(coordinator, jid)
    assert task['status'] == 'failed'
    assert 'returned non-zero exit status 3' in task['error']
    assert task['exit_code'] == 3, 'the exit code only this site used to keep'
    assert task['ended_at']


def test_a_cancelled_analysis_is_recorded_as_cancelled_not_failed(dashboard):
    coordinator, jid, aid = seed(dashboard, 'aa11bb22cc66')

    coordinator.analysis_coordinator.run(jid, aid, CancellingWorker())

    task = record(coordinator, jid)
    assert task['status'] == 'cancelled'
    assert task['error'] == 'Cancelled by user'


def hold(coordinator, jid):
    """Take the run's own lock the way a live worker holds it."""
    lock = (coordinator.RUNS / jid / '.worker.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return lock


def test_an_analysis_waits_out_a_run_lock_that_is_about_to_be_released(dashboard):
    """The completion path queues a run's analyses as its worker lets go, so a lost claim used to kill the thread."""
    coordinator, jid, aid = seed(dashboard, 'aa11bb22cc77')
    worker = FailingWorker()
    coordinator.ANALYSIS_WORKERS[(jid, aid)] = worker
    lock = hold(coordinator, jid)
    threading.Timer(0.2, lock.close).start()

    coordinator.analysis_coordinator.run(jid, aid, worker)

    task = record(coordinator, jid)
    assert task['status'] == 'failed' and task['exit_code'] == 3, 'the command ran once the run let go'
    assert (jid, aid) not in coordinator.ANALYSIS_WORKERS, 'the run is free for its next analysis'


def test_a_run_that_never_lets_go_is_a_recorded_refusal_rather_than_a_lost_thread(dashboard, monkeypatch):
    """Measured on run 0c5f5738089c: the thread died on the lock, the slot was never released, and the run answered
    every later analysis `already active` until a restart."""
    coordinator, jid, aid = seed(dashboard, 'aa11bb22cc88')
    monkeypatch.setattr(analysis_coordinator.AnalysisCoordinator, 'CLAIM_SECONDS', 0.2)
    worker = FailingWorker()
    coordinator.ANALYSIS_WORKERS[(jid, aid)] = worker
    lock = hold(coordinator, jid)
    try:
        coordinator.analysis_coordinator.run(jid, aid, worker)
    finally:
        lock.close()

    task = record(coordinator, jid)
    assert task['status'] == 'failed'
    assert 'worker still holds this run' in task['error']
    assert (jid, aid) not in coordinator.ANALYSIS_WORKERS, 'the attempt records the refusal and gives the slot back'
