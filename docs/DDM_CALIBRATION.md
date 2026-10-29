# DDM calibration and carbohydrate validation

Current status and decisions. Last scientific campaign: 2026-09-16; dashboard status updated 2026-10-26. Earlier
design documents describe intent, not proof of implementation.

## Resume here

1. Keep circular-harmonic torsion scale **1.0 provisionally**. Neither 0.75 nor 1.25 clearly improves it.
2. Resolve **AA reference sampling** before finer fitting. The mapped glycosidic torsion mean changes across the
   10 ns reference; acquire independent sampling, check equilibration and block stability, and reserve independent
   data for evaluation. A completed MD process is not convergence.
3. Once the target distribution is reliable, test whether its narrow main peak and broad tails need a periodic
   potential or coupled linkage-angle/torsion treatment. Keep the current model as control. A second torsional
   state is not established.
4. For dashboard work, fix the gaps below and verify in a real browser. Do not delete outputs or restart active
   simulations from this document.

No further MD was launched for this documentation. All three named CG campaigns completed; inspect live
jobs/processes before operating the server. Old process IDs are stale.

## Current scientific model

- AA source: `c9d94e874c3d`, 10 ns production at 300 K. Full-duration reference for these screens, **not**
  demonstrated converged sampling.
- DDM mapping: six massive sugar S beads, three massive tail R beads, two massless TC4 sites = **11 sites, 9 massive
  beads**. Covers all 35 heavy atoms. Six ring constraints use the paper-inspired 1.15 scaling; virtual sites are
  arithmetic means of their three parent beads, not necessarily the COG of all ring atoms.
- Atom assignments, bead types, constraints and non-torsion terms were identical across the torsion screens.
- Baseline glycosidic torsion: atoms `1 2 5 6`, GROMACS function 2, phase `-99.976346°`, force constant
  `4.5566924 kJ mol^-1 rad^-2`. `torsion_scale=1.0` multiplies the AA-derived constant.
- Comparison CG runs: 1 ns equilibration + 10 ns production, 300 K, 10 ps trajectory interval, independent seeds,
  8 CPU threads. Structural screening, not validation of micellization, partitioning or protein-detergent behavior.
- Earlier “local 10 bead” descriptions concern older candidates, not this mapping.

## Campaign results

| Campaign | Outcome |
| --- | --- |
| Circular torsion scales 0.5/1.0/1.5, two replicas each | Circular phase correction improved the old torsion mismatch; scale 1.0 remains provisional. |
| Linkage-angle variants, two replicas each | Baseline retained. “Soft”/“firm” changed both angle center and stiffness, so effects cannot be attributed to stiffness alone. |
| Fine torsion scales 0.75/1.25, two replicas each | No consistent improvement over 1.0. |
| Combined torsion analysis, all five scales | Primary source for the 1.0 recommendation. All four new runs completed with 1001 CG frames each and no runtime LINCS/fatal errors. |

### Corrections

- Scale 1.0 is balanced, not a clear winner. Scale 1.5 has a slightly lower overall score but a narrower torsion
  distribution than AA.
- Low Wasserstein distance with a large Fast-Forward score does **not** prove a software bug. Narrow constrained
  distributions, ring expansion and metric sensitivity can explain it. B05–B08 is a derived-site distance; do not
  add an independent B05–B08 spring to improve its score.
- AA is dominated by a peak near -100° with substantial tails. Approximate 2 ns block circular means:
  -124.6, -117.5, -98.0, -82.9, -65.4°. Direct recalculation from mapped XTC matched saved samples (max wrapped
  discrepancy ~0.0037°). Convergence is not established.
- No normalized combined objective was implemented. Do not add Wasserstein nm, dimensionless Hellinger, SASA units
  and angles without declared normalization. Reports keep separate components.

## Scoring contract

| Output | Calculation and interpretation |
| --- | --- |
| `score_matrix_DDM.png` / `report_distances.out` | Native Fast-Forward comparison against raw AA-mapped distributions. Modified Hellinger/mean-difference score, not pure Hellinger. Default weights 0.7/0.3; recognized constrained pairs 0.2/0.8 unless `-include-constraints`. Constraints are reweighted, not excluded. See `resources/parameterizers/fast_forward/fast_forward/score.py`. |
| `report_interactions.out` | Per-term entries are `Hellinger (modified score)`. Overall interaction score is a modified-score summary. Keep labels distinct. |
| `distance_diagnostics_stratified.json` | Wasserstein distances in **nm**, raw mapped AA and ring-expanded AA vs independent CG. Lower is closer; no universal 0.3/0.5 nm threshold. |
| `distance_matrix_stratified_DDM.png` | Physical-pair Wasserstein matrix against expanded AA when available, else raw AA. Virtual pairs masked; six constrained physical pairs visible. |
| `stratified_means_nm.physical` | Mean over 30 pairs, excluding 6 constrained physical pairs and 19 virtual-site pairs (55 unique pairs total). Not the mean of every heatmap entry. |
| SASA | Means, variability and sampling matter. Larger/smaller SASA is not inherently better. Use the recorded radius/probe convention. |

