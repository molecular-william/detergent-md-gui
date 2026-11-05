# Handoff: current state, open items, recent slices

State and open items for this repository. Rules live in `AGENTS.md`; subsystem behaviour and procedures live in
`docs/PROJECT_GUIDE.md`; scoring science in `docs/DDM_CALIBRATION.md`. Read this before touching the DDM CG chain,
the protein-detergent pipeline or the coordinator. This file keeps only what is current and the evidence behind it.

## Next task

None named. The user's 2026-11-04 request -- move the analysis graphs to Run view, and state the selected segment's
frame count and total ns -- is implemented (see *Landed slices*); the plan of record is
`docs/plans/2026-11-04-analysis-graphs-in-run-view.md`. The open items table below is the queue.

The dashboard was restarted on 2026-11-04 at 13:56 for the Python half (the trajectory header reader). Live checks:
`6c36b3c610f3` states `45,001 frames · 900 ns` on its CG extension and draws its trajectory-overview figure in Run
view; `b920391735dd` is the protein-free alternative. `00b9ae6db23f` was deleted by the user on 2026-10-30 and is
history, not a live run.

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
- **Run view.** Static structures, the CG segment table, and the on-demand Trajectory block: the run holds one
  stored `frame-series` at `analyses/frame-series/run-frames.pdb` + `frames.json`, built from eleven arguments
  (segment, atoms, ns per frame, start/end, `pbc`, `boxcenter`, `center`, `fit`, `group`) and replaced in place by
  every build; Play fetches the PDB only then. `pbc` is `none|mol|res|atom|whole|nojump|cluster`; `cluster` alone
  shells out to `gmx trjconv` and stages the trajectory's `.tpr`, refusing at queue time without one. The form is
  behind the **Frame options** disclosure; the one submit labels itself Build or Recompute. An older attempt under
  `analyses/frame-series/<signature>/<attempt>/` -- with `stride`/`assembled`/`fit: protein|beads` -- is still found
  by matching the form's arguments and played as the view it described. Each monitor has its own **Analysis** card
  under the Trajectory block: the run's current figures (every kind, through `GET /api/jobs/<id>/figures` and
  `RunFigureViewer`), the three controls that queue analyses (Recompute, Trajectory overview, Re-score assessment),
  the task list and the assessment's distance diagnostics. The Runs card draws no figures and offers no analysis
  button; the Run view's gallery door and pdc's `gallery_note` are gone. `/trajectory` answers run-root paths with
  each playable segment's `identity`, `frames` and `time_ns`; the Trajectory block states the selected segment's
  `45,001 frames · 900 ns` and "not recorded" when the header cannot be read. A `.pdb` structure is served by the
  artifact route. Caps are 240 models / ~250 MB.
  `config/dashboard.json` admits 40 GiB per run (the deleted `00b9ae6db23f` was 34.08 GiB, which the former 30 GiB
  limit could not analyse).
- **Detergent conformations.** A pdc run may stamp its detergents from a fixed-size library taken from micelle-only
  runs: `detergent_pdc/conformations/` writes `<workspace>/conformations/<residue>/<key>/library.json` plus
  `library.sha256` (K = 2000 whole molecules, stratified split, pure numpy), `pdc.prepare` records it as the
  `detergent_conformations` input, and `pdc_build`/`pdc_preview` draw one entry and one azimuth per site through
  `place_detergents(conformations=…)` and stamp the same numbers. `null` is the template's one rigid molecule and
  every earlier run. The panel's **Detergent shape** card is the fourth New run card; the two routes are
  `GET /api/pdc/conformations/runs` and `GET /api/pdc/conformations/libraries`.
- **Service.** The dashboard runs on port 5000 as the transient user unit `detergent-dashboard`; restart it with
  `systemctl --user stop` then a new `systemd-run --user`. Restart after Python changes; `static/` and templates are
  read per request.

## Open items

