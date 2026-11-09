# Fast-Forward outputs: inventory and plotting proposal

Date: 2026-11-09. Research note for `docs/plans/2026-11-09-next-round.md` item 4 and decision 4.
No production code. Evidence: source under `packages/core/src/dashboard/execution/`, `tools/fast_forward/`, and the
live run artifacts named below.

## What Fast-Forward is here

`ff_inter` fits bonded terms from a mapped atomistic trajectory; `ff_assess` scores a coarse-grained trajectory
against reference histograms it does **not** make. The repository drives both through repository scripts:

- `packages/core/src/dashboard/execution/scripts/fit_topology.sh` — stage 3's fit path:
  `ff_inter -f 2_mapping/mapped.xtc -s 2_mapping/mapped.gro -i <seed>.itp -temperature <rounded K> -constraints 10000
  -dists -plots -dist-matrix`, then `refine_bonded.py`.
- `packages/core/src/dashboard/execution/scripts/assess.sh` — stage 5:
  `ff_assess -f 4_CG_sim/prod/lig_CG.xtc -s ... -i 3_initial_CG/<initial>.itp -d <references> -plots -plot-data -dists`,
  then `validate_run.py` and `distance_diagnostics.py`.
- `tools/fast_forward/bin/{ff_inter,ff_assess}` are the tool's own entry points; `config/tools.json` resolves them.

A run that **fits** has stage 3's raw Fast-Forward data. A run that **consumes** a mapping's current revision
(`use_parameterization.py`) has stage 3 without those files, because the reference histograms were fitted earlier and
live in the immutable parameterization store; stage 5 re-measures only the CG side. Any plot has to handle both shapes.

## Inventory

### Stage 3 — fit path (a run that fitted)

| file | format | producer | what it holds | consumer today |
| --- | --- | --- | --- | --- |
| `<stem>_ff_inter.itp` | GROMACS ITP | `ff_inter` (preserved by `refine_bonded.py`) | the tool's fitted topology, `funct 9` dihedrals | `bonded-cross-check`, `dihedral-fit`, `mapping` export |
| `<stem>.itp` (final) | GROMACS ITP | `refine_bonded.py` | the topology the run simulates, torsion refinement applied | `gmx grompp`, cross-check, dihedral-fit |
| `bonded_fit.json` | JSON | `refine_bonded.py` | `temperature_k`, `options`, `torsions`, `manual_overrides`, source/fitted/model digests | nothing (not published as an analysis) |
| `distributions.json` | JSON | `cg.prepare` (from the revision) or fit staging | inventory: `interactions.files`, `pairs.expected/files`, one entry per `.dat` with digest; absolute store path for a consumed revision | stage 5's skip reason only |
| `<a>_<b>_bonds.dat` / `_distr.dat` | text | `ff_inter -dists` | per-frame distance and probability density (bins, probability) | not read |
| `<a>_<b>_<c>_angles.dat` / `_distr.dat` | text | `ff_inter -dists` | as above, degrees | not read |
| `<a>_<b>_<c>_<d>_dihedrals.dat` / `_distr.dat` | text | `ff_inter -dists` | as above, degrees | not read |
| `<res>_<a>_<res>_<b>_distances.dat` / `_distr.dat` | text | `ff_inter -dist-matrix` | every pairwise bead distance over frames | not read |
| `fitted_interactions.png` | PNG | `ff_inter -plots` | the tool's own fitted-interaction figure | an artifact only |
| `plot_data.p` (only with `-plot-data`, which `fit_topology.sh` does not pass) | Python pickle | `ff_inter` | `{bonds,angles,dihedrals: {name: {x, Reference, Simulated}}}` arrays | nothing |
| `parameterization.json` | JSON | `use_parameterization.py` / the fit's revision record | revision identity, engine, `terms` counts, `distributions` inventory, `topology` text, digests | the run's mapping comparison / parameterization panel |
| `parameterization_used.json` | JSON | `use_parameterization.py` | the revision a consuming run actually staged | the run's own record |
| `reference_sugars_v2.itp` + `.source.json` | ITP + JSON | sugar preparation / Martini install | the published sugar reference and its hash/commit/DOI | named as a run input only |

