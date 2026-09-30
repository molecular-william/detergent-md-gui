# Protein-detergent complexes: our own detergent model, and what the runs show

**Status:** decided 2026-09-30 by the user; this note extends
`2026-09-28-protein-detergent-complex-panel-design.md` rather than replacing any of it. The protocol, the gates
and the claims of that spec stand. Two things are added: which detergent model a build uses, and what a run
records as it goes.

## 1. The detergent is ours, in Martini 3

### Why not `references/martini-ddm.itp`

It is a **Martini 2** model: its bead types are `P1`, `P2`, `P4`, `C1` with bead masses around 44-60, which is
Martini 2's vocabulary. Our protein comes from `martinize2` under Martini 3 (spec §2) and our sugars are mapped
against `martini_v3.0.0_sugars_v2.itp`, so a Martini 2 detergent would put two force-field generations in one box
— a mismatch that no amount of care in the stages can repair. The file stays in `references/` as context, in the
same standing as the sugar reference entries: worth comparing against, not worth simulating.

### What we build instead

The route the sugars already use, with the same labels and the same limits:

| step | what happens | what it costs |
| --- | --- | --- |
| 1 | An **AA reference run** for DDM (`aa_only`), from the packaged `molecules/DDM` tree | one run slot, ~3 h at the measured 1569 ns/day |
| 2 | A **molecule-scoped mapping candidate**: the recognizer handles the glucose head (one hexopyranose ring) and leaves the 12-carbon tail as a draft, which we finish in the CG Bead Assignment editor with Martini 3 bead types | editing, no run slot |
| 3 | A **`draft-smoke` CG run** off that reference, which is what produces our DDM CG topology: `ff_map` maps the trajectory, `ff_inter` fits the bonded terms against the AA reference, `ff_assess` reports the distance score | ~15 min of run slot |
| 4 | The **bead geometry** comes from the same assignment: each bead's centre is the mean of its atoms, which the editor's 3D overlay already draws. Nothing is copied from a reference structure | none |

### What this does and does not claim

- **Claims:** the detergent, the protein and the sugars are all Martini 3; the detergent's bonded terms were
  fitted against a trajectory we ran and can re-derive; the bead assignment is saved, inspectable and reproducible
  from its provenance.
- **Does not claim:** that this detergent model is validated. It carries the same `candidate-unvalidated` label
  the composition and sugar candidates carry, and the run's record says so. A draft model's geometry is an
  execution check, not a parameterisation anyone should publish.
- The recognizer's rules **do not transfer wholesale**: they cover one hexopyranose ring, which is DDM's head. The
  tail is outside their scope and is a deliberate, recorded choice of the person who finishes the mapping — three
  or four `C1`-type beads for twelve carbons, stated in the candidate's notes.

## 2. What a run shows: snapshots

The spec's panel section already promises "the built system after setup and the final snapshot after each
assessment". This generalises that to a **series**, because the question these runs answer is a question about
time: is the micelle forming, around what, and does it stay.

### The series

| name | when | where it comes from |
| --- | --- | --- |
| `placement` | before any dynamics, before solvent | the placed system, which is stage 1's own output |
| `start` | the state the assessment phase actually started from | the assessment stage's input structure |
| `equilibrated` | the end of each equilibration / assessment stage | that stage's final structure |
| `production.<ps>` | through the production and extension trajectories | `gmx trjconv -dump` at fixed time points |

One setting decides the cadence, so two runs' series are comparable by construction: **every 10 ns of production
and extension, capped at 20 frames per stage**, plus the four non-trajectory states above. The cap is what keeps a
900 ns extension from producing a hundred files nobody reads.

### Every snapshot carries the criterion's own numbers

A picture is not evidence, and a gallery that shows eight pretty frames of an aggregate that never formed would be
worse than no gallery. Each snapshot is written together with the numbers the assessment uses — the largest
cluster size, its fraction of the requested aggregation number, the protein contact count, and the contact
distance — computed by **the same function that decides the verdict** (spec §7). One implementation, applied at
every time point, so the gallery is the assessment's time series and cannot disagree with the report.

### Rules

- Snapshot files are **derived**: the trajectory and the stage outputs stay the immutable record, and every
  snapshot records the command that produced it, the time it was taken at, and the source file's checksum. A
  resumed run re-derives them rather than keeping stale ones.
- The panel reads them through the existing viewer and artifact routes — the PDB is written server-side from the
  coordinates, as the Molecule Combination panel does, so the picture cannot disagree with the system.
- Water and ions stay hidden by default, as the spec already says.
- **What a series is not:** evidence of equilibration. The spec's own words — the assessment criteria are proxies
  for aggregate formation — apply to every frame in it.

## 3. Order of work

The critical path avoids idling the run slot:

1. **B7b** — the five remaining stage scripts, including the snapshot outputs above. Needs no detergent model.
2. **The DDM AA reference**, queued once the E3 chain has finished with the slot (~17:00 HKT).
3. **The DDM mapping candidate and its `draft-smoke` CG run.**
4. **B7c** — wire stage 1 to our model: the template names our CG topology, the placement stamps its beads, and
   `system.top` is assembled with the molecule names read from the two `.itp` files.
5. The first end-to-end pdc run on a small system, which is when the series above first has anything to show.

## 4. Open questions

- **Scheduling:** the DDM reference can queue behind the E3 chain (default) or ahead of the trehalose legs. Ahead
  buys the detergent ~3 h and delays the third sugar leg by the same amount; behind costs nothing but a later
  detergent. Default: behind.
- **Cadence:** the 10 ns / 20-frame rule above is a first guess, recorded in the settings where it can be changed
  without touching a stage. The floor that matters is not the interval but that the initial state is always
  recorded, because that is the one a reader needs to judge the placement.