| item | state | next |
| --- | --- | --- |
| run-layout migration | applied 2026-10-27 (`legacy_layout.json` on every then-existing run); `936b74bd3fa8`, `00b9ae6db23f` deleted by the user | verify the migrated runs still render and resolve analyses |
| analysis progress visibility | queued and watched only in Run view now: the Runs card's Analysis graphs panel is gone | decide whether the Runs card needs a one-line "analysis running" pointer |
| Overall Run view progress | the card bar is the current stage's fraction; timeline/plan skips show settings | decide whether a true run-level percentage is wanted |
| cloud vs rough belt | open measurement, not a task | one protein, one seed, two 100 ns legs; compare removal fraction/aggregation/belt thickness before adopting a belt criterion |
| `pytest-socket` | not installed; no test enforces the no-outbound-HTTPS audit | add with `--allow-hosts=127.0.0.1,localhost` |
| known test flake | `test_pdc_preview.py::test_the_cached_step_is_not_run_again...` has failed in one full fast run and passed alone | capture a failing order with `-p no:cacheprovider` |
| checkpoint resume before a stage's last mdrun | Resume is hidden there (no checkpoint for the final mdrun) and Restart re-runs the stage | decide whether the pdc extension should continue a death in `eq`/`ramp` instead of re-entering the stage from its inputs |
| DDM CG Task 2.4 | written off by the user 2026-10-15; six arms failed with stochastic onset, causes eliminated | do not rebuild the arms or cron schedule |
| Phase 4 sucrose/maltose | deferred; targets remain `availability: metadata_only` | separate decision |
| native micelle builder | paused; `micelle/` is a partial, unvalidated skeleton | do not present it as a model |
| CI / coverage | no `.github/workflows`; `scripts/gate_commit.sh` is the gate; mutation signal is 11 mutants, 10 caught | no CI to add by default |
| docs beyond this file | HANDOFF, DDM calibration, PROJECT_GUIDE and README are current | use code/manifests/run records for superseded evidence |

## Invariants and incidents worth keeping

