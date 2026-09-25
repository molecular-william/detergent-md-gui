# Sucrose Martini Reference Mapping Implementation Plan

> **For agentic workers:** execute task-by-task, TDD, one commit per task. Steps use `- [ ]`.

**Goal:** Make the automatic CG mapping candidate reproduce the pinned Martini 3 reference
carbohydrate mapping — bead partition, bead types, virtual sites, residue layout and inter-residue
connectivity — derived from an atomistic structure. Sucrose (`SUCR`) is the first and only target.

**Architecture:** The reference topology `references/martini_v3.0.0_sugars_v2.itp` becomes a parsed,
hash-pinned table that acts as the oracle. Recognition is extended to cover the ring classes sucrose
needs (furanose/ketose), a residue matcher identifies which reference entry a structure's connectivity
corresponds to, the existing fragment partition is validated against that entry's signature, and the
generated topology is written in the reference's two-residue layout. Where the derived partition and
the reference disagree, the reference wins and the disagreement is recorded, never silently absorbed.

**Tech Stack:** Python 3.12, networkx, numpy, MDAnalysis (angles/dihedrals), pytest; Flask dashboard
for the candidate route; no new dependencies.

**Evidence (measured on this checkout, 2026-09-25, not inferred):**

- `identify_hexoses(Sucrose)` finds **1** ring (the glucopyranose). `SUCR` has **two** residues.
- The current sucrose candidate is `S1A SP1r / S1B SP4r / S1C SP1r / S1VS` plus
  `TAIL1 P1 4 atoms [OCCO]`, `TAIL2 P1 4 atoms [CCOC]`, `TAIL3 TP1 1 atom [O]`, `TAIL4 TP1 2 atoms [CO]`.
  `TAIL1`/`TAIL2` are chunks of the fructofuranose ring and `TAIL3` is a lone oxygen atom.
- `identify_hexoses(Maltose)` finds **2** rings and yields `S1A SP4r / S1B SP1r / S1C SP1r` +
  `S2A SN6 / S2B SP4r / S2C SP1r`, which is exactly the reference `LAC` signature. Maltose needs **no**
  recognition change; the earlier report that it produced `TAIL` names does not reproduce here.
- The reference file's sha256 equals the pinned value in
  `references/martini_v3.0.0_sugars_v2.source.json`: `4d29956a77d936cfdad10e8bbdf201cebdaa24a2f5f50688988a1c7bb9ebfc50`.
- `sugars/topology.py` writes every bead as `B{index:02d}` inside **one** residue, so the reference's
  per-residue `A/B/C/VS` layout and two residue numbers are not reproduced in the exported `.itp`.

**Reference `SUCR` entry (the target, verbatim from the pinned file):**

| residue | bead | type | mass | role comment |
|---|---|---|---|---|
| 1 | A | SP1r | 54 | glycosidic bead |
| 1 | B | SP4r | 54 | |
| 1 | C | SP1r | 54 | |
| 1 | VS | TC4 | 0 | |
| 2 | A | SN6 | 54 | receiving bead |
| 2 | B | SP4r | 54 | |
| 2 | C | SP1r | 54 | |
| 2 | VS | TC4 | 0 | |

Constraints: res1 `1-2 0.305`, `1-3 0.385`, `2-3 0.336`; res2 `5-6 0.376`, `5-7 0.468`, `6-7 0.359`.
Linkage bond `1-5` length 0.369, fc 6200. Angles `2-1-5`/135/25, `1-5-6`/71/60, `1-5-7`/73/73,
`3-1-5`/65/40. Dihedral `2-1-5-7` 5/10. `virtual_sitesn` 4←1,2,3 and 8←5,6,7.

---

## Decisions

**D1 — Scope of "reproduces the reference".** Conformance covers the *mapping*: number of residues,
bead count per residue, bead types, per-bead heavy-atom membership (partition), virtual sites and their
parents, and the inter-residue connectivity. Equilibrium numbers (constraint lengths, bond fc, angle and
dihedral values) are **not** copied from the reference by default: the paper derives them as mean
all-atom COG distances scaled uniformly by 1.15, the candidate already computes exactly that from the
local AA source, and constraints that disagree with the starting coordinates are a LINCS hazard. The
reference's numbers are reported as a per-term delta instead. A `reference_lengths` switch can adopt
them verbatim for comparison runs. **This is the one decision worth the user's attention.**

**D2 — Identification is connectivity-based, stereochemistry is not perceived.** Connectivity uniquely
selects `SUCR` among the file's disaccharides (one pyranose + one furanose, linked anomeric-carbon to
anomeric-carbon). For monosaccharides, connectivity cannot separate `GLC`/`MAN`/`GAL`; those share a
bead-type signature, so the partition still conforms and the stereo-dependent numbers stay
geometry-derived. The candidate records which entry was matched and whether stereochemistry was
resolved.

