# Handoff: current state, open items, recent slices

State and open items for this repository. Rules live in `AGENTS.md`; subsystem behaviour and procedures live in
`docs/PROJECT_GUIDE.md`; scoring science in `docs/DDM_CALIBRATION.md`. Read this before touching the DDM CG chain,
the protein-detergent pipeline or the coordinator. This file keeps only what is current and the evidence behind it.

## Right now (2026-10-29): the dashboard is three distributions

- The engine is `detergent-core` (`packages/core`, import `dashboard`), and the two features are
  `detergent-validation` (`packages/validation`) and `detergent-pdc` (`packages/pdc`); the root `detergent-md-gui`
  names them as the `det`/`prot`/`all` extras. A feature is whatever installed distribution advertises in the
  `detergent_md.features` entry point (`dashboard/features.py` loads its `Feature`; `KNOWN` there is only the fallback
  for an editable checkout whose metadata predates the entry point), so installing a wheel adds a workspace.
  `Feature.priority` orders them -- the shell opens on the first -- and core never imports one: blueprints, run types,
  analysis kinds, workspaces, admission rules and the prepare/readiness/series hooks all arrive through the record.
- Tests live in each distribution's tree: `packages/<name>/tests/{unit,integration,browser}`, with the shared harness
  at `tests/harness/` and `--import-mode=importlib` in `pytest.ini`, so a duplicate basename across tiers needs no
  `__init__.py`. The two selection axes remain: subject (`-m <area>`, table in `tests/harness/areas.py`) and owner
  (`-m core|validation|pdc`, derived from the tree); `scripts/test_module.sh <module> [tier]` runs one tree.
- **The test-package split landed 2026-10-29** (plan and record: `docs/plans/2026-10-29-modular-test-packages.md`):
  191/29/69 files and 1466/312/662 tests in core/validation/pdc, 2,440 collected. Each package's `pyproject.toml`
  carries a dev-only `test` extra, and a built wheel carries no tests (`packages.find` scans `src/` only). One residual
  is open: the mapping editor's overlay occasionally loads an empty bead file under load; every failed test passes
  alone. See the open-items row.
- `DASHBOARD_TABS` is validated when the app is constructed: every named slug must exist in every installed
  workspace, so a typo is a start-up failure rather than a 400 on the first page.
- The data root is `DASHBOARD_ROOT` (falling back to the checkout), and the interpreter is `.venv/` at the
  checkout root. `detergent-dashboard` is the console entry point; `python -m dashboard` still runs the checkout.
- Runs prepared before the package move keep verifying: recorded code spells `dashboard/...` and
  `run_scripts.code_path` resolves it through the distribution that took the file over.
- The engine no longer names a pdc stage, role, segmenter or structure reader: the stage table, five roles, three
  review pairs and detergent-topology resolver live in `detergent_pdc/layout.py` (registered through
  `Feature.layout`), the nine-stage segmenter and markers in `detergent_pdc/segments.py`, the protein moleculetypes in
  `detergent_pdc/topologies.py`, the queued-run skip preview in `detergent_pdc/view.py`, and `/api/micelle/build` on
  the pdc blueprint. The structure writer is engine code (`analysis/runs/structures.py`) because it serves every run.
- The validation analyses and their seven kind rows moved to `detergent_validation/` (`kinds.py`, `analysis/runs/`,
  `analysis/validation/`, `sugar_ensemble.py`). The carbohydrate evidence vocabulary moved too:
  `detergent_validation/evidence.py` owns the three section texts and the `carbohydrate` profile; the engine keeps
  `alkyl_tail`/`charged_headgroup`/`detergent`, and `molecules/evidence.PROFILES` is a live merged view (a core-only
  install therefore has no carbohydrate profile, by design). The engine seams they needed are `Kind.payload` (a row states its
  queue body keys), `features.kind_payload_for(kind)` (the feature validates and derives that body), the targets route
  on the validation blueprint, and `analysis/runs/statistics.py` (the block summary core and validation both report).
- Still in core by decision: the bonded/dihedral analyses (`bonded-cross-check`, `dihedral-fit`, `bartender-fit`), the
  micelle adapter and its science, the mapping editor, the molecules panel, and `analysis/validation/
  carbohydrate_targets.py` (a mapping route and the validation analyses both read it). The remaining engine-held
  feature vocabulary are now registered too: the carbohydrate evidence sections/profile (2a) and the legacy pdc stage
  names the migration reads (2b).
