# One directory of files reused across simulations

Status: **draft for review. Nothing built.** This answers the question *"maybe there can be a directory with files
that we can reuse across simulations? how can we resolve the problem you mentioned then"* — with what the 14 live
runs already share, what they recompute, and what sharing would have to record. It is a design note, not a task
list to execute; the decisions below are the ones that have to be settled first.

Its second job is a negative result: it says plainly that a reusable directory would **not** have fixed the frame
bug fixed the same day (`dashboard/analysis/runs/observability.py`), because that was a path-resolution defect and
not a storage one. Evidence in *Would a store have fixed the frame bug?* below.

## What the runs share today, measured

Read from `workspace/dashboard/runs/` (14 runs, 2026-10-14: 6 `aa_only`, 2 `aa_cg`, 6 `osmotic`), latest-first
per run 29 MB – 1.20 GB, ~9.3 GB total. Every file that is byte-identical in two or more runs, grouped by content
hash and name:

| shared artifact | one copy | present in | redundant bytes |
| --- | --- | --- | --- |
| `martini_v3.0.0.itp` (tutorial CG topology) | 16.0 MB | 8 runs | **112.2 MB** |
| `ffnonbonded.itp` | 2.7 MB | 5 runs (a second hash: 3 runs) | 16.2 MB |
| `lipid.rtp` | 2.6 MB | 5 (and 3) | 15.5 MB |
| `ffbonded.itp` | 2.5 MB | 5 (and 3) | 14.9 MB |
| `lipid.hdb` | 1.5 MB | 5 (and 3) | 9.0 MB |
| `cgenff.rtp` | 1.2 MB | 5 (and 3) | 7.5 MB |
| six more charmm36 tree files | | 5 (and 3) | 15.1 MB |
| the remaining ~168 duplicated files (mostly ×2) | | | ~2.9 MB |

**180 distinct files are present in two or more runs; ~193 MB is one extra copy per run beyond the first.**

That understates it, because the same bytes are staged more than once *inside* one run. Counted by content:

- **the tutorial CG topology: 14 byte-identical copies, 224.4 MB on disk, for one published 16.0 MB file** — a CG
  run keeps four ( `stages/3_initial_CG/`, `stages/4_CG_sim/inputs/`, `inputs/3_initial_CG/`,
  `inputs/4_CG_sim/inputs/` ), an osmotic run one (`01_simulate/`), and all 14 hash to the published
  `resources/templates/small_mols_fast_forward/3_initial_CG/martini_v3.0.0.itp` (`0ecbf0ff…`).
- **the charmm36 tree: 1,008 files, 214.1 MB, across 16 staged copies, for one published 13.4 MB tree.**

So ~438 MB of disk holds ~30 MB of published content. Every one of those files is a *published* input the
repository keeps under `resources/` and copies into the run directory. None of it is derived, none of it differs
between two runs, and all of it is already hashed into the run's manifest (`cg.prepare` records
`force_field.sha256` per file; `aa_references.publish` hashes the whole staged tree).

What the runs genuinely recompute, and should keep recomputing:

- the AA solvated/neutralized system and its production trajectory (`stages/01_solvation` … `07_reference`);
- the CG boxed, solvated and simulated system (`stages/4_CG_sim/{boxed,solvated,min,eq,md}.*`);
- the per-run **fitted** bonded topology (`stages/3_initial_CG/{residue}_ff_inter.itp`), fitted to *that run's own*
  AA reference — the AA reference it was fitted to is exactly what makes it non-transferable;
- osmotic conditions (their `plumed.dat`, the box, the molality).

## Where each expensive artifact lives now

| artifact | produced by | where it lives now | shared? |
| --- | --- | --- | --- |
| AA reference (solute + trajectory) | `07_reference` stage of an `aa_only` run, published by `analysis/runs/references.publish` | `<aa_only run>/stages/07_reference/{lig.gro,lig.tpr,lig.xtc,diagnostics.xvg,reference.json}` | **yes, by reference** — see below |
| published force field, AA | copied at prepare (`shutil.copytree(FORCE_FIELD, run_dir)`) | `<run>/stages/common/charmm36-jul2022.ff/` and `<run>/inputs/charmm36-jul2022.ff/` | no — a fresh 13 MB copy per run |
| published force field, CG | `shutil.copy2(TUTORIAL_TEMPLATE/'3_initial_CG/martini_v3.0.0.itp', …)` | `<run>/stages/3_initial_CG/martini_v3.0.0.itp` and `<run>/stages/4_CG_sim/inputs/…` (a CG run also keeps the `inputs/` copies) | no — 16 MB per run, up to four times |
| the mapping | `mappings.export_files(saved candidate)` at prepare | `<run>/stages/2_mapping/{model.json,mapping.map,mapping.ndx,README.txt}` | no — identical for two runs on the same candidate |
| the CG protein beads | `martinize2` through `pdc_build.cg_protein`, run in `<stage>/cg/` | `<pdc run>/<stage>/cg/protein_cg.pdb` (`-x`) and `molecule_0.itp` beside it | **never** — no PDC run survives (all deleted 2026-10-13), so the one external tool in the chain has never had its output reused |

