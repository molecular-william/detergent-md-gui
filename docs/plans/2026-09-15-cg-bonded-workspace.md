# CG Bonded Workspace Implementation Plan

Status as of 2026-09-16: partially implemented. Before executing this backlog,
read the [current handoff](../../DDM_CALIBRATION.md), especially the code-inspected
editing, overlay, preview, and scoring gaps. This plan is not a completion record.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate reusable bead mappings from versioned bonded states, improve analysis figures and captions, and add safe short CG bonded-state validation to the dashboard.

**Architecture:** Extend the existing Flask/SQLite/workflow system. Keep mapping JSON as the atom-assignment source, add a small bonded-state store and immutable revisions, and make analysis metadata/cache products live inside each run. Add the new UI as focused panels in the existing dashboard rather than introducing another frontend or service.

**Tech Stack:** Python 3, Flask, SQLite, GROMACS, MDAnalysis, NumPy/SciPy, Plotly HTML, browser JavaScript/CSS, pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-15-cg-bonded-workspace-design.md`

## Global Constraints

- Existing run directories, AA references, mappings, and derived outputs are immutable.
- Every job snapshots the exact mapping and bonded-state revision and records hashes, commands, tools, seeds, and stage results.
- Paper ring constraints, virtual sites, exclusions, and canonical assignments stay protected unless an acknowledged expert override is recorded.
- Short validation defaults to 10 ps equilibration plus 100 ps production at 300 K and 8 CPU threads.
- Analysis caches live inside the owning run and use content hashes, not only mtime/size.
- Lower mismatch scores are better; SASA and distribution curves require agreement of mean/shape/variability rather than a universal direction.
- Legacy runs remain readable and receive inferred captions marked as legacy.

---

### Task 1: Establish versioned bonded-state persistence and compatibility

**Files:**
- Create: `dashboard/models/bonded_states.py`
- Modify: `dashboard/store.py`, `dashboard/models/mappings.py`, `dashboard/app.py`
- Test: `dashboard/test_bonded_states.py`

**Interfaces:**
- `bonded_states.create(mapping, source, kind, name) -> dict`
- `bonded_states.revise(state_id, expected_revision, patch, in_place=False) -> dict`
- `bonded_states.resolve(state_id, revision=None) -> dict`
- `bonded_states.references(state_id) -> list[dict]`
- `bonded_states.can_delete(state_id) -> tuple[bool, list[dict]]`

- [ ] Write failing tests for mapping identity mismatch, immutable new revisions, in-place revision pointers, run-reference deletion blocks, and state deletion after dependent jobs are deleted.
- [ ] Add SQLite tables for `bonded_states` and `bonded_state_revisions` with JSON payloads, hashes, current revision, provenance, and timestamps. Use the existing transactional connection and revision pattern.
- [ ] Validate state payloads by calling the existing bonded/topology validators, require a mapping hash, and reject incomplete fitted states when a run requests reuse.
- [ ] Add API endpoints for list/create/revise/resolve/delete and dependency responses. Require confirmation at the UI boundary and transactional reference checks at the API boundary.
- [ ] Add a migration/indexer that discovers fitted `DDM.itp`, `DDM_ff_inter.itp`, and `model.json` artifacts as read-only legacy states without modifying runs.
- [ ] Run `dashboard/.venv/bin/python -m pytest dashboard/test_bonded_states.py -q` and the existing mapping/export tests.

### Task 2: Make workflow intents select mapping plus bonded state

**Files:**
- Modify: `dashboard/app.py`, `dashboard/execution/workflow.py`, `dashboard/analysis/worker.py`
- Create: `dashboard/execution/scripts/promote_validation.py`
- Test: `dashboard/test_bonded_workflow.py`, `dashboard/test_new_run_state.py`

**Interfaces:**
- `workflow.normalize_intent(payload) -> dict` with `fit_and_simulate`, `fit_only`, or `reuse_state`.
- `workflow.prepare_bonded_snapshot(run_dir, mapping, state, intent) -> dict`.
- `app.create_bonded_validation(...) -> job`.

- [ ] Write failing tests showing fit-only stops before CG, reuse skips fitting, incompatible mapping/state/reference blocks launch, and old request payloads map to fit-and-simulate.
- [ ] Add explicit run fields `mapping_id`, `mapping_snapshot`, `bonded_state_id`, `bonded_state_revision`, and `bonded_intent`; retain old fields for compatibility.
- [ ] Update preparation to snapshot the selected state, preserve raw FF output, and run `refine_bonded.py` only for fit intents. Publish a complete fitted state before automatic CG continuation.
- [ ] Make fitting failures terminal before CG and expose diagnostic artifacts without publishing a complete reusable state.
- [ ] Add temporary validation jobs with the 10 ps/100 ps defaults, fresh seed, 300 K, and `-ntmpi 1 -ntomp 8 -nb cpu`. Place artifacts under the owning temporary job's `analysis/bonded-validation` path and prevent them from AA-reference selection.
- [ ] Add promotion and cleanup helpers with active-lease checks, latest-five protection, 7-day successful and 30-day failed expiry for older attempts, and path/symlink validation.
- [ ] Run workflow tests with subprocesses mocked, then one real GROMACS preprocessing validation using a temporary fixture.

### Task 3: Build the CG Bond Interactions page and state-aware bead page

**Files:**
- Modify: `dashboard/web/templates/dashboard.html`, `dashboard/web/static/js/main.js`, `dashboard/web/static/dashboard.css`
- Create: `dashboard/web/static/bonded-editor.js`, `dashboard/web/static/bonded-editor.css`
- Test: `dashboard/test_bonded_editor.py`, `dashboard/test_dashboard_browser.py`

**Interfaces:**
- `BondedEditor.loadMapping(mapping)`, `.loadState(state)`, `.render()`, `.saveAsNew()`, `.editInPlace()`.
- `bondedDiagram.render(mapping, interactions, selection) -> SVG`.

- [ ] Write browser tests for the exact tab order, mapping-only/state selectors, table editing, invalid-save blocking, delete confirmation/dependency message, and desktop/mobile layout.
- [ ] Rename the existing tab to `CG Bead Assignment` and add `CG Bond Interactions` after it. Remove the advanced bonded JSON editor from the bead page while preserving assignment editing.
- [ ] Implement interaction tables with units, function-specific controls, locked constraints, expert override warning, and expandable exact ITP preview.
- [ ] Implement SVG/CSS overlay lines from CG bead centers to assigned AA atoms. Add toggles for bonds, angles, dihedrals, constraints, and virtual links; row/diagram selection highlights the same interaction.
- [ ] Add save-as-new by default and confirmed edit-in-place revision actions. Disable deletion when API reports undeleted dependent runs.
- [ ] Add the short validation button, status/progress/result links, cleanup confirmation, and promotion action.
- [ ] Run browser checks with no console errors, keyboard selection, invalid JSON/parameter cases, and responsive screenshots.

### Task 4: Add authoritative graph metadata, captions, and cached analyses

**Files:**
- Modify: `dashboard/analysis/worker.py`, `dashboard/app.py`, `dashboard/analysis/observability.py`, `dashboard/analysis/surfaces.py`, `dashboard/web/static/js/main.js`, `dashboard/web/static/dashboard.css`, `dashboard/web/templates/dashboard.html`
- Create: `dashboard/analysis_metadata.py`, `dashboard/cache.py`
- Test: `dashboard/test_analysis_metadata.py`, `dashboard/test_analysis_cache.py`, `dashboard/test_figure_viewer.py`

**Interfaces:**
- `analysis_metadata.describe(kind, artifact, stats) -> dict`.
- `cache.key(kind, dependencies) -> str`; `cache.get_or_build(run_dir, key, builder) -> manifest`.
- `surfaces.surface_comparison(run_dir, frame_selection) -> metadata/result`.
- `observability.sasa_timeseries(run_dir, frame_selection) -> metadata/result`.

- [ ] Write failing tests for metric directions/units, legacy-caption inference, frame decimation preserving statistics, cache hit/no builder call, dependency invalidation, and duplicate request deduplication.
- [ ] Emit metadata beside new PNG/SVG/HTML/XVG outputs: title, explanation, ideal result, metric direction, units, frame range/count, source hashes, and algorithm version.
- [ ] Add legacy filename/report classifiers with an explicit `Legacy caption` flag and no fabricated missing values.
- [ ] Extend the figure viewer with kind-specific captions and compact defaults: score matrix about 420 px, interaction/fitted plots about 440 px, surface about 520 px, SASA about 360 px. Preserve zoom and original links.
- [ ] Generate Plotly AA/CG surface overlays from cached meshes/alignment products, including raw/expanded/simulated variants and molecular markers. Cache per run with radius/probe/frame/alignment/algorithm hashes.
- [ ] Add cached full-resolution SASA-over-time traces with 2,000-point display decimation and statistics from every valid frame. Use separate elapsed axes when trajectories are not paired.
- [ ] Ensure analysis requests atomically publish cache manifests, never reuse partial output, and never copy complete trajectories into every cache entry.
- [ ] Run analysis unit tests and the existing figure-viewer browser test against fixture artifacts.

### Task 5: Migration, cleanup, documentation, and end-to-end proof

**Files:**
- Modify: `dashboard/README.md`, `dashboard/analysis/observability.py`, `dashboard/execution/resources.py`
- Create: `dashboard/execution/scripts/migrate_bonded_states.py`, `dashboard/test_migration.py`, `dashboard/test_temporary_validation_cleanup.py`

- [ ] Write migration tests proving existing jobs/artifacts/hashes remain unchanged, imported legacy states are read-only, and rerunning migration is idempotent.
- [ ] Implement the explicit migration command with a backup, schema version, dry-run report, and atomic inserts. Refuse path escapes and malformed topology rather than guessing.
- [ ] Implement daily/startup temporary cleanup with leases, latest-five protection, age cutoffs, audit records, and retryable filesystem failures. Test controlled clock boundaries and active workers.
- [ ] Document state lifecycle, run intents, graph meanings, cache invalidation, temporary retention, and expert constraint overrides.
- [ ] Run focused tests, the full dashboard pytest suite, JavaScript syntax checks, and Playwright desktop/mobile smoke tests.
- [ ] Run one real DDM short validation through the new button/API and verify manifest, 8-thread command, state hash, cached graphs, cleanup protection, and no modification of the selected state or existing runs.

## Execution checkpoints

After Task 1, verify state persistence before touching the UI. After Task 2,
verify old and new run requests with mocked workers. After Task 3, perform the
browser review before adding graph work. After Task 4, verify cache manifests
and figure captions with fixture artifacts. Task 5 is the final migration and
real-run gate; do not delete or overwrite completed simulation directories.
