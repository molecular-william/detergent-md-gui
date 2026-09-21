# DDM calibration and carbohydrate implementation — current handoff (2026-09-16)

Read this before continuing DDM calibration, changing distance scoring, or extending the bonded-state dashboard. This document records current decisions and gaps; linked run reports contain the numerical evidence. Earlier design documents describe intended behavior, not proof of implementation.

## Resume here

1. Read the [torsion comparison report](../reports/dashboard/ddm-torsion-comparison-20260916/REPORT.md) and its [figure](../reports/dashboard/ddm-torsion-comparison-20260916/torsion_comparison.png). Retain circular-harmonic torsion scale **1.0 provisionally**. Neither new scale 0.75 nor 1.25 clearly improves it.
2. Resolve **AA reference sampling** before further fine fitting. The mapped AA glycosidic torsion mean changes markedly across the 10 ns reference. Obtain independent AA sampling, check equilibration and block stability, and reserve independent data for evaluation. Completion requires consistent populations across independent trajectories/time blocks, or an explicit finding that they remain unconverged; a completed MD process is insufficient.
3. Once the target distribution is reliable, test whether its narrow main peak and broad tails require a periodic potential or coupled linkage-angle/torsion treatment. Preserve the existing model as the control. A second torsional state has not been established.
4. For dashboard work, start with the implementation gaps below. Verify behavior in the browser before declaring a feature complete. This handoff does not authorize deleting existing outputs or restarting active simulations.

No further MD was launched during this documentation handoff. All three named CG campaigns below were completed at the last analysis. Inspect live jobs/processes before operating the server; process IDs from previous conversations are stale.

## Current scientific model

- AA source run: `c9d94e874c3d`, 10 ns production at 300 K. It is a full-duration reference for these screens, **not demonstrated converged sampling**.
- Current control mapping: [mapping_candidate_e2691221c11c4a8783d145f8161ee288.json](../dashboard/mapping_drafts/mapping_candidate_e2691221c11c4a8783d145f8161ee288.json), “DDM paper circular torsion circular.” Two control runs: `32acba4d38d2`, `f8b29dcc067f`.
- Architecture: six massive sugar S beads, three massive tail R beads, two massless TC4 sites: **11 total sites, 9 massive beads**. Earlier “local 10 bead” descriptions concern older candidates.
- Mapping covers all 35 heavy atoms. Six ring constraints retain the paper-inspired 1.15 scaling; virtual sites are arithmetic means of their three parent beads. Their positions are not necessarily the COG of all sugar ring atoms.
- Atom assignments, bead types, constraints, and non-torsion bonded terms were identical across the torsion stiffness screens, verified against `stages/4_CG_sim/DDM.itp`.
- Baseline glycosidic torsion: atoms `1 2 5 6`, GROMACS function 2, phase `-99.976346°`, force constant `4.5566924 kJ mol^-1 rad^-2`. `torsion_scale=1.0` is a multiplier on the AA-derived constant.
- All comparison CG runs use 1 ns equilibration plus 10 ns production, 300 K, 10 ps trajectory interval, independent seeds and 8 CPU threads. This is structural screening, not validation of micellization, partitioning, or protein-detergent behavior.

| Export names | Mapping names | Role |
|---|---|---|
| B01 / B02 / B03 | S1A / S1B / S1C | First sugar physical sites |
| B04 | S1VS | First sugar virtual site |
| B05 / B06 / B07 | S2A / S2B / S2C | Second sugar physical sites |
| B08 | S2VS | Second sugar virtual site |
| B09 / B10 / B11 | TAIL1 / TAIL2 / TAIL3 | Alkyl chain |

The carbohydrate architecture is included at the end of this document; the pinned paper/topologies are in `references/`. Sugar–alkyl bead chemistry remains provisional. Keep the paper's bridge-oxygen ownership rule based on chemical carbon numbering; changing fragments arbitrarily is not an established remedy for the residual torsion mismatch.

## Completed campaigns and authoritative results