**D3 — Internal bead names stay unique; exported names follow the reference.** Bead names remain
`S{residue}{letter}` internally (`S1A`, `S2C`, `S1VS`) because the schema, the editor and the topology
builder key on names, and the reference's bare `A/B/C` repeat across residues. The *writer* emits the
reference's layout: atom names `A/B/C/VS` with the residue number taken from the bead's `residue` field.

**D4 — Unsupported sugar classes refuse rather than draft.** A structure whose rings are recognised but
cannot be mapped by a template (5-rings without an exocyclic hydroxymethyl on the anomeric carbon, i.e.
`RIBF`-like; 6-deoxy, uronic, N-acetyl, inositol) currently falls through to an arbitrary BFS chunker
that produced a lone-oxygen bead. That path becomes an explicit refusal naming the ring and the reason.
Genuinely non-sugar molecules keep the existing generic `BEADnn` graph draft.

**D5 — The reference is an oracle, and a conformance failure is a bug or a recorded deviation.** No
silent pass: `conform()` returns a list of issues, the candidate stores the verdict in its provenance,
and the fidelity tests assert an empty issue list for sucrose.

## Not doing (YAGNI, and to keep this reviewable)

- Stereochemistry perception from 3D geometry (needs a CIP implementation; not required for sucrose).
- Per-class templates for deoxy/uronic/N-acetyl/inositol sugars, and `RIBF`/`XYL` furanoses.
- Adopting the reference's equilibrium numbers as the default (see D1).
- Renaming the internal bead-name convention (see D3) or touching the editor's duplicate-name handling.

---

## Tasks

### Task 1: Reference table parser

**Objective:** A hash-pinned, structured view of the reference topology, with the `#ifdef` branch
handled, so later tasks can compare against it.

**Files:** create `dashboard/models/sugars/reference.py`; create
`tests/dashboard/unit/test_sugar_reference.py`.

- [ ] Write the failing test: entries are keyed by moleculetype; `SUCR` has 2 residues of 3 physical
      beads + 1 `TC4`; its linkage bond is `(1, 5)` length 0.369 fc 6200; `GLC` constraints are
      `0.380/0.470/0.396`; `NMC` takes the `#ifndef CONST` branch (bonds present, constraints absent);
      the file's sha256 equals the pinned value in `source.json`.
- [ ] Run it and watch it fail on the missing module.
- [ ] Implement `entries()`, `entry(name)`, `signature(entry)`, and the section parser.
- [ ] Run the test to pass; run the fast tier; commit.

### Task 2: Furanose and ketose recognition

**Objective:** Recognise the fructofuranose ring and emit it in the same `carbons` convention the
pyranose path already uses, so the existing partition code needs no change.

**Files:** modify `dashboard/models/sugars/recognition.py` (add `identify_furanoses`, share the ring
walk); modify `dashboard/models/sugars/__init__.py` (export); create
`tests/dashboard/unit/test_sugar_recognition_furanose.py`.

- [ ] Write the failing test: `identify_furanoses(sucrose)` finds exactly one 5-ring whose ring oxygen
      neighbours are the anomeric carbon (bearing an exocyclic O **and** an exocyclic C) and a
      hydroxymethyl carbon; `carbons` is
      `[exocyclic CH2 on the anomeric carbon, anomeric, ..., c5, exocyclic CH2 on c5]` — six carbons in
      the pyranose's slot order.
- [ ] Run it and watch it fail.
- [ ] Implement; keep `identify_hexoses` behaviour byte-identical for maltose.
- [ ] Run the unit tier and the fast tier; commit.

### Task 3: Residue identification against the reference

**Objective:** Say which reference entry a structure is, from connectivity alone, and in which residue
order.

**Files:** create `dashboard/models/sugars/identification.py`; create
`tests/dashboard/unit/test_sugar_identification.py`.

- [ ] Write the failing test: sucrose → entry `SUCR`, residue 1 = the furanose, residue 2 = the
      pyranose, linkage carbons (anomeric of res1) and (anomeric of res2), `stereochemistry: 'unresolved'`;
      maltose → an entry whose signature matches `LAC` (resolved by linkage: 1→4), flagged as an analogy
      rather than a direct entry; a non-sugar structure → `None`.
- [ ] Run it and watch it fail.
- [ ] Implement the fingerprint and matcher (ring sizes, linkage carbons, per-ring substituent counts).
- [ ] Run the tests and the fast tier; commit.

### Task 4: Reference-driven residue layout and the linkage

**Objective:** Emit the reference's residue structure — two residues, per-residue bead letters, the
linkage bond between the two linkage beads, one virtual site per ring.

