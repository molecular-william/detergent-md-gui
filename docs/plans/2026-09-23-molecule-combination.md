# Molecule Combination Dashboard Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Molecule Combination panel, immutable composite CG model artifacts, CG-only execution path, and integration with CG Bond Interactions and New Run.

**Architecture:** Keep `compositions.py` as the immutable composition repository and put chemistry/topology construction in a focused `composition_topology.py`. Expose compositions through a read-only CG model catalog so existing mapping and bonded editors can consume them without changing ordinary mapping persistence. Add a separate `composition_workflow.py` contract for CG-only runs; keep the maintained AA-only and AA-to-CG contracts unchanged.

**Tech Stack:** Python 3, Flask, immutable JSON repositories, GROMACS command construction, native ES modules, Plotly, pytest, Playwright/Chrome.

**Spec:** `docs/superpowers/specs/2026-09-23-molecule-combination-design.md`

## Global Constraints

- Original `references/` files remain canonical and are never rewritten.
- Composition records and derived artifacts are immutable; every changed choice creates a new record.
- All 15 Martini sugar residues remain visible, while profile compatibility gates Preview, Save, and Run.
- The first tail recipes are `Linear C1` and `Linear C1/C2 terminal`; tail input is carbon count.
- Linkage profiles are named and reference-backed; no free-form linkage parameters are exposed in Molecule Combination.
- Generated compositions remain `candidate-unvalidated`; execution and screening never promote scientific validation.
- Existing `/api/mappings`, AA-only, and AA-to-CG behavior must remain compatible.
- CG-only runs use `run_type: cg_composition` and never fabricate or require an AA reference.
- Before editing an existing symbol, run GitNexus impact analysis and resolve `UNKNOWN` findings with source search.
- Before each commit, run `node .gitnexus/run.cjs detect-changes --scope all --repo .`, review affected processes, and run `git diff --check`.
- Use test-first development for every behavior change: failing focused test, minimal implementation, focused pass, then broader checks.

## File Map

Create `dashboard/models/composition_topology.py` for sugar fragment parsing, recipe expansion, profile compatibility, index renumbering, deterministic coordinates, merged ITP/GRO output, and topology round trips.

Modify `dashboard/models/compositions.py` to expose catalog, preview, immutable bundle creation, duplicate identity checks, and composition references.

Create `dashboard/models/cg_models.py` for a read-only catalog that normalizes ordinary mapping candidates and composition-backed CG models for shared consumers.

Create `dashboard/execution/composition_workflow.py` for the `cg_composition` stage contract, preparation, readiness, manifests, and stage scripts.

Modify `dashboard/web/routes/models.py` for composition catalog/preview/detail and CG model catalog endpoints. Modify `dashboard/web/routes/runs.py`, `dashboard/execution/workflow.py`, and coordinator dispatch only where needed to accept `cg_composition`.

Modify `dashboard/web/templates/dashboard.html` and `dashboard/web/static/js/main.js` to add the fifth tab. Create `dashboard/web/static/js/compositions.js` and `dashboard/web/static/css/compositions.css` for isolated panel state, Plotly rendering, controls, diagnostics, and responsive layout.

Modify `dashboard/web/static/js/bonded.js` to consume the unified CG model catalog and load composition-backed initial states. Modify `dashboard/web/static/js/new-run.js` and `dashboard/web/static/css/new-run.css` for the explicit CG-only form path.

Add focused unit, integration, and browser tests under `tests/dashboard/` for every boundary listed below.

---

### Task 1: Build the reference catalog, recipes, and linkage profiles

**Files:**
- Create: `dashboard/models/composition_topology.py`
- Test: `tests/dashboard/unit/test_composition_topology.py`
- Test: `tests/dashboard/unit/test_sugar_fragment_catalog.py`

**Interfaces:**
- `load_sugar_catalog(source: Path) -> dict[str, dict]`
- `tail_recipe_catalog() -> list[dict]`
- `linkage_profile_catalog() -> list[dict]`
- `expand_tail(recipe_id: str, carbon_count: int) -> dict`
- `preview_payload(payload: dict, project_root: Path) -> dict`
- `composition_identity(result: dict) -> str`

- [ ] **Step 1: Write failing catalog tests.**

