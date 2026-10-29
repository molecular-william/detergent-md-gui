# In-place Run Resume Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Resume a terminal run using its original job ID, database row, and run directory while executing the current stage files and retaining prior metadata as auditable history.

**Architecture:** The existing coordinator owns admission, leases, SQLite state, and worker handoff. A focused workflow helper checks the resumable prefix, validates selected/downstream stage directories, journals reversible metadata updates, and updates the same manifest. Existing new-run and legacy copied-resume paths remain separate.

**Tech Stack:** Python 3, Flask, SQLite, filesystem locks/renames, pytest, vanilla JavaScript.

**Spec:** docs/superpowers/specs/2026-09-22-in-place-run-resume-design.md

## Global Constraints

- Preserve job ID, database row, creation timestamp, external references, and immutable inputs/.
- Do not hash or restore current stage files for in-place resume; execute them as found.
- Never delete simulation evidence; preserve current stage directories and archive prior metadata below resume_history/.
- Reject active workers, active analyses, external leases, invalid stages, quota failures, and retained consumers that would be invalidated.
- Keep Retry and Clone as new-run operations; keep existing copied-resume records readable.
- Use TDD: each behavior gets a failing test before production code.
- Run GitNexus impact before each production symbol edit and detect-changes before completion.

---

### Task 1: Establish failing same-run API and workflow tests

**Files:**
- Modify: tests/dashboard/integration/test_aa_api.py
- Modify: tests/dashboard/integration/test_aa_workflow.py
- Modify: tests/dashboard/integration/test_operations.py
- Create: tests/dashboard/integration/test_in_place_resume.py

**Interfaces:**
- Consumes current resume endpoint, Coordinator.run_job, and workflow stage contracts.
- Produces executable acceptance cases for same-ID responses, history, cleanup, rollback, leases, analyses, consumers, and legacy copied resumes.

- [ ] Add a fixture that creates a layout-version-2 AA run with input snapshots, upstream completed outputs, selected/downstream outputs, logs, and stage metadata.
- [ ] Add a test that posts resume and asserts HTTP 200, identical ID, one database row, unchanged created, and unchanged run directory.
- [ ] Add a direct workflow test that resumes from a selected stage, preserves current scripts/MDPs and upstream files, and executes the selected/downstream stages.
- [ ] Add tests for resume_history, distinct attempt log directories, and superseded analysis metadata/files.
- [ ] Add acceptance tests for modified or missing input/upstream files, plus rejection tests for symlinks, active worker/analysis, external lease, retained consumer, and storage/quota admission.
- [ ] Add a failure-injection test for preparation rollback and a restart-recovery test for a leftover journal.
- [ ] Update old resume API assertions from “new attempt” to same-ID behavior while preserving clone/retry new-ID assertions.
- [ ] Run the new tests before implementation and confirm they fail for the old copied-resume behavior.

### Task 2: Implement reversible in-place workflow preparation

**Files:**
- Modify: dashboard/execution/workflow.py
- Test: tests/dashboard/integration/test_in_place_resume.py

**Interfaces:**
- Produces prepare_resume_in_place(run_dir: Path, from_stage: str) -> dict and recover_resume_journal(run_dir: Path, job: dict | None) -> None.
- Reuses stage_definitions, resumable_stages, declared_output_hashes, files.verify, and execution_root.

- [ ] Add GitNexus impact for resumable_stages, prepare_resume, run, and any new helper callers before editing.
- [ ] Use the manifest's completed-stage prefix to validate the requested restart boundary without checksum gates.
- [ ] Validate the selected stage is a resumable prefix boundary and reject malformed or missing stage records before mutation.
- [ ] Create a unique resume_history/<attempt>/ directory and durable resume_journal.json describing original manifest bytes and progress.
- [ ] Validate that selected/downstream stage directories exist and are not symlinks; leave their current files in place.
- [ ] Archive the prior active manifest, stage records, and analysis metadata; mark prior analysis records superseded in the active job metadata while keeping their files.
- [ ] Write the new active manifest with only the completed prefix, incremented resume metadata, and a queued/running-neutral state.
- [ ] Roll back the manifest and journal metadata on pre-commit errors; make recovery idempotent and safe under the run lock.
- [ ] Keep legacy prepare_resume unchanged for jobs with resume_of.

