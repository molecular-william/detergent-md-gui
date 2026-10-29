# Repository Cleanup and Readability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove obsolete generated and compatibility material and make execution, analysis, and model HTTP code readable while preserving the new API and scientific semantics.

**Architecture:** Cleanup is bounded by explicit paths and a reset record. Compatibility-only routes/imports are deleted after graph and text checks. Readability refactors introduce named helpers at existing ownership boundaries rather than new services.

**Tech Stack:** Python 3.13, Flask, pathlib, JavaScript modules, pytest, Playwright, GitNexus.

**Spec:** `docs/superpowers/specs/2026-09-21-repository-cleanup-readability-design.md`

## Global Constraints

- Cleanup is path-contained, symlink-safe, explicit, and auditable.
- No source, reference, resource, test, or paused-package file is deleted by runtime cleanup.
- New routes reject malformed payloads before model code runs.
- Route handlers never expose paths outside configured workspace or canonical roots.
- Browser state uses one current key namespace and schema.
- Analysis preserves units, source identity, missing values, and the scientific-validation boundary.

### Task 1: Normalize Generated-File Boundaries

**Files:**
- Modify: `.gitignore`
- Modify: `dashboard/README.md`
- Modify: `README.md`
- Create: `tests/dashboard/unit/test_generated_paths.py`

- [ ] **Step 1: Inventory generated paths.** Run `find` for `.ipynb_checkpoints`, `__pycache__`, `.pytest_cache`, runtime workspaces, and local virtual environments. Record only generated paths that are inside the approved reset boundary.
- [ ] **Step 2: Write failing path-policy tests.** Assert that the reset target list includes runtime state and checkpoints but excludes `molecules/`, `references/`, `resources/`, `tests/`, `docs/`, and `micelle/`.
- [ ] **Step 3: Correct `.gitignore`.** Ignore Python caches, notebook checkpoints, local virtual environments, SQLite sidecars, workspace runtime directories, and generated reports without hiding canonical source assets that should be versioned.
- [ ] **Step 4: Document the boundary.** Add one current cleanup/reset section and remove duplicated obsolete cleanup instructions.
- [ ] **Step 5: Run tests and static checks.** Run `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_generated_paths.py -q` and `git check-ignore -v dashboard/__pycache__ dashboard/.ipynb_checkpoints dashboard/jobs.sqlite3-wal`. Expected: PASS and all generated paths ignored.
- [ ] **Step 6: Run GitNexus detection and commit.** Run `detect-changes --scope all --repo .`, then commit with `git commit -m "chore: define generated file boundaries"`.

### Task 2: Remove Legacy HTTP Routes and Browser Fallbacks

**Files:**
- Modify: `dashboard/web/routes/runs.py`
- Modify: `dashboard/web/static/js/runs.js`
- Modify: `dashboard/web/static/js/mappings.js`
- Modify: `dashboard/web/static/js/shared.js`
- Modify: `dashboard/web/static/js/tabs.js`
- Modify: `tests/dashboard/browser/test_dashboard_browser.py`
- Modify: `tests/dashboard/browser/test_new_run_state.py`
- Modify: `tests/dashboard/browser/test_candidate_selection_browser.py`

**Interfaces:**
- Current routes remain `/`, `/api/jobs`, `/api/jobs/<id>`, `/api/jobs/<id>/log`, and the current model/analysis endpoints.
- `/history`, `/run/<id>`, and `/console/<id>` are removed.
- Browser persistence uses only the current `ddm.` key namespace and current resource keys; numeric legacy detail keys are removed.