Measured example (fitted run `22075892b606`): stage 3 holds 22 pair-distance files with their distributions,
5 interaction time series, `fitted_interactions.png`, `bonded_fit.json` (all torsion lists empty,
digests equal — the refinement changed nothing for that mapping), and the final `LIG1.itp`.

### Stage 5 — assessment

| file | format | what it holds |
| --- | --- | --- |
| `<a>_<b>_bonds.dat`, `<a>_<b>_<c>_angles.dat`, `<a>_<b>_<c>_<d>_dihedrals.dat` | text, one value per frame | the **CG trajectory's** own measured values (interactions only) |
| their `_distr.dat` siblings | text, `bin probability` | the CG trajectory's interaction densities |
| `report_interactions.out` | text | Hellinger distance and score per interaction, an overall `mean ± sem` |
| `report_distances.out` | text | pairwise score matrix, overall score, max. `ff_assess` does **not** write pairwise `.dat` files; the 253 reference pair histograms live in the parameterization store (or stage 3 of a run that fitted) |
| `plot_data.p` | pickle | fitted-interaction data (`x/Reference/Simulated`) for the assessment plot |
| `plot_data_distribution.p` | pickle | pairwise distance distributions (`x/Reference/Simulated`) |
| `interaction_distributions_<mol>.png` | PNG | the tool's interaction overlay |
| `distance_distributions_<mol>.png` | PNG | the tool's pairwise overlay |
| `distance_matrix_stratified_<mol>.png` | PNG | stratified distance score matrix |
| `score_matrix_<mol>.png` | PNG | the score matrix |
| `validation.json` | JSON | frame counts per ensemble, mapping max coordinate error, and the full report text |
| `distance_diagnostics_stratified.json` | JSON | consumed by the live Distance diagnostics section |
| `references.txt` | text | the directory `-d` was handed |

Measured example (`67bc79a995d6`, a consuming run): 34 interaction series (10 bonds, 22 angles, 2 dihedrals) and a
`distributions.json` inventory of 253 pairwise **reference** histograms in the store; `report_interactions.out`
overall 0.238 ± 0.0208; worst bonds `B17_B20` 0.89 (0.65) and `B17_B21` 0.84 (0.62); `report_distances.out` overall
0.358 ± 0.011; 20,001 frames per ensemble, mapping max coordinate error 5.00e-4 nm. The same run's dashboard currently
shows the cross-check and dihedral fit as sections, the distance diagnostics beside them, and the stage-5 PNGs only
through the Artifacts list.

## What the dashboard reads today

- `bonded-cross-check` and `dihedral-fit` (`analysis/kinds.py`, `default_for_run_types=('aa_cg',)`) read the ITPs and
  the mapped trajectory, not the `.dat`/pickle files.
- The Distance diagnostics section reads `distance_diagnostics_stratified.json`.
- `observables`, `plots` and `stability` are registered but have `default_for_run_types=()`, so nothing queues them.
  `plots` expects a legacy `*SASA*/AA/SASA-AA.xvg` tree that current runs do not write; `observables` measures
  unparameterized observables on the mapped trajectory, not the Fast-Forward outputs. Neither is a candidate.
- The stage-5 PNGs are immutable artifacts; the run's Analysis card does not draw them. A reader can reach them only
  through the artifact list.

## Proposal (decision 4)

Ranked by data-directness and cost. Each option reads outputs that already exist; none reruns `ff_inter`/`ff_assess`.

### P1 — Fitted and assessed distributions, per term (recommended first)

Plot `plot_data.p` (or, without pickles, `<term>.dat` / `_distr.dat`) as small multiples: one panel per term,
`Reference` and `Simulated` overlaid, grouped by bonds/angles/dihedrals. It is the same data Fast-Forward's own
`fitted_interactions.png` draws, but interactive and consistent with the dashboard's own figure style. Add the
Hellinger score from `report_interactions.out` as the panel title so a reader sees which curve is the weak one.