- Feature panels own their browser surface now: the shell loop includes each registered `panels/<id>.html` from the
  feature's template package, links its `styles`, and boots its `panel_modules` (mapping-validation + osmotic from
  detergent_validation, the Complexes panel from detergent_pdc); a deployment without a feature fetches neither its
  markup nor its JS. The last shared panels follow the same rule through extension hooks: `new-run.js` and the
  `run-view-*.js` family expose `registerNewRunExtension({workspace, create(context)})` and
  `registerRunViewExtension({name, serves, structure, runSelected})`, the pdc feature registers both from
  `js/new-run-pdc.js` / `js/run-view-pdc.js` (`Feature.extension_modules`), and its markup lives in
  `templates/fragments/` inserted at generic slots. The engine's panel JS, CSS and template name no pdc/protein-detergent
  vocabulary; the styling followed the markup into `pdc.css`.
- The validation-only endpoints (`mapping-consistency`, `distance-diagnostics`, `carbohydrate-validation`,
  `/api/runs/transferability`) and the cross-molecule reader are the validation feature's now. `/api/compare`,
  `/api/mappings/validation-targets`, `/api/mappings/ring-site/preview` and `/api/evidence/evaluate` look
  validation-flavoured but stay engine-owned until their consumers are confirmed.
- A validation-only deployment lives at `/mnt/data/wee/detergent-gui-mini` (`run.sh`, port 5001, `DASHBOARD_TABS`
  six panels); `scripts/build_mini.sh` rebuilds and force-reinstalls it (`--smoke` checks it). `detergent-import-run`
  ports a run between workspaces.

## Right now (2026-10-27)

- **Snapshots are retired (2026-10-28):** the `snapshots` analysis kind, PDC's stage snapshot writer and
  `snapshots.json` indexes, and Run view's transport/film are removed. The New run snapshot interval/cap are gone;
  Run view shows static structures, the CG-chain segment table and figures. Notes below that describe snapshot
  frames or the film are historical evidence, not current behaviour.
- **The run-lifecycle refactor is built and the live layout is migrated; the 100 ns acceptance run is open.** Every run type
  writes `stages/` and a generated-data `inputs/`; `inputs/inputs.json` names every shared input by
  `role`/`label`/`kind`/`root`/`path`/`sha256`, and the manifest's `input_snapshot_sha256` digests that record,
  re-verified before every stage. No new run carries a `.py` or a copied `.sh`: `stage_scripts`/`python_modules` pin the
  repository script and helpers each stage runs. MDPs are written from the reviewed profiles in
  `dashboard/execution/mdp/` and recorded as `mdp_profiles`; pdc has ten stage directories numbered `01_prepare` …
  `10_backmap`, and a stage the settings rule out has no directory. Two exceptions are recorded in the plan's
  *Notes from implementation*: AA still writes its generated `run.sh`, and osmotic's MDPs still come from
  `osmotic_mdp`.
- **Run-layout migration** is `.venv/bin/python -m dashboard.cli.migrate_run_layout --all --apply`
  (dry run without `--apply`). Per legacy run it archives `inputs/` and the copied code, or moves a pre-numbering
  pdc stage tree under `stages/`, to `legacy_evidence*.tar.gz`, proves the archive reads back, then writes
  `legacy_layout.json`; `manifest.json` is never rewritten. It has no busy-run guard and iterates in run-name
  order, so never run it while a run is executing. Applied to the live workspace 2026-10-27: every remaining run now
  has `legacy_layout.json` and `stages/` (10 of 10; `936b74bd3fa8` was deleted by the user before it was migrated).
  Archives are written with `pigz` when installed. Open every migrated run in the run view and resolve its analyses
  before treating the migration as accepted.
- **The 100 ns micelle-only acceptance run is `b920391735dd`**: a protein-free pdc run, DDM mapping revision 2,
  `remove_out_of_micelle=false`, `backmap=false`; 99 ns assessment + 1 ns extension folded into one 5,000,000-step
  leg at 20 fs. Completed 2026-10-27; `stages/06_assessment/prod/whole.xtc` runs 0-100 ns, the four ruled-out stages
  have no directory and render skipped, and the run holds no `.py`/`.sh`.
- **`936b74bd3fa8` was deleted by the user on 2026-10-27.** It had failed in `CG assessment MD` on 2026-10-26 with
  `Worker stopped: per-run storage limit reached`; nothing was running when it was removed.
- **Restart the dashboard when convenient**: the running service predates the empty-micelle display assembly. Use
  `systemctl --user restart detergent-dashboard`.