```python
def test_sugar_catalog_contains_all_reference_residues():
    catalog = load_sugar_catalog(PROJECT_ROOT / "references" / "martini_v3.0.0_sugars_v2.itp")
    assert set(catalog) == {
        "GLC", "MAN", "GAL", "FRUF", "LFUC", "LRHA", "RIBF", "XYL",
        "INO", "GLA", "GYN", "NMC", "LAC", "SUCR", "TREH",
    }
    assert catalog["GLC"]["virtual_sites"]
    assert catalog["GLC"]["source_sha256"]
```

```python
def test_tail_recipe_catalog_has_two_named_recipes():
    recipes = {item["id"]: item for item in tail_recipe_catalog()}
    assert recipes["linear-c1"]["name"] == "Linear C1"
    assert recipes["linear-c1-terminal"]["name"] == "Linear C1/C2 terminal"
    assert recipes["linear-c1"]["carbons_per_bead"] == 4
```

- [ ] **Step 2: Run the focused tests and confirm they fail.**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_composition_topology.py tests/dashboard/unit/test_sugar_fragment_catalog.py -q`

Expected: FAIL because the catalog and recipe functions do not exist.

- [ ] **Step 3: Implement source parsing and fixed catalogs.**

Parse `[moleculetype]`, `[atoms]`, `[constraints]`, `[bonds]`, `[angles]`, `[dihedrals]`, `[exclusions]`, and virtual-site sections from the canonical sugar ITP. Preserve local indices, bead names/types, masses/charges, virtual-site parents, exclusions, bonded terms, and source SHA256. Define versioned recipe/profile dictionaries as module constants; do not read recipe definitions from browser input.

Implement `load_sugar_catalog` to reject malformed or duplicate residue blocks and return deterministic residue ordering. Define profile compatibility by endpoint role/type and residue class, with the DDM sugar-to-alkyl transfer profile as the first required profile.

- [ ] **Step 4: Add recipe expansion tests before implementation.**

```python
def test_linear_c1_expands_c12_to_three_beads():
    result = expand_tail(recipe_id="linear-c1", carbon_count=12)
    assert [bead["type"] for bead in result["beads"]] == ["C1", "C1", "C1"]
    assert [bead["carbon_range"] for bead in result["beads"]] == [[1, 4], [5, 8], [9, 12]]
    assert result["coordinates"] == expand_tail("linear-c1", 12)["coordinates"]
```

```python
def test_recipe_rejects_invalid_carbon_count():
    with pytest.raises(ValueError, match="carbon count"):
        expand_tail("linear-c1", 0)
```

- [ ] **Step 5: Implement deterministic tail generation.**

Add `expand_tail(recipe_id: str, carbon_count: int) -> dict` with bounded integer input, named recipe lookup, deterministic bead names, carbon ranges, types, masses, charges, bonds, and zig-zag coordinates. Keep synthetic carbon metadata separate from simulation bead coordinates.

- [ ] **Step 6: Run the topology unit tests.**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_composition_topology.py tests/dashboard/unit/test_sugar_fragment_catalog.py -q`

Expected: PASS.

- [ ] **Step 7: Commit the catalog and recipe unit.**

```bash
git add dashboard/models/composition_topology.py tests/dashboard/unit/test_composition_topology.py tests/dashboard/unit/test_sugar_fragment_catalog.py
git commit -m "feat: add composition fragment catalogs and tail recipes"
```

---

### Task 2: Assemble, validate, and persist immutable compositions

**Files:**
- Modify: `dashboard/models/composition_topology.py`
- Modify: `dashboard/models/compositions.py`
- Test: `tests/dashboard/unit/test_composition_topology.py`
- Test: `tests/dashboard/unit/test_detergent_models.py`

**Interfaces:**
- `build_preview(payload: dict, project_root: Path) -> dict`
- `validate_preview(result: dict) -> dict`
- `parse_composite_itp(text: str) -> dict`
- `parse_composite_gro(text: str) -> dict`
- `create(payload: dict) -> dict`
- `preview(payload: dict, project_root: Path | None = None) -> dict`
- `all_compositions() -> list[dict]`
- `get(composition_id: str) -> dict`

- [ ] **Step 1: Write failing assembly tests.**

```python
def test_build_preview_renumbers_head_tail_and_linkage_terms():
    result = build_preview(valid_payload(), PROJECT_ROOT)
    assert result["mapping"]["beads"][-1]["name"] == "C03"
    assert result["generated_terms"]["bonds"]
    assert result["validation"]["structural"]["ok"]
```