### Task 3: Add same-row persistence and safe coordinator admission

**Files:**
- Modify: dashboard/store.py
- Modify: dashboard/execution/coordinator.py
- Modify: dashboard/web/routes/runs.py
- Test: tests/dashboard/integration/test_in_place_resume.py

**Interfaces:**
- Produces Store.resume or an equivalent transactional update that validates dependencies and updates one existing job row.
- Produces a coordinator method for in-place resume admission and worker scheduling.

- [ ] Add GitNexus impact for Coordinator.reconcile, Coordinator.run_job, Coordinator.public_job, Coordinator.log_path, and route callers before editing.
- [ ] Add a transactional store operation that checks the run still has terminal status, has no retained consumer that depends on mutable outputs, and updates the same row to queued with cleared terminal fields, resume_count, resume_from, and request timestamp.
- [ ] Acquire the existing run lease while checking resumability, active analyses, external workers, source/reference dependencies, resource headroom, and preparing the journaled stage reset.
- [ ] Start exactly one worker for the existing ID; return HTTP 200. Ensure duplicate requests see the worker/status guard and cannot queue a second worker.
- [ ] Update run_job to recognize the in-place marker, reuse the existing run directory, acquire its lease, avoid mkdir, avoid replacing the manifest, and execute the prepared active plan.
- [ ] Keep normal new runs and legacy copied resumes on their current preparation paths.
- [ ] Update finalization and reconciliation messages so interrupted in-place resumes remain resumable under the same ID and never signal old PIDs.
- [ ] Ensure artifact cache/log paths and nested log archives retain historical and current paths without overwriting history.

### Task 4: Mark analyses and public projections consistently

**Files:**
- Modify: dashboard/execution/analysis_coordinator.py
- Modify: dashboard/execution/coordinator.py
- Modify: dashboard/web/static/js/runs.js
- Modify: dashboard/web/templates/dashboard.html if copy is server-rendered
- Test: tests/dashboard/integration/test_in_place_resume.py
- Test: tests/dashboard/browser/test_dashboard_browser.py if browser dependencies are available

**Interfaces:**
- Consumes the same job ID and manifest history.
- Produces current-vs-superseded analysis filtering, same-card status transitions, and accurate resume wording.

- [ ] Exclude superseded analyses from dependency resolution and duplicate-signature reuse while keeping their files and artifact links inspectable.
- [ ] Keep active analyses as a resume blocker and expose a clear terminal error.
- [ ] Change the browser notice to “Run resumed; current stage files will be executed.”
- [ ] Keep the same card and console selection when polling the resumed row; do not add a new option.
- [ ] Add or adjust browser assertions for same ID and queued/running transition when the endpoint is stubbed.

### Task 5: Update documentation and run full focused verification

**Files:**
- Modify: docs/PROJECT_GUIDE.md
- Modify: docs/DDM_CALIBRATION.md only if resume wording is present
- Test: focused integration/unit/browser commands

- [ ] Document Resume as same-run continuation; contrast Retry and Clone as new runs; document metadata history, current-file execution, and analysis invalidation.
- [ ] Run focused workflow/API/operations tests, browser resume acceptance when available, shell/Python checks, and git diff --check.
- [ ] Refresh GitNexus index and run detect-changes --scope all --repo .; inspect HIGH/CRITICAL/UNKNOWN results and confirm dynamic route/thread callers by text search.
- [ ] Report any pre-existing unrelated failures separately; do not claim full-suite success without fresh full-suite output.
