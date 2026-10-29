# CG Bond Interactions Editor Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the CG Bond Interactions editor with a five-action, Plotly 3D, bead-selection workflow that edits functions and parameters, generates reference-informed bonded drafts, and saves immutable new states.

**Architecture:** Keep `bonded_states` as the authoritative immutable JSON store and keep Flask routes responsible for snapshot validation and request shaping. Add one model module that parses reference bond terms and builds validated topology drafts, extend the existing bonded parser for function edits, and make the browser controller manage only draft state while a small Plotly adapter owns 3D rendering and selection.

**Tech Stack:** Flask, existing JSON repository and bonded topology helpers, Python standard library, installed Plotly JavaScript bundle, browser ES modules, Playwright, pytest.

**Spec:** `docs/superpowers/specs/2026-09-21-cg-bond-interactions-redesign-design.md`

## Global Constraints

- Mapping and molecule snapshots are validated server-side before generation or save.
- Saved bonded states are immutable by default; this page always saves a new state.
- Interaction functions and parameters are validated in the model layer, not trusted from browser controls.
- Reference files are read-only, indexed deterministically, and recorded with SHA-256 provenance.
- Plotly is served locally from the installed package; no CDN dependency is introduced.
- Generated parameters remain hypotheses and do not imply scientific validation.
- Existing short-run coordinator guards, deletion guards, and legacy state APIs remain intact.
- Run GitNexus impact before editing existing symbols and `detect-changes --scope all` before each implementation commit.

---

## File map

- Create `dashboard/models/bonded_generation.py` for reference bond indexing, deterministic automatic terms, and generic mapping-to-topology assembly.
- Modify `dashboard/models/bonded.py` to expose editable-term metadata and apply function plus parameter updates while preserving the existing parameter-only helper.
- Modify `dashboard/models/bonded_states.py` to pass the new interaction edit payload through revision creation without changing legacy callers.
- Modify `dashboard/web/routes/models.py` to expose automatic draft generation, term-based state creation, and the local Plotly asset.
- Modify `dashboard/web/templates/dashboard.html` to render the five actions, editable table host, and Plotly host.
- Modify `dashboard/web/static/js/bonded.js` to manage mapping/state selection, draft terms, actions, table editing, and save-as-new flow.
- Create `dashboard/web/static/js/bonded-plot.js` to render the `scatter3d` scene and cap bead selection at two.
- Modify `dashboard/web/static/dashboard.css` for the new responsive editor/table/plot layout and remove obsolete bonded SVG/editor rules.
- Modify `tests/dashboard/unit/test_bonded.py` and create `tests/dashboard/unit/test_bonded_generation.py` for parser and generator behavior.
- Modify `tests/dashboard/integration/test_performance_api.py` or add a focused bonded API test module for generation, term saves, and function edits.
- Modify `tests/dashboard/browser/test_bonded_workspace_browser.py` and `tests/dashboard/browser/test_figure_viewer.py` for the new toolbar and Plotly workflow.
- Modify `docs/PROJECT_GUIDE.md` to describe the five actions, draft lifecycle, and reference-informed automatic generation.

## Task 1: Add deterministic reference-informed topology generation

**Files:**
- Create: `dashboard/models/bonded_generation.py`
- Test: `tests/dashboard/unit/test_bonded_generation.py`
- Inspect before editing: `dashboard/models/sugar_topology.py`, `dashboard/models/draft_model.py`, `dashboard/models/mapping_context.py`, and the reference `.itp` files.

**Interfaces:**
- `reference_bond_index(project_root: Path) -> dict` returns `{version, sources, bonds, diagnostics, index_sha256}`. Each bond record contains unordered bead types, function, numeric parameters, source rank, relative path, line number, and source SHA-256.
- `generate(mapping: dict, structure: dict, project_root: Path) -> dict` returns `{topology, interactions, provenance, diagnostics}` without writing files.
- `topology_from_terms(mapping: dict, structure: dict, terms: list[dict], *, title: str) -> str` validates term bead names and produces a complete ITP text with `[moleculetype]`, `[atoms]`, `[bonds]`, derived `[angles]`, mapping ring constraints/virtual sites where applicable, and no invented dihedrals.

