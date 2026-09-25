"""One attempt lifecycle, so three coordinators cannot spell it three ways.

workflow.run, coordinator.run_job and analysis_coordinator.run each marked work running, caught,
decided between failed and cancelled, recorded the message and ran their own exit bookkeeping --
and they disagreed: one wrote the terminal status into a manifest entry, one wrote it straight to
the database, one kept locals and wrote them in a finally. A cancelled stage and a cancelled
analysis were recorded by different code, and only one of them kept a CalledProcessError's exit
code. This is the shape they share.
"""
import subprocess

import pytest

from dashboard.execution.coordination import attempt as attempt_module
from dashboard.execution.workflow import Cancelled


def writer(calls):
    def update(record, **fields):
        record.update(fields)
        calls.append(dict(fields))
    return update


def test_a_successful_attempt_marks_running_then_completed():
    record, calls = {}, []
    with attempt_module.attempt(record, update=writer(calls)) as work:
        assert work is record, 'the caller works on the record it passed in'
        assert record['status'] == 'running', 'running is written on entry, before the body'
    assert record['status'] == 'completed'
    assert [call['status'] for call in calls] == ['running', 'completed']


def test_a_failure_is_recorded_with_its_message_and_re_raised():
    record = {}
    with pytest.raises(ValueError, match='the reason'):
        with attempt_module.attempt(record, update=writer([])):
            raise ValueError('the reason')
    assert record['status'] == 'failed'
    assert record['error'] == 'the reason'


def test_a_cancellation_is_not_a_failure():
    record = {}
    with pytest.raises(Cancelled):
        with attempt_module.attempt(record, update=writer([])):
            raise Cancelled('Cancelled by user')
    assert record['status'] == 'cancelled'
    assert record['error'] == 'Cancelled by user'


def test_a_failed_command_keeps_its_exit_code():
    """The site that recorded exit codes was the stage loop; the others dropped them."""
    record = {}
    failure = subprocess.CalledProcessError(1, ['gmx', 'mdrun'])
    with pytest.raises(subprocess.CalledProcessError):
        with attempt_module.attempt(record, update=writer([])):
            raise failure
    assert record['status'] == 'failed' and record['exit_code'] == 1


def test_the_entry_fields_a_site_supplies_are_written_with_running():
    """The job loop's entry write carries more than the status."""
    record, calls = {}, []
    with attempt_module.attempt(record, update=writer(calls), running={'stage': 'input'}):
        pass
    assert calls[0] == {'status': 'running', 'stage': 'input'}


def test_the_exit_hook_runs_exactly_once_on_either_path():
    seen = []
    with attempt_module.attempt({}, update=writer([]), on_exit=lambda record: seen.append(record)):
        pass
    with pytest.raises(ValueError):
        with attempt_module.attempt({}, update=writer([]), on_exit=lambda record: seen.append(record)):
            raise ValueError('boom')
    assert len(seen) == 2, 'once per attempt, successful or not'
