# Carbohydrate Validation Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dashboard-controlled, provenance-preserving validation workspace that compares TC4 and physical-only ring-constrained carbohydrate representations using geometry, transfer free energy, and osmotic-pressure evidence.

**Architecture:** Extend the existing mapping schema, sugar topology generator, immutable analysis worker, and analysis coordinator. A validation request remains attached to a completed source run, but uses a dedicated `carbohydrate-validation` analysis kind whose payload contains the mapping snapshot, representation mode, tier, target dataset, and protocol. The worker derives the selected representation, copies only declared sources into an isolated attempt, runs the three analysis modules, and publishes one immutable report; the dashboard only submits validated requests and renders stored reports.

**Tech Stack:** Python 3, Flask, SQLite-backed dashboard jobs, GROMACS subprocesses, MDAnalysis, NumPy/SciPy, existing Plotly/browser JavaScript, pytest, Playwright browser fixtures.

**Spec:** `docs/superpowers/specs/2026-09-24-carbohydrate-validation-design.md`

## Global Constraints

- Preserve existing mappings, trajectories, runs, references, and reports; every validation request creates a new immutable analysis attempt.
- `tc4` retains TC4 beads, virtual-site parents/exclusions, and ring constraints; `physical_only_ring_constrained` removes TC4 and virtual-site records while retaining physical beads, atom ownership, ring parents, and 1.15 ring constraints.
- Setup checks are `diagnostic_only`; only complete, target-backed, protocol-sufficient evidence can report `evidence_complete`.
- Required evidence keys are exactly `mapped_geometry`, `transfer_free_energy`, and `osmotic_pressure`; bonded, stability, and execution checks remain diagnostics.
- Missing AA data, octanol parameters, targets, lambda windows, or concentration points produces `insufficient_data` and never a pass.
- Do not add dependencies; use installed MDAnalysis, NumPy, SciPy, and GROMACS where available, and record versions and commands.
- Run targeted tests after each task and run GitNexus `detect-changes --scope all` before committing.

---

### Task 1: Add representation-aware mapping derivation

**Files:**
- Create: `dashboard/models/carbohydrate_validation.py`
- Modify: `dashboard/models/mapping_schema.py`
- Modify: `dashboard/models/mappings.py`
- Modify: `dashboard/models/draft_model.py`
- Test: `tests/dashboard/unit/test_carbohydrate_validation_mapping.py`
- Test: `tests/dashboard/unit/test_carbohydrates.py`

**Interfaces:**
- `derive_representation(mapping: dict, mode: str) -> dict` returns a deep-copied mapping with `representation_mode`, `source_mapping_hash`, and `transformation` provenance.
- `validate_representation(mapping: dict, mode: str) -> None` raises `ValueError` for unsupported modes, missing rings, mismatched ring/site parents, or non-deterministic virtual-site relationships.
- `representation_modes() -> list[dict]` returns the two dashboard choices and their descriptions.

- [ ] **Step 1: Write the failing tests**

```python
def test_physical_only_removes_tc4_but_preserves_physical_ring_data(ddm_mapping):
    physical = derive_representation(ddm_mapping, 'physical_only_ring_constrained')
    assert all(not bead.get('virtual_site') for bead in physical['beads'])
    assert [ring['beads'] for ring in physical['rings']] == [ring['beads'] for ring in ddm_mapping['rings']]
    assert all(ring['scale'] == 1.15 for ring in physical['rings'])
    assert physical['source_mapping_hash'] == mapping_identity(ddm_mapping)

def test_tc4_derivation_is_identity_copy(ddm_mapping):
    result = derive_representation(ddm_mapping, 'tc4')
    assert result == ddm_mapping
    assert result is not ddm_mapping

def test_physical_only_rejects_mapping_without_ring_definitions(simple_mapping):
    with pytest.raises(ValueError, match='ring'):
        derive_representation(simple_mapping, 'physical_only_ring_constrained')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_carbohydrate_validation_mapping.py -q`
Expected: FAIL because the representation helper and representation-aware schema rules do not exist.

- [ ] **Step 3: Implement the minimal derivation and schema changes**

Make `derive_representation` remove only beads whose `virtual_site.function == 1` and whose type is `TC4`; preserve all other bead dictionaries, rings, connections, and source fields. Add `representation_mode` to identity payloads only when present. Change `check_schema(data, representation_mode=None)` so a ring without `virtual_site` is accepted only for physical-only mode, while legacy calls retain TC4 validation. Export the helper through `dashboard.models.mappings`.

