# Handoff: current state, open items, recent slices

State and open items for this repository. Rules live in `AGENTS.md`; subsystem behaviour and procedures live in
`docs/PROJECT_GUIDE.md`; scoring science in `docs/DDM_CALIBRATION.md`. Read this before touching the DDM CG chain,
the protein-detergent pipeline or the coordinator. This file keeps only what is current and the evidence behind it.

## Next session

**2026-11-13 MkVsites derivation lands as a read-only per-molecule report (phase 1).** MkVsites
(github.com/ErikMarklund/mkvsites, commit 3878974, MIT; Larsson, Kneisz & Marklund, *J. Comput. Chem.* 41:1564-
1569, 2020) derives missing vsite parameters from an ITP/RTP plus force-field data. Its own scope is terminal
groups (one heavy neighbour, the rest hydrogen) and OH angle constraints; it does not rewrite a topology. On this
repo's DDM it finds nothing against CHARMM36 (SwissParam's CR/OR/HCMM/HOR types are aliens), but with the ITP's
own atom types and exact inline bond/angle rows it derives `MCH3_1` (one dummy type) and seven OH constraints --
matching the upstream tool run over a minimal ITP-derived force-field overlay. Their `topinspect.py` ITP->RTP
helper crashes on the DDM ITP, so a converter is ours.

Phase 1 is `models/molecules/vsites.py` (adapted port, no vendored tree), the `derive_vsites` CLI, the
`POST /api/molecules/<id>/virtual-sites` route, and a **Derive virtual sites** action in the folded New run
molecule block. It reports dummy types/masses, constraints, OH angle constraints, `.vsd` lines and diagnostics;
it queues no run and changes no setting. Checks: fast **2794 passed / 1 xfailed**, browser **382 passed** at
`-n 8` (two known load flakes appeared at `-n 16`; each passed solo), slow **24 passed**, ruff clean. Live DDM:
the route returns `MCH3_1` (count 1) and one `CR HOR` constraint (count 7) with no diagnostics; the New run
button shows `1 vsite type · 1 OH angle constraint`. Phase 2 (not built) is the AA run setting that builds an
RTP + force-field overlay + `.vsd` and runs `pdb2gmx -vsite`, recording the generated topology and comparing it
with all-atom.

**2026-11-13 CG runs get stage editors, both seeds get Generate, the overview gains stage traces, and pdc gains protein
virtual sites.** The New run form now has three CG stage editors beside the AA ones: CG minimisation (step cap,
`nstlist`, Verlet tolerance), CG equilibration and CG production (duration, timestep, `nstlist`, Verlet tolerance,
thermostat/barostat coupling, compressibility). Production keeps its cadence and cutoff overrides under *Other run
options*. Defaults are read from the reviewed `PROFILES` (`cg._reviewed_stage_defaults`), so an untouched run renders
the CG MDPs byte for byte; the keys are advertised by `cg`, `composition` and the sugar `sugar_cg` adapter, so all
three CG kinds show the editors. The AA and CG random seeds now have **Generate**, drawing an integer in
`1..YYYYMMDD` (today local), replacing Default.
The overview gains a third row: Potential vs step for minimisation, Temperature for NVT and Pressure for NPT, each
read from the leg's own EDR and recorded under `stages`; the production panels and record are unchanged.
`pdb2gmx` cannot build the AA reference for this project's ligands -- the stored DDM PDB is residue `LIG`, and
`gmx pdb2gmx -vsite {none,hydrogens,aromatics}` fails with `Residue 'LIG' not found in residue topology database` --
so the virtual-site choice lives in the pdc back-map, the only stage that invokes pdb2gmx (inside CG2AT2). The choice
is `protein_vsite` (`none`/`hydrogens`/`aromatics`), recorded in the pdc settings; `pdc_backmap.sh` writes a
repo-owned `gmx` wrapper that appends `-vsite <choice>` to `pdb2gmx` calls and passes it to CG2AT2 with `-gmx`.
Checks: fast **2769 passed / 1 xfailed**, browser **381 passed**, slow **24 passed**, ruff clean. Live: Sucrose
published-reference CG run `d1dc16dfe369` completed in **19.3 s** with equilibration at 2 fs (10 ps, 5 000 steps,
nstlist 30) and production at 10 fs (10 ps, 1 000 steps, nstlist 30); the minimisation wrote its 1 000-step cap.
Its overview `04171a0091c5` read all three stage traces -- minimisation Potential (242 step samples), equilibration
Temperature and Pressure (51 samples each, both from `eq.edr`) -- and the production energy from `md.edr` (43
terms). The live form exposes the three CG editors and both Generate buttons; the pdc form exposes
`protein_vsite`. A pre-existing race was hit while queuing an automatic analysis immediately after a run finished:
the analysis thread failed with `A worker still holds this run` and stayed queued until a dashboard restart. That
is not caused by this change and was not fixed here.

**2026-11-13 the trajectory overview records the full statistics, shape, RMSF and every EDR term.** The first batch
of the richer overview landed. `analysis/runs/statistics.py` gains `series_summary` (20 keys: n, mean, sample std,
naive SEM, block-averaged SEM, median, p05/p95, min/max, half means, OLS slope per ns + stderr + R² + RMS from fit,
integrated autocorrelation time and effective samples); `block_summary` is unchanged. The overview now summarises
`rmsd_nm`, `gyration_nm` and the aggregate largest/count/free series with it (keeping the legacy `mean`/`se`/
`second_half_mean`/`*_mean` keys; `se` is the block SEM), and adds `shape` (Rg-tensor eigenvalues, asphericity,
acylindricity, relative shape anisotropy), `rmsf_nm` (per-atom after the same Kabsch fit; per-atom list only at
≤512 atoms), and `end_to_end_nm` (max pairwise distance per frame at ≤512 atoms, otherwise null plus
`end_to_end_absent`). Energy now discovers the **whole** `gmx energy` menu on stderr, selects every 1-based index,
and summarises all terms (45 on a live AA production EDR); only Temperature/Pressure/Potential keep `time_ps`/`values`
(≤600 points), so the JSON stays bounded. `energy.components` (Angle, Proper-Dih., LJ-14, Coulomb-14, LJ-(SR),
Coulomb-(SR), Coul.-recip., Potential, plus Bond/Improper when written), `energy.pressure_tensor` (Pres-*/Vir-*/surface
tension), `energy.drift` (slopes of Total-Energy/Potential/Kinetic-En., `|total|/|potential|`, an `nve` flag and a
basis sentence) and `energy.interactions` (terms containing ':') are added. Component/drift names match through a
hyphen→space fold because XVG legends normalise `Total-Energy` → `Total Energy`, `LJ-(SR)` → `LJ (SR)` etc.; the
menu's dashed rule sits before the rows and selection is 1-based. The XVG parser streams line by line into
`array('d')` columns: on a 200k-row EDR this cut peak RSS from ~665 MB to ~263 MB at ~13 s (from ~15 s), against a
116 MB XVG. `series_summary` uses the sampled ≤200-frame series for geometry and every EDR row for energy; the drift
ratio is only conservation evidence when the leg has neither thermostat nor barostat, which the flag and basis say.

