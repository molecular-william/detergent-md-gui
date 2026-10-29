# Persistence and Coordinator Clean-Break Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the dual JSON/SQLite job boundary, centralize immutable JSON record mechanics, and separate analysis scheduling from the coordinator while preserving concurrency and deletion invariants.

**Architecture:** SQLite is the only live job store. A focused JSON repository helper serves model records without hiding their domain validation. `Coordinator` keeps leases, admission, lifecycle, and public projections; `AnalysisCoordinator` owns analysis task execution and publication.

**Tech Stack:** Python 3.13, SQLite WAL transactions, pathlib, Flask, subprocess workers, pytest.

**Spec:** `docs/superpowers/specs/2026-09-21-persistence-coordinator-clean-break-design.md`

## Global Constraints

- SQLite is the only live job-status authority.
- Job updates, revisions, dependency checks, and cleanup guards remain transactional.
- Model records are atomically published and reject symlinked paths.
- Analysis products are keyed by source hashes, request payload, code signature, and relevant dependencies.
- Analysis never modifies source trajectories or completed stages.
- Worker leases belong to the current coordinator and are released in `finally` paths.
- The reset targets only the approved generated paths.

### Task 1: Make SQLite the Canonical Job Store

**Files:**
- Modify: `dashboard/paths.py`
- Modify: `dashboard/store.py`
- Modify: `dashboard/execution/coordinator.py`
- Modify: `dashboard/cli/migrate_workspace.py`
- Modify: `tests/dashboard/conftest.py`
- Modify: `tests/dashboard/unit/test_store.py`
- Modify: `tests/dashboard/integration/test_aa_api.py`
- Modify: `tests/dashboard/integration/test_operations.py`

**Interfaces:**
- `Paths.database -> Path` returns `workspace / 'jobs.sqlite3'`.
- `Store(database: Path)` opens or creates the SQLite database directly.
- `Coordinator.database() -> Store` passes `self.DATA` as the SQLite path.
- `Store.insert`, `insert_many`, `get`, `all`, `update`, `delete_with_cleanup`, `page`, and `artifacts` retain their behavior with no JSON import side effect.

- [ ] **Step 1: Write failing canonical-path tests.** Assert that a fresh `Paths` object exposes `database`, that `Store(paths.database)` creates SQLite without reading any JSON file, and that no `jobs.json` is required for `all()`.
- [ ] **Step 2: Run focused store tests.** Run `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_store.py -q`. Expected: FAIL because `Store` currently derives SQLite from a legacy JSON path and imports it.
- [ ] **Step 3: Implement the direct SQLite store.** Rename the constructor argument, remove one-time JSON import metadata and `replace`, and update `Paths` and coordinator construction. Keep WAL, transactions, revisions, artifact rows, dependency checks, and export refusal behavior only where still relevant.
- [ ] **Step 4: Remove legacy export/migration coupling.** Delete the `dashboard.store` JSON-export CLI path and remove workspace-migration assumptions that copy or compare live `jobs.json`. Keep migration code only if it is still required for canonical source paths; otherwise delete it with its tests.
- [ ] **Step 5: Update test fixtures.** Replace all `jobs.json` patches with isolated SQLite paths and create empty workspace directories explicitly.
- [ ] **Step 6: Run the persistence suite.** Run `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_store.py tests/dashboard/integration/test_aa_api.py tests/dashboard/integration/test_operations.py tests/dashboard/integration/test_aa_dependencies.py -q`. Expected: PASS.
- [ ] **Step 7: Run GitNexus impact and commit.** Run impact for `Store`, `Paths`, and `Coordinator.database`, inspect the critical Store callers, run `detect-changes`, and commit with `git commit -m "refactor: make SQLite the canonical job store"`.

### Task 2: Add the Shared Immutable JSON Repository Helper

**Files:**
- Create: `dashboard/models/json_repository.py`
- Modify: `dashboard/models/mapping_store.py`
- Modify: `dashboard/models/bonded_states.py`
- Modify: `dashboard/models/model_registry.py`
- Modify: `dashboard/models/compositions.py`
- Modify: `dashboard/files.py`
- Create: `tests/dashboard/unit/test_json_repository.py`
- Modify: `tests/dashboard/unit/test_bonded_states.py`
- Modify: `tests/dashboard/unit/test_detergent_models.py`

**Interfaces:**
- `JsonRepository(root: Path, pattern: str, validate_id: Callable[[str], str])` owns path containment and record-file mechanics.
- `JsonRepository.path(record_id: str) -> Path` rejects invalid IDs and symlinked roots.
- `JsonRepository.get(record_id: str) -> dict` loads one object.
- `JsonRepository.list() -> list[dict]` returns valid records in stable path order and applies the caller's corrupt-record policy.
- `JsonRepository.write(record_id: str, record: dict) -> dict` atomically publishes a complete JSON object.

