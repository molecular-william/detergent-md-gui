# Modular test packages: move each module's tests into its distribution

Status: **done, 2026-10-29**, in six commits through `8612cca`. Written at `1455d1e`, after the source split
and the ownership axis; executed with `--import-mode=importlib`, as chosen at Phase 3.
Predecessor state: the suite already divides by *subject* (`tests/dashboard/areas.py`) and by *owning distribution*
(`tests/dashboard/modules.py`, `-m core|validation|pdc`, `scripts/test_module.sh`). What remains is the physical
layout: every test still lives in one `tests/dashboard/` tree, so a feature cannot be developed or tested from its
own package directory and its tests cannot be shipped or excluded by its own project file.

## Goal

```
packages/core/tests/{unit,integration,browser}/...        # 188 files, 1465 collected tests  (core)
packages/validation/tests/{unit,integration,browser}/...  #  29 files,  312 collected tests  (validation)
packages/pdc/tests/{unit,integration,browser}/...         #  70 files,  662 collected tests  (pdc)
tests/harness/                                            # shared fixtures/plugins, never collected
tests/__init__.py                                         # keeps `tests.harness` importable
pytest.ini                                                # one root config, four paths
```

Acceptance is the same suite, same result, with three independently runnable trees:

- `pytest packages/core/tests` (fast/browser/slow tiers still selected by `-m`).
- `pytest packages/validation/tests`, `pytest packages/pdc/tests`.
- Running from a package directory also works: `cd packages/validation && ../../.venv/bin/python -m pytest tests`.
- `pytest` (from the repo root) still collects all 2439 tests; counts per tree/browser/area unchanged.
- A feature wheel still carries no tests, and each package's `pyproject.toml` remains the only description of its
  package tree.

## Current inventory (measure again before starting)

| fact | value |
| --- | --- |
| test files | 287 (`tests/dashboard/{unit:196, integration:54, browser:37}`) |
| collected tests | 2439 = 2186 fast passes + 1 fast xfail + 235 browser + 17 slow |
| per-module files | core 188 (unit 126, integration 42, browser 22); validation 29 (21/6/2); pdc 70 (50/6/13) |
| shared-harness modules | `tests/dashboard/{support.py (185), factory.py (30), bond_fixtures.py, pdc_fixtures.py, areas.py, modules.py, conftest.py (80), browser/conftest.py (95), browser/panels.py}` |
| tests importing the harness | 123 files (`tests.dashboard.support` / `from tests.dashboard import ...`) |
| tests computing the checkout from `__file__` | 38 files, 43 occurrences: `parents[3]` (36), `parents[1]` (6), `parents[2]` (1) |
| cross-test helper imports | 24 import lines using `tests.dashboard.pdc_fixtures`, `...bond_fixtures`, and two test modules' symbols (`unit/test_mapping_context._write_fixture`, `unit/test_pdc_prepare.TEMPLATE_PATH`/`molecule_tree`) |
| tooling that names test paths | `scripts/mutants.json` (11), `scripts/gate_commit.sh`, `scripts/test_module.sh`, `pytest.ini`, `README.md`, AGENTS/PROJECT_GUIDE/HANDOFF |

Cross-module duplicate basenames: **none** today; verify again after the move (it decides whether `importlib` mode
is required).

## Baseline recorded (2026-10-29, `bc6678a`, clean tree)

Phase 0 measured. Comparable numbers for every later phase:

| measurement | recorded | Phase 0 expectation |
| --- | --- | --- |
| fast tier, `-n 8 --dist loadfile` | **2186 passed, 1 xfailed** (26 s) | 2186 + 1 xfail |
| browser tier, `-n 16 --dist worksteal` | 235 collected; three full runs gave **234+1**, **233+2**, **234+1** | 235 passed |
| browser tier, `-n 0` | **234 passed, 1 failed** (343 s) | -- |
| slow tier, `-n 0` | **17 passed** (43 s) | 17 |
| `--collect-only -q` | **2439** | 2439 |
| per module (`-m core\|validation\|pdc`) | **1465 / 312 / 662** | 1465 / 312 / 662 |
| `ruff check packages tests scripts` | clean | -- |

The expected xfail is
`tests/dashboard/integration/test_pdc_preview_api.py::test_the_route_reads_the_preparation_choice_and_refuses_a_value_that_is_not_one`.

