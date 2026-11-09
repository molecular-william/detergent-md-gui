# Martini sugar references: sucrose, trehalose, and an AA comparison

Date: 2026-11-09. Research note for `docs/plans/2026-11-09-next-round.md` items 5 and 6 and decisions 5 and 6.
No production code. Everything below is read from the repository and its run records; nothing is a science guess.

## Inventory

### The reference

`references/martini_v3.0.0_sugars_v2.itp` (505 lines, 11,300 bytes), tracked, with
`references/martini_v3.0.0_sugars_v2.source.json`:

```json
{"url": "…/e11f1d31923ba8090779f8601847dbde84e559e4/…/martini_v3.0.0_sugars_v2.itp",
 "commit": "e11f1d31923ba8090779f8601847dbde84e559e4",
 "sha256": "4d29956a77d936cfdad10e8bbdf201cebdaa24a2f5f50688988a1c7bb9ebfc50",
 "paper_doi": "10.1021/acs.jctc.2c00757", "martini_version": 3}
```

It is a **carbohydrate topology**, not a lipid set entry. Fifteen `[ moleculetype ]` blocks: twelve monosaccharides
(`GLC MAN GAL FRUF LFUC LRHA RIBF XYL INO GLA GYN NMC`) and three disaccharides — `LAC`, `SUCR`, `TREH`
(lines 360, 409, 456). The installed copy is at `workspace/dashboard/martini3/martini_v3.0.0_sugars_v2.itp`; that
install is the source a run names in its `inputs` record, and a sugar run also stages a copy in stage 3.

The two disaccharides, as published:

| entry | atoms | residues | physical beads | constraints | inter-residue bond | angles | dihedrals | virtual sites |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `SUCR` | 8 | 1 (A,B,C,VS) and 2 (A,B,C,VS) | 6 | 6 (rings ×3 each) | 1–5, 0.369 nm, k 6200 | 4 (`funct 1`) | 1 (`funct 1`, φ 5°, k 10) | 2 × `TC4` (parents 1,2,3 / 5,6,7) |
| `TREH` | 8 | 1 and 2 | 6 | 6 | 1–5, 0.417 nm, k 9000 | 4 (`funct 1`) | 1 (`funct 1`, φ 5°, k 25) | 2 × `TC4` |

Bead types: residue 1 is `SP1r` (A), `SP4r` (B), `SP1r` (C); residue 2 is `SN6` (A), `SP4r` (B), `SP1r` (C). Masses
are 54/54/54/0. The reference's constraints are rigid (`funct 1`), its inter-residue link is a harmonic bond, and its
angles/dihedrals are `funct 1`. None of this is an experimental measurement; the DOI is citation metadata.

### The molecules

`molecules/Sucrose/` and `molecules/Trehalose/` each hold an AA topology and coordinates from SwissParam (CHARMM36
July 2022, TIP3P), e.g. `MMFF/lig1.itp`, `MMFF/lig1.pdb`, `MMFF/lig1.gro` (Sucrose; Trehalose has the same layout),
plus `MATCH/` files. `metadata.json` says `parameterization: SwissParam`, `force_field: charmm36-jul2022.ff`, and the
caveat that SwissParam does not record the CGenFF version. Neither is a Martini set.

### What the code already does with the reference

- `packages/core/src/dashboard/models/sugars/reference.py` parses the reference (with its one `#ifdef CONST` branch),
  hashes it, and exposes `entry(name)`, `signature(entry)` (residues, bead letters/types, virtual-site parents,
  inter-residue links), `conform(data, entry)` (mapping conformance, no numbers), and
  `parameter_delta(topology_text, entry)` (generated constraint lengths and link values beside the published ones).
- `packages/core/src/dashboard/models/sugars/coords.py:candidate(structure, name)` builds a candidate mapping from
  the AA chemistry: recognized pyranose/furanose rings, COG beads, `TC4` virtual sites, reference residue order when
  the connectivity identifies an entry. It records `reference` (entry, stereochemistry, `unambiguous`,
  `covers_whole_molecule`, …) and warnings; `status: candidate-unvalidated`.