- [ ] **Step 4: Run focused tests**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_carbohydrate_validation_mapping.py tests/dashboard/unit/test_carbohydrates.py -q`
Expected: PASS, including existing legacy TC4 tests.

- [ ] **Step 5: Commit**

```bash
git add dashboard/models/carbohydrate_validation.py dashboard/models/mapping_schema.py dashboard/models/mappings.py dashboard/models/draft_model.py tests/dashboard/unit/test_carbohydrate_validation_mapping.py tests/dashboard/unit/test_carbohydrates.py
git commit -m "feat: derive physical-only carbohydrate mappings"
```

### Task 2: Generate mode-specific sugar topology and coordinates

**Files:**
- Modify: `dashboard/models/sugar_topology.py`
- Modify: `dashboard/models/sugar_mapping.py`
- Modify: `dashboard/models/mapping_exports.py`
- Test: `tests/dashboard/unit/test_carbohydrate_topology_modes.py`

**Interfaces:**
- `sugar_topology.topology(data, structure, residue_name='DDM', representation_mode=None) -> str` emits both modes.
- `sugar_mapping.coordinates(data, positions, atom_ids=None, scaled=False, representation_mode=None) -> list` adds derived site coordinates only for TC4.

- [ ] **Step 1: Write the failing tests**

```python
def test_physical_only_has_ring_constraints_without_virtual_sites(sugar_mapping, sugar_structure):
    tc4 = topology(sugar_mapping, sugar_structure, representation_mode='tc4')
    physical = topology(derive_representation(sugar_mapping, 'physical_only_ring_constrained'), sugar_structure,
                       representation_mode='physical_only_ring_constrained')
    assert '[virtual_sitesn]' in tc4 and '[virtual_sitesn]' not in physical
    assert '[exclusions]' in tc4 and '[exclusions]' not in physical
    assert physical.count('[constraints]') == tc4.count('[constraints]')

def test_physical_only_coordinates_keep_scaled_ring_cogs_without_tc4_atoms(sugar_mapping, positions):
    physical = derive_representation(sugar_mapping, 'physical_only_ring_constrained')
    assert len(coordinates(physical, positions, scaled=True)) == len(physical['beads'])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_carbohydrate_topology_modes.py -q`
Expected: FAIL because topology currently infers virtual-site output from ring data.

- [ ] **Step 3: Implement mode-aware output**

Pass the explicit mode through export callers. Emit `[virtual_sitesn]` and parent exclusions only when mode is `tc4` and a bead has a virtual-site record. Always emit the same scaled ring constraints and keep cross-ring links unscaled. Make coordinate generation retain physical bead COGs and scaled ring positions in both modes, adding TC4 site coordinates only for `tc4`.

- [ ] **Step 4: Run focused tests**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_carbohydrate_topology_modes.py tests/dashboard/unit/test_prepare_ring_constraints.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dashboard/models/sugar_topology.py dashboard/models/sugar_mapping.py dashboard/models/mapping_exports.py tests/dashboard/unit/test_carbohydrate_topology_modes.py
git commit -m "feat: preserve ring constraints in physical-only topology"
```

### Task 3: Add target datasets and the carbohydrate evidence profile

**Files:**
- Modify: `dashboard/models/evidence.py`
- Modify: `dashboard/analysis/targets.py`
- Modify: `dashboard/analysis/metadata.py`
- Create: `dashboard/analysis/carbohydrate_targets.py`
- Create: `resources/validation/carbohydrates/targets-v1.json`
- Test: `tests/dashboard/unit/test_carbohydrate_targets.py`
- Test: `tests/dashboard/unit/test_analysis_metadata.py`

**Interfaces:**
- `carbohydrate_targets.catalog(root: Path, molecule_id: str) -> dict` returns immutable target datasets with citations, units, uncertainties, and conditions.
- `carbohydrate_targets.validate_selection(root: Path, molecule_id: str, dataset_id: str) -> dict` returns the selected dataset or raises `ValueError`.
- `evidence.evaluate('carbohydrate', results)` requires the three exact evidence keys and returns `evidence_complete` only when all have `passed=True` and no insufficiency.

- [ ] **Step 1: Write failing target/profile tests**