**The browser tier is flaky at this commit, independent of the move.** Four different tests failed across three full
runs -- `test_bead_editor_controls_browser.py::test_add_and_delete_beads_...`,
`test_mapping_overlay3d_browser.py::test_every_sphere_sits_...`, and twice
`test_bonded_parameterization_browser.py` (`::test_a_running_job_...`, `::test_a_fit_answer_that_arrives_...`). Every
failed test passed alone. The fit-answer one failed **1 in 5** solo runs, spending 15 s in an expectation that resolved
to "Choose an AA reference: this engine fits to its ensemble": the reference picker is re-rendered between the test's
`wait_for_function` and its click, so the button is disabled again when clicked. That is a race in the test's own
re-apply loop, not load and not layout. Phase 5 must compare the failure *set* against this note, not demand 235/235,
until the flake is fixed.

### Inventory re-measured (supersedes the table above)

- Test files **288**: unit 197 / integration 54 / browser 37. The +1 is `unit/test_test_modules.py`, added in
  `1455d1e`; the table's 287 describes `4f295a5`.
- Per module **190 / 29 / 69** (core/validation/pdc). The table's totals of 188 and 70 contradict its own parenthetical
  splits, which sum to 190 and 69; the measured values match the splits.
- Files importing the harness: **60** (61 import lines), not 123. `__file__` checkout computations: **37 files, 38
  uses** (`parents[3]` 36, `parents[2]` 1, `parents[1]` 1), not 38/43. Cross-test helper imports: **24** (match).
- **A duplicate basename exists:** `test_assessment_rescore.py` in both `unit/` and `integration/`, so the "none" above
  is stale. They do not collide today only because both directories are `__init__.py` packages. Phase 3 must therefore
  keep an `__init__.py` chain under `packages/<module>/tests/` **or** adopt `--import-mode=importlib`, or prepend mode
  will import the two files under one module name.
- Harness sizes: support 185, factory 30, bond_fixtures 60, pdc_fixtures 172, areas 112, modules 57, conftest 80,
  browser/conftest 95, browser/panels 105 lines.

## Decisions to implement (resolve these; do not re-derive from scratch)

1. **Harness stays at the repository root** as `tests/harness/`, outside every distribution. It is not shipped and
   imports the engine, so it cannot live in `packages/core` without making feature tests depend on the engine's test
   package. Move `support.py`, `factory.py`, `bond_fixtures.py`, `pdc_fixtures.py` there; rename neither their APIs
   beyond the module path, so the 123 import lines are a mechanical rewrite. `browser/panels.py` and the browser
   fixtures become `tests/harness/browser.py` / `browser_plugin.py`.
2. **Fixtures are a pytest plugin, loaded from a new root `conftest.py`.** Move the contents of
   `tests/dashboard/conftest.py` (MPLCONFIGDIR, martini3, `dashboard`, `isolated_workspace`, the collection hook) and
   `tests/dashboard/browser/conftest.py` (`browser`, `live_page`, expectation timeout) into
   `tests/harness/plugin.py` and `tests/harness/browser_plugin.py`. The root conftest inserts the repository root
   into `sys.path` itself and declares `pytest_plugins = ('tests.harness.plugin', 'tests.harness.browser_plugin')`, so
   it works whether pytest is started at the root or inside a package.
3. **One root `pytest.ini`.** `testpaths` becomes the three trees (not `tests`). Keep `addopts = -n 8 --dist loadfile
   --strict-markers`; register `core/validation/pdc` markers (already present). If collection reports import-mode
   collisions after the move (it should not: no duplicate basenames), switch to `--import-mode=importlib` rather than
   adding `__init__.py` one by one.
4. **The owning tree is the module.** Replace `modules.py`'s pattern table with path derivation:
   `packages/<core|validation|pdc>/tests/**` → that module, applied as a marker by the collection hook. Keep the
   `module_of(path)` API and the `-m` markers working; `test_test_modules.py` becomes: every collected file lives
   under exactly one of the three trees, every item carries exactly one module marker, and the three groups partition
   the suite. Keep `modules.py`'s current table only as the **migration manifest** until Phase 3 is green, then delete
   it (git history keeps it).
5. **Area patterns become tree-relative.** `areas.area_of` should strip `packages/<module>/tests/` and match the
   existing `unit/...`, `integration/...`, `browser/...` patterns, so one table keeps serving all trees. Keep
   `test_test_areas.py` failing on an unnamed module and on a module claimed twice.