- [ ] **Step 1: Write failing repository tests.** Cover invalid IDs, root symlinks, record symlinks, atomic replacement, malformed JSON, stable listing, and absence of temporary files after a successful write.
- [ ] **Step 2: Run the focused test.** Run `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_json_repository.py -q`. Expected: FAIL because the helper does not exist.
- [ ] **Step 3: Implement the minimal helper.** Use `files.atomic_json` or a tightened equivalent, enforce root containment, and expose an explicit `skip_invalid` option rather than silently deciding for every caller.
- [ ] **Step 4: Migrate bonded states.** Replace `_path`, `_write`, and `all_states` mechanics with the helper while retaining revisions, mapping identity, topology validation, dependency references, and deletion guards. Remove `import_legacy_job`.
- [ ] **Step 5: Migrate model registry and compositions.** Replace repeated `_id`, `_path`, `_all`, and write loops with the helper while preserving per-kind validation and source-hash checks.
- [ ] **Step 6: Migrate mapping drafts and reviews.** Use the helper for saved drafts and review records, preserving packaged source discovery, validation cache keys, and parent provenance.
- [ ] **Step 7: Run model tests.** Run `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_json_repository.py tests/dashboard/unit/test_bonded_states.py tests/dashboard/unit/test_detergent_models.py tests/dashboard/integration/test_mapping_exports.py -q`. Expected: PASS.
- [ ] **Step 8: Run GitNexus impact and commit.** Run impact for `bonded_states.create`, `model_registry._write`, `mapping_store.save_draft`, and `compositions.create`, then `detect-changes`. Commit with `git commit -m "refactor: centralize immutable JSON persistence"`.

### Task 3: Extract Analysis Coordination

**Files:**
- Create: `dashboard/execution/analysis_coordinator.py`
- Modify: `dashboard/execution/coordinator.py`
- Modify: `dashboard/analysis/worker.py`
- Modify: `dashboard/web/routes/analyses.py`
- Create: `tests/dashboard/unit/test_analysis_coordinator.py`
- Modify: `tests/dashboard/integration/test_operations.py`
- Modify: `tests/dashboard/integration/test_analysis_display.py`

**Interfaces:**
- `AnalysisCoordinator(owner, worker_factory)` exposes `queue(job_id, kind, payload)`, `cancel(job_id, analysis_id)`, `update(job_id, analysis_id, **fields)`, `dependencies(job)`, and `run(job_id, analysis_id, worker)`.
- `Coordinator` delegates analysis methods and remains the source of job lookup, run paths, leases, storage limits, and job updates.
- The analysis subprocess request format remains `{run, kind, payload, code_signature, dependencies}`.

- [ ] **Step 1: Write failing delegation tests.** Assert that queue deduplication, active-worker rejection, analysis-capacity admission, cancellation, and result publication are handled through the extracted component.
- [ ] **Step 2: Run the focused test.** Run `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_analysis_coordinator.py -q`. Expected: FAIL because the component does not exist.
- [ ] **Step 3: Extract pure signature/dependency helpers.** Move source fingerprint construction, analysis dependency selection, and task-directory creation into the new module without changing the serialized task fields.
- [ ] **Step 4: Extract worker execution.** Move request writing, subprocess invocation, result loading, progress publication, output recording, and cleanup into `AnalysisCoordinator.run`.
- [ ] **Step 5: Delegate from Coordinator.** Keep `Coordinator.queue_analysis`, `cancel_analysis`, and public job projection as thin forwarding methods. Preserve `JOBS_LOCK`, worker maps, leases, capacity checks, and artifact refresh behavior.
- [ ] **Step 6: Run analysis tests.** Run `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_analysis_coordinator.py tests/dashboard/integration/test_operations.py tests/dashboard/integration/test_analysis_display.py tests/dashboard/browser/test_figure_viewer.py -q`. Expected: PASS.
- [ ] **Step 7: Run GitNexus impact and commit.** Run impact for `Coordinator.queue_analysis`, `Coordinator.run_analysis`, `Coordinator.update_analysis`, and `analysis.worker.execute`, then `detect-changes`. Commit with `git commit -m "refactor: isolate analysis coordination"`.

### Task 4: Extract Manifest Cache and Projection Helpers

**Files:**
- Create: `dashboard/execution/manifest.py`
- Modify: `dashboard/execution/coordinator.py`
- Modify: `dashboard/web/routes/runs.py`
- Create: `tests/dashboard/unit/test_manifest.py`
- Modify: `tests/dashboard/integration/test_operations.py`

