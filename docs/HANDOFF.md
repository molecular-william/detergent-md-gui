# Handoff: current state, open items, recent slices

State and open items for this repository. Rules live in `AGENTS.md`; subsystem behaviour and procedures live in
`docs/PROJECT_GUIDE.md`; scoring science in `docs/DDM_CALIBRATION.md`. Read this before touching the DDM CG chain,
the protein-detergent pipeline or the coordinator. This file keeps only what is current and the evidence behind it.

## Next task

The 2026-11-05 nine-point round is implemented and committed (items 1-6, 8, 9; there was no item 7). Its plan is
`docs/plans/2026-11-05-feature-round.md`, which carries the decisions, the per-lane evidence and the two corrections
found while building. The open items table below is the queue; the two the round left behind are the first two rows.

The 2026-11-06 Run-view Analysis slice is built and live-checked; its plan is
`docs/plans/2026-11-06-run-view-analysis-fixes.md`. It fixed the cross-check's preprocessor failure, the fit
temperature it reads, the dihedral reader's treatment of periodic impropers, and the overview's stage-level `.edr`
lookup; it compacted the figure tabs and task list, reduced the card spacing, and made the second monitor
minimizable. The dashboard was restarted at 11:39. Live: `67bc79a995d6`'s cross-check publishes 22 terms (8 bonds,
14 constraints) at the fit's 300.0 K; `dihedral-fit` publishes one proper dihedral with eight harmonics; the overview
reports Temperature 303.1535 K, Pressure 0.9865 bar and Potential −14,634.92 kJ/mol from `4_CG_sim/md.edr`.

The 2026-11-06 mapping-analysis move is built and live-checked; its plan is
`docs/plans/2026-11-06-mapping-analyses-in-run-view.md`. The Mapping Validation tab, its panel module, its template,
its run picker and the Runs card's validation button are retired. Each Run view monitor's Analysis card now carries
the sections the validation feature registers — **Geometry**, **Bonded terms** and **Shape and volume** — read from
the same published `/api/jobs/<id>/mapping-consistency` record, and every completed run gets the card (an `aa_cg` run
offers the sections; an `aa_only`/`pdc` run gets a one-sentence "not defined" notice; a stopped `aa_cg` run with no
attempt gets the endpoint's reason). The engine seam is `web/static/js/run-view-analysis-extension.js`; the
validation module is `run-view-mapping.js`. The dashboard was restarted at 15:53. Live: `22075892b606` (Maltose,
`aa_cg`) shows 6 constrained pairs and an 8-bar chart, 6 term rows and 4 SASA rows; `619ab118abd6` (`aa_only`) shows
the notice and no mapping tabs; the retired URL answers 404; the validation workspace has 7 tabs. Checks:
`pytest -m 'not browser and not slow' -q` 2467 passed, 1 xfailed; `pytest -m browser -q -n 16 --dist worksteal`
290 passed; `ruff check packages tests conftest.py` clean.

The 2026-11-06 follow-up adds the missing start control. A stopped `aa_cg` run with no published comparison now
offers **Calculate the comparison** in Geometry; it posts `/api/jobs/<id>/mapping-consistency` with `{}` and the
validation feature's `_mapping_payload` derives the mapping snapshot, molecule and `cg_names.final_itp` from the
run's own record. `67bc79a995d6` was queued this way at 16:30 and attempt `06a79aef9a0c` published 12 pairs (0
outside the AA observed range), 34 terms and rmsd 0.0274 nm; its cross-check and dihedral fit were already
published, while surfaces and overlap still have to be queued by hand.

The 2026-11-09 comparison-map slice is built and live-checked; its plan is
`docs/plans/2026-11-06-comparison-map.md`. One map per monitor sits above the mapping sections; the section tabs are
its perspectives (Geometry = displacement + pairs, Bonded terms = terms coloured by overlap, Shape = per-bead overlap)
and it is hidden on Figures. The production renderer reuses `bonded-plot.js` with optional `beadColor` (including
`ramp`), `pairs`, `term.ink`, halo selection, `height` and `uirevision`; the Bonded panel passes none of them and is
unchanged. The map controller resolves `(residue,letter)`, `B01` and the mapping name to one bead key, reads
`stages/2_mapping/model.json` + `mapped.gro` (static first frame), and renders a headline plus top-three ranked
attention per perspective; no composite score. Shape also offers **Calculate surfaces** and **Calculate bead overlap**.

The live check exposed and fixed a real overlap bug: `overlap` was staged the all-atom `1_AA-reference` (atoms
`C`/`C1`, residue `LIG1`) and read the model's residue name for both sides, so it died on the first Universe. It now
stages `2_mapping/mapped.{gro,xtc}`, compares the mapped AA beads with the CG leg, and reads each side's own residue
name (`overlap.publish`; `kinds.py` no longer declares `reads_aa_reference`). On `67bc79a995d6`, overlap published
253 pairs with mean 0.710, and surfaces published four SASA rows; the Shape envelope and overlap figures are present.
The dashboard was restarted at 09:24. Live map: 12 pairs, all unconstrained (the pinned entry states none), largest
displacement 45 pm at (4,C); 34 terms, 3 below overlap 0.5. Checks: fast tier 2471 passed, 1 xfailed; browser 303
passed; ruff clean.

