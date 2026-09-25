"""The analysis attempt lifecycle: what a failure and a cancellation record.

Adopting coordination/attempt.py here replaced a try/except/finally that recorded a failure and then
let the worker thread end quietly. attempt() re-raises on purpose, so this site has to swallow it
*after* the record is written -- and nothing tested that: the first version leaked
PytestUnhandledThreadExceptionWarning under -n 4, which is only visible because the warning is not a
failure. The plan's named gate for the adoption covers the worker's report, not this path.

The two things worth pinning are the two the shared lifecycle exists for: a cancellation is recorded
as cancelled, not failed, and a failed command keeps its exit code.
"""
import subprocess

from dashboard.execution import workflow


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
           'analyses': [{'id': aid, 'kind': 'snapshots', 'payload': {}, 'signature': 'sig',
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
