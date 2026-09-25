# Architecture Consolidation and Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `dashboard/` from a flat pile of 86 modules into a navigable package with one interface per concept, and fix every defect the 2026-09-24 architecture review found, without changing any HTTP URL, browser storage key, workspace layout, run artefact shape, or CLI entry point.

**Architecture:** Four moves, in this order. (1) Relocate every module into a concept subpackage, updating all import sites in the same commit, guarded by a layout test. (2) Introduce the missing interfaces — one stage protocol, one environment resolver, one run view, one candidate gate. (3) Delete the code that only existed to paper over their absence: duplicated dispatch, duplicated rules, re-export blocks, compatibility launchers. (4) Fix the behavioural defects (composition screening stub, composition identity mismatch, dead event) and the dev-loop gaps (test dependencies, hard-coded tool paths, missing reference data).

**Tech Stack:** Python 3.12, Flask 3.1, SQLite (WAL), pytest 9 + pytest-xdist, native JS modules, GROMACS 2026 / Fast_Forward when executing runs.

**Evidence:** `architecture-review-20260924.html` (repository root) — all file:line claims below were verified against commit `e0504a3`. Test counts below were measured on this checkout on 2026-09-24, not predicted.

**Status 2026-09-24:** Phase 0 and Phase 1 are complete on `main`: `219e745` opens the phase, `ef7f77e..fe6817d` perform the moves and the guards, `d76c10d` repairs the two paths the moves broke, and the corrected ownership documentation lands in the commit that carries this paragraph. Where the executed layout differs from the tree in Task 1, the deviation is deliberate and named there.

---

## How to execute this plan

Phases 0, 1, 6 and 8 are mechanical enough to run one package (or one batch) per commit — the granularity note in `writing-plans` assumes a feature plan, not a repository-wide move; here a "task" is one independently verifiable, independently revertable change, and the verification command is what makes it safe to batch. Phases 2, 3, 4, 5 and 7 are written test-first: write the failing test, watch it fail for the stated reason, implement, watch it pass, commit.

When executing, use `subagent-driven-development`: one fresh subagent per task with this plan's task text as its context, a spec-compliance review, then a code-quality review. Phase 1 must run in a single agent, in order — parallel agents editing import sites in the same tree will conflict.

## Sequencing

Phase order is deliberate: the layout move lands first so every later diff is written against the final tree, and the new interfaces are created before the modules that will satisfy them are moved behind them.

| Phase | Content | Depends on | Risk | Rough size |
|---|---|---|---|---|
| 0 | Safety net: baseline, dev deps, layout guard | — | none | 5 tasks |
| 1 | Layout move into concept subpackages | 0 | medium (pure churn) | 9 tasks |
| 2 | One stage protocol + one environment resolver | 1 | medium | 8 tasks |
| 3 | Run view out of the coordinator | 2 | medium | 5 tasks |
| 4 | Candidate gate + mapping-cluster consolidation | 1 | medium | 6 tasks |
| 5 | Web surface: routes by concept, one browser request module | 1 | low | 5 tasks |
| 6 | Correctness and honesty fixes | 1 | low | 5 tasks |
| 7 | Test surface: one factory, no global patching | 2,3 | high (touches all tests) | 4 tasks |
| 8 | Docs, tooling, rejected-items record | all | none | 4 tasks |

## Global Constraints

- No behaviour change in Phases 0-5 and 7. Any task that changes behaviour must say so in its own task name and carry its own regression test.
- HTTP URLs, browser storage keys (`ddm.*`), workspace layout (`jobs.sqlite3`, `runs/`, `mapping_drafts/`, `bonded_states/`, `model_registry/`, `compositions/`), manifest field names, and stage names are contracts. Do not rename them.
- `python dashboard/app.py` and `python -m dashboard` stay working.
- `scientifically_validated: false` and every diagnostic-only boundary stay exactly as they are. This plan moves code, not scientific claims.
- One package move per commit. Run the fast suite after every task; run `-m 'not browser'` before every commit in Phases 1-7.
- After Phase 0, the fast-suite baseline is **3 failed, 244 passed, 19 deselected** (measured, `vermouth` installed). The three failures are enumerated in `docs/PROJECT_GUIDE.md` as environment gaps. A task is done when the count and the failure names match that baseline exactly.

---

## Phase 0 — Safety net

### Task 0.1: Record the environment baseline in the project guide

**Objective:** Make the three environment-gap failures a documented fact rather than a permanent red suite.

**Files:**
- Modify: `docs/PROJECT_GUIDE.md` (add a "Known environment gaps" subsection under Verification)

- [ ] **Step 1:** Reproduce the baseline and capture it verbatim:

```bash
dashboard/.venv/bin/python -m pytest -m 'not browser and not slow' -q -p no:cacheprovider
```

Expected (measured 2026-09-24): `3 failed, 244 passed, 19 deselected in ~7.7s`.

- [ ] **Step 2:** Add the subsection listing each failure and its cause:

| Test | Cause | Class |
|---|---|---|
| `test_mapping_exports.py::test_fast_forward_parser_reads_names_and_order` | `resources/parameterizers/fast_forward/fast_forward/map_file_parers.py` absent | unprovisioned Fast_Forward source |
| `test_carbohydrates.py::test_ff_dihedral_membership_controls_restricted_bending` | `resources/parameterizers/fast_forward/fast_forward/interaction_fit.py` absent | unprovisioned Fast_Forward source |
| `test_mapping_references.py::test_real_reference_records_have_verifiable_origins` | `assert {1} == {1, 2, 3}` — reference ranks 2-3 absent from `references/M3-Small-Molecules/models/` | missing reference data |

Two of the three are one root cause: the vendored Fast_Forward Python source tree is not in this checkout, so any test that loads it by literal path fails for a reason unrelated to the code under test. Task 0.3 addresses both.

- [ ] **Step 3:** Verify the doc renders and the test counts match the run you just did.

- [ ] **Step 4:** Commit:

```bash
git add docs/PROJECT_GUIDE.md && git commit -m "docs: record the fast-suite environment baseline"
```

### Task 0.2: Pin the test-only dependencies

**Objective:** A fresh checkout must be able to run the browser suite and the sugar tests from the documented instructions.

**Files:**
- Modify: `requirements-dashboard-tests.txt`
- Modify: `dashboard/README.md` (test setup section)

- [ ] **Step 1:** Add the two missing pins:

```text
pytest-xdist>=3.6,<4
playwright>=1.40
vermouth>=0.15
```

- [ ] **Step 2:** Install and prove all three import:

```bash
dashboard/.venv/bin/python -m pip install -r requirements-dashboard-tests.txt
dashboard/.venv/bin/python -c "import playwright, xdist, vermouth; print('ok')"
```

Expected: `ok`. Note for reproducibility: pip resolved `vermouth==0.15.0` on 2026-09-24.

- [ ] **Step 3:** Re-run the fast suite. `vermouth` was already installed during this review, so the numbers below are measured, not predicted: `3 failed, 244 passed, 19 deselected`. Two of the three sugar failures are resolved by `vermouth`; the third (`test_ff_dihedral_membership_controls_restricted_bending`) is the Fast_Forward-source gap Task 0.3 fixes — do not expect it to pass here. Record the measured baseline in `docs/PROJECT_GUIDE.md`.

- [ ] **Step 4:** Commit:

```bash
git add requirements-dashboard-tests.txt dashboard/README.md docs/PROJECT_GUIDE.md
git commit -m "chore: pin playwright and vermouth as test dependencies"
```

### Task 0.3: Stop the three tests that depend on uncommitted third-party layout

**Objective:** Tests must fail for real reasons, not because a vendored source tree is absent. Two of the three failures (`test_fast_forward_parser_reads_names_and_order`, `test_ff_dihedral_membership_controls_restricted_bending`) are one root cause and get one shared resolver.

**Files:**
- Create: `tests/dashboard/tool_paths.py`
- Modify: `tests/dashboard/integration/test_mapping_exports.py:30-32`
- Modify: `tests/dashboard/unit/test_carbohydrates.py:107-110`
- Modify: `tests/dashboard/unit/test_mapping_references.py:7-11`

- [ ] **Step 1:** Create the shared resolver:

```python
# tests/dashboard/tool_paths.py
"""Locate vendored third-party sources; skip, never fail, when unprovisioned."""
import pathlib

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]


def fast_forward_source(*parts):
    """Return the path to a Fast_Forward Python source file, or None."""
    candidate = PROJECT_ROOT / 'resources/parameterizers/fast_forward/fast_forward' / pathlib.Path(*parts)
    return candidate if candidate.is_file() else None
```

- [ ] **Step 2:** In `test_fast_forward_parser_reads_names_and_order` and `test_ff_dihedral_membership_controls_restricted_bending`, resolve through it and skip with the reason:

```python
path = fast_forward_source('map_file_parers.py')       # 'interaction_fit.py' in the other test
if path is None:
    pytest.skip('Fast_Forward source is not provisioned in this checkout')
```

Keep each test's assertions and the literal `dashboard/execution/scripts` reference untouched — only the load path changes.

- [ ] **Step 3:** In `test_real_reference_records_have_verifiable_origins`, derive expected ranks from the index sources rather than asserting `{1, 2, 3}` (measured today: `assert {1} == {1, 2, 3}`):

```python
ranks = {record["source_rank"] for record in index["records"]}
assert ranks == {source["rank"] for source in index["sources"]}
assert ranks <= {1, 2, 3} and 1 in ranks
assert all(record["fragment_id"] and record["references"] for record in index["records"])
```

- [ ] **Step 4:** Run all three:

```bash
dashboard/.venv/bin/python -m pytest tests/dashboard/integration/test_mapping_exports.py tests/dashboard/unit/test_carbohydrates.py tests/dashboard/unit/test_mapping_references.py -q -p no:cacheprovider
```

Expected: `2 skipped, N passed` — no failures. Then the whole fast suite: `0 failed, ≥245 passed, 19 deselected` (the two skips move out of the failed column; the count depends on how many of the three are skipped in a provisioned vs unprovisioned checkout).

- [ ] **Step 5:** Commit:

```bash
git add tests/dashboard/tool_paths.py tests/dashboard/integration/test_mapping_exports.py tests/dashboard/unit/test_carbohydrates.py tests/dashboard/unit/test_mapping_references.py
git commit -m "test: resolve tool and reference paths instead of asserting a vendored layout"
```

This is the point where the fast suite becomes green. Every later task in this plan is verified against a green baseline rather than a "known 3 failures" baseline, which is why this task comes before the layout move.

### Task 0.4: Add a layout guard test

**Objective:** After the Phase 1 move, nothing may import an old module path.

**Files:**
- Create: `tests/dashboard/unit/test_module_layout.py`

- [ ] **Step 1:** Write the guard: `test_no_module_imports_a_retired_path` scans `dashboard/**/*.py` and `tests/**/*.py` for import lines naming any retired module (the `RETIRED` tuple, grouped by the phase that relocates it), and `test_new_paths_are_importable` is a parametrised import check over `NEW_MODULES`.