```python
def test_carbohydrate_profile_requires_three_physical_evidence_keys():
    report = evaluate('carbohydrate', {'mapped_geometry': {'passed': True}})
    assert report['missing'] == ['transfer_free_energy', 'osmotic_pressure']
    assert report['status'] == 'insufficient_data'

def test_target_catalog_rejects_unknown_or_uncited_dataset(tmp_path):
    with pytest.raises(ValueError, match='dataset'):
        validate_selection(tmp_path, 'Maltose', 'missing')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_carbohydrate_targets.py -q`
Expected: FAIL because the current profile uses bonded diagnostics and no carbohydrate target catalog exists.

- [ ] **Step 3: Implement target validation and profile status rules**

Add `resources/validation/carbohydrates/targets-v1.json` for available monosaccharide/disaccharide datasets, including citation, value, uncertainty, unit, temperature, solvent, and concentration. Reject unknown molecules, missing citations, non-positive uncertainties, and absent octanol targets. Update metadata descriptions for the three evidence keys and keep legacy profile names unchanged for other molecule classes.

- [ ] **Step 4: Run focused tests**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_carbohydrate_targets.py tests/dashboard/unit/test_analysis_metadata.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dashboard/models/evidence.py dashboard/analysis/targets.py dashboard/analysis/metadata.py dashboard/analysis/carbohydrate_targets.py resources/validation/carbohydrates tests/dashboard/unit/test_carbohydrate_targets.py tests/dashboard/unit/test_analysis_metadata.py
git commit -m "feat: add carbohydrate evidence targets"
```

### Task 4: Generalize geometry evidence and report block uncertainty

**Files:**
- Modify: `dashboard/analysis/surfaces.py`
- Modify: `dashboard/analysis/observability.py`
- Create: `dashboard/analysis/carbohydrate_geometry.py`
- Test: `tests/dashboard/unit/test_carbohydrate_geometry.py`

**Interfaces:**
- `carbohydrate_geometry.run(work_dir: Path, representation: dict, protocol: dict) -> dict` returns `mapped_geometry` metrics and artifacts.
- `carbohydrate_geometry.block_summary(values: Sequence[float], block_count: int = 5) -> dict` returns finite mean, standard deviation, block standard error, and sample count.

- [ ] **Step 1: Write failing geometry tests**

```python
def test_block_summary_is_finite_and_deterministic():
    result = block_summary([1, 2, 3, 4, 5, 6], block_count=3)
    assert result['samples'] == 6
    assert result['mean'] == 3.5
    assert result['blocks'] == 3
    assert result['stderr'] >= 0

def test_geometry_rejects_less_than_200_ns_for_evidence(fake_run):
    with pytest.raises(ValueError, match='200 ns'):
        run(fake_run, {'representation_mode': 'tc4'}, {'tier': 'evidence', 'duration_ns': 10})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_carbohydrate_geometry.py -q`
Expected: FAIL because the dedicated geometry runner and duration gate do not exist.

- [ ] **Step 3: Implement geometry runner**

Reuse the existing GROMACS SASA/radius and Connolly envelope logic, accept `tc4` and physical-only model snapshots, and produce SASA, ring side/angle, molecular-volume, frame-count, and block-statistics artifacts. Enforce the 200 ns minimum only for `tier == 'evidence'`; setup checks may run shorter and must set `diagnostic_only=True`. Include paired TC4/physical-only metadata when a shared source identity is present.

- [ ] **Step 4: Run focused tests**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_carbohydrate_geometry.py tests/dashboard/unit/test_carbohydrates.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dashboard/analysis/surfaces.py dashboard/analysis/observability.py dashboard/analysis/carbohydrate_geometry.py tests/dashboard/unit/test_carbohydrate_geometry.py
git commit -m "feat: calculate carbohydrate geometry evidence"
```

### Task 5: Add transfer free-energy analysis and BAR input validation

**Files:**
- Create: `dashboard/analysis/transfer_free_energy.py`
- Modify: `dashboard/analysis/targets.py`
- Test: `tests/dashboard/unit/test_transfer_free_energy.py`

**Interfaces:**
- `lambda_windows(count: int = 19) -> list[float]` returns the fixed nonuniform 19-window schedule.
- `build_protocol(payload: dict) -> dict` validates water/octanol, soft-core LJ, NpT, and lambda settings and returns canonical protocol metadata.
- `parse_bar(output: str) -> dict` parses finite free-energy and uncertainty values or raises `ValueError`.
- `run(work_dir: Path, payload: dict) -> dict` returns `transfer_free_energy` with water, octanol, transfer, uncertainty, target residual, and `passed`/`insufficient_data` state.