- `bbda8d632309` is a permanent failed record: it carried `prepare_protein=true` with `protein=null` because generic
  job normalization applied a protein-only default before the adapter knew the run had no protein. `create_job`
  now sets `prepare_protein=false` for a pdc job with no protein, so **retry** or a new queue works; the old record
  cannot be repaired in place.
- `00b9ae6db23f` is the current 1 us-labelled complex run, but its data is **200 ns**: assessment 100 ns + extension
  100 ns. The rebuilt extension path ignored `extension.ps`; `restart_mdp` now rewrites `nsteps` from `length_ps` and
  the mdp `dt`, so future rebuilt runs honour 900 ns.
- Run view draws NVT, NPT and the one no-removal CG leg as segments; the timed film that played them is retired.
- The dashboard is a user service: `systemctl --user restart detergent-dashboard`. Never infer its PID from an
  unfiltered `ss`; DSH owns 3080. Use `lsof -t -iTCP:5000 -sTCP:LISTEN` or the service name.

## Open items

| item | state | next |
| --- | --- | --- |
| run-layout migration | applied 2026-10-27 to all 10 existing runs (`legacy_layout.json`); `936b74bd3fa8` deleted by the user | verify run view and analyses for every migrated run |
| 100 ns micelle-only acceptance | `b920391735dd` completed 2026-10-27: 5,000,000 steps, 100 ns, skipped stages absent, stage artifacts present | inspect it in the run view; no open action |
| `936b74bd3fa8` | deleted by the user 2026-10-27; failed in `CG assessment MD` (per-run storage limit) | nothing |
| 1 us run for `00b9ae6db23f` | impossible from its data: 200 ns total | new pdc run with the corrected extension duration |
| Overall Run view progress | the card bar is the current stage's fraction; timeline/plan skips now show settings | decide whether a true run-level percentage is wanted |
| Run view film | retired with the `snapshots` analysis; the panel shows static structures and CG-chain segments | nothing |
| cloud vs rough belt | open measurement, not a task | one protein, one seed, two 100 ns legs; compare removal fraction/aggregation/belt thickness before adopting a belt criterion |
| `pytest-socket` | not installed; no test enforces the no-outbound-HTTPS audit | add with `--allow-hosts=127.0.0.1,localhost` |
| known test flake | `test_pdc_preview.py::test_the_cached_step_is_not_run_again...` has failed in one full fast run and passed alone | capture a failing order with `-p no:cacheprovider` |
| browser-tier flake | the mapping editor's overlay can load an empty bead file under load (`atoms: [35, 0]`), about one browser run in eight; every failed test passes alone | capture with `--tb=line`; suspect the editor's initial candidate selection |
| DDM CG Task 2.4 | written off by the user 2026-10-15; six arms failed with stochastic onset, causes eliminated | do not rebuild the arms or cron schedule |
| Phase 4 sucrose/maltose | deferred; targets remain `availability: metadata_only` | separate decision |
| native micelle builder | paused; `micelle/` is a partial, unvalidated skeleton | do not present it as a model |
| CI / coverage | no `.github/workflows`; `scripts/gate_commit.sh` is the gate; mutation signal is 11 mutants, 10 caught | no CI to add by default |
| docs beyond this file | HANDOFF, DDM calibration, PROJECT_GUIDE and README are current; AGENTS carries the new run contract; history archives deleted on request | use code/manifests/run records for superseded evidence |

## Invariants and incidents worth keeping

- **Skipped is a real outcome.** A stage with nothing to do exits 4, writes `skip.json` with its reason, and the run
  continues. The 11,821-attempt incident happened because skipped analyses were requeued; the coordinator now treats
  a skipped kind as current by signature, and automatic queue dedupe ignores payload only where it should not.
- **An analysis signature is code plus inputs.** `pdc_view.py` changes and pdc source changes must mint a new
  attempt; a completed analysis is not reused for different sources.
- **`analysis/runs/segments.py` still names the pdc stage order** for the segment table; the `_pdc_timeline`
  film that consumed it is retired.
- **Display assembly is not dynamics.** For a complex, chains are joined and detergent molecules are moved to the
  image nearest the protein *surface*. For an empty micelle, `_assemble_micelle` seeds on the first detergent and
  wraps the rest to it, then centres. Never rewrite the trajectory; never use `gmx trjconv -pbc cluster` to pull
  separate micelles together.
- **A rebuilt extension must set its own duration.** `restart_mdp(..., length_ps=)` overwrites `nsteps`; the old
  path left the assessment's 100 ns in place, which is why the 1 us run is 200 ns.