- [ ] **Step 1: Write reference parser tests with a temporary reference tree.** Create a tiny ITP containing `[atoms]` and `[bonds]`, a second file with the same type pair and different values, and assert that `reference_bond_index()` normalizes the pair, records both source hashes/locators, and chooses the deterministic most frequent record. Add a malformed ITP and assert it appears in diagnostics without aborting the index.

- [ ] **Step 2: Run the focused test to verify the new module is absent.**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_bonded_generation.py -q`

Expected: collection failure because `dashboard.models.bonded_generation` is not implemented.

- [ ] **Step 3: Implement safe reference indexing.** Scan only regular, non-symlink `.itp` files below the project `references/` directory. Parse `moleculetype`, `atoms`, and `bonds`; skip comments and preprocessor lines; require finite numeric function parameters; rank sources by relative path order and retain line numbers. Hash every accepted source with `dashboard.files.sha256` or `hashlib.sha256`, then hash the canonical JSON payload with sorted keys.

- [ ] **Step 4: Add topology-generation tests.** Use `tests.dashboard.fixtures.physical_mapping()` and a small explicit structure to assert that an exact reference pair produces a bond with the reference length/force/function and provenance, while an unknown pair produces a geometry-length fallback with a fallback diagnostic. Assert connected triples produce one angle, duplicate terms are rejected, virtual-site parents remain present, and no file is written.

- [ ] **Step 5: Implement structure normalization and topology assembly.** Accept both the rich mapping context shape (`bonds` dictionaries) and the packaged legacy structure shape (`bonds` pairs). Compute physical bead COGs in nm from assigned atom coordinates, place virtual sites at parent means, infer physical edges only when `mapping.connections` is absent, and emit contiguous bead IDs. Reuse `sugar_topology.topology()` for mappings with ring definitions, then replace only flexible bond values; use the generic builder for other mappings. Validate every term against physical bead names, arity, finite values, allowed function, and duplicate orientation.

- [ ] **Step 6: Implement the automatic algorithm.** For each mapping connection, match unordered bead-type pairs in the reference index, select the most frequent exact `(function, parameters)` record with deterministic tie-breaks, or use COG distance/function 1/provisional force `5000` with a fallback marker. Derive graph angles from COG geometry using function 1 and force `25`. Return parser-compatible interaction records plus algorithm version, index hash, source hashes, selected reference locators, and diagnostics.

- [ ] **Step 7: Run the focused unit suite and commit.**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_bonded_generation.py tests/dashboard/unit/test_carbohydrates.py -q`

Expected: all focused tests pass.

Run: `node .gitnexus/run.cjs detect-changes --scope all --repo .`

Expected: the changed model symbols are reported with no partial/truncated result. Commit as `feat: add reference-informed bonded draft generation`.

## Task 2: Make bonded function edits server-validated

**Files:**
- Modify: `dashboard/models/bonded.py:15-119`
- Modify: `dashboard/models/bonded_states.py:92-117`
- Test: `tests/dashboard/unit/test_bonded.py` and `tests/dashboard/unit/test_bonded_states.py`

**Interfaces:**
- `parse_interactions(topology)` continues returning `kind`, `indices`, `beads`, `function`, `parameters`, and `id`; it additionally returns `editable` and parameter-label metadata for ordinary terms.
- `apply_interaction_edits(topology: str, updates: list[dict]) -> str` accepts `{id, function, parameters}` and rewrites the matching section row while preserving comments and unrelated rows.
- `apply_interaction_parameters(topology, updates)` remains a compatibility wrapper that calls the new helper with the existing function number.
- `bonded_states.revise()` accepts `interaction_edits` in addition to legacy `interaction_parameters` and always validates the resulting topology before persistence.

- [ ] **Step 1: Add parser/edit tests.** Assert labels and editability for bonds, angles, dihedrals, constraints, and virtual sites. Add tests that change a bond function/values, reject unknown IDs, reject disallowed function/parameter counts, reject nonfinite values, and preserve an inline comment and virtual-site row.