- [ ] **Step 1: Run GitNexus and text impact checks.** Query the route functions and search templates/tests for the aliases and legacy browser keys. Treat unresolved dynamic strings as explicit review items.
- [ ] **Step 2: Write failing route tests.** Assert old aliases return 404 and current routes retain their existing response shapes. Assert the browser no longer reads numeric fallback keys.
- [ ] **Step 3: Delete aliases and fallbacks.** Remove redirect handlers and legacy client fallback branches. Keep path containment and artifact authorization unchanged.
- [ ] **Step 4: Run route and browser tests.** Run `dashboard/.venv/bin/python -m pytest tests/dashboard/integration/test_operations.py tests/dashboard/browser/test_dashboard_browser.py tests/dashboard/browser/test_new_run_state.py tests/dashboard/browser/test_candidate_selection_browser.py -q`.
- [ ] **Step 5: Run GitNexus detection and commit.** Confirm only route/client/test files changed and commit with `git commit -m "refactor: remove legacy dashboard entry points"`.

### Task 3: Add Explicit HTTP Request Helpers

**Files:**
- Modify: `dashboard/web/routes/common.py`
- Modify: `dashboard/web/routes/models.py`
- Modify: `dashboard/web/routes/molecules.py`
- Modify: `dashboard/web/routes/analyses.py`
- Create: `tests/dashboard/unit/test_route_helpers.py`
- Modify: `tests/dashboard/integration/test_mapping_exports.py`
- Modify: `tests/dashboard/integration/test_performance_api.py`

**Interfaces:**
- `json_object(*, required: bool = True) -> dict` rejects non-object JSON with HTTP 400.
- `molecule_context(payload: dict, *, require_molecule: bool = False) -> dict | None` resolves and verifies the current snapshot.
- `translate_model_error(error: Exception, *, missing: int = 404, conflict: int = 409) -> NoReturn` maps domain errors at the HTTP boundary.

- [ ] **Step 1: Write failing helper tests.** Cover missing JSON, list payloads, missing schema-3 molecule IDs, stale snapshots, invalid IDs, and domain conflicts.
- [ ] **Step 2: Run the focused test.** Run `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_route_helpers.py -q`. Expected: FAIL because helpers do not exist.
- [ ] **Step 3: Implement helpers in `common.py`.** Keep Flask-specific abort behavior in the route layer and avoid importing model modules into the generic helper module.
- [ ] **Step 4: Migrate model/molecule/analysis routes.** Replace repeated payload/context/exception blocks with helpers while preserving endpoint paths, fields, and status codes in the clean-break contract.
- [ ] **Step 5: Run route tests.** Run `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_route_helpers.py tests/dashboard/integration/test_mapping_exports.py tests/dashboard/integration/test_performance_api.py tests/dashboard/browser/test_candidate_selection_browser.py -q`.
- [ ] **Step 6: Run GitNexus impact and commit.** Run impact for `_payload_context`, `_query_context`, `mapping_list`, `bonded_state_patch`, and `readiness_api`, then `detect-changes`. Commit with `git commit -m "refactor: centralize route validation"`.

### Task 4: Refactor Dense Analysis and Execution Helpers

**Files:**
- Modify: `dashboard/analysis/worker.py`
- Modify: `dashboard/analysis/observability.py`
- Modify: `dashboard/analysis/surfaces.py`
- Modify: `dashboard/analysis/aa_references.py`
- Modify: `dashboard/execution/workflow.py`
- Modify: `dashboard/execution/cg_adapter.py`
- Modify: `dashboard/execution/temporary.py`
- Create: `tests/dashboard/unit/test_analysis_helpers.py`
- Modify: `tests/dashboard/integration/test_analysis_display.py`

**Interfaces:**
- `analysis.source_entries(root, kind) -> dict[str, Path]` remains the source-selection API.
- New private helpers have single responsibilities: `read_xvg_values`, `build_source_fingerprint`, `publish_analysis_output`, `record_stage_entry`, and `validate_required_outputs`.
- Existing result JSON fields, units, missing-value behavior, and source hashes remain unchanged.