The 2026-11-09 next-round request is with the durable `next-round` agent; its queue, evidence and open decisions are
`docs/plans/2026-11-09-next-round.md`. First-wave A and B are built and committed; C is research only.
`d96eb46` warms the catalogue lists on idle and keeps them for five minutes, re-reads the live run list without
rebuilding a shown Run view pair, and mounts Bonded once until its resources change. Measured revisits: Run view
1706 -> 767 ms and 21 -> 4 requests; Bonded 801 -> 585 ms and 2 -> 0 requests; New run first visit after idle 7 -> 2
requests. `0e42297` groups only the angle rows in a native details/summary, open by default; a map attention item that
names an angle opens the group first. The Shape draft is
`docs/design/drafts/2026-11-09-shape-surface-comparison.html` (PNG beside it): the AA-vs-Simulated-CG surface
comparison above the bead map, with the map explicitly labelled "bead overlap, not surface area". It is a draft only;
the user still has to confirm above-vs-replace, AA-vs-CG-only vs variant selector, and whether a 2D SASA-vs-time chart
is wanted. Checks after the two commits: fast 2471 passed / 1 xfailed, browser 307 passed, ruff clean. Task-7
(Fast-Forward output inventory, Martini sugar reference feasibility, compact New run settings draft) is done as
research only; no production code for New run, sugar selection or FF plotting. Notes:
`docs/research/2026-11-09-fast-forward-outputs.md` (stage 3 fit data vs stage 5 assessment data; four ranked plots:
reference-vs-simulated distributions, Hellinger score ranking, pairwise distance-score heatmap, run-quality summary;
the pickles are optional and unpickling run artifacts in the web process is a code-execution surface);
`docs/research/2026-11-09-martini-sugar-references.md` (SUCR/TREH topology, existing sugar machinery, three options
A compare-only / B reference-seeded parameterization / C B plus a CG simulation scored against AA; the reference is a
citation, not a validation); and `docs/research/2026-11-09-new-run-settings-specs.md` + the compact-settings draft
(advertised-vs-rendered table, `cg_seed` and `box_shape` gaps, exact GROMACS 2026.3 `mdrun -h` quotes, proposed
`cg_seed`/`mdrun_pmefft`/`mdrun_update`/`mdrun_tunepme` additions). The decisions still open are printed in the plan
and the drafts: FF plots, sugar run shape/acceptance, which mdrun extras and MDP values, and whether `box_shape` is
exposed or removed.

The Shape decision is built: `bbe4691` + `cb074f3` replace the map in Shape with the AA vs Simulated CG two-panel
surface comparison and a 2D SASA-vs-time chart, keep bead overlap as a separate labelled block, collapse the angle
group by default, and add **Recalculate surfaces** for attempts that predate the pair. The surfaces producer now
publishes `surface-comparison-aa-cg.json`; the route rebases the pair and the per-model `sasa.xvg` paths to run-root
artifacts. The dashboard was restarted at 10:50 for the Python changes. Live on `67bc79a995d6`: the Shape map is
hidden, the two panels draw (AA 14.819 nm² vs Simulated CG 13.728 nm², probe 0.191 nm), and both SASA series carry
20,001 frames; the new surfaces attempt is `b524698b71d3`. Older attempts show their published figure plus the SASA
series and the recalculate action. Checks: fast 2471 passed / 1 xfailed; browser 308 passed; validation browser 29,
integration 10; ruff clean.

The 2026-11-09 FF/sugar/MDP wave is built. The validation feature adds the on-demand **`ff-interactions`** kind and
route: fitted runs read stage 3 reference distributions, reference-seeded runs resolve the revision's histograms from
the parameterization store, and stage 5 supplies the simulated side; text `.dat`/`.out` only, and the record states
`source` plus a missing side rather than drawing one curve. Bonded terms now has a right-hand FF panel: selecting a
term shows reference vs simulated and labels **FF Hellinger distance**, **FF score** and the dashboard **overlap
coefficient** separately. Live on `67bc79a995d6`: 34 terms (10 bonds, 22 angles, 2 dihedrals), the analysis completed,
and the first term's chart draws both 180-bin series. The live queue exposed a worker provenance bug for store files
outside `runs/`; `_source_provenance` now names them from the workspace and is pinned by
`test_analysis_source_provenance.py`.

The validation feature also adds the CG-only **`sugar_cg`** run type: Sucrose or Trehalose plus the published
Martini 3 `SUCR`/`TREH` entry, AA coordinates mapped onto the published layout, the reference's own topology, one
molecule in Martini water, CG minimization/equilibration/production, no AA reference/mapping/fit and no automatic
comparison analyses. Sucrose conforms; Trehalose is selectable-but-blocked because the published `TREH` second `TC4`
carries residue 1. The New run form gets the sugar selector, provenance and conformance preview; its `sugar-cg-v1`
default is 5 ns equilibration / 10 ns production, and switching to/from sugar re-defaults rather than leaking the
AA–CG 10 ps/10 ns values. `4ab5bf8` fixed the live order race where the molecule list's DDM fallback could reset a
sugar selection before Sucrose was chosen, and keeps AA/AA-CG CG choices when those two are toggled. No full CG MD was
run; the adapter's prepare smoke reached `min.tpr`, and the form preview
was checked live.