- [ ] **Step 1: Write failing tests**

```python
def test_lambda_windows_has_nineteen_ordered_values():
    values = lambda_windows()
    assert len(values) == 19 and values[0] == 0.0 and values[-1] == 1.0
    assert values == sorted(values)

def test_bar_parser_rejects_missing_uncertainty():
    with pytest.raises(ValueError, match='uncertainty'):
        parse_bar('Delta G = -2.4 kJ/mol')

def test_transfer_requires_octanol_source(tmp_path):
    with pytest.raises(ValueError, match='octanol'):
        run(tmp_path, {'water': {}, 'target': {}})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_transfer_free_energy.py -q`
Expected: FAIL because no transfer module exists.

- [ ] **Step 3: Implement protocol and parser**

Build deterministic per-solvent lambda input metadata and GROMACS command records, require exactly 19 windows, soft-core LJ, NpT, and octanol parameter provenance. Parse BAR output without silently treating missing values as zero. When executables or trajectories are unavailable, return `insufficient_data` with explicit blockers; never claim `passed` from setup-only files.

- [ ] **Step 4: Run focused tests**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_transfer_free_energy.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dashboard/analysis/transfer_free_energy.py dashboard/analysis/targets.py tests/dashboard/unit/test_transfer_free_energy.py
git commit -m "feat: add transfer free-energy evidence"
```

### Task 6: Add concentration-series osmotic-pressure analysis

**Files:**
- Create: `dashboard/analysis/osmotic_pressure.py`
- Test: `tests/dashboard/unit/test_osmotic_pressure.py`

**Interfaces:**
- `validate_series(points: list[dict], tier: str) -> list[dict]` validates approximately 0–2.5 molal coverage, flat-bottom restraint metadata, and z-only pressure coupling.
- `pressure_from_force(force_kj_nm: float, area_nm2: float) -> float` returns pressure in the documented unit and rejects non-finite/zero area.
- `run(work_dir: Path, payload: dict) -> dict` returns concentration rows, block uncertainty, target residuals, and completion state.

- [ ] **Step 1: Write failing tests**

```python
def test_pressure_from_force_uses_area_and_finite_units():
    assert pressure_from_force(10.0, 2.0) == pytest.approx(5.0)
    with pytest.raises(ValueError, match='area'):
        pressure_from_force(1.0, 0.0)

def test_series_marks_missing_concentration_incomplete():
    result = validate_series([{'molal': 0.0}, {'molal': 2.5}], 'evidence')
    assert result['complete'] is False
    assert result['missing']
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_osmotic_pressure.py -q`
Expected: FAIL because no concentration-series implementation exists.

- [ ] **Step 3: Implement validation and calculation**

Require the configured concentration grid, approximately 500 ns per point for evidence tier, flat-bottomed solute restraint metadata, and z-only pressure coupling. Parse per-block forces and box areas, compute pressure and block uncertainty, preserve completed points when a later point fails, and set `osmotic_pressure.passed=False` until every required point and target is present.

- [ ] **Step 4: Run focused tests**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_osmotic_pressure.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dashboard/analysis/osmotic_pressure.py tests/dashboard/unit/test_osmotic_pressure.py
git commit -m "feat: add osmotic pressure evidence"
```

### Task 7: Extend the immutable analysis worker and coordinator

**Files:**
- Modify: `dashboard/analysis/worker.py`
- Modify: `dashboard/execution/analysis_coordinator.py`
- Modify: `dashboard/analysis/metadata.py`
- Modify: `dashboard/analysis/__main__.py`
- Create: `dashboard/analysis/carbohydrate_validation.py`
- Test: `tests/dashboard/unit/test_carbohydrate_validation_worker.py`
- Test: `tests/dashboard/integration/test_carbohydrate_validation_api.py`

**Interfaces:**
- Worker kind: `carbohydrate-validation`.
- `worker.source_entries(root, 'carbohydrate-validation')` copies the AA source, selected CG artifacts, mapping snapshot, topology inputs, target dataset, and protocol files only.
- `carbohydrate_validation.run(work_dir: Path, payload: dict) -> dict` returns `{status, representation, mapped_geometry, transfer_free_energy, osmotic_pressure, provenance}`.
- `AnalysisCoordinator.queue(jid, 'carbohydrate-validation', payload)` creates the same immutable attempt directory and deduplication signature as existing analyses.

