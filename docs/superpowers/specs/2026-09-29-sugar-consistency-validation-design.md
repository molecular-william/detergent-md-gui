# Sugar mapping consistency validation — design

Status: **approved for implementation, 2026-09-29.** The layout draft in
`docs/design/prototypes/sugar-consistency-20260929.html` was reviewed and accepted, and every decision below
(D1-D6) stands as written, so nothing in this note changed during review. Implementation has not started; the
task list is `docs/superpowers/plans/2026-09-29-sugar-consistency-validation.md`.

## What this is for

The problem this answers is not "does our mapping match the paper". It is "does the CG model we build
reflect the atomistic structures we actually have". The 2026-09-29 measurement of run `03875cf39790`
made the difference concrete: our sucrose mapping reproduces the pinned `SUCR` entry's bead types
exactly, its glucose-ring A–B distance is 16% short of that entry's number, and the fragment-split
explanation for the gap was tested and refuted (of the ten arc cuts of the glucose ring's atoms, exactly
one partition survives the reference's own bead types, and it is the one the recognizer already
produces). Nothing in the repository can currently say whether that 16% matters for our model, because
nothing measures the simulated CG side of the comparison at all.

So the deliverable is a comparison chain with three tiers, kept visibly apart:

| tier | question | data needed | status |
| --- | --- | --- | --- |
| T1 internal consistency | does a CG run of this mapping reproduce **our own AA** ensemble? | our AA reference + our CG run of the same molecule | not built |
| T2 reference context | how far are **our derived targets** from the pinned reference entry? | `references/martini_v3.0.0_sugars_v2.itp` | core exists (`sugar_ensemble`), no surface |
| T3 experimental evidence | does it agree with measured physical chemistry? | cited targets with uncertainties | blocked: every registry dataset is `metadata_only` |

T1 is the primary evidence and needs no citation. T2 is context and must never be rendered as a pass or a
fail. T3 stays blocked until measured targets are entered; the existing rule applies and is not relaxed —
a completed analysis proves execution, not model validity.

## The comparison primitives

Every analysis below is one of four primitives, and each one names which of them it is (see "Labelling").

1. **Distribution comparison.** Two ensembles of the same scalar (a bead-pair distance, a bond length, an
   angle, a dihedral, a radius of gyration, a SASA value). Report mean, standard deviation, block standard
   error, Wasserstein distance in native units, and the overlap score Fast_Forward already computes
   (modified Hellinger), so a number here is comparable with the existing assessment reports rather than
   introducing a fourth metric family.
2. **Target comparison.** One derived value (our AA ensemble mean) against one declared number (the
   reference entry's constraint, or a cited experimental value). Report the delta in percent and absolute
   units, and the spread that produced it.
3. **Structural displacement.** Bead centres from the AA reference mapped to CG, against the bead centres
   the CG run actually holds, after a rigid-body fit on physical beads. Report per-bead displacement and
   RMSD.
4. **Convergence.** Block averages over the sampling window for every scalar above, plus the observed
   range. No figure is published without it, because a single trajectory has no error bar of its own.

## Panels, and the decisions taken

Design decisions below are mine, taken so the review can be about judgement rather than about
fill-in-the-blank. Each is reversible and says what it costs to reverse.

### D1. One new tab, plus a line on the run card

The content is scoped to a *quadruple* — molecule, saved mapping, AA source run, CG consumer run — which
is not any existing tab's scope, and it is four cards deep. It gets a new tab, **Mapping Validation**,
with a sticky selector row at the top: molecule, mapping, AA source, CG consumer, tier badge. Reversal
cost: moving four existing cards into `#tab-mappings` is a template edit and one mount change.

So that the tab is not something a user must know about, a run card whose mapping and sibling run both
exist gains one line under its timeline: "Consistency: CG 4 of 6 ring distances inside the AA spread — open".
It links to the tab with the triple preselected. Reversal cost: deleting one line from the run card.

### D2. Four cards, in this order

1. **Ring and constraint geometry** — the ensemble tool's natural home. For each constrained pair:
   overlaid AA and CG distributions, the AA mean marked, the reference value as a dashed context line,
   and a row in a table: AA mean ± block stderr, CG mean ± block stderr, Δ(AA→CG) in %, and whether the
   CG mean lies inside the AA range. This is the card that answers the current open question.
2. **Bonded terms** — same treatment per bond, angle and dihedral, one row per term, with the term's
   provenance (reference / consensus / geometry-derived) beside it. Filter by term family, sort by
   disagreement. Catches mis-fitted constants, which ring distances alone cannot see.
3. **Shape and volume** — Rg, molecular volume, SASA at the paper's convention (probe 0.191 nm, bead
   radii) and the SAS envelope overlay that `surfaces.py` already draws. Also the ring-expansion factor
   comparison from D5.
