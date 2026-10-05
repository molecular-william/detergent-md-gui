# The membrane frame — protein orientation, belt and box

## Status

Decisions taken by the user on 2026-10-05 ("go with the box"). Amends
`2026-09-28-protein-detergent-complex-panel-design.md` §1 (box and protein insertion), §4 (box extension in z), the
belt clearance in §3 and the belt contact criterion in §7. Nothing is implemented yet.

## Why

The panel spec's box is a blob rule: the protein's own extent plus 2.0 nm, with the protein centred. Two things
follow from it, and both are in the code rather than inferred from it:

- `micelle/cli.py:25` calls `infer_orientation(protein)` with no OPM metadata and no explicit axis, so **every
  build today records `method='heuristic'`, `confidence=0.35`, `evidence=('principal-axis fallback',)`** — the
  weakest of the three sources `infer_orientation` knows about.
- `micelle/geometry.py:candidate_score` measures its belt from `p - p.mean(0)`, **the protein's centroid**, with
  `span=(-1,1)` nm — a value no input sets, and 1.0 nm on a structure that may state its own thickness.

Measured on OPM entry **1qj8** (OmpX, 1,158 atoms), fetched from
`https://biomembhub.org/shared/opm-assets/pdb/1qj8.pdb`:

| quantity | value |
| --- | --- |
| z-extent | −2.26 .. +3.80 nm |
| atom-mean z — what the belt is measured from today | **+0.73 nm** |
| membrane plane — what OPM states the belt straddles | 0.00 nm |
| half-thickness in the file (`REMARK 1/2 of bilayer thickness: 11.8`) | 1.18 nm |
| half-thickness implied by the unset `span` default | 1.00 nm |

The two bands disagree about **361 of 1,158 atoms (31.2%)**: the slab `|z| ≤ 1.18 nm` holds 46.6% of the atoms, the
centroid band `+0.73 ± 1.00 nm` holds 39.1%. `coverage` — the fraction of protein atoms inside the belt — is the
first term of `candidate_score`'s score, so the placement has been rewarded for approaching a band that is half a
nanometre off the bilayer OPM measured, and thinner than the structure says.

This is not a broken box. At 1qj8's numbers the belt's worst clearance today is 3.08 nm, comfortably past the CG
1.35 nm cutoff. The case is narrower and worth stating exactly: the belt's **origin** is wrong, its **thickness** is
a guess, its clearance is **asymmetric**, and the frame the box is built in is the protein's rather than the
membrane's.

## Decisions

### 1. The belt is measured from the membrane plane, not from the centroid

`OrientationReport` gains an `origin`. `candidate_score` measures `axial` from it. When a build supplies no
orientation the origin stays the centroid, which is the present behaviour, so nothing changes for a protein that
carries no membrane metadata.

### 2. The belt's half-thickness is the one the structure states

`infer_orientation`'s OPM branch reads the span from its metadata instead of leaving it to
`explicit_span or (-1.,1.)`. A fetched structure's `REMARK 1/2 of bilayer thickness` is parsed into that field. A
structure that states nothing keeps the 1.0 nm default, and the manifest records which was used — the report
already carries `orientation.__dict__` (`micelle/cli.py:26`), so this is a value, not a new mechanism.

### 3. The box is expressed in the membrane frame

- **x and y**: max(protein extent, belt footprint) + `box_margin_nm`.
- **z**: the membrane plane is the box's midplane, and the half-length is
  `max(largest |z| over the protein's atoms, the belt's half-thickness) + box_margin_nm`.
- Today's rule — the protein's extent + 2 × margin, protein centred — is kept as the fallback for a build with no
  orientation, which is every build today. No existing behaviour is removed; the rule is bypassed only when a build
  states its membrane.

Measured cost on 1qj8 at the default 2.0 nm margin: z goes **10.07 → 11.61 nm**, and the shape is applied
afterwards:

| shape | box | volume |
| --- | --- | --- |
| rectangular, membrane frame | 8.30 × 7.41 × 11.61 nm | 714 nm³ |
| rectangular, today's rule | 8.30 × 7.41 × 10.07 nm | 619 nm³ |
| cubic, membrane frame | 11.61 nm on every axis | 1,565 nm³ |

So the frame costs **+15%** as a rectangular box and **+53%** as a cube.

### 4. A membrane protein takes a rectangular box

`box_shape` is absent from `DEFAULTS` (`dashboard/execution/adapters/pdc.py:42`) and is not exposed in the panel,
so it arrives as `box_for`'s own `'cubic'` default. `box_for(shape='cubic')` puts the largest dimension on every
axis, and for a membrane protein the largest dimension is normally z — the belt plus the soluble domains plus
water. On 1qj8 the cube is 2.2× the rectangular volume and buys nothing.

So `box_shape` becomes a stated default of `rectangular` for a build that carries an orientation, remainable by the
same setting a run can already pass, and validated as the two values `box_for` accepts.

## The importer this depends on

Fetch at import, never at build. `https://biomembhub.org/shared/opm-assets/pdb/<pdbid>.pdb` (verified: 200,
`Content-Type` text, PDB, 1,158 atoms for 1qj8). `opm.phar.umich.edu` cannot be fetched from: it is a React SPA
that answers every path with the same 1.4 KB shell.

The import writes the structure plus a sidecar — pdbid, source URL, sha256, the half-thickness it states, fetch
date — into the packaged molecule directories, which `pdc.py:_proteins` already lists by scanning
`molecules/*/*.pdb`, so the catalogue needs no new source. A network call inside a build would break the repo's
contract that a run records the versions and paths it used and stays reproducible offline.

## Pre-run preview

The panel design's Goal already promises the whole setup is "visible in an NGL viewer before anything is run"
(line 15), but every picture is addressed by `job_id` (`/api/pdc/<job_id>/system.pdb`), so a build has to be queued
before it can be looked at. A preview endpoint builds the placement and the box only — no topology, no solvent —
and returns it through the same server-side PDB writer the run viewer uses, so there is one renderer rather than
two. This is offered as part of the same work and is conditional: the placement is asserted to be deterministic and
seeded, and that assertion has to be checked in the code before a preview can be promised to be the same build.

## Verification

- The run manifest records `method='opm'`, `confidence=1.0`, against today's `'heuristic'`, `0.35`.
- The belt band the placement scored against appears in the manifest and equals the structure's own statement.
- Box dimensions and pre-extension dimensions are both recorded, as §4 already requires.
- For 1qj8 the belt band holds 46.6% of the atoms, where the centroid band holds 39.1% — the classification
  changes by 361 atoms, and that number is the regression test.
- A protein-free build: box rule unchanged, orientation report carrying no protein.

## Open questions

- Whether fetched structures are committed, cached or fetched-and-recorded. OPM derives from the PDB and asks to be
  cited; the M3-Lipid set is kept untracked by the user's standing instruction and this needs the same decision.
  OPM's terms have not been read.
- Whether half-thickness comes from the file's REMARK or the entry page's "Hydrophobic Thickness or Depth" (23.6 Å
  for 1qj8, which is the REMARK's 2 × 11.8 — they agree here). The REMARK travels with the coordinates, so it is
  the one the import should trust.
- OPM's bulk `/download` page has not been inspected.