- [ ] **Step 2: Run the focused tests to capture the current failure.**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_bonded.py tests/dashboard/unit/test_bonded_states.py -q`

Expected: new function-edit assertions fail against the parameter-only implementation.

- [ ] **Step 3: Implement the shared function specification.** Define the exact existing allow-list: bonds `{1: 2}`, angles `{1: 2, 2: 2, 10: 2}`, and dihedrals `{1: 3, 2: 2, 9: 3}`. Add stable labels for each parameter based on section/function. Keep `parse_interactions()` output backward compatible for callers that only read the original fields.

- [ ] **Step 4: Implement `apply_interaction_edits()`.** Parse section rows with the same IDs as `parse_interactions()`, validate update IDs, function integers, finite numeric parameters, counts, and section-specific ranges, then replace `fields[:width] + function + parameters` while preserving the original comment suffix. Reject updates targeting constraints or virtual sites.

- [ ] **Step 5: Wire revisions through `bonded_states.revise()`.** Pop `interaction_edits`, call `apply_interaction_edits()` on the current topology, then apply ordinary patch fields and existing mapping/status checks. Translate legacy `interaction_parameters` updates into edits that retain each parsed term's function. Keep expected-revision conflicts and save-as-new parent metadata unchanged.

- [ ] **Step 6: Run unit tests and commit.**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_bonded.py tests/dashboard/unit/test_bonded_states.py -q`

Expected: all tests pass, including the legacy parameter-only test.

Run: `node .gitnexus/run.cjs detect-changes --scope all --repo .`

Expected: no partial/truncated result. Commit as `feat: validate bonded function edits`.

## Task 3: Add generation, term-save, and local Plotly API routes

**Files:**
- Modify: `dashboard/web/routes/models.py:1-187`
- Test: create `tests/dashboard/integration/test_bonded_api.py`

**Interfaces:**
- `POST /api/bonded-states/automatic` accepts a mapping snapshot and returns the nonpersistent result from `bonded_generation.generate()`.
- `POST /api/bonded-states` continues accepting `topology`; when `interactions` is supplied it resolves the validated molecule context, calls `topology_from_terms()`, and creates the state with provenance.
- `PATCH /api/bonded-states/<state_id>` accepts `patch.interaction_edits`, `expected_revision`, and `in_place`; existing callers remain valid.
- `GET /api/assets/plotly.min.js` returns the installed Plotly package bundle with JavaScript MIME type, or a clear 503 response when the package is unavailable.

- [ ] **Step 1: Add API tests for the automatic draft.** Submit a valid mapping with its current snapshot, assert the response has topology, interactions, provenance, and no new state file. Submit a changed snapshot and assert HTTP 409. Submit an invalid mapping and assert HTTP 400.

- [ ] **Step 2: Add API tests for term saves and function edits.** POST a mapping plus one bond term, assert a complete state is created with matching mapping hash and parsed interaction. PATCH it with `in_place: false` and a function/parameter update, assert a new state ID and unchanged source file bytes. Assert stale expected revision returns HTTP 409.

- [ ] **Step 3: Run the focused API tests before implementation.**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/integration/test_bonded_api.py -q`

Expected: failures for the new endpoint and term payload until the routes are added.

- [ ] **Step 4: Add the automatic route with the existing `_payload_context()` trust boundary.** Validate schema-3 snapshots against canonical molecule files. Preserve compatibility for legacy packaged DDM mappings by using the existing packaged structure when no molecule binding is present. Pass the coordinator project root to `bonded_generation.generate()` and return JSON without persistence.

- [ ] **Step 5: Extend state creation for interaction terms.** If `interactions` is present, require a list, resolve the molecule structure, build topology server-side, and store `source` provenance plus `status='complete'`. Keep the existing explicit-topology path untouched for coordinator-created fit states.

- [ ] **Step 6: Add the local Plotly asset endpoint.** Resolve `plotly/package_data/plotly.min.js` through Python package metadata, reject symlinked/missing package files, and use `send_file()` with a fixed MIME type. Do not accept a filesystem path from the request.

- [ ] **Step 7: Run focused API and existing persistence tests, then commit.**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/integration/test_bonded_api.py tests/dashboard/integration/test_performance_api.py tests/dashboard/unit/test_bonded_states.py -q`

