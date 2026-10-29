# UI Redesign Preflight Correctness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix bonded-state identity, topology parsing, async preview, and analysis-display correctness so the dashboard can be redesigned safely.

**Architecture:** Keep existing Flask blueprints, JSON state files, vanilla ES modules, and stable routes. Centralize mapping identity in the mapping model, make bonded-state revision modes explicit, and pass compact metadata to browser modules. Preserve immutable run artifacts and scientific gates.

**Tech Stack:** Python 3.13, Flask, JSON filesystem stores, pytest, vanilla ES modules, Node syntax checks, Python Playwright with installed Chrome.

**Spec:** `docs/superpowers/specs/2026-09-18-ui-redesign-preflight-design.md`

## Global Constraints

- Existing DDM mapping/state records remain readable.
- Existing HTTP routes and response fields remain compatible; new fields and query filters are additive.
- Simulation outputs, canonical references, and run snapshots remain immutable.
- No SQLite migration, long simulation, scientific validation promotion, or micelle-builder work.
- Reusable bonded states require complete topology and compatible mapping identity.
- Tests use isolated temporary stores and do not write user-owned workspace state.
- Every production change follows TDD: failing test, observed failure, minimal fix, passing test.
- This checkout has no Git metadata; do not create commits or alter archived rollback material.

---

### Task 1: Centralize mapping identity and parse virtual-site parents

**Files:**
- Modify: `dashboard/models/mappings.py`
- Modify: `dashboard/models/bonded_states.py`
- Modify: `dashboard/web/routes/models.py`
- Test: `tests/dashboard/unit/test_bonded_states.py`
- Test: `tests/dashboard/integration/test_performance_api.py`

**Interfaces:**
- Produce `mappings.mapping_identity(mapping) -> str`.
- Include `mapping_hash` in `mappings.get()` and `mappings.list_candidates()` records.
- Produce `bonded_states.parse_interactions(topology) -> list[dict]` records with `indices`, `beads`, `function`, `parameters`; virtual-site records additionally contain `parents` and `parent_beads`.
- Keep `GET /api/bonded-states?mapping_hash=<hash>` filtering behavior and make mapping summaries expose the hash.

- [ ] **Step 1: Write failing identity tests.**

Add tests proving the same mapping produces one stable hash, changing a bead name or virtual-site parent changes the hash, and mapping summaries include `mapping_hash`.

```python
def test_mapping_identity_covers_virtual_site_definition():
    candidate = physical_mapping()
    first = mappings.mapping_identity(candidate)
    changed = json.loads(json.dumps(candidate))
    changed['beads'][-1]['virtual_site']['parents'][0] = changed['beads'][1]['name']
    assert mappings.mapping_identity(changed) != first
```

- [ ] **Step 2: Run the focused tests and confirm RED.**

Run:

```bash
dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_bonded_states.py tests/dashboard/integration/test_performance_api.py -q
```

Expected: failure because `mapping_identity` and `mapping_hash` fields do not exist.

- [ ] **Step 3: Implement one canonical identity helper.**

In `mappings.py`, hash the existing identity fields in sorted JSON form:

```python
def mapping_identity(mapping):
    payload = {key: mapping.get(key) for key in ('name', 'beads', 'rings', 'connections')}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
```

Use this helper in candidate detail and summary records. Keep an existing stored
`mapping_hash` only when it equals the canonical value; otherwise report the
canonical value for the current content.

- [ ] **Step 4: Replace duplicate bonded-state hashes.**

Import `mappings` in `bonded_states.py` and replace all inline `_hash({...})`
mapping expressions with `mappings.mapping_identity(mapping)`. Keep `_hash()` for
other payloads if still used.

- [ ] **Step 5: Add virtual-site parser tests before parser code.**

Use this topology fixture and assert parent indices are separate:

