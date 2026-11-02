# Handoff: current state, open items, recent slices

State and open items for this repository. Rules live in `AGENTS.md`; subsystem behaviour and procedures live in
`docs/PROJECT_GUIDE.md`; scoring science in `docs/DDM_CALIBRATION.md`. Read this before touching the DDM CG chain,
the protein-detergent pipeline or the coordinator. This file keeps only what is current and the evidence behind it.

## Next task (2026-11-02): implement the detergent conformation library

Approved and designed; **not started** (no code has changed). Read these in **this checkout** — plans and drafts are
local since `684a5d3`, not tracked:

- `docs/plans/2026-11-02-detergent-conformation-library.md` — the plan of record (schema, producer, resolver,
  integration, refusals, tests, definition of done).
- `docs/design/drafts/2026-11-02-conformation-library-in-form.html` — the compact card in the New run form.
- `docs/design/drafts/2026-11-02-conformation-library.html` — the same card alone. Screenshots sit beside each.

Decisions the user has already made:

- **Sources**: one or several completed, protein-free pdc runs of the same detergent; the caller picks.
- **Size**: exactly **K = 2000** per detergent, chosen by stratified selection; pure numpy, no new dependency.
- **Two ways to name it**: build from runs `{runs, size, seed}` (built or reused on demand) or reference a stored
  library `{key, sha256}` (used as-is; source runs need not be here). A build writes into the store, so it becomes
  selectable by key afterwards. The store is not tracked and is copyable; a referenced library is never rebuilt.
- **Orientation**: the library stores internal geometry (head anchored, head-ward axis +z); placement draws the
  azimuth. Applies to both lattice modes (sphere and torus) and the preview, and the draw lives in
  `place_detergents`, so self-assembly shares it.
- **Default**: one rigid conformation; a run with no setting stays byte-identical.
- **Panel**: one header row (eyebrow + segmented control) and only the chosen mode's body — one-line run rows, one
  footer row of size/seed/status, or one-line stored-library rows. No per-option prose.

Suggested order (the plan has the detail): (1) `detergent_pdc/conformations/` with the CLI and unit tests;
(2) `place_detergents(profiles=…)` + `stamp(entries=…, twists=…)`; (3) `pdc.py` setting/validation/prepare,
`pdc_build`, `pdc_preview`, and the inputs record; (4) the panel, its candidate/stored-library routes and browser
tests; (5) `PROJECT_GUIDE.md`, this file, gates. The store is
`workspace/dashboard/conformations/<residue>/<key>/library.json` plus `library.sha256`.

The Run view controls and PBC slice landed earlier on 2026-11-02
(`docs/plans/2026-10-30-run-view-pbc-controls.md`): a taller canvas, the removable bonds-reason readout cell gone,
one build action behind **Frame options**, **ns per frame** instead of a frame step, and `pbc`/`centre`/`fit`/`group`
as a view of the frames.

Live checks use `b920391735dd` (the empty micelle, 100 ns) or a fixture. **`00b9ae6db23f` was deleted by the user on
2026-10-30**; anything that still names it is history, not a live run.

## Current state (2026-11-02)

- **Three distributions.** Engine `detergent-core` (`packages/core`, import `dashboard`); features
  `detergent-validation` (`packages/validation`) and `detergent-pdc` (`packages/pdc`), discovered through the
  `detergent_md.features` entry point. The root meta distribution names them as `det`/`prot`/`all`. The engine never
  imports a feature.
- **Feature selection and modules.** `--features`/`DASHBOARD_FEATURES` filters discovery before loading; a selected
  feature that fails is skipped and recorded (`features.failures()`); no feature still serves the engine's own
  `dashboard` workspace. The header Modules switch saves `modules.json` per workspace; hidden means not offered, never
  unloaded. The front door `/` renders a workspace without naming it, so client code reads `body[data-workspace]`.
- **Tests** live in each distribution's tree (`packages/<name>/tests/{unit,integration,browser}`), with the shared
  harness at `tests/harness/` and `--import-mode=importlib`; the two axes are area (`-m pdc`, …) and owner
  (`-m core|validation|pdc`). `scripts/test_module.sh` runs one tree.
- **Run layout.** Every run type writes `stages/` and a generated-data `inputs/inputs.json` (roles, paths, digests);
  repository code is pinned in `stage_scripts`/`python_modules`, MDPs in `mdp_profiles`; pdc's ten stages are
  `01_prepare` … `10_backmap`. Legacy trees were migrated to `legacy_layout.json`; `manifest.json` is never rewritten.
