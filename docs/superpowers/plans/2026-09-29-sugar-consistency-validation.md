# Sugar mapping consistency validation, and the surface for it

Design: `docs/superpowers/specs/2026-09-29-sugar-consistency-validation-design.md`.
Layout draft: `docs/design/prototypes/sugar-consistency-20260929.html` (for review, decisions D1-D6).

## Why

We can currently say how far our derived geometry is from the pinned reference entry, and we cannot say
anything about the model we actually run. On 2026-09-29 the sucrose run `03875cf39790` measured a 16%
shortfall on the glucose ring's A–B pair against the reference's `SUCR` entry, and the obvious explanation
— that our fragment split assigns different atoms — was refuted: of the ten arc cuts of the glucose ring's
atoms, exactly one partition survives the reference's own bead types, and it is the one the recognizer
already produces. What nobody has measured is the CG side. There is also no CG run in this workspace at all
right now, so the comparison has no right-hand term yet.

The repository's validation machinery is aimed at the other question (T3, experimental targets), and every
registry dataset is `metadata_only`, so it cannot complete. What is missing is the tier that needs no
citation: does a CG run of our mapping reproduce our own AA ensemble.

## Current state (verified 2026-09-29)

- `dashboard/analysis/sugar_ensemble.py` measures ring-pair distances over an AA-only run's own inputs
  (`stages/07_reference/lig.{gro,xtc}`, the run's copy of `molecule.itp`) and compares them with
  `models/sugars/reference.entry(entry)`. Pure arithmetic plus a thin trajectory shell; 11 unit tests.
- The CG stage table (`dashboard/execution/adapters/cg.py:33-62`) uses the ENAP-era layout inside a
  consumer's `stages/`: `1_AA-reference/prod/lig.xtc`, `2_mapping/mapped.{gro,xtc}`,
  `3_initial_CG/{final_itp}`, `4_CG_sim/prod/lig_CG.{gro,tpr,xtc}`, `5_assessment/`, `6_SASA/`.
  So the CG side is readable today, at known paths, once a CG run exists.
- An AA-only run uses the newer layout: `stages/07_reference/lig.xtc` (run `03875cf39790`). Two layouts,
  one of them zero-padded. A resolver is needed, and it must not guess: a path that is absent is reported.
- `dashboard/analysis/runs/observability.py:232` (`unparameterized_observables`) already parses an ITP's
  bonds/angles/dihedrals and computes distributions absent from the fitted topology — but it is hard-coded
  to `2_mapping/mapped.*` and `3_initial_CG/DDM_initial.itp`, i.e. to the DDM run, and it measures the
  **mapped AA** side only.
- `dashboard/analysis/runs/surfaces.py` already implements the paper's surface convention: `PROBE = .191`,
  bead radii, a marching-cubes SAS envelope, and an alignment on physical beads (`align`).
- `dashboard/analysis/validation/geometry.py:9` (`block_summary`) is the convergence arithmetic.
- `dashboard/analysis/worker.py:98` registers analysis kinds; `dashboard/web/routes/analyses.py` serves
  them. A new kind is added there, not in a route of its own.
- The tab bar is `dashboard/web/templates/dashboard.html:19-26` (six tabs), panels are
  `<section id=... role="tabpanel">`, and `main.js` dispatches mounts by id.
- Live workspace: two runs, both `aa_only`, both completed. No CG run.

## Design

1. **One analysis, four primitives.** A new analysis module computes the comparison and publishes one
   immutable result per (mapping, AA source, CG consumer) triple, as the other analyses do
   (`analyses/<kind>/<request-key>/<attempt-id>/`). The primitives are distribution comparison, target
   comparison, structural displacement and convergence (spec, "The comparison primitives").
2. **A layout resolver** for the two stage layouts, used by every new reader, reporting absent paths by
   name instead of falling back.
3. **The CG side is measured, not inferred.** CG bead centres and bonded terms come from the CG run's own
   trajectory and topology, never from hand-mapped AA frames. This is the whole point of the exercise.
4. **Every number carries its comparison and its convergence** (spec D3). No bare figures.
5. **No thresholds invented** (spec D4): only `inside the AA range` and `inside the AA spread`, both
   computed from our own data, may be badged.
6. **The reference stays context** (spec D2 card 1): a muted dashed line and a delta column, never a
   pass/fail.
7. **AA reference drives targets and scoring, not partitions** (spec, "AA-reference-driven mapping
   creation"): ensemble targets, a measured ring-expansion factor reported against 1.15, and candidate
   scoring restricted to the chemically admissible set the bead types allow.
8. **One new tab plus a line on the run card** (spec D1). The tab is drafted before it is built; the draft
   is signed off first.

## Phases

Order matters: A produces the numbers, B (approval of the draft) unlocks the surface, C and D are the
science, E is the paperwork. Each task is one commit.

### Phase A — the comparison, headless

**Task A1: a resolver for the two stage layouts.**
Objective: one function that answers "where is this run's AA trajectory / CG trajectory / CG topology",
for the AA-only layout and the consumer layout, raising with the path names when absent.
Files: create `dashboard/analysis/runs/layout.py`; test `tests/dashboard/unit/test_run_layout.py`.
Test: build both layouts under `tmp_path` (a `stages/07_reference/lig.xtc` tree and a
`stages/1_AA-reference/prod/lig.xtc` + `stages/4_CG_sim/prod/lig_CG.xtc` tree); assert both resolve; assert a
tree with neither raises `ValueError` naming the candidates tried.
Implement, run the test, run `ruff check dashboard/analysis/runs/layout.py`, commit.

**Task A2: the CG-side measurement.**
Objective: per-bead-pair mean distances over a CG trajectory, using the CG topology's own atom order and
the mapping snapshot for bead identities — the mirror of `sugar_ensemble.run`'s trajectory loop.
Files: create `dashboard/analysis/runs/consistency.py` (pure functions first:
`bead_pairs_from(mapping)`, `summarise_pair_distances(samples)`); test
`tests/dashboard/unit/test_consistency_arithmetic.py`.
Test: synthetic bead coordinate arrays; assert the six constrained pairs are the ones the mapping's rings
declare, that a missing bead is reported rather than skipped silently, and that the summary carries mean,
std, min, max and count. Then the thin shell over a CG trajectory in
`tests/dashboard/integration/test_consistency_runs.py` using the fixture workspace.
Run, `ruff check`, commit.

**Task A3: AA against CG, per pair, with convergence.**
Objective: the report body — for each constrained pair, AA mean ± block stderr, CG mean ± block stderr,
delta in %, `inside_range` and `inside_spread` booleans, frame counts, windows, and the reference value as
a separate context field.
Files: extend `dashboard/analysis/runs/consistency.py`; test
`tests/dashboard/unit/test_consistency_report.py`.
Test: hand-built summaries with known values assert each field, including a pair where the CG mean is
outside the AA range and one where it is inside; assert a reference value never sets a boolean.
Run, `ruff check`, commit.

**Task A4: bonded terms, AA-mapped against CG-simulated.**
Objective: per-term distributions and their agreement, with each term's provenance, for bonds, angles and
dihedrals.
Files: create `dashboard/analysis/runs/bonded_terms.py` (an ITP term reader shared by both sides — lift the
parsing out of `observability.unparameterized_observables` rather than duplicating it); test
`tests/dashboard/unit/test_bonded_terms.py`.
Test: a small ITP with one bond, one angle, one dihedral; assert the term sets, that a term present in one
topology and absent in the other is reported as absent rather than scored, and that the metric is the
modified Hellinger score Fast_Forward uses plus Wasserstein in native units.
Run, `ruff check`, commit. Note: lifting the parser means `observability.py` must keep working — its test
(`tests/dashboard/integration/test_operations.py:224`) is the guard.

**Task A5: structural displacement.**
Objective: per-bead displacement and RMSD between the mapped AA bead centres and the CG bead centres, after
a rigid-body fit on physical beads, reusing `surfaces.align`.
Files: extend `dashboard/analysis/runs/consistency.py`; test
`tests/dashboard/unit/test_consistency_displacement.py`.
Test: a constructed case where one bead is displaced by a known vector; assert the per-bead displacement
and the RMSD in nm.
Run, `ruff check`, commit.

**Task A6: register the analysis and publish its result.**
Objective: the analysis runs as an immutable attempt with the standard layout and provenance.
Files: modify `dashboard/analysis/worker.py:98` (register the kind), `dashboard/analysis/metadata.py`
(one `DESCRIPTIONS` entry per the existing pattern), and only if the route needs it,
`dashboard/web/routes/analyses.py`.
Test: `tests/dashboard/integration/test_consistency_api.py` — queue the analysis for a fixture triple,
assert 200, assert the published result carries the request key, the attempt id and the source hashes.
Run, `ruff check`, full fast tier, commit.

### Phase B — the surface (draft signed off 2026-09-29)

**Task B1: panel section 1 (ring and constraint geometry)** — route to fetch a published attempt, panel
that renders the per-pair overlay and table, `tests/dashboard/browser/test_mapping_validation_browser.py`
reading the resolved series rather than the payload (per the dashboard skill's rule 2).
**Task B2: the run-card line** — one line, only when the quadruple resolves, linking with the triple
preselected.
**Task B3: cards 2 and 3** — bonded terms and shape/volume, reusing `surfaces.generate`.
**Task B4: card 4** — solution behaviour, visible-but-empty with its reason until a concentration series
exists.
**Task B5: the tab** — wire the id, the mount and the browser tests in one commit (an unwired id falls
through to the mapping editor and reads as a broken tab).

### Phase C — AA-reference-driven mapping

**Task C1: ensemble targets.** Constraint lengths and, later, bonded targets derived as ensemble means with
block stderr over a named AA run; the candidate records the run id, frame count, window and stderr.
**Task C2: measured ring-expansion factor.** Per ring, the factor that reproduces our AA SASA and volume,
reported as a delta from 1.15; the topology writer keeps 1.15 until a separate review changes it.
**Task C3: admissible-set scoring.** Score the chemically admissible partitions of a ring by CG-vs-AA
fidelity (cheap level: chord fidelity, bead displacement, SASA/volume). Report, do not auto-select.
**Task C4: covariance score.** The fraction of AA fluctuation covariance the mapping explains. Its own task
because a score that ranks mappings is a claim; it needs its own test and its own wording in the panel.
**Task C5: fit/evaluate split.** Targets from run 1, evaluation on run 2, and a flag when a target moves
outside its own error bars.

### Phase D — the experiments

**Task D1 (E1): a second AA reference.** Same molecule, same force field, different seed; queue it, then
compare it against `03875cf39790` with the Phase A machinery. Deliverable is a statement, in the panel and
in the notes, that the targets either agree within their errors or do not.
**Task D2 (E2): a CG run long enough to sample.** First a 10 ns scouting run to measure CG ns/day on this
box, then a `cg-geometry-200ns` profile (the existing profile is 10/50 ps). This is what gives Phase A's
report a right-hand term.
**Task D3 (E5): transferability across molecules** — the same bead types in sucrose, maltose, trehalose.
**Task D4 (E3): the concentration-series builder.** Its own sequence: box sizing for a thin solute slab,
solute count from molality and water mass, flat-bottomed COM restraint, semiisotropic coupling with z
decoupled, force extraction, then the 0-2.5 molal series at 500 ns per condition. Largest item here; do not
start it inside another task.
**Task D5 (E4): water-to-octanol transfer.** CG first (`OCO` is in
`resources/templates/small_mols_fast_forward/4_CG_sim/inputs/martini_v3.0.0_solvents_v1.itp`), 19 windows
from `validation/transfer.py`, both legs; an AA leg needs an octanol topology that no CHARMM36 tree here
ships, so it is a separate decision.

### Phase E — docs

`docs/PROJECT_GUIDE.md` (the new tab and the analysis kind), the operations note (how to run a consistency
check), `AGENTS.md` (the standing goal: internal consistency, reference as context), and `README.md`'s
roadmap line for the validation panel.

## Acceptance

- A published consistency result for one molecule, mapping, AA run and CG run, reproducible from the run
  directories alone.
- Every figure in the surface carries a comparison label and a convergence line; a test asserts a figure
  without them is not rendered.
- No badge is produced by a reference or experimental comparison, only by the two internal claims.
- `dashboard/.venv/bin/python -m pytest -m 'not browser and not slow' -q` passes; `ruff check` on touched
  files exits 0. Measure the tier's own count when committing, do not copy a number from here.
- The surface's browser tests read the resolved series, not the request.

## Out of scope

- Replacing 1.15 in generated topologies (display-only until separately reviewed).
- Auto-selecting a mapping from a score.
- Entering experimental targets into the registry.
- Any threshold for "good enough" other than the two internal claims.
- Membrane, glycolipid and oligomer work (the paper's Sections 3.2-3.4); noted, not scheduled.