**Energy groups were tried and reverted.** Adding `energygrps = non-Water Water` to the three AA dynamics profiles
rendered, and `grompp` accepted it, but `mdrun` refuses energy groups with GPU nonbonded (`Multiple energy groups is
not implemented for GPUs`), and these runs use `-nb gpu`; the live probe run `e37d1ee4523f` failed at NVT. The
profiles change was reverted; the reader's `energy.interactions` remains ready for a CPU-only run or an `mdrun -rerun`
with an energy-group tpr. The failed diagnostic run is still on disk (delete it from Runs if it is noise).

Checks: fast **2738 passed / 1 xfailed**, browser **376 passed**, slow **24 passed**, ruff clean. Live run
`5d7dae545905` (DDM draft-smoke, box 4.0 nm) completed all seven stages in ~50 s; its overview `a7a520f4b394`
completed in **6 s** and its record has 45 energy terms, 8 components, 18 pressure-tensor terms, drift
`total=-21631.71`, `potential=-15532.49`, ratio **1.39**, `nve=False` (V-rescale/Parrinello-Rahman recorded), 81-atom
RMSF (mean 0.121 nm, max 0.274), Rg eigenvalues 0.370/0.060/0.016 nm, asphericity 0.332 and end-to-end 2.03 nm mean.
`energy.interactions` is empty because this build's MDPs set no energy groups. Dashboard restarted. Left deliberately:
the all-term XVG is ~116 MB on a long leg (peak ~263 MB, ~13 s, on-demand only); geometry is over the sampled series,
not every frame; the pair quantities are capped at 512 atoms; the per-atom RMSF list is dropped above that cap.

**2026-11-12 the AA stage editors carry the coupling, one HMR factor, and no timestep ceiling.** The timestep cap is
gone (`SETTING_SPECS` now takes `high=None`; `execution/settings.py`'s normalizer names only the floor, 0.5 fs), because
a topology with larger hydrogen masses may step further and GROMACS' stability is the real limit. Each dynamics stage
now states its thermostat (`aa_<stage>_tcoupl`, V-rescale/Nose-Hoover/Berendsen/no) and `tau-t`; NPT equilibration and
production also state `pcoupl` (C-rescale/Parrinello-Rahman/Berendsen/no), `pcoupltype`
(isotropic/semiisotropic/anisotropic), `tau-p` and `compressibility`, while NVT has no barostat because it fixes the
box. A non-isotropic kind repeats the form's one compressibility and one `ref-p` for each direction it requires (the
MDP writer now formats a tuple space-separated), so every choice is executable; `surface-tension` is deliberately not
offered (slab physics, not a solvated molecule). **Hydrogen mass repartitioning** is one optional run setting,
`mass_repartition_factor` (blank = off), written as `mass-repartition-factor` into the three dynamics MDPs only; it has
no default key, so a blank field writes no line and a clone/retry does not re-feed a null into the normalizer. Its
GROMACS refusal for a topology whose heavy atom would fall below the light mass is stated in the field's help: with
CHARMM36 here factor 3 passes and factor 4 does not. The Run label's input is exempt from the 9 rem numeric cap. Checks:
fast **2717 passed / 1 xfailed**, browser **376 passed**, slow **24 passed**, ruff clean. Live `e9383ac781f3` (DDM,
draft-smoke, HMR factor 2, box 4.0 nm) completed all seven stages in **49.5 s**: `04_nvt`, `05_npt` and `06_production`
each carry `mass-repartition-factor = 2` plus their reviewed `tcoupl`/`tau-t` and (NPT legs) barostat lines, while the
minimisation writes none. The first attempt (`d7f6b6793d9b`) was refused at input for the unchanged reason that DDM
spans 1.85 nm and does not fit the 2.5 nm default box. Dashboard restarted. Left deliberately: the HMR form bound is
1–10 and the topology check is GROMACS' (a run can still be prepared with a factor grompp then refuses); a non-isotropic
`pcoupltype` repeats equal values rather than offering per-direction vectors; HMR is not written into minimisation.

**2026-11-12 the trajectory overview reads an AA run's energy and loses its detergent wording.** An AA-only run's
reviewable trajectory is `07_reference/lig.xtc`, extracted from `06_production/run.xtc`; its `run.edr` was never
beside it, so the overview's energy panels said "no .edr is staged beside the trajectory or its stage directory".
`sources()` now stages `06_production/run.edr` for an `aa_only` run when no sibling energy exists
(`_reference_leg_energy`), and `_energy` falls back to the one `.edr` in the staged tree because it need not sit beside
the trajectory; the energy still comes from GROMACS' own `gmx energy` columns. The figure's titles are generic now --
**RMSD**, **Radius of gyration**, **Largest aggregate**, and the Temperature/Pressure/Potential mean titles -- because
the same figure is drawn for a protein, a micelle and a small molecule; the kind's one-line Run view description is
generic too. A segment holding at most one non-water
molecule draws **five** panels (no aggregate panel: one molecule cannot aggregate, and the panel was a flat line at 1);
a multi-molecule segment keeps it. The record's `subject` says `molecule` for that case and its note no longer says
"detergent". Checks: fast **2714 passed / 1 xfailed**, browser **375 passed**, slow **24 passed**, ruff clean. Live
`619ab118abd6` (AA, completed) ran its overview in **8.4 s** (07:51:50 → 07:51:58 UTC): `sources.json` names
`stages/06_production/run.edr`, the record's energy has Temperature/Pressure/Potential (`run.edr`, Temperature mean
303.178), and the figure shows RMSD / Radius of gyration / Temperature / Pressure / Potential with no aggregate cell.
The recomputed attempt is under `analyses/trajectory-overview/4da8ef18…`; the Run view shows that figure on its next
load. Dashboard restarted. Left deliberately: the overview still measures one sampled segment and says nothing about
convergence; other legs' EDRs (NVT/NPT) are not plotted; `subject` for a single molecule is the molecule, while a
protein run still reports `protein`.