- **A removed disclosure breaks every Runs card.** `runs.js`'s creation loop opens the card's `<details>` by class; when the analysis panel was deleted from the template, the loop's fourth name resolved to nothing and `detail.open` threw before the Clone handler was bound -- every card rendered, and no button on any of them worked. The loop now names only the three details the template has; a card's binding block must not look up an element the shell no longer renders.
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
  analysis is not reused for different sources. `frame-series` adds the chosen trajectory through `Kind.source_hook`;
  a changed signature there rebuilds its one stored series rather than minting a second attempt.
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
- **One run, one frame series.** `frame-series` declares `Kind.stable_directory = 'analyses/frame-series'`: the
  coordinator keeps one record (`stable: true`, the same id across rebuilds) and the worker replaces
  `run-frames.pdb` then `frames.json`, each through `files.atomic_copy`; a failed build publishes neither, so the
  previous pair stays. Any arguments set replaces the pair -- there is no attempt directory to mint. Attempts under
  `analyses/frame-series/<signature>/<attempt>/` written before this change stay readable as the panel's fallback.
  Switching the segment combo changes the form, never the stored series: the block names the segment the build
  sampled (from `frames.json`'s arguments) and says the selected segment or options differ.
- **Admission is per GPU.** `Coordinator.admit_device` reads the run's own `settings.mdrun_gpu` and refuses only
  while that device already holds `max_concurrent_runs` active runs; a run on another device starts beside it, and
  the refusal names the GPU. A worker with no readable row counts on device 0, and a host reporting no devices
  answers as device 0, so the old one-at-a-time behaviour survives where devices cannot be told apart.
- **A Python change is live only after the dashboard restarts.** The transient unit keeps its imported modules for
  its whole life while `static/` is read per request, so a server started before a code change serves the new browser
  script against the old engine. Measured 2026-11-03: the unit started at 10:41, the frame-series change landed at
  11:11, and a 11:20 build wrote an attempt-shaped record (`stable` absent) that the new panel could not recognise as
  a stored series. Check the unit's start time against the commit before blaming a build.
- **Never kill DSH.** The first listener on 3080 is DSH; the dashboard is 5000 and is a systemd user service.
- **Resume continues one stage's last mdrun, never an earlier one.** `continue_plan` names the first stage that is
  not completed/reused/skipped and the first existing checkpoint its declaration names; a stage that died before
  that mdrun has none, so Resume is hidden and Restart is the answer. The continue preparation keeps the stage
  directory (no archive) and truncates the manifest's stage list from that stage.
- **`MDRUN_CONTINUE` reaches exactly one stage.** The worker sets it from the manifest's `continue_stage`/
  `continue_checkpoint` for that stage only and records it in that stage's environment; the fields are cleared when
  the stage completes, so a later stage cannot inherit a spent checkpoint. The scripts skip the work before the
  final mdrun **including its `grompp`**, run `-cpi … -append`, and re-run their post-step.
- **`mdrun_cpt` defaults to ten minutes.** It is a `DEFAULTS` entry in the AA, pdc and osmotic tables, so every run
  records the cadence and its `mdrun` carries `-cpt 10` unless the caller names another; the forms prefill 10. A bare
  settings dict handed straight to `mdrun_command_flags` still emits no flag, which is why an old unit-level
  expectation of the untouched command remains true.
- **A conformation library is pinned, never swapped.** `library.json` is canonical bytes and `library.sha256` is the
  verifier; the key is the first 16 hex of the canonical spec over the detergent signature and the sorted
  `(run_id, trajectory_identity)` pairs, so a rebuild from the same sources names the same directory. A run records
  the path and digest as a `store` input, a stored library whose bytes differ is refused rather than overwritten, and
  a key-mode library is never rebuilt: if it is deleted and its runs are gone, the original must be copied back.
- **A library shapes the bodies, never the sites.** The entry index and the azimuth are drawn from
  `default_rng([seed, 0xC0FF])` in site order, so a placement naming no library keeps every draw it had; the
  clearance gate measures the drawn body and `pdc_build.stamp` writes that same entry and twist.
- **A library is matched bead for bead.** Its residue, bead names/order and the source run's mapping digest must equal
  the new run's own model; the build stage re-verifies the recorded digest before reading the file, so a hand-edited
  library stops the stage instead of stamping different molecules.
- **A library samples frames, and only reads its run.** A CG production trajectory writes a frame every 2 ps
  (`b920391735dd`: 50,001), so extraction takes at most `MAX_FRAMES = 200` evenly strided frames and records the
  stride; MDAnalysis' `*_offsets.npz` cache is kept out of the run by opening the trajectory through a symlink in a
  temporary directory, because a run's outputs are immutable.
- **A molecule is judged against its own topology.** The bond/constraint reference is the `funct 1` line's stated
  length, never the mapping-derived geometry: on `b920391735dd` the geometry states 0.2696 nm for `2-5` where the itp
  states 0.334 and the measured median is 0.3242, so a geometry reference fails 51.6% of a normal fluctuation and
  drops good molecules. Virtual-site parents are connectivity only.

## Current measurements

- `b920391735dd`: protein-free pdc run (DDM, no removal, no back-map), 5,000,000 steps at 20 fs = 100 ns in one
  assessment leg, the ruled-out stages absent. Its series: 120 models over 0–99.246 ns, 8,604 atoms, 15.7 MB, and
  180,000 CONECT records measured on the assembled acceptance series. It is the surviving live pdc example.
- `00b9ae6db23f` (deleted by the user 2026-10-30) was 4iar + 120 DDM, 2,248 atoms in the dry build and 11,708/10,427
  through its two systems; its measurements remain in `docs/plans/2026-10-30-run-view-trajectory.md` as the acceptance
  evidence, not as a live run.
- Frame-series producer (2026-10-30): 44 s for the whole 100 ns, 2.5 GB extension trajectory after one sequential
  pass; random `.xtc` access cost 1.7 s a frame, which is why the producer never indexes frames at random.
- Conformation library, built from `b920391735dd` alone (2026-11-02): 50,001 frames of 2 ps sampled every 250th (201
  frames, stride recorded), pool 30,150, kept 29,504, broken 646, non-finite 0, wall 10.38 s (record 10.05 s); a
  second rebuild is byte-identical. Key `d389b3135533cd3a`, sha256 `e43192db…`, 2,000 entries of 11 beads, stored at
  `workspace/dashboard/conformations/DDM/d389b3135533cd3a/` (gitignored). Reading is cheap — 200 frames in 0.14 s,
  offsets in 0.13 s — so the per-molecule processing is the whole cost and `MAX_FRAMES` is what bounds it.
- Tests (measured 2026-11-02, after checkpoint resume): 2,713 collected; fast **2,413 passed, 1 xfailed**;
  browser **273 passed**; slow **26 passed**; `ruff check packages tests conftest.py` clean; mutation signal 10
  caught / 1 survived. `pytest.ini` owns tier counts; do not copy moving counts into this file.

## Landed slices, newest first

- **2026-11-05 Ponytail audit cleanup**: dead surface removed after a parallel seven-lane audit. Deleted:
  `validation/analysis/runs/draft_geometry.py` (+its test), the unused bonded interaction-editor chain in
  `models/bonded/__init__.py`, pdc's `protein_frame`/`_outward`/`TIMELINE_STAGES`, `kinds.published()` with its four
  tests, the `/api/compare` route and `assessment_directory`, `cli/migrate_models.py`, the validation refinement
  blueprint (cancelled panel), `/api/model-references`+`/api/model-fragments`, the clientless suggest-bead and
  ring-site routes, the `sugar_ensemble` report path (the consistency analyses keep the arithmetic they call), the
  superseded `osmotic_box.water_beads`/`solute_molecules`, the committed `detergent_md_gui.egg-info/`, the duplicate
  `tests/harness/mapping_fixtures.py`, and 16 dead CSS rules. The legacy sibling-series failure hook
  (`feature.on_run_failed`, `Coordinator._series_stop_reason`, `test_osmotic_series_stop.py`) is gone: a series is
  one run now. Five findings were kept after verification: the schema<3 depiction/export path is exercised by the
  export/diagram API tests, the MDP parity oracles pin the reviewed profiles, the pdc `planned_skips`/box merges
  would change UI wording or preview behaviour, `/#<panel>` bookmarks are deliberate compatibility, and the
  diagram/export routes are documented. Checks: fast tier 2398 passed + 1 xfailed, browser 282 passed, slow 25
  passed; ruff clean over the changed trees.

- **2026-11-04 Analysis card in Run view, and the segment readout**: the Runs card's **Analysis graphs** panel is
  gone; each Run view monitor's Analysis card draws that run's own figures, queues its analyses and lists its tasks,
  with the distance diagnostics beside them. `GET /api/jobs/<id>/trajectory` gained `frames` and `time_ns`, read from
  the trajectory header by `analysis/runs/trajectory_header.py` (0.045 s to open a live 1.7 GB, 45,001-frame
  extension, 0.001 s to seek its last frame; never a frame walk, cached per process by path/size/mtime). `time_ns` is
  last frame time minus first, so the live extension reads 900 ns, not `frames × dt` (900.02). A header that cannot
  be read answers `null` and the panel prints "Frames and time not recorded for this segment." The Run view heading's
  "Open the zoomable figures in Runs" door and pdc's `gallery_note` fragment were removed. Tests: unit
  `test_trajectory_header.py`, the `/trajectory` fields pinned in `test_frame_series_analysis.py`, a new
  `browser/test_run_view_analysis_browser.py`, and the figure/rescore/overview browser tests moved to Run view.
- **2026-11-04 Trajectory overview**: a new on-demand analysis kind, `trajectory-overview`, samples the run's latest
  playable segment (at most 200 frames, one sequential pass) and publishes a 2×3 PNG plus a JSON record: RMSD and
  radius of gyration of the protein -- or of the detergent assembly in an empty micelle -- the largest detergent
  aggregate by the run's own `contact_nm`, and Temperature/Pressure/Potential from the sibling EDR. Energy columns
  are mapped by their XVG legend, because `gmx energy` writes them in the EDR's order, not the selection order. The
  Runs analysis toolbar gains a **Trajectory overview** button; a run with nothing to play answers `skipped` with
  the producer's reason. Each panel draws the raw samples at low alpha under a thick opaque moving average (5% of
  the plotted points, 2–25 samples), whose window is named in the legend and recorded under `smoothing`. Measured on `6c36b3c610f3` (900 ns, 92 DDM molecules): 28 s, largest aggregate 62.8 mean
  (74.1 in the second half), Rg 3.9 nm, T 300.00 K / P 0.99 bar / potential -192,666 kJ/mol. A minimum-image
  follow-up on the same run corrected that first reading: the 1.7 GB `whole.xtc` is `-pbc mol -center` on the whole
  system, not a clustered micelle, so the raw distances split one 92-molecule micelle into face fragments (largest
  26–92, Rg 2.25–5.36 nm). With minimum-image distances and a fixed first-frame aggregate the answer is one
  92-molecule aggregate at every sampled frame, free 0, Rg 2.13 nm (±0.005), 42 s.