## How a shared AA reference is recorded today

This is the shape to extend, so it is worth stating exactly. It is the `aa_cg` consumer path (the two live `aa_cg`
runs), read out of `execution/workflow.py` and `analysis/runs/references.py`:

- **What a consumer records.** Its manifest carries
  `"shared_reference": {"source_run_id": "a54ac8f64710", "sha256": {"stages/07_reference/lig.xtc": "fc1ca4c6…", "…": "…"}}`
  — the *full file-hash map* of the source's published reference — plus `reference_reused: true` and
  `reference_run_id`. Each stage entry that used it carries its own copy of `shared_reference`.
- **What it does not do.** It does not copy the reference. `22075892b606` holds no `lig.xtc` of its own; its
  `stages/1_AA-reference/` contains only the stage *script*. `cg.prepare` calls
  `aa_references.resolve(reference_root, source_run_id, expected_sha256)` for the check and copies nothing.
- **How it reads it.** `workflow.run` resolves the source once per run
  (`aa_references.resolve(run_dir.parent, …)`) and hands every stage `AA_REFERENCE_DIR=<source run>/stages/07_reference`
  as an environment variable, recorded in the stage entry. The stage scripts (`map_trajectory.sh`, `fit_topology.sh`,
  `cg_simulation.sh`, `assess.sh`, `sasa.sh`, `sugar_mapping.py`) read it from there, each with the old relative path
  as its default.
- **How the reuse is visible.** The `AA reference` stage is recorded `status: "reused"`, `command: []`,
  `source_run: <id>`, with the declared output hashes — so the manifest says in one line that this run did not
  produce its own reference, and which run did.
- **The check is re-run, not trusted.** `references.verify` re-hashes every entry against `sha256` and refuses on
  any mismatch, on a symlink, or on a `molecule_identity`/settings disagreement. A mutated source run strands every
  consumer with an error rather than a silent difference.

Two things about that mechanism matter for the store:

1. **The root is `run_dir.parent`, not recorded.** `reference_root` is passed at prepare time and used for the
   check; the record says *which bytes*, not *where*. That works while every reference lives under the runs root.
   A store is a second root, and a manifest that names an entry without a resolvable root is a run that cannot be
   re-read — so the store's location has to be recorded or fixed by configuration.
2. **The key is the full file hash map, not a name.** Two runs on different molecules hash differently and are
   correctly incomparable; the same molecule at the same settings hashes identically and collapses to one entry.
   The `reused` stage status is the precedent for the rule below that sharing a *result* has to be visible.

## What extending it takes

### The store

A content-addressed directory beside the runs, not inside them — e.g. `workspace/dashboard/assets/<kind>/<sha256>/`,
gitignored like `workspace/`. Content-addressed rather than named so a new fit is a new entry and never an overwrite
(the same rule that already forbids silently overwriting a run). It must stay outside `RUNS/` so
`resources.report`/`max_total_bytes` stay about simulation data, and so `files.safe_files` cannot walk a run's own
directory into another run's inputs.

Kinds worth an entry, in the order I would build them:

1. **`forcefield/`** — the published trees, keyed by the tree hash the manifest already computes. Cheapest, most
   bytes saved (~438 MB today, and it grows with every run), and no scientific risk at all because the artifact is
   published and immutable. `charmm36-jul2022.ff` and `martini_v3.0.0.itp` are the two.
2. **`reference/`** — the AA reference, generalised from *`aa_only` sources* to *any run's published reference*,
   stored by the same file-hash map that `shared_reference` already carries. Today a reference is reachable only
   through the run that produced it; a store entry survives that run's deletion, which is a decision the user has
   to make (see below).
3. **`mapping/`** — the four exported files, keyed by the saved candidate's export hash plus the molecule snapshot.
4. **`cg-protein/`** — martinize2's `protein_cg.pdb` + `molecule_0.itp`, keyed by (input protein file hash,
   martinize2 version, its model/mapping flags, the secondary-structure letters). Highest value per entry for the
   PDC workflow, because martinize2 is the chain's only external tool and its output is a function of those inputs.

### What a manifest would have to record

For every reused artifact, in the run's own `manifest.json`:

- the entry's content hash and the store kind it belongs to;
- the exact per-file hashes inside it (so a mutated entry is caught, the way `verify` catches a mutated reference);
- **where the store is**, or a rule that resolves it — the gap `reference_root` leaves today;
- for a derived artifact, the inputs that decide its bytes: the tool name/version/path, the flags, and for anything
  fitted the AA reference `sha256` it was fitted to;