**2026-11-12 the run card states its throughput; New run and Bond Interactions widths.** The Runs card's identity line
now ends with the run's **highest observed ns/day** (`id · GPU · size · 2124.7 ns/day`): `views.performance_ns_per_day`
scans `<run>/logs/*.log` tails for GROMACS' `Performance:` line (first number), takes the maximum, and remembers each
file's result per `(path, mtime_ns, size)` (cap 4096 entries) because `/api/jobs` polls 100 runs every five seconds; the
view adds `ns_per_day` unconditionally, so the summary shape carries it, and `runs.js` omits the segment when absent. A
run with no stating log shows no number. New run's **Stage settings** column is now 4 of the form's 12 columns and
takes the settings half (8): `layout.css` scopes `4 + 8` with `@media (min-width: 1101px)` to `.new-run-layout:has(.stage-editor)`,
so the pdc workspace's form keeps its 6 + 6 halves; `new-run.css` lays settings four across (`minmax(10rem, 1fr)`) with
controls capped at 9 rem, so an AA stage editor's four fields share one row (measured: inputs 4x144 px, no sideways
scroll at 1600). Bond Interactions: each pane draws the **connectivity plot above the interactions table**; the fit card
and the Result card share the first row (Fit 7 columns, Result 5) while the Job card takes the full-width row below
(`dashboard.css`, `:has` widens Fit back to 12 while Result is hidden); the fit card's fields sit four to a row in
narrow cells; and the **fit temperature follows the chosen AA reference's `settings.temperature_k`** by default (on the
auto-selected single reference, and on every explicit reference change; a value typed before the reference list arrives
survives, and 300 K stands when the reference records none). Tests: unit `test_run_view.py` (max, tail window, none,
summary), browser `test_runs_table_browser.py` (2124.7 ns/day), `test_aa_new_run_browser.py` (four-per-row + widths),
`test_bonded_parameterization_browser.py` (three temperature tests, two layout tests, updated cadence layout claim),
`test_workspace_navigation_browser.py` (new-run spans 4 + 8) and the pdc test that loads this form (now asserts the
settings half is wider, its own form's 6 + 6 unchanged). Checks: fast **2711 passed / 1 xfailed**, browser **375 passed**,
slow **24 passed**, ruff clean. Live: runs `fbb95f11e083 · … · 2124.7 ns/day`; fit 899 px + result 637 px on one row,
job 1552 px below; diagram bottom above table top. Dashboard restarted. Left deliberately: throughput comes only from
top-level `logs/*.log` (not resume attempt subdirectories or a legacy console log outside the run tree); the four-across
grid is cramped between 1101 and ~1150 px (three across; it stacks at 1100); dead `.bonded-model-body`/`.bonded-torsion`
CSS from the merged fit card is still in `dashboard.css`.

**2026-11-12 a minimisation always runs the scheme choices at auto.** The New run form's Other run options
(nonbonded/PME/PME-FFT/update/load-tuning schemes and the checkpoint cadence) now describe the equilibration and
production legs only: `aa.mdrun_command_flags(stage='em')` forces those five choices to auto over a copy of the
settings, keeps the device bracket, and emits no `-cpt`, so the first leg cannot inherit a scheme chosen for dynamics.
`stage='equilibration'` is the same bracket with the run's choices (the CG-style scripts' dynamics), and
`stage='production'` keeps the PME-on-GPU AA-reference bracket. `workflow.py` builds all three from the one builder and
exports `MDRUN_FLAGS_AUTO`, `MDRUN_FLAGS` and `MDRUN_FLAGS_PME`; `cg_simulation.sh`, `sugar_cg_simulation.sh`,
`aa_reference.sh`, `pdc_leg.sh` (by its stage directory) and the pdc extension plan read the auto bracket on their
minimisation lines. The thread, rank and device budget still applies to every stage: it says how the leg executes, not
what physics it runs. Help text and the form's Other run options hint state the rule. Checks: fast **2707 passed / 1
xfailed**, browser **369 passed** (two unrelated load flakes failed on separate runs and passed on rerun; the third
full run was green), slow **24 passed**, ruff clean. Live `a04732bc4b9e` (DDM, draft-smoke, mdrun_nb/pme/update=cpu,
tunepme=off, cpt=1) completed in ~84 s: its minimisation command is `-ntomp 8 -gpu_id 0 -nb gpu -pin on` and its
NVT/NPT/production commands are `-ntomp 8 -nb cpu -pme cpu -gpu_id 0 -pin on -update cpu -notunepme -cpt 1`; the
stage environment carries `MDRUN_FLAGS_AUTO`. Dashboard restarted. Left deliberately: the minimisation bracket still
names the run's device and its nonbonded offload (auto means the profile's bracket, not "no device"); only the
explicit scheme/cadence choices are withheld.

