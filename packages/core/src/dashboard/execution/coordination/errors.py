"""Domain errors the lifecycle raises, and nothing about HTTP.

The coordinator and the analysis coordinator used to answer a request by name -- ``abort``
with a status code -- which put the web layer's vocabulary inside the module that owns
runs, and spread "what did the request fail with?" over forty call sites. They name the
failure now. ``dashboard/web/routes/common.py`` is the one place that decides the status
code for each name, and ``dashboard/app.py`` registers those handlers.

The plan's six names are here. Two more are here because the sites that needed them would
otherwise have had to change a status code or lie about their meaning: ``InvalidRequest``
for a malformed request that is nobody's conflict, and ``RunConflict`` for a request that
conflicts with the run's recorded state, as opposed to one blocked by a worker.
"""


class RunError(Exception):
    """Something about the request cannot be honoured."""


class InvalidRequest(RunError):
    """The request is malformed, or names something the catalogue does not have."""


class InvalidRunId(RunError):
    """The record's id cannot address a run directory: malformed, or a symbolic link."""


class RunNotFound(RunError):
    """No such run, analysis or record exists."""


class RunBusy(RunError):
    """A worker, a lock or another process holds what this request needs."""


class RunConflict(RunError):
    """The request conflicts with the run's recorded state."""


class CapacityFull(RunError):
    """The request would exceed a configured limit."""


class DependencyRetained(RunError):
    """Completed consumers still reference what this request would remove."""


class SourceUnavailable(RunError):
    """A reference or source this request needs is missing, incomplete or unusable."""


ALL = (InvalidRequest, InvalidRunId, RunNotFound, RunBusy, RunConflict, CapacityFull,
       DependencyRetained, SourceUnavailable)
