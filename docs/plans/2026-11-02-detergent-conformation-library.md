# Detergent conformations from micelle-only runs

Status: **approved 2026-11-02** (the user's decisions; this file is the plan of record). Owner: next agent.
Read `docs/HANDOFF.md` first.

## The request

CHARMM-GUI's micelle builder gives each detergent a randomly chosen configuration taken from micelle simulations
rather than stretching one template molecule over the whole surface. This repository stamps every detergent from one
conformation today. The request: build our own conformation library from micelle-only simulations, keep the library
size constant, and use it wherever detergents are placed.

The user's decisions (2026-11-02):

1. **Source scope**: the caller chooses one run or several pooled runs.
2. **Size**: **K = 2000** entries per detergent, chosen by **stratified selection**.
3. **Reference**: a run names the library in one of two ways — by its **source run ids**, in which case it is built
   (or reused) on demand, or by the **key and digest of a stored library**, in which case it is used as-is. Building
   from runs writes the result into the same store, so it immediately becomes a selectable pre-built library. The
   store is **not tracked** in git; a built directory is self-contained and may be copied between workspaces by hand.
4. **Orientation**: the library stores each molecule's **internal geometry** (head anchored, head-ward axis along
   +z); the placement draws the azimuth.
5. **Scope**: both lattice modes (sphere and torus) and the **preview**. The draw lives in `place_detergents`, so the
   self-assembly generator gets it too rather than a second code path.

## Verified current state

- Every detergent is **one conformation**: `molecules/*/micelle_template.json` names coordinates (or the run's
  mapping-derived beads), `pdc_placement.detergent_profile` turns them into offsets + axis + head anchor, and
  `pdc_build.stamp` writes that one body at every site. The placement seed chooses sites and directions, never the
  molecular shape (`packages/pdc/src/detergent_pdc/execution/adapters/pdc_placement.py`,
  `.../execution/scripts/pdc_build.py:123`).
- `place_detergents` is the one placement resolver for the sphere shell, the torus belt and the self-assembled cloud;
  the **preview** runs the build's own functions including `stamp` (`.../execution/pdc_preview.py:12`).
- A **micelle-only run is an ordinary build**: a pdc run with no protein is the empty-micelle path
  (`prepare` writes `inputs/protein.pdb` as a "no protein" note). `b920391735dd` is a 100 ns DDM example with 120
  written frames.
- Runs record what they read by reference: `run_inputs.store(role, path, label=...)` for a workspace file and
  `run_inputs.run_output(role, run_id, path, ...)` for another run's file, each with a sha256 tamper seal
  (`packages/core/src/dashboard/execution/run_inputs.py`). `prepare` already records the mapping this way.
- The build stage resolves file settings by path (`pdc_build.resolve`); `02_system` declares the settings file and the
  empty topology, and writes `system.gro`/`system.top`.