New run also has the transferable pdc **Other run options**: output cadence, neighbour/cutoffs, thermostat/barostat
couplings, `cg_seed`, `box_shape`, and mdrun `pmefft`/`update`/`tunepme`. MDP overrides are scoped to the CG production
leg; untouched runs write the reviewed MDP byte-for-byte. Help is one server-side map from the GROMACS 2026-rc MDP
manual and `gmx mdrun -h`, returned with `/api/defaults`; the form has no duplicated help prose and the info buttons
are keyboard/focus accessible. The dashboard was restarted at 11:47 for the Python changes. Checks: fast 2511 passed /
1 xfailed; browser 318 passed; ruff clean; worker provenance and run-type default tests added.

The performance work that was **not** done in `d96eb46` is now the built 2026-11-09 follow-up; the plan is
`docs/plans/2026-11-09-performance-follow-up.md` and its three audits are
`docs/research/2026-11-09-performance-cold-content.md`, `-polling.md` and `-surfaces.md`. **Loading states**: the shell
marks the open panel busy while boot's feature imports and a tab mount are pending (`panel-busy.js`'s `setPanelBusy`, one
`role=status` line as the panel's first child, `aria-busy`); `[aria-busy="true"]` has CSS for the first time (five
modules set it; no stylesheet read it), `main.js` marks every tab mount and the section pane while an analysis section
reads its record, and Runs' `mount()` now returns its first read so the line lasts until the table fills. **Polling**:
`shared.js` gained `liveVisible()`, `whenLive()` and `liveApi()`; the Runs, Analysis, Trajectory, pdc whole-trajectory
and Bonded pollers stop on a hidden tab or panel and resume with the same read, and the Analysis card and Trajectory
block share one `/analyses` request per tick instead of two. `/api/jobs/<id>/analyses?view=summary` drops
`result`/`environment`/`tools`/`command` (the default answer is unchanged): on `67bc79a995d6`, 527,290 B -> 33,245 B.
**Surfaces**: the four variants' gmx commands are pipelined behind the main-thread XTC extraction (bound 4), failures are
joined per variant, and a producer reports phases through `dashboard.analysis.progress` (`DASHBOARD_ANALYSIS_PROGRESS`);
one timed end-to-end rerun took 48.2 s against 83.0 s (1.72x), with NDOTS/frames/probe/variants unchanged. Not built:
the shown-panel Plotly warm -- a panel that plots asks for its own bundle at mount, so only a hidden-panel prefetch
would help, which the plan rejects by default; NGL is still an eager 1,284,224 B script on every page. Checks: fast
2523 passed / 1 xfailed; browser 325 passed; slow 25 passed; ruff clean. The dashboard was restarted at 13:39. Live on
`67bc79a995d6`: `/analyses` 527,290 B -> 33,265 B, and a queued `surfaces` attempt (`73051f3c10b0`) published in
50.6 s with the phases above and the same numbers as the earlier attempt (AA 14.819, Simulated CG 13.728 nm²).