- **A protein-only default must not become an empty-micelle request.** `create_job` clears `prepare_protein` for a
  pdc job with no protein; `pdc.prepare` still refuses a direct explicit true.
- **The run card timeline follows settings.** `views.planned_skips` predicts empty-micelle/no-removal/back-map/
  equilibration skips; a real stage record always wins. The bar itself remains stage-local.
- **No `ION`/water in the pdc viewer.** `ION` was once drawn as unbonded protein beads; it is in `WATER_RESIDUES`.
- **pdc bonds are chemical by default.** Protein and detergent CONECT records; the elastic network is a separate
  PDB series at opacity 0.1, not the chemical bonds.
- **Never kill DSH.** The first listener on 3080 is DSH; the dashboard is 5000 and is a systemd user service.

## Current measurements

- `00b9ae6db23f`: 4iar + 120 DDM; assessment cluster sizes `[76,21,14,7,2]`, final `[42,16,15,3]`; protein contacts
  41/34; 2,248 atoms; 2,194 chemical bonds/model; 2,236 protein elastic pairs; assessment 100 ns, extension actual
  100 ns; total 200 ns.
- `00b9ae6db23f`, historical film measurement before the `snapshots` analysis was retired: NVT 0.5005 ns, NPT
  4.5005 ns, assessment 100 ns, extension 100 ns; NVT at 0.1 ns/frame (6 models), NPT at 0.1 (46), production 101
  each; 254 frames total. NVT/NPT raw `.xtc` are made whole with `gmx trjconv -pbc mol -center`.
- `936b74bd3fa8`: empty micelle, 120 DDM, no removal; the 1,000 ns leg after NVT/NPT was configured at
  50,000,000 steps and did not finish: the run failed in `CG assessment MD` at the per-run storage limit.
- `bbda8d632309`: failed at input before stages; no stage directories.
- Tests (measured 2026-10-29, after the split): 2,440 collected; fast **2,187 passed, 1 xfailed**; browser **235
  passed**; slow **17 passed**; `ruff check packages tests conftest.py` clean. `pytest.ini` owns tier counts; do not
  copy moving counts into this file.

## Landed slices, newest first

- **2026-10-29 test-package split**: every test moved into its package (191/29/69 files; 1466/312/662 tests), shared
  fixtures and the selection tables at `tests/harness/`, a root `conftest.py`, `--import-mode=importlib`;
  `scripts/test_module.sh` selects a tree and `scripts/mutants.json` follows it.
- **2026-10-27 run lifecycle**: one layout for every run type — `inputs/inputs.json` for shared inputs by path and
  digest, generated data only in `inputs/`, repository code pinned in `stage_scripts`/`python_modules`, profile-written
  MDPs with `mdp_profiles`, pdc's ten numbered stages with prepare-time skips, and `migrate_run_layout.py` for the old
  trees.
- **2026-10-26 pdc Run view**: timed CG reel from NVT/NPT/assessment/extension; one global playhead; 1 ns/frame
  default for pdc; elastic overlay; protein/detergent bonds; PBC surface assembly.
- **2026-10-26 empty micelle / no removal**: `remove_out_of_micelle`; single CG MD leg = assessment + extension;
  empty-micelle preview and disabled Bonds/Ribbon; settings-driven SVG; job-level `prepare_protein` sanitization;
  run-card planned skips; empty-micelle image assembly.
- **2026-10-26 extension duration fix**: `restart_mdp` writes `nsteps` from `length_ps`/`dt`.
- **2026-10-23 DDM back-map**: CG2AT2 vendored, fragment and force field wired, net charge -5.0 → 0.0, protein
  preparation default.
- **2026-10-22 bond panel/rows, body-aware placement, device setting**.
- **2026-10-21 serializer/store/name rules**.
- **2026-10-20 profile choice removal, mapping reuse, lazy-Plotly slice**.
- **2026-10-16 run type owns its fit; parameterization without a run**.
- **2026-10-15 gate, mutation signal, property tests**.
- **2026-10-12 → 2026-10-15 protein-detergent chain and run view**.

## Where to read what

- Rules, invariants, verify commands: `AGENTS.md`.
- Repo layout, source ownership, run contracts, module notes: `docs/PROJECT_GUIDE.md`.
- Scoring, linkage, carbohydrate evidence and limits: `docs/DDM_CALIBRATION.md`.
- Plans: every plan lives under `docs/plans/`; `docs/design/` holds design records, not plans.
- Superseded measurements are intentionally not kept here; use the code, manifests and run records as the record.
