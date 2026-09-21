# Persistence and Coordinator Clean-Break Design

## Goal

Start the new workspace from a single SQLite job store and make execution
coordination readable by separating job state ownership from analysis
scheduling and repeated immutable JSON persistence mechanics.

## Scope

The reset removes the live `jobs.json` file and all generated runtime/model
records listed in the approved deletion boundary. No migration of old jobs is
provided. A new workspace is created explicitly and must be empty before the
dashboard starts.

Canonical scientific inputs and source code remain untouched. Simulation
outputs are created only in new run directories and are immutable after stage
publication except for append-only manifest status updates.

## Design

`dashboard/paths.py` exposes `workspace/jobs.sqlite3` as the job database path.
`dashboard/store.py` accepts that database path directly; it no longer imports
`jobs.json`, preserves a legacy JSON path, or offers a live JSON replacement
operation. SQLite schema creation remains idempotent and transactional. The
CLI export command is removed with the old store contract; database backup is
the supported recovery mechanism.

The job store keeps job records and artifact-index rows. `Coordinator.database()`
constructs the store with the canonical SQLite path. Admission, deletion, and
dependency checks continue to happen inside SQLite transactions while the
coordinator owns worker leases and process groups.

The file-backed model stores share a small repository helper for:

- resolving a validated record ID below a configured root;
- listing JSON records while skipping corrupt files with a caller-selected
  policy;
- loading one record;
- writing a complete record through a same-directory temporary file and atomic
  replacement; and
- refusing symlinked roots or records.

Mapping, bonded-state, model-registry, composition, and review modules retain
their domain validation, identity hashing, revision rules, and reference
guards. They call the helper rather than reimplementing path, ID, and atomic
write mechanics. The helper does not hide scientific validation or turn
distinct record types into a generic schema.

`Coordinator` remains the owner of job lifecycle, leases, admission, recovery,
and public job projections. Analysis fingerprinting, task persistence,
subprocess execution, progress publication, and analysis-worker cleanup move to
`dashboard/execution/analysis_coordinator.py` (or an equivalently named
focused module). The coordinator calls this component with a job identity and
the current run path; it does not know the analysis subprocess command details.
Manifest parsing/cache behavior moves beside manifest handling so public-job
projection does not mix file caching with scheduling.

The extracted components use explicit narrow interfaces and receive paths,
store access, and worker factories through their constructor. They do not own a
second global coordinator, database, or service lease.

## Invariants

- SQLite is the only live job-status authority.
- A job update and its revision increment are one transaction.
- A source run cannot be deleted while a consumer or active resume depends on
  it.
- A filesystem cleanup failure leaves the database record available for retry.
- A model record is fully written or not visible; partial JSON files are never
  published as records.
- Analysis products are keyed by source hashes, request payload, code
  signature, and relevant completed analysis dependencies.
- Analysis output never modifies source trajectories or completed run stages.
- A worker lease belongs to the current coordinator process and is released in
  a `finally` path.

## Fresh-workspace reset

The reset command or documented operator procedure validates the target path,
rejects symlinks, verifies that no current coordinator owns it, removes only
the approved generated directories/files, recreates the empty workspace
directories, and writes a reset record containing timestamp, operator intent,
and deleted paths. It must not recurse into the project root or delete
canonical inputs.

## Tests and acceptance

- Store tests create a SQLite database directly and prove insert, update,
  pagination, artifact indexing, dependency-protected deletion, rollback on
  cleanup failure, and concurrent transaction behavior.
- Repository-helper tests cover atomic replacement, malformed JSON, invalid
  IDs, symlink rejection, and immutable record visibility.
- Coordinator tests verify the extracted analysis component's queue,
  deduplication, cancellation, failure publication, and lease cleanup.
- API tests use fresh SQLite workspaces and contain no `jobs.json` patches.
- Reset tests prove only the approved generated paths are removed and source
  assets remain unchanged.
- GitNexus impact checks cover `Store` (critical), `Paths` (medium),
  `Coordinator`, `queue_analysis`, `run_analysis`, and every direct database
  caller before implementation edits.

## Non-goals

This does not migrate historical job data, preserve the old JSON export
format, add a distributed database, or change scientific analysis semantics.
