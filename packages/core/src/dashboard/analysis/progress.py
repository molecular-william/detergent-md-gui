"""Report an analysis attempt's current phase from its own subprocess.

`worker.execute` names the attempt's `progress.json` in `DASHBOARD_ANALYSIS_PROGRESS` for the duration of the
producer call; a producer (or a thread it starts) calls `report` and the UI's task line follows. The variable is
absent in direct calls and tests, where reporting is a silent no-op. Each analysis is its own process, so this is
process-local state rather than a shared global.
"""
import os

from dashboard import files

ENV = 'DASHBOARD_ANALYSIS_PROGRESS'


def report(phase):
    """Write `{'phase': phase}` to the attempt's progress file, or do nothing when none was named."""
    path = os.environ.get(ENV)
    if not path:
        return
    files.atomic_json(path, {'phase': phase})