```python
def test_virtual_site_parents_and_exclusions_survive_merge():
    result = build_preview(valid_glucose_payload(), PROJECT_ROOT)
    assert result["topology"]["virtual_sites"]
    assert all(set(item["parents"]) <= set(result["mapping"]["bead_names"]) for item in result["topology"]["virtual_sites"])
    assert result["topology"]["exclusions"]
```

```python
def test_incompatible_profile_blocks_preview():
    payload = valid_payload(linkage_profile_id="unknown-profile")
    with pytest.raises(ValueError, match="linkage profile"):
        build_preview(payload, PROJECT_ROOT)
```

- [ ] **Step 2: Run the assembly tests and confirm failure.**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_composition_topology.py -q`

Expected: FAIL because merge and validation functions are not implemented.

- [ ] **Step 3: Implement fragment merge and profile application.**

Add `build_preview` to load the selected sugar block, expand the selected tail recipe, verify endpoint ownership and profile compatibility, renumber all head/tail beads contiguously, translate tail coordinates from the head endpoint, append inherited terms, add generated linkage terms, preserve virtual-site parents/exclusions, and produce a mapping-like descriptor plus bonded-state descriptor.

Add explicit diagnostics with `class`, `code`, `message`, and `blocking` fields. Reject virtual-site endpoints, disconnected output, nonfinite values, severe overlaps, missing terms, duplicate content, and invalid residue names. Keep chemical-transfer limitations as nonblocking warnings only when the selected profile supplies complete terms.

- [ ] **Step 4: Write topology round-trip and identity tests.**

```python
def test_round_trip_preserves_generated_itp_and_gro():
    result = build_preview(valid_payload(), PROJECT_ROOT)
    parsed = parse_composite_itp(result["itp"])
    assert parsed["atoms"] == result["topology"]["atoms"]
    assert parse_composite_gro(result["gro"])["atom_count"] == len(result["mapping"]["beads"])
```

```python
def test_display_name_does_not_change_composition_identity():
    first = build_preview(valid_payload(display_name="A"), PROJECT_ROOT)
    second = build_preview(valid_payload(display_name="B"), PROJECT_ROOT)
    assert composition_identity(first) == composition_identity(second)
```

- [ ] **Step 5: Implement immutable composition persistence.**

Extend `compositions.create` to rebuild from payload, reject duplicate structural identity, write a temporary artifact directory, verify the generated manifest, atomically rename it, and write the JSON repository record containing the artifact paths and hashes. Keep `all_compositions` and `get` compatible with existing records and reject symlinked/invalid IDs.

- [ ] **Step 6: Run domain tests and existing registry tests.**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_composition_topology.py tests/dashboard/unit/test_detergent_models.py -q`

Expected: PASS.

- [ ] **Step 7: Commit the composition domain.**

```bash
git add dashboard/models/composition_topology.py dashboard/models/compositions.py tests/dashboard/unit/test_composition_topology.py tests/dashboard/unit/test_detergent_models.py
git commit -m "feat: assemble immutable composite CG models"
```

---

### Task 3: Add composition catalog and CG model API contracts

**Files:**
- Create: `dashboard/models/cg_models.py`
- Modify: `dashboard/web/routes/models.py`
- Test: `tests/dashboard/integration/test_compositions_api.py`
- Test: `tests/dashboard/unit/test_cg_models.py`

**Interfaces:**
- `list_models(view: str = "summary") -> list[dict]`
- `get_model(kind: str, identifier: str) -> dict`
- `GET /api/compositions/catalog`
- `POST /api/compositions/preview`
- `POST /api/compositions`
- `GET /api/compositions/<composition_id>`
- `GET /api/cg-models`
- `GET /api/cg-models/mapping/<mapping_file>`
- `GET /api/cg-models/composition/<composition_id>`

- [ ] **Step 1: Write failing API tests.**

```python
def test_composition_catalog_lists_all_sugars_recipes_and_profiles(client):
    response = client.get("/api/compositions/catalog")
    assert response.status_code == 200
    payload = response.get_json()
    assert {item["id"] for item in payload["sugars"]} >= {"GLC", "LAC", "TREH"}
    assert {item["id"] for item in payload["tail_recipes"]} == {"linear-c1", "linear-c1-terminal"}
```

```python
def test_preview_and_save_reject_stale_source_hash(client):
    payload = valid_payload(source_sha256="stale")
    assert client.post("/api/compositions/preview", json=payload).status_code == 409
    assert client.post("/api/compositions", json=payload).status_code == 409
```

