"""One attempt lifecycle for a stage, a job and an analysis task.

Each of the three loops marks its work running, catches, decides between failed and cancelled,
records the message and runs its own exit bookkeeping. They disagreed on the spelling: the stage
loop wrote a terminal status into a manifest entry and kept a CalledProcessError's exit code, the
analysis loop wrote straight to the database and dropped it, and the job loop kept locals and
wrote them in a finally. The decision that must not differ -- what a failure and a cancellation
are called, and what is recorded with them -- lives here now.

A site passes the record it updates and how to write it. The manager writes `running` on entry,
exactly one terminal status, and calls the exit hook once either way. Errors are re-raised: the
caller still decides what the process does about them.
"""
from contextlib import contextmanager

from ..workflow import Cancelled, Skipped


def _terminal_fields(exc):
    """A failed command's exit code travels with its failure, when it has one."""
    code = getattr(exc, 'returncode', None)
    return {'exit_code': code} if code is not None else {}


@contextmanager
def attempt(record, *, update, running=None, on_exit=None):
    """Run one unit of work under the shared lifecycle.

    `update(record, **fields)` is how this site writes the record: into a manifest entry, a
    database row, or locals it will write in the exit hook. `running` carries whatever else the
    site's entry write has always included. `on_exit(record)` runs exactly once, after the
    terminal status has been written, on the successful and the failing path alike.
    """
    update(record, status='running', **(running or {}))
    try:
        yield record
    except Skipped as exc:
        # Nothing was attempted, so nothing failed and nothing is owed: the stage is recorded and the loop that called
        # it goes on to the next one. This is the one terminal status that is not re-raised, because stopping the run
        # is exactly what it must not do.
        update(record, status='skipped', error=str(exc), **_terminal_fields(exc))
        return
    except Cancelled as exc:
        update(record, status='cancelled', error=str(exc), **_terminal_fields(exc))
        raise
    except Exception as exc:
        update(record, status='failed', error=str(exc), **_terminal_fields(exc))
        raise
    else:
        update(record, status='completed')
    finally:
        if on_exit is not None:
            on_exit(record)