- `packages/core/src/dashboard/models/sugars/topology.py` writes the CG topology. **It adopts only the reference's
  inter-residue linkage stiffness** (6200 sucrose, 9000 trehalose, 11250 lactose) and keeps the length derived from the
  mapped AA geometry; ring constraints are AA COG distances × 1.15; angles/dihedrals are geometry seeds. The module
  says this explicitly: "Constraints/angles/dihedrals are seeded from COG geometry and later refined by FF_inter."
- `packages/core/src/dashboard/execution/adapters/cg.py:shared_inputs` names the reference (and its provenance) in a
  run's `inputs` record when the mapping has `rings`; no stage opens it.
- `packages/core/src/dashboard/models/compositions/topology.py` uses the same reference for CG **compositions**:
  it seeds a composition's head-sugar constraints/bonds from the reference and adds a linkage profile.
- `packages/core/src/dashboard/execution/scripts/sugar_mapping.py` maps an AA trajectory onto any such mapping
  (COG + equal-parent virtual sites, raw and ring-scaled trajectories). It is the one mapper a run and a panel fit
  both call.
- A run whose mapping has `rings` (a sugar, including the fitted run `22075892b606`) carries
  `reference_sugars_v2.itp` and `.source.json` in stage 3; a non-sugar run (e.g. LMNG `67bc79a995d6`) carries neither.
  A consuming run names the installed copy in `inputs` instead.

## How a New-run mapping/topology could use the reference

Three separable options. Only A reads the reference with no new run; B and C need a science decision.

### A. Compare-only (no run)

Given a molecule directory and a candidate mapping, `sugars.reference.conform(candidate, 'SUCR'|'TREH')` says whether
the mapping reproduces the published bead/letter/type/VS/link structure, and
`sugars.reference.parameter_delta(topology, entry)` says how the generated constraint lengths and linkage compare with
the published numbers. This is a static comparison and needs no simulation. It is already enough to answer "is this
mapping the published sugar representation?" but cannot answer "does the reference reproduce the AA ensemble?".

### B. Reference-seeded parameterization (the direct selection the request names)

Create the mapping (saving the candidate), then create the mapping's **current parameterization revision** from the
reference entry rather than from `ff_inter`: write the reference's terms into the run's `B01..` layout, record
`engine: martini-v3-sugars` (or similar) and the reference's sha256/commit/DOI, and let the normal `aa_cg` run consume
it. Stage 3 already has the consume path (`use_parameterization.py`) and leaves the fit out; the run records that it
did not fit, exactly as it does for any parameterized mapping.

Feasible if, and only if, `conform(candidate, entry)` is empty: terms are addressed by residue/letter/type, so a
candidate that differs in bead order, bead type, VS parents or link endpoints cannot receive the reference's numbers.
The mapping's own `topology.py` already writes every representation this needs. What must change is only the *source*
of the current revision and the labels that say where it came from.

Limits, stated plainly:

- The reference's lengths are its own 15%-COG-scaled geometry, not the mapped AA geometry. Substituting them moves the
  run's start off the AA-mapped structure. The existing writer deliberately avoids that (adopts stiffness, derives
  length); a reference-seeded revision would cross that line, and the run would begin by pulling the molecule onto the
  published geometry.
- The published numbers fit the paper's own model and bead types. A mapping that merely satisfies `conform` (same
  layout) has already been placed at AA-derived coordinates; equality of layout is not equality of parameterization.
- `SUCR`/`TREH` are `funct 1` rigid-constraint rings plus one harmonic link; that is a different model class from a
  Fast-Forward fit (`funct 9` dihedrals, harmonic bonds) and the comparison is not like-for-like.
- No experimental validation is claimed anywhere; the reference is a published force-field entry, not a measurement of
  these two AA topologies.
- Phase 4 (sucrose and maltose experimental sources) is deferred by the user; checked-in targets stay
  `availability: metadata_only`.

### C. Martini reference against an AA trajectory

The honest comparison can reuse the existing `aa_cg` machinery:

1. Build/validate the mapping (A), so bead identities match the published entry.
2. Create the reference-seeded current revision (B), so the simulated topology is the reference's.
3. Run the normal `aa_cg` path against the AA reference. It produces `2_mapping/mapped.{gro,xtc}` (the AA trajectory
   on the beads) and `4_CG_sim/prod/lig_CG.xtc` (the reference model's dynamics).
4. Compare through the analyses that already exist: `mapping-consistency` (pairs, terms, displacement),
   `overlap` (per-bead distance-distribution overlap), `surfaces` (SASA), and ff_assess (stage 5) which scores the CG
   trajectory against the AA-mapped reference histograms.

To score against AA without fitting, stage 3 still has to **measure** the AA reference histograms
(`ff_inter -dists -dist-matrix` writes them as a by-product) even if its fitted topology is discarded; stage 5 then
scores the CG trajectory against those histograms. That is the existing `assess.sh` contract; what changes is only
which topology the CG leg simulated.

Limits and boundaries:

- This compares **a model against our own AA trajectory**, not against experiment. The acceptance criterion must say
  so; "the reference agrees with the AA ensemble" is not "the reference is validated".
- The mapped AA trajectory is produced by the same `sugar_mapping.py`; a mapping error shows up as a distribution
  difference, so the mapping's `conform` result must be reported beside the score.
- Fast-Forward cannot compare two existing trajectories directly. It fits from one and scores another; the score is
  Hellinger distance against AA histograms, not a model-vs-model metric. Any model-vs-model claim needs a different
  tool and is out of scope.
- The reference is CG; the AA trajectory is atomistic. The only bridge is the mapping, and the mapping's virtual sites
  (`TC4`) and COG beads are part of the comparison.
- The current UI has no run type for "CG-only from a published reference"; C rides on `aa_cg` + a reference-seeded
  revision. A dedicated run type would be a larger change and is not required by the request.

## What is not decided

The following are the user's science decisions, not the agent's (plan decisions 5 and 6):

1. **Target file and molecules.** Is `martini_v3.0.0_sugars_v2.itp` the intended source for both `SUCR` and `TREH`,
   or is another sugar parameterization expected? The file's `SUCR`/`TREH` entries are the only whole-disaccharide
   entries there.
2. **What a New-run sugar selection creates.** A CG-only run from that parameterization, or a mapping + topology built
   from the AA sugar and compared to it (B, C, or A only)?
3. **Does the resulting run need the mapping comparison and surface analyses?** If yes, it must be an `aa_cg` shape
   (shared AA reference + mapping + CG leg), not a standalone CG job.
4. **Acceptance criterion** for "compare a Martini reference with an AA trajectory": which metric decides it —
   mapping-consistency displacement, per-bead overlap, SASA agreement, ff_assess's Hellinger score, or a combination —
   and what threshold, if any, counts as agreement. No threshold is defensible without a measured baseline.
5. **Whether to adopt reference equilibrium values or only its linkage stiffness.** Today's writer adopts only the
   stiffness and derives lengths from AA. Direct selection implies adopting the reference's whole bonded state; that
   changes the start geometry and needs its own comparison.

## Files that would change (when approved)

- `packages/core/src/dashboard/models/sugars/` — a reference→revision transcript (new function or module) that writes
  the `B01..` layout, plus its conformance gate.
- `packages/core/src/dashboard/models/bonded/parameterizations.py` (or the parameterization store's writer) — a
  revision whose `engine` is the reference and whose provenance is the reference digest.
- `packages/core/src/dashboard/web/routes/runs.py` and the validation feature's mapping panel — the New-run sugar
  selector and the saved-mapping/parameterization wiring.
- `packages/core/src/dashboard/execution/scripts/use_parameterization.py` — accept the reference engine and record it.
- Tests: a `conform` fixture for `SUCR`/`TREH`, a revision round-trip through `use_parameterization.py`, and a
  browser test that the selector only offers a reference for a conforming mapping.
- Docs: `docs/HANDOFF.md` (Lead) and the plan; the science caveats above belong in the run's own record, not only in
  the panel copy.