```python
def test_parse_virtual_sites_preserves_parent_links():
    rows = bonded_states.parse_interactions(
        '[ atoms ]\n1 X 1 RES A 1 X 0\n2 X 1 RES B 1 X 0\n3 X 1 RES C 1 X 0\n4 X 1 RES VS 1 X 0\n'
        '[ virtual_sitesn ]\n4 1 1 2 3\n'
    )
    assert rows == [{'kind': 'virtual_sitesn', 'indices': [4], 'beads': ['VS'],
                     'function': '1', 'parameters': [], 'parents': [1, 2, 3],
                     'parent_beads': ['X', 'X', 'X'], 'id': 'virtual_sitesn:1'}]
```

- [ ] **Step 6: Run parser test and confirm RED.**

Run:

```bash
dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_bonded_states.py::test_parse_virtual_sites_preserves_parent_links -q
```

Expected: failure because current parser places parent values in `parameters`.

- [ ] **Step 7: Implement variable-length virtual-site parsing.**

For `virtual_sitesn`, parse site index and function, then read the optional
parent count and exactly that many parent indices. For `virtual_sites3`, expose
the three parent indices after the function and retain remaining numeric weights
in `parameters`. Resolve names from `[ atoms ]`; malformed rows remain skipped,
matching current parser tolerance.

- [ ] **Step 8: Run focused backend tests.**

Run:

```bash
dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_bonded_states.py tests/dashboard/integration/test_performance_api.py -q
```

Expected: PASS.

---

### Task 2: Make bonded revisions safe and explicit

**Files:**
- Modify: `dashboard/models/bonded_states.py`
- Modify: `dashboard/web/routes/models.py`
- Test: `tests/dashboard/unit/test_bonded_states.py`
- Test: `tests/dashboard/integration/test_performance_api.py`

**Interfaces:**
- `bonded_states.revise(state_id, patch, expected_revision=None, in_place=False)` returns a new state for save-as-new or the revised state for in-place mode.
- Save-as-new records `parent_state_id` and `parent_revision` and leaves source file bytes unchanged.
- PATCH `/api/bonded-states/<id>` accepts `patch`, `expected_revision`, and `in_place`; stale in-place requests return 409.

- [ ] **Step 1: Write failing save-as-new and in-place tests.**

Add tests that snapshot source JSON, call `revise(..., in_place=False)`, assert a
different state ID and unchanged source, then call `revise(..., in_place=True,
expected_revision=1)` and assert revision 2. Add a stale expected revision test.
Import both `bonded_states` and `mappings` in the test module so the fixture uses
the canonical identity helper.

```python
def test_save_as_new_preserves_source_and_in_place_is_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr(bonded_states, 'storage_root', lambda: tmp_path)
    mapping = {'name':'DDM','beads':[{'name':'B01'}],'rings':[],'connections':[]}
    mapping['mapping_hash'] = mappings.mapping_identity(mapping)
    state = bonded_states.create(mapping, 'fit', topology='[ moleculetype ]\n[ atoms ]', status='complete')
    original = (tmp_path / f"{state['state_id']}.json").read_bytes()
    copy = bonded_states.revise(state['state_id'], {'name': 'edited'}, 1, in_place=False)
    assert copy['state_id'] != state['state_id']
    assert copy['parent_state_id'] == state['state_id']
    assert (tmp_path / f"{state['state_id']}.json").read_bytes() == original
    revised = bonded_states.revise(state['state_id'], {'name': 'r2'}, 1, in_place=True)
    assert revised['revision'] == 2
```

- [ ] **Step 2: Run the revision tests and confirm RED.**

Run:

```bash
dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_bonded_states.py -q
```

Expected: failure because `in_place` currently has no effect.

- [ ] **Step 3: Implement save-as-new.**

Validate patch keys and mapping identity. For `in_place=False`, merge the patch
with current payload, create a new state ID, set `parent_state_id` and
`parent_revision`, preserve mapping hash, and write only the new file.

- [ ] **Step 4: Implement guarded in-place revision.**

For `in_place=True`, require an exact `expected_revision`; reject absent or stale
values with `ValueError('Bonded state changed; reload it before editing')`. Append
one revision, update current pointer, and write atomically.