- **Tools.** All provisioned tools live under the gitignored `tools/`: `fast_forward` (patched checkout, pinned
  `61e407e6` in `config/tools.json`), `bartender/m3_bartender` (with its bundled xtb) and `cg2at`. `config/tools.json`
  is the one declaration `execution/tools.py` resolves; a declared path is verified or resolves to nothing. The
  Fast-Forward patch itself is tracked source under `resources/patches/`.
- **Martini 3 set.** The published lipidome ITPs, the sugar reference and the licence are tracked in
  `references/M3-Lipid-Parameters`, so a clone installs the force field without a download; the first CG reader
  installs one copy at `workspace/dashboard/martini3` and records the upstream commit and per-file digests. The rest
  of `references/` (PDFs, partial clones, benchmark material) stays untracked.
- **Run view.** Static structures, the CG segment table, figures, and the on-demand Trajectory block: a
  `frame-series` attempt is built from eleven arguments (segment, atoms, ns per frame, start/end, `pbc`, `boxcenter`,
  `center`, `fit`, `group`), played back from a server-written multi-model PDB, fetched only on Play. `pbc` is
  `none|mol|res|atom|whole|nojump|cluster`; `cluster` alone shells out to `gmx trjconv` and stages the trajectory's
  `.tpr`, refusing at queue time without one. The form is behind the **Frame options** disclosure; the one submit
  labels itself Build or Recompute. An older attempt recorded with `stride`/`assembled`/`fit: protein|beads` is still
  found and played as the view it described. `/trajectory` answers
  run-root paths with each playable segment's `identity`; a `.pdb` structure is served by the artifact route. Caps are
  240 models / ~250 MB. `config/dashboard.json` admits 40 GiB per run (the deleted `00b9ae6db23f` was 34.08 GiB,
  which the former 30 GiB limit could not analyse).
- **Service.** The dashboard runs on port 5000 as the transient user unit `detergent-dashboard`; restart it with
  `systemctl --user stop` then a new `systemd-run --user`. Restart after Python changes; `static/` and templates are
  read per request.

## Open items

| item | state | next |
| --- | --- | --- |
| detergent conformation library | approved and drafted 2026-11-02; plan and drafts are local to this checkout (untracked since `684a5d3`) | build it: K=2000 stratified from one or several micelle-only runs; name it by run id or by a stored key; used by both lattice modes and the preview |
| run-layout migration | applied 2026-10-27 (`legacy_layout.json` on every then-existing run); `936b74bd3fa8`, `00b9ae6db23f` deleted by the user | verify the migrated runs still render and resolve analyses |
| Overall Run view progress | the card bar is the current stage's fraction; timeline/plan skips show settings | decide whether a true run-level percentage is wanted |
| cloud vs rough belt | open measurement, not a task | one protein, one seed, two 100 ns legs; compare removal fraction/aggregation/belt thickness before adopting a belt criterion |
| `pytest-socket` | not installed; no test enforces the no-outbound-HTTPS audit | add with `--allow-hosts=127.0.0.1,localhost` |
| known test flake | `test_pdc_preview.py::test_the_cached_step_is_not_run_again...` has failed in one full fast run and passed alone | capture a failing order with `-p no:cacheprovider` |
| DDM CG Task 2.4 | written off by the user 2026-10-15; six arms failed with stochastic onset, causes eliminated | do not rebuild the arms or cron schedule |
| Phase 4 sucrose/maltose | deferred; targets remain `availability: metadata_only` | separate decision |
| native micelle builder | paused; `micelle/` is a partial, unvalidated skeleton | do not present it as a model |
| CI / coverage | no `.github/workflows`; `scripts/gate_commit.sh` is the gate; mutation signal is 11 mutants, 10 caught | no CI to add by default |
| docs beyond this file | HANDOFF, DDM calibration, PROJECT_GUIDE and README are current | use code/manifests/run records for superseded evidence |

## Invariants and incidents worth keeping

- **A trajectory URL is the run-root spelling.** `segments.relative()` keeps `stages/` because `/structure` and
  `/artifacts` resolve from the run root; a `.pdb` structure is named by the artifact route instead. The route test
  fetches every URL it answers rather than matching shapes -- a shape check stayed green while every URL 404'd.