**2026-11-12 Bond Interactions is two comparison panes, and New run stages are editable.** The panel now renders
one Jinja macro twice: pane A keeps every bare id the browser tier addresses, pane B carries the same ids with a
`-B` suffix and a **Minimize** header control remembered in `ddm.bonded.state`; each pane has its own model select,
parameterization select, facts, table, Plotly scene (own `uirevision`) and saves. The old model card merged into one
**Model and fit** card above the panes with its own **Molecule** and **Mapping to fit** selects; the torsion explainer
is an **(i)** beside Torsion stiffness scale. Editing is now the store's `edit_gate`: a fit's own revision is editable
but **Save in place is unavailable until it carries hand edits** (its first edit is Save as new, whose clone then
allows in place); a `martini-reference` transcription is read-only in the table and both modes; a published Martini 3
reference is display-only (no inputs, neither save) and **the seed/transcription path is gone** — a CG run consumes it
directly. `GET /api/bonded-parameterizations` publishes `parameters_editable`, `save_in_place` and
`save_in_place_reason` per revision and on `summary`, and the client renders them rather than re-deriving the rule.
New run's AA stage settings are three minimisable `<details>` editors (NVT open; summary facts like
`100 ps · 2 fs · 50 000 steps · nstlist 20`) with per-stage `aa_<stage>_dt_fs` (2 fs, 0.5–4),
`aa_<stage>_nstlist` (20, 1–10000) and `aa_<stage>_verlet_buffer_tolerance` (-1 off, -1–0.1, **0 refused by name**);
the timestep changes the step count, not the duration. `box_nm` is now the **minimum image distance d** for four
GROMACS cells — cube, rhombic dodecahedron (xy-square, `-bt dodecahedron -box d`), the same in xy-hexagon
(`-bt triclinic -box d d d -angles 60 60 60`) and truncated octahedron (`-bt octahedron -box d`) — with volumes
1.000/0.707/0.707/0.770 d³, so the existing `Rc < d/2` checks still hold. The CG production tolerance bound became
0.001–0.1 because grompp refuses exactly 0. Defaults render the AA MDPs byte-identically; the old dodecahedron size
(clearance) changed, and no live run had recorded a box shape. Checks: fast **2704 passed / 1 xfailed**, browser
**369 passed**, slow **24 passed**, ruff clean. Live, after restart: two panes render and B minimises/expands;
`#bonded-fit-molecule` lists the AA molecules and hides the mapping select when one mapping; a published reference
shows 0 inputs and both saves disabled with its sentence; a fresh bartender revision's Save in place is disabled with
`fitted by bartender; Save as new to edit it`; the stage editors show the facts and hide on a CG run. Timed AA
`draft-smoke` run `717414831e06` (DDM, 1 fs, nstlist 10, hexagon d=4.0) **completed in ~45 s**; its NVT/NPT/production
MDPs read `dt 0.001`, `nsteps 5000/5000/50000`, `nstlist 10`, and its box line is the manual's hexagon
`4 3.46410 3.26599 0 0 2 0 2 1.15470`. The first attempt `d0e1eff3a258` failed at prepare because DDM spans 1.85 nm
and the 2.5 nm default does not fit; the retry used `box_nm 4.0`. Left deliberately: the composition store keeps its
own in-place save (Combinations owns those edits; Bond Interactions shows a composition's derived revision read-only);
CG/pdc timesteps are not exposed (standing decisions); a positive AA tolerance can still make `rlist` exceed the box
and grompp's refusal is shown in the stage console rather than pre-computed. Follow-up `fa102b5` hides the AA "Stages" heading, its blurb and the box-shape note on a CG run (they stayed
visible with no controls under them) and pins that in the AA browser module; browser 369 re-run green after it.
Drafts:
`docs/design/drafts/2026-11-12-{bond-interactions-two-panes,new-run-stage-settings}.html`; plans
`docs/plans/2026-11-12-{bond-interactions-comparison-panes,new-run-stage-settings}.md` (local). Dashboard restarted
on the new code (unit `detergent-dashboard`).

**2026-11-12 a rigid constraint's length is editable.** Committed `c408966`. The interactions table offered no input on a constraint row because a constraint's length is the mapping's AA-derived ring target; it is now a parameter like a bond's. `PARAMETER_RANGES` carries `constraints` (function 1, length 0.01-2 nm), `rewrite_interactions`/`save_terms` accept the edit, and the row renders one input. The mapping's ring target stays the starting value; an edit overrides it in the revision, Source reads `manual` (checked before the ring-pair reading), and `edited_terms` keeps before/after. Save in place / Save as new and the Martini 3 reference rule are unchanged. A virtual site's parents remain a reading, and the composition store keeps constraints read-only because `bonded.refine` refuses to replace a ring constraint; `generation._validate_term` refuses a constraint by name rather than crashing on its arity. Checks: fast 2690 passed / 1 xfailed, browser 360 (one unrelated rescore-load flake, green on rerun), slow 24, ruff clean. **The dashboard needs a restart** for the table and hint changes; the live Glucose-0 work dir still holds its valid BARTENDER `gmx_out.itp`, so its next fit reuses it.

**2026-11-12 BARTENDER's Glucose fit read the wrong path.** Live job `8ede5d9e0fc64915` ran the tool to completion (its log ends `Your Martini, Mr. Bond.`) and then failed with `BARTENDER did not write gmx_out.itp; there is no fit to store`: `_bartender` looked for the file in `3_initial_CG/`, while BARTENDER writes it in its own working directory, the fit's work root (where `1_AA-reference/` and `2_mapping/` live). Committed `c7e56f0`: the job reads `work/gmx_out.itp`, and the unit test's stand-in tool writes it there so the old guard path fails again. The failed job's work dir already holds the valid file (`[ bonds ]` + two ring constraints, merged cleanly from the live topology), so the next **Fit this model** on Glucose-0 reuses it and stores a revision without re-running BARTENDER. The dashboard was restarted on 2026-11-12 10:50 HKT. Remember the fitted revision carries BARTENDER's raw (unscaled) ring constraints.