The 2026-11-09 Run view Analysis UI slice is built and live-checked on `67bc79a995d6`; its plan and draft are local
(`docs/plans/2026-11-09-analysis-ui.md`, `docs/design/drafts/2026-11-09-analysis-ui.html` + `.png`). The analysis list
is a ticked checklist (`run-view-analysis.js`/`run-view.css`, `.analysis-check`): a completed kind is ticked, a failed
one is unticked with the last line of its console and no Log link, and an unsettled one shows its progress and Cancel.
The validation sections start compact: Constrained pairs, Bonds, Angles and "Our fit against the independent estimate"
are closed `<details>` (the map's focus opens the group that holds the term it names), and in the full-width card
(`#run-view-monitors.one-column`, second monitor minimized) the comparison map's scene and its Reading box sit side by
side. Shape and volume draws one scene from the published pair JSON with the AA and Simulated CG meshes and their
markers, two checkboxes as that scene's legend, the 3-column SASA table (Model/Mean/SD, no frames or duration) beside
it in the full-width card, and the bead-overlap figure capped at 640x300. Legend text is 12 px and every Plotly host is
observed so the monitor toggle resizes it. The test construction for surfaces/overlap/mapping moved into
`tests/harness/validation_fixtures.py`. Checks: fast 2523 passed / 1 xfailed; browser 331 passed; ruff clean.
Static JS/CSS only, so the dashboard was not restarted.

The New run Stage settings cells were tightened after that: `new-run.css` gives each label a two-row grid whose first
row is the caption plus its info button (the button moved up from a line of its own), sets `margin:0` on the cell (the
global `label` 12 px margin was the height), and cuts the grid gap to 4 px. A cell with a caption and a Default button
went from 79 px to 58 px; the info button sits on the caption's line at its right, and the geometry is pinned in
`test_aa_new_run_browser.py`'s help-button test. CSS and a test only; no restart.

**The next queue (2026-11-09, for the next session)** is four items; the plan with the proposed copy, files and
acceptance is `docs/plans/2026-11-09-next-round-runs-filters-pdc-analyses.md` (local, as plans are). **Runs**: dense is
the only view (remove Table/Grouped, its storage key and CSS), and checkbox filters for run type and status (plus
possibly molecule/method/date) feed a multi-value `/api/jobs`; the run-type vocabulary and labels come from the
registered types, not a hardcoded engine list. **Bond Interactions**: replace the Torsion refinement hint with a plain
"why / how / what a run needs" explainer — torsions set chain flexibility, the circular-harmonic fit takes phase and
stiffness from the mapped AA dihedral distribution (scaled 0.1–3), stage 3's `refine_bonded` rewrites the fitted ITP
and keeps `*_ff_inter.itp`, and the choice travels as the mapping's parameterization revision that a later run consumes
and records. **Shape and volume**: state what AA reference, Mapped raw, Mapped ring-scaled and Simulated CG are, and
mark Simulated CG as the only one that is this run's data; the others are the AA reference or mapped from it. **pdc Run
view analyses**: a pdc "Structure and interactions" section backed by kinds — `pdc-structure` (RDF, micelle
eccentricity/asphericity, aggregation and contacts from the final production leg), `pdc-interaction-energy` (GROMACS
rerun with energy groups over a sampled window), and an optional `pdc-sdf`; the science definitions are listed in the
plan and must be answered before a producer is written. UI changes need an HTML draft before code.

The dashboard was restarted on 2026-11-05 at 17:12 for the whole round. Live checks: LMNG's automatic candidate is
23 connected beads with the branch bead `[11,22,46]` (connectivity and spectral agree on the bead count, differ on
the grouping); run `619ab118abd6`'s rebuilt AA series carries 160 CONECT records over 201 models and the viewer draws
160 bonds; the import dialog created and validated `molecules/ZZIMPORTCHECK` from fixture text, which was removed
after the check; this host reports three GPUs, so the no-GPU path is pinned by tests only (`gpu-device.js` stubs).

**The 2026-11-09 Runs-filter slice is built and committed** (`119d5c0`). The panel is one dense table: the
Table/Grouped/Dense control, `runsView` and both alternate layouts are gone. A **Filters** disclosure above the
table holds checkbox groups for run type, status and method — OR inside a group, AND between them, nothing ticked
meaning no narrowing from that group — applied on change, with page 1 and a cleared `ETag`, and saved under
`runsFilters` so a reload keeps it (and opens the panel). `GET /api/run-filters` publishes the vocabulary: the
registered run types labelled by `protocol.RUN_TYPE_LABELS` overlaid by each feature's `run_type_labels` (pdc and
validation label their own), and the methods runs actually record. `/api/jobs` takes each of `run_type`, `status`
and `method` repeated and builds `IN` clauses; a single value answers exactly as before, so the Run view's one-type
read and the panel-wide `?limit=100` reads are unchanged, and an unknown run type in a list is still a 400 naming
the vocabulary. The method label map moved from `runs.js` to `routes/runs.py`'s `METHOD_LABELS`, so a card's Method
column and the box that narrows to it share one spelling. A narrowed table that matches nothing says "No runs match
these filters" with Clear all filters, never the "No runs yet" sentence. Checks: fast 2531 passed / 1 xfailed;
browser 333 passed; slow 25 passed; ruff clean. One full browser run had
`test_dashboard_browser.py::test_the_selectors_sit_above_the_diagram_side_by_side` fail (a Bead Assignment layout
measurement that touches no Runs file); it passed alone and in the next full run, so it is the tier's known load
flake. **The dashboard was not restarted**: `92971317fbe2` (`AA NPT production`, ETA 17:44) is live under the
dashboard unit and stopping it would kill its mdrun. Until the next restart the new template/JS/CSS are served but
the new route and repeated parameters are not, so the Filters block reports its vocabulary unavailable.

The queue's other three items now have their gates written, not built. The torsion explainer draft
(`docs/design/drafts/2026-11-09-torsion-refinement-explainer.html`) and the Shape-and-volume model-labels draft
(`docs/design/drafts/2026-11-09-shape-volume-models.html`) both correct the plan's copy against the code: the AA run
id sits in Geometry's identity line, not Shape's (`run-view-mapping.js`); Mapped raw is the unweighted atom mean and
a virtual site the mean of its parents (`models/sugars/coords.py`); ring dilation is illustrative and the
ring-scaled row exists only when the mapping declares rings (`analysis/runs/surfaces.py`); phase and k are recorded
only under circular-harmonic, `refine_bonded` runs from `fit_topology.sh` after `ff_inter` and keeps the
pre-refinement `*_ff_inter.itp`, and a mapping's saved options are what a run records. The pdc lane produced its
science question list and report schemas (`docs/plans/2026-11-09-pdc-analyses-definitions.md`, Q1–Q24 with a JSON
schema per kind) and a section mock (`docs/design/drafts/2026-11-09-pdc-structure-interactions.html`); no producer
is written until the user answers it, and its §12 corrects three plan assumptions — `09_final_assessment` writes only
`assessment.json`, so production is `08_extension/prod/whole.xtc`, a skipped final leg also skips the extension
(leaving `06_assessment/prod/whole.xtc`), and the energy rerun needs `grompp` plus a `trjconv`-extracted sample.
The user then named four GROMACS tools for that analysis. All four exist in GROMACS 2026.3 and were tested on a real pdc
run (`d17de0a443f3`, 80 DDM): `gyrate`, `rdf` and `mindist` work on the CG system and replace the custom Rg/RDF/contact
pass (Rg is mass-weighted; the tensor eigenvalues stay producer-side), `spatial` writes the SDF as a Gaussian98
`grid.cube` (a volume file, not a Plotly figure — Q25), and `hbond` **refuses** it: "0 acceptors and 0 donors", because a
Martini topology has no hydrogens and a pdc run has no atomistic trajectory. So the design reports bead contacts and
never hydrogen bonds. The tested commands, their observed output and the one-extracted-sample rule are §1.1 of the
definitions document.