**Files:** modify `dashboard/models/sugars/coords.py` (`candidate`, and the fallback below it);
create `tests/dashboard/unit/test_sucrose_reference_candidate.py`.

- [ ] Write the failing test: for sucrose the candidate has 8 beads — two residues of
      `A SP1r / B SP4r / C SP1r / VS TC4` and `A SN6 / B SP4r / C SP1r / VS TC4`; the bridge oxygen
      belongs to residue 1's `A` fragment; heavy atoms per bead are `4/4/4` and `3/4/4`, summing to 23;
      the connection list contains exactly one inter-residue edge and it joins the two `A` beads.
- [ ] Run it and watch it fail with the current `TAIL` output.
- [ ] Implement; the type rules already reproduce the reference once the partition is right — do not
      rewrite them, extend the fragment letters only if the test disagrees.
- [ ] Run the tests and the fast tier; commit.

### Task 5: Role-based naming for what is left over

**Objective:** `TAIL` means an apolar carbon chain, or it is not used. No single-atom beads.

**Files:** modify `dashboard/models/sugars/coords.py` (remainder classifier); create
`tests/dashboard/unit/test_sugar_remainder_naming.py`.

- [ ] Write the failing test: a pure-carbon acyclic chain → `TAILn`; a chain containing O or N → `LINKn`;
      a component with a single heavy atom is merged into its neighbour, never emitted as a bead; a
      whole-molecule saccharide has no `TAIL` name; `DDM` (sugar head plus C12 chain) keeps `TAILn` for
      the chain.
- [ ] Run it and watch it fail.
- [ ] Implement, keeping names stable and collision-free.
- [ ] Run the tests, the mapping-workspace integration tests and the fast tier; commit.

### Task 6: Reference-style topology output

**Objective:** The generated `.itp` reads like the reference: per-residue `A/B/C/VS` atom names, residue
numbers from the bead's `residue` field, one `virtual_sitesn` per ring.

**Files:** modify `dashboard/models/sugars/topology.py`; create
`tests/dashboard/unit/test_sugar_topology_names.py`.

- [ ] Write the failing test: the sucrose topology has `[ moleculetype ]` as one molecule, two distinct
      resnr values, atom names `A`, `B`, `C`, `VS` in each, and each `virtual_sitesn` line naming its own
      residue's three physical beads.
- [ ] Run it and watch it fail.
- [ ] Implement; keep the constraint/angle/dihedral generation unchanged.
- [ ] Run the tests, `tests/dashboard/unit/test_carbohydrate_topology_modes.py`, the fast tier; commit.

### Task 7: Conformance verdict and the parameter delta

**Objective:** "Matches the reference" becomes a reported verdict plus a per-term delta, not a claim.

**Files:** modify `dashboard/models/sugars/reference.py` (add `conform`, `parameter_delta`); modify
`dashboard/models/sugars/coords.py` (record `reference` in provenance); modify the candidate route if a
field is needed; create `tests/dashboard/unit/test_sugar_conformance.py`.

- [ ] Write the failing test: `conform(sucrose_candidate, 'SUCR')` returns no issues; deleting a bead,
      changing a type, or moving the linkage edge each produces a specific issue naming the bead;
      `parameter_delta` reports per-constraint reference vs generated lengths for sucrose.
- [ ] Run it and watch it fail.
- [ ] Implement.
- [ ] Run the tests and the fast tier; commit.

### Task 8: Documentation and the end-to-end gate

**Objective:** The workflow note, the validation note and the README roadmap describe what is now true,
and one test asserts the whole path from the shipped structure to the reference-conformant candidate.

**Files:** modify `docs/research/2026-09-24-carbohydrate-validation-operations.md`,
`docs/DDM_CALIBRATION.md` (Sucrose paragraph), `README.md` (roadmap); create
`tests/dashboard/integration/test_sucrose_reference_mapping.py`.

- [ ] Write the failing test: drive the candidate route for `Sucrose` end to end and assert the
      reference-conformant signature plus an empty conformance issue list.
- [ ] Run it and watch it fail.
- [ ] Update the documentation; state D1's boundary explicitly (mapping conforms; equilibrium numbers
      stay geometry-derived and are reported as deltas).
- [ ] Run the fast tier, the mapping integration tier, `ruff check dashboard tests --select F,E9,I`; commit.

## Verification commands

```
dashboard/.venv/bin/python -m pytest -m 'not browser and not slow' -q      # fast tier
dashboard/.venv/bin/python -m pytest tests/dashboard/unit -q               # unit tier
dashboard/.venv/bin/python -m pytest tests/dashboard/integration/test_mapping_workspace_api.py tests/dashboard/integration/test_carbohydrate_validation.py -q
dashboard/.venv/bin/python -m ruff check dashboard tests --select F,E9,I
```

Baselines before Task 1: fast tier **464 passed**; lint clean.