| Campaign | Evidence | Outcome |
|---|---|---|
| Circular torsion scales 0.5, 1.0, 1.5; two replicas each | [Plan and run IDs](../reports/dashboard/ddm-circular-screen-20260915/plan.json) | Circular phase correction improved the old torsion mismatch. See the latest comparison for ranking. |
| Linkage-angle variants; two replicas each | [Plan and run IDs](../reports/dashboard/ddm-linkage-angle-screen-20260916.json) | Baseline retained. The “soft” and “firm” variants changed both angle center and stiffness, so effects cannot be attributed to stiffness alone. |
| Fine torsion scales 0.75, 1.25; two replicas each | [Plan and run IDs](../reports/dashboard/ddm-torsion-scale-screen-20260916.json) | No consistent improvement over scale 1.0. |
| Combined torsion analysis, all five scales | [Report](../reports/dashboard/ddm-torsion-comparison-20260916/REPORT.md), [results and source hashes](../reports/dashboard/ddm-torsion-comparison-20260916/results.json), [analysis script](../reports/dashboard/ddm-torsion-comparison-20260916/analyze.py) | Primary source for the current recommendation. |
| Earlier distance rescore | [Report](../reports/dashboard/ddm-rescore-20260915/REPORT.md) | Supplementary historical report; the latest combined analysis supersedes its ranking. |

The latest comparison inspected actual simulated topologies, production frame counts, SASA, and equilibration/production logs. All four new runs completed, with 1001 CG frames each and no runtime LINCS warnings, constraint failures, or fatal errors found. A `lincs-warnangle` settings line is not a runtime warning.

### Corrections to earlier conclusions

- Scale 1.0 is a balanced provisional choice, not a clear winner on every score. Scale 1.5 has a slightly lower overall score but a narrower torsion distribution than AA.
- A low Wasserstein distance alongside a large Fast-Forward score does **not** prove a software bug. Narrow constrained distributions, deliberate ring expansion, and different metric sensitivities can explain the discrepancy. B05–B08 is a derived-site distance; no independent B05–B08 spring should be introduced to improve its score.
- The AA distribution is dominated by a peak near -100°, but has substantial tails. Approximate 2 ns block circular means are -124.6, -117.5, -98.0, -82.9, -65.4°. Direct recalculation from mapped XTC confirmed the saved dihedral samples (maximum wrapped discrepancy about 0.0037°). Convergence has not been established.
- The local skill mentions a possible weighted multi-observable objective. **No normalized combined objective was implemented or used to select the model.** Do not add Wasserstein nm, dimensionless Hellinger values, SASA units, and angles without declared normalization. Current reports show separate components.

## Scoring contract

| Output | Calculation and interpretation |
|---|---|
| `score_matrix_DDM.png` / `report_distances.out` | Native Fast-Forward comparison against raw AA-mapped distributions. The matrix uses a modified Hellinger/mean-difference score, not pure Hellinger. Current default weights are 0.7/0.3; recognized constrained pairs use 0.2/0.8 unless `-include-constraints` is requested. Constraints are reweighted, not excluded. See `resources/parameterizers/fast_forward/fast_forward/score.py`. |
| `report_interactions.out` | Per-term entries are `Hellinger (modified score)`. The reported overall interaction score is a modified-score summary. Keep these labels distinct. |
| `distance_diagnostics_stratified.json` | Wasserstein distances in **nm**, comparing raw mapped AA and ring-expanded AA with independent CG. Lower is closer; no universal 0.3/0.5 threshold applies to nm values. |
| `distance_matrix_stratified_DDM.png` | Physical-pair Wasserstein matrix against expanded AA when available, otherwise raw AA. Virtual pairs are masked; the six physical constrained pairs remain visible in the heatmap. |
| `stratified_means_nm.physical` | Mean over 30 pairs, excluding 6 constrained physical pairs and 19 pairs involving virtual sites (55 unique pairs total). Therefore it is not the mean of every visible heatmap entry. |
| SASA | Agreement of means, variability, and sampling is relevant. A larger/smaller SASA is not inherently better. Existing comparison uses the recorded radius/probe convention. |