- **2026-11-03 Per-GPU run admission**: `Coordinator.admit_device` replaced the host-wide
  `max_concurrent_runs` counter at all four start sites (create, admit, resume/continue, waiting); the setting is now
  a per-device ceiling, so two runs on different `mdrun_gpu` devices start together. The refusal is "This GPU is
  busy. Either wait for the run to stop or choose a free GPU." Pinned by
  `integration/test_run_gpu_capacity.py`.

- **2026-11-03 GitNexus removed**: the generated context block is gone from `AGENTS.md` and `CLAUDE.md` (which now
  points at `AGENTS.md`), the six `.claude/skills/gitnexus-*` trees are deleted, the local `.gitnexus/` index and its
  `.gitignore` entry are gone, and `test_agents_contract.py` no longer splits or asserts a generated block. Callers
  are found by search and pinned by tests, not by a graph.

- **2026-11-03 One stored frame series, and the Run view figures subpanel removed**: the Trajectory block's build now
  replaces `analyses/frame-series/run-frames.pdb` + `frames.json` in place instead of minting an attempt per
  arguments set. `Kind.stable_directory` is the declaration; the coordinator keeps one `frame-series` record and the
  worker publishes through `files.atomic_copy`, `frames.json` last. The panel always plays the stored pair, says so
  when the form names other arguments, and still plays the last good pair after a failed rebuild; attempts written
  before the change are still matched by the form's arguments. The third Run view subpanel (**figures**) and its
  `loadFigures` machinery are gone -- the Runs gallery and `GET /api/jobs/<id>/figures` stay. Plan:
  `docs/plans/2026-11-03-frame-series-in-place.md`.