**The torsion refinement's eight-line defect is fixed** (`16709b7`). `bonded.refine` now groups a dihedral's lines
per `[ dihedrals ]` block, writes the one harmonic term from the first line and drops the siblings, so a
circular-harmonic fit lands the fitted stiffness once and `bonded_fit.json` counts one torsion. Pinned by
`test_a_fitted_torsion_is_rewritten_once_not_once_per_harmonic`,
`test_legacy_keeps_every_fitted_harmonic_line` and `test_two_molecule_blocks_keep_their_own_torsions`; verified on
the real DDM fit (one `1 2 5 6 2 -93.202814 6.6283454`, k 6.628, not eight times that). No run consumed the buggy
path: no run tree holds a `bonded_fit.json`, and the one stored circular fit (`10c318949…` revision 1) recorded the
choice while its refinement actually ran legacy, so it never wrote `funct 2`. `funct 2` is the calibrated spelling
(DDM_CALIBRATION's documented baseline), not a defect. Two things the fix exposed remain open: `dihedral-fit` skips
`funct 2`, so it has no circular-harmonic reading (the panel's caveat now says so), and a fit queued with an unsaved
circular choice records that choice in the revision while its refinement reads the mapping's saved pair (evidence:
that revision's report carries `options: {}` and zero torsions). A Bartender fit is still never refined although
the panel offers the choice.

**The round's other three items are built.** `17fe2c4` replaces the Bond Interactions fieldset's one sentence with
the approved explainer — visible "What it is for" and caveat, one closed disclosure holding "How it works" and
"What a run needs", the corrected facts, and no eight-term claim. `99770d6` puts the four Shape models (AA, Mapped
raw, Mapped ring-scaled, Simulated CG) above the scene, marks the simulated row with a text "this run", adds the
AA-derived-context sentence and prints the AA source run id in the section's identity line; presentation only.
`b55b9e2` adds the pdc feature's first analysis kind, `pdc-structure`: the run's own leg through the pdc segmenter,
one bounded sample (`gmx trjconv`, ≤200 frames, then `-pbc cluster` on the detergent), `gmx gyrate`/`gmx rdf`/
`gmx mindist` on it, the run's own micelle criterion, a report carrying method/sampling/caveats and
`scientifically_validated: false`, a read route and the Run view section (empty, published, no protein, fallback).
Clustering is part of the measurement: on `d17de0a443f3` the unclustered sample's Rg was 6.48 nm against 1.96 nm
clustered. One timed live producer run on that run: 34.5 s, 200 of 50,001 frames (stride 251), Rg 1.965 nm, largest
cluster 79.97 of 80, head–head first peak 0.45 nm, tail–tail 0.50 nm, contacts "not defined" (no protein), and the
fallback reason read from the manifest. Checks after the round: fast 2547 passed / 1 xfailed, browser 338, slow 25, pdc unit
657, pdc browser 3, ruff clean. The dashboard was not restarted (the production run above still holds the unit); the
new route and kind need one. The defaults the producer chose are answerable against
`docs/plans/2026-11-09-pdc-analyses-definitions.md`'s questions without touching the UI: RDF pairs
protein→head/head–head/tail–tail with `-norm rdf`, 0.05 nm bins, `r_max` = min(2 nm, half the box); the contact
cutoff is the run's own micelle contact distance; the shape numbers are the detergent-only tensor eigenvalues; the
whole leg is sampled and summarised in five blocks.

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
  the task list, the assessment's distance diagnostics, the feature-registered sections (Geometry, Bonded terms,
  Shape and volume) read from the published mapping comparison, and the one comparison map above those sections. The
  Runs card draws no figures and offers no analysis
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
| Align trajectory's initial state | the form prefills defaults, so a stored series built with `fit: rot+trans` opens with the box unchecked while its summary line says the fit | decide whether Frame options should prefill the stored build's arguments instead of the defaults |
| Analysis checklist membership | the checklist lists the run's attempted kinds; a kind never queued (e.g. an automatic kind that has not run) is absent | add a server-side "what this run can compute" list and show those unticked, if wanted |
| Runs filters | built 2026-11-09 (`119d5c0`): dense only, checkbox run type/status/method, multi-value `/api/jobs`, `GET /api/run-filters` | the molecule and created-after facets were not added; its own slice if wanted |
| Torsion refinement on a `funct 9` dihedral | fixed 2026-11-09 (`16709b7`): one harmonic term per dihedral, siblings dropped, pinned by three unit tests; `funct 2` is the calibrated spelling; no consumed data was affected | none — keep the grouping when the refiner changes, and decide whether a Bartender fit should be refinable at all |
| A fit's unsaved torsion choice | the revision records what the job started with, but `refine_bonded` reads the mapping's saved `model.json`; measured on `10c318949…` revision 1 (circular in `options`, `{}` in the report) | decide: pass the job's options to the refiner, or record the mapping's options |
| `dihedral-fit` has no circular reading | it skips `funct 2`, which is the circular model's spelling, so it checks a legacy fit only; the panel caveat now says so | add a harmonic branch, or keep it as the legacy-only check |
| pdc `pdc-structure` defaults | built with the document's recommended defaults (RDF pairs, 0.05 nm bins, `r_max` = min(2 nm, half the box), the run's own contact cutoff, detergent-only shape tensor) | change any of them; each is stated in the report's method |
| pdc contacts on a protein run | `gmx mindist -on` contacts are produced only when the run records a protein; no completed protein pdc run exists to verify it on | verify on the first completed protein pdc run, then its report is comparable with the micelle-only one |
| pdc energy and SDF | not built: `pdc-interaction-energy` waits on Q10–Q12/Q14/Q15, `pdc-sdf` on Q18–Q25 | answer the questions, then build in the document's order (`pdc-structure` first, already done) |
| New routes need a restart | `119d5c0` added `/api/run-filters` and repeated `/api/jobs` values; `16709b7`/`b55b9e2` added the refinement fix and the pdc kind. The dashboard was not restarted because `92971317fbe2` was in production | restart after that run finishes, then check the Runs filters and the Structure section live |
| pdc CG analysis definitions | `pdc-structure` (RDF, micelle eccentricity, aggregation/contacts), `pdc-interaction-energy` (GROMACS rerun with energy groups) and optional `pdc-sdf` need science definitions | settle the energy pairs/terms/sampling, RDF selections and normalization, eccentricity definition and SDF grid, then build `pdc-structure` first |
| NGL is eager on every panel | one blocking 1,284,224 B script on every page, 68% of the shell's script bytes; Runs, New run and Bonded build no scene | make it lazy like Plotly (`vendor/ngl-loader.js`) and load it for Run view/Complexes/Bead editor; `window.NGL` has readers in three distributions, so this is its own measured slice |
| Plotly warm and the default figure | a panel that plots asks for its own bundle at mount, so a shown-panel warm cannot help it (Bonded first content 4275 ms); a cold Run view also pulls a 10,300.8 KB interactive figure | decide plan open decisions 2 and whether the first figure waits for a click or visibility; do not prefetch hidden panels |
| CG-only molecules beyond pdc | a `kind: cg` folder works as a pdc detergent without a mapping; compositions, osmotic and CG conformation libraries still assume a mapping | separate slice if wanted (`docs/plans/2026-11-05-feature-round.md`, *Not in this round*) |
| `pdc_preview.py` wording | prepare/build describe a no-mapping CG molecule correctly; the preview still says "one centre per molecule" for any no-mapping build | align the preview's sentence with `_limitations` |
| run-layout migration | applied 2026-10-27 (`legacy_layout.json` on every then-existing run); `936b74bd3fa8`, `00b9ae6db23f` deleted by the user | verify the migrated runs still render and resolve analyses |
| analysis progress visibility | queued and watched only in Run view now: the Runs card's Analysis graphs panel is gone | decide whether the Runs card needs a one-line "analysis running" pointer |
| Overall Run view progress | the card bar is the current stage's fraction; timeline/plan skips show settings | decide whether a true run-level percentage is wanted |
| `aa_only` overview energy | the overview stages the selected leg's own `.edr`; an AA-only reference's energy is in `06_production/run.edr`, a different stage | extend the lookup for an `aa_only` run if wanted |
| cloud vs rough belt | open measurement, not a task | one protein, one seed, two 100 ns legs; compare removal fraction/aggregation/belt thickness before adopting a belt criterion |
| mutation signal | 9 caught, 1 survived (control), 1 stale: `cg-timestep-on-the-wrong-half` anchors on `if folder == aa_dir:`, which the audit refactor removed (`bfd2f82`) | retarget that mutant to the current `cg.mdp_values` line |
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