6. **Path constants replace `__file__` arithmetic.** `tests/harness/support.py` already exports `PROJECT_ROOT` and
   `PACKAGE`; migrate the 38 `Path(__file__).resolve().parents[N]` sites to those (or `PACKAGE`), because every move
   changes N. Two sites (`sys.path.insert(0, str(PROJECT_ROOT))`, `PACKAGE / 'execution/scripts'`) stay, just import
   the constant.
7. **Cross-test helper imports resolve through the harness.** Move `pdc_fixtures`/`bond_fixtures` symbols to
   `tests/harness/`, and move the two test-module exports (`_write_fixture`, `TEMPLATE_PATH`/`molecule_tree`) into
   `harness/mapping_fixtures.py` / `harness/pdc_fixtures.py`; update the 24 use sites. No test module should import
   another test module afterwards (`grep -rn "tests.*\.test_"` must be empty).
8. **Tools follow the trees.** `scripts/test_module.sh <module> [tier]` runs `pytest packages/<module>/tests` with the
   tier expression (keep `-m` as the documented alias); `scripts/mutants.json`'s test selections and
   `scripts/gate_commit.sh`'s path handling move to the new paths; `pytest.ini`'s counts comment is refreshed.
9. **Wheel purity is checked, not assumed.** `packages/*/pyproject.toml` uses `packages.find where = ["src"]`, so
   `packages/<name>/tests` is outside the wheel. Verify with `pip wheel packages/<name>` +
   `unzip -l <wheel> | grep -c '/tests/' == 0` for all three, and record it in the final commit message. If you add a
   `test` extra per feature, it is dev-only and must not leak into dependencies.

## Phased execution (commit after each green phase)

**Phase 0 — baseline.** Clean tree; record:
```
MPLCONFIGDIR=$(mktemp -d) .venv/bin/python -m pytest -m 'not browser and not slow' -q   # expect 2186 + 1 xfail
... -m browser -q -n 8 --dist worksteal                                               # expect 235
... -m slow -q -n 0                                                                    # expect 17
pytest --collect-only -q | tail -1                                                     # expect 2439
```
Save the per-module counts (`-m core|validation|pdc --collect-only -q`) for the final comparison.

**Phase 1 — harness extraction, no test moves.** Create `tests/harness/{__init__,support,factory,bond_fixtures,
pdc_fixtures,plugin,browser_plugin}.py`; move the fixture/hook code; add root `conftest.py` with the `sys.path` insert
and `pytest_plugins`; point the 123 harness imports at `tests.harness`; delete `tests/dashboard/{support,factory,
bond_fixtures,pdc_fixtures,conftest.py,browser/conftest.py}`. Full suite must be identical (all three tiers). This is
the phase that proves the fixture plugin reach; do not move test files in the same commit.

**Phase 2 — path independence while files stay put.** Replace the 38 `__file__` computations with harness constants;
give `areas.py`/`modules.py` a `module_of`/`area_of` that accept any path (tree-relative matching); update
`test_test_areas`/`test_test_modules`; keep `scripts/test_module.sh` working. Run all three tiers.

**Phase 3 — the move.** Generate the manifest from the current `modules.py` and `git mv` in one commit:
```bash
.venv/bin/python - <<'PY'
from pathlib import Path
from tests.dashboard import modules
root = Path('tests/dashboard')
for path in sorted(root.rglob('test_*.py')):
    module = modules.module_of(path)
    target = Path(f'packages/{module}/tests') / path.relative_to(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f'git mv {path} {target}')
PY
```
Then: add `packages/<module>/tests/conftest.py` if needed for `cd packages/<module> && pytest tests` (a two-line
`sys.path` insert is acceptable; the root conftest should already cover the root invocation); update `pytest.ini`
`testpaths`; update `areas.py` root and `modules.py` to path-derived; update `test_test_modules.py` (tree partition),
`test_test_areas.py` (walk all trees), `scripts/mutants.json` (11 test selections), `scripts/test_module.sh`
(directory selection); rewrite the harness imports one more time only if the package dir name changed anything
(it should not); run each tree independently (fast, browser, slow) and the full tiers. Confirm counts: files 287,
collected 2439, per-tree 1465/312/662.