- **The URL does not always name the workspace.** The front door `/` renders one without a path segment, so client code
  reads `body[data-workspace]`; a remembered workspace is followed only while it is still shown. Both 2026-10-30
  failures came from assuming the path.
- **Skipped is a real outcome.** A stage with nothing to do exits 4, writes `skip.json` with its reason, and the run
  continues. The 11,821-attempt incident happened because skipped analyses were requeued; the coordinator treats a
  skipped kind as current by signature.
- **An analysis signature is code plus inputs.** `pdc_view.py` and pdc source changes mint a new attempt; a completed
  analysis is not reused for different sources. `frame-series` adds the chosen trajectory through `Kind.source_hook`.
- **`analysis/runs/segments.py` still names the pdc stage order** for the segment table; the film that consumed it is
  retired.
- **A view is not dynamics.** `pbc`, `centre` (`boxcenter`) and `fit` move sampled frames without touching the
  trajectory; the view is recorded in `frames.json.view` and stated in the PDB's `VIEW MODIFICATIONS` REMARK.
  `nojump` is applied to every frame of the window in order, never only to the sampled ones. `mol`/`res`/`atom`/
  `whole` and `centre` are MDAnalysis transforms; `cluster` is a `gmx trjconv` subprocess on a temporary slice of the
  sampled frames (frame-local, so the slice gives the same answer as the whole file), and its `.tpr` is staged only
  for that mode. `-pbc mol -center`, `res`, `atom`, `nojump`, `centre` (`tric`/`rect`/`zero`) and `cluster` are
  pinned by `gmx trjconv` differential tests. Never use `gmx trjconv -pbc cluster` to pull separate micelles
  together.
- **`-n` replaces GROMACS' group table.** `gmx trjconv -n` uses only the index file's own groups, so an index naming
  only the clustering group made the output prompt fall back to it: the first cluster build on `b920391735dd` wrote
  1,650 solute atoms of an 8,604-atom system and the producer refused the file. The index file now names `view` and
  `System`, the call answers group 0 then group 1, and `_clustered` refuses an output whose atom count is not the
  system's. Pinned by `test_cluster_writes_the_whole_system_even_when_the_group_is_a_subset`.
- **A rebuilt extension must set its own duration.** `restart_mdp(..., length_ps=)` overwrites `nsteps`; the old path
  left the assessment's 100 ns in place.
- **A protein-only default must not become an empty-micelle request.** `create_job` clears `prepare_protein` for a pdc
  job with no protein; `pdc.prepare` still refuses a direct explicit true.
- **The run card timeline follows settings.** `views.planned_skips` predicts empty-micelle/no-removal/back-map/
  equilibration skips; a real stage record always wins. The bar itself remains stage-local.
- **No `ION`/water in the pdc viewer.** `ION` was once drawn as unbonded protein beads; it is in `WATER_RESIDUES`.
- **pdc bonds are chemical by default.** Protein and detergent CONECT records; the elastic network is a separate PDB
  series at opacity 0.1.
- **The player's files are views with a record.** `frames.json` carries the trajectory identity, the arguments, the
  effective cadence, the `view` and any `legacy` marker; `series_pdb`'s REMARKs state a fit and any PBC/centre view.
  The series PDB is fetched only on Play.
- **Never kill DSH.** The first listener on 3080 is DSH; the dashboard is 5000 and is a systemd user service.

## Current measurements

- `b920391735dd`: protein-free pdc run (DDM, no removal, no back-map), 5,000,000 steps at 20 fs = 100 ns in one
  assessment leg, the ruled-out stages absent. Its series: 120 models over 0–99.246 ns, 8,604 atoms, 15.7 MB, and
  180,000 CONECT records measured on the assembled acceptance series. It is the surviving live pdc example.
- `00b9ae6db23f` (deleted by the user 2026-10-30) was 4iar + 120 DDM, 2,248 atoms in the dry build and 11,708/10,427
  through its two systems; its measurements remain in `docs/plans/2026-10-30-run-view-trajectory.md` as the acceptance
  evidence, not as a live run.
- Frame-series producer (2026-10-30): 44 s for the whole 100 ns, 2.5 GB extension trajectory after one sequential
  pass; random `.xtc` access cost 1.7 s a frame, which is why the producer never indexes frames at random.