- [ ] **Step 1: Write failing worker/coordinator tests**

```python
def valid_payload(seed=0):
    return {
        'molecule_id': 'Maltose', 'mapping_snapshot': mapping_snapshot,
        'representation_mode': 'physical_only_ring_constrained',
        'tier': 'setup', 'target_dataset_id': 'maltose-pilot-v1', 'seed': seed,
    }

def test_validation_request_copies_declared_sources_and_records_hashes(completed_run, client):
    response = client.post(f"/api/jobs/{completed_run['id']}/carbohydrate-validation", json=valid_payload())
    assert response.status_code == 202
    task = response.get_json()
    assert task['kind'] == 'carbohydrate-validation'

def test_validation_attempt_is_not_reused_when_seed_changes(completed_run, client):
    first = client.post(f"/api/jobs/{completed_run['id']}/carbohydrate-validation", json=valid_payload(seed=1)).get_json()
    second = client.post(f"/api/jobs/{completed_run['id']}/carbohydrate-validation", json=valid_payload(seed=2)).get_json()
    assert first['id'] != second['id']
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_carbohydrate_validation_worker.py tests/dashboard/integration/test_carbohydrate_validation_api.py -q`
Expected: FAIL because the analysis kind, source patterns, and route do not exist.

- [ ] **Step 3: Implement validation dispatch and provenance**

Add the kind and source patterns, include every validation module in the code signature, validate payload representation/tier/target selection before queueing, and write `request.json`, `sources.json`, `progress.json`, `analysis-metadata.json`, and immutable `result.json` using existing worker rules. Ensure a missing source, target, octanol asset, or incomplete evidence becomes `insufficient_data` rather than an exception that looks like a scientific failure.

- [ ] **Step 4: Run focused tests**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_carbohydrate_validation_worker.py tests/dashboard/integration/test_carbohydrate_validation_api.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dashboard/analysis/worker.py dashboard/execution/analysis_coordinator.py dashboard/analysis/metadata.py dashboard/analysis/__main__.py tests/dashboard/unit/test_carbohydrate_validation_worker.py tests/dashboard/integration/test_carbohydrate_validation_api.py
git commit -m "feat: queue immutable carbohydrate validation analyses"
```

### Task 8: Add validation API and mapping workspace controls

**Files:**
- Modify: `dashboard/web/routes/analyses.py`
- Modify: `dashboard/web/routes/models.py`
- Modify: `dashboard/web/static/js/mappings.js`
- Modify: `dashboard/web/templates/dashboard.html`
- Modify: `dashboard/web/static/mappings.css`
- Test: `tests/dashboard/integration/test_carbohydrate_validation_api.py`
- Test: `tests/dashboard/browser/test_mapping_validation_browser.py`

**Interfaces:**
- `GET /api/mappings/representations` returns `representation_modes()`.
- `GET /api/mappings/<name>/validation-targets?molecule_id=<id>` returns the target catalog.
- `POST /api/jobs/<jid>/carbohydrate-validation` validates and queues a request through `AnalysisCoordinator.queue`.
- `GET /api/jobs/<jid>/carbohydrate-validation` returns validation tasks and their stored reports.

- [ ] **Step 1: Write failing API/browser tests**

```python
def test_validation_controls_expose_two_modes_and_two_tiers(client):
    response = client.get('/api/mappings/representations')
    assert {item['id'] for item in response.get_json()['representations']} == {'tc4', 'physical_only_ring_constrained'}

