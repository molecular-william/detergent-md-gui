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

### Why not build it with Fast_Forward's fitting

The obvious cheap route — map the detergent and let `ff_inter` fit its terms — needs the mapped **trajectory**:
the stage script calls `ff_inter -f ../2_mapping/mapped.xtc -s mapped.gro ... -dists -plots`, and the bundled
version's own comment in `fit_topology.sh` says it plainly: *this bundled FF version has no `-itp-only` switch*.
Fitting is a Boltzmann inversion over frames, so without an AA reference run there is nothing to invert. Skipping
the reference therefore does not mean *fitting less carefully*; it means **assembling** the topology from
parameters that already exist in Martini 3.

### What we build instead: assembled from Martini 3 building blocks

The pieces are already in the repository, and `molecules/DDM/BEAD_REFERENCE.md` — written before this decision —
names them and their limits.

| piece | source |
| --- | --- |
| the head's beads | the M3 carbohydrate references (`martini_v3.0.0_sugars_v2.itp`): two glucose rings' worth of `SP4r` / `SP1r` / `TC4` / `SN6` beads, i.e. the same vocabulary the sugar mappings already use |
| the tail's beads | the M3 Bible's CG-SMILES database: dodecane (`DOD`) is **three `C1` beads** |
| the linkage | the glycosidic bond between the reducing-end sugar bead and the first tail bead — a choice, recorded as one, because the building-block database does not decide it for us |
| the bonded terms | `dashboard/models/bonded/generation.py`: parameters looked up from Martini 3 reference `.itp` files by bead-type combination, with its documented fallbacks where a combination is unseen |
| the bead geometry | the assignment itself: each bead's centre is the mean of its atoms |
| the mapping draft | `molecules/DDM/mapping_candidate.ndx` already groups the molecule into nine beads: `TAIL1..TAIL3`, `LINK`, `SUGAR1`, `SUGAR1_OH`, `SUGAR2`, `SUGAR2_OH_A`, `SUGAR2_OH_B` |

What this costs in strength, stated where a reader will see it: **borrowed** parameters are not fitted ones, and a
combination the references do not cover falls back to the generator's placeholder values rather than to a
measurement. So the report must record, per run, which terms were transferred and how many fell back — and the
model keeps the `candidate-unvalidated` label regardless.

### The option that stays open

An AA reference run for DDM is still worth queueing when the slot is free, because it upgrades this model rather
than replacing it: `ff_map` + `ff_inter` would fit the same mapping's terms against a real trajectory, and the two
models are distinguishable in the manifest (which model a run used is recorded). Assembling first is what makes
the pipeline runnable now; fitting later is what makes the detergent defensible.

### What this does and does not claim

- **Claims:** the detergent, the protein and the sugars are all Martini 3; the bead assignment is saved,
  inspectable and reproducible from its provenance; every bonded term records which reference it came from, and
  every fallback is counted rather than hidden.
- **Does not claim:** that this detergent model is validated, or that its terms were fitted. It carries the same
  `candidate-unvalidated` label the composition and sugar candidates carry, and the run's record says so. DDM's
  head is two *linked* sugar rings with an alkyl glycosidic linkage, and `BEAD_REFERENCE.md`'s own warning stands:
  substitution changes hydroxyl and ether environments, so copying two isolated glucose models unchanged is not
  justified.
- The recognizer's rules **do not transfer wholesale**: they cover hexopyranose rings, which is DDM's head — the
  same case the sugar work already exercised with maltose (two rings, linkage letters AB). The 12-carbon tail is
  outside their scope and is a deliberate, recorded choice: three `C1` beads for twelve carbons, from the M3
  Bible's dodecane entry, stated in the candidate's notes.

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
2. **The DDM model, assembled**: finish the mapping candidate from `mapping_candidate.ndx`, take the head's beads
   and terms from the M3 carbohydrate references and the tail's from the M3 Bible's dodecane entry, and let
   `dashboard/models/bonded/generation.py` supply what the references cover — counting every fallback. No run
   slot needed.
3. **A short CG smoke run** of the detergent alone: stability, plus bead distances against the AA structure, which
   is the cheapest evidence that an assembled model is not nonsense.
4. **B7c** — wire stage 1 to it: the template names our CG topology and coordinates, the placement stamps the
   mapped beads, and `system.top` is assembled with the molecule names read from the two `.itp` files, with
   `grompp` accepting the pair as the test.
5. The first end-to-end pdc run on a small system, which is when the series above first has anything to show.
6. *(Optional, later, when the slot is free)* DDM's AA reference, then `ff_map` + `ff_inter` to fit the same
   mapping's terms — the upgrade from borrowed to fitted parameters, distinguishable in the manifest.

## 5. What the two references in `references/` support (read 2026-09-30)

`acs.biochem.0c00183.pdf` — "How Do Branched Detergents Stabilize GPCRs in Micelles?" (Lee et al.) — is an
**atomistic** (CHARMM) study of A2A/β2 adrenergic receptors in LMNG, DMNG, OGNG and DDM. It is not a parameter
source for a Martini 3 build, and it is not used as one. What it does give:

- **Scale.** A receptor-detergent complex there holds **192 DDM molecules** (96 for the branched detergents), built
  with CHARMM-GUI and sampled as five 250 ns runs. Our `aggregation_number` default of 12 is a smoke-test number,
  not a physical one, and the panel should say so rather than let a 12-detergent "micelle" read as a result.
- **Vocabulary for judging packing.** They ask the question with *radial density profiles of the head and tail
  groups*, the *eccentricity* of the complex, the *density of tail carbons within 4 Å of a receptor residue*, and
  the *water density within 3.5 Å of the receptor*. Our §7 criterion is coarser than that on purpose (it is a
  contact graph, and it is cheap enough to run on every frame), but these four are candidate additions to the
  numbers a report carries, and they are what a reader would compare us against.

`ct2c00757_si_001.pdf` — the supporting information of "Martini 3 Coarse-Grained Force Field for Carbohydrates"
(Grünewald, Punt et al.) — is the source of the sugar parameters we already use (`martini_v3.0.0_sugars_v2.itp`),
and it carries the entries our DDM head needs: `a-D-GLC`, `b-D-GLC`, and the note that the mapping's `TC4` central
site is part of the model. A maltose head is two of those rings, which is the case our recognizer already handles
(it is what the saved maltose candidate is), so the head's beads and bonded terms have a published source rather
than an analogy.

Neither reference decides anything in this note; both bound what a run of ours can be compared with.

## 6. Open questions

- **Scheduling:** no longer blocking. The detergent is assembled from Martini 3 building blocks, so the E3 chain
  keeps the run slot, and DDM's AA reference becomes an optional upgrade rather than a prerequisite.
- **Cadence:** the 10 ns / 20-frame rule above is a first guess, recorded in the settings where it can be changed
  without touching a stage. The floor that matters is not the interval but that the initial state is always
  recorded, because that is the one a reader needs to judge the placement.
- **Aggregation number:** the default is a smoke-test number. A real DDM complex is two orders of magnitude larger
  (see §5), so a production-meaning setting belongs in the run record with its source, not in the defaults.
