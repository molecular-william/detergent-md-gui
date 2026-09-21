# Workflow Contract Clean-Break Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AA and AA-to-CG execution use one stage declaration contract, dynamic molecule-aware artifact names, strict current run layout, and truthful fit-only completion.

**Architecture:** `Stage` objects are the only workflow declarations. A shared resolver produces the runtime plan and contracts from stage definitions plus prepared molecule names. The coordinator admits only shared-reference CG runs and the runner executes the selected declared plan.

**Tech Stack:** Python 3.13, dataclasses, pathlib, subprocess, pytest, Flask coordinator integration.

**Spec:** `docs/superpowers/specs/2026-09-21-workflow-contract-clean-break-design.md`

## Global Constraints

- Every selected stage records command, environment, inputs, outputs, hashes, timestamps, exit code, and log path.
- A stage can be reused only when its recorded output hashes verify.
- A completed run has completed every stage in its declared workflow plan.
- A CG run has an identity-checked AA reference before preparation.
- All prepared executable paths stay inside the current run directory.
- Completion never implies scientific validation.
- Do not delete canonical scientific inputs.

### Task 1: Unify Stage Declarations

**Files:**
- Modify: `dashboard/execution/stages.py`
- Modify: `dashboard/execution/aa_workflow.py`
- Modify: `dashboard/execution/cg_adapter.py`
- Modify: `dashboard/execution/workflow.py`
- Create: `tests/dashboard/unit/test_stages.py`

**Interfaces:**
- `Stage.resolve(context: Mapping[str, str]) -> Stage` resolves `{name}` placeholders in `relative`, `inputs`, and `outputs`.
- `stage_tables(stages: tuple[Stage, ...], context: Mapping[str, str] | None = None) -> tuple[plan, inputs, outputs]` returns immutable plan data for current callers.
- `aa_workflow.STAGE_DEFS` and `cg_adapter.STAGE_DEFS` are tuples of `Stage` objects.

- [ ] **Step 1: Write failing contract tests.** Add tests that construct a stage with `{final_itp}`, resolve it with `{'final_itp': 'Molecule.itp'}`, and assert the plan, input map, and output map contain the resolved value. Add a test that missing placeholders raise `ValueError` naming the placeholder.
- [ ] **Step 2: Run the focused test.** Run `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_stages.py -q`. Expected: FAIL because the resolver and shared context argument do not exist.
- [ ] **Step 3: Implement the resolver.** Add the typed context resolver and update both workflow adapters to declare `Stage` tuples. Preserve the existing public derived constants for callers that still need the default, unresolved AA contract.
- [ ] **Step 4: Make runtime stage selection use definitions.** Change `workflow.stage_definitions(metadata)` to select the adapter definition tuple, resolve it from `metadata['cg_names']` when present, and return the derived plan/input/output maps. Remove direct CG tuple/dictionary declarations.
- [ ] **Step 5: Run the focused test and existing workflow tests.** Run `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_stages.py tests/dashboard/unit/test_workflow.py tests/dashboard/integration/test_aa_workflow.py -q`. Expected: PASS.
- [ ] **Step 6: Run GitNexus impact and commit.** Run `node .gitnexus/run.cjs impact "stage_tables" --direction upstream --repo .`, inspect direct callers, then run `node .gitnexus/run.cjs detect-changes --scope all --repo .`. Commit only the task files with `git commit -m "refactor: unify workflow stage contracts"`.

### Task 2: Remove DDM Names from Generic CG Contracts

**Files:**
- Modify: `dashboard/execution/cg_adapter.py`
- Modify: `dashboard/execution/stage_io.py`
- Modify: `dashboard/analysis/worker.py`
- Modify: `dashboard/web/routes/analyses.py`
- Modify: `tests/dashboard/integration/test_draft_execution.py`
- Modify: `tests/dashboard/integration/test_aa_api.py`
- Create: `tests/dashboard/integration/test_dynamic_cg_contract.py`

**Interfaces:**
- `CGNames.env() -> dict[str, str]` remains the source of prepared residue and topology filenames.
- CG stage declarations use `{residue_name}`, `{initial_itp}`, and `{final_itp}` placeholders.
- Diagnostic outputs use molecule-neutral glob patterns; identity-bearing topology outputs use the resolved exact filename.