def test_browser_validation_panel_keeps_mapping_approval_separate(page):
    page.goto(dashboard_url)
    page.get_by_role('tab', name='CG Bead Assignment').click()
    assert page.get_by_label('Representation').count() == 1
    assert page.get_by_text('Evidence status').count() == 1
    assert page.get_by_role('button', name='Approve mapping').count() == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/integration/test_carbohydrate_validation_api.py tests/dashboard/browser/test_mapping_validation_browser.py -q`
Expected: FAIL because the validation endpoints and controls are absent.

- [ ] **Step 3: Implement server validation and browser rendering**

Add route helpers that bind mapping snapshots to molecule snapshots and completed source runs, reject stale identities, expose target datasets, and return report state without computing pass/fail in JavaScript. Add a validation panel beside the existing editor with representation, tier, target dataset, source run, protocol summary, estimated work, launch button, progress, and separate evidence cards. Disable evidence launch when required targets or sources are missing; show `diagnostic_only`, `insufficient_data`, `failed`, and `evidence_complete` distinctly.

- [ ] **Step 4: Run focused integration/browser tests**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/integration/test_carbohydrate_validation_api.py -q` and `dashboard/.venv/bin/python -m pytest tests/dashboard/browser/test_mapping_validation_browser.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dashboard/web/routes/analyses.py dashboard/web/routes/models.py dashboard/web/static/js/mappings.js dashboard/web/templates/dashboard.html dashboard/web/static/mappings.css tests/dashboard/integration/test_carbohydrate_validation_api.py tests/dashboard/browser/test_mapping_validation_browser.py
git commit -m "feat: add carbohydrate validation dashboard controls"
```

### Task 9: Add paired-report rendering, documentation, and regression coverage

**Files:**
- Modify: `dashboard/web/static/js/main.js`
- Modify: `dashboard/web/static/js/mappings.js`
- Modify: `dashboard/README.md`
- Modify: `docs/PROJECT_GUIDE.md`
- Modify: `docs/DDM_CALIBRATION.md`
- Create: `docs/research/2026-09-24-carbohydrate-validation-operations.md`
- Test: `tests/dashboard/integration/test_analysis_display.py`
- Test: `tests/dashboard/browser/test_mapping_validation_browser.py`

**Interfaces:**
- Report cards display exact source hashes, protocol settings, target citations, per-evidence status, paired differences, and the immutable attempt ID.
- Existing mapping approval state and production authorization remain unchanged after any validation result.

- [ ] **Step 1: Write failing display/regression tests**

```python
def test_evidence_report_does_not_mark_mapping_approved(client, completed_run, mapping):
    payload = {
        'molecule_id': mapping['molecule_id'],
        'mapping_snapshot': mapping,
        'representation_mode': 'tc4',
        'tier': 'setup',
        'target_dataset_id': 'maltose-pilot-v1',
        'seed': 7,
    }
    queued = client.post(f"/api/jobs/{completed_run['id']}/carbohydrate-validation", json=payload)
    assert queued.status_code == 202
    task = queued.get_json()
    response = client.get(f"/api/mappings/{mapping['file']}")
    assert response.get_json()['status'] != 'approved'
    assert task['report']['status'] in {'diagnostic_only', 'evidence_complete'}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/integration/test_analysis_display.py tests/dashboard/browser/test_mapping_validation_browser.py -q`
Expected: FAIL because validation reports are not rendered and approval separation is not asserted.

- [ ] **Step 3: Implement report display and documentation**

Render raw artifacts and summary metrics through existing artifact links, show paired TC4/physical-only differences only when source and target identities match, and document setup versus evidence tiers, required sampling, target provenance, and the fact that Maltose remains extrapolative unless independently targeted.

- [ ] **Step 4: Run the full dashboard test slice**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/unit tests/dashboard/integration tests/dashboard/browser -q`
Expected: PASS, with any pre-existing unrelated failures recorded separately and no new failures in mapping, analysis, or dashboard tests.

- [ ] **Step 5: Run final repository checks**

Run: `node .gitnexus/run.cjs detect-changes --scope all --repo .` and `git diff --check`.
Expected: GitNexus reports the known dirty-worktree aggregate risk without an unreviewed new critical path, and `git diff --check` produces no whitespace errors.

- [ ] **Step 6: Commit**

```bash
git add dashboard/web/static/js/main.js dashboard/web/static/js/mappings.js dashboard/README.md docs/PROJECT_GUIDE.md docs/DDM_CALIBRATION.md docs/research/2026-09-24-carbohydrate-validation-operations.md tests/dashboard/integration/test_analysis_display.py tests/dashboard/browser/test_mapping_validation_browser.py
git commit -m "docs: document carbohydrate validation workflow"
```

## Self-review

The plan covers the approved representation transformation, mode-specific topology, the three paper-aligned evidence classes, target and provenance gates, immutable analysis publication, dashboard controls, paired reporting, and documentation. Existing bonded and stability diagnostics stay outside the carbohydrate evidence profile. No task deletes or rewrites canonical inputs. The only intentionally deferred work is scientific expansion to polysaccharides, membranes, glycolipids, or protein binding, which the spec marks as out of scope.