- [ ] **Step 5: Add API mode tests.**

Exercise PATCH through an isolated Flask app. Assert default mode returns a new
state ID, explicit in-place returns the original ID with incremented revision,
and stale in-place returns HTTP 409 without changing the JSON file.

- [ ] **Step 6: Run focused API tests.**

Run:

```bash
dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_bonded_states.py tests/dashboard/integration/test_performance_api.py -q
```

Expected: PASS.

---

### Task 3: Filter state selectors and finish safe preview loading

**Files:**
- Modify: `dashboard/web/static/js/bonded.js`
- Modify: `dashboard/web/templates/dashboard.html`
- Modify: `dashboard/web/static/dashboard.css`
- Create: `tests/dashboard/browser/test_bonded_workspace_browser.py`

**Interfaces:**
- Bonded state list request becomes `/api/bonded-states?view=summary&mapping_hash=<hash>`.
- Preview and interaction loads use one generation token and clear previous preview on failure.
- UI exposes “Save as new state” and “Revise selected state” controls.

- [ ] **Step 1: Add browser regression tests first.**

Cover: selecting mapping A excludes mapping B states; selecting a state then
changing mapping leaves no old topology preview; a rejected detail request shows
the panel error and provisional preview is not retained; save-as-new sends
`in_place:false`; revise sends `expected_revision` and `in_place:true` after
confirmation.

- [ ] **Step 2: Run the browser test and confirm RED.**

Run:

```bash
dashboard/.venv/bin/python -m pytest tests/dashboard/browser/test_bonded_workspace_browser.py -q
```

Expected: failure because selector is unfiltered, controls are absent, or stale
preview remains.

- [ ] **Step 3: Add explicit editor controls and status hooks.**

Add buttons and an editor region to the bonded template. Keep existing class names
and controls. Add `aria-live` status for load/save errors and a confirmation text
that in-place revision mutates the selected state revision.

- [ ] **Step 4: Filter state loads by selected mapping hash.**

After `loadMapping()` resolves, request only compatible summaries. Keep current
selection when still valid; otherwise reset to mapping-only. Do not trust client
labels for compatibility.

- [ ] **Step 5: Guard all preview paths.**

Increment generation on mapping and state changes. Clear diagram, interaction
table, and preview before a new load. Check generation after every awaited call.
On failure, show error status and retain only a clearly labeled provisional
mapping preview when the selected mapping itself loaded successfully.

- [ ] **Step 6: Add minimal structured parameter editor.**

Render editable numeric inputs only for supported `bonds`, `angles`, and
`dihedrals`; render constraints and virtual-site parents read-only. Validate finite
numbers and function-specific arity in the browser. Build a patch from the current
state and post the exact selected revision. Server validation remains authoritative.

- [ ] **Step 7: Wire save-as-new and in-place actions.**

Save-as-new calls PATCH with `in_place:false`; replace selector with returned state
without altering source. Revise action requires `confirm()` and sends
`in_place:true`, `expected_revision: state.revision`; on 409 reload detail and show
the conflict message.

- [ ] **Step 8: Run browser regression and JS syntax checks.**

Run:

```bash
dashboard/.venv/bin/python -m pytest tests/dashboard/browser -q
for f in dashboard/web/static/js/*.js; do node --input-type=module --check < "$f"; done
```

Expected: PASS with no page errors in the focused flow.

---

### Task 4: Make analysis captions and values metadata-driven

**Files:**
- Modify: `dashboard/web/static/js/runs.js`
- Modify: `dashboard/web/static/js/figures.js`
- Modify: `dashboard/analysis/observability.py` to attach nearest `analysis-metadata.json` to indexed artifacts
- Test: `tests/dashboard/browser/test_figure_viewer.py`
- Test: `tests/dashboard/integration/test_operations.py` or a new analysis-display test