- **2026-11-09 pdc Structure**: the pdc feature's first kind, `pdc-structure` — one bounded, clustered sample
  of the run's own leg read by `gmx gyrate`/`rdf`/`mindist`, the run's own micelle criterion, the schema
  report, the read route and the Run view section. Commit `b55b9e2`.

- **2026-11-09 Shape model labels**: the four SASA models named above the scene, a text "this run" marker,
  the AA-derived-context sentence and the AA source id. Commit `99770d6`.

- **2026-11-09 Torsion explainer**: the Bond Interactions fieldset's dense sentence replaced by the approved
  Why / How / What / Caveat copy, with the corrected facts. Commit `17fe2c4`.

- **2026-11-09 Torsion refinement fix**: one harmonic term per fitted torsion, its sibling `funct 9` lines
  dropped, and three unit tests. Commit `16709b7`.

- **2026-11-09 Runs filters**: the panel is one dense table with a checkbox **Filters** block (run type, status,
  method); `GET /api/run-filters` is the vocabulary; `/api/jobs` takes repeated values; the method labels live
  once in the route. Commit `119d5c0`.

- **2026-11-06 Run-view Analysis card fixes**: the six items on `67bc79a995d6`. **Topology readers**:
  `itp.active_lines` evaluates `#ifdef`/`#ifndef`/`#else`/`#endif`, and the cross-check reads the live branch
  (`cg.prepare` clears `FLEXIBLE`); `dihedral_fit` skips the periodic impropers (`funct 2`/`4`) instead of refusing
  them as short propers. **Fit temperature**: `kinds.TABLE['bonded-cross-check'].sources` stages
  `3_initial_CG/parameterization_used.json`, and the report uses its `temperature_k` (300.0 K here) rather than the
  303.15 default. **Overview energy**: `trajectory_overview._energy_beside` looks beside the trajectory and then one
  stage directory up (explicit `md.edr`/`run.edr`, never a glob), so the extracted `prod/lig_CG.xtc` reads
  `4_CG_sim/md.edr`. **Analysis card**: a disabled first `trajectory overview` figure tab until the figure publishes
  (three-per-row tabs, two rows for five figures); one task row per kind, the latest attempt, with the last line of
  that attempt's `console.log` as the error and one `Log` link only on the failed row; card margin 0, padding 8 px,
  monitor gap 8 px; the second monitor collapses to its header, lets the first monitor take the full width, and
  remembers the choice in `run-view.state`. A pairing-toolbar control (`Hide`/`Show second monitor`) stays in view
  because the collapsed header moves below the tall first monitor; a `ResizeObserver` on each viewer host remeasures
  NGL and asks it to render again, so restoring needs no page reload (measured: the first monitor's canvas 750 px
  before, 1534 px after minimizing; the second monitor's host 750 × 696 px after expanding). **Frame options**:
  `trajectory_header` and `/trajectory` now state `first_ns` and `dt_ps`; the form computes the producer's own
  low/high/stride and shows `About N models`, disabling a build over the 240 cap. The run's failed request was
  `150–200 @ 0.1 ns` = 501 models; the form now refuses it before queueing (`50–150 @ 1 ns` = 101 and enabled).
  **Distance diagnostics**: the guidance box keeps the pair counts and category means, adds the within-ring and
  between-ring/tail expanded-ring means (live LMNG 0.010 against 0.098 nm, where the physical aggregate is 0.089),
  adds a `Group` column to the pair table, and moves the long legend behind a closed `How to read this`.
  Live: cross-check 22 terms (8 bonds, 14 constraints), 0 unmeasured, 4 disagreements, 300.0 K, 2.7 s; dihedral-fit
  1 proper dihedral (8 harmonics), 0 disagreements, 2.41 s; overview Temperature 303.1535 K, Pressure 0.9865 bar,
  Potential −14,634.92 kJ/mol from `4_CG_sim/md.edr`, 4.33 s. Checks: full fast, browser and slow tiers green; ruff
  clean. Plan `docs/plans/2026-11-06-run-view-analysis-fixes.md`; drafts and after screenshots in
  `docs/design/drafts/2026-11-06-run-view-*`, `2026-11-06-analysis-after.png`, `2026-11-06-overview-after.png`,
  `2026-11-06-runview-minimized-after.png`, `2026-11-06-runview-minimized-toolbar.png`,
  `2026-11-06-frame-options-budget.png`, `2026-11-06-frame-options-over-cap.png`,
  `2026-11-06-distance-guidance-compact.png` and `2026-11-06-distance-guidance-open.png`.

- **2026-11-06 Whole-trajectory rebuild (pdc Run view)**: a pdc run's derived `whole.xtc` can be rebuilt in place
  from its immutable `run.xtc` with a chosen frame step and precision. Code: producer `detergent_pdc/execution/
  rebuild_whole.py`, routes `GET|POST /api/pdc/<job_id>/whole-trajectory`, the card in the pdc Run view extension
  (engine slot `nodes.extension`), tests and docs. Compact default (100 ps, 0.01 nm): live `6c36b3c610f3` went
  **1.60 GB -> 0.24 GB**, overview aggregate unchanged at **92**, Rg 2.1333 -> 2.1387 nm, RMSD 2.5874 -> 2.5916 nm.
  Three defects caught live and pinned: gmx trjconv needs an `.xtc` suffix on its output (a `.tmp` name writes
  nothing); the header reader needs the sibling `run.gro`, not `prod/run.gro` joined twice; and the size estimate's
  cadence ratio was inverted (100 ps predicted larger than a 20 ps source). The card's controls also needed scoping
  against the app's form styles (labels wrapped, the link rendered as a button). Plan:
  `docs/plans/2026-11-05-rebuild-whole-trajectory.md`; draft `docs/design/drafts/2026-11-05-whole-trajectory-panel.html`.
  Checks: the three new pdc test files (15 passed), full fast tier and browser tier, ruff clean.

- **2026-11-05 Nine-point feature round (items 1-6, 8, 9)**: a host with no GPU now offers no device setting, no
  `-gpu_id`/offload flag and no device control (`devices.present`, `config/dashboard.json`'s `gpus`), commits
  `80c1157`; clicking a bead's atoms field no longer loses the selection, and Group into bead plus 3D picking are
  gone with a selection halo in their place (`13382b1`); the automatic mapping is branch-safe (LMNG `[11,22,46]`,
  23 beads, max span 3.84 A) and a second algorithm ports cg_param_m3's mapping half behind a per-mapping select and
  a `graph.validate` gate (`d8ca4b4`); Frame options has the restored **Align trajectory** control and an all-atom
  series now carries one CONECT block, with `layout.aa_topology` and a followed `#include` finding the moleculetype
  (`25674f2`); local AA and CG-only molecules import through `/api/molecules/import`, and pdc uses a CG-only
  molecule as a detergent without a mapping (`99bbd03`). Focus doc `docs/plans/2026-11-05-feature-round.md`.
  Checks: fast 2437 passed + 1 xfailed, browser 287 passed, slow 25 passed, ruff clean; live checks in *Next task*.
  Follow-up (17:35): an all-atom file now states its atoms' own elements in the PDB element column instead of the
  bead stand-in `C`, so the Run view colours LMNG by chemistry (C grey, O red, H white); `619ab118abd6`'s rebuilt
  series holds 17,688 H / 9,447 C / 4,422 O and the live viewer draws red oxygen.
  Follow-up (17:55): each Runs card now states its trajectory weight (`layout.trajectory_bytes`, 30 s cache) so a
  deletion decision sees the bytes; the live list reads 0.45 GB, 3.9-4.2 GB and 0.07 GB across the current runs, and
  the walk costs 28 ms for all 15 runs.
  Follow-up (18:00): the run card's View run link moved from the title cell into the doors row beside Artifacts,
  the stage records and the console (`docs/design/drafts/2026-11-05-runs-card-doors.png`).
  Follow-up (18:02): the table's Run/progress column widened 39% -> 43%, Status 11% -> 9% and Method 8% -> 6%
  (8% wrapped the `completed` badge onto two lines).
  Corrections found while building: there was no 3D bead highlight to preserve (one was added), and the CONECT
  layout was measured on the vendored NGL (a single block after the models binds every frame) rather than assumed.

- **2026-11-05 Audit remainder: decisions 1-3 and 5-9**: the pdc preview box now passes the build's
  `belt_reach_nm`; the run card and the prepare record read one `pdc.skipped_stages`; the MDP parity oracles
  (`aa.mdp`, `cg.mdp_integration`, `environment.update_mdp`) are gone and `test_mdp_writer` pins literal AA maps
  and literal template patches; the review workflow (route + `record_review`/`list_reviews`/`generate_variants`),
  `ring_site_preview` and the model-registry writers are retired, their tests replaced or removed; the
  `/api/mappings/validation-targets` route is gone (the representations test remains); `worker.known` folded into
  `kinds.known`, its callers updated; `catalog.list_models` no longer takes the ignored `view` parameter.
  Checks: fast 2385 passed + 1 xfailed, browser 282 passed, slow 25 passed.

- **2026-11-05 Audit group E, the safe rotation merge**: `pdc_build`'s private `_rotation` is gone; the build stamps
  through `pdc_placement.alignment` (now public), the one copy of the map the placement gate also uses. The other E
  items are not landed: merging the preview's box rule changes preview behaviour, the `planned_skips`/adapter merge
  changes UI wording, and rewriting the MDP parity oracles into literal expected maps is a test-authoring change
  rather than a deletion. Checks: fast 2392 passed + 1 xfailed, browser 282 passed, slow 25 passed.

- **2026-11-05 Audit group B, the safe endpoint trim**: `/api/migration/inventory`,
  `/api/migration/delete-obsolete`, the duplicate `GET /api/compositions` and
  `GET /api/compositions/<id>` reads, and `/api/temporary/cleanup` are gone; the write routes and
  `/api/cg-models` reads remain. `test_request_bodies.py` now pins the optional-body contract on
  `/api/jobs/<id>/resume` instead of the migration routes. `/api/mappings/review` and
  `/api/evidence/evaluate` were deliberately kept. Checks: fast 2392 passed + 1 xfailed, browser 282 passed.

- **2026-11-05 Audit remainder, batches D/A/C**: tooling hygiene (the deprecated singleton patch leaves
  `tests/harness/plugin.py`; the three package `test` extras and the root one go, with `pytest>=8` now pinned in
  `requirements-dashboard-tests.txt`; stale ruff excludes, `support.py`'s `__all__`/re-export, the unread
  `bartender_source` key and the duplicate `pdc` marker are gone). Dead API removed: the metadata legacy describer
  and evidence forwarder, `series_of`/`conditions_of`, `divide`, `plan_and_build`, `PAPER_MOLALITIES` and the
  route's registry alias, the `_adapter_defaults` shape branch, the GPU bracket constants, `Coordinator.public_job`,
  `run_inputs.run_output`, `worker.source_paths`, `aa.verify_prepared`, `owned_by`, `parse_composite_*`,
  `LEGACY_IDENTITY_VERSION`, and `stage_environment`'s test-only `extras`. The pdc stage scripts digest through
  `dashboard.files.sha256`. Browser: `modules.js` and `run-view.js` use the shared `api`/`post`/`notice`/`storage`,
  and `setBeadRadiusScale`, `downloadBlob`, `beadFamilyCode`, `isStructurePath` and `saveForm` are gone. Kept:
  `automatic_candidate`/`new_draft` (a 40-call fixture migration, not a mechanical delete), the duplicated
  `kinds.known`/`worker.known` accessor, and `catalog.list_models(view=)`. Checks: fast 2392 passed + 1 xfailed,
  browser 282 passed, slow 25 passed, ruff clean.

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