```python
def test_cg_model_catalog_includes_saved_composition(client, saved_composition):
    rows = client.get("/api/cg-models?view=summary").get_json()["models"]
    assert any(row["kind"] == "composition" and row["id"] == saved_composition["id"] for row in rows)
```

- [ ] **Step 2: Run the API tests and confirm failure.**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/integration/test_compositions_api.py tests/dashboard/unit/test_cg_models.py -q`

Expected: FAIL because the routes and catalog module do not exist.

- [ ] **Step 3: Implement the unified read-only CG model catalog.**

Normalize ordinary mapping summaries and composition summaries into a stable shape containing `kind`, `id`, `name`, `mapping_hash`, `state_id`, `status`, `origin`, and `scientifically_validated`. Composition detail must return its mapping descriptor and embedded initial bonded state without copying it into ordinary mapping storage.

- [ ] **Step 4: Implement the Flask routes and error mapping.**

Use the existing `_json_object` and `abort` patterns. Return 409 for stale source or duplicate content, 400 for malformed/invalid choices, 404 for unknown IDs, and 201 for a newly persisted composition. Keep existing bonded-state route response fields unchanged.

- [ ] **Step 5: Run API and regression tests.**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/integration/test_compositions_api.py tests/dashboard/unit/test_cg_models.py tests/dashboard/integration/test_dashboard.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the API boundary.**

```bash
git add dashboard/models/cg_models.py dashboard/web/routes/models.py tests/dashboard/integration/test_compositions_api.py tests/dashboard/unit/test_cg_models.py
git commit -m "feat: expose composition and CG model APIs"
```

---

### Task 4: Integrate compositions with CG Bond Interactions

**Files:**
- Modify: `dashboard/web/static/js/bonded.js`
- Modify: `dashboard/web/templates/dashboard.html`
- Modify: `dashboard/web/static/css/compositions.css`
- Test: `tests/dashboard/browser/test_dashboard_browser.py`
- Test: `tests/dashboard/integration/test_dashboard.py`

**Interfaces:**
- `bonded.js` consumes `GET /api/cg-models?view=summary`.
- `bonded.js` loads `GET /api/cg-models/composition/<id>` for composition rows.
- Composition-backed initial state uses `state_id: composition:<id>` and remains read-only until a revision is saved.

- [ ] **Step 1: Write failing browser/API assertions.**

```python
def test_bonded_panel_lists_composition_origin(page, saved_composition):
    page.goto(dashboard_url)
    page.get_by_role("tab", name="CG Bond Interactions").click()
    page.locator(".bonded-mapping-select").select_option(f"composition:{saved_composition['id']}")
    expect(page.locator(".bonded-state-summary")).to_contain_text("Composition")
    expect(page.locator(".bonded-interaction-table")).to_contain_text("generated")
```

```python
def test_composition_state_revision_preserves_parent_hash(client, saved_composition):
    response = client.patch(f"/api/bonded-states/{saved_composition['state_id']}", json={"patch": {"name": "revision"}, "in_place": False})
    assert response.status_code == 201
    assert response.get_json()["source"]["composition_id"] == saved_composition["id"]
```

- [ ] **Step 2: Run the focused browser test and confirm failure.**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/browser/test_dashboard_browser.py -k composition -q`

Expected: FAIL because the bonded selector still loads only `/api/mappings`.

- [ ] **Step 3: Add catalog loading and detail resolution to `bonded.js`.**

Load ordinary and composition model descriptors through the unified catalog. Keep ordinary mapping behavior unchanged. When a composition is selected, fetch its detail, convert its embedded mapping/state into the existing renderer shape, label inherited/generated terms, and disable deletion of the embedded base state. Reuse the existing revision save path for edited copies.

- [ ] **Step 4: Add origin and generated-term presentation.**

Add origin text and generated-term labels without changing the existing interaction table fields or function combobox behavior. Ensure selected rows and 3D bead selection continue to work for composition bead names.

- [ ] **Step 5: Run browser and bonded regression tests.**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/browser/test_dashboard_browser.py tests/dashboard/integration/test_dashboard.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the Bond Interactions integration.**

```bash
git add dashboard/web/static/js/bonded.js dashboard/web/templates/dashboard.html dashboard/web/static/css/compositions.css tests/dashboard/browser/test_dashboard_browser.py tests/dashboard/integration/test_dashboard.py
git commit -m "feat: show compositions in bonded interactions"
```

