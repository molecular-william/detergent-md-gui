# In-place run resume

Date: 2026-09-22. Implements the user-approved same-run design.

Resume keeps the job ID, database row, label, creation timestamp, settings, and
run directory. It restarts the selected stage from its beginning, executing the
files currently present in that stage and its downstream stages. It does not
continue partway through a GROMACS checkpoint.
Retry and Clone still create separate jobs. Historical copied-resume jobs retain
their provenance, but subsequent Resume requests use their own existing ID.

## Storage and provenance

The manifest's completed-stage prefix determines which stage can be selected;
resume does not hash or compare `inputs/` or upstream outputs. Selected and
downstream stage directories must exist and must not be symlinks. Their current
launchers, inputs, outputs, and scratch files remain in place and are passed to
the worker unchanged. This lets an operator repair or replace a launcher before
resuming. Archive the old manifest and job record under
`resume_history/<attempt>/`; the current manifest retains an append-only
`resume_history` and only the upstream active stage records. Each attempt gets a
distinct log directory.

A durable preparation journal supports rollback after exceptions or interruption.
Before the database commit, any failed preparation restores the original stage
paths and manifest. After the commit, recovery retains the prepared attempt.
The journal is resolved under the worker lock before further preparation or
startup reconciliation. Original scientific data are never deleted by resume.

## Admission and worker ownership

The coordinator holds its job lock and the existing run's worker lease during
admission, preparation, and transfer to the worker. Reject active simulation or
analysis workers, external leases, invalid stages, insufficient disk/capacity,
and retained reference consumers (or active legacy copied-resume consumers).
Dependency checking and requeueing use one SQLite transaction, preventing a
consumer from attaching across the transition. Verify shared AA sources before
queueing and again at execution.

Requeue the existing row with cleared error/end/command, reference eligibility
false, incremented `resume_count`, `resume_from`, and `resume_requested_at`.
Use `resume_in_place` to select the already-prepared worker path. The worker must
not prepare twice, recreate the run directory, or replace its manifest. A thread
launch failure leaves a failed, resumable job with preserved history. Recovery
marks interrupted attempts failed and never signals historical process IDs.

## Analyses and UI

Preserve analysis files and original task records in the archived job. Mark the
current job's prior analysis records superseded, so dependency selection and
signature reuse cannot silently reuse earlier trajectories. Active analyses block
resume. Old records remain inspectable as historical artifacts.

POST `/api/jobs/<id>/resume` returns HTTP 200 and the same ID. The row transitions
to queued/running and the message says "Run resumed; current stage files will be
executed." Detailed responses expose resume history. Prior logs remain
accessible and log downloads preserve their relative directory names.

## Acceptance

Test same ID/row count/creation timestamp; actual worker completion in the same
directory; repeated resumes and cancellation; current stage launchers and
upstream files preserved; modified or missing checksum inputs accepted; symlink,
lease, consumer, and quota rejection before mutation; rollback and restart
recovery before/after commit; shared-reference resume; superseded analyses;
unchanged clone/retry semantics; and browser row identity/status/notice.