`dashboard/execution/scripts/distance_diagnostics.py` owns the additive diagnostics. `assess.sh` invokes it after Fast-Forward assessment. Raw and ring-expanded targets must both remain available: expansion is a chosen modeling target, not independent physical validation. The diagnostic assumes molecule-whole coordinates and matching bead order; preserve and verify these invariants when adding new sources.

Legacy reports may lack pair categories. Missing fields are **unknown**, not zero. Some older diagnostics/stratified PNGs were added directly beside the original assessment files during prior sessions; those additions may not appear in the original manifest checksums. Preserve them and publish future derived work under a new analysis/report directory with source hashes.

## Dashboard implementation status and remaining gaps

Latest user preference: molecular connectivity is an **enlarged fixed 2D view**, not rotatable. Tabs are Runs, New run, CG Bead Assignment, CG Bond Interactions. Keep one selected mapping candidate at a time. The separate 3D bead-assignment visualization is a different feature.

Present in code:

- Figure tabs with image zoom, native and stratified matrices, and diagnostic tables.
- Figure listing refreshes the persisted artifact index for `media=1`, fixing stale completed-run lists that hid newly generated matrices. Figure captions are currently selected in JavaScript by filename.
- Bonded-state JSON store, revision API, legacy-fit indexing, confirmation/dependency checks for deletion, fit-only/reuse run intents, short-validation launcher, topology parser, and read-only interaction table/ITP preview.
- Manual bonded overrides remain available through the advanced JSON editor in CG Bead Assignment and are applied after fitting. `dashboard/models/bonded.py` supports circular-harmonic fitting and one override per flexible term.

Code-inspected gaps to address before claiming the full approved bonded workspace is complete:

1. **Interactive editing is unfinished.** CG Bond Interactions has no parameter editing/save-as-new controls. Creating a state produces an incomplete record with no topology. Backend `revise()` appends revisions but does not implement distinct `in_place` semantics. The approved [design](superpowers/specs/2026-09-15-cg-bonded-workspace-design.md) and [plan](superpowers/plans/2026-09-15-cg-bonded-workspace.md) are a backlog, not completion evidence.
2. **Mapping/state matching and overlay identities:** the workspace state selector lists all states without filtering by mapping identity. Parsed topology labels are B01/B02/etc., while diagram centers are keyed by S1A/S1B/etc.; existing-state term overlays/highlighting need an explicit index-to-mapping translation. Mapping hashes include the candidate name, making renaming relevant to compatibility.
3. **Virtual-site parsing:** `virtual_sitesn` parents currently appear in generic parameter fields instead of participating bead indices. Fix that before visualizing parent links or exposing editing.
4. **Preview/load behavior:** the preview updates only when a state is passed to `draw()`. Mapping-only selection can retain stale preview contents. Provisional `[ mapping-only preview ]` / `[ connections ]` text is explanatory, not a GROMACS-ready ITP. Add stale-response protection and explicit async errors.
5. **Scoring display:** old JSON fallbacks can misclassify constrained pairs; missing expanded values can be rendered as zero in the current JS. Captions must reflect actual reference and metric. Matrix color limits vary with each run's maximum; compare numbers, not color alone. The generic native-matrix caption still oversimplifies the modified score.
6. **State safety:** payload/topology validation, revision concurrency, and mapping compatibility need stronger tests before exposing general editing. Current storage is JSON, not the SQLite state tables envisaged by the plan. Do not trust a `complete` status alone as scientific validation.

These are documented observations, not fixed by this documentation-only handoff. Avoid propagating earlier “implemented” claims beyond what the code and browser demonstrate.

## Operation, verification, and file ownership