**2026-11-11 editable bonded terms, a working composition CG run, and the surface HTML gone.** Committed `245bf7e` (the round) and `17f6ba8` (the bond-force cap); the 14:31 constraint-threshold fix is `55d2715`. Run view's Bonded terms rows now highlight the selected term in the comparison map (`rvm-term-select`; the map's one `selectTerm` state, `data-selected-term` test seam), and the surfaces analysis stopped writing `surface-comparison.html`, so `/figures` and `media=1` are image-only, an older attempt shows its own SASA numbers plus **Recalculate surfaces**, and `RunFigureViewer` carries no iframe. CG Bond Interactions edits parameters (bonds/angles/dihedrals; the function form, a constraint's length and a virtual site's parents are readings): **Save in place** rewrites the current revision with `expected_revision`+digest, clears the checks and keeps `edited_terms` before/after (Source reads `manual`); **Save as new** clones the shown revision and makes it current. A Martini 3 reference disables Save in place with the reason, and Save as new seeds a `martini-reference` transcription revision on the molecule's one saved mapping, refusing a differing bead partition. The read-only Revisions strip is gone; the display selector is the history. BARTENDER's Glucose-0 failure was goChem's DCD reader: 12 atoms × 4 bytes equals the 48-byte unit-cell block, so the reader lost phase and panicked at EOF; the fit is handed a multi-PDB of the heavy atoms and fits 2001 frames in 0.077 s. A failing command now streams into the job log and puts the tool's own last line in the record's `error`. Combinations: `render_gro` writes the joined preview geometry (the old 0.1 nm placeholder stack put two beads on one point and minimisation died with `-nan`), and a saved composition's terms are editable in place; revisions live in `workspace/compositions/parameterizations/<id>.json` (revision 0 derived), a CG payload names `composition_revision` (else current, then 0), and the manifest records the revision with the base and staged-topology digests. The composition table's bond-force max is the CG stage's 50000 clamp, so a saved number is the simulated one. Checks: fast 2685 passed / 1 xfailed, browser 360, slow 24, ruff clean. Live verification: a GLC-C12 CG run completed in 15.0 s and an edited revision-1 run in 13.5 s (manifest `composition_revision: 1`, staged ITP carries 3000). Drafts: `docs/design/drafts/2026-11-11-{analysis-highlight-and-surface-removal,bond-interactions-editing,combinations-editing}.html` (local). **The dashboard needs a restart** for the template, JS and Python changes. Left deliberately: the BARTENDER revision carries raw (unscaled) ring constraints -- a science choice, not this round; the composition manifest's `workflow_version` still reads `cg-composition-v1` while `composition.VERSION` is `cg-composition-v2`; and no geometry-migration CLI was added (this workspace holds no saved composition).

**2026-11-11 the Runs panel registers copied runs.** Committed `5765586`. The adopt routes now have their panel: a banner above the run table appears when `GET /api/runs/unregistered` is non-empty, and its dialog lists those directories with checkboxes (AA-only first, so a `cg` run and the source it consumes register in one click) and posts one `POST /api/runs/adopt` per ticked id. Successes and refusals are marked in place, the table and banner refresh, the banner hides when nothing is left, and a 409 is shown with its message. The list is re-read on mount, on a storage refresh and after an adoption -- not on the five-second poll, because a directory appears only when a reader copies one in. Only ids the route listed can be posted. Checks: fast 2624 passed / 1 xfailed, browser 349 (one load flake, green on rerun), slow 23, ruff clean. Draft reviewed: `docs/design/drafts/2026-11-11-runs-adopt-button.html` (local). **The dashboard needs a restart** to serve the new markup and JS. The 14:31 constraint-threshold edit (`models/bonded/parameterization.py`, `test_bonded_fitting.py`) and this file's round paragraphs were still uncommitted at that point; the fix is `55d2715` now.

**2026-11-11 pasted runs are adoptable; AA references travel.** Committed `2a50351`. A run is a directory and a job row, and a directory copied between workspaces had no row, so the Runs list, the Run view and the Bond Interactions reference picker could not see it; and `stages/07_reference/reference.json` recorded its shared sources as absolute paths from the publishing checkout, so `references.verify` failed elsewhere and `/api/references` dropped the run silently. `execution/adoption.py` rebuilds the row from the manifest (and the analyses from their attempt manifests), verifies the copy's inputs, and sets `reference_eligible` only when `references.verify` passes; it is exposed as `python -m dashboard.cli.import_run --adopt --workspace <ws> --run <id> [--apply]`, `POST /api/runs/adopt {"run": "<id>"}`, and `GET /api/runs/unregistered`. Schema-2 reference records name each source by locator (`repo`/`workspace` + relative path, absolute only outside the checkout); a source absent on this host is a `warnings` entry, one present and changed is still refused, and the route returns `unavailable: [{id, reason}]` plus per-reference `warnings` that the Bond Interactions card states. Checks: fast 2624 passed / 1 xfailed, browser 347, slow 23, ruff clean. **The two new routes need a dashboard restart.** The live workspace was not adopted into (no copy was imported); `docs/PROJECT_GUIDE.md` states the run-is-a-row rule and the adopt paths. The user's own 14:31 constraint-threshold edit was left in the tree at that point; it is `55d2715` now.

**2026-11-11 constraint threshold is an integer.** Live fit job `761a2bfe316243f0` failed with
`ff_inter: error: argument -constraints: invalid int value: '10000.0'`: `normalise_options` cast every numeric option to
float, and `ff_inter`'s parser declares `-constraints` an `int`. `parameterizations.DEFAULT_CONSTRAINTS` is now `10000`
and that one key is rounded at the store's door, so the recorded option, the revision's note and the argument agree.
`test_bonded_fitting.py` pins the integer env value and the rounding of a fractional request. The dashboard was
restarted at 2026-11-11 14:31 HKT on the fixed code, with no run queued or running. Checks: bonded 243, mapping 134,
`test_bonded_fitting.py` 64, ruff clean.

**2026-11-11 ponytail-audit cleanup.** Committed `82b731f` (the round), after a five-lane re-audit of the whole tree. The run contract is smaller: the `resume_of` fork-from-source path (no caller, no row) and the `waiting` status (no writer) are gone -- a CG run consumes a completed AA reference and queues directly -- `sections.py` no longer carries the tests-only panel vocabulary, and `Store.page` owns the Runs filters so `routes/runs.pages_of_runs` keeps no second copy of the query. The harness absorbed `saved_mapping`, one `gpu_host`, `write_cg_pdb`, and the browser helpers `wait_for_traces`/`open_run_section`/`read_when`/`open_compositions`/`serve_pdc_new_run`; JS `shared.js` owns `artifactUrl`/`artifactText`/`plural` and `api()` takes an optional `timeoutMs`; dead `beadFamilyCode`/`jobsGeneration`/`lowestOverlapPairs` and the one-caller route/coordinator/views wrappers went. Checks: fast 2613 passed / 1 xfailed, browser 346 (one load flake, green on rerun), slow 23, ruff clean. Left deliberately: the 16,870-line `docs/superpowers/drafts/2026-10-13-pdc-system-preview-draft.html` is `test_ngl_beads.py`'s oracle (its three unreferenced companions went); this file keeps its landed-slices history; `scripts/test_module.sh` keeps its tier shorthand; Playwright `expect` was not substituted for the synchronous `count() == 0` reads. The live dashboard was not restarted -- no route behavior changed beyond the dropped `waiting` status and the one filtered query. `docs/PROJECT_GUIDE.md` states the current waiting rule. `.bench-surfaces/` is ignored in the working tree's `.gitignore`, which still carries the user's uncommitted `graphify-out/` line.