**Interfaces:**
- Numeric formatter returns `n/a` for absent, null, non-finite, or missing metric values.
- Figure artifact metadata, when present, supplies title, units, direction, and legacy flag.
- Filename-only captions remain available but explicitly say `Legacy caption`.

- [ ] **Step 1: Write failing missing-value tests.**

Use diagnostics with absent `raw_AA`, absent `ring_expanded_AA`, and explicit zero.
Assert UI text contains `n/a` for absent values and `0.000 nm` for explicit zero.
Add a figure metadata fixture with Wasserstein nm direction and assert it replaces
generic score wording.

- [ ] **Step 2: Run focused browser tests and confirm RED.**

Run:

```bash
dashboard/.venv/bin/python -m pytest tests/dashboard/browser/test_figure_viewer.py -q
```

Expected: failure because current `Number(value || 0)` renders missing values as zero
and captions infer only from filenames.

- [ ] **Step 3: Implement missing-safe numeric formatting.**

Add a local helper in `runs.js` that distinguishes `undefined`, `null`, empty,
non-finite, and numeric zero. Use it for summary cards and pair tables.

- [ ] **Step 4: Index and consume figure metadata with legacy fallback.**

Update `observability.artifacts()` to find the nearest `analysis-metadata.json`
inside the same run directory and add its parsed object as an additive `metadata`
field on figure entries. Pass this field into `RunFigureViewer`. Prefer `title`,
`units_or_direction`, `ideal_result`, and `legacy` fields. When absent, use
existing filename rules and append a visible `Legacy caption` marker.

- [ ] **Step 5: Run focused analysis tests.**

Run:

```bash
dashboard/.venv/bin/python -m pytest tests/dashboard/browser/test_figure_viewer.py tests/dashboard/integration/test_operations.py -q
```

Expected: PASS.

---

### Task 5: Remove maintained documentation path drift

**Files:**
- Modify: `dashboard/FAST_FORWARD_ALIGNMENT.md`
- Modify: `docs/MICELLE_BUILDER.md` only where current examples are intended to refer to maintained inputs
- Modify: any maintained docs found by `rg -n 'detergents/DDM' README.md docs dashboard molecules`
- Test: documentation search command

- [ ] **Step 1: Identify current versus historical references.**

Run:

```bash
rg -n 'detergents/DDM' README.md docs dashboard molecules
```

Classify each hit. Leave archived reports, historical manifests, and preserved
source text unchanged.

- [ ] **Step 2: Update only maintained current-workflow examples.**

Use `molecules/DDM` for canonical molecule inputs. Keep experimental micelle
template references explicit and separate from dashboard AA/CG inputs.

- [ ] **Step 3: Verify no maintained path drift remains.**

Run the same search and confirm only historical/archived references remain.

---

### Task 6: Full verification and fresh isolated UI smoke

**Files:**
- No production files unless verification exposes a regression.
- Test artifacts: `/tmp/ui-redesign-preflight-*.png` only.

- [ ] **Step 1: Run focused backend tests.**

```bash
dashboard/.venv/bin/python -m pytest \
  tests/dashboard/unit/test_bonded_states.py \
  tests/dashboard/unit/test_bonded.py \
  tests/dashboard/integration/test_performance_api.py -q
```

- [ ] **Step 2: Run all dashboard tests.**

```bash
dashboard/.venv/bin/python -m pytest -q
```

- [ ] **Step 3: Run JavaScript syntax checks.**

```bash
for f in dashboard/web/static/js/*.js; do node --input-type=module --check < "$f"; done
```

- [ ] **Step 4: Run isolated browser smoke.**

Use a fresh Flask test server/workspace or the repository browser fixture. Check
page identity, tab order, mapping/state filtering, preview error state, save-as-new,
desktop viewport, mobile viewport, and console errors. Save screenshots outside the
repository.

- [ ] **Step 5: Inspect diff and report evidence.**

Run `git status` only to confirm the checkout still has no Git metadata, list changed
files with `find`/`stat`, and report exact test counts, warnings, browser environment,
known limitations, and any remaining historical path references.
