# Sucrose Diagnostic Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make sucrose validation controls populate, provide a reproducible provisional sucrose AA-to-CG diagnostic run path, and publish paper-inspired geometry/SASA plots without claiming scientific validation.

**Architecture:** Keep the existing molecule discovery, staged AA/CG coordinator, immutable analysis worker, and mapping store. Repair the reserved validation routes at the HTTP boundary, add a molecule-scoped provisional mapping through the existing automatic preview/save path, and extend carbohydrate analysis metadata/reporting to expose the existing surface comparison artifact and geometry summaries.

**Tech Stack:** Flask, Python, pytest, GROMACS/MDAnalysis/Plotly when available, native dashboard JavaScript.

**Spec:** Approved in chat on 2026-09-24; see `docs/research/2026-09-24-carbohydrate-validation-operations.md` for the scientific protocol boundary.

## Global Constraints

- Preserve immutable run and analysis artifacts; never overwrite source trajectories.
- Setup and short diagnostic runs remain `scientifically_validated: false`.
- Use the official Martini 3 sugar topology as provenance; mark sucrose mapping assumptions as provisional.
- Do not make transfer-free-energy or osmotic-pressure evidence complete without target-backed paper-scale inputs.

### Task 1: Refresh the Validation API Process

**Files:**
- Documentation: `docs/research/2026-09-24-carbohydrate-validation-operations.md`

- [x] Verify a fresh app instance returns `/api/mappings/representations` and sucrose validation targets.
- [x] Restart the stale dashboard process so the live UI uses the committed endpoints.
- [x] Verify the live dashboard API returns representation modes and the sucrose dataset.

### Task 2: Add Sucrose Provisional Mapping Workflow

**Files:**
- Test: `tests/dashboard/integration/test_mapping_workspace_api.py`

- [x] Exercise `generate_baseline` against the checked-in sucrose structure and assert the candidate is molecule-scoped and provenance-marked.
- [x] Persist the candidate through the existing draft endpoint; assert it is listed only for sucrose.
- [x] Keep the candidate status provisional and preserve its limitations in the stored document.

### Task 3: Publish Diagnostic Plot Metadata

**Files:**
- No source edits required for the first diagnostic run; existing immutable surface analysis is the plot producer.
- Documentation: `docs/research/2026-09-24-carbohydrate-validation-operations.md`

- [x] Confirm the current worker invokes surface analysis for a completed source run.
- [x] Record the generated HTML comparison and SASA metadata paths in the run report.
- [x] Keep the existing report diagnostic-only for short sampling.

### Task 4: Run and Verify Sucrose Diagnostic Workflow

**Files:**
- Documentation: `docs/research/2026-09-24-carbohydrate-validation-operations.md`

- [x] Validate sucrose AA readiness and GROMACS availability.
- [x] Create a shared AA reference and matching CG diagnostic run using the existing coordinator settings.
- [x] Queue a sucrose `setup` validation attempt and verify the report is diagnostic-only.
- [x] Verify generated plot artifacts and record any unavailable paper-scale evidence as `insufficient_data`.