**2026-11-10 round built and live.** Committed `38c113e` (the round) and `081a60d` (migration output), after all phases of `docs/plans/2026-11-10-aa-cg-cg-run-bond-panel.md`. The live workspace was migrated with `python -m dashboard.cli.migrate_run_types --apply` (the four `aa_cg` records `141cb0d45c76`, `64f272ade054`, `67bc79a995d6`, `ce1318485197` are now `cg`, `legacy_run_type: aa_cg`, stages and files untouched, `migration_history/run-type-*.json` written), and the dashboard was restarted at 2026-11-11 10:50 HKT. Live checks: `/api/run-filters` names `aa_only/cg/osmotic/pdc`; all 13 runs list with the four `cg` records readable; New run shows the parameterization select (DDM's two revisions); Bond Interactions shows `Martini 3 reference · LAC` for Lactose and `· GLC` for Glucose, with the GAL-ambiguity sentence on the Glucose model; the Combinations panel renders the molecule-name/head-link fields and the saved-models table; no page errors. The migrated DDM revision records no starting coordinates (fitted before this change) and its recorded AA reference no longer verifies, so `stored` correctly refuses it with the reason and only a fresh fit will carry coordinates. Checks: fast 2619 passed / 1 xfailed, browser 346, slow 24, ruff clean; the two superseded browser modules are deleted. Left in the tree deliberately: the pre-existing `README.md` deletion and `.gitignore`, `.agents/`, `.bench-surfaces/`, and `molecules/{DM,LMNG,NG,OG,OGNG,UDM}` — none is part of this round. Drafts: `docs/design/drafts/2026-11-10-{bond-interactions-parameterization,new-run-aa-cg,cg-compositions-molecules}.html`.

**State at hand-off (2026-11-09).** The round is committed: `16709b7` (refinement fix), `17fe2c4` (torsion explainer),
`99770d6` (Shape model labels), `b55b9e2` (pdc `pdc-structure`), docs `e72ab89`/`a1f97bf`. The tree is clean apart
from the pre-existing untracked `molecules/{DM,LMNG,NG,OG,OGNG,UDM}` and `.bench-surfaces`. Checks: fast 2547 passed
/ 1 xfailed, browser 338, slow 25, pdc unit 657, pdc browser 3, ruff clean.

**1. Restart the dashboard first.** `92971317fbe2` (`AA NPT production`) still held the unit at hand-off (its own ETA
17:44). Restart only when it is no longer `running`, then check the three things the new code added: the Runs
**Filters** block loads its vocabulary and narrows a list; the pdc **Structure and interactions** section appears for
a pdc run and queues one attempt; and a circular-harmonic model saved to a mapping writes **one** `1 2 5 6 2 …`
dihedral line in stage 3, not eight.

**2. Then the open decisions, in this order.** Each is a row in the table below with its evidence: the fit/saved
torsion asymmetry (which also settles the auto-save question the user asked), `dihedral-fit`'s circular reading, the
pdc questions that gate the energy rerun and the SDF, and pdc contacts on a protein run. The pdc defaults already in
force, and where they are stated, are in the 2026-11-09 round paragraph under *Next task*.

**3. The queue behind those.** NGL's eager load, Plotly's warm, the stale mutation mutant and `pytest-socket` — none
blocks the above.

The plans and drafts these items name are local (gitignored): `docs/plans/2026-11-09-pdc-analyses-definitions.md`,
`docs/plans/2026-11-09-next-round-runs-filters-pdc-analyses.md` and the
`docs/design/drafts/2026-11-09-{runs-filters,torsion-refinement-explainer,shape-volume-models,pdc-structure-interactions}.html`
drafts.

## Next task

**graphify agent skill (2026-11-09).** The `graphify` skill is installed for agents working in this checkout:
`.agents/skills/graphify/` is tracked (the upstream skill + references, `graphifyy 0.9.104`), `graphifyy` itself lives
in `.venv` only (a local development tool, not a runtime or test dependency; reinstall with
`.venv/bin/python -m pip install graphifyy`), and `graphify-out/` is gitignored
because the graph is rebuilt from the checkout on demand. The stock installer looks for `graphify` on `PATH` and falls
back to a uv-tool install, which this host's read-only home refuses, so the checked-in `SKILL.md` carries a two-line
local note that runs every command through `.venv/bin`; `graphify install --platform agents --project` overwrites it
and the note must be re-applied after an upgrade. AGENTS.md's *Where things are* now teaches the agent-facing rule:
build/`--update`/`query` through `.venv/bin/graphify`, cross-file questions only, never as a check. Edges are
`EXTRACTED`/`INFERRED`/`AMBIGUOUS`, and callers are still found by search and pinned with tests. Verified: the skill
appears in the session catalog; a code-only build of `micelle/` (16 files → 66 AST nodes, 166 edges; graph 75 nodes,
164 edges, 10 communities, no LLM) and `graphify query "How is the belt radius measured?"` answered from `frame.py`
(`belt_mask` L69, `belt_points` L78, `_axial` L115). The scoped `graphify-out/` from that check was removed, so the
first `/graphify .` builds the repository graph.

**Molecule selector and published sugar references in CG Bond Interactions (2026-11-09).** The panel's model card
now leads with a **Molecule** select; the **Mapping** select lists that molecule's saved mappings, asked of
`/api/mappings?view=summary&molecule_id=…` rather than filtered in the page. A sugar molecule gets a read-only
**Martini 3 sugar reference · <ENTRY>** option when the entry is its own published model: Sucrose is SUCR and
Trehalose is TREH (after the 2026-11-09 decision to unblock it, below). **Maltose is refused**: its layout also
matches `LAC`, but `LAC` is lactose and identification is stereochemistry-blind (two hexoses, an AB link), so
`reference.PUBLISHED_FOR` gates the route before the layout check. The new core route
`GET /api/mappings/reference/<molecule_id>` transcribes the entry with `sugars.reference.run_topology` and answers
`{"model": {file, name, molecule_id, read_only, reference_entry, beads, rings, connections, topology, reference,
limitations, status}}`; a molecule with no published entry, no ring, no identified entry or a non-conforming layout is
404, an unknown molecule 400. The route imports only `dashboard.models.sugars` and the mapping context, never the
validation feature. The summary rows now also carry `molecule_id`.

A selected reference is shown, never parameterized: the table and Plotly scene read `parseTopology(model.topology)`
with source `martini-reference` (B01.. joins the candidate's own bead names as a revision does), while AA reference,
engine, threshold, temperature, torsion controls, **Fit this model** and **Delete this parameterization** are disabled
with the panel's own read-only sentences; the revision strip says it has no revisions and no
`/api/bonded-parameterizations*` route is read or written for it. Leaving the reference for a saved mapping restores
the normal card. Files: `web/templates/dashboard.html`, `bonded.js`, `bonded-parameterization.js`, `mappings.js`,
`web/routes/mappings.py`, `models/mappings/store.py`, the two bonded browser tests, the new
`tests/integration/test_reference_models_api.py` (area: mapping), and `test_plotly_lazy_browser.py`'s fixture (now
built through the editor's molecule+snapshot construction). Checks: fast 2560 passed / 1 xfailed; browser 340 passed;
the six affected browser modules 48 passed; ruff clean. Live after the 19:44 restart: Sucrose/SUCR and Trehalose/TREH
each show 14 terms (1 bond, 6 constraints, 4 angles, 1 dihedral, 2 virtual sites) with source `martini-reference`,
Fit and Delete disabled, the transcript sentence, a drawn Plotly scene and no page errors; Maltose offers no
reference option (its LAC layout match is refused as lactose); DDM offers none. Plan (local):
`docs/plans/2026-11-09-bonded-molecule-selector.md`. This slice is uncommitted in the working tree.

**Trehalose unblocked (2026-11-09, the user's decision).** The published `TREH` atom 8 carries residue 1 while its
parents 5–7 are residue 2. Two readings were wrong, not the candidate: `reference.signature` grouped a virtual site
by the file's residue column (now it takes the site's residue from its parents), and `coords.ring_layer` gave a 1,1
linkage's bridging oxygen to the higher ring (now the tie goes to the first ring, matching the entry's SP1r glycosidic
bead and SN6 linker). `reference.conform` and `sugar_cg` now accept TREH: `GET /api/mappings/reference/Trehalose`
answers 200, the panel offers the read-only TREH model, and the CG-only Trehalose run is no longer blocked. The
published file is untouched. The pinned automatic-candidate list for Trehalose moved with the oxygen (deliberate and
noted in `test_mapping_algorithms.py`); no other molecule's candidate moved. Tests updated: `test_sugar_reference.py`,
`test_sucrose_reference_candidate.py`, `test_reference_models_api.py` (TREH 200), validation
`test_sugar_cg_adapter.py` and `test_sucrose_cg_api.py`, and the core `test_new_run_sugar_cg_browser.py` (TREH now
starts rather than blocks). Live: the route answers TREH with 8 beads (SP1r/SP4r/SP1r/TC4/SN6/SP4r/SP1r/TC4), the
panel draws its 14 ITP terms read-only, and `/api/sugar-cg/preview?molecule_id=Trehalose&sugar_entry=TREH` reports
`ready: true, conforms: true` with Start enabled. The `test_dashboard_browser.py` layout test also gained a wait for
the molecule options before measuring, which is what made its intermittent parallel-tier failure reproducible.

**BARTENDER fit on a preprocessor topology (2026-11-09).** The Maltose panel fit (`31ae7f1695c14e78`,
`7770e83c37f346b2`) died in its `fit` step after four seconds with `ValueError: invalid literal for int() with base
10: '#ifdef'`. Cause: `bartender_fit.physical_topology` read the CG model with `itp.sections(text)` and no `defines`,
so `#ifdef FLEXIBLE` was content; `ff_inter` writes the B2-B5 linkage as a bond under `#ifdef FLEXIBLE` and the same
pair as a constraint under `#ifndef`, and the `[ bonds ]` branch fed `int()` a directive. The reader now passes
`defines=()` like every other topology reader (`dihedral_fit`, `bonded_estimate`, `structures`), so only the branch
`grompp` takes is handed to the fit and the linkage is the constraint it is in the run that consumes the model.
Regression test: `test_only_the_preprocessor_branch_grompp_reads_is_handed_to_the_fit`. Verified on a copy of the
Maltose work directory, never the live one: the fit completes and `gmx_out.itp` holds 4 bonds, 3 constraints, 4
angles and 1 dihedral, and `topology_from_fit` merges them back into the 8-atom model with the virtual sites kept.
Checks: `test_bartender_fit.py` 13 passed, the neighbouring fitting/topology modules 57 passed, ruff clean. The
dashboard imports `bartender_fit` at startup, so restart it before retrying the two failed jobs.

**AA constraints in New run (2026-11-09).** The Stage settings now carry a visible
**Constraints** control: `constraints` (`none` / `h-bonds` / `all-bonds`) is an AA-half `CHOICE_SPECS` entry that
defaults to the force-field entry's own `all-bonds` and is written into every AA MDP (`aa.mdp_values` +
the writer's force-field block, which accepts the run's value in place of the entry's). A run type with no AA half
(`sugar_cg`, `cg_composition`) shows the control disabled at `none`, keeps the AA value in the form so a switch
back cannot post it, and the reviewed CG profiles keep their own `none`. The AA child job of a new AA-to-CG pair
now keeps the parent's **choice** settings too, not only the numeric ones -- otherwise `force_field` and
`constraints` were dropped before the source was prepared and `aa_references.verify` would refuse the reference
the run named. The form's help text is the manual's `constraints` sentence; the option selects bond conversion,
and a topology's `[ constraints ]` block (the 0.274 nm B02-B05 link in `64f272ade054`) is enforced by LINCS
whatever it says. Checks: fast 2551 passed / 1 xfailed, browser 339, ruff clean. Plan
`docs/plans/2026-11-09-aa-constraints-setting.md` (local). The dashboard was restarted 18:56 and `/api/defaults?run_type=aa_cg` answers `all-bonds`.

Newest first: the five paragraphs above are the current slices; the 2026-11-09 round is the section above it, and the
paragraphs below are the slices before that, newest last; the open items table is the queue. The 2026-11-05 nine-point round is implemented and committed (items 1-6, 8, 9; there was no item 7). Its plan is
`docs/plans/2026-11-05-feature-round.md`, which carries the decisions, the per-lane evidence and the two corrections
found while building.

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
comparison analyses. Sucrose conforms; Trehalose was selectable-but-blocked because the published `TREH` second `TC4`
carried residue 1. That blocker was retired on 2026-11-09 by reading a site's residue from its parents and giving a
1,1 linkage's bridging oxygen to the first ring (see the Trehalose paragraph under *Next task*): both entries conform
and both runs are offered. The New run form gets the sugar selector, provenance and conformance preview; its
`sugar-cg-v1`
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

**Sugar comparison subpanel (deferred, hand-off 2026-11-10).** Add a **Sugar comparison** subpanel to the validation
workspace: compare the three-bead ring triangles and bead compositions of the published Martini 3 sugar *entries* with
the sugars we have **mapped/parameterized**. No code has been started. This is a UI and cross-layer change, so a future
agent starts with a plan in `docs/plans/` and an HTML draft, not code.

Data sources. Reference entries: `dashboard.models.sugars.reference` (`entries`, `entry`, `signature`, `run_topology`;
the reference constraints are already "15% COG scaled" in the file) and `reference.PUBLISHED_FOR` for the
molecule-to-entry policy. Our sugars: the saved mapping drafts (`mappings.list_candidates`; each mapping's `rings` and
`beads`) and the fitted parameterization revisions (their own `[ atoms ]` and `[ constraints ]`); a run's
`2_mapping/ring_targets.json` carries `raw_mean_nm` and `target_nm` per ring pair, where `target_nm = raw_mean_nm ×
ring.scale` (default 1.15). Geometry: each ring's three physical beads form a triangle; sides are the mapping
constraints, area is Heron, angles are the law of cosines, perimeter is the sum; the `TC4` virtual site is the
equal-weight centroid of its three parents and adds no fourth vertex; the inter-ring link is **unscaled** and is not
part of the triangle.

Show reference and mapped side by side per sugar unit, with the source named and **raw and scaled distinguished**.
Rules the panel must keep: a reference entry is citation metadata, not validation; `conform` checks mapping facts only
and records `stereochemistry: unresolved`; `PUBLISHED_FOR` must keep a layout match from being presented as another
molecule's model (Maltose identifies `LAC` by layout, but `LAC` is lactose); never label reference numbers as fitted
values. Measured 2026-11-10 on the scaled values: GLC 7.25 Å², LAC rings 6.82/6.04, TREH 6.70/6.76, our Maltose units
5.64/5.29. Open question for the panel: our scaled Maltose units (mean 5.47 Å²) are close to the reference's
**unscaled** sizes (≈5.1–5.5 Å²) rather than its scaled ones (6.0–7.25 Å²); show both and do not conclude a missing
scale or a chemistry difference until a like-for-like AA source exists (there is no `molecules/Lactose`/`Glucose`).

| item | state | next |
| --- | --- | --- |
| Sugar comparison subpanel | not started; hand-off 2026-11-10 | build the validation "Sugar comparison" panel (reference vs mapped triangles and bead compositions); start with a plan + HTML draft; see the paragraph above |
| Align trajectory's initial state | the form prefills defaults, so a stored series built with `fit: rot+trans` opens with the box unchecked while its summary line says the fit | decide whether Frame options should prefill the stored build's arguments instead of the defaults |
| Analysis checklist membership | the checklist lists the run's attempted kinds; a kind never queued (e.g. an automatic kind that has not run) is absent | add a server-side "what this run can compute" list and show those unticked, if wanted |
| Runs filters | built 2026-11-09 (`119d5c0`): dense only, checkbox run type/status/method, multi-value `/api/jobs`, `GET /api/run-filters` | the molecule and created-after facets were not added; its own slice if wanted |
| Torsion refinement on a `funct 9` dihedral | fixed 2026-11-09 (`16709b7`): one harmonic term per dihedral, siblings dropped, pinned by three unit tests; `funct 2` is the calibrated spelling; no consumed data was affected | none — keep the grouping when the refiner changes, and decide whether a Bartender fit should be refinable at all |
| A fit's unsaved torsion choice | the revision records what the job started with, but `refine_bonded` reads the mapping's saved `model.json`; measured on `10c318949…` revision 1 (circular in `options`, `{}` in the report) | decide: pass the job's options to the refiner, record the mapping's options, or let a successful fit save the pair to the mapping (the auto-save the user asked about) |
| `dihedral-fit` has no circular reading | it skips `funct 2`, which is the circular model's spelling, so it checks a legacy fit only; the panel caveat now says so | add a harmonic branch, or keep it as the legacy-only check |
| pdc `pdc-structure` defaults | built with the document's recommended defaults (RDF pairs, 0.05 nm bins, `r_max` = min(2 nm, half the box), the run's own contact cutoff, detergent-only shape tensor) | change any of them; each is stated in the report's method |
| pdc contacts on a protein run | `gmx mindist -on` contacts are produced only when the run records a protein; no completed protein pdc run exists to verify it on | verify on the first completed protein pdc run, then its report is comparable with the micelle-only one |
| pdc energy and SDF | `pdc-structure` is built; `pdc-interaction-energy` waits on Q10–Q12/Q14/Q15 and `pdc-sdf` on Q18–Q25 in `docs/plans/2026-11-09-pdc-analyses-definitions.md` (Q25 is how the cube is shown; it has no Plotly reader) | answer the numbered questions, then build in the document's order (energy, then SDF) |
| pdc cluster step | 1 of 4 live producer runs failed inside `gmx trjconv -pbc cluster`; the cause was hidden by the old error tail, which now reports the real GROMACS line (`error_tail`); the three repeats were identical | if it recurs, capture the reported line and decide a retry or a cheaper clustering (the frame-series producer's sampled-slice `-pbc cluster` is the existing alternative) |
| New routes need a restart | `119d5c0` added `/api/run-filters` and repeated `/api/jobs` values; `16709b7`/`b55b9e2` added the refinement fix and the pdc kind. The dashboard was not restarted because `92971317fbe2` was in production | restart after that run finishes, then check the Runs filters and the Structure section live |
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
  `max_concurrent_runs` counter at all four start sites (create, admit, resume/continue, and the then-live waiting
  consumer); the setting is now a per-device ceiling, so two runs on different `mdrun_gpu` devices start together. The
  refusal is "This GPU is busy. Either wait for the run to stop or choose a free GPU." Pinned by
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