- Use `dashboard/.venv/bin/python` from the repository root; check the configured GROMACS path/version and manifests. CG scripts currently request `-ntmpi 1 -ntomp 8 -nb cpu`.
- Start only one dashboard coordinator at `127.0.0.1:5000`. Check active jobs, leases, and subprocesses before restart; a restart can interrupt work. Do not reuse old PIDs or broadly kill Python processes.
- Campaign runner: `-m dashboard.cli.screen_candidates <absolute-plan-path>`. Plans store unique labels, run IDs, seeds, status and errors and support resumption. The runner executes serially and stops on failure. A completed plan resumes without new MD; use a new plan for new variants. Verify that any background launcher persists and records the first accepted run.
- `<workspace>/runs/<id>/manifest.json`, `inputs/`, `stages/`, `logs/` are simulation evidence. SQLite is the only live job-status authority. See [project operations](PROJECT_GUIDE.md).
- `dashboard/models/bonded.py` owns overrides and torsion fitting; `carbohydrates.py` owns sugar geometry/topology; `bonded_states.py` owns state records; `dashboard/execution/` owns execution, `dashboard/web/routes/` owns HTTP endpoints, and `dashboard/web/static/js/`, CSS, and templates own UI behavior.
- The personal skill is `/home/wtliaf/.codex/skills/detergent-calibration/SKILL.md` with `references/carbohydrates.md` and `references/building-blocks.md`. It is outside this repository; this handoff and the linked chemistry document provide the portable project context.
- This directory did not have Git metadata at the latest check. Verify repository/worktree availability before planning commits or branches.

Focused checks when modifying bonded logic:

```bash
dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_bonded.py tests/dashboard/unit/test_bonded_states.py -q
node --input-type=module --check < dashboard/web/static/js/main.js
```

The older bonded checkpoint reported 10 focused tests passing; that is not a full-suite guarantee. Mapping/export/draft-execution tests now generate self-contained candidates rather than reading deleted `mapping_candidate.json` or `mapping_candidate_smoke.json`. Browser tests exercise the implemented Runs and New run pages; the superseded Runs prototype test was removed. Keep fixtures in temporary test directories rather than restoring user-deleted candidates. UI work needs real browser interaction checks, including fitted-state selection, save/reload behavior, invalid input, and responsive layout.

To reproduce the latest analysis, copy the analysis script into a new report directory at the same depth before running; its output directory is its own location and rerunning in place replaces report files. Simulation outputs are read-only inputs. No long MD is required for these checks.

## Other work on hold

The protein-detergent micelle builder is paused at the user's request. Its separate starting points are [MICELLE_BUILDER.md](MICELLE_BUILDER.md), the [approved design](superpowers/specs/2026-09-14-detergent-micelle-builder-design.md), and the [implementation plan](superpowers/plans/2026-09-14-detergent-micelle-builder.md). Inspect the implementation before resuming; do not silently replace DDM calibration with this project.
## DDM carbohydrate mapping implementation

This is the architecture and initial execution record. For the subsequent
10 ns campaigns, current model recommendation, and AA convergence limitation,
read the calibration section above. The short-run scores and test
counts below describe the implementation checkpoint, not current validation.

Implemented from DOI 10.1021/acs.jctc.2c00757 and the pinned official sugars v2 topology in `references/`. Existing candidates and simulation outputs were preserved.

## Candidate

[DDM carbohydrate paper draft](../dashboard/mapping_drafts/mapping_candidate_5a5397aac5254c7c94626886acc020bd.json) has six massive sugar S beads, three massive tail R beads and two massless TC4 interaction sites. Physical assignment covers all 35 heavy atoms exactly once. Nominal representation is 34 (mismatch −1).