4. **Solution behaviour** — only for systems with more than one solute: solute–solute RDF, cluster-size
   histogram, contact map, and the osmotic-pressure series when one exists. Empty with an explanation
   when the loaded runs are single-solute, rather than hidden.

### D3. Labelling is part of the layout, not a caption

Each card carries a `comparison` label — `AA vs CG`, `AA vs reference`, `AA vs target` — rendered as a
badge next to the card title, and each figure carries its convergence line (`n = 2001 frames, 10 blocks,
stderr 0.0031 nm`). A figure without a comparison label or a convergence line is a layout bug. The
reference column is present but visually subordinate (muted text, dashed line) because it is context.

### D4. Pass/fail only where a threshold is declared

`CG mean outside the AA observed range` is a claim our own data supports and may be badged. Nothing is
badged against the reference entry or an absent experimental target: those render as deltas with the word
"context". T3 cards state `blocked: target dataset is metadata_only` and name the registry path.

### D5. The ring-expansion factor is measured, not assumed

Today every ring is dilated by 1.15 about its centre, because the paper's numbers are "15% COG scaled".
We can measure the factor that reproduces *our* AA SASA and molecular volume, per ring, and report it as a
delta from 1.15. Recommendation: measure it, display it, and keep 1.15 as the value actually written into
generated topologies until a change is separately reviewed. Reversal cost: a display-only card.

### D6. No new visual vocabulary

Same palette (`--ink`, `--muted`, `--line`, `--accent`, `--danger`), same card/table/badge idiom, no new
chart library: figures are Plotly (already vendored and served) or SVG produced by the analysis, exactly
like the existing score and SASA figures.

## AA-reference-driven mapping creation

You asked whether CG mapping creation should include an AA reference run and use it algorithmically. My
answer is yes for deriving targets and scoring candidates, and no for inventing partitions.

**Yes, in four places, in increasing ambition:**

1. **Ensemble targets instead of one frame.** A constraint length derived from one frame is a noisy
   estimate of a quantity that fluctuates; the module's own docstring says so. Derive every target as an
   ensemble mean with block stderr over our AA reference, and record the frame count and window in the
   candidate's provenance. This is what makes experiment A (a second AA reference) interpretable.
2. **Measured ring expansion** (D5): a scalar per ring, derived from our AA, reported against 1.15.
3. **Candidate scoring across an admissible set.** The recognizer is connectivity-based today, which is
   good: it cannot overfit a trajectory. But when several chemically admissible partitions exist, an AA
   reference can rank them. The honest criterion is not "which one matches the reference's numbers" (that
   is T2) but "which one's CG model best reproduces the AA ensemble it was derived from". Two levels:
   cheap — ring-chord and bead-position fidelity plus SASA/volume agreement; principled — the fraction of
   AA covariance the mapping explains (a linear mapping-quality measure: project the AA fluctuation
   covariance onto the CG bead coordinates and report the residual). Recommendation: implement the cheap
   level first, and treat the covariance score as its own task with its own test, because a score that
   ranks mappings is a claim, not a display.
4. **Fit/evaluate split as the anti-overfitting discipline.** Targets fitted on one AA reference are
   evaluated on an independent one. A candidate whose targets move inside their own error bars is stable;
   one whose targets move outside them is fitted to a trajectory. This is the paper's own sampling
   discipline (at least 200 ns, and the DDM calibration note already warns that the 10 ns reference was
   never shown to be converged).

**No, in two places, and this is the part worth being firm about:**

1. **Do not let the trajectory choose bead boundaries freely.** `SP1r`, `SP4r`, `SN6` and their relatives
   are calibrated bead types: their nonbonded parameters were fitted for a fragment of a particular size
   and polarity composition. A partition outside the paper's convention leaves the calibrated domain, and
   the generated topology would then be a set of numbers whose meaning is unknown. The admissible set is
   the one the types admit — in the sucrose case, exactly one partition, which is why the sweep mattered.
2. **Do not fit a mapping to a single trajectory and call it validated.** One AA run gives one estimate;
   the report must say which run produced each target, and a target derived from one run must be labelled
   as such wherever it is shown.

## MD experiments, with their setup

Ordered by cost per unit of information, not by ambition. Measured rates: the AA reference here runs at
1568.9 ns/day for this system (200 ns in 3 h 04 min, run `03875cf39790`); CG throughput for Martini is
unmeasured and is the first thing a CG experiment must establish.

