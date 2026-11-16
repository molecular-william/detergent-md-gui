"""A failed stage says what went wrong, not which command returned 1.

`subprocess.CalledProcessError` stringifies to `Command '['bash', ...]' returned non-zero exit status 1` -- the
wrapper naming the failure and never its reason. The reason is in the stage log, which nobody reading a run card
opens: run `6ed68979edf0` failed this way, and the line that explains it ("Cannot compute PME interactions on a GPU
... Systems that do not use PME for electrostatics") was two screens down the log. The executor now reads the log's
tail once and carries it on the failure, so the stage record, the run record, the console line and the card say the
same thing.
"""
import json
import subprocess

import pytest
from dashboard.execution import workflow
from dashboard.execution.adapters import aa
from dashboard.models.molecules import aa as aa_molecules

from tests.harness.support import PROJECT_ROOT

MOLECULES = PROJECT_ROOT / 'molecules'

#: What GROMACS writes below the wrapper's line: the error block a reader can act on, then the MPI shutdown banner
#: that a bounded tail does not need.
GROMACS_FAILURE = """
+ gmx mdrun -deffnm eq -nb gpu -pme gpu -update gpu
-------------------------------------------------------
Program:     gmx mdrun, version 2026.3
Source file: src/gromacs/taskassignment/decidegpuusage.cpp (line 540)

Inconsistency in user input:
Cannot compute PME interactions on a GPU, because:
  PME GPU does not support:
    Systems that do not use PME for electrostatics.
-------------------------------------------------------
--------------------------------------------------------------------------
MPI_ABORT was invoked on rank 0 in communicator MPI_COMM_WORLD
with errorcode 1.

NOTE: invoking MPI_ABORT causes Open MPI to kill all MPI processes.
You may or may not see output from other processes, depending on
exactly when Open MPI kills them.
--------------------------------------------------------------------------
"""


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    """A real AA-only run, prepared with the tool probes stubbed -- the run its first stage can fail in."""
    monkeypatch.setattr(aa, 'tool_metadata', lambda: {'gmx': {'path': 'gmx', 'version_output': 'test'}})
    monkeypatch.setattr(aa, 'gromacs_flavour', lambda *arguments, **keywords: 'mpi')
    selected = aa_molecules.selection(MOLECULES, 'DDM', run_type='aa_only')
    aa.prepare_run(tmp_path, MOLECULES, selected, {'box_nm': 4.0})
    return tmp_path


def test_a_failed_stage_records_the_tools_own_error(prepared):
    """The whole path the executor uses: the command fails, and the record quotes the log, not the wrapper."""
    (prepared / 'logs').mkdir()

    def execute(command, **kwargs):
        kwargs['stdout'].write(GROMACS_FAILURE)
        kwargs['stdout'].flush()
        raise subprocess.CalledProcessError(1, command)

    with pytest.raises(workflow.StageFailed) as failure:
        workflow.run(prepared, prepared / 'logs/console.log', execute=execute, stop_after=aa.STAGES[0][0])

    stage = json.loads((prepared / 'manifest.json').read_text())['stages'][0]
    assert stage['status'] == 'failed' and stage['exit_code'] == 1
    message = stage['error']
    assert message.splitlines()[0] == 'AA solvation failed (exit 1):', 'the first line names the stage'
    assert 'Cannot compute PME interactions on a GPU' in message
    assert 'Systems that do not use PME for electrostatics.' in message
    assert 'MPI_ABORT' not in message and 'You may or may not see output' not in message
    assert failure.value.snapshot.splitlines()[-1] == 'Systems that do not use PME for electrostatics.'


def test_the_snapshot_is_a_bounded_tail_of_the_log(tmp_path):
    """A production log holds a whole run's output: the snapshot reads the end of the file, not all of it."""
    log = tmp_path / 'stage.log'
    log.write_text('\n'.join(f'step {index}' for index in range(1000)) + '\nthe reason\n')

    snapshot = workflow.failure_snapshot(log)

    assert snapshot.splitlines()[-1] == 'the reason'
    assert len(snapshot.splitlines()) == workflow.ERROR_TAIL_LINES
    assert 'step 999' in snapshot and 'step 990' not in snapshot


def test_a_log_that_cannot_be_read_leaves_the_stage_named(tmp_path):
    """No log is not a reason to lose the failure: the stage and its exit code still travel."""
    assert workflow.failure_snapshot(tmp_path / 'absent.log') == ''
    failure = workflow.StageFailed('CG simulation', 1, '')
    assert str(failure) == 'CG simulation failed (exit 1)'
    assert failure.returncode == 1