- Tests (measured 2026-11-02, after the full PBC set and the cluster index fix): 2,575 collected; fast **2,288
  passed, 1 xfailed**; browser **260 passed**; slow **26 passed**; `ruff check packages tests conftest.py` clean;
  mutation signal 10 caught / 1 survived. `pytest.ini` owns tier counts; do not copy moving counts into this file.

## Landed slices, newest first

- **2026-11-02 Run view controls and PBC**: a taller NGL canvas, the bonds-reason readout cell removed, one **Frame
  options** disclosure with a state-dependent Build/Recompute submit, **ns per frame** instead of a frame step, and
  view options `pbc` (`none|mol|res|atom|whole|nojump|cluster`), **box centre** (`tric|rect|zero`), `centre`, `fit`
  and `group`, each pinned by a `gmx trjconv` differential test; old `stride`/`assembled` attempts stay playable and
  labelled as frame-step builds. `cluster` is the one mode that shells out to `gmx`, on a temporary slice of the
  sampled frames with a staged `.tpr`; its index file names both the clustering group and `System`, because `-n`
  replaces GROMACS' own group table (the fix for the first live cluster build writing 1,650 of 8,604 atoms).
- **2026-10-30 Martini 3 set tracked**: the published lipidome ITPs, the sugar reference and the licence are in git
  (18 MB), so a clone installs the force field without a download; benchmark material and the workbook stay untracked.
- **2026-10-30 tools layout**: Fast-Forward moved from `resources/parameterizers/` to `tools/fast_forward`, so all
  provisioned tools live under the one gitignored tree; the tracked patch stays in `resources/patches/`.
- **2026-10-30 Run view trajectory**: the path-contract fix, the on-demand `frame-series` analysis (payload-driven
  sources, fit/assembly, caps) and the player plus build form in the shared panel.
- **2026-10-30 modules switch**: the header popover hides/shows installed features per workspace, saved in
  `modules.json` and applied on reload; hidden means not offered, not unloaded.
- **2026-10-30 feature selection and core-only start**: `DASHBOARD_FEATURES`/`--features` filters discovery before
  loading; failed features are skipped and recorded; an empty registry gets the engine's own workspace.
- **2026-10-29 browser-tier flake**: a stale molecule load could replace a newer selection in the bead editor;
  `loadMoleculeEditor` now checks its generation after every await, with a delayed-fetch regression test.
- **2026-10-29 test-package split**: every test moved into its package, shared fixtures and selection tables at
  `tests/harness/`, a root `conftest.py`, `--import-mode=importlib`; `scripts/test_module.sh` selects a tree.
- **2026-10-27 run lifecycle**: `inputs/inputs.json` for shared inputs by path and digest, repository code pinned in
  `stage_scripts`/`python_modules`, profile-written MDPs with `mdp_profiles`, pdc's ten numbered stages with
  prepare-time skips, and `migrate_run_layout.py` for old trees.
- **2026-10-26 empty micelle / no removal**: `remove_out_of_micelle`; one CG MD leg = assessment + extension;
  empty-micelle preview and disabled Bonds/Ribbon; settings-driven SVG; job-level `prepare_protein` sanitisation;
  planned skips; empty-micelle image assembly.
- **2026-10-26 extension duration fix**: `restart_mdp` writes `nsteps` from `length_ps`/`dt`.
- **2026-10-23 DDM back-map**: CG2AT2 vendored, fragment and force field wired, net charge -5.0 → 0.0, protein
  preparation default.
- **2026-10-20 → 2026-10-22**: parameterization without a run, profile choice removal and mapping reuse, bond
  panel/rows, body-aware placement, device setting, serializer/store/name rules.
- **2026-10-12 → 2026-10-15**: protein-detergent chain and run view; gate, mutation signal and property tests.

## Where to read what

- Rules, invariants, verify commands: `AGENTS.md`.
- Repo layout, source ownership, run contracts, module notes: `docs/PROJECT_GUIDE.md`.
- Scoring, linkage, carbohydrate evidence and limits: `docs/DDM_CALIBRATION.md`.
- Plans: every plan lives under `docs/plans/`, which is **local to the checkout and untracked** (except its
  `README.md`); `docs/design/drafts/` is untracked too. `docs/design/` holds design records, not plans.
- Superseded measurements are intentionally not kept here; use the code, manifests and run records as the record.