- [ ] **Step 1: Write characterization tests.** Capture current behavior for XVG parsing, missing values, source fingerprint changes, immutable output publication, stage-entry creation, and required-output failures.
- [ ] **Step 2: Run characterization tests.** Run `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_analysis_helpers.py tests/dashboard/integration/test_analysis_display.py -q`. Expected: new tests pass against the current behavior before refactoring.
- [ ] **Step 3: Extract source/fingerprint helpers.** Replace dense comprehensions and inline hashes in `analysis/worker.py` with named functions and typed return values.
- [ ] **Step 4: Extract numeric/report parsers.** Move XVG value reading, finite-value checks, and report assembly out of long route/analysis blocks without changing error policy.
- [ ] **Step 5: Extract stage record helpers.** Make stage-entry construction, dependency hashes, output verification, and finalization explicit in `workflow.py`.
- [ ] **Step 6: Run analysis and execution tests.** Run `dashboard/.venv/bin/python -m pytest tests/dashboard/unit tests/dashboard/integration/test_analysis_display.py tests/dashboard/integration/test_operations.py -q`.
- [ ] **Step 7: Run GitNexus detection and commit.** Run impact for `analysis.worker.execute`, `workflow.run`, `observability.sasa_plot`, and `surfaces.connolly_surfaces`, then `detect-changes`. Commit with `git commit -m "refactor: clarify analysis and stage helpers"`.

### Task 5: Remove Compatibility-Only Source and Checkpoint Files

**Files:**
- Delete: `dashboard/execution/ddm.py`
- Delete: all tracked `**/.ipynb_checkpoints/**` files if present after reset
- Modify: `tests/dashboard/browser/test_candidate_selection_browser.py`
- Modify: `tests/dashboard/integration/test_candidate_selection.py`
- Modify: `docs/PROJECT_GUIDE.md`
- Modify: `docs/DDM_CALIBRATION.md`

- [ ] **Step 1: Verify the deletion set.** Run `rg -n "dashboard\.execution\.ddm|\.ipynb_checkpoints|legacy route|jobs\.json|execution_root" dashboard tests docs README.md` and classify every hit as maintained, historical, or delete-target.
- [ ] **Step 2: Update maintained references.** Replace direct shim imports and current documentation references; leave scientific historical reports only when they are not part of the fresh runtime.
- [ ] **Step 3: Delete compatibility-only files.** Remove the shim and generated checkpoints from the maintained tree. Do not delete canonical scientific assets or source files outside the approved reset list.
- [ ] **Step 4: Run static scans.** Run `rg -n "dashboard\.execution\.ddm|/history|/run/<|/console/<|jobs\.json|execution_root|\.ipynb_checkpoints" dashboard tests docs README.md`. Expected: no maintained-code hits.
- [ ] **Step 5: Run GitNexus detection and commit.** Confirm deleted symbols have no unresolved callers, then commit with `git commit -m "chore: remove compatibility-only files"`.

### Task 6: Verify the Clean Repository

**Files:**
- Modify: `README.md`
- Modify: `dashboard/README.md`
- Modify: `docs/PROJECT_GUIDE.md`
- Modify: `docs/DDM_CALIBRATION.md`

- [ ] **Step 1: Consolidate current documentation.** Link the three specs and plans, describe the fresh SQLite workspace, and remove duplicated legacy/migration claims.
- [ ] **Step 2: Run Python and JavaScript syntax checks.** Run `dashboard/.venv/bin/python -m compileall -q dashboard tests` and `for f in dashboard/web/static/js/*.js; do node --check "$f"; done`.
- [ ] **Step 3: Run the fast non-browser suite.** Run `dashboard/.venv/bin/python -m pytest -m 'not browser and not slow' -q`.
- [ ] **Step 4: Run browser verification.** Run `dashboard/.venv/bin/python -m pytest -m browser -q` against the fresh workspace.
- [ ] **Step 5: Run final GitNexus analysis.** Run `node .gitnexus/run.cjs analyze --index-only`, then `node .gitnexus/run.cjs detect-changes --scope all --repo .`; repeat if `partial` or `truncated` is reported.
- [ ] **Step 6: Commit documentation and verification updates.** Commit with `git commit -m "docs: document the clean-break repository"` only after the verification commands pass.