---

### Task 5: Add the CG-only composition workflow

**Files:**
- Create: `dashboard/execution/composition_workflow.py`
- Modify: `dashboard/execution/workflow.py`
- Modify: `dashboard/execution/coordinator.py`
- Test: `tests/dashboard/unit/test_composition_workflow.py`
- Test: `tests/dashboard/integration/test_composition_workflow.py`

**Interfaces:**
- `STAGES`: `CG simulation`, `CG assessment`, `CG SASA`.
- `readiness(composition_id: str, root: Path) -> dict`
- `prepare_run(run_dir: Path, composition_id: str, settings: dict | None = None) -> None`
- `stage_definitions(metadata)` dispatches `run_type == "cg_composition"` to this workflow.

- [ ] **Step 1: Write failing stage-contract tests.**

```python
def test_composition_stage_contract_has_three_stages():
    assert [stage[0] for stage in composition_workflow.STAGES] == [
        "CG simulation", "CG assessment", "CG SASA"
    ]
    assert composition_workflow.REQUIRED_INPUTS["CG simulation"]
```

```python
def test_prepare_composition_run_records_snapshot_hash(tmp_path, saved_composition):
    composition_workflow.prepare_run(tmp_path, saved_composition["id"])
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["run_type"] == "cg_composition"
    assert manifest["composition_id"] == saved_composition["id"]
    assert manifest["composition_snapshot_sha256"] == saved_composition["snapshot_hash"]
```

- [ ] **Step 2: Run workflow tests and confirm failure.**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_composition_workflow.py tests/dashboard/integration/test_composition_workflow.py -q`

Expected: FAIL because the workflow module and dispatch branch do not exist.

- [ ] **Step 3: Implement the composition stage contract and preparation.**

Stage immutable composition artifacts into a run-local input directory, generate `cg_simulation.sh` with the corrected `-gpu_id 0 -nb gpu -pin on` flags and no PME flags for reaction-field CG, reuse the existing assessment logic with composition paths, and generate a CG-only SASA script that does not reference AA files. Persist composition, mapping, state, recipe, profile, force-field, and tool hashes in the manifest.

- [ ] **Step 4: Add workflow dispatch and lifecycle guards.**

Extend `stage_definitions`, `plan_for`, readiness, and coordinator preparation only for `cg_composition`. Reject missing composition IDs, missing artifacts, AA reference fields, and ordinary molecule inputs. Keep resume and cancellation behavior aligned with existing stage contracts.

- [ ] **Step 5: Run focused workflow and GPU launcher tests.**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_composition_workflow.py tests/dashboard/integration/test_composition_workflow.py tests/dashboard/unit/test_gpu_launchers.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the CG-only workflow.**

```bash
git add dashboard/execution/composition_workflow.py dashboard/execution/workflow.py dashboard/execution/coordinator.py tests/dashboard/unit/test_composition_workflow.py tests/dashboard/integration/test_composition_workflow.py
git commit -m "feat: add CG-only composition workflow"
```

---

### Task 6: Add New Run composition selection and launch transitions

**Files:**
- Modify: `dashboard/web/routes/runs.py`
- Modify: `dashboard/web/static/js/new-run.js`
- Modify: `dashboard/web/templates/dashboard.html`
- Modify: `dashboard/web/static/css/new-run.css`
- Test: `tests/dashboard/integration/test_composition_runs.py`
- Test: `tests/dashboard/browser/test_dashboard_browser.py`

**Interfaces:**
- POST `/` accepts `run_type: "cg_composition"` and `composition_id`.
- `createNewRun().openComposition(compositionId)` selects the new run type and composition.
- Existing `aa_only` and `aa_cg` payloads retain their current fields and validation.

- [ ] **Step 1: Write failing run API tests.**

```python
def test_composition_run_requires_composition_id(client):
    response = client.post("/", json={"run_type": "cg_composition"})
    assert response.status_code == 400

def test_composition_run_rejects_aa_reference_fields(client, saved_composition):
    response = client.post("/", json={
        "run_type": "cg_composition",
        "composition_id": saved_composition["id"],
        "reference_run_id": "aa-reference",
    })
    assert response.status_code == 400