- Graph-derived hexopyranose numbering; sugar-first canonical A/B/C fragments preserve the paper's diol/functional-group convention. The inter-sugar bridge belongs to the C4-containing acceptor fragment. The sugar–tail ether remains with the sugar A fragment.
- Sugar types: S1A/SP1r, S1B/SP1r, S1C/SP1r; S2A/SN6, S2B/SP4r, S2C/SP1r. The sugar–alkyl ether SP1r transfer remains provisional.
- Six constraints use mean raw AA COG distances ×1.15. Inter-sugar and tail bonds remain unscaled. Each TC4 site is the mean of its three parent beads, has zero mass, and excludes those parents.
- Four inter-sugar angles and one glycosidic torsion are fitted. Three connected units receive an extra orientation torsion. Unrecognized sugar classes retain an explicitly provisional generic fallback.
- Save/export/run snapshots preserve ring/site definitions. Bundles include the virtual-site mapping helper and initial topology. Standalone Fast-Forward mapping files contain only physical assignments and cannot alone construct the complete site list.
- Fixed two Fast-Forward defects in angle/dihedral membership: the property getter used the wrong attribute name, and matching considered only the last dihedral. Installed the corrected local package; future tool manifests record the fitter hash.

## Execution evidence

[Execution records](../reports/validation/carbohydrate-1789376385/execution-proof.json) record mapping, fitting, CG simulation, assessment and SASA commands and exit codes. All five stages passed against completed AA reference `c9d94e874c3d` (10 ns, 300 K). The independent CG execution check was 2 ps equilibration plus 5 ps production at 300 K. It had no LINCS warnings or fatal errors. The fitted topology retains six constraints, two virtual sites and exclusions, and restricted-bending angles for the glycosidic torsion. This establishes execution only, not scientific validation. The 5 ps CG assessment remains poor: interaction score 0.529 and distance score 0.613 (lower is better). Intended ring expansion also contributes to differences from the raw AA distance reference; report ring-internal and flexible-link behavior separately in subsequent calibration.

50 focused tests pass, including atom-renumbering invariance, glucose reference typing, three-repeat torsions, virtual-site geometry, linkage-length preservation, exports, candidate selection, and dashboard browser behavior. The browser rendered the new mapping and three 3D surface scenes without JavaScript errors.

## Surface comparison

[Interactive comparison](../reports/validation/carbohydrate-1789376385/analyses/surfaces/output/be7ae84c3782e09ea94c38682ca3478ac0b4b1cbdf90acf60efc95a12fb89854/analysis/surfaces/surface-comparison.html) includes synchronized AA/raw-mapped/ring-expanded/simulated views, consistent physical scale, original GROMACS dot outputs and SASA statistics. CG radii are R=.264, S=.230, T=.191 nm; AA uses Rowland–Taylor radii, with a .191 nm probe for both. Smooth meshes are solvent-accessible sphere-union envelopes, not re-entrant solvent-excluded surfaces.

| Model | Frames | Duration (ps) | Mean SASA (nm²) | Frame SD (nm²) |
|---|---:|---:|---:|---:|
| AA | 1001 | 10000.0 | 9.4206 | 0.5495 |
| Mapped raw | 1001 | 10000.0 | 8.7451 | 0.5351 |
| Mapped ring-scaled | 1001 | 10000.0 | 9.1288 | 0.5640 |
| Simulated CG | 51 | 5.0 | 9.2299 | 0.2534 |

Ring expansion reduces the mapped SASA shortfall from about 7.2% to 3.1%. Frame SD is not uncertainty in the mean. The short CG trajectory does not demonstrate converged SASA or justify production approval; the paper used at least 200 ns for its reported averages. Coordinate mapping is explicitly heavy-atom COG; hydrogen-inclusive weights require a separately recorded protocol.

## Files and operation

`dashboard/models/carbohydrates.py` owns ring recognition, fragment assignment, coordinate construction and constrained topology architecture. `dashboard/models/mappings.py` owns schema, review and exports. `dashboard/analysis/surfaces.py` owns surface geometry and GROMACS SASA. The DDM calibration skill includes a dedicated carbohydrate reference and corrected type/size naming guidance.

Refresh the dashboard, open CG mappings, and select “DDM carbohydrate paper draft.” Its approval remains a structural review, separate from simulation validation. New surface analyses appear as sandboxed interactive HTML within a run's analysis gallery. Earlier immutable surface artifacts remain available.