- **2026-11-02 Resume from a checkpoint**: the Runs table gains **Resume** beside Delete, offered only for a
  `failed`/`cancelled` run whose stopped stage left its own mdrun checkpoint. It keeps the run id and the stage
  directory, and the worker hands that stage `MDRUN_CONTINUE=<checkpoint>`; the script skips the work before its
  final mdrun (and that mdrun's `grompp`) and runs `mdrun -cpi <checkpoint> -append` against the existing `.tpr`, so
  the trajectory, log and energy file grow. `Stage.checkpoint`/`resumes_in_place` declare what each stage can
  continue from (pdc legs `system.cpt`, assessment `prod/run.cpt`, extension `('prod/run.cpt','run.cpt')`, CG
  `md.cpt`, AA `run.cpt`, AA reference `3-run.cpt`; the osmotic series resumes itself). The old picker is renamed
  **Restart from stage** (button **Restart**) and keeps its archive-and-re-run behaviour. `mdrun_cpt` (minutes,
  default 10, prefilled 10 in the forms) is emitted as `-cpt` by `aa.mdrun_command_flags`. A run holds 3–8 current
  checkpoints (4–6 for pdc), ~38–100 kB each.

- **2026-11-02 Detergent conformation library**: a pdc run may now stamp each detergent from a library of whole
  molecules taken from micelle-only runs instead of repeating one template. `detergent_pdc/conformations/` validates
  the source runs, makes each molecule whole, stores it head-anchored with its axis on +z, selects exactly K = 2000 by
  a stratified split and writes canonical `library.json` + `library.sha256` under
  `<workspace>/conformations/<residue>/<key>/` (untracked, copyable); the key is the first 16 hex of the canonical
  spec, so a rebuild from the same sources is the same directory. A run names it by `{runs, size, seed}` (built or
  reused on demand) or by `{key, sha256}` (used as-is, source runs need not exist); `prepare` records it as the
  `detergent_conformations` input, the build stage re-verifies the digest and matches it bead for bead against the
  run's mapping, and both the build and the preview draw one entry and one azimuth per site from
  `default_rng([seed, 0xC0FF])` and stamp that same body. `null` leaves every earlier run byte-identical. The New run
  form gains a fourth card (**Detergent shape**: one conformation · build from runs · stored library), the preview
  prints the resolved key and size, and two routes serve the lists (`GET /api/pdc/conformations/runs`,
  `GET /api/pdc/conformations/libraries`).
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