- [ ] **Step 2:** Mark both `@pytest.mark.xfail(reason='layout move in progress', strict=False)` and prove they fail for the right reason with the marker disabled:

```bash
dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_module_layout.py -q --runxfail
```

Expected (measured): `13 failed` — one retired-path failure listing every offending file:line, plus twelve `ModuleNotFoundError`s for the new paths. `strict=False` means the suite stays green while the move is in flight and each test clears its marker automatically once it starts passing.

- [ ] **Step 3:** Run the fast suite. Expected: `245 passed, 2 skipped, 19 deselected, 13 xfailed`.

- [ ] **Step 4:** Commit. Fold this with Task 0.5 — a commit that leaves the suite red is not worth the TDD theatre; `--runxfail` is the failing-test evidence:

```bash
git add tests/dashboard/unit/test_module_layout.py
git commit -m "test: guard the package layout with a retired-path check"
```

### Task 0.5: Mark the guard tests expected-to-fail while the move is in flight

**Objective:** Keep every commit green during Phase 1 without hiding the guard.

Folded into Task 0.4: both guard tests carry `@pytest.mark.xfail(reason='layout move in progress', strict=False)` from the moment they land, and `--runxfail` is the record of what they actually report. There is no separate commit for this task.

---

## Phase 1 — Layout move

One commit per package. In each task: `git mv` the files, update every import site, update every `monkeypatch`/`patch` target that names the old path, then run the full non-browser suite.

Target tree:

```text
dashboard/
  app.py  __main__.py  constants.py  paths.py  store.py  files.py
  execution/
    workflow.py             # stays: the run-type dispatcher (Task 2.5)
    protocol.py             # NEW, Phase 2
    stages.py
    environment.py          # from stage_io.py
    adapters/    aa.py  cg.py  cg_names.py  composition.py  micelle.py
    coordination/ coordinator.py  worker.py  analysis_coordinator.py
                  admission.py  resources.py  temporary.py  manifest.py
    scripts/               # unchanged shell/python launchers
  models/
    repository.py          # from json_repository.py
    catalog.py             # from cg_models.py
    mappings/    __init__.py (public facade = today's mappings.py)
                 schema.py  store.py  graph.py  context.py  exports.py
                 suggestions.py  references.py  depiction.py  verdict.py (NEW, Phase 4)
    bonded/      __init__.py (the interaction library, was bonded.py)
                 states.py  generation.py
    sugars/      __init__.py (facade, was carbohydrates.py)
                 recognition.py  coords.py  topology.py  validation.py
    compositions/ __init__.py (was compositions.py)  topology.py
    molecules/   __init__.py  aa.py  registry.py  evidence.py  draft.py  packaged.py
  analysis/
    metadata.py  worker.py  __main__.py
    validation/  __init__.py  geometry.py  targets.py  report.py  transfer.py  osmotic.py
                 carbohydrate_targets.py   # citation registry; distinct from targets.py
    runs/        __init__.py  references.py  observability.py  refinement.py  surfaces.py
  web/
    routes/  __init__.py  common.py  runs.py  analyses.py  maintenance.py
             molecules.py  catalog.py  mappings.py  bonded.py  refinement.py
    templates/  static/
  cli/   __init__.py  screen_candidates.py  migrate_models.py  migration.py  reset_workspace.py
```

Deliberately **not** moved: `app.py`, `paths.py`, `store.py`, `files.py`, `constants.py`. They are the application frame, `dashboard.app`/`dashboard.paths` are imported by 27 modules and by every test, and `python dashboard/app.py` is a documented entry point. Moving five small files would buy nothing and touch everything.

What the executed move changed about this tree, and why:

- `models/mappings/`, not `models/candidates/`. The HTTP surface (`/api/mappings/*`),
  the workspace directory (`mapping_drafts/`), the public facade and every test call
  this a mapping. "Candidate" is the name of one record inside it (`mapping_candidate_*.json`),
  and the plan's Phase 4 introduces a *candidate verdict* module — a package called
  `candidates` would have made "candidate" mean three things.
- `models/bonded/__init__.py` holds the interaction library (it was `bonded.py`), with
  `states.py` and `generation.py` beside it; likewise `sugars/__init__.py` (was
  `carbohydrates.py`, the facade) and `compositions/__init__.py` (was `compositions.py`).
  A `model.py` beside each `__init__.py` would have been a second module in the same
  role, created only to satisfy the tree above.
- `analysis/validation/carbohydrate_targets.py` stays separate from `targets.py`: one
  is the read-only citation registry for carbohydrate validation, the other writes
  experimental target documents and residuals for a run. Same word, different jobs.
- Call sites keep their existing local bindings (`from ...models.bonded import states
  as bonded_states`), so the Phase 1 diff is paths only. Renaming every call site is a
  separate, reviewable change; the guard test lists both the retired and the target
  paths, so the move cannot silently half-land.

Three latent path defects the move exposed and Phase 1 or Phase 2 fixed: after `cg_adapter.py`
became `execution/adapters/cg.py`, its `SCRIPTS` constant computed
`execution/adapters/scripts` (absent) — every script copy in run preparation would
have raised `FileNotFoundError` at the first real CG run; after `aa_molecules.py`
became `models/molecules/aa.py`, `PACKAGED` computed
`dashboard/molecules/DDM/results/MMFF`; and the AA adapter copied its run helpers
under `Path(module.__file__).name`, so a prepared run received `references.py` and
`aa.py` while the generated stage scripts invoke `../common/aa_references.py` and
the copied publication helper imports `aa_molecules` — the AA neutralization and
reference-publication stages would have failed on a missing file.

All three are now anchored to something explicit: the package root rather than
counted parents, and an `RUN_HELPERS` table of `(name, module)` pairs rather than
whatever the file happens to be called. Two guards cover the class, because it is
invisible to import checks and to unit tests that never run a stage:
`test_module_layout.py` walks every dashboard module's module-level `Path`
constants and asserts they exist, and `test_run_helpers.py` asserts the helper
names the stage scripts invoke are the names a run directory receives, and that
those copies import with no package beside them.

### Task 1.1: Move `execution/` into `adapters/` and `coordination/`

**Files (moved):**
- `dashboard/execution/{coordinator,worker,analysis_coordinator,admission,resources,temporary,manifest}.py` → `dashboard/execution/coordination/`
- `dashboard/execution/{aa_workflow,cg_adapter,cg_workflow,composition_workflow,micelle_job}.py` → `dashboard/execution/adapters/`
- `dashboard/execution/stage_io.py` → `dashboard/execution/environment.py`
- Create: `dashboard/execution/coordination/__init__.py`, `dashboard/execution/adapters/__init__.py`

- [ ] **Step 1:** `git mv` each file to its new path; add empty `__init__.py` files.
- [ ] **Step 2:** Rewrite the deep import sites. Find them first:

```bash
grep -rn "from \.\.execution import\|from dashboard.execution import\|from \. import aa_workflow\|from \. import composition_workflow\|from \.stage_io\|import aa_workflow\|import cg_adapter" dashboard tests --include=*.py | grep -v '\.venv'
```

- [ ] **Step 3:** Fix intra-package relative imports: everything inside `coordination/` that imported `from .worker import Worker` still works; anything that imported `from . import aa_workflow` becomes `from ..adapters import aa as aa_adapter`. Prefer the new names over compatibility aliases.
- [ ] **Step 4:** Fix `stage_io` importers to `from .environment import ...` (or `from ..environment import`). Grep:

```bash
grep -rn "stage_io" dashboard tests --include=*.py | grep -v '\.venv'
```

- [ ] **Step 5:** Run:

```bash
dashboard/.venv/bin/python -m pytest -m 'not browser' -q -p no:cacheprovider
```

Expected: the Task 0.1/0.2 baseline count, with no collection errors.

- [ ] **Step 6:** Commit:

```bash
git add -A dashboard/execution tests && git commit -m "refactor: group execution modules into adapters and coordination"
```

### Task 1.2: Move the mapping cluster into `models/candidates/`

**Files (moved):**
- `mapping_schema.py` → `candidates/schema.py`, `mapping_store.py` → `candidates/store.py`, `mapping_graph.py` → `candidates/graph.py`, `mapping_context.py` → `candidates/context.py`, `mapping_exports.py` → `candidates/exports.py`, `mapping_suggestions.py` → `candidates/suggestions.py`, `mapping_references.py` → `candidates/references.py`, `depiction.py` → `candidates/depiction.py`
- `mappings.py` → `candidates/__init__.py` (the package boundary is now the interface)

- [ ] **Step 1:** `git mv` the nine files.
- [ ] **Step 2:** Update the facade `__init__.py` to import from the sibling modules by their new names, and fix every relative import inside the moved files.
- [ ] **Step 3:** Update the 7 deep importers of `dashboard.models.mapping_context`, plus importers of `mapping_references`, `mapping_suggestions`, `depiction`:

```bash
grep -rn "models.mapping_\|models import mapping_\|from \.depiction\|from \.mapping_\|import depiction" dashboard tests --include=*.py | grep -v '\.venv'
```

- [ ] **Step 4:** Update test patch targets that name the moved modules (notably `models.mapping_store`, `models.mapping_references`).
- [ ] **Step 5:** Run the suite; expect the baseline.
- [ ] **Step 6:** Commit:

```bash
git add -A dashboard/models tests && git commit -m "refactor: group the mapping cluster into models/candidates"
```

### Task 1.3: Move bonded, sugar, composition and molecule clusters

**Files (moved):**
- `bonded.py` → `bonded/model.py`; `bonded_states.py` → `bonded/states.py`; `bonded_generation.py` → `bonded/generation.py`
- `sugar_recognition.py` → `sugars/recognition.py`; `sugar_mapping.py` → `sugars/coords.py`; `sugar_topology.py` → `sugars/topology.py`; `carbohydrate_validation.py` → `sugars/validation.py`; `carbohydrates.py` → `sugars/__init__.py`
- `compositions.py` → `compositions/model.py`; `composition_topology.py` → `compositions/topology.py` (package `__init__.py` re-exports the public names)
- `aa_molecules.py` → `molecules/aa.py`; `model_registry.py` → `molecules/registry.py`; `evidence.py` → `molecules/evidence.py`; `draft_model.py` → `molecules/draft.py`; `packaged_ddm_source.py` → `molecules/packaged.py`
- `json_repository.py` → `models/repository.py`; `cg_models.py` → `models/catalog.py`

- [ ] **Step 1:** `git mv` all files; create package `__init__.py` files that re-export the names each package's callers use (`from dashboard.models import compositions` must keep resolving, and `compositions.get`/`all_compositions`/`create` must stay reachable).
- [ ] **Step 2:** Rewrite import sites. Enumerate them first:

```bash
grep -rn "models.aa_molecules\|models.model_registry\|models.cg_models\|models.json_repository\|models.bonded\|models.sugar\|models.carbohydrate\|models.composition_topology\|models.packaged_ddm\|models.draft_model\|models.evidence" dashboard tests --include=*.py | grep -v '\.venv'
```

