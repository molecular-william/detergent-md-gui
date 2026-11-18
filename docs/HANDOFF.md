# Handoff: current state, next actions, open items, incidents

State and open items for this repository. Rules live in `AGENTS.md`; subsystem behaviour and procedures live in
`docs/PROJECT_GUIDE.md`; scoring science in `docs/DDM_CALIBRATION.md`. Read this before touching the DDM CG chain,
the protein-detergent pipeline or the coordinator.

Per-slice history is not repeated here. Every landed slice is its own commit, with the rationale and the checks in its
message, and this file's earlier revisions are in git (`git log -p -- docs/HANDOFF.md`). What stays here is the
state, what is next, what is open, and the measurements and incidents a reader has to know.

## Current state (2026-11-16)

- **Surfaces: two models, and the Align-trajectory tickbox gone (2026-11-18).** `analysis/runs/surfaces.py`
  measures only `AA` (the atomistic reference) and `Simulated CG` (this run's own trajectory). The `Mapped raw` and
  `Mapped ring-scaled` variants are removed: no mapped trajectory is written and no mapped `gmx sasa` leg runs. The
  mapping still contributes its bead radii and one first AA frame mapped onto the beads, which is the rigid-body fit
  target that puts the CG envelope in the AA frame; it is one frame of positions, not a surface calculation. The run
  view's Shape section names the two models and its table filters to them, so an older attempt whose metadata still
  lists four variants reads the same way. The trajectory form's **Align trajectory** checkbox is gone; **Fit** and
  **Group** are the fit controls and are never disabled. Plan:
  `docs/plans/2026-11-18-surfaces-two-models-and-align-removal.md`; draft:
  `docs/design/drafts/2026-11-18-surfaces-two-models-and-align-removal.html`. The running dashboard unit predates
  this change (Python and template), so restart it with no run in flight.
- **New run: one Nonbonded and constraints section for AA and CG (2026-11-18).** The validation workspace's
  Stage settings gains one section shared by every dynamics leg -- AA NVT/NPT/production and CG equilibration and
  production; minimisation keeps its reviewed values. It exposes `rlist`, `rcoulomb`, `rvdw`, `rvdw_switch`,
  `vdwtype`, `vdw_modifier`, `nsttcouple`, `nstpcouple`, `lincs_order`, `lincs_warnangle`, AA `lincs_iter`, and for
  CG `coulombtype`, `epsilon_r`, `epsilon_rf`. The AA boxes prefill from the force-field block, the CG boxes from the
  reviewed profiles; a value equal to the reviewed one is omitted by `execution/nonbonded.py:overrides`, so an
  untouched run still renders its files byte for byte, and where the profile states no line (the coupling intervals,
  the AA LINCS numbers) blank writes no line and leaves GROMACS' own rule. The old Other run options → CG production
  cutoffs group is gone: those three now apply to the equilibration leg too. `nonbonded.check` refuses the
  combinations `readir.cpp` refuses -- `rlist` below a cut-off, unequal `rcoulomb`/`rvdw` outside PME, `vdwtype = PME`
  with a switched modifier, a switch not below `rvdw`, `epsilon-rf` outside reaction-field or below `epsilon-r`, and
  an AA cut-off past half the box -- at the queue route (409, the run-type refusal's status). The run read-back shows
  one `Nonbonded and constraints` group. `Profile.variable` now replaces a force-field-block line by folded name
  rather than only appending an absent option. Plan: `docs/plans/2026-11-18-new-run-nonbonded-and-constraints.md`;
  draft: `docs/design/drafts/2026-11-18-new-run-nonbonded-and-constraints.html`. The running dashboard unit predates
  this change (Python and template), so restart it with no run in flight.
- **New run: queue on the GPU or share it (2026-11-17).** The form's one Start button is two: **Queue run on GPU**
  (`#start-run`, the old id) and **Share run on GPU** (`#start-run-share`, enabled only when the selected device
  already holds a run, read from `/api/run/devices`' new `active: {device: [run ids]}` -- NVML's `in_use` is empty
  between create and mdrun). Both post a recorded run choice `gpu_sharing` (`queue`|`share`), advertised by the AA and
  CG adapters; absent keeps the historical refusal. `share` may take one slot past `max_concurrent_runs` for its
  device; `queue` is never refused for capacity -- a queue run whose device is full is stored `queued` with
  `gpu_queue:{device,requested_at}` and no worker, and `Coordinator.start_queued()` starts held rows oldest-first
  wherever a worker is released and after `reconcile`, so the queue survives a restart. A held row is cancellable
  (`cancel_job` ends it, `ownership_flags` offers `can_cancel`) and is never revived by the queue. `cg_run` lifts
  `gpu_sharing` around each kind's dialect, so composition and published-reference CG runs accept it too. Plan:
  `docs/plans/2026-11-17-new-run-gpu-queue-and-share.md`.
- **Equilibration statistics report the final half (2026-11-17).** The Run row's equilibration panel and the trajectory
  overview's stage-trace titles state the mean of the leg's **final 50 %** (`second_half_mean`) instead of the
  whole-leg mean, which mixes the transient with the plateau. The record keeps both numbers
  (`equilibration-traces.json` terms carry `mean` and `second_half_mean`; the overview's stage entries already
  spread the full summary), and a record published before the field still shows its `mean`, labelled as one. Plan:
  `docs/plans/2026-11-17-equilibration-final-half-mean.md`.

- **Trajectory overview: aggregate search, frame access, XVG parse (2026-11-17).** The overview's `_aggregates` tested
  every detergent atom against every other (2,112² distances per sampled frame); it now tests molecule bounding
  spheres first and measures atom distances only for the pairs whose spheres reach (2,450-5,700 of 18,336 on the pdc
  micelle), 417 → 86 ms per frame with the same grouping. The sampled-frame loop uses MDAnalysis' frame-offset cache
  (MDAnalysis writes `_offsets.npz` beside the trajectory it opened — an attempt's staged copy, never the run tree)
  instead of decoding every frame: 20k AA frames 0.84 → 0.01 s, 4001 micelle frames 3.26 → 0.17 s. `readers.xvg_columns`
  parses the data block with numpy (59 MB / 46-term XVG: 1.19 → 0.46 s) and falls back to the per-line reader for a
  ragged file. End to end: pdc micelle overview **85.6 → 19.9 s**, AA overview 13.8 → 12.6 s (its remaining time is
  `gmx energy`: two subprocess calls per `.edr` and a 3.2 s all-term XVG write), with `trajectory-overview.json`
  byte-identical on both runs. Plan: `docs/plans/2026-11-17-analysis-hot-paths.md`. Next lever if wanted: a direct
  `.edr` reader (removes ~4.5 s per AA overview, needs a parser or a dependency) and a cell-list aggregate search
  (the pdc overview is still 16 s of aggregates).
- **Performance hot paths: live-log scan, per-poll work, cold load (2026-11-17).** A running stage's log is no longer
  rescanned on every poll: `web/progress.py` keeps an append-aware scan state per file (52 MB: 0.92 s per poll before,
  0.1 ms after; the cold first scan still costs one full pass) and `views.eta`/`views.detail_revision` cache their
  parse/digest on `(path, mtime, size)`. `Store.read()` takes no write lock, runs no DDL and creates the schema once per
  file; the worker's runs-root quota walk is cached 10 s (the run itself is still measured every tick); the two
  analysis waits back off instead of reading SQLite 20×/s; `/figures` and the fit-job poll read one record; the
  catalogue is cached 10 s and invalidated by an import; the artifact index parses one `analysis-metadata.json` per
  directory. Browser: NGL (1.28 MB) is fetched when a panel first draws a stage instead of parser-blocking `<head>`,
  feature panel modules load on their tab, `/figures` is read only when the analysis set settles, the run chooser asks
  `/api/jobs` once for repeated run types, the pdc whole-trajectory poll stops with the panel, the runs poll stops
  while the tab is hidden, superseded pdc preview/extent requests are aborted, and static/feature assets carry
  `max-age=300` (an edited module needs a hard refresh within five minutes; Python/template changes still need the
  usual restart). Plan: `docs/plans/2026-11-17-performance-hot-paths.md`. Deliberately not built: a pre-build ETag for
  `/api/jobs` (the scan cache made the payload cheap, and a marker would have to carry every running log's size/mtime
  or freeze the progress line) and the `/api/readiness` parse memo (6 ms, twice per keystroke debounce).
- **Stage-wise progress bar for every run type (2026-11-17).** The Runs card's bar is one segment per *work* stage in
  the run's own plan, in plan order: AA's four dynamics stages keep their step-weighted widths; CG (mapping,
  parameterization, simulation, assessment, SASA), pdc (minimisation through back-mapping, without the two preparation
  stages) and osmotic (its one stage) are equal-width, because their stages have no comparable step count. The current
  stage fills its segment from its own percent; a stage with no percent sweeps; a planned skip is hatched and never
  reads as current. Colour is semantic (`STAGE_COLORS`: min/NVT/NPT/equilibration/production/assessment/fit/analysis/
  back-map). A run type with no segment table keeps the single fill. Plan:
  `docs/plans/2026-11-17-stage-progress-all-run-types.md`, which reverses decision 2 of the 2026-11-16 plan for
  cg/pdc/osmotic.
- **SASA stage: 48 dots/atom and the published AA radii (2026-11-17).** `sasa.sh` passes `-ndots 48` to both passes
  (was 4800) and copies the published Rowland-Taylor `vdwradii_AA.dat` into its AA directory before the AA call. The
  copy was missing entirely: `prepare` writes only the CG radii, and GROMACS fell back to guessing radii from atom
  names, so the AA surface was low by ~2% and disagreed with the validation `surfaces` analysis on the same run by the
  same amount (the warning it prints is the same with or without the file). `CODE_VERSIONS['sasa']` is version 3, so a
  run prepared under version 2 or earlier refuses stage 5 rather than publish a series its record does not claim. The
  prepared run still keeps no copy (`sasa_radii_aa` is a layout-4 input read in place); the validation `surfaces`
  analysis keeps its own `NDOTS = 240`, so only the CG run's stage changed.
- **Service.** `detergent-dashboard` is a transient user unit on port 5000, working directory = the checkout root.
  It was restarted 2026-11-17 12:40 HKT on the per-stage-physics tree (no run was in flight), and
  before that 12:05 on the stage-settings/deletable-library tree and 2026-11-16 18:23 on `696fae7`. Restart after a
  Python or template change: the unit keeps its
  imported modules for its whole life while `static/` is read per request. A restart is only safe with no run in
  flight. `77504a003e5e` (Glucose-CG-200ns, revision kind) failed on 2026-11-16 at CG assessment: `ff_assess` wrote
  `Overall Score : nan ± nan` and `validate_run` refused `report_interactions.out: nonfinite scores`. Fixed the same
  day -- the molecule is constraints-only, so there is no interaction half to score. The retry was then refused by
  the run's own code pins, repaired with a recorded `code_repair`, and re-run: the run **completed** 2026-11-16
  15:14 HKT with `interaction_scores.scored: false` in `validation.json`, the stratified distance figure, both SASA
  series and its three analyses. The clause that a new *fit* CG run needed a restart is satisfied by the 17:36
  restart, which also deployed the named-identity phases.
- **Store.** `workspace/dashboard` is 3.4 GB: 10 runs (six aa 200 ns, four cg) after the user deleted the five pdc
  1 us runs and two cg runs on 2026-11-16 (that deletion predates the tombstone code, so their names are not in
  `retired_runs`); `parameterizations/` 189 MB -- five records now named (`records/<slug>.json` plus their revision
  directories), with the fit scratch `77504a003e5e`'s retry recreated; `martini3/` 18 MB (the shared set every run
  reads in place, still the flat `legacy` install); `jobs.sqlite3` 3.5 MB. A stray empty `runs/jobs.sqlite3` from
  2026-11-06 was removed.
- **Store cleanup applied 2026-11-16** (474 MB removed, 82 MB reclaimed): `parameterizations/work/` (455 MB of fit
  scratch -- a re-fit restages it, and only `engine_command[4]` in three records names the vanished path), `preview/`
  (14 MB, an orphaned 2026-10-14 cache nothing reads), `dashboard.log` and the `_live*` screenshots (5 MB, 2026-10-30),
  `jobs.json`/`jobs.sqlite` and `workspace-migration.json` (0.8 MB, no reader); `jobs.sqlite3` was VACUUMED from
  85.7 MB to 3.5 MB (96% of it was free pages). `model_registry/` and `uploads/` are kept: empty, but they are path
  roots the code reads. The remaining 24 GB is evidence: 21.7 GB of pdc simulation outputs, 415 MB of captured
  console and 225 MB of derived analyses -- prunable only if the user asks.
- **Named identity is in place for runs, analyses and prepared runs** (phases 0-2, recorded under Next session):
  names are casefolded-unique, attempts are sequences, layout 4 names its inputs and code. Remaining: the named
  parameterization store, molecule version directories, then the contract step that removes the legacy digest branches.
  A checkout without git and without `DASHBOARD_CODE_VERSION` reads one code version, 'unknown', for every change.
- **Fixed on 2026-11-16** (each commit carries its own rationale and checks): the bonded writer kept six digits and
  answered 500 on Save as new (`e6aba99`); a reference CG run drew no bonds or colours and refused its overview
  (`5786b1c`); CG production accepts 0.5-50 fs (`0788ed4`); the CG surface draws rings at the table's own scale
  (`5f050b9`); a CG preset keeps its parameterization kind and a pinned reference digest compares like with like
  (`45f04d3`); a constraint-only CG model's assessment records its interaction half unscored instead of failing on
  the tool's `nan`; a failed stage's record and Runs card quote the tail of the stage log instead of the wrapper's
  exit-status line; the Run view gets de Jong et al.'s energy-conservation analysis, and a CG run no longer names a
  PME scheme.
- **pdc New run: one Stage settings fieldset, per-stage timesteps, presets, deletable shape libraries (2026-11-17).**
  Plan: `docs/plans/2026-11-17-pdc-stage-settings-and-library-deletion.md` (local). The form's *Other run options*
  fold is gone; its six groups are sections inside `fieldset.new-pdc-stages`, after the five stage editors. NVT, NPT,
  assessment and extension each open with **Duration · Timestep · Steps**: the four new settings are
  `pdc_nvt_dt_fs`/`pdc_npt_dt_fs` (0.5-20 fs) and `pdc_assessment_dt_fs`/`pdc_extension_dt_fs` (0.5-50 fs), blank
  meaning the reviewed profile's dt. The retired `pdc_equil_dt_fs`/`pdc_production_dt_fs` are still advertised for
  old payloads and translated in `_numbers`; the extension's own dt reaches only the restarted path (the
  `convert-tpr -extend` continue keeps the assessment tpr's dt, and the editor says so); the Steps box has no `name`
  and back-solves the duration. A preset bar (the validation ids, read through `preset-*` classes because
  `test_rendered_hosts` allows one writer per host) saves every named control for run type `pdc`; the store answers
  the adapter's builder names (`nvt_ps`, `seed`, ...) and the panel translates them back. Both preview disclosure
  blocks are deleted and the 3D viewer is 480 px. Stored shape libraries are deletable per row (browser confirm, then
  `DELETE /api/pdc/conformations/libraries/<key>` `{confirm:true}`); `Feature.mapping_deletions` and
  `features.forget_mapping(workspace, mapping_sha256)` let a mapping or parameterization deletion purge every library
  built from it (a library records the mapping file's byte digest), and both delete routes report `conformations`.
  Checks: fast tier **3017 passed / 1 xfailed**; pdc area **775 passed / 1 xfailed**; full browser tier **394 passed**
  at `-n 8`; ruff clean; live check on the restarted dashboard (form renders, presets/libraries routes answer, an
  unknown library key is 404 and a missing `confirm` 400). At `-n 16` two tests flaked under load
  (`test_pdc_preview_browser.py::test_the_empty_micelle_preview_is_the_detergents_own_mapping_and_carries_its_families`
  and `test_pdc_new_run_browser.py::test_the_stage_settings_start_on_the_catalogues_own_numbers`); both pass alone and
  the whole tier is green at `-n 8`, which is contention rather than a code failure.
- **pdc New run: per-stage physics, three-across rows, merged production, size/box estimate (2026-11-17 follow-up).**
  Plan: `docs/plans/2026-11-17-pdc-per-stage-physics-and-box-estimate.md` (local). This supersedes the previous
  bullet's five editors and six groups: Stage settings now has **four** editors (minimisation, NVT, NPT, one merged
  **CG production**) and **five** sections (output cadence, neighbour search and cutoffs, salt/seed/box, back-map,
  execution), and every grid is three controls across at desktop width, two below 1100 px, one on a phone. Each leg
  states its own `nstlist`/`ref-t`/`tau-t` (`pdc_nvt_*`, `pdc_npt_*`) and the merged production editor one shared
  `pdc_production_nstlist`/`_ref_t`/`_tau_t`/`_tau_p`/`_ref_p`/`_compressibility` set for both durations; its two
  Duration · Timestep · Steps rows keep the assessment/extension timesteps. The reviewed defaults are the profile
  values (40, 300 K, 1.0 ps; production barostat 1 bar/12 ps/4.5e-5), so untouched runs render byte-identical files.
  The run-wide `nstlist`/`ref_t`/`tau_t`/`ref_p`/`tau_p`/`compressibility` are out of `DEFAULTS` and the form but
  still advertised; `_with_leg_physics` in `_numbers` translates them onto the production names. The Execution
  section gains **Update and constraints** (`mdrun_update`), which reaches mdrun through `aa.mdrun_command_flags`,
  and the seed gains a **Generate** button. The Membrane protein card shows the protein's x × y × z and the initial
  box from `GET /api/pdc/proteins/<entry>/extent`, which calls `pdc_box`'s own rules on the structure's coordinates
  (membrane rule when the entry states one, belt reach 0), hidden for an empty micelle.
  Checks: fast tier **3034 passed / 1 xfailed**; pdc non-browser **794 passed / 1 xfailed**; pdc browser **104
  passed** with the known preview flake once (`test_the_empty_micelle_preview_...`, green alone); full browser tier
  **401 passed** at `-n 8` (one AA layout test flaked under load and is green alone), ruff clean. Live at the 12:40
  restart: four editors and the five sections render, the extent route answers for 1at9 and 4iar (membrane boxes
  10.4 × 10.4 × 11.168 and 9.6117 × 9.6 × 17.673801 nm), and a bad `margin_nm` is a 400.
- **Known gaps.** `dbc366ae772b` (the DDM AA reference) lacks `07_reference/run.sh`, so the DDM mapping `10c318949`
  refuses at `files.verify`; a CG-only reference run cannot be compared with a separate AA run; `docs/design/drafts`
  is 31 MB of local screenshots (gitignored, 152 files).

## Next session

**2026-11-18 analysis performance round: built (seven slices, two waves).**
Plan and execution record: `docs/plans/2026-11-18-analysis-performance-round.md`. What the audit found first, because
it frames everything below: the tab is **hybrid** by design (`pdc-structure` is GROMACS tools plus one NumPy/MDAnalysis
aggregation pass; the validation kinds are MDAnalysis + NumPy/SciPy/scikit-image/biotite with only `surfaces` shelling
out; the core kinds mix `gmx energy`/`gmx trjconv` with MDAnalysis), and the biggest lever was the **engine**, not the
numerics.
- *Staging (commit `b8ff2df`).* An attempt now stages each source as a **symlink** to the run's own file, and the
  producer's input guard is `files.stat_snapshot` instead of two SHA-256 passes. Staging on a 322 MB trajectory
  1.64 s -> 0.0004 s, whole attempt 1.76 -> 0.016 s. The ceiling is stated in `PROJECT_GUIDE.md` (*Run accounting*):
  a buggy producer writing through a link reaches the run's file and is detected, not prevented. The analysis
  subprocess now runs under `sys.executable`, not a `python` from the stage PATH.
- *Algorithms.* pdc's contact graph and protein-contact test are two `cKDTree`s (`8875dd1`): 40.9 -> 2.8 ms/frame at 100
  detergents, 186 -> 5.6 ms for the protein test at 8 000 beads, identical clusters and identical `pdc-structure.json`.
  `measure_torsions` 20.55 -> 2.32 s and BARTENDER reads `lig.xtc` once (`b0a3e17`); `frame-series` decodes only the
  frames it writes and formats each model once (`9674954`, 1.33 -> 0.18 s real, 22.7 -> 9.5 s worst case);
  `mapping-consistency` does one pass per trajectory with batched bead geometry (`3fa907b`, 10.9 -> 4.4 s).
- *Energy reads (`091311c`).* `read_energy(edr, work, terms=None)`: `equilibration-traces` and `energy-conservation`
  ask only for the terms they record, `trajectory_overview` keeps its all-term record, and the legs overlap on threads.
  AA overview 13.43 -> 8.87 s, AA eq-traces 7.40 -> 1.63 s, AA energy-conservation 10.86 -> 4.59 s.
- *One defect the slice proofs could not see.* `mkstemp` pre-creates its file, and GROMACS backs up an existing output
  as `#<name>.1#`; that name is not hidden, so the worker published it as a 0-byte artifact. The end-to-end replay
  through `python -m dashboard.analysis` found it; the placeholder is now unlinked before `gmx energy` writes. Lesson:
  compare the **output set**, not only the record.
- *Wave 2, `surfaces`/`osmotic`/`overlap` (`e568a93`).* The two mapped variants share one read of the AA trajectory
  (one decode instead of two), the envelope evaluates each sphere only in its own sub-box, the osmotic centre of mass
  is one gather/einsum and the overlap series one vector op per frame. `surfaces` 17.2 -> 15.0 s (published 18.8),
  envelope 118.8 -> 0.36 s at 2 000 beads/3.2M cells, osmotic 461 -> 296 us/frame, overlap publish 5.0 -> 2.6 s; 34/34
  files byte-identical (the `*.log` files differ only as GROMACS' own timestamps, proven by a HEAD-vs-HEAD control).
- *`coordinates_many` is not the mapped path, and that is a finding.* `sugars.coordinates` is dtype-sensitive: a float32
  trajectory makes its bead centre of geometry a float32 mean, while `coordinates_many` promotes to float64. On the
  real 20 001-frame reference they disagree on 18 378 frames after the timestep store and change the `surface.xtc`
  bytes, so `surfaces` keeps the per-frame oracle; `coordinates_many` is used where the caller already hands float64
  (`mapping-consistency`). A float64 batch for surfaces would be a published-numbers change, not a performance tweak.
- *Open.* `mapping-consistency` still reads the CG trajectory twice (the second read is core `bonded_terms.measure`),
  and `surfaces` still decodes the AA file twice (its own variant + the mapped pair) because two MDAnalysis readers of
  one file must not overlap.
- *numpy floor.* `np.vecdot` in `dihedral_fit`/`bonded_estimate`/`bartender_fit` is load-bearing for the +-180 branch
  cut, so `detergent-core` now declares `numpy>=2` (commit `5f89ab8`); the feature distributions inherit it through
  `detergent-core==0.2.0`. A numpy 1.x host needs a row-per-dot fallback, not a `.sum()`.

**2026-11-17 the pdc New run form is staged, and a run's equilibration traces are drawn in its Runs row.**
Approved draft: `docs/design/drafts/2026-11-17-pdc-new-run-clarity.html`; plan:
`docs/plans/2026-11-17-pdc-new-run-clarity.md` (both local -- `.gitignore` keeps drafts and plans out of history).
- *Stage settings.* The belt card's two duration pairs and four groups of `Other run options` became one
  `fieldset.run-settings` with five `details.stage-editor` (minimisation, NVT, NPT, assessment, extension), each with
  a facts line (`500 ps · free`) and its own inputs; the fold went from 10 groups / 37 controls to 6 / 27. The facts
  writer is `new-run-pdc.js`'s own table (the engine's `syncStageSummaries` is private and keyed to the AA/CG stages),
  and its Default buttons read `/api/pdc/catalog` under their own `pdc-default` class because `/api/defaults` answers
  400 for `pdc`.
- *A real display bug, fixed with it.* `pdc_nvt_ps`/`pdc_npt_ps` rendered blank: `DEFAULT_ALIASES` had no
  `nvt_ps`/`npt_ps` entry, so the panel never showed the 500 / 4 500 ps the run was using. `minimisation_steps` had
  the same problem and now has a control too.
- *Restraints are per leg.* `pdc_posres_min`/`pdc_posres_nvt`/`pdc_posres_npt` (yes/no, defaults yes/no/yes); the
  retired single `pdc_restrain_protein` is still accepted and `prepare` translates it (yes ⇒ minimisation and NPT),
  and it is no longer written into a new record. `pdc-nvt-v1` gained `define` as a variable, so the NVT leg can hold
  the window; assessment and extension are never restrained (they are the state that is judged and back-mapped).
- *Estimate.* The `<details>` and its static "the number is the server's" sentence are gone. The dashboard's own info
  button (`field-help`/`info-btn`/`setting-tip`, Escape and outside-click close it) carries `ESTIMATE_SUMMARY` (new,
  ~40 words) plus the caveat; `ESTIMATE_METHOD` (270 words) stays the route's own field because the tests that pin it,
  and a reader checking the number, still need it.
- *Diagnostics.* The run row's detail gained a `Diagnostics` disclosure beside `Stage settings`, fed by a new
  opt-in analysis kind `equilibration-traces` (`analysis/runs/equilibration_traces.py` reuses
  `trajectory_overview.STAGE_ENERGY` / `read_energy` / `ENERGY_POINTS`; one `gmx energy` per leg, three terms),
  `GET /api/jobs/<id>/equilibration-traces` (answers `published: false, run_stopped` until an attempt publishes), and
  `static/js/runs-equilibration.js` (Plotly, one chart per term, a target line only where the run recorded one). One
  file answering two legs is recorded once (the pressure-coupled one), so a CG run is one leg, not three.
- *Split.* The pdc form carries `new-pdc-form`; layout.css excludes it from the "stage editor ⇒ settings take 8
  columns" rule and pdc.css puts its editor grid two across inside the 6-column half, so the halves stay 6 + 6 and the
  390 px page still does not scroll sideways.
Checks: fast tier 2995 passed / 1 xfailed; `ruff` clean; pdc browser area 89 passed; `test_runs_table_browser.py`
13 passed (including the new diagnostics test); full browser tier 385 passed.
Live, on this workspace: the pdc panel renders all five editors with their facts lines (`200 000 steps · … ·
restrained`, `500 ps · free`, `4 500 ps · restrained`, `100 ns`, `900 ns`), and the traces for
`Glucose-AA-202ns-20261113` took **7.6 s** over three legs (≤501 points each, one `gmx energy` per leg); that run's
minimisation EDR carries no Temperature, and its panel says so rather than drawing an empty frame. Two attempts were
published on that run while verifying (`analyses/equilibration-traces/0001` and `0002`, the first with the banner
line as its version); the newer one is what a reader sees.
Still open: the failed `DDM_4iar_1conf_1us-5` needs a **fresh** run at 5 fs equilibration and 20 fs production (its own
record says 20 fs for both); its traces will then be readable in the new disclosure.

**2026-11-17 pdc restraint window needed grompp -r; the DDM micelle run then failed at NVT on its own timestep.**
The transient POSRES window added `define = -DPOSRES` to the minimisation and NPT legs, but the shared leg script
called grompp without reference coordinates, so GROMACS refused with "Cannot find position restraint file
restraint.gro (option -r)"; the fix (`dcc8f5f`) passes `-r system.gro` (the leg's own input structure) and moves
`pdc_leg` to version 2. The live run `DDM_4iar_1conf_1us-5` was repaired with a recorded `code_repair` (its
manifest original is under `workspace/.named-migration/code-repairs/`), and minimisation then converged in 534
steps (Fmax 609, machine precision reached before the 100 target). Its NVT leg failed at step 1 with LINCS errors:
the run records `pdc_equil_dt_fs = 20` and `pdc_production_dt_fs = 30`, so the equilibration ran at 20 fs instead
of the reviewed 5 fs (CG production is 20 fs); the equilibration bound (0.5-20) permits it, so the run needs a
fresh start at 5 fs. Minimisation's Fmax 609 also shows the 100 kJ mol-1 nm-1 target is not reached on this dense
CG micelle, which is why the reference minim.mdp keeps the same target.
**2026-11-17 pdc restraints, minimisation convergence and NPT barostat.** The protein-in-micelle pipeline now
generates martinize2 position restraints (`-p backbone`; vermouth 0.15 writes the `#ifdef POSRES` block inside the
cg molecule itp, not a separate posre file, and the cg tree is already a recorded input) and a new
`pdc_restrain_protein` choice (yes/no, default yes) adds `define = -DPOSRES` to minimisation and NPT plus
`refcoord-scaling = com` on NPT, released in production; `no` reproduces the previous files. `emtol` (100) and
`emstep` (0.001) are stated and tunable, and the NPT leg exposes `pdc_npt_pcoupl` (c-rescale default),
`pcoupltype` (isotropic default; two/six direction values are repeated like the AA legs), `ref_p`, `tau_p` and
`compressibility`; production physics is unchanged. The changed module bumps `pdc_system` 1->2, so a run prepared
under v1 refuses its not-yet-run System stage by design (reprepare/code_repair). Limits: `posre.itp` is not emitted
by this martinize2 version; multi-direction coupling repeats the one stated number. Checks: pdc area 754 / 1 xfail;
form/pairing browser tests 20; core mdp/run_scripts 73; ruff clean.
**2026-11-17 CG equilibration barostat controls.** The detergent-validation CG equilibration editor now states its
Barostat (`cg_equil_pcoupl`: no/Berendsen/Parrinello-Rahman/C-rescale), pressure-coupling type
(`cg_equil_pcoupltype`: isotropic/semiisotropic/anisotropic/surface-tension/volumetric) and target pressure
(`cg_equil_ref_p`, 0.1-100 bar). Defaults are read from the reviewed `cg-equilibration-v1` profile (c-rescale,
isotropic, 1 bar -- not the production profile's Parrinello-Rahman), so untouched runs render byte-identical MDPs;
overrides reach the equilibration MDP only and are recorded in the run settings/choices. Limits: the three settings
are revision-kind only until sugar_cg/composition adopt the choices (their forms hide them), a non-isotropic
coupling type still writes one pressure value (AA-style per-direction expansion is a follow-up), and the run view
shows the two choice names unlabelled until web/stage_settings._labels merges cg choices. Checks: core unit 1539,
targeted 77, CG browser 6 + related 18, integrations 24+18, sugar 21; ruff clean.
**2026-11-16 pdc Other run options gain the two MD timesteps.** `pdc_equil_dt_fs` (0.5-20) and
`pdc_production_dt_fs` (0.5-50) are advertised, posted from the New run fold's new Timesteps group, and flow into
both the written mdp `dt` and the ps->steps arithmetic: the equilibration setting governs the NVT and NPT legs, the
production setting the assessment and extension legs; blank keeps the reviewed profile's own dt and writes identical
MDPs. The two equilibration durations (`pdc_nvt_ps`, `pdc_npt_ps`) also gained form fields beside the CG production
legs, so the whole sampling schedule is stated before launch rather than only the production half. The four pdc
profiles in `execution/mdp/profiles.py` now mark `dt` as `variable` (the CG precedent), and a
dt that would leave a requested leg at zero steps is refused by name (only when an override is stated, so untouched
runs keep their arithmetic). The removal-path restart-equilibration template keeps 5 fs deliberately. Checks: pdc
area 745 passed / 1 xfailed, pdc units+mdp writer 749, integration 57, form/payload browser tests 3; ruff clean.
**2026-11-16 The pre-assembled micelle belt is a cylinder, not a torus.** pdc_placement measures the transmembrane
region as a cylinder about the membrane frame's normal (the user's follow-up: the normal, not a PCA axis; radius = the
slab atoms' radial extent, `radius_nm` a floor;
height = their axial extent at the stated membrane thickness) and places each detergent at its own closest surface
point: the sugar head one length outside along the local outward normal, the head-ward direction tilted 15 deg about
the tangent so the tail sits nearer the axis, over a vertical band 1.1x the old half-height. The record carries the
cylinder and `orientation` provenance; the sphere/self-assembly path is untouched. Measured on fixtures: a tilted
bundle gives a 24.2 deg axis; head-height spread exactly 1.5x; determinism and the overlap/clearance gates unchanged.
The `radius_nm` floor and the absence of a hard headgroup clamp are the two known trade-offs (a clamp would break
the literal 1.5x spread on thin frames). Checks: pdc area 738/1 xfail, fast and browser tiers green (the known
assessment-rescore flake passes solo), ruff clean; dashboard restarted.
**2026-11-16 Runs are named by their labels, and a run directory carries what its analyses read.** `cli/rename_runs.py`
applied: the ten legacy hex runs are now DDM-AA-reference-200-ns-matching-the-sugar-references-sampling,
DDM-CG-100ns-20261022, LMNG-AA-200ns-20261104, Maltose-AA-200ns-20261109, Sucrose-AA-200ns-20261110,
Glucose-AA-202ns-20261113, Glucose-AA-201ns-4fs-20261116, Glucose-CG-M3-200ns-20261116, Glucose-CG-200ns-20261116,
Glucose-CG-205ns-20261116; the ten old ids are retired, every manifest verifies and every analysis count survived
(ledger `.named-migration/run-rename.json`). The records migration additionally remapped six manifests' molecule
inputs to molecules/<id>/v1/ so they verify after the folder move. Second, a run directory is self-contained for its
analyses: every source outside the run is copied once into `runs/<name>/sources/<run-relative name>` (the paired AA
reference pair, the consumed revision's histogram files), `sources.json` records that run-relative name, the copy is
skipped when size+digest match, `source_path` prefers it, and the queue counts the durable copies. Copying only
`runs/<name>/` therefore rebuilds ff-interactions and the AA-reference analyses with no store and no reference-run
directory (proved by tests); attempts published before this change have no copies and can still only be re-analysed
where the original paths exist. Residual: the fit that was running during the migration was written by the old code
and needs `migrate_reference_pins --apply` once it ends; the dashboard restart is deferred until then. Checks: fast
**2936 passed / 1 xfailed**, browser **383 passed**, ruff clean.
**2026-11-16 Full named migration: molecules are versions, identities are names, references are editions.** The
source-data layer followed the records. `molecules/<id>/v1/` now holds every folder (12, ledger
`molecules/.named-migration/versions.json`; only DDM's rename is tracked) and `aa.resolve` refuses a flat folder.
All 10 job rows and manifests were re-selected to `{molecule_id, version: v1}` (ledger
`workspace/.named-migration/snapshots.json`), the three CG rows/manifests that embed a full `mapping_snapshot` had
only its nested snapshot rewritten (same ledger, extended), and `IDENTITY_VERSION` 3 binds a schema-3 mapping to
`{molecule_id, version}` + chemistry: 8 drafts re-keyed, 4 records restamped (top level, `current` and every revision),
one orphan record left alone (`Glucose-carbohydrate-paper-draft` has no draft to compute from; it refuses a name
reuse). References: `repair_reference_edition` removed `dbc366ae772b`'s vanished launcher with a recorded `repaired`
note and stamped edition 1, `migrate_named_records` re-pinned its consumer, and `migrate_reference_pins` moved all six
stored revisions from `reference_sha256` to `reference_edition`; `references.verify` accepts only an edition pin and a
fit now records `reference_edition` too. The two data residuals are real and recorded: the Trehalose paper draft's
bead assignments no longer match its molecule's canonical sugar fragments (proved pre-existing), and
`pdc._templates` still lists a legacy id-folder entry beside its versioned ones. A fit job running during the
migration (`f4364dc762d24da0`) was written by the old code and needs `migrate_reference_pins --apply` once it ends.
Checks: fast **2941 passed / 1 xfailed**, browser **383 passed**, ruff clean; dashboard restarted on the migrated
store.
**2026-11-16 Named identity finished: the live store is migrated and the legacy readers are gone.** Scope A closed the
two residuals (`pdc.prepare` records the Martini set by `martini3.VERSION` witness, and a versioned CG-only
molecule's `micelle_template.json` is discovered under its version folder). Scope B (`cli/migrate_named_analyses.py`)
was applied: every `<signature>/<attempt>` tree is now `<NNNN>-<YYYYMMDD>` (33 attempts; a second run `move=0
unchanged=10`), superseded `frame-series` entries were retired from their job row while their bytes stayed, and a v2
ledger with `--rollback` is in `workspace/.named-migration/analyses.json`. Scope C (`cli/migrate_named_records.py`)
was applied: all 10 manifests are layout 4 and pass `run_inputs.verify_manifest`, all 10 job rows carry digest-free
named snapshots, `martini3/v3.0.0-2121527/` is installed, five of six published references carry `edition: 1`, and
the ledger is `.named-migration/records.json`. A first apply exposed a real gap -- two CG runs named their revision
histograms under the *legacy content hash* of the store record -- fixed by rebasing store paths through each record's
`legacy_hash` (a re-apply rewrote those two manifests; the third run reported `manifests:unchanged=10`).
Then the contract deletion commit (`09f6cdb`) removed the `<signature>/<attempt>` readers, the digest
molecule-selection and layout-2/3 verification branches, the store's hash/owners addressing (with
`migrate_named_parameterizations.py`), the legacy work-dir reuse and the JS `content_hash` fallbacks, and Martini's
flat-install fallback. Three branches stay on purpose: `mappings.context`'s `Snapshot` legacy equality (the eight
saved drafts hash digest snapshots into their mapping identity), the unversioned `molecules/<id>/` shape (all twelve
live folders), and `references.verify`'s legacy digest pin -- `dbc366ae772b`'s reference cannot be stamped until its
missing `stages/07_reference/run.sh` is repaired, so its consumer `ce1318485197` keeps the old pin. Checks: fast
**2902 passed / 1 xfailed**, browser **382 passed** plus the known assessment-rescore flake (green solo), ruff clean;
dashboard restarted on the migrated store.
**2026-11-16 Named identity, phases 3-4: the store and the molecules are named too.** (3) A parameterization is
`parameterizations/records/<slug>.json` with `<slug>.revisions/<n>/` (`5de549a`): the slug is the mapping name, a
second model's save answers 409 with the existing name (explicit overwrite on confirmation), a rename moves record
and revisions, and a legacy record stays readable by content hash (`legacy_hash`) -- the contract deletion of that
branch is still to come. A run records `mapping: <slug>` + revision (hashes kept as provenance); readiness/prepare
resolve name-first and refuse a revision whose stamped identity is not the snapshot's; fit scratch is
`work/<slug>--<run>`. `cli/migrate_named_parameterizations.py` was applied to the live store the same day: dry-run
`move=5`, apply moved all five (Maltose-0-20261109, DDM_CG_20261021, LMNG-334, Glucose-carbohydrate-paper-draft,
Glucose-0), second run `unchanged=5`; `/api/mappings?view=summary` now stamps `parameterization_name`. (4) A molecule
folder is `molecules/<id>/<version>/` (`ed3e995`): an unversioned folder is the legacy shape read as its own
version (nothing in the store moved), imports always write a new `vN`, a selection is `{id, version, path, inputs,
atom_count, metadata}` with no digests and `verify_selection` compares `(id, version)` structurally, mapping
snapshots are `{molecule_id, version}` and still compare equal to a legacy digest snapshot, and the analysis
reference identity hashes molecule+version+chemistry. Martini 3 is `martini3/<version>/` with a `martini3.json`
witness (the live flat install still reads as `legacy`); `create_job` re-selects a run's molecule version from its
mapping and `cg.prepare` refuses a mapping fitted on another version. Checks: fast **2898 passed / 1 xfailed**,
browser **392 passed**, ruff clean. Residuals: `pdc.prepare` still hashes each Martini file as recorded evidence
(nothing gates it); a versioned CG-only import's `micelle_template.json` is not discovered under its version
directory; an in-place edit of a legacy unversioned molecule folder no longer invalidates mappings pinned
`version: null` (deliberate -- the version directory is the change detector) until the folders are migrated.
**2026-11-16 Named identity, phases 0-2: runs are names, analyses are sequences, provenance is names.** Approved by
the user: casefolded uniqueness, strip change-detection digests, rewrite the digest invariants. (0)
`dashboard/run_names.py` is the one rule -- `^[A-Za-z0-9](?:[A-Za-z0-9_-]{0,78}[A-Za-z0-9])?$`, a strict superset of
the 12-hex ids, so no directory was renamed; `create_job` slugs the label and suffixes a collision under `JOBS_LOCK`,
a deleted name goes to `retired_runs` and is never reused, and `run_path`/`views.usable_run_id`/`adoption`/
`references`/`fitting`/a revision's `aa_reference` all validate through it (`2d6783b`). (1) An analysis attempt is
`analyses/<kind>/<NNNN>-<YYYYMMDD>/`; its identity is kind + canonical payload + run name + source names + a code
version (`DASHBOARD_CODE_VERSION`, else `git describe --always --dirty`), never a digest; the legacy
`<signature>/<attempt>/` trees stay readable. (2) A prepared run is layout 4: `inputs.json` names
role/label/kind/root/path (a legacy digest entry still verifies), `stage_scripts`/`python_modules` record
`{name, version}` from `run_scripts.CODE_VERSIONS`, and `provenance.json` records the same and gates nothing; a
published reference carries `edition`, which `resolve` compares instead of re-hashing the 466 MB trajectory (a legacy
record keeps its digest branch, so an old reference is not faster until republished). Checks: fast **2869 passed / 1
xfailed**, browser **391 passed** plus the known assessment-rescore flake (green solo), ruff clean; the dashboard was
restarted on `9dd97ba`. Remaining, planned in `docs/plans/2026-11-16-named-identity.md`: phase 3 names the
parameterization store (`records/<slug>.json`, dual-read plus a migration CLI) and phase 4 versions molecule folders
and the Martini set; the contract step that deletes the legacy digest branches comes after those.
**2026-11-16 The paper's energy-conservation test reaches the Run view, and a CG run stops naming PME.** The new
`energy-conservation` analysis kind is the default for every `cg` run: it reads the production leg's `.edr` through
the shared `trajectory_overview.read_energy`, takes de Jong et al.'s last-600 ps window (Comput. Phys. Commun. 199
(2016) 1-7, section 2.4), and publishes a figure (whole leg, then the window with its drift fits) and a record of the
temperature drift, the potential drift and the drift of the ensemble's conserved quantity (total energy in NVE,
`Conserved En.` in NVT, enthalpy in NpT) divided by the potential's, with the paper's own 0.3 K / 0.12
straight-cutoff and 1.3 shifted-potential numbers as the scale. The verdict uses the paper's thresholds only where
the ensemble makes the ratio a conservation check; every CG production leg is NpT, so the record says the ratio is
bath exchange and checks that the temperature holds its target and the potential energy is stationary in the window.
Measured on run `77504a003e5e` (200 ns, 30 fs): 300.24 K against 300, potential drift 13.4 kJ/mol against a 57.5
standard deviation, state `steady`. Separately, the PME policy is one answer: `workflow._uses_pme` gives PME to the
atomistic stages only (an `aa_only` run, and a legacy CG run's `AA reference`), `aa.mdrun_command_flags(...,
pme=False)` emits no `-pme`/`-pmefft` and refuses a device scheme, the three CG-family normalizers retire
`mdrun_pme`/`mdrun_pmefft`/`mdrun_tunepme` (so a job or preset that recorded `mdrun_pme: gpu` can be retried), and the
New run form hides those controls outside `aa_only`. Tests: `test_energy_conservation.py` (the window and the ratio,
the NpT verdicts, the ensemble mapping, the registration), `test_mdrun_gpu_pme.py` (no PME flags, the AA control, the
refusal, `_uses_pme`, the normalizers), `test_sugar_cg_protocol.py`'s retirement case, and a browser case that the CG
form offers no PME control. Checks: fast **2825 passed / 1 xfailed**; browser **392 passed**; ruff clean. **The
dashboard needs a restart** for the Python and template changes; run `77504a003e5e` then owes the new kind, which its
Recompute asks for.

**2026-11-16 A failed stage's record is the tail of its own log, not the wrapper's exit-status line.** Run
`6ed68979edf0` (Glucose-CG-200ns, revision 1) failed at CG simulation; the card said `Command '['bash', ...]'
returned non-zero exit status 1` while the log said, below the grompp stanza, `Cannot compute PME interactions on a
GPU, because: PME GPU does not support: Systems that do not use PME for electrostatics.` The CG MDPs are Martini 3
`coulombtype = reaction-field`, and this run's choices were `mdrun_pme: gpu`, `mdrun_nb: gpu`, `mdrun_update: gpu`;
the earlier glucose run with `mdrun_pme: auto`, `mdrun_nb: auto`, `mdrun_update: cpu` ran the same stages to
completion. The form offers the PME scheme to a CG run, so this was a settings error a reader could only find by
opening the stage log; the run was then deleted by the user, so the evidence is the quoted manifest and log rather
than a replay. `workflow` now raises `StageFailed` carrying `failure_snapshot` -- the last 8 nonblank,
non-separator lines of the last 64 KiB of the stage log, with the `MPI_ABORT`/Open MPI banner dropped -- and the
Runs card shows the whole message verbatim (`runs.js`/`runs.css`), not its first line. The stage record, the run
`error`, the console line and the card therefore quote the tool; a log that cannot be read still names the stage
and its exit code. Tests: `test_stage_failure.py` (the record quotes the GROMACS block, the tail is bounded, an
unreadable log keeps the stage) and a Runs browser case that the card shows the second line, which is the one a
reader needs. Checks: fast **2812 passed / 1 xfailed**; browser **391 passed**, the new Runs case among them;
ruff clean. Ceiling: the New run form still offers `mdrun_pme: gpu` to a CG run whose MDPs are
reaction-field; refusing that combination in the adapter or the form is the next step if it recurs.

**2026-11-16 A constraint-only CG model is assessed, not failed.** Run `77504a003e5e` died at stage 5 on
`validate_run`'s `report_interactions.out: nonfinite scores`, after a completed 201 ns simulation and a finite
distance matrix. The glucose model is a rigid ring: three `[ constraints ]` and a virtual site, no bond, angle or
dihedral, so `ff_inter` wrote no `<group>_bonds_distr.dat` while fitting and its recorded baseline is the pairwise
family alone (`distributions.json`: `pairs 6`, `interactions 0`). `ff_assess` then reported `Overall Score : nan` for
an empty per-type set -- nothing to compare, not a short distribution -- and the stage's gate read the word as a failure; the
inventory already counted `interactions` but nothing consumed it. The fix reads the ITP the tool was handed
(`$INITIAL_DIR/$INITIAL_ITP`, exported by `assess.sh`) and only requires a finite interaction report when it declares
a bonded row; otherwise `validation.json` records `interaction_scores: {scored: false, reason, topology}` and the
distance scores stand. A model with bonds that still gets `nan` keeps failing, and a topology the caller cannot find
keeps the strict check. Two declarations of the same assumption are gone with it: the fit path's stage 3 outputs and
stage 5 inputs named `*_bonds_distr.dat`/`*_angles_distr.dat`, and `missing_files` treats an unmatched glob as missing,
so a *fit* of the same molecule would have died at "required outputs are missing or empty"; both now name
`*_distr.dat`. Measured by replaying the failed run's stage 5 in a scratch copy with its own environment: exit 0,
`validation.json` with the unscored note, `distance_diagnostics_stratified.json` and the stratified figure written.
Tests: `test_cg_assessment_validation.py` (constraint-only accepted and recorded; bonded model still refused; an
unnamed or missing ITP stays strict; a finite report adds no note; the two family declarations satisfy their
contracts). **The dashboard needs a restart** for the adapter's stage contract; the assessment fix itself is read per
stage, so **Restart from stage** on `77504a003e5e` finishes that run without one.

The retry then met the run's code pins, which is the guard working and not a second bug: the run prepared at 14:46
with `validate_run.py` and `assess.sh` at their pre-fix digests, so the stage was refused before it started. The
manifest now carries one `code_repair` record (both pins with recorded/found sha256, commit `39d9ed5`, stages 1-4 on
the recorded code and 5-6 on the current), the two digests were re-pinned, and `POST
/api/jobs/77504a003e5e/resume {"stage": "CG assessment (ff_assess)"}` ran stages 5-6 in 63 s. `77504a003e5e` is
**completed**: `validation.json` records `interaction_scores.scored: false` with its reason,
`distance_diagnostics_stratified.json` and `distance_matrix_stratified_LIG1.png` are written, `6_SASA/{AA,CG}` hold
their series, and the run's three analyses (`bonded-cross-check`, `dihedral-fit`, `ff-interactions`) completed. The
`ff-interactions` record publishes `available: false`, and its reason now names the constraint-only case among the
three (`ff_interactions.publish`), so a Recompute says something true about this run. The pre-repair pins are in
`resume_history/0001/manifest.before.json`. Checks after the repair: 18 passed in
`test_mapping_consistency_api.py`, ruff clean; the completed run was measured live, not replayed.

1. **Cross-run AA vs CG comparison** (asked 2026-11-16): the data and the approach are in its row below. Start with
   a plan in `docs/plans/` and settle the one science decision -- which mapping the published entry is compared through.
2. **`dbc366ae772b` missing `run.sh`**: re-publish that reference or leave the DDM mapping refused. Re-publishing
   rewrites a completed run's provenance, so it is the user's call.
3. **Derived store pruning**, if the disk matters: 225 MB of analyses and 415 MB of console logs are rebuilt or
   re-derived on demand, while the 21.7 GB of pdc outputs is evidence and archiving it is its own decision.
4. Then the queue in the table below: NGL's eager load, Plotly's warm, the sugar comparison subpanel.

## Open items

**Sugar comparison subpanel (deferred, hand-off 2026-11-10).** A validation subpanel comparing the three-bead ring
triangles and bead compositions of the published Martini 3 sugar entries with the sugars mapped and parameterized
here. Sources: `dashboard.models.sugars.reference` (`entries`, `signature`, `run_topology`, already 15% COG scaled)
and `reference.PUBLISHED_FOR`; our mappings' `rings`/`beads` and the fitted revisions' own `[ atoms ]`/
`[ constraints ]`; a run's `2_mapping/ring_targets.json` (`raw_mean_nm`, `target_nm`). Geometry: triangle sides are
the mapping constraints, area Heron, angles the law of cosines, the `TC4` site the centroid of its three parents, the
inter-ring link unscaled and outside the triangle. Show reference and mapped side by side, raw and scaled
distinguished; a reference entry is citation metadata, never validation, and `PUBLISHED_FOR` must not present a
layout match as another molecule's model. Measured 2026-11-10 on the scaled values: GLC 7.25 A2, LAC rings
6.82/6.04, TREH 6.70/6.76, our Maltose units 5.64/5.29; our scaled Maltose (mean 5.47 A2) is nearer the reference's
*unscaled* sizes, so show both and conclude nothing until a like-for-like AA source exists. Start with a plan in
`docs/plans/` and an HTML draft.

| item | state | next |
| --- | --- | --- |
| Sugar comparison subpanel | not started; hand-off 2026-11-10 | build the validation panel described above |
| Cross-run AA vs CG comparison | asked 2026-11-16 after run `0c5f5738089c`: the AA-vs-CG panels are single-run (they read `1_AA-reference/` + `2_mapping/` + `4_CG_sim/` inside one run), so a CG-only reference run can only be put *beside* an AA run, never compared with it | build it as a new kind: the AA run named in the request (its `stages/07_reference/lig.{gro,xtc}`), this run's `4_CG_sim/prod/lig_CG.{gro,xtc}`, and the bead-atom correspondence from the sugar package's own candidate; needs a payload/UI "compare this run with run X" and one science decision (which mapping the published entry is compared through) |
| `dbc366ae772b` AA reference lacks `07_reference/run.sh` | `reference.json` records its digest, so `files.verify` refuses the DDM mapping `10c318949` with `Cannot reuse changed or missing artifact`; the other six revisions verify | decide whether to re-publish that reference (a new record over the files it has) or leave it refused |
| Workspace store cleanup | applied 2026-11-16: 474 MB removed (fit scratch, orphaned preview, stale logs and pre-sqlite files) and the job database VACUUMED 85.7 -> 3.5 MB; what remains is evidence | decide whether to prune the derived analyses (225 MB) and console logs (415 MB), or archive the 21.7 GB of pdc outputs |
| Align trajectory's initial state | the form prefills defaults, so a stored series built with `fit: rot+trans` opens with the box unchecked while its summary line says the fit | decide whether Frame options should prefill the stored build's arguments instead of the defaults |
| Analysis checklist membership | the checklist lists the run's attempted kinds; a kind never queued is absent | add a server-side "what this run can compute" list and show those unticked, if wanted |
| A fit's unsaved torsion choice | the revision records what the job started with, but `refine_bonded` reads the mapping's saved `model.json`; measured on `10c318949` revision 1 | decide: pass the job's options to the refiner, record the mapping's options, or let a successful fit save the pair to the mapping |
| `dihedral-fit` has no circular reading | it skips `funct 2`, the circular model's spelling, so it checks a legacy fit only; the panel caveat says so | add a harmonic branch, or keep it as the legacy-only check |
| pdc contacts on a protein run | `gmx mindist -on` contacts are produced only when the run records a protein; no completed protein pdc run exists to verify it on | verify on the first completed protein pdc run |
| pdc energy and SDF | `pdc-structure` is built; `pdc-interaction-energy` waits on Q10-Q12/Q14/Q15 and `pdc-sdf` on Q18-Q25 in `docs/plans/2026-11-09-pdc-analyses-definitions.md` (Q25 has no Plotly reader) | answer the numbered questions, then build energy, then SDF |
| pdc cluster step | 1 of 4 live producer runs failed inside `gmx trjconv -pbc cluster`; the cause was hidden by the old error tail, which now reports the real GROMACS line (`error_tail`); the three repeats were identical | if it recurs, capture the reported line and decide a retry or a cheaper clustering |
| NGL is eager on every panel | one blocking 1,284,224 B script on every page, 68% of the shell's script bytes; Runs, New run and Bonded build no scene | make it lazy like Plotly (`vendor/ngl-loader.js`) and load it for Run view/Complexes/Bead editor; `window.NGL` has readers in three distributions |
| Plotly warm and the default figure | a panel that plots asks for its own bundle at mount, so a shown-panel warm cannot help it (Bonded first content 4275 ms); a cold Run view also pulls a 10,300.8 KB interactive figure | decide plan open decisions 2 and whether the first figure waits for a click or visibility; do not prefetch hidden panels |
| CG-only molecules beyond pdc | a `kind: cg` folder works as a pdc detergent without a mapping; compositions, osmotic and CG conformation libraries still assume a mapping | separate slice if wanted (`docs/plans/2026-11-05-feature-round.md`) |
| `pdc_preview.py` wording | prepare/build describe a no-mapping CG molecule correctly; the preview still says "one centre per molecule" for any no-mapping build | align the preview's sentence with `_limitations` |
| analysis progress visibility | queued and watched only in Run view now: the Runs card's Analysis graphs panel is gone | decide whether the Runs card needs a one-line "analysis running" pointer |
| Overall Run view progress | the card bar is the current stage's fraction; timeline/plan skips show settings | decide whether a true run-level percentage is wanted |
| `aa_only` overview energy | the overview stages the selected leg's own `.edr`; an AA-only reference's energy is in `06_production/run.edr`, a different stage | extend the lookup for an `aa_only` run if wanted |
| cloud vs rough belt | open measurement, not a task | one protein, one seed, two 100 ns legs; compare removal fraction/aggregation/belt thickness before adopting a belt criterion |
| mutation signal | 9 caught, 1 survived (control), 1 stale: `cg-timestep-on-the-wrong-half` anchors on `if folder == aa_dir:`, which the audit refactor removed (`bfd2f82`) | retarget that mutant to the current `cg.mdp_values` line |
| `pytest-socket` | not installed; no test enforces the no-outbound-HTTPS audit | add with `--allow-hosts=127.0.0.1,localhost` |
| known test flake | `test_pdc_preview.py::test_the_cached_step_is_not_run_again...` failed in one full fast run and passed alone | capture a failing order with `-p no:cacheprovider` |
| checkpoint resume before a stage's last mdrun | Resume is hidden there (no checkpoint for the final mdrun) and Restart re-runs the stage | decide whether the pdc extension should continue a death in `eq`/`ramp` instead of re-entering the stage from its inputs |
| Phase 4 sucrose/maltose | deferred; targets remain `availability: metadata_only` | separate decision |
| native micelle builder | paused; `micelle/` is a partial, unvalidated skeleton | do not present it as a model |

## Incidents and measurements worth keeping

### Incidents worth keeping

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

### Current measurements

- SASA `-ndots` sweep (2026-11-17, whole trajectories on one core; glucose AA 24 atoms/20,001 frames, glucose CG
  4/20,021, DDM AA 81/20,001, DDM CG 11/20,001): the trajectory **mean is insensitive** -- 24 dots already matches 4800
  within 0.06%, and the AA-vs-CG gap (2.99% glucose, 7.29% DDM) is unchanged at every setting -- while **per-frame
  values and the spread are not**: at 24 dots a frame is 2-3% off (max 13%) and `std` is 3.6x high on glucose AA and
  34x on glucose CG; at the chosen 48 dots, ~1.0-1.2% per frame and glucose CG's std still 18x high. Time is
  sublinear, ~`ndots^0.75`: a real stage run went 48.5 -> 4.0 s (glucose) and 217 -> 11.2 s (DDM), means moving
  <=0.02%. 960 is the knee if frame-level variability is ever a decision input (0.2% per frame, std within 3%).
- SASA AA radii (2026-11-17): the stage's AA pass ran with GROMACS-guessed radii because `6_SASA/AA/` never received
  the published `vdwradii_AA.dat`. The file moves the AA mean by -1.8% (glucose 4.1612 -> 4.0861) and -2.1% (DDM
  9.7326 -> 9.5240), so the AA-vs-CG gap moves 2.99 -> 1.20% on glucose. The validation `surfaces` analysis, which
  builds the same table, reports 4.0865 for that AA surface; the stage now agrees with it. The DDM run (prepared
  2026-10-22) still had the file and its stored AA value matches the corrected convention.
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

## Where to read what

- Rules, invariants, verify commands: `AGENTS.md`.
- Repo layout, source ownership, run contracts, module notes: `docs/PROJECT_GUIDE.md`.
- Scoring, linkage, carbohydrate evidence and limits: `docs/DDM_CALIBRATION.md`.
- Plans live under `docs/plans/`, local to the checkout and untracked (except its `README.md`); `docs/design/drafts/`
  is untracked too, and `docs/design/` holds design records, not plans.
- What a slice changed and why: its commit message. What an earlier version of this file said:
  `git log -p -- docs/HANDOFF.md`.
- Superseded measurements are not kept: use the code, the manifests and the run records as the record.