**E1. A second, independent AA reference** (~3 h). Same molecule and force field, different seed, and a
different box edge if the protocol allows. Check: ring distances and bonded distributions agree with the
first reference within their block errors. If they do not, every T1 comparison downstream is comparing CG
with noise. Needs no new code; it is a queue with different settings.

**E2. CG geometry at paper scale** (hours; measure first). Setup: our mapping consumed by a CG run long
enough to sample — the existing profile is 10/50 ps, so 200 ns is a new profile (`cg-geometry-200ns`) or
longer durations in the form. Martini water `W`, the registry's temperature, 20-30 fs timestep, 10 ps
frames. Deliverable: card 1 and card 3 of the new tab, populated. Preceded by a 10 ns scouting run to
measure CG ns/day on this box.

**E3. Transferability across molecules** (cheap, and it needs no new system). The same bead types inside
sucrose, maltose and trehalose, each with its own AA reference and CG run; per-bead distributions compared
across the three. This is the paper's own disaccharide transferability check and the cheapest test of
whether our type assignment is chemistry or coincidence.

**E4. Osmotic pressure series** (CG: days; AA: weeks). Setup, matching `validation/osmotic.py`'s existing
contract: 0, 0.5, 1.0, 1.5, 2.0 and 2.5 molal; a box sized so the xy area is large and the solute slab
thin in z; solute count from the target molality and the water mass; flat-bottomed restraint on the solute
centre of mass; semiisotropic pressure coupling with the z degree of freedom decoupled; osmotic pressure
= mean restraint force / xy area; 500 ns per condition, so 3 µs per molecule. The missing piece is a
concentration-series system builder — this is the largest single item in the plan and it should be its own
task sequence, not a step inside one.

**E5. Water-to-octanol transfer free energy.** Setup, matching `validation/transfer.py`: 19 non-uniform λ
windows (`0.0 … 1.0`, the canonical list is in that module), soft-core LJ, NpT, BAR with uncertainty, both
solvent legs. Martini 3's 1-octanol is available locally (`OCO` in
`resources/templates/small_mols_fast_forward/4_CG_sim/inputs/martini_v3.0.0_solvents_v1.itp`, three beads);
no CHARMM36 tree in this checkout ships an octanol topology, so an AA leg needs one added or the check
stays CG-versus-experiment. Budget: CG ≈ 200-400 ns for both legs (hours); AA ≈ 400-800 ns (roughly 6-12
days at the measured rate). One molecule, one check.

## Metrics and thresholds

No absolute threshold is invented. The two comparisons with an internal reference have one:

- `inside the AA range`: the CG mean lies within the AA observed range for that scalar.
- `inside the AA spread`: the CG mean lies within the AA mean ± 2 block standard errors.

Both are computed from our own data, so both may be badged. Everything else is a delta with units.

## Gaps that block evidence, stated as such

- `resources/validation/carbohydrates/targets-v1.json`: glucose, sucrose, trehalose and maltose are all
  `metadata_only` with empty `targets` arrays, so T3 cannot complete. Entering values with citations is a
  separate decision with its own review.
- No AA octanol topology (E4).
- No concentration-series system builder (E3).
- No CG profile long enough to sample geometry (E2).
- The AA reference used for targets is 200 ns; convergence is not demonstrated until E1 exists.

## Review questions, and their answers

The draft was reviewed and accepted as drawn on 2026-09-29, so the recommendations below are the answers:
one new tab plus the run-card line; card 4 visible-but-empty; badges for the two internal claims only; the
expansion factor measured but not applied; candidate scoring restricted to the admissible set; and the
experiment order E1 → E2 → E3 → E4 → E5. The questions are kept because they are the record of what was
asked, and any of them can be revisited.

1. **D1**: a new Mapping Validation tab plus a line on the run card, or all four cards inside CG Bead
   Assignment? Recommended: the tab.
2. **D2 card 4**: keep the solution-behaviour card visible-but-empty for single-solute runs, or omit it
   until a concentration series exists? Recommended: visible.
3. **D4**: is "inside the AA observed range" a badge you want, or would you rather see only the numbers?
   Recommended: keep the badge.
4. **D5**: measure and display the ring-expansion factor against our own AA, without changing the 1.15
   written into topologies? Recommended: yes.
5. **AA-reference-driven mapping**: is the admissible-partition restriction (no free bead boundaries) the
   line you want drawn, or do you want the covariance-scored search over *chemically plausible* boundaries
   as an explicit later goal? Recommended: restriction now, covariance score as task C4.
6. **E1-E5 order**: second AA reference → CG geometry → transferability → osmotic pressure → transfer.
   Recommended: as listed.