- [ ] **Step 1: Write failing dynamic-name tests.** Prepare a non-DDM molecule fixture with residue name `MALT` and assert the resolved CG input/output contract requires `MALT_initial.itp` and `MALT.itp`, never `DDM_initial.itp` or `DDM.itp`.
- [ ] **Step 2: Run the new test.** Run `dashboard/.venv/bin/python -m pytest tests/dashboard/integration/test_dynamic_cg_contract.py -q`. Expected: FAIL because CG contracts currently contain DDM literals.
- [ ] **Step 3: Replace literals with placeholders.** Update CG stage definitions and analysis source patterns to use the prepared names. Add one helper for molecule-specific analysis topology paths so analysis and route code do not re-create DDM paths.
- [ ] **Step 4: Validate output checks.** Ensure required-output validation accepts the neutral diagnostic globs but rejects missing resolved topology files. Keep path containment and non-empty-file checks unchanged.
- [ ] **Step 5: Run workflow and analysis tests.** Run `dashboard/.venv/bin/python -m pytest tests/dashboard/integration/test_dynamic_cg_contract.py tests/dashboard/integration/test_draft_execution.py tests/dashboard/integration/test_analysis_display.py -q`. Expected: PASS.
- [ ] **Step 6: Run GitNexus impact and commit.** Run impact for `CGNames`, `stage_definitions`, and `source_entries`, then `detect-changes`. Commit with `git commit -m "refactor: make CG contracts molecule-aware"`.

### Task 3: Make the Current Run Layout Strict

**Files:**
- Modify: `dashboard/execution/stage_io.py`
- Modify: `dashboard/execution/workflow.py`
- Modify: `dashboard/execution/cg_adapter.py`
- Modify: `dashboard/execution/coordinator.py`
- Modify: `dashboard/analysis/worker.py`
- Modify: `dashboard/web/routes/analyses.py`
- Modify: `tests/dashboard/unit/test_workflow.py`
- Modify: `tests/dashboard/integration/test_operations.py`

**Interfaces:**
- `stage_root(run_dir: Path) -> Path` returns `run_dir / 'stages'` and rejects missing or symlinked stage roots.
- `workflow.prepare_run(...)` is the only preparation entry point.
- All runtime and analysis callers use `stage_root`; `execution_root` is removed.

- [ ] **Step 1: Add failing strict-layout tests.** Assert that a run without `stages/` is rejected, a symlinked `stages/` is rejected, and a current run resolves only `run_dir/stages`.
- [ ] **Step 2: Run the focused tests.** Run `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_workflow.py tests/dashboard/integration/test_operations.py -q`. Expected: FAIL while fallback behavior remains.
- [ ] **Step 3: Implement `stage_root`.** Replace fallback behavior with one strict helper. Update preparation, resume, workflow execution, analysis source discovery, analysis routes, and coordinator artifact lookup.
- [ ] **Step 4: Remove legacy preparation functions.** Delete `workflow.prepare`, `cg_adapter.validate_reference`, and the inline DDM preparation branch. Make the coordinator reject CG admission without `shared_reference` and make all prepared manifests layout version 2.
- [ ] **Step 5: Run all execution tests.** Run `dashboard/.venv/bin/python -m pytest tests/dashboard/unit tests/dashboard/integration/test_aa_workflow.py tests/dashboard/integration/test_draft_execution.py tests/dashboard/integration/test_operations.py -q`. Expected: PASS.
- [ ] **Step 6: Run GitNexus impact and commit.** Run impact for `execution_root` and `prepare`, resolve every direct caller, run `detect-changes`, and commit with `git commit -m "refactor: enforce current run layout"`.

### Task 4: Make Fit-Only a Declared Workflow

**Files:**
- Modify: `dashboard/execution/workflow.py`
- Modify: `dashboard/execution/cg_adapter.py`
- Modify: `dashboard/execution/coordinator.py`
- Modify: `dashboard/web/routes/runs.py`
- Modify: `tests/dashboard/integration/test_draft_execution.py`
- Modify: `tests/dashboard/integration/test_aa_api.py`
- Create: `tests/dashboard/unit/test_fit_only_workflow.py`

**Interfaces:**
- `workflow.plan_for(metadata: dict) -> tuple[Stage, ...]` returns the validated selected plan.
- Fit-only metadata declares the prefix through `CG topology (ff_inter)` and contains no later stage entries.
- `workflow.run(...)` executes its selected plan and always finalizes status from the selected plan, without `stop_after`.