- for the mapping, the candidate's `snapshot_sha256` and export hash;
- a `reused: true` marker plus the role(s) it satisfies, so the analysis layer keeps one resolver rather than a
  second table of where things live.

### What must be true for a reused file not to silently make two runs incomparable

- **The key contains every input that changes the bytes.** A fitted topology keyed without its AA reference
  sha256 would be reused by a run it was never fitted to, and the two would then read as replicates and are not.
  The repository already states this rule twice (`references.identity` over files + chemistry; `mapping_sha256`).
- **Verified on every read, never trusted.** `aa_references.verify` is the model: re-hash, refuse on mismatch. A
  store mutated in place is a run whose recorded provenance is a lie.
- **Immutable and content-addressed.** A refit writes a new entry; it never overwrites one. Deleting a run must not
  delete an entry another run references — content-addressed storage should simply not delete, and the standing
  rule *"do not delete simulation data during cleanup"* extends to it.
- **Resolved by one resolver that knows every root.** A reader handed the store root and a reader handed the run
  root must agree, and a run that holds the artifact at *both* is the ambiguity the layout resolver already refuses
  (`layout.resolve`). This is the same two-spelling problem AGENTS.md records for `stages/` versus the work
  directory, one root larger.
- **Sharing a result must be visible.** A reused input (a force field, a mapping) changes nothing about what a run
  means. A reused *result* (a fitted topology, an assessment) does: two runs that share one fit are not two
  independent estimates, and a report that does not say so turns one measurement into a fake replicate.

## Would a store have fixed the frame bug?

**No — and the failure would have been the same shape.** On 2026-10-14 `observability.generate` hard-coded one
stage spelling and refused any other:

```
stage_dir = run_dir / '1_AA-reference'
trajectory = stage_dir / '3-run.xtc';  topology = stage_dir / '3-run.tpr'
if stage != '1_AA-reference': raise ValueError(…)
```

Measured on the real runs before the fix: `generate(<aa_only run>)` and `generate(<aa_cg run>)` both raised
`FileNotFoundError: AA trajectory requires 1_AA-reference/3-run.xtc and 1_AA-reference/3-run.tpr`. The trajectories
were present the whole time — `<aa_only run>/stages/07_reference/lig.{gro,xtc}` and
`<aa_cg run>/stages/4_CG_sim/prod/lig_CG.{gro,xtc}` — under the run's own layout. Nothing was missing from the
filesystem; the reader was looking in one place and refusing to look anywhere else.

A store changes *where* files live. It does not make a hard-coded path able to find them: the same function handed a
store root would raise the same error about a path that does not exist there. Worse, a store adds a *second* root
that a reader has to know about (the entry under the store, and the copy inside the run), which is exactly the
defect `layout.py` was written for — AGENTS.md records that a reader spelling only `stages/...` sees a complete run
as empty, and the fix there was a resolver that knows both spellings, not a different directory. The frame bug was
fixed by resolving the role from the run's own layout (`layout.frame_source`); if a store is ever added, that
resolver is where the store root is added, and it is the resolver — not the directory — that makes a frame real.

The one thing a store *would* have changed is nothing about this bug and something about a neighbouring one: the AA
reference a consumer reads would have been reachable without a producing run, where today deleting the source run
strands every consumer. That is a real problem, and it is separate.

## Decisions this needs from the user

1. **Does a store entry outlive the run that produced it?** Content-addressed and never deleted is the only choice
   that cannot corrupt provenance, and it means storage grows without the retention sweep (`retention_days: 90`)
   ever touching it.
2. **Force fields first, or references first?** I recommend force fields: ~438 MB of the runs' ~9.3 GB is
   byte-identical published content (224.4 MB of it one 16 MB file), there is zero scientific risk, and the
   manifest already hashes them.
3. **A reused *fit* — allowed, or refused?** Sharing an input is free. Sharing a fitted topology makes two runs
   one estimate, and the report has to say so. The user's standing decisions on this file point one way (*"fitted
   linkage values are not a diagnosis"*, *"internal consistency = primary evidence"*); I would refuse result
   sharing in the first version and revisit it when a second workflow asks for it.
4. **Where the store lives** — `workspace/dashboard/assets/` (gitignored, beside the runs) versus a path named in
   `config/dashboard.json`. The second is checkable at startup; the first needs no new configuration.

## Out of scope

- Not a package manager, not a cache with eviction, not a remote mirror.
- Not a change to how a run *simulates*: this is a reader-side and manifest-side change, plus the prepare-time copy
  becoming a resolve-time reference.
- Not claiming that any reused artifact is validated. Reuse is about bytes being the same, not about them being
  right.
- The frame producer's own fix is separate, is built, and is not part of this design.