- No conformation library, no `conformations` setting, and no clustering dependency is declared: `scipy`/`sklearn` are
  present only through other packages (see `analysis/runs/dihedral_fit.py`'s note), so the selection is pure numpy.

## What a library entry is

One whole detergent molecule, in a **local frame**: bead positions with the molecule's head anchor at the origin and
its head-ward axis along **+z**. The axis is decided by the same four rules `detergent_profile` already documents
(`roles`, then Martini bead `type`, then polar atoms, then principal axis), so the site still names the molecule's
head end and `stamp` needs no new convention. Positions are rounded to `1e-4` nm.

Each entry also carries its four **descriptors**, in nm:

| descriptor | definition |
| --- | --- |
| `length_nm` | furthest bead behind the head along the axis |
| `rg_nm` | radius of gyration of the beads |
| `reach_nm` | furthest bead from the head anchor |
| `radial_nm` | furthest bead from the axis |

and its provenance: source run index, frame time, residue id.

## Library file, identity and location

One file per detergent and source set, under the workspace store:

```
workspace/dashboard/conformations/<residue>/<key>/library.json
workspace/dashboard/conformations/<residue>/<key>/library.sha256
```

- `<residue>` is the detergent's own residue name (`DDM`).
- `<key>` is the first 16 hex of the sha256 of the canonical spec: format version, detergent signature, selection
  parameters, and the **sorted** list of `(run_id, trajectory_identity)` pairs. It is stable across rebuilds and
  independent of frame order.
- `library.sha256` holds the sha256 of `library.json`, so a copied directory can be verified before it is trusted.
- `library.json` is canonical: sorted keys, entries in canonical order, floats rounded, trailing newline. It contains
  everything needed to use and audit the library, including the sources; there is no timestamp in it (a rebuild must
  reproduce the same bytes where the inputs are the same).

Schema (`format: "detergent-conformations-v1"`):

```json
{
  "format": "detergent-conformations-v1",
  "detergent": {"residue": "DDM", "beads": ["B01", "..."], "mapping_sha256": "..."},
  "selection": {"size": 2000, "seed": 0, "method": "stratified-median-split",
                "descriptors": ["length_nm", "rg_nm", "reach_nm", "radial_nm"]},
  "sources": [{"run_id": "...", "detergent": "DDM", "trajectory": "...", "trajectory_identity": "...",
               "frames": 120, "pool": 18000, "protein": false}],
  "pool": 18000,
  "entries": [{"beads": [[0.0, 0.0, 0.0], "..."], "descriptors": [1.42, 0.81, 1.44, 0.31],
               "source": {"run": 0, "time_ns": 12.3, "resid": 1234}}]
}
```

`beads` is the bead order the run's mapping states; an entry's `beads` list is in that same order. A library whose
bead names, count or mapping digest do not match the run is **refused**, never silently used.

## Building it

New package `detergent_pdc/conformations/` (pure functions, no new dependency), plus a CLI:

```
python -m detergent_pdc.conformations build --workspace <ws> --runs <id>[,<id>...] --size 2000 [--seed 0]
python -m detergent_pdc.conformations show  <library.json|key>
```

1. **Source validation** (`sources.py`): every named run exists, is `completed`, is a pdc run, states **no protein**
   (a protein-contacted micelle is a different ensemble — refused with the run's own sentence), and its recorded
   detergent signature matches the new run's template/mapping. Pick the run's production trajectory the way the
   analysis code already does (`analysis/runs/segments`/`layout`, last non-duplicate segment) and record its
   `identity`.
2. **Extraction** (`extract.py`): read the trajectory once with MDAnalysis, group atoms by residue, keep the residues
   named for the detergent, make each molecule whole (declare the molecule's bonds inside the residue, unwrap — the
   same operation `pbc mol` uses), and drop a molecule that is non-finite or whose bond lengths leave the mapping's
   own [0.8, 1.2] range. Turn each survivor into the local frame and compute its descriptors. Counts of kept,
   broken, and non-finite molecules go into the build record for the operator, not into `library.json`.
3. **Selection** (`select.py`): standardise the descriptors (median/IQR, guard a zero spread), then repeatedly split
   the widest cell at its median along its widest descriptor until there are exactly K cells; take the candidate
   nearest each cell's centre. Deterministic: canonical candidate order, stable sorts, tie-break by that order. If
   the pool is smaller than K, **refuse**, naming the pool size and the runs — K never silently shrinks.
4. **Write** (`library.py`): canonical JSON, sidecar digest, atomic replace under a lock file so two concurrent
   prepares build one library.

Cost: one sequential pass per source run. The existing frame-series producer measured 44 s for a 100 ns, 2.5 GB
trajectory; a library build is the same order. The result is cached by key, so it is paid once per source set.

## The two ways to name a library

`conformation_library` is one of:

- **build** — `{"runs": ["<id>", ...], "size": 2000, "seed": 0}`. Resolve builds it when absent and reuses the stored
  copy when present. A build-from-runs **writes into the store**, so the result is immediately a pre-built library the
  same card can select by key afterwards.
- **reference** — `{"key": "<key>", "sha256": "<digest of library.json>"}`. Use the stored library as it is. The source
  runs need not exist in this workspace: the library is self-contained and names them in its own `sources`. The
  resolver verifies the sidecar, the digest, the size and the detergent signature, and refuses a missing or changed
  file — it never rebuilds a referenced library.

Both modes record the resolved **key and digest** on the run; the build mode also records the source run ids it built
from, and the reference mode records the source run ids the library names (as strings, because they may live in another
workspace). A copied directory dropped into the workspace store is therefore usable by key without its runs; a build
from runs is the way to *create* one.

## Resolving it

`conformations.resolve(workspace, spec, *, build=True)`:

- **build** spec: compute the key; if the directory exists and `library.sha256` matches, return it; otherwise, with
  `build=True`, build, verify, write atomically and return it; with `build=False`, raise "no library for these runs".
- **reference** spec: find the directory by key; verify the sidecar digest, size and signature; return it. Never build.

A **copied** directory is accepted when its sidecar matches; a hand-edited one is refused with the sentence naming the
mismatch. A rebuild whose bytes differ from a run's recorded digest is also refused: a run pins the library it was
prepared with, the same rule `inputs.json` applies to every other input. For a referenced library, losing it is a
refusal with "copy the original back", because its runs may not be local.

## Run integration

- **New setting** `conformation_library`: `null` (today's behaviour), `{"runs": ["<id>", "..."], "size": 2000,
  "seed": 0}`, or `{"key": "<key>", "sha256": "<digest>"}`. Validated in `validate_payload`: build mode checks the ids,
  completion, empty-micelle state and detergent signature, `size` an integer 1..5000, `seed` an integer; reference
  mode checks the key's shape, the digest, and that the stored library's signature matches the run's detergent. Absent
  means one rigid conformation and every existing run is unchanged.
- **`prepare`** (`pdc.py`): resolve the library (building only for the build mode), record it with
  `run_inputs.store('detergent_conformations', path, label=...)`, and write into `pdc-settings.json`:
  `conformations_library` (absolute path), `conformations_key`, `conformations_sha256`, `conformations_runs`,
  `conformations_size`, `conformations_mode` (`build` or `reference`). A build records the runs it built from; a
  reference records the runs the library names. The 02_system stage already reads the settings file, so no new stage
  input line is needed; the build re-verifies the sha256 before reading it.
- **`pdc_build`**: load and validate the library against the run's own detergent model (bead names and mapping
  digest), then hand `placement` the profiles. A library that fails validation stops the stage with a sentence, as a
  template that cannot build already does.
- **`place_detergents`**: new keyword `profiles=None`. When given, draw one entry index and one azimuth per site from
  the existing seeded RNG, return both (and the library key) in the placement record, and measure `body_beads` with
  the **drawn** entry so the clearance gate sees the body that will be written. When `profiles` is `None`, nothing
  changes.
- **`stamp`**: new keyword `entries=None` / `twists=None` from the placement. Each molecule's beads are the entry's
  offsets rotated so +z lands on the direction, then twisted by its azimuth; the head anchor still sits on the site
  and the bead names still come from the topology. The per-detergent residue numbers are unchanged.
- **Preview**: resolve the same library, include its key, size and source run ids (never coordinates) in the preview
  record, and use the same profiles for placement and stamping. The CG protein cache is unaffected; the library is
  cached beside it.
- **Panel** (New run, pdc): a **Detergent shape** block inside the New run form (a sibling of the Detergent, Membrane
  protein and Run configuration cards — not a panel of its own), with three choices: one rigid conformation (default),
  **build from runs** (eligible-run list, size 2000, seed), or **existing library** (the stored libraries discovered
  for this detergent, by key, size and source runs). Building from runs refreshes the "existing library" list. The
  preview request carries the spec. This is a cross-layer UI change: the in-context HTML draft
  `docs/design/drafts/2026-11-02-conformation-library-in-form.html` (with the component draft beside it) lands before
  the panel code.

## Tests

Unit (`tests/unit` under the pdc tree, fixtures only):

- local frame: head anchor at origin, axis +z, descriptor values, round trip;
- extraction: a molecule split across the boundary is made whole, a non-finite one is dropped, counts recorded;
- selection: exactly K, distinct, deterministic for one pool and seed, spans the descriptor ranges; pool < K refused;
- serialisation: canonical bytes and digest stable across two builds; a tampered file refused; a copied directory
  accepted; a signature mismatch refused;
- resolver: cache hit, rebuild when missing, atomic write under two callers; a **reference** spec resolves without the
  source runs, and a reference whose key, digest, size or signature does not match is refused without building;
- sources: not completed, a protein present, a different detergent, a deleted run — each refused with its sentence;
- library store: a build writes into the store and appears in the stored-library listing; a copied directory appears
  there too; a directory with a missing or wrong sidecar is not listed;
- placement: the same seed draws the same indices/azimuths; the body gate outcome changes when the drawn entry is
  long versus short; no library leaves the record and the placement unchanged;
- stamp: head on the site, axis along the direction, twist applied, bead names and residue numbering preserved.

Integration:

- `prepare` records the library as a `store` input with the digest; editing the file makes input verification fail;
- a build and the preview of the same settings produce the same placement (the existing preview-vs-build test is
  extended with a library);
- a one-run and a two-run library both record their source ids and identities;
- a build run records mode `build`, and a later run that selects the resulting library by key records mode
  `reference` with the same digest and no dependency on the source runs.

Browser:

- the New run panel offers eligible runs, size and seed; the preview shows the library key and size; choosing no
  library keeps today's form and preview;
- the shape card's third mode lists the stored libraries and selects one by key; after a build-from-runs the library
  appears in that list.

## Hazards and limits

- **Determinism across versions.** The library's digest is the run's pin. A rebuild on another numpy/MDAnalysis version
  may produce different bytes; that is refused rather than swapped, and the copy/paste affordance is the way to move
  the original. Record the producer version in the build record (not in `library.json`).
- **A referenced library cannot be rebuilt.** Key mode uses a stored directory; if it is deleted and its source runs
  are not local, the run is refused and the original must be copied back. That is the price of portability, and the
  run's recorded digest is what makes the loss visible instead of silent.
- **K versus pool.** A short source run may not hold 2000 whole molecules; the build refuses and names the pool, so K
  stays constant. Pooling more runs is the answer.
- **Memory**: candidates are K-sized arrays of beads plus descriptors; a large pool is a few tens of MB, not a copy of
  the trajectory.
- **Cost**: one sequential pass per source run, once per key.
- **Ensemble purity**: only empty-micelle runs are accepted, so a protein-contacted conformation cannot enter the
  library by accident.
- **Scientific validation**: this changes the initial condition, not the physics. The library is judged by internal
  consistency (bond geometry, descriptor coverage, deterministic rebuild) and the existing placement gates; it is not
  a claim that the resulting micelle is better equilibrated.

## Not doing

- No tracked library asset in git (the user's decision).
- No new similarity/clustering dependency: the selection is pure numpy.
- No per-detergent mixed-micelle library in this slice: one residue per library; a mixed system would need one per
  species later.
- No change to existing runs; the setting is opt-in.

## Files

- New: `packages/pdc/src/detergent_pdc/conformations/{__init__,library,extract,select,sources}.py`.
- Drafts (landed 2026-11-02): the compact component draft
  `docs/design/drafts/2026-11-02-conformation-library.html` (the card alone, states: one rigid conformation, build
  from runs, existing library) and the in-context draft
  `docs/design/drafts/2026-11-02-conformation-library-in-form.html` (the whole New run form with the shape card among
  the Detergent, Membrane protein and Run configuration cards). Both are labels-and-controls only: no per-option
  prose. Screenshots sit beside each but are gitignored by the repository's `docs/design/drafts/*.png` rule. Design
  records, not wired up.
- Changed: `packages/pdc/src/detergent_pdc/execution/adapters/pdc_placement.py` (`profiles`, draws, record),
  `.../execution/scripts/pdc_build.py` (load, validate, stamp), `.../execution/pdc_preview.py` (resolve, record),
  `.../execution/adapters/pdc.py` (setting, validation, prepare, inputs), the pdc New run panel and its browser test,
  `docs/PROJECT_GUIDE.md`, `docs/HANDOFF.md`.

## Definition of done

- A library can be built from one run or several, has exactly 2000 entries selected by the stratified method, and its
  file digest is stable across two builds from the same sources.
- A run can name the library either by its source runs (built or reused on demand) or by the key and digest of a
  stored library (used as-is, no source runs needed); a build-from-runs writes into the store and becomes selectable
  by key. The library is recorded in `inputs.json` with its digest and is not tracked in git; a copied directory is
  accepted and a tampered one is refused.
- A build whose setting names a library places each detergent with a drawn entry and azimuth, records the library key
  and per-detergent indices, and the clearance gate measures the drawn body.
- Both lattice modes and the preview use it; a run with no setting is byte-identical to today's build.
- Refusals name the missing run, the protein, the detergent mismatch, the pool size or the digest mismatch.
- Fast, browser and slow tiers, ruff and the mutation check pass; the plan's execution record, `PROJECT_GUIDE.md` and
  `HANDOFF.md` are updated.