```

```python
def test_new_run_page_contains_composition_mode(client):
    page = client.get("/").get_data(as_text=True)
    assert 'value="cg_composition"' in page
    assert 'id="composition-run-selector"' in page
```

- [ ] **Step 2: Run the run tests and confirm failure.**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/integration/test_composition_runs.py tests/dashboard/browser/test_dashboard_browser.py -k composition -q`

Expected: FAIL because the run type and selector do not exist.

- [ ] **Step 3: Implement server-side composition run validation.**

Resolve the composition through the repository, copy its snapshot metadata into the job record, pass only the composition ID into preparation, and return clear 400/404 errors for missing or unknown compositions. Preserve existing run creation and database fields for other run types.

- [ ] **Step 4: Implement the New Run form path.**

Add a `CG composition` option. Show a composition selector and hide molecule, AA reference, AA duration, and AA-only controls for that mode. Keep the review panel explicit about CG simulation, assessment, and CG-only SASA. Populate the selector from `/api/compositions` and preserve the selected composition when the panel is opened from Molecule Combination.

- [ ] **Step 5: Add transitions from Molecule Combination.**

Implement `openComposition` to select the New Run tab, set `run_type`, select the composition, refresh readiness, and leave the saved composition immutable. Wire the action from `compositions.js` through `main.js` without adding global mutable panel state.

- [ ] **Step 6: Run New Run and regression tests.**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/integration/test_composition_runs.py tests/dashboard/integration/test_aa_api.py tests/dashboard/integration/test_aa_workflow.py tests/dashboard/browser/test_dashboard_browser.py -q`

Expected: PASS.

- [ ] **Step 7: Commit New Run integration.**

```bash
git add dashboard/web/routes/runs.py dashboard/web/static/js/new-run.js dashboard/web/templates/dashboard.html dashboard/web/static/css/new-run.css tests/dashboard/integration/test_composition_runs.py tests/dashboard/browser/test_dashboard_browser.py
git commit -m "feat: launch CG-only runs from compositions"
```

---

### Task 7: Build the Molecule Combination panel

**Files:**
- Modify: `dashboard/web/templates/dashboard.html`
- Modify: `dashboard/web/static/js/main.js`
- Create: `dashboard/web/static/js/compositions.js`
- Create: `dashboard/web/static/css/compositions.css`
- Test: `tests/dashboard/browser/test_composition_panel.py`

**Interfaces:**
- `createCompositions({ selectTab, openBondedModel, openCompositionRun }) -> { mount }`
- `createCompositions.preview() -> Promise<PreviewResult>`
- `createCompositions.save() -> Promise<CompositionRecord>`

- [ ] **Step 1: Write failing browser acceptance tests.**

```python
def test_combination_panel_previews_and_saves_a_c12_tail(page):
    page.goto(dashboard_url)
    page.get_by_role("tab", name="Molecule Combination").click()
    page.locator("#composition-sugar").select_option("GLC")
    page.locator("#composition-carbon-count").fill("12")
    page.locator("#composition-tail-recipe").select_option("linear-c1")
    page.locator("#composition-head-endpoint").select_option("A")
    page.locator("#composition-tail-endpoint").select_option("C1")
    page.locator("#composition-linkage-profile").select_option("sugar-alkyl-ether-ddm-transfer")
    page.get_by_role("button", name="Preview composition").click()
    expect(page.locator("#composition-diagnostics")).to_contain_text("structural")
    expect(page.locator("#composition-save")).to_be_enabled()
```

```python
def test_combination_panel_keeps_all_sugars_visible(page):
    page.goto(dashboard_url)
    page.get_by_role("tab", name="Molecule Combination").click()
    options = page.locator("#composition-sugar option").all_text_contents()
    assert {"GLC", "LAC", "TREH"} <= set(options)
```

- [ ] **Step 2: Run the browser tests and confirm failure.**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/browser/test_composition_panel.py -q`

Expected: FAIL because the fifth tab and controls do not exist.

- [ ] **Step 3: Add the semantic panel markup.**

Add the fifth tab and one workspace with components, synchronized endpoint diagrams, attachment/profile diagnostics, Plotly preview, provenance summary, and the four ordered actions. Keep controls labeled, keyboard reachable, and clear about candidate/unvalidated status. Do not put implementation details into user-facing copy.

- [ ] **Step 4: Implement isolated composition state and API calls.**