- [ ] **Step 1: Write failing fit-only tests.** Assert that fit-only preparation records only the selected stage names, the runner executes exactly those stages, and the root manifest ends `completed` with every listed stage completed.
- [ ] **Step 2: Run the focused test.** Run `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_fit_only_workflow.py -q`. Expected: FAIL because `stop_after` currently breaks a full plan.
- [ ] **Step 3: Implement plan selection.** Add validated plan selection from the run intent, write the selected plan into the prepared manifest, remove `stop_after`, and finalize completion only after the selected plan loop ends.
- [ ] **Step 4: Update admission and projections.** Make job records, manifests, resume checks, and UI workflow stages use the selected plan. Reject unknown or non-prefix plans at preparation.
- [ ] **Step 5: Run fit/reuse and API tests.** Run `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_fit_only_workflow.py tests/dashboard/integration/test_draft_execution.py tests/dashboard/integration/test_aa_api.py tests/dashboard/browser/test_candidate_selection_browser.py -q`. Expected: PASS.
- [ ] **Step 6: Run GitNexus impact and commit.** Run impact for `workflow.run`, `Coordinator.run_job`, and `create_job`, then `detect-changes`. Commit with `git commit -m "fix: make fit-only workflows explicit"`.

### Task 5: Delete Internal Compatibility Surfaces

**Files:**
- Delete: `dashboard/execution/ddm.py`
- Modify: `dashboard/execution/coordinator.py`
- Modify: `dashboard/web/routes/runs.py`
- Modify: `tests/dashboard/integration/test_candidate_selection.py`
- Modify: `tests/dashboard/integration/test_draft_execution.py`
- Modify: `tests/dashboard/browser/test_candidate_selection_browser.py`
- Modify: `tests/dashboard/browser/test_new_run_state.py`

**Interfaces:**
- Maintained code imports `dashboard.execution.cg_adapter` directly.
- Retry and resume use the current run type without checking `ddm-legacy-v1`.
- No maintained caller imports `dashboard.execution.ddm`.

- [ ] **Step 1: Use GitNexus impact before deletion.** Run `node .gitnexus/run.cjs query "dashboard.execution.ddm" --repo .` and text-search only dynamic imports or string references not resolved by the graph.
- [ ] **Step 2: Update direct callers and tests.** Replace shim imports with `cg_adapter` imports and remove legacy workflow-version branches from retry/resume admission.
- [ ] **Step 3: Delete the shim.** Remove `dashboard/execution/ddm.py` only after the import scan is empty.
- [ ] **Step 4: Run the affected tests.** Run `dashboard/.venv/bin/python -m pytest tests/dashboard/integration/test_candidate_selection.py tests/dashboard/integration/test_draft_execution.py tests/dashboard/browser/test_candidate_selection_browser.py tests/dashboard/browser/test_new_run_state.py -q`. Expected: PASS.
- [ ] **Step 5: Run GitNexus change analysis and commit.** Run `detect-changes --scope all --repo .`, confirm the deletion and caller updates, then commit with `git commit -m "refactor: remove DDM compatibility shim"`.

### Task 6: Verify the Workflow Spec

**Files:**
- Modify: `docs/PROJECT_GUIDE.md`
- Modify: `README.md`
- Modify: `docs/DDM_CALIBRATION.md`

- [ ] **Step 1: Update active documentation.** Describe only the current stage contract, shared-reference CG path, strict layout, and explicit fit-only plan. Remove claims that legacy execution paths remain supported.
- [ ] **Step 2: Run static contract scans.** Run `rg -n "execution_root|ddm-legacy-v1|validate_reference|jobs.json|stop_after" dashboard tests docs README.md` and confirm only the planned historical/spec references remain.
- [ ] **Step 3: Run the smallest sufficient workflow suite.** Run `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_stages.py tests/dashboard/unit/test_workflow.py tests/dashboard/integration/test_aa_workflow.py tests/dashboard/integration/test_draft_execution.py tests/dashboard/integration/test_operations.py -q`.
- [ ] **Step 4: Run GitNexus detection and commit.** Run `detect-changes --scope all --repo .`, then commit with `git commit -m "docs: describe the current workflow contract"`.