**Interfaces:**
- `ManifestCache.read(path: Path) -> dict` performs bounded mtime/size caching and returns `{}` for unreadable manifests.
- `read_manifest(run_dir: Path) -> dict` validates the current run-root manifest path.
- `stage_log_path(run_dir: Path, recorded: str) -> Path | None` resolves only paths contained by the run.

- [ ] **Step 1: Write failing manifest-helper tests.** Cover cache invalidation after atomic replacement, unreadable manifests, absolute recorded paths containing the current run ID, traversal rejection, and symlink rejection.
- [ ] **Step 2: Run the focused test.** Run `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_manifest.py -q`. Expected: FAIL because the module does not exist.
- [ ] **Step 3: Move cache and path-resolution code.** Extract `_ManifestCache`, `stage_log_path`, and manifest reading without changing public JSON fields.
- [ ] **Step 4: Simplify Coordinator methods.** Replace embedded cache/path code with the helper and leave `public_job` focused on projection and lifecycle flags.
- [ ] **Step 5: Run route and operation tests.** Run `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_manifest.py tests/dashboard/integration/test_operations.py tests/dashboard/browser/test_dashboard_browser.py -q`. Expected: PASS.
- [ ] **Step 6: Run GitNexus detection and commit.** Run `detect-changes --scope all --repo .`, verify only manifest/coordinator callers changed, and commit with `git commit -m "refactor: isolate manifest handling"`.

### Task 5: Implement the Fresh-Workspace Reset

**Files:**
- Create: `dashboard/cli/reset_workspace.py`
- Modify: `dashboard/paths.py`
- Modify: `dashboard/README.md`
- Create: `tests/dashboard/integration/test_reset_workspace.py`

**Interfaces:**
- `reset_workspace(workspace: Path, *, confirm: bool, now: Callable[[], str]) -> dict` returns deleted paths and recreated directories.
- CLI usage: `dashboard/.venv/bin/python -m dashboard.cli.reset_workspace --workspace /absolute/path --confirm`.
- The command refuses missing confirmation, symlinked workspace roots, paths outside the selected workspace, active service locks, and unknown deletion targets.

- [ ] **Step 1: Write failing reset tests.** Build a temporary workspace containing each approved generated target plus sentinel source files. Assert missing confirmation and active lock refusal, then assert confirmed reset deletes only the target list and writes `reset-record.json`.
- [ ] **Step 2: Run the focused test.** Run `dashboard/.venv/bin/python -m pytest tests/dashboard/integration/test_reset_workspace.py -q`. Expected: FAIL because the command does not exist.
- [ ] **Step 3: Implement bounded deletion.** Use an explicit tuple of workspace-relative targets: `runs/`, `jobs.sqlite3`, `jobs.sqlite3-wal`, `jobs.sqlite3-shm`, `mapping_drafts/`, `bonded_states/`, `model_registry/`, `compositions/`, and configured generated report directories only when they are under the selected workspace. Do not recurse from the project root or remove upload/source inputs unless they are explicitly added to a future approved reset boundary.
- [ ] **Step 4: Recreate runtime directories and record the reset.** Create empty workspace directories, write a reset record atomically, and return a structured report suitable for CLI output.
- [ ] **Step 5: Run reset and workspace tests.** Run `dashboard/.venv/bin/python -m pytest tests/dashboard/integration/test_reset_workspace.py tests/dashboard/integration/test_workspace_migration.py tests/dashboard/unit/test_store.py -q`. Expected: PASS or remove obsolete migration tests as specified by the clean-break plan.
- [ ] **Step 6: Run GitNexus impact and commit.** Run impact for `Paths`, `default_paths`, and `Store`, then `detect-changes`. Commit with `git commit -m "feat: add bounded fresh-workspace reset"`.

### Task 6: Verify the Persistence Spec

**Files:**
- Modify: `docs/PROJECT_GUIDE.md`
- Modify: `README.md`
- Modify: `dashboard/README.md`

- [ ] **Step 1: Document the SQLite-only workspace.** Remove live `jobs.json` and migration instructions, document the reset command, and state the exact recovery/backup boundary.
- [ ] **Step 2: Run static persistence scans.** Run `rg -n "jobs\.json|imported|Store\([^)]*legacy|import_legacy_job|database\(\)" dashboard tests docs README.md` and classify every remaining hit.
- [ ] **Step 3: Run the persistence suite.** Run `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_store.py tests/dashboard/unit/test_json_repository.py tests/dashboard/unit/test_analysis_coordinator.py tests/dashboard/integration/test_reset_workspace.py tests/dashboard/integration/test_aa_api.py tests/dashboard/integration/test_operations.py -q`.
- [ ] **Step 4: Run GitNexus detection and commit.** Run `detect-changes --scope all --repo .`, then commit with `git commit -m "docs: describe the SQLite workspace"`.