- Data: stage 5's `plot_data.p` → `{type: {name: {x, Reference, Simulated}}}` (verified shape on `67bc79a995d6`).
  Without pickles, overlay stage 5's `_distr.dat` (CG) with the same term's `_distr.dat` from the revision recorded in
  `distributions.json` (AA reference); the two files are different distributions, not two columns of one file.
- Cost: negligible; one file read and one Plotly figure.
- Where: a new published analysis (or an extension of the Bonded terms section) named for assessment, not the
  parameterization fit, so a consuming run still gets it.
- Caveat: prefer parsing the text `.dat`/`.out` files and treat the pickles as optional; unpickling a run artifact
  in the web process is a code-execution surface, and the current producer writes them, not a reader.

### P2 — Hellinger score ranking

Parse `report_interactions.out` into a per-term bar chart (0 good, 1 no overlap), grouped by interaction type with the
0.3/0.5 guide lines. This is the one number the tool itself calls the score, and the panel currently reports the
dashboard's histogram *overlap coefficient* instead — the two are not the same metric and should not be conflated.

- Data: text report, already numerical; no new computation.
- Cost: negligible.
- Where: Bonded terms, beside the existing overlap verdicts, with the metric named.

### P3 — Pairwise distance score matrix

A Plotly heatmap of `report_distances.out` (253 pairs for an 11-bead molecule) with the worst pairs ranked, and the
matching `distance_distributions_<mol>.png` still available as an artifact. The table is 55 cells for 11 beads but 253
values in the report; the matrix is the tool's own summary and is currently a static PNG.

- Data: `report_distances.out` (text) and optionally `plot_data_distribution.p`.
- Cost: small; the report is 253 values.
- Where: Shape/volume or a new assessment section.
- Caveat: the score matrix is symmetric and unlabelled by bead name in the file — the names are the column order in
  the report; a reader must keep the two in step.

### P4 — Run-quality summary

A small table/callout from `validation.json` and `report_*.out`: frames per ensemble, mapping max coordinate error,
overall interaction score, overall distance score, and the tool's own 0–0.3/0.3–0.5/0.5–1 guide. This is the only
place the "overall" numbers already exist; no figure needed.

### Not recommended

- Re-running `ff_inter`/`ff_assess` to draw: the outputs are immutable and already present; a rerun would be a second
  model, not a plot.
- Reviving `observables`/`plots`: wrong inputs/layout, and `observables` computes new observables rather than plotting
  the fit.
- Plotting the `_distr.dat` of stage 5 alone as "AA vs CG": stage 5 writes the **CG** side; the reference side lives in
  the parameterization store (or `plot_data.p`). A two-column file is not two distributions.
- Treating `report_interactions.out`'s Hellinger score as the dashboard's overlap coefficient, or vice versa. They
  answer the same question with different arithmetic; the label must say which one is drawn.

## Open decision (from the plan, decision 4)

Which of P1–P4 does the user want plotted, and where? The inventory above is complete; the choice is the user's.
"Specifics later" was the request, so this note stops at the proposal.

## Files that would change (when approved)

- `packages/core/src/dashboard/analysis/kinds.py` — a new kind or an extension of an existing one, with
  `default_for_run_types` if it should publish automatically.
- A producer under `packages/core/src/dashboard/analysis/runs/` reading `stages/5_assessment/report_*.out`,
  `plot_data*.p` and `stages/5_assessment/*.dat` (and the revision store for a consuming run).
- `packages/validation/src/detergent_validation/static/js/run-view-mapping.js` if the chart belongs in the existing
  Bonded/Shape sections rather than a new analysis card.
- Tests: a fixture with a tiny `report_interactions.out` and two `.dat` series; assert the chart's data, not a
  wall-clock time.
