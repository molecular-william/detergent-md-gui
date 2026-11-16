# Handoff: current state, next actions, open items, incidents

State and open items for this repository. Rules live in `AGENTS.md`; subsystem behaviour and procedures live in
`docs/PROJECT_GUIDE.md`; scoring science in `docs/DDM_CALIBRATION.md`. Read this before touching the DDM CG chain,
the protein-detergent pipeline or the coordinator.

Per-slice history is not repeated here. Every landed slice is its own commit, with the rationale and the checks in its
message, and this file's earlier revisions are in git (`git log -p -- docs/HANDOFF.md`). What stays here is the
state, what is next, what is open, and the measurements and incidents a reader has to know.

## Current state (2026-11-16)

- **Service.** `detergent-dashboard` is a transient user unit on port 5000, working directory = the checkout root.
  It was restarted 2026-11-16 14:45 on `45f04d3`. Restart after a Python or template change: the unit keeps its
  imported modules for its whole life while `static/` is read per request. A restart is only safe with no run in
  flight. `77504a003e5e` (Glucose-CG-200ns, revision kind) failed on 2026-11-16 at CG assessment: `ff_assess` wrote
  `Overall Score : nan ± nan` and `validate_run` refused `report_interactions.out: nonfinite scores`. Fixed the same
  day -- the molecule is constraints-only, so there is no interaction half to score. The retry was then refused by
  the run's own code pins, repaired with a recorded `code_repair`, and re-run: the run **completed** 2026-11-16
  15:14 HKT with `interaction_scores.scored: false` in `validation.json`, the stratified distance figure, both SASA
  series and its three analyses. A restart is still needed before preparing a new *fit* CG run: that adapter
  contract is imported at startup, while a repository stage script is read fresh per attempt.
- **Store.** `workspace/dashboard` is 24 GB after the cleanup below: 16 runs (five pdc 1 us runs 21.7 GB, four aa
  200 ns 1.9 GB, seven cg 1.0 GB); `parameterizations/` 27 MB (the records and their own revisions); `martini3/`
  18 MB (the shared set every run reads in place); `jobs.sqlite3` 3.5 MB. Inside `runs/`: 415 MB of captured console
  and 225 MB of derived analyses.
- **Store cleanup applied 2026-11-16** (474 MB removed, 82 MB reclaimed): `parameterizations/work/` (455 MB of fit
  scratch -- a re-fit restages it, and only `engine_command[4]` in three records names the vanished path), `preview/`
  (14 MB, an orphaned 2026-10-14 cache nothing reads), `dashboard.log` and the `_live*` screenshots (5 MB, 2026-10-30),
  `jobs.json`/`jobs.sqlite` and `workspace-migration.json` (0.8 MB, no reader); `jobs.sqlite3` was VACUUMED from
  85.7 MB to 3.5 MB (96% of it was free pages). `model_registry/` and `uploads/` are kept: empty, but they are path
  roots the code reads. The remaining 24 GB is evidence: 21.7 GB of pdc simulation outputs, 415 MB of captured
  console and 225 MB of derived analyses -- prunable only if the user asks.
- **Fixed on 2026-11-16** (each commit carries its own rationale and checks): the bonded writer kept six digits and
  answered 500 on Save as new (`e6aba99`); a reference CG run drew no bonds or colours and refused its overview
  (`5786b1c`); CG production accepts 0.5-50 fs (`0788ed4`); the CG surface draws rings at the table's own scale
  (`5f050b9`); a CG preset keeps its parameterization kind and a pinned reference digest compares like with like
  (`45f04d3`); a constraint-only CG model's assessment records its interaction half unscored instead of failing on
  the tool's `nan`; a failed stage's record and Runs card quote the tail of the stage log instead of the wrapper's
  exit-status line; the Run view gets de Jong et al.'s energy-conservation analysis, and a CG run no longer names a
  PME scheme.
- **Known gaps.** `dbc366ae772b` (the DDM AA reference) lacks `07_reference/run.sh`, so the DDM mapping `10c318949`
  refuses at `files.verify`; a CG-only reference run cannot be compared with a separate AA run; `docs/design/drafts`
  is 31 MB of local screenshots (gitignored, 152 files).

## Next session

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