`dashboard/execution/scripts/distance_diagnostics.py` owns additive diagnostics; `assess.sh` invokes it after
Fast-Forward assessment. Raw and ring-expanded targets both remain available: expansion is a chosen modeling target,
not independent physical validation. The diagnostic assumes molecule-whole coordinates and matching bead order.

Legacy reports may lack pair categories. Missing fields are **unknown**, not zero. Older diagnostics/PNGs may not be
in original manifest checksums; preserve them and publish future derived work under a new analysis/report directory
with source hashes.

## Dashboard status

- Carbohydrate validation: queue through `POST /api/jobs/<id>/carbohydrate-validation` for a completed source run.
  Two representations: published TC4 model and physical-only variant (removes TC4, keeps physical ownership, ring
  parents and 1.15 ring constraints). Setup check is diagnostic-only; an evidence run needs a cited target dataset.
  Attempts are immutable analyses attached to the source; status does not approve a mapping or authorize production.
- Evidence profile needs mapped geometry/volume, water-to-octanol transfer free energy, and concentration-dependent
  osmotic pressure. The target registry currently records Martini 3 paper citations as metadata-only for the packaged
  Maltose pilot and reference sugars; no evidence-complete result is possible until molecule-specific targets and
  uncertainties exist. Paper-aligned minimums: 200 ns geometry, 19 BAR lambda windows, 0–2.5 molal series at about
  500 ns per concentration.
- Mapping UI uses the **3D NGL overlay**: heavy atoms, translucent sphere at each bead's atom mean. The old fixed 2D
  depiction is gone (`aa318e0`); the server's RDKit depiction remains only because the export bundle embeds its SVG.
  Tabs: Runs, Run view, New run, CG Bead Assignment, CG Bond Interactions. Keep one selected candidate at a time.
- Parameterization store: revisions keyed by mapping content hash, one current, `owners` naming claiming mappings;
  fit-job queue produces a revision without MD; deletion/dependency checks; topology parser; interaction table/ITP
  preview. The flat bonded-state store was deleted 2026-10-21 (`1667ff5`).
- Manual bonded overrides remain in the advanced JSON editor and apply after fitting. `dashboard/models/bonded/`
  supports circular-harmonic fitting and one override per flexible term.
- An artifact without per-pair `kind` is labelled unclassified with its reason, not guessed into “Physical bead”.
  The interaction parser resolves `virtual_sitesn` into named parent beads and keeps it read-only.
- `complete` is an execution fact, never scientific validation.

## Operation and verification

- Use `.venv/bin/python` from the repository root. Tier commands live in `AGENTS.md` (`## Verify`);
  `pytest.ini` owns worker defaults and counts.
- Maintained AA stages request GPU 0 for nonbonded and PME (`-gpu_id 0 -nb gpu -pme gpu -pmefft gpu`) with one MPI
  rank and eight OpenMP threads. CG leaves PME on CPU and takes its device from the run's setting. Confirm the
  selected GPU in the recorded GROMACS log.
- Start only one dashboard coordinator at `127.0.0.1:5000`. Check active jobs, leases and subprocesses before
  restart. Never reuse old PIDs or broadly kill Python processes.
- Campaign runner: `-m dashboard.cli.screen_candidates <absolute-plan-path>`. Plans store labels, run IDs, seeds,
  status/errors and support resumption; the runner is serial and stops on failure. Completed plans do not relaunch
  MD; use a new plan for new variants.
- Simulation evidence: `<workspace>/runs/<id>/manifest.json`, `inputs/`, `stages/`, `logs/`. SQLite is the only live
  job-status authority. See [project operations](PROJECT_GUIDE.md).
- Ownership: `dashboard/models/bonded/` (interaction library in `__init__.py`, fitting/generation/parameterization),
  `dashboard/models/sugars/` (ring recognition, geometry, topology), `dashboard/execution/` (execution),
  `dashboard/web/routes/` (HTTP), static JS/CSS/templates (UI).

## On hold

The native protein-detergent micelle builder is paused at the user's request; `micelle/` is a partial, unvalidated
skeleton and must not be presented as a model. Existing starting points:
[approved design](superpowers/specs/2026-09-14-detergent-micelle-builder-design.md) and
[implementation plan](plans/2026-09-14-detergent-micelle-builder.md). Do not silently replace DDM
calibration with this project.