Create `compositions.js` with state for catalog, selections, preview generation, saved record, and local recovery. Fetch `/api/compositions/catalog`, invalidate stale responses with a generation counter, send choice-only payloads to preview/save, and render structural/chemical/execution diagnostics. Disable actions until their gates pass and disable Save on duplicate identity.

- [ ] **Step 5: Implement synchronized diagrams and Plotly preview.**

Use the existing Plotly asset and diagram conventions. Render sugar beads/virtual sites and tail CG beads with type/size colors, highlight selected endpoints, display carbon ranges, and show the combined deterministic geometry. Fall back to an accessible endpoint list when pointer selection is unavailable.

- [ ] **Step 6: Implement responsive styling and transitions.**

Add the three-column desktop layout and sequential narrow-screen layout. Wire `Open CG Bond Interactions` and `Start CG-only run` through callbacks passed from `main.js`; do not add cross-module globals. Persist unsaved state under a key containing source hashes and recipe version.

- [ ] **Step 7: Run panel and full browser checks.**

Run: `node --check dashboard/web/static/js/compositions.js && node --check dashboard/web/static/js/main.js`

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/browser/test_composition_panel.py tests/dashboard/browser/test_dashboard_browser.py -q`

Expected: PASS with no browser console errors and no layout overflow at desktop and mobile viewports.

- [ ] **Step 8: Commit the panel.**

```bash
git add dashboard/web/templates/dashboard.html dashboard/web/static/js/main.js dashboard/web/static/js/compositions.js dashboard/web/static/css/compositions.css tests/dashboard/browser/test_composition_panel.py
git commit -m "feat: add molecule combination panel"
```

---

### Task 8: Complete documentation, acceptance coverage, and final review

**Files:**
- Modify: `docs/PROJECT_GUIDE.md`
- Modify: `dashboard/README.md`
- Test: `tests/dashboard/integration/test_composition_workflow.py`
- Test: `tests/dashboard/integration/test_compositions_api.py`

- [ ] **Step 1: Add workflow documentation tests.**

```python
def test_project_guide_mentions_composition_workflow():
    text = Path("docs/PROJECT_GUIDE.md").read_text()
    assert "Molecule Combination" in text
    assert "cg_composition" in text
    assert "candidate-unvalidated" in text
```

- [ ] **Step 2: Update documentation.**

Document the fifth panel, source-hash/provenance behavior, two tail recipes, reference-backed profiles, CG-only stages, and the distinction between screening and scientific validation. Update dashboard operation and run-type descriptions without changing claims about DDM calibration status.

- [ ] **Step 3: Run the complete focused suite.**

```bash
dashboard/.venv/bin/python -m pytest \
  tests/dashboard/unit/test_composition_topology.py \
  tests/dashboard/unit/test_sugar_fragment_catalog.py \
  tests/dashboard/unit/test_cg_models.py \
  tests/dashboard/unit/test_composition_workflow.py \
  tests/dashboard/unit/test_detergent_models.py \
  tests/dashboard/integration/test_compositions_api.py \
  tests/dashboard/integration/test_composition_workflow.py \
  tests/dashboard/integration/test_composition_runs.py \
  tests/dashboard/integration/test_aa_api.py \
  tests/dashboard/integration/test_aa_workflow.py \
  tests/dashboard/browser/test_composition_panel.py \
  tests/dashboard/browser/test_dashboard_browser.py -q
```

Expected: PASS.

- [ ] **Step 4: Run syntax, diff, and graph checks.**

```bash
node --check dashboard/web/static/js/main.js
node --check dashboard/web/static/js/compositions.js
git diff --check
node .gitnexus/run.cjs analyze --index-only
node .gitnexus/run.cjs detect-changes --scope all --repo .
```

Review every high-risk or `UNKNOWN` affected symbol before committing. Confirm no source reference file changed and no unrelated workspace artifact was staged.

- [ ] **Step 5: Run the broader dashboard suite.**

```bash
dashboard/.venv/bin/python -m pytest -m 'not browser and not slow' -q
dashboard/.venv/bin/python -m pytest -m browser -q
```

Run GROMACS-backed checks only with the local environment configured and keep composition screening separate from scientific validation claims.

- [ ] **Step 6: Commit documentation and final tests.**

```bash
git add docs/PROJECT_GUIDE.md dashboard/README.md tests/dashboard/integration/test_composition_workflow.py tests/dashboard/integration/test_compositions_api.py
git commit -m "docs: document molecule combination workflow"
```