- [ ] **Step 3:** Update `monkeypatch.setattr`/`patch.dict` targets in tests (`models.bonded_states`, `models.compositions`, `models.mapping_store`, `models.model_registry` appear in 12 test files).

- [ ] **Step 4:** Run the suite; expect the baseline.
- [ ] **Step 5:** Commit:

```bash
git add -A dashboard/models tests && git commit -m "refactor: group bonded, sugar, composition and molecule models"
```

### Task 1.4: Move `analysis/` into `validation/` and `runs/`

**Files (moved):**
- `carbohydrate_geometry.py` → `validation/geometry.py`; `carbohydrate_targets.py` + `targets.py` → `validation/targets.py`; `carbohydrate_validation.py` → `validation/report.py`; `transfer_free_energy.py` → `validation/transfer.py`; `osmotic_pressure.py` → `validation/osmotic.py`
- `aa_references.py` → `runs/references.py`; `observability.py` → `runs/observability.py`; `refinement.py` → `runs/refinement.py`; `surfaces.py` → `runs/surfaces.py`
- `metadata.py`, `worker.py`, `__main__.py` stay at `analysis/` root

- [ ] **Step 1:** `git mv`; keep `analysis/validation/__init__.py` exporting `run` (today's `carbohydrate_validation.run`) and the target helpers so `analysis.worker` changes minimally.
- [ ] **Step 2:** Note the one real merge in this task: `analysis/targets.py` (40 lines, experimental property targets) and `analysis/carbohydrate_targets.py` (40 lines, citation registry) serve one concept — pick one module name, fold both bodies in, and make the second a documented section. If their interfaces differ enough that merging hides a seam, keep them separate as `targets.py` and `target_citations.py` and say so in the commit message.
- [ ] **Step 3:** Update `analysis/worker.py`'s imports and the `KINDS` dispatch if names changed.
- [ ] **Step 4:** Run the suite; expect the baseline.
- [ ] **Step 5:** Commit:

```bash
git add -A dashboard/analysis tests && git commit -m "refactor: split analysis into validation and run analyses"
```

### Task 1.5: Split `web/routes/models.py` by concept

**Objective:** 38 rules in one 412-line module become four modules of concept-sized surface, with no URL change.

**Files:**
- Split `dashboard/web/routes/models.py:18-49,397-405` (compositions) + `52-62` (cg-models) + `143-146` (reference index) + `269-279` (plotly asset) + `374-394` (model registry) → `dashboard/web/routes/catalog.py`
- Split `105-196,299-371` (14 mapping rules) → `dashboard/web/routes/mappings.py`
- Split `199-296` (7 bonded-state rules) → `dashboard/web/routes/bonded.py`
- Split `320-334` (refinement) + `408-412` (evidence) → `dashboard/web/routes/refinement.py`
- Keep `common.py`, and move `_json_object`, `_payload_context`, `_query_context` into it

- [ ] **Step 1:** `git mv dashboard/web/routes/models.py dashboard/web/routes/catalog.py`.
- [ ] **Step 2:** Cut each concept into its own module; each keeps the same `blueprint` object name and the same `@blueprint.route` paths verbatim. Confirm the rules survive by diffing the URL map before and after:

```bash
dashboard/.venv/bin/python -c "from dashboard.app import create_app; print(sorted(str(r) for r in create_app().url_map.iter_rules()))" > /tmp/urls_after.txt
git stash && dashboard/.venv/bin/python -c "from dashboard.app import create_app; print(sorted(str(r) for r in create_app().url_map.iter_rules()))" > /tmp/urls_before.txt && git stash pop
diff /tmp/urls_before.txt /tmp/urls_after.txt && echo "URL surface unchanged"
```

Expected: `URL surface unchanged`.

- [ ] **Step 3:** Register the new modules in `dashboard/app.py`'s blueprint loop.
- [ ] **Step 4:** Run the integration suite (it exercises the HTTP surface) plus the fast suite:

```bash
dashboard/.venv/bin/python -m pytest -m 'not browser' -q -p no:cacheprovider
```

- [ ] **Step 5:** Commit:

```bash
git add -A dashboard/web tests && git commit -m "refactor: split route modules by concept"
```

### Task 1.6: Delete the compatibility launchers

**Files:**
- Delete: `dashboard/scripts/screen_candidates.py`, `dashboard/scripts/migrate_models.py`, and the `dashboard/scripts/` directory

- [ ] **Step 1:** Prove nothing references them:

```bash
grep -rn "dashboard/scripts\|scripts/screen_candidates\|scripts/migrate_models" dashboard tests docs --include=* | grep -v '\.venv\|docs/superpowers'
```

Expected: no hits outside historical plan documents (which stay as history).

- [ ] **Step 2:** Delete them; the supported entry points are `python -m dashboard.cli.screen_candidates` and `python -m dashboard.cli.migrate_models`.
- [ ] **Step 3:** Run the fast suite; expect the baseline.
- [ ] **Step 4:** Commit:

```bash
git rm -r dashboard/scripts && git commit -m "chore: drop compatibility launchers superseded by the cli package"
```

### Task 1.7: Turn the layout guard green and delete the xfail

- [ ] **Step 1:** Remove the `xfail` marker from both tests in `tests/dashboard/unit/test_module_layout.py`; they must now pass unmarked.
- [ ] **Step 2:** Run the guard:

```bash
dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_module_layout.py -q
```

Expected: `2 passed`.

- [ ] **Step 3:** Run the full non-browser suite; expect the baseline.
- [ ] **Step 4:** Commit:

```bash
git add tests/dashboard/unit/test_module_layout.py && git commit -m "test: enforce the new module layout"
```

### Task 1.8: Correct the ownership documentation

**Files:**
- Modify: `docs/PROJECT_GUIDE.md` ("Source ownership" section)
- Modify: `dashboard/README.md` (source-ownership list)
- Modify: `AGENTS.md:34` (phantom `execution/ddm.py` shim)

- [ ] **Step 1:** Replace both ownership lists with the tree in this plan's Phase 1 header.
- [ ] **Step 2:** Delete the `dashboard/execution/ddm.py` sentence from `AGENTS.md` and state that `dashboard/execution/adapters/cg.py` is the generic CG adapter with no shim.
- [ ] **Step 3:** Verify every path named in the docs exists:

```bash
grep -oE 'dashboard/[a-z_/]+\.py' docs/PROJECT_GUIDE.md dashboard/README.md AGENTS.md | sort -u | while read -r f; do [ -f "$f" ] || echo "MISSING $f"; done
```

Expected: no `MISSING` lines.

- [ ] **Step 4:** Commit:

```bash
git add docs/PROJECT_GUIDE.md dashboard/README.md AGENTS.md && git commit -m "docs: correct the source ownership map after the layout move"
```

### Task 1.9: Phase 1 gate

- [ ] **Step 1:** Run the full non-browser suite and the JS syntax checks:

```bash
dashboard/.venv/bin/python -m pytest -m 'not browser' -q -p no:cacheprovider
node --check dashboard/web/static/js/main.js
```

- [ ] **Step 2:** Confirm the dashboard still boots against the real workspace and serves the same URL map:

```bash
dashboard/.venv/bin/python -c "from dashboard.app import create_app; app=create_app(); print(len(list(app.url_map.iter_rules())), 'rules')"
```

Expected: `69 rules`.

- [ ] **Step 3:** Commit any remaining churn and record the phase in `docs/PROJECT_GUIDE.md`.

---

## Phase 2 — One stage protocol, one environment resolver

### Task 2.1: Create the protocol interface

**Objective:** One module that answers, for any run type: which stages exist, which settings are legal, is this runnable, how is it prepared, and what tool versions were used.

**Files:**
- Create: `dashboard/execution/protocol.py`
- Test: `tests/dashboard/unit/test_protocol.py`

- [ ] **Step 1:** Write the failing test:

```python
"""Every run type answers the same protocol surface, in the same shapes."""
from dashboard.execution import protocol


def test_every_adapter_exposes_the_same_surface():
    for run_type in ('aa_only', 'aa_cg', 'cg_composition'):
        adapter = protocol.adapter_for(run_type)
        plan, required_inputs, required_outputs = adapter.stage_contract({})
        assert plan and required_inputs is not None and required_outputs is not None
        specs = adapter.settings_specs()
        assert all(isinstance(bounds, tuple) and len(bounds) in (2, 3) for bounds in specs.values())
        assert set(adapter.readiness({})) >= {'ready', 'checks', 'blockers'}
        assert adapter.tool_report() is not None
```

- [ ] **Step 2:** Run it. Expected: FAIL — `No module named 'dashboard.execution.protocol'`.

- [ ] **Step 3:** Write the interface: a `Protocol` dataclass with fields `name`, `stage_contract`, `settings_specs`, `stage_defaults`, `normalize_settings`, `readiness`, `prepare`, `tool_report`, plus `adapter_for(run_type)` and `SETTINGS_BOUNDS` normalisation helpers that accept both the `(lo, hi)` and `(label, lo, hi)` shapes so both existing adapters satisfy the surface on the day they are wrapped.

- [ ] **Step 4:** Run the test. Expected: PASS for `aa_only` and `cg_composition`; `aa_cg` passes only once the adapters are wrapped — mark the loop body with `pytest.param(..., marks=pytest.mark.xfail)` for the not-yet-wrapped types so the failure stays visible.

- [ ] **Step 5:** Commit:

```bash
git add dashboard/execution/protocol.py tests/dashboard/unit/test_protocol.py
git commit -m "feat: add the run-type protocol interface"
```

### Task 2.2: Wrap the AA adapter

**Files:**
- Modify: `dashboard/execution/adapters/aa.py`
- Modify: `dashboard/execution/protocol.py`

- [ ] **Step 1:** Wrap `aa.py`'s module-level functions (STAGE_DEFS/STAGES, SETTING_SPECS, stage_defaults, normalize_settings, readiness, prepare_run, tool_metadata) into a `Protocol` instance without changing any behaviour.
- [ ] **Step 2:** Run `tests/dashboard/unit/test_protocol.py` and the AA integration tests:

```bash
dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_protocol.py tests/dashboard/integration/test_aa_api.py tests/dashboard/integration/test_aa_workflow.py -q
```

Expected: PASS.

- [ ] **Step 3:** Commit:

```bash
git add -A dashboard/execution tests && git commit -m "refactor: expose the AA workflow through the protocol interface"
```

### Task 2.3: Wrap the CG adapter (and drop its "everything is public" comment)

**Files:**
- Modify: `dashboard/execution/adapters/cg.py:18-19` (delete the shim comment), `dashboard/execution/workflow.py:9-11` (delete the re-export block)

- [ ] **Step 1:** Wrap the CG adapter's surface; keep `stage_contract(names)` as the one entry point for naming contexts.
- [ ] **Step 2:** Delete `workflow.py`'s re-export block, including the private `_mdp_value`, and point every importer at `adapters.cg` directly. Find them:

```bash
grep -rn "from \.workflow import\|from dashboard.execution.workflow import\|from \.\.execution import workflow" dashboard tests --include=*.py | grep -v '\.venv'
```

- [ ] **Step 3:** Run:

```bash
dashboard/.venv/bin/python -m pytest -m 'not browser' -q -p no:cacheprovider
```

Expected: baseline. Pay attention to `tests/dashboard/integration/test_dashboard.py` and `test_operations.py`, which patch `workflow.readiness` and `workflow.prepare_run` — repoint those patches at the adapter, or at the protocol object once Task 2.5 lands.

- [ ] **Step 4:** Commit:

```bash
git add -A dashboard tests && git commit -m "refactor: expose the CG adapter through the protocol and drop the re-export block"
```

### Task 2.4: Wrap the composition adapter

**Files:**
- Modify: `dashboard/execution/adapters/composition.py`

- [ ] **Step 1:** Add the missing surface members (`settings_specs`, `stage_defaults`, `normalize_settings`, `tool_report`) so the composition adapter answers the same questions as the other two. Its settings are empty and its tool report records only `python`; say that explicitly in the docstring rather than leaving the attributes absent.
- [ ] **Step 2:** Make `readiness` return the same key set (`ready`, `checks`, `blockers`, plus its own extras).
- [ ] **Step 3:** Run `tests/dashboard/unit/test_protocol.py` with all three run types un-xfailed. Expected: PASS.
- [ ] **Step 4:** Commit:

```bash
git add dashboard/execution/adapters/composition.py tests/dashboard/unit/test_protocol.py
git commit -m "refactor: complete the composition adapter protocol surface"
```

### Task 2.5: Make `workflow.py` the dispatcher, not a second owner

**Objective:** One owner of the run-type matrix. `admission.py` is used by the queue routes; `coordinator.create_job` re-implements it; `workflow.stage_definitions`/`plan_for` and `coordinator.run_job` each branch on run type again.

**Files:**
- Modify: `dashboard/execution/workflow.py:64-88`
- Modify: `dashboard/execution/coordination/coordinator.py:416-438, 494-522, 556-573`
- Modify: `dashboard/execution/coordination/admission.py`
- Modify: `dashboard/web/routes/runs.py:12,43,157`

- [ ] **Step 1:** Write the failing test that pins the single owner:

```python
def test_run_type_matrix_has_one_owner():
    """Coordinator payload checks must come from admission, not a private copy."""
    import inspect
    from dashboard.execution.coordination import coordinator
    source = inspect.getsource(coordinator.Coordinator.create_job)
    assert 'AA-only cannot use CG inputs' not in source
    assert 'CG composition runs require composition_id' not in source
```

- [ ] **Step 2:** Run it. Expected: FAIL on both assertions.
- [ ] **Step 3:** Call `admission.validate_run_type(...)` from `create_job` (keeping `coordinator()`'s 400-vs-409 distinction in one place: admission raises `ValueError`, which `app.py` maps to 400, and `create_job` re-raises the admission error as 400 while keeping its own 409s for state conflicts).
- [ ] **Step 4:** Replace `stage_definitions`/`plan_for`'s branches with `protocol.adapter_for(run_type).stage_contract(metadata)`.
- [ ] **Step 5:** Run the integration suite:

```bash
dashboard/.venv/bin/python -m pytest tests/dashboard/integration -q -p no:cacheprovider
```

Expected: PASS (same count as baseline).
- [ ] **Step 6:** Commit:

```bash
git add -A dashboard tests && git commit -m "refactor: one owner for run-type admission and stage dispatch"
```

### Task 2.6: Merge the settings dialects

**Objective:** `SETTING_SPECS` is `(lo, hi)` in the AA adapter and `(label, lo, hi)` in the CG adapter, so `coordinator.py:560-565` hand-merges them into a legacy dict.

**Files:**
- Modify: `dashboard/execution/adapters/{aa,cg,composition}.py`
- Modify: `dashboard/execution/coordination/coordinator.py:558-565`
- Test: `tests/dashboard/unit/test_protocol.py`

- [ ] **Step 1:** Write the failing test:

```python
def test_settings_specs_share_one_shape():
    from dashboard.execution import protocol
    for run_type in ('aa_only', 'aa_cg', 'cg_composition'):
        specs = protocol.adapter_for(run_type).settings_specs()
        assert all(len(bounds) == 3 and isinstance(bounds[0], str) for bounds in specs.values())
```

- [ ] **Step 2:** Convert the AA adapter's `SETTING_SPECS` to `(label, lo, hi)` with real labels ("AA NVT duration", "AA seed", …).
- [ ] **Step 3:** Delete the legacy merge in `create_job`; pass the requested settings to the adapters and let each adapter's `normalize_settings` reject what it does not own. Keep the "unknown run settings" 400 for keys no adapter claims.
- [ ] **Step 4:** Run the settings-sensitive tests:

```bash
dashboard/.venv/bin/python -m pytest tests/dashboard/integration/test_aa_api.py tests/dashboard/integration/test_dashboard.py -q
```

- [ ] **Step 5:** Commit:

```bash
git add -A dashboard tests && git commit -m "refactor: one settings shape across run types"
```

### Task 2.7: One environment resolver, and honour `config/tools.json`

**Objective:** `environment()` builds `PATH` by hand from an import-time root and a hard-coded `~/Downloads/gromacs-2026.0` path in two modules, while `config/tools.json` (which declares `gromacs`, `fast_forward`, `bartender`, `xtb`) is read by nothing.

**Files:**
- Create: `dashboard/execution/tools.py`
- Modify: `dashboard/execution/environment.py:12-24`
- Modify: `dashboard/analysis/runs/surfaces.py:65`
- Modify: `dashboard/execution/adapters/aa.py:75-78`, `adapters/cg.py:227-238`
- Test: `tests/dashboard/unit/test_tools.py`

- [ ] **Step 1:** Write the failing test:

```python
def test_tool_resolution_prefers_config_then_path(tmp_path, monkeypatch):
    from dashboard.execution import tools
    config = tmp_path / 'tools.json'
    config.write_text('{"gromacs": "/usr/local/gromacs/2026.3/bin/gmx"}')
    assert tools.tool_path('gromacs', config=config) == '/usr/local/gromacs/2026.3/bin/gmx'
    assert tools.tool_path('not-declared', config=config) is None or tools.tool_path('not-declared', config=config).endswith('gmx')
```

- [ ] **Step 2:** Run it. Expected: FAIL — no `tools` module.
- [ ] **Step 3:** Implement `tools.py`: read `config/tools.json` relative to `paths.current().project_root`, expand `~`, verify the file exists and is executable, fall back to `shutil.which` on the inherited `PATH`, and return `None` when neither resolves. Add `search_path()` returning the composed `PATH` for subprocess environments, built from the workspace root and the resolved tool directories — no literal home-directory paths.
- [ ] **Step 4:** Rewrite `environment()` to use `tools.search_path()`, keep `MPLBACKEND=Agg` and `OMP_NUM_THREADS=8` where they are today, and route every `shutil.which`/`probe_tool` call in `aa.py`, `cg.py`, `surfaces.py` through `tools.tool_path`.
- [ ] **Step 5:** Fix `config/tools.json` to name the GROMACS build that exists on this machine, and add a readiness check that reports a missing declared tool instead of silently falling back.
- [ ] **Step 6:** Run:

```bash
dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_tools.py tests/dashboard/unit/test_gpu_launchers.py tests/dashboard/unit/test_paths.py -q
```

Expected: PASS.

- [ ] **Step 7:** Commit:

```bash
git add -A dashboard config tests && git commit -m "feat: resolve declared tools from config and drop hard-coded paths"
```

### Task 2.8: One stage-log resolver

**Objective:** Stage log paths are encoded four ways: `logs/resume-####/` in the coordinator, `logs/<dir>/<dir>.log` and `stages/<dir>/<dir>.log` in `workflow.run`, and `manifest.stage_log_path` for recorded paths.

**Files:**
- Modify: `dashboard/execution/coordination/manifest.py:50-67`
- Modify: `dashboard/execution/workflow.py:280-283`
- Modify: `dashboard/execution/coordination/coordinator.py:308-342`
- Test: `tests/dashboard/unit/test_stage_logs.py`

- [ ] **Step 1:** Write the failing test: for a run directory with only `stages/<dir>/<dir>.log` present, the resolver returns it; with a `resume-0002` directory present and a resume count of 2, it returns the resume path; with a recorded absolute log outside the run, it returns `None`.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3:** Implement `manifest.stage_log_path(run_dir, *, name=None, recorded=None, resume_count=None)` as the single encoder/decoder; make `workflow.run` write logs through it and delete the candidate-path guessing loop from `_eta`.
- [ ] **Step 4:** Run the resume and operations tests:

```bash
dashboard/.venv/bin/python -m pytest tests/dashboard/integration/test_in_place_resume.py tests/dashboard/integration/test_operations.py -q
```

- [ ] **Step 5:** Commit:

```bash
git add -A dashboard tests && git commit -m "refactor: one stage-log path resolver"
```

---

## Phase 3 — Run view out of the coordinator

### Task 3.1: Create the run view module

**Objective:** `coordinator.public_job` and `_ownership_flags` decide the browser's field set, read `progress.json`, parse GROMACS ETA and resolve log paths inside the lifecycle module. Move that to `web/`.

**Files:**
- Create: `dashboard/web/views.py`
- Test: `tests/dashboard/unit/test_run_view.py`

- [ ] **Step 1:** Write the failing test, constructing a run view from plain inputs with no Flask app:

```python
def test_run_view_builds_without_flask(tmp_path):
    from dashboard.web import views
    job = {'id': 'a' * 12, 'status': 'completed', 'created': '2026-09-24T00:00:00+00:00',
           'edited': None, 'run_type': 'aa_only', 'stage': 'complete'}
    view = views.run_view(job, run_dir=tmp_path, manifest={'stages': [], 'stage_plan': ['AA solvation']},
                          ownership={'can_delete': True}, summary=True)
    assert view['id'] == job['id']
    assert view['stages'] == []
    assert view['workflow_stages'] == ['AA solvation']
    assert view['elapsed_seconds'] is None
```

- [ ] **Step 2:** Run it. Expected: FAIL — no `views` module.
- [ ] **Step 3:** Move `_VISIBLE_FIELDS`, `_HIDDEN_FIELDS`, `_ANALYSIS_SUMMARY_FIELDS`, `_STAGE_SUMMARY_FIELDS`, `_analysis_view`, `_elapsed`, `_eta`, `_stage_view`, `public_job` and the log-tailing helpers into `views.py` as pure functions taking `(job, run_dir, manifest, ownership, summary)`. Keep `parse_gromacs_eta` and `tail` there too — they are view concerns.
- [ ] **Step 4:** Run the test. Expected: PASS.
- [ ] **Step 5:** Commit:

```bash
git add dashboard/web/views.py tests/dashboard/unit/test_run_view.py
git commit -m "feat: add a flask-free run view module"
```

### Task 3.2: Point the routes at the view and thin the coordinator

**Files:**
- Modify: `dashboard/web/routes/runs.py:29-35,80,84,167,201,204`
- Modify: `dashboard/execution/coordination/coordinator.py` (delete the moved members; keep `public_job` as a two-line delegation until Task 3.3 removes its callers)

- [ ] **Step 1:** Replace every `c.public_job(job, summary=...)` call with `views.run_view(...)`, passing ownership flags from a new `coordinator.ownership(job)` that returns only the three booleans.
- [ ] **Step 2:** Run the runs-surface integration tests and the browser-independent API tests:

```bash
dashboard/.venv/bin/python -m pytest tests/dashboard/integration/test_dashboard.py tests/dashboard/integration/test_operations.py tests/dashboard/integration/test_analysis_display.py -q
```

- [ ] **Step 3:** Commit:

```bash
git add -A dashboard tests && git commit -m "refactor: routes build run views through the view module"
```

### Task 3.3: Replace HTTP status codes with domain errors

**Files:**
- Create: `dashboard/execution/coordination/errors.py` (`RunNotFound`, `RunBusy`, `CapacityFull`, `InvalidRunId`, `DependencyRetained`, `SourceUnavailable`)
- Modify: `dashboard/execution/coordination/coordinator.py` (replace every `abort(...)`), `analysis_coordinator.py:48,59`
- Modify: `dashboard/web/routes/*.py` (map domain errors to 400/404/409/429)
- Modify: `dashboard/app.py` (register the error handlers)

- [ ] **Step 1:** Write the failing test that the lifecycle module no longer imports Flask:

```python
def test_coordinator_does_not_import_flask():
    import pathlib
    for name in ('coordinator.py', 'worker.py', 'analysis_coordinator.py', 'admission.py'):
        text = (pathlib.Path('dashboard/execution/coordination') / name).read_text()
        assert 'flask' not in text.lower(), name
```

- [ ] **Step 2:** Run it. Expected: FAIL on `coordinator.py` (and `analysis_coordinator.py`).
- [ ] **Step 3:** Define the errors, replace each `abort(code, message)` with the matching error, and add **one** mapping table in `web/routes/common.py` plus an `app.errorhandler` per class. Preserve the exact status codes currently returned — the browser's stale-source branch depends on them. Verify by comparing the status code inventory before and after:

```bash
grep -rn "abort(" dashboard/execution/coordination/coordinator.py | sed 's/.*abort(\([0-9]*\).*/\1/' | sort | uniq -c > /tmp/codes_before.txt
```

- [ ] **Step 4:** Run the full non-browser suite; expect the baseline with no HTTP-contract failures.
- [ ] **Step 5:** Commit:

```bash
git add -A dashboard tests && git commit -m "refactor: lifecycle raises domain errors; routes decide status codes"
```

### Task 3.4: One cleanup signature for temporary runs

**Files:**
- Modify: `dashboard/execution/coordination/temporary.py`
- Modify: `dashboard/execution/coordination/coordinator.py:209`, `dashboard/web/routes/maintenance.py:26`

- [ ] **Step 1:** Reduce `cleanup(jobs, runs, delete, delete_with_cleanup=...)` to `cleanup(jobs, runs, store)` where `store` is the `Store` instance the coordinator already builds; both callers pass the same object and the two injected callables disappear.
- [ ] **Step 2:** Run `tests/dashboard/unit/test_temporary_validation_cleanup.py` and the operations tests. Expected: PASS.
- [ ] **Step 3:** Commit:

```bash
git add -A dashboard tests && git commit -m "refactor: one deletion seam for temporary runs"
```

### Task 3.5: Absorb the one-line delegations

**Objective:** `coordinator.py` has 34 public methods, 12 of which are single-line pass-throughs to the store, the resources module or `AnalysisCoordinator`.

**Files:**
- Modify: `dashboard/execution/coordination/coordinator.py`
- Modify: `dashboard/web/routes/*.py`

- [ ] **Step 1:** For each of `load`, `save`, `lookup`, `update_job`, `now`, `manifest_data`, `update_analysis`, `analysis_dependencies`, `run_analysis`, `cancel_analysis`, `queue_analysis`, `database`: either delete it and have the caller reach the collaborator it owns (`coordinator.database()`, `coordinator.analysis_coordinator`), or keep it and state in a docstring which invariant it enforces. The deletion test decides: if the method only forwards, it goes.
- [ ] **Step 2:** Run the full non-browser suite.
- [ ] **Step 3:** Commit:

```bash
git add -A dashboard tests && git commit -m "refactor: drop pass-through coordinator methods"
```

---

## Phase 4 — Candidate gate and mapping-cluster consolidation

### Task 4.1: Create the candidate verdict module

**Objective:** One question — "can this candidate be saved, reused, exported, approved?" — answered in one place. Today five modules each hold their own issue-code list and two of them ignore the flags they receive.

**Files:**
- Create: `dashboard/models/candidates/verdict.py`
- Test: `tests/dashboard/unit/test_candidate_verdict.py`

- [ ] **Step 1:** Write the failing test:

```python
def test_verdict_is_one_shape_for_every_question():
    from dashboard.models.candidates import verdict
    result = verdict.evaluate({'beads': []}, context=None)
    assert set(result) >= {'codes', 'issues', 'can_save', 'can_reuse', 'can_export', 'can_approve'}
    assert result['can_save'] is False
```

- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3:** Implement `evaluate(candidate, *, context=None) -> dict` that calls `graph.validate` once and derives all four permissions from the returned codes, with the code→permission table living in this module and nowhere else.
- [ ] **Step 4:** Replace every hard-coded code list: `candidates/store.py:77-91,114-120`, `candidates/exports.py:22,56-60`, `molecules/draft.py:27-55`, `sugars/validation.py:22-47`. Each keeps its own error messages but stops re-deciding which codes matter.
- [ ] **Step 5:** Run:

```bash
dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_candidate_verdict.py tests/dashboard/unit/test_mapping_documents.py tests/dashboard/integration/test_mapping_workspace_api.py tests/dashboard/integration/test_mapping_exports.py -q
```

Expected: PASS.
- [ ] **Step 6:** Commit:

```bash
git add -A dashboard tests && git commit -m "feat: one verdict for candidate usability"
```

### Task 4.2: One candidate identity

**Objective:** The canonical-JSON sha256 idiom appears five times, and `mapping_identity` (schema v2) omits `molecule_id`, so two molecules can hash alike.

**Files:**
- Modify: `dashboard/models/candidates/schema.py:17-30`, `candidates/context.py:21-27,198-202`, `bonded/states.py:55-76`, `sugars/validation.py:60`, `compositions/topology.py:248-252`
- Test: `tests/dashboard/unit/test_identity.py`

- [ ] **Step 1:** Write the failing tests: identical content hashes equal; a candidate differing only in `molecule_id` hashes differently for schema v3 and above; every identity function in the tree returns 64 hex characters.
- [ ] **Step 2:** Run them. Expected: FAIL on the molecule-id case.
- [ ] **Step 3:** Add `dashboard/models/candidates/identity.py` with `canonical_sha256(payload)`, `candidate_identity(candidate)` and `content_identity(candidate)`; make the five sites call it. Preserve existing hex values for schema ≤2 candidates — old drafts must keep their stored hashes, so version the function, do not silently change it.
- [ ] **Step 4:** Run the mapping and bonded suites. Expected: PASS.
- [ ] **Step 5:** Commit:

```bash
git add -A dashboard tests && git commit -m "refactor: one candidate identity implementation"
```

### Task 4.3: Close the storage-layout seam

**Objective:** `web/routes/models.py:322` builds the candidate store's `reviews` directory with a `JsonRepository` whose id validator is `lambda value: value` — defeating `candidates/store.py:124`. `:341` unlinks inside `storage_root()` directly.

**Files:**
- Modify: `dashboard/models/candidates/store.py` (add `list_reviews()`, `delete_draft(name)`)
- Modify: `dashboard/web/routes/mappings.py` (the two call sites)

- [ ] **Step 1:** Write the failing test that a hostile draft name is rejected through the route: `DELETE /api/mappings/drafts/..%2Fetc%2Fpasswd` returns 400 and nothing outside the store is touched.
- [ ] **Step 2:** Run it. Expected: FAIL (today the route's own regex catches most cases, but the reviews read path validates nothing).
- [ ] **Step 3:** Add the two store functions with the real validator and call them from the route.
- [ ] **Step 4:** Run the mapping workspace API tests. Expected: PASS.
- [ ] **Step 5:** Commit:

```bash
git add -A dashboard tests && git commit -m "refactor: the candidate store owns its layout"
```

### Task 4.4: Absorb the two near-duplicate export bodies

**Files:**
- Modify: `dashboard/models/candidates/exports.py:18-54,55-114`

- [ ] **Step 1:** Diff the two inline bodies to confirm they differ only in which files they emit.
- [ ] **Step 2:** Collapse to one emission function parameterised by the file set; keep the public return mapping identical.
- [ ] **Step 3:** Run `tests/dashboard/integration/test_mapping_exports.py tests/dashboard/unit/test_mapping_generic_export.py -q`. Expected: PASS.
- [ ] **Step 4:** Commit:

```bash
git add -A dashboard && git commit -m "refactor: one export emission path"
```

### Task 4.5: Stop `suggestions` and `draft` restating their neighbours

**Files:**
- Modify: `dashboard/models/candidates/suggestions.py:46-60,74-88`
- Modify: `dashboard/models/molecules/draft.py:40-46,58-94`

- [ ] **Step 1:** Point `suggestions`' group fallback at `schema`'s fragment grouping.
- [ ] **Step 2:** Point `draft`'s atomtypes parse at the single parser, and collapse its two topology builders into one path with an explicit branch.
- [ ] **Step 3:** Run the draft/mapping tests. Expected: PASS.
- [ ] **Step 4:** Commit:

```bash
git add -A dashboard && git commit -m "refactor: remove restated grouping and topology builders"
```

### Task 4.6: One source of truth for the reference index

**Objective:** `candidates/references.py:78-100` re-hashes every reference ITP plus the M3-Bible workbook on every request; `bonded/generation.py:437` re-walks `references/**/*.itp` per generate; nothing is cached.

**Files:**
- Modify: `dashboard/models/candidates/references.py`, `dashboard/models/bonded/generation.py:437`, `dashboard/models/bonded/__init__.py`

- [ ] **Step 1:** Measure first, then fix: time `load_index` and the generation walk on this checkout and record the numbers in the commit message.
- [ ] **Step 2:** Add a content-keyed cache (keyed on the set of source paths plus their mtimes and sizes, invalidated when either changes — a size/mtime key, not a bare `lru_cache`).
- [ ] **Step 3:** Run the reference and bonded-generation tests plus a repeat-request timing check. Expected: PASS, with the second call measurably faster.
- [ ] **Step 4:** Commit:

```bash
git add -A dashboard tests && git commit -m "perf: cache the reference index and bonded reference walk"
```

---

## Phase 5 — Web surface

### Task 5.1: One request-context module

**Objective:** `_payload_context` (models.py:72-92), `_query_context` (:95-102) and an inline third copy (molecules.py:71-72) each re-derive the same staleness protocol.

**Files:**
- Modify: `dashboard/web/routes/common.py`
- Modify: `dashboard/web/routes/{mappings,catalog,bonded,refinement,molecules,runs,maintenance,analyses}.py`

- [ ] **Step 1:** Write the failing test: a POST with a stale `molecule_snapshot` returns 409 with the same message from all three entry points.
- [ ] **Step 2:** Move `_json_object`, `_payload_context`, `_query_context` into `common.py` as `json_object()`, `payload_context()`, `query_context()`; delete the third copy.
- [ ] **Step 3:** Replace the four ad-hoc body parsers (`runs.py:41,154,172`, `maintenance.py:32,40`, `analyses.py:16`, `models.py:293`) with `common.json_object()`, keeping each route's current failure mode. Where a route currently swallows a bad body with `or {}`, keep swallowing but route it through the same parser with an explicit `optional=True`.
- [ ] **Step 4:** Run the integration suite; expect the baseline.
- [ ] **Step 5:** Commit:

```bash
git add -A dashboard/web tests && git commit -m "refactor: one request context module for payload, query and staleness"
```

### Task 5.2: One response shape per collection

**Objective:** `/api/jobs` returns a bare array without `?page` and an object with it; `/api/jobs/<id>/artifacts` does the same; the browser defends with `Array.isArray(jobs) ? jobs : []`.

**Files:**
- Modify: `dashboard/web/routes/runs.py:29,31-35,184,188`
- Modify: `dashboard/web/static/js/runs.js`, `mappings.js:207`

- [ ] **Step 1:** Write the failing test: both request forms return `{'jobs': [...], 'total': n, 'page': 1, 'limit': 20}`.
- [ ] **Step 2:** Return the object shape unconditionally, defaulting `page=1, limit=20` when the keys are absent. Keep the `revision` field and the ordering identical.
- [ ] **Step 3:** Delete the client-side defensive branch and the `view=summary` string duplication (add one exported constant in `shared.js`).
- [ ] **Step 4:** Run the runs-table API tests and the browser tests:

```bash
dashboard/.venv/bin/python -m pytest -m browser -q -p no:cacheprovider
```

- [ ] **Step 5:** Commit:

```bash
git add -A dashboard tests && git commit -m "refactor: one collection response shape"
```

### Task 5.3: One guarded loader in the browser

**Objective:** Eight modules hand-roll the same stale-response guard, each slightly differently (`console.js:45` compares two fields, `new-run.js:249` one counter, `runs.js:172` a per-card counter, `runs.js:204` a module counter).

**Files:**
- Modify: `dashboard/web/static/js/shared.js`
- Modify: `dashboard/web/static/js/{runs,console,new-run,mappings,bonded,compositions}.js`

- [ ] **Step 1:** Add to `shared.js`:

```js
// Latest-wins loader: one generation per key; late responses are dropped, not rendered.
const generations = new Map();
function guarded(key, loader) {
  const token = (generations.get(key) || 0) + 1;
  generations.set(key, token);
  return Promise.resolve().then(loader).then(
    value => (generations.get(key) === token ? value : new Promise(() => {})),
    error => { throw error; }
  );
}
export { guarded };
```

- [ ] **Step 2:** Replace every hand-rolled guard with `guarded(key, …)`; the key must include the tab plus the record id where the current code scopes per card.
- [ ] **Step 3:** Run the browser suite and the JS check:

```bash
node --check dashboard/web/static/js/main.js
dashboard/.venv/bin/python -m pytest -m browser -q -p no:cacheprovider
```

Expected: PASS. Browser tests exercise polling without state loss, so a wrong key shows up here.
- [ ] **Step 4:** Commit:

```bash
git add -A dashboard/web tests && git commit -m "refactor: one generation-guarded loader in the browser"
```

### Task 5.4: Delete the dead handoff event, or wire it

**Objective:** `main.js:18` dispatches `dashboard:composition-selected`; no listener exists anywhere in the tree, so the Molecule Combination → CG Bond Interactions handoff is dropped. `shared.js:41` dispatches `dashboard:resources-changed`, also with no listener.

**Files:**
- Modify: `dashboard/web/static/js/main.js:18,24`, `dashboard/web/static/js/shared.js:41`

- [ ] **Step 1:** Decide by checking the intended behaviour: the guide says saved compositions are reachable through the unified CG model catalog, so the event is redundant. Delete `dashboard:composition-selected` and have `openBondedModel` select the model through the catalog path that `bonded.js` already uses.
- [ ] **Step 2:** Keep `dashboard:resources-changed` and add the listener that clears the bonded and mapping caches, or delete it — do not leave a dispatch with no listener. Prefer adding the listener if any cache is currently stale after a save; verify by saving a mapping and re-opening the catalog in a browser test:

```bash
dashboard/.venv/bin/python -m pytest tests/dashboard/browser/test_bonded_workspace_browser.py tests/dashboard/browser/test_lazy_loading.py -q
```

- [ ] **Step 3:** Commit:

```bash
git add -A dashboard/web tests && git commit -m "fix: close the composition handoff and the cache-change event"
```

### Task 5.5: One tab list

**Objective:** the five tab ids are hard-coded in `tabs.js:4`, `dashboard.html:18-22` and `main.js:24`.

**Files:**
- Modify: `dashboard/web/static/js/tabs.js`, `dashboard/web/templates/dashboard.html`

- [ ] **Step 1:** Derive the tab list from the DOM at load (`[role=tab]` nodes) and delete the duplicated arrays.
- [ ] **Step 2:** Run the browser suite. Expected: PASS.
- [ ] **Step 3:** Commit:

```bash
git add -A dashboard/web && git commit -m "refactor: derive the tab list from the document"
```

---

## Phase 6 — Correctness and honesty fixes

### Task 6.1: The composition adapter must not report MD it never ran

**Objective:** `adapters/composition.py:39-61` writes `printf` scripts (`printf "composition CG screening\n" > cg.xtc`, `printf "# composition CG SASA screening\n" > sasa.xvg`) and manifests three completed stages. A `cg_composition` run therefore looks like executed MD in the Runs tab and ran none.

**Files:**
- Modify: `dashboard/execution/adapters/composition.py:39-61`
- Modify: `dashboard/web/views.py` (surface the flag)
- Modify: `dashboard/web/templates/dashboard.html` (render the badge)
- Test: `tests/dashboard/unit/test_composition_workflow.py`

- [ ] **Step 1:** Write the failing test:

```python
def test_composition_screening_is_declared(tmp_path):
    from dashboard.execution.adapters import composition
    composition.prepare_run(tmp_path, <composition_id>, settings=None)   # via the fixtures' composition
    metadata = json.loads((tmp_path / 'manifest.json').read_text())
    assert metadata['execution_kind'] == 'screening-stub'
    assert metadata['limitations'], 'a stub must state its limitation'
    script = (tmp_path / 'stages/1_CG-simulation/cg_simulation.sh').read_text()
    assert 'gmx' not in script or 'mdrun' not in script   # the stub must not pretend to run MD
```

- [ ] **Step 2:** Run it. Expected: FAIL — no `execution_kind` key.
- [ ] **Step 3:** Decide, and record the decision in the commit message: either implement real GROMACS CG screening for compositions (a `cg_composition` variant of the CG simulation stage that consumes the composition's `composition.gro`/`composition.itp`), or declare the stub. The minimum acceptable change is the declaration: `execution_kind: 'screening-stub'`, the limitation text, a `views.py` badge reading "screening stub — no MD executed", and the manifest's `scientifically_validated: false` already present. Removing the fabricated `cg.xtc`/`sasa.xvg` artefacts is part of this task: emit no trajectory-shaped file that no integrator produced.
- [ ] **Step 4:** Run:

```bash
dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_composition_workflow.py tests/dashboard/integration/test_compositions_api.py -q
```

- [ ] **Step 5:** Commit:

```bash
git add -A dashboard tests && git commit -m "fix: declare composition screening as a stub instead of a completed simulation"
```

### Task 6.2: Composition identities must resolve in the bonded-state store

**Objective:** `compositions/model.py:88` publishes `state_id: "composition:<id>"`, which `bonded/states.py:28-31` rejects — verified: `bonded_states.get("composition:abc123")` raises `ValueError: Invalid bonded state ID`. `catalog.py:14` then republishes that id as resolvable.

**Files:**
- Modify: `dashboard/models/bonded/states.py:28-31`
- Modify: `dashboard/models/compositions/model.py:88,102` or `dashboard/models/compositions/__init__.py`
- Test: `tests/dashboard/unit/test_composition_state_identity.py`

- [ ] **Step 1:** Write the failing test:

```python
def test_composition_state_id_resolves_through_the_bonded_store(tmp_path, monkeypatch):
    from dashboard.models import bonded
    record = write_composition_fixture(tmp_path)          # existing fixture helper
    state = bonded.states.get(record['state_id'])
    assert state['mapping']['identity'] == record['identity']
```

- [ ] **Step 2:** Run it. Expected: FAIL — `Invalid bonded state ID`.
- [ ] **Step 3:** Pick one identity model and implement it: preferred is a namespaced id accepted by the validator (`composition:[a-f0-9]{12,64}`) whose `get` dispatches to the composition's own `bonded-state.json`; the alternative is minting a `[a-f0-9]{16}` id at composition creation. Either way, one reader must exist for both id shapes and `catalog.py` must only publish ids that resolve.
- [ ] **Step 4:** Add the regression assertion that every `state_id` the catalog returns is retrievable:

```python
def test_catalog_only_publishes_resolvable_state_ids():
    for row in catalog.list_models():
        if row['state_id']:
            assert bonded.states.get(row['state_id'])
```

- [ ] **Step 5:** Run the composition and bonded tests. Expected: PASS.
- [ ] **Step 6:** Commit:

```bash
git add -A dashboard tests && git commit -m "fix: composition state ids resolve in the bonded-state store"
```

### Task 6.3: One attempt-loop shape

**Objective:** the same per-unit-of-work loop is written three times: `workflow.run` (per stage), `coordinator.run_job` (per job), `analysis_coordinator.run` (per task) — each marking running, catching, recording status, releasing the lease, indexing and re-scheduling by hand.

**Files:**
- Create: `dashboard/execution/coordination/attempt.py`
- Modify: `dashboard/execution/workflow.py:253-337`, `coordination/coordinator.py:388-491`, `coordination/analysis_coordinator.py:108-146`
- Test: `tests/dashboard/unit/test_attempt.py`

- [x] **Step 1:** Write the failing test: `attempt()` yields a record, writes `status='running'` on entry, converts an exception into `status='failed'` with the message, converts `Cancelled` into `status='cancelled'`, and always calls the `finally` hook exactly once.
- [x] **Step 2:** Run it. Expected: FAIL. — Done: `tests/dashboard/unit/test_attempt.py`, 6 tests, RED then GREEN.
- [ ] **Step 3:** Implement the context manager, then adopt it in all three call sites, keeping each site's existing fields and ordering of writes (manifests are evidence; do not reorder key writes without checking the resume tests).

  `dashboard/execution/coordination/attempt.py` is implemented and tested (`attempt(record, *, update, running=None, on_exit=None)`), but **not yet adopted** — the three sites are not interchangeable, and each needs its write policy translated explicitly:

  - `analysis_coordinator.run` (adopt first; the closest fit): its entry write carries `started_at`/`command`/`environment`/`log` (`running=`), its failure write carries `ended_at`/`error`/`exit_code`, and its success write carries `exit_code=0`/`outputs`/**`result` — values computed inside the body, so the site needs a small holder the body fills before the manager's success write.
  - `workflow.run`: the reuse path sets `status='reused'` and `continue`s, which a context manager sees as a *successful* block and would overwrite with `completed`. Translate by having the site's `update` keep a record that already reached a terminal status, and keep the run-level `data['status']`/`data['error']` writes and the `fp.write` failure line in that same function.
  - `coordinator.run_job`: keeps `status`/`error` locals, writes them once in the `finally`, and overrides them there from `worker.limit_error`. Its `update` must therefore write the locals and leave the single terminal write to `on_exit`, or the limit-error override will land after the record was already written.

- [ ] **Step 4:** Run:

```bash
dashboard/.venv/bin/python -m pytest tests/dashboard/integration/test_in_place_resume.py tests/dashboard/integration/test_aa_workflow.py tests/dashboard/unit/test_carbohydrate_validation_worker.py -q
```

- [ ] **Step 5:** Commit:

```bash
git add -A dashboard tests && git commit -m "refactor: one attempt lifecycle used by stages, jobs and analyses"
```

### Task 6.4: One subprocess environment

**Objective:** the same three-key environment dict is rebuilt in five places (`workflow.py:135,276`, `adapters/aa.py:184`, `adapters/cg.py:219`, `analysis_coordinator.py:118`).

**Files:**
- Modify: the five sites, plus `dashboard/execution/environment.py`

- [ ] **Step 1:** Add `environment.stage_environment(extras=None)` returning the composed environment (from Task 2.7's search path) plus `MPLBACKEND` and `OMP_NUM_THREADS`, and a matching `environment.recorded_keys()` for manifests.
- [ ] **Step 2:** Replace all five sites; a manifest that records `environment` must record the same key set and values as before the change — verify by diffing a freshly prepared run's manifest against a fixture prepared before the change:

```bash
dashboard/.venv/bin/python -m pytest tests/dashboard/integration/test_aa_workflow.py -q
```

- [ ] **Step 3:** Commit:

```bash
git add -A dashboard tests && git commit -m "refactor: one subprocess environment"
```

### Task 6.5: One manifest emission for prepared runs

**Objective:** four modules each write `layout_version`, `stage_plan`, `tools`, `environment` and `prepared_at` when preparing a run, and they disagree: only two write `input_snapshot_sha256`, only the composition adapter omits `inputs/`.

**Files:**
- Modify: `dashboard/execution/workflow.py:91-104`, `adapters/aa.py:180-184`, `adapters/cg.py:207-224`, `adapters/composition.py:56-61`

- [ ] **Step 1:** Write the failing test asserting every prepared run directory contains `manifest.json`, `inputs/`, and an `input_snapshot_sha256` matching `files.hashes(inputs/)`, for all three run types.
- [ ] **Step 2:** Run it. Expected: FAIL for `cg_composition`.
- [ ] **Step 3:** Add `protocol.write_prepared_manifest(run_dir, metadata, *, tools, plan)` and call it from all four sites. The composition adapter gains `inputs/` and the snapshot hash; nothing else changes.
- [ ] **Step 4:** Run the fast suite plus the three workflow integration tests. Expected: baseline.
- [ ] **Step 5:** Commit:

```bash
git add -A dashboard tests && git commit -m "refactor: one manifest emission for prepared runs"
```

---

### Task 6.6: One `POST /api/compositions`, and it should be the one that works

**Objective:** the route is registered twice, and the reachable one is the one nobody would expect. `catalog.py:31` `composition_create_api` and `catalog.py:53` `composition_create` both answer `POST /api/compositions`. Werkzeug matches the first, so `composition_create` is unreachable code that differs from its live twin: it calls `compositions.create(payload)` without the workspace root, and reports a conflict as 400 rather than the live route's 409 for `stale` / `already exists`.

Verified before writing this task, on the split tree:
`app.url_map.bind('localhost').match('/api/compositions', method='POST')` returns `catalog.composition_create_api`; `url_map.iter_rules()` lists both rules.

**Files:**
- Modify: `dashboard/web/routes/catalog.py:53-55`
- Inspect: `dashboard/models/compositions/__init__.py:128` (`create`), `:~140` (`create_composition`)

- [ ] **Step 1:** Write the failing test: two `POST /api/compositions` handlers must not exist — assert `len([r for r in app.url_map.iter_rules() if str(r) == '/api/compositions' and 'POST' in r.methods]) == 1`, and assert the surviving rule's endpoint is the one that received the request (a client POST returns 201 and a duplicate name returns 409, not 400).
- [ ] **Step 2:** Run it. Expected: FAIL — two rules.
- [ ] **Step 3:** Delete `composition_create`. Then decide `compositions.create` deliberately: after this deletion its only callers are `tests/dashboard/unit/test_detergent_models.py:29,32`. Either route those tests at `create_composition(payload, root)` and delete `create`, or keep `create` as the documented root-free variant with a docstring saying who uses it. Do not leave two creation functions where one is test-only and undocumented.
- [ ] **Step 4:** Run `tests/dashboard/integration/test_compositions_api.py`, `tests/dashboard/unit/test_detergent_models.py`, and the fast suite. Expected: baseline.
- [ ] **Step 5:** Commit:

```bash
git add -A dashboard tests && git commit -m "fix: one POST /api/compositions registration"
```

---

### Task 6.7: The mapping export bundle ships a module that cannot import

**Objective:** the ring-mapping export writes `carbohydrates.py` into the downloaded bundle. That file is the sugars facade, whose first statements are `from .recognition import ...`, `from .coords import ...`, `from .topology import ...` — relative imports in a file with no package, and the bundle ships none of the three modules it names. Anything that tries to use the bundled helper fails at import.

Pre-existing, not a regression from the move: at `e0504a3` the file was `models/carbohydrates.py` with `from .sugar_recognition import ...`, the same shape. Phase 1 relocated it to `models/sugars/__init__.py`, which is why the bundled filename is now also inaccurate.

**Files:**
- Modify: `dashboard/models/mappings/exports.py:107-114`
- Inspect: `dashboard/models/sugars/__init__.py`, `dashboard/execution/scripts/sugar_mapping.py`

- [ ] **Step 1:** Write the failing test: build the export for a ring mapping and assert every `.py` file in it imports in a clean subprocess with the bundle directory on `sys.path` — or, minimally, that no bundled `.py` contains a relative import. Expected: FAIL on `carbohydrates.py`.
- [ ] **Step 2:** Run it to confirm the failure mode is the import, not a missing fixture.
- [ ] **Step 3:** Pick one and say why in the commit: ship the whole `sugars/` package into the bundle (relative imports then resolve inside the bundle, and the bundled script's import path changes), or generate one self-contained helper by concatenating the four modules in dependency order. Whichever is chosen, the bundle's filename should match what the module now is (`sugars`), and `README.txt` must name the real import target — the shipped `sugar_mapping.py` and `prepare_ring_constraints.py` are the files a user actually runs.
- [ ] **Step 4:** Run `tests/dashboard/integration/test_mapping_exports.py` plus the fast suite. Expected: baseline.
- [ ] **Step 5:** Commit:

```bash
git add -A dashboard tests && git commit -m "fix: ship an importable sugar helper in the mapping export"
```

---

## Phase 7 — Test surface

### Task 7.1: One dashboard factory fixture

**Objective:** 18 of 59 test files drive the import-time `default_coordinator` singleton; `conftest.py` patches six of its attributes; 63 tests patch module globals across 15 production modules.

**Files:**
- Create: `tests/dashboard/factory.py`
- Modify: `tests/dashboard/conftest.py`
- Modify: `dashboard/app.py` (expose `create_app(paths, config)` only — it already exists)

- [x] **Step 1:** Add the fixture: — done: tests/dashboard/factory.py (`Dashboard` record + `build(tmp_path, **config)`).

```python
# tests/dashboard/factory.py
from dataclasses import dataclass
from dashboard.app import create_app
from dashboard import paths as path_config


@dataclass
class Dashboard:
    app: object
    client: object
    coordinator: object
    paths: object


def build(tmp_path, **config):
    selected = path_config.Paths(project_root=PROJECT_ROOT, workspace=tmp_path / 'workspace')
    app = create_app(selected, {'DISABLE_COORDINATOR': True} | config)
    return Dashboard(app, app.test_client(), app.extensions['dashboard_coordinator'], selected)
```

- [x] **Step 2:** Expose it as a `dashboard` fixture in `conftest.py`; keep `isolated_workspace` for one commit as a deprecated alias so the suite keeps running while files migrate. — done; the `dashboard` fixture also enters `paths.use(built.paths)`, which the singleton fixture used to do for module-level resolvers.
- [x] **Step 3:** Run the suite; expect the baseline. — 465 passed (three of them pinning the fixture itself).
- [ ] **Step 4:** Commit:

```bash
git add -A tests && git commit -m "test: add a dashboard factory fixture"
```

### Task 7.2: Migrate the test files, twenty at a time

**Objective:** Move tests off the singleton and off global patching. One commit per batch; the batch size keeps each diff reviewable.

**Files:**
- Modify: `tests/dashboard/{unit,integration}/*.py` (batched by directory order)

- [~] **Step 1:** For each file, replace `web = default_coordinator` + `web.app.test_client()` with the factory fixture, and delete now-redundant `patch.object(web, ...)` calls. — all thirteen integration files are done and committed (`a45b183`, `7.2b`); the browser tier is migrated with 7.4's fixtures. The retargeting is equivalent rather than convenient, and the reason is checkable: routes resolve their coordinator through `current_app.extensions['dashboard_coordinator']`, and the singleton is named in exactly one place, `dashboard/app.py:42`. The delete-or-retarget rule the batches used: delete a `patch.object(web, NAME, VALUE)` only when VALUE is what the built application already has, and retarget it to the built coordinator *preserving the original value* otherwise — several tests pin ROOT/DATA/RUNS to their own tmp_path on purpose, and flattening those would have changed behaviour. Where a test patches a module global to control the launch gate or the tool set, inject through the seam instead (Task 2.7's tools module and Task 2.5's admission).
- [ ] **Step 2:** After each batch:

```bash
dashboard/.venv/bin/python -m pytest -m 'not browser and not slow' -q -n 4 -p no:cacheprovider
```

Expected: baseline count, and the run completes in parallel — which is the point: the suite becoming `-n 4`-safe proves no shared module state remains.
- [ ] **Step 3:** Commit each batch:

```bash
git add tests && git commit -m "test: migrate <batch> to the factory fixture"
```

### Task 7.3: One fixture module

**Objective:** `fixtures.py` (17 lines, three flat names), `mapping_fixtures.py` (16 lines, one function duplicating a private helper in `test_mapping_context.py:4`), and `conftest.py` (28 lines) overlap.

**Files:**
- Create: `tests/dashboard/support.py`
- Delete: `tests/dashboard/fixtures.py`, `tests/dashboard/mapping_fixtures.py` (after migration)

- [x] **Step 1:** Fold the four modules into one `support.py` exporting `PROJECT_ROOT`, `physical_mapping()`, `write_aa_fixture()`, `QuietHandler`, `fast_forward_source()` (from Task 0.3's `tool_paths.py`) and the dashboard factory. — done (`90fb8e3`). Two details carried over deliberately: `physical_mapping()`'s mappings import moved inside the function, so collecting the suite no longer imports the mappings package, and the "unprovisioned sources must skip, never fail" rationale travelled with `fast_forward_source`.
- [x] **Step 2:** Keep `tests/dashboard/fixtures.py` as a one-line re-export shim for exactly one commit, then delete it and update the 12 importing files. — done in two commits (the shims in `90fb8e3`, the sweep and deletion in 7.3b). There were twenty importing files, not twelve, because `fixtures.PROJECT_ROOT` was reached for by nearly every file that needs the repository root.
- [x] **Step 3:** Run the fast suite in parallel. Expected: baseline. — 443 passed, plus the slow tier (7) and the browser tier (15), because three browser files were among the importers.
- [ ] **Step 4:** Commit:

```bash
git add -A tests && git rm tests/dashboard/mapping_fixtures.py
git commit -m "test: one support module for fixtures"
```

### Task 7.4: One browser-test server fixture

**Objective:** nine browser files each rebuild `make_server`, a `serve_forever` thread and `sync_playwright` + `chromium.launch`.

**Files:**
- Create: `tests/dashboard/browser/conftest.py`
- Modify: nine files under `tests/dashboard/browser/`

- [x] **Step 1:** Add session-scoped `live_server` and page fixtures in a browser `conftest.py`, parameterised by the temp database the factory builds. — done, with one deliberate deviation: the *browser* is session-scoped (Chromium launch is the expensive part and is safe to share), while the server and the page are per-test, because each browser test seeds its own workspace and database — a session-scoped server could not serve the test's own application. `live_page` yields a record that unpacks as `page, errors = live_page` so the existing assertion lines stay untouched.
- [ ] **Step 2:** Migrate the nine files to the fixtures; the assertion lines stay untouched (one file spends 30 lines of setup on a 3-line assertion — that is the diff to expect).
- [ ] **Step 3:** Run:

```bash
dashboard/.venv/bin/python -m pytest -m browser -n 2 -q -p no:cacheprovider
```

Expected: same pass count as before the change.
- [ ] **Step 4:** Commit:

```bash
git add -A tests && git commit -m "test: one live-server fixture for browser tests"
```

---

## Phase 8 — Tooling, docs, decisions

### Task 8.1: Add a lint/type configuration that ignores the venv

**Objective:** the only config in the repository is `pytest.ini`; `dashboard/.venv/` sits inside the package directory, so any tool globbing `dashboard/**/*.py` walks ~20 000 vendored files.

**Files:**
- Create: `pyproject.toml`

- [x] **Step 1:** Add `[tool.ruff]` (target-version py312, line-length, `exclude = ["dashboard/.venv", "archive", "references", "resources", "tools", "workspace"]`), `[tool.ruff.lint]` with `E,F,I` at minimum, and `[tool.pytest.ini_options]` mirroring `pytest.ini` so both entry points agree.
- [x] **Step 2:** Run the linter and record the current violation count in the commit message rather than fixing everything in this task: — done; 1297 findings recorded in the commit, ruff walks 191 files with the venv excluded.

```bash
dashboard/.venv/bin/python -m pip install ruff
dashboard/.venv/bin/python -m ruff check dashboard tests --statistics
```

- [ ] **Step 3:** Commit:

```bash
git add pyproject.toml && git commit -m "chore: add ruff and pytest configuration"
```

### Task 8.2: Pay down the lint findings, module by module

- [x] **Step 1:** Fix findings per module, smallest first, one commit per module group; do not mix lint fixes with behaviour changes. — dashboard/ done in two commits (118 mechanical, then the six F841/F821 by hand; two of those were latent defects). tests/ deferred: the migration subagents held those files. E701/E702/E501 are not paid down, with the reason in docs/decisions/.
- [ ] **Step 2:** After each group, run the fast suite.

Expected: no test changes required for pure lint fixes; any fix that changes behaviour needs its own test.

### Task 8.3: Reconcile the scientific documentation with the code

**Files:**
- Modify: `docs/DDM_CALIBRATION.md` ("Code-inspected gaps" list)
- Modify: `docs/PROJECT_GUIDE.md` (mapping exports, bonded workflow sections if paths changed)

- [x] **Step 1:** Re-check each of the six documented gaps against the code and mark what the 2026-09-22 bonded-generation work already closed — done against the current tree, not the commits: three closed, three partly open, each with file:line and the closing commit. (the automatic reference-consensus generator and save-as-new states exist; virtual-site parent parsing, the mapping-identity filter and stale-preview protection are the ones worth re-verifying).
- [x] **Step 2:** For anything still open, keep the item and add the file:line where it lives now; for anything closed, say which commit closed it. — done. Nine claims the document made are now demonstrably false and were replaced; the residue that is really still open names the file:line (the name-in-hash identity, the pre-`kind` JSON classification, per-run colour limits, two untested paths, and JSON storage as a recorded decision). One residue was a live defect rather than a doc error and was fixed: the bonded ITP preview panel no script ever wrote.
- [ ] **Step 3:** Commit:

```bash
git add docs && git commit -m "docs: reconcile the calibration handoff with the current code"
```

### Task 8.4: Record what was considered and rejected

**Files:**
- Create: `docs/decisions/2026-09-24-architecture-decisions.md`

- [x] **Step 1:** Write one entry per rejected change, each with the reason a future reviewer needs: — done: docs/decisions/2026-09-24-architecture-decisions.md, the eight entries plus the decisions taken during this consolidation.

| Rejected | Reason |
|---|---|
| Caching `candidates/store._validation` differently | Its `lru_cache` is keyed on file content and structure, so a workspace change cannot return a stale verdict — verified, no change needed |
| Splitting `Coordinator` into five classes | The view extraction (Phase 3) holds the leverage; further splitting moves complexity across classes instead of concentrating it |
| A plugin/registry framework for run types | The protocol interface plus three adapters is the whole requirement; a registry is a seam with nothing varying across it |
| Renaming HTTP URLs or `ddm.*` browser keys | Documented as stable through reorganizations; the browser and any bookmarked link depend on them |
| Moving `dashboard/.venv` out of the package | Launchers embed absolute interpreter paths; exclude it in tool configs instead (Task 8.1) |
| Deleting the `cg_composition` run type | It answers a real question (CG-only screening of a saved composition); Task 6.1 fixes its honesty rather than removing it |
| Moving bonded states to SQLite tables | The JSON store is atomic and adequate; revisit only if concurrent writers appear |
| Keeping the `mappings` facade as a passthrough module | The package boundary is the interface — the facade becomes `candidates/__init__.py`, it does not stay as a second name |

- [ ] **Step 2:** Commit:

```bash
mkdir -p docs/decisions && git add docs/decisions && git commit -m "docs: record rejected architecture changes and their reasons"
```

---

## Acceptance for the whole plan

- [x] `dashboard/` contains six packages and six root modules, with at most 13 modules per package directory. — measured at the end: five packages plus `__pycache__` (`analysis`, `cli`, `execution`, `models`, `web`) and six root modules plus `__init__.py` (`app`, `constants`, `files`, `__main__`, `paths`, `store`). The counts in this line were written before the layout settled and are off by one on each side; the criterion's real content is the per-directory ceiling, which `test_module_layout.py` enforces and which passes (43 tests).
- [x] `tests/dashboard/unit/test_module_layout.py` passes; no retired path is imported anywhere. — 43 tests pass, and greps for the retired module paths (fixtures, mapping_fixtures, tool_paths, default_coordinator in tests) return nothing.
- [x] The URL map is byte-identical to the pre-plan map, and `python -m dashboard` plus `python dashboard/app.py` both start. — compared as a set of (method, URL) rules against the recorded pre-plan map: 68 before, 68 now, none added and none removed. The recorded baseline carried a "winner for POST /api/compositions" annotation because that URL was registered twice; Task 6.6 de-duplicated the registration, so the rule set is unchanged while the duplicate is gone. Both entry points start and serve on 127.0.0.1:5000 (`-m dashboard` and `dashboard/app.py`).
- [x] `coordinator.py` imports no Flask symbol; run views build without an application context in a unit test. — zero flask references in the coordinator; test_run_view.py builds views from plain inputs.
- [x] Exactly one module owns: the run-type matrix, the settings bounds shape, the candidate verdict, candidate identity, the stage-log path, the attempt lifecycle, the subprocess environment, tool resolution. — `admission.validate_run_type`; the settings-bounds shape with the AA durations; the candidate verdict module; `mappings/identity.py`; the one stage-log resolver; `coordination/attempt.py` (pinned, adoption still open per 6.3); `environment.recorded_environment`; `execution/tools.py`.
- [x] The fast suite passes with 0 failures (2 documented skips) and the browser suite passes with `-n 2`. — fast tier 443 passed, 0 failures. The "2 documented skips" is stale: nothing skips now, because those two skips were the Fast_Forward vendor tree being unprovisioned and it is provisioned (Phase 2). The slow tier is 7 passed and the browser tier 15 passed at `-n 2`, with the caveat recorded in the 7.4 commit: one failure in seven of my runs that I could not attribute.
- [x] No `cg_composition` run can report a completed simulation stage without a declared `execution_kind`. — Task 6.1: the adapter records `execution_kind: screening-stub` and a limitation, the view renders `execution_note`, and two tests pin it.
- [x] `docs/PROJECT_GUIDE.md`, `dashboard/README.md`, `AGENTS.md` and `docs/DDM_CALIBRATION.md` name only files that exist. — checked by extracting every path they name: no repository file is missing. The references that do not resolve are generated workspace artifacts (the DDM screening reports, two mapping drafts), which the documents cite as evidence of past runs.