Expected: all selected tests pass.

Run: `node .gitnexus/run.cjs detect-changes --scope all --repo .`

Expected: no partial/truncated result. Commit as `feat: expose bonded draft and plotly APIs`.

## Task 4: Implement the Plotly 3D adapter

**Files:**
- Create: `dashboard/web/static/js/bonded-plot.js`
- Modify: `dashboard/web/templates/dashboard.html:10,129-138`
- Modify: `dashboard/web/static/dashboard.css` bonded workspace rules
- Test: browser assertions in `tests/dashboard/browser/test_bonded_workspace_browser.py`

**Interfaces:**
- `mountBondedPlot(host, {onBeadSelection, onTermSelection, onPlotError}) -> {render, destroy}`.
- `render({beads, edges, terms, selectedBeads, selectedTermId})` uses `Plotly.react()` and never mutates mapping data.
- Bead `customdata` contains stable bead names; interaction trace `customdata` contains parser IDs.

- [ ] **Step 1: Add template and asset-loader markup.** Load `/api/assets/plotly.min.js` before the module entry point. Replace the SVG diagram host with a Plotly host, add a two-bead selection status element, and remove the old SVG legend text.

- [ ] **Step 2: Implement the adapter's coordinate and trace contract.** Build one `scatter3d` marker/text trace for physical beads, one line trace per mapping edge, and one line trace per interaction. Use stable colors for normal, selected, and fallback terms; configure responsive camera, axes titles, hover labels, and bounded height.

- [ ] **Step 3: Implement selection events.** On `plotly_click`, distinguish bead and interaction customdata. Toggle bead names in insertion order; if a third bead is selected, remove the oldest and call `onBeadSelection()` with the remaining two. Call `onTermSelection()` for interaction traces. Catch missing `window.Plotly` and call `onPlotError()` without throwing into the page.

- [ ] **Step 4: Add CSS for the plot and responsive columns.** Keep the interaction table and plot usable at desktop and mobile widths, avoid horizontal overflow, and remove obsolete `.bonded-svg`, `.aa-link`, and SVG-specific rules.

- [ ] **Step 5: Run JavaScript syntax checks and the existing browser test that loads the dashboard.**

Run: `node --check dashboard/web/static/js/bonded-plot.js`

Expected: syntax check passes; the browser test can load the page without `pageerror`.

## Task 5: Replace the bonded workspace controller and table editor

**Files:**
- Modify: `dashboard/web/static/js/bonded.js`
- Modify: `dashboard/web/static/js/mappings.js:7,263`
- Modify: `dashboard/web/templates/dashboard.html:130-138`
- Modify: `dashboard/web/static/dashboard.css`
- Test: `tests/dashboard/browser/test_bonded_workspace_browser.py`

**Interfaces:**
- `setupBondedWorkspace(mappingData, {loadMapping}) -> {mount}` keeps the existing mount entry point; the obsolete `onFit` dependency is removed from this page only.
- Controller draft state is `{mapping, state, terms, selectedBeads, selectedTermId, dirty}`.
- `saveDraft()` posts `interactions` for a mapping-only draft or patches the selected state with `{name, interaction_edits}` and `in_place:false`.

- [ ] **Step 1: Update the template toolbar.** Render exactly the five requested buttons with stable classes: `.bonded-automatic`, `.bonded-create-interaction`, `.bonded-short-run`, `.bonded-save-new`, and `.bonded-delete`. Keep mapping/state selectors and the state-name input. Remove `.bonded-load`, `.bonded-create`, `.bonded-fit`, and `.bonded-revise` buttons and their instructional copy.