**Phase 4 — package ergonomics.** Verify the three per-package commands from inside each package directory; make
`pip install -e packages/<name>` (with the checkout's `.venv`) runnable without importing another feature's tests
(only `tests.harness` is shared); decide whether to add `[project.optional-dependencies] test` to each feature
(recommended: yes, pytest/playwright only, dev-only) and document it; check `python -m pip wheel` purity (Decision 9).

**Phase 5 — docs and final verification.** Update `PROJECT_GUIDE.md` (verification/testing section: three trees, how to
run one, the plugin/conftest arrangement, where new tests go), `README.md` (repository layout + verify block),
`AGENTS.md` (Verify line: `pytest packages/<module>/tests`; keep the 120-human-line budget — displace a line rather
than exceed it), `HANDOFF.md` (close this item, record the final counts and the one residual risk). Run:
fast 2186 + 1 xfail, browser 235, slow 17, per-module tiers, `ruff check packages tests scripts`,
`scripts/mutation_check.py` (11 mutants, 10 caught, 1 survived, 0 stale), `scripts/gate_commit.sh` on the moved
paths, wheel purity. Do not rebuild the mini or restart the live dashboard: no runtime code changes in this task.

## Hazards and mitigations

| hazard | mitigation |
| --- | --- |
| A fixture used by a test in another tree is not loaded | Root `pytest_plugins` plugin; prove with `pytest packages/pdc/tests/unit/test_pdc_adapter.py` before moving the rest |
| `tests.harness` unimportable when pytest starts inside a package | Root conftest inserts its own parent on `sys.path` before declaring plugins; test both start directories in Phase 4 |
| `__file__` depth changes silently point at the wrong root | Phase 2 removes all 38 computations before any move; `test_module_layout`/`test_agents_contract` do not cover this, so the area-level tests are the proof |
| Cross-test helper imports break (24 sites) | Phase 1 moves them into the harness; `grep -rn "tests.*\.test_" tests packages/<module>/tests` must be empty |
| Two same-stem test modules collide under `prepend` import mode | No duplicates today; run `pytest --collect-only` after the move, and if it fails, adopt `--import-mode=importlib` (Decision 3) |
| `areas.py` / `modules.py` silently mis-match after the move | Their enforcement tests are part of every phase's gate; keep both tables exhaustive |
| `mutants.json` test selections go stale | Update the 11 paths in Phase 3; the mutation run is part of Phase 5 acceptance |
| A wheel accidentally ships tests | `unzip -l` check per package (Decision 9); tests sit beside `src`, not inside it |
| Browser tier flake is mistaken for a migration failure | Run full browser only on an idle machine; two failing tests that pass alone and on rerun are the known load flake (`test_mapping_overlay3d_browser`, `test_new_run_cg_model_browser` are the usual suspects) |
| Docs claim the old layout | Phase 5 edits all four docs; `test_agents_contract` enforces its own budget |

## Rollback

Each phase is one commit and touches only tests, `pytest.ini`, scripts and docs — no runtime source. A failed phase
is `git revert <phase-commit>`; a failed Phase 3 is also reversible with the inverse of the generated `git mv` list
(the manifest is in the commit message or regenerate it from git history). Never mix a harness change and a move in
one commit.

## Definition of done

- `packages/{core,validation,pdc}/tests/` exist with the count table above; `tests/dashboard/` no longer exists.
- All four documented commands pass at the same counts; the three per-tree commands pass from the repo root **and**
  from their package directories.
- `grep -rn "tests\.dashboard" packages tests scripts docs` returns only this plan and dated historical plans.
- The suite's selection still works three ways: tree path, `-m` module marker, `-m` area marker.
- No wheel contains a `tests/` path; docs are current; HANDOFF closes this item.

## Completed (2026-10-29)

- 289 files moved: core 191, validation 29, pdc 69; 2,440 collected (1,466 / 312 / 662 by marker and by directory).
- `--import-mode=importlib` settled the duplicate basename; no `__init__.py` chain inside a tests tree.
- `tests/harness/` holds the fixtures, the two plugins, `mapping_fixtures.py`, `validation_fixtures.py` and the
  selection tables; `modules.py` derives ownership from `packages/<module>/tests`.
- Each package carries a dev-only `test` extra; all three wheels contain zero `/tests/` paths.
- Acceptance: fast 2,187 + 1 xfailed, slow 17, mutation 11/10 caught/1 survived/0 stale, ruff clean, DoD grep clean.
- The one flake seen during acceptance was traced after the plan closed to a stale molecule load in the bead editor
  and fixed in `0738b49`, with a delayed-fetch browser test that fails on the previous code.