- [ ] **Step 2: Replace controller state loading.** Keep mapping-filtered state requests and selected-state loading. On selection, copy parsed interactions into a mutable draft, retain the source revision, compute bead centers/edges from the mapping and molecule context, and render both the table and Plotly adapter. Mapping-only mode starts with existing mapping connections as provisional bond terms.

- [ ] **Step 3: Implement automatic generation.** Disable the button while the request is in flight, post `{mapping}` to `/api/bonded-states/automatic`, replace the local draft with returned terms/topology/provenance, clear bead selection, and enable save. Do not invalidate or mutate the saved-state catalogue until a save occurs.

- [ ] **Step 4: Implement table rendering and editing.** Render section/kind, bead labels, a function `<select>` using the exact allow-list, and labeled numeric inputs from parser metadata. Keep constraints and virtual sites read-only. On edits, update the local term and mark the draft dirty; changing a function resizes the parameter list with blank values only for newly required slots.

- [ ] **Step 5: Implement bead-driven interaction creation.** Enable `.bonded-create-interaction` only for two physical selected beads. Reject an existing unordered bead pair, calculate the COG distance in nm, append a new bond term with function 1 and force 5000, select the new row, and rerender the table/plot.

- [ ] **Step 6: Implement save-as-new and deletion.** Save a mapping-only draft with `POST /api/bonded-states` and its terms; save a selected state with `PATCH` and `in_place:false`. After success invalidate `/api/bonded-states`, reload compatible states, select the new state, and clear dirty state. Keep confirmation and existing delete endpoint behavior.

- [ ] **Step 7: Keep short validation safe.** Disable `.bonded-short-run` when no saved state is selected. Reuse the existing temporary draft-smoke payload and selected state ID; report the queued run ID without changing draft terms.

- [ ] **Step 8: Remove the obsolete `onFit` page dependency and run browser tests.** Keep `new-run.js` fit-only behavior for the New run workflow, but stop passing it into `setupBondedWorkspace`. Assert no legacy button exists, all five requested buttons are present, state filtering remains correct, and no page errors occur.

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/browser/test_bonded_workspace_browser.py tests/dashboard/browser/test_figure_viewer.py -q`

Expected: updated browser tests pass, including mobile overflow checks.

## Task 6: Update documentation and complete verification

**Files:**
- Modify: `docs/PROJECT_GUIDE.md` CG Bond Interactions section
- Modify: `tests/dashboard/browser/test_bonded_workspace_browser.py`
- Modify: `tests/dashboard/browser/test_figure_viewer.py`

- [ ] **Step 1: Update workflow documentation.** Describe the five buttons, local draft lifecycle, two-bead Plotly selection, editable function/units, reference-derived automatic bonds, fallback provenance, and the distinction between execution completion and scientific validation. Remove references to the old create/load/fit/revise toolbar and 2D diagram.

- [ ] **Step 2: Add end-to-end browser assertions.** Seed two mapping-specific states, select each mapping, verify only compatible states appear, click two Plotly bead points through the Plotly event surface, create one interaction, change its function/parameter controls, save as new, and assert the source state remains unchanged. Add a third-point click assertion that the selection count stays at two.

- [ ] **Step 3: Run the smallest complete proof.**

Run:

```bash
dashboard/.venv/bin/python -m pytest tests/dashboard/unit tests/dashboard/integration tests/dashboard/browser -q
node --check dashboard/web/static/js/bonded.js
node --check dashboard/web/static/js/bonded-plot.js
git diff --check
```

Expected: all tests pass, both JavaScript checks pass, and `git diff --check` is clean.

- [ ] **Step 4: Run GitNexus change analysis and review the diff.**

Run: `node .gitnexus/run.cjs detect-changes --scope all --repo .`

Expected: a complete, non-truncated result with no unresolved high/critical risk. Review every changed route/model/browser symbol against the approved spec before committing.

- [ ] **Step 5: Commit the finished implementation.**

```bash
git add dashboard/models dashboard/web dashboard/web/static dashboard/web/templates tests/dashboard docs/PROJECT_GUIDE.md
git commit -m "feat: redesign CG bonded interaction editor"
```

