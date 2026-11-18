# Plan: analysis performance round (shared staging, pdc contact graph, per-frame loops)

Status: **built (2026-11-18): Wave 1 (S1–S6) and Wave 2 (S7).** Evidence of what landed and its before/after table is
in the execution record at the end. Evidence for the slices themselves: the four-lane audit of 2026-11-18; every slice
preserves the published numbers of every analysis it touches, and each lane asserts that by replaying the producer and
comparing its artifacts byte for byte.

Rules this plan is held to: `AGENTS.md` *Engineering rules* (measure before and after; one timed live replay of a
producer that reads a production trajectory; no re-run of migrations; GROMACS + Martini by default, anything else only
with measured need) and `docs/plans/README.md` (status, acceptance criteria, tasks in execution order).

## Acceptance criteria (whole round)

1. **Numbers do not change.** For every kind a slice touches, the published artifact is byte-identical to a
   pre-change replay on the same staged work tree: `trajectory-overview.json`, `equilibration-traces.json`,
   `energy-conservation.json`, `dihedral-fit.json`, `bonded-cross-check.json`, the BARTENDER records, the
   `mapping-consistency` report, the `overlap` record, the `osmotic-pressure` record, `pdc-structure.json`, and for
   `frame-series` both `run-frames.pdb` and `frames.json`. For `surfaces`: `metadata.json` (including `commands` and
   `source_sha256`), `surface-comparison-aa-cg.json`, and the sha256 of each variant's `surface.xtc`/`surface.gro`.
   The `trajectory-overview.png` and `overlap` HTML are not byte-compared (rendering, not numbers).
2. **Each slice reports before/after wall time** cold and warm on the same staged corpus, with the command it ran.
   The table is appended to this plan as the execution record.
3. **No test is weakened.** Constants pinned by tests (`MAX_FRAMES`, `PAIR_ATOM_CAP`, `ENERGY_POINTS`, `MAX_MODELS`,
   `MAX_BYTES`, `DEFAULT_SAMPLE_STRIDE`, the SASA knobs, the `stride`/`limit` semantics) keep their values and their
   tests. A slice that cannot pass an existing test without changing it stops and says so.
4. **Gates.** Each lane: `ruff check` on its own paths, its owned tests serial (`-n 0 -p no:cacheprovider`, private
   `MPLCONFIGDIR`), then the affected area (`-m '<area> and not browser and not slow'`). Integrator, once at the end:
   fast tier, the two whole-tree contract tests (`test_agents_contract.py`, `test_test_areas.py`), one timed replay per
   touched kind, then `scripts/gate_commit.sh`. `scripts/mutation_check.py` after the last commit.
5. **HANDOFF is current** before the round closes: what landed, the measured before/after, and any invariant this
   round changed (S2 changes how analyses stage their inputs — that belongs in AGENTS *Invariants*).

## Baseline corpus (staged by the integrator before Wave 1)

Replays go through the real worker path (`worker.execute` with a `request.json`, cwd = checkout root) so the staging
slices are exercised too. Sources are copied to `/tmp/bench/`; `workspace/` is only read.

| id | run / files | what it exercises |
| --- | --- | --- |
| AA | `Glucose-AA-201ns-4fs-20261116`: `07_reference/lig.{gro,xtc}` (24 atoms, 20 001 frames), `06_production/run.{edr,xtc}` (108 MB), stage `min/eq` EDRs | overview, energy, equilibration, mapping-consistency atomistic side |
| CG | `Glucose-CG-200ns-20261116`: `2_mapping/mapped.{gro,xtc}` (4 beads, 20 001), `4_CG_sim/{min,eq,md}.edr`, `prod/lig_CG.{gro,xtc}`, `md.xtc` (17 MB) | overview, frame-series, mapping-consistency CG side, surfaces |
| MIC | synthetic 12 000-atom, 100-detergent, 200-frame leg (lane A's generator, the audit's model system) | pdc-structure, protein/detergent contact graph |
| BIG | synthetic 240 models × 10 427 atoms | frame-series formatting worst case |

No completed `pdc` run exists in this workspace, so every pdc number is a measured component on MIC, not an observed
end-to-end attempt. That is stated in the execution record.

## Slices, lanes and waves

Waves exist only so two lanes never write the same file. All lanes in a wave start together; the integrator reviews and
commits lane by lane, in the listed order, and later commits rebase onto earlier ones.

### Wave 1 (six lanes, disjoint write scopes)

#### S1 · Lane A — pdc micelle criterion: one KD-tree for both contact tests
**Write scope:** `packages/pdc/src/detergent_pdc/execution/adapters/pdc_assessment.py`,
`packages/pdc/tests/unit/test_pdc_assessment.py`.
**Read-only context:** `packages/pdc/src/detergent_pdc/analysis/runs/structure.py` (calls it),
`packages/pdc/src/detergent_pdc/execution/scripts/pdc_assess.py` (the stage's own criterion), MIC.
**Measured problem:** `contact_components` is a Python `for left … for right` over detergent pairs with a `T×T×3`
broadcast per pair: 44.2 ms/frame at 100 detergents, 3.59 s/frame at 800. `assess_micelle`'s protein test
(`_within(tails[index], protein_points, reach)` once per largest-cluster member) measured **191 ms/frame at 100
detergents × 8 000 protein beads** — larger than the detergent graph.
**Change:** one `scipy.spatial.cKDTree` over all tail beads + `query_pairs(contact_nm)` + union-find for
`contact_components`; one `cKDTree` over the protein beads with `query(..., k=1, distance_upper_bound=np.nextafter(reach,
np.inf))` for the protein test, then a per-molecule `any` over its tail beads. Keep `_points` (validation and finite
check), the `contact_nm <= 0` refusal, and the sort order (largest first; ties by first member index, which today's
stable sort gives — reproduce it explicitly).
**Measured gain:** graph 44.2 → 0.5 ms/frame; protein 191 → 8.1 ms/frame (one query for all 500 tail beads, tree
rebuilt per frame). ~24× on the dominant per-frame step.
**Acceptance:** a fuzz-differential test against a frozen copy of today's implementation over ≥500 random systems
(1–800 molecules, 0–8 tail beads, single-bead and 1-molecule systems, duplicate points, distances exactly at the
cutoff, protein None/empty/large, aggregation-number edges) demanding identical `contact_components` lists **including
order** and identical `assess_micelle` dicts; `pdc-structure.json` identical on a MIC replay; `pytest -m 'pdc and not
slow'`.
**Risk to numbers:** none. The predicate (`<=`), the cutoff, the graph and the tie-break are unchanged; only the search
is. Add `scipy` to nothing (already imported by core; the repository treats the scientific stack as host-provisioned).

#### S2 · Lane B — engine staging: stat snapshot, linked sources, one interpreter
**Write scope:** `packages/core/src/dashboard/analysis/worker.py`, `packages/core/src/dashboard/files.py`,
`packages/core/src/dashboard/execution/coordination/analysis_coordinator.py`,
`packages/core/tests/unit/test_analysis_staging.py` (new), `packages/core/tests/unit/test_analysis_self_contained.py`.
**Measured problem:** every attempt `shutil.copy2`s every source into a temp dir (worker.py:247-256), SHA-256s the whole
staged tree (:278) and re-SHA-256s it after the producer (:309-313). Measured: 1.06 s per 465 MB hash pass, 0.26 s copy;
≈**5 s per GB per attempt** of overhead before any science (≈12 s on a 2.5 GB leg, ≈30 s on 6 GB), plus a multi-GB
write into a 95 %-full disk.
**Change, three commits:**
1. Replace the baseline/verify pair of full digests with a `(st_size, st_mtime_ns)` snapshot (`files.stat_snapshot`),
   re-statted after the producer; hash only files whose stat changed, then raise on a mismatch as today.
2. Stage an immutable run source by **symlink** into the work dir (the pattern already used at
   `analysis/runs/trajectory_header.py:78-80` for MDAnalysis' `*_offsets.npz`), keeping `copy2` for a source outside
   the run (the run's durable `sources/` copy stays real, and is the link target). `files.safe_files` already skips
   symlinks, so produced outputs are unchanged. Update the coordinator's `copied_bytes` charge to what the attempt
   actually stores.
3. Launch with `sys.executable` instead of `shutil.which('python', PATH)` (analysis_coordinator.py:407) and record the
   interpreter on the task.
**Acceptance:** a staged attempt holds links, not copies (`lstat`), a producer that writes to a staged source is refused
by the stat guard (test with a deliberately writing producer), a second attempt of the same kind stages the same set
with no new durable copy, `test_analysis_self_contained.py` and `test_analysis_recompute.py` pass unchanged; every
touched kind's JSON identical on a replay; `test_operations.py::test_async_analysis_is_idempotent_and_preserves_sources`
**still xfails** (its route was deleted in the 2026-11-13 audit; if it starts xpassing that is a finding, not a flake).
**Risk to numbers:** none for the published files. The one real risk is a producer writing through a link — hence the
stat guard lands first, in its own commit.

#### S3 · Lane C1 — frame-series: indexed reads, one atom pass
**Write scope:** `packages/core/src/dashboard/analysis/runs/frame_series.py`,
`packages/core/src/dashboard/analysis/runs/structures.py` (only `series_pdb`/`structure_records` internals),
`packages/core/tests/unit/test_frame_series.py`.
**Measured problem:** the build loop decodes **every frame of the selected window** to keep ≤240 (measured 1.06 s vs
0.01 s for the sampled indexed reads on a 20 021-frame file — 100× on the read step), and formats every atom **twice**
in Python (`_frame_atoms` 2.96 µs/atom + `structure_records` 5.58 µs/atom ⇒ **21.4 s for 240 models × 10 427 atoms**,
GIL-held).
**Change:** iterate `indices` with indexed reads (the offset cache is already proven in `trajectory_overview`), keeping
the sequential pass **only** for `pbc: nojump` (history-dependent); hoist the per-atom invariants (name/residue/residue
id strings, record prefix, atomistic-vs-bead columns) once per series and format each model's coordinates with a
template, so one pass builds the file instead of two per-atom loops.
**Acceptance:** `run-frames.pdb` **and** `frames.json` byte-identical for views `none`, `mol`, `res`, `atom`, `whole`,
`nojump`, `cluster`, with `center`/`fit` on and off, on the BIG corpus and on a real CG `md.xtc`; the single-structure
path through `structure_records` (run-view `/structure`) byte-identical too; `test_frame_series.py` unchanged and green.
**Risk to numbers:** medium (transform order); mitigated by the byte comparison over all seven PBC modes.

#### S4 · Lane C2 — vectorise the per-frame term loops
**Write scope:** `packages/core/src/dashboard/analysis/runs/dihedral_fit.py`,
`packages/core/src/dashboard/analysis/runs/bonded_estimate.py`,
`packages/core/src/dashboard/analysis/runs/bartender_fit.py`,
`packages/core/tests/unit/test_dihedral_fit.py`, `packages/core/tests/unit/test_bonded_estimate.py`,
`packages/core/tests/unit/test_bonded_fitting.py`.
**Measured problem:** `measure_torsions` calls `torsion_deg` per dihedral per frame — **20.02 s → 1.11 s (18×)** on the
real 20 001-frame `mapped.xtc`; `pair_series` is a per-pair Python norm loop (2×); `bartender_fit` reads `lig.xtc`
twice and loops per frame × per ring pair.
**Change:** read each frame once, gather the four (or two) atom rows as one array and evaluate all terms per frame as
one vector op; keep `torsion_deg` as the oracle the differential test calls; in `bartender_fit`, accumulate ring-pair
centres in the pass it already makes instead of a second full read.
**Acceptance:** `dihedral-fit.json`, `bonded-cross-check.json` and the BARTENDER records byte-identical on the real
mapped leg; a test asserting the vectorised angles equal the per-term `torsion_deg` results exactly (they are the same
float64 operations in the same order; if they differ, the order changes and the lane stops); existing tests green.
**Risk to numbers:** low (same arithmetic; the JSON is rounded to 6 dp and must still match).

#### S5 · Lane D — EDR reads: ask for the terms each consumer records, overlap the legs
**Write scope:** `packages/core/src/dashboard/analysis/runs/trajectory_overview.py`,
`packages/core/src/dashboard/analysis/runs/equilibration_traces.py`,
`packages/core/src/dashboard/analysis/runs/energy_conservation.py`,
`packages/core/tests/unit/test_run_trajectory_overview.py`,
`packages/core/tests/unit/test_equilibration_traces.py`,
`packages/core/tests/unit/test_energy_conservation.py`.
**Measured problem:** `read_energy` selects every menu index and summarises every term. On a 62 MB AA EDR: 46 terms =
3.71 s `gmx energy` + 1.19 s parse = 4.90 s, versus 3 terms = 1.59 s (3.1×). `equilibration-traces` keeps
`TRACE_TERMS` (3) and `energy-conservation` keeps `SERIES_TERMS` (5), but both pay for all 46. Separately,
`trajectory-overview` runs `_energy` and `_stages` back to back although they are independent, and `_stages` runs its
legs sequentially (two `gmx` calls each, ~0.6 s startup apiece).
**Change:** `read_energy(edr, work, terms=None)` where `None` keeps today's all-terms behaviour; a unique temp XVG name
per call (today's `.gmx-energy.xvg` is a fixed name, so a pool would collide); `equilibration_traces` and
`energy_conservation` pass their own term lists; `trajectory_overview` runs `_energy` and `_stages` on two threads and
`_stages`' legs on a small pool. `trajectory-overview` keeps the **all-terms** read: its record publishes the shape of
the whole EDR, so narrowing it would change the JSON — that is not this round's business (see *Not in this plan*).
**Measured gain:** equilibration-traces 7.6 s → ~2.5 s; energy-conservation 6.0 s → ~2.5 s; overview on the small CG
run 8.6 s → ~6 s (the EDR read and the stage traces overlap; the AA overview's ~4.5 s all-term read is unchanged).
**Acceptance:** the three JSONs byte-identical on AA and CG replays; `test_energy_conservation.py` and
`test_equilibration_traces.py` unchanged; a test that two concurrent `read_energy` calls in one work dir produce two
XVGs and the same result.
**Risk to numbers:** none (the same terms are selected for the same consumer).

#### S6 · Lane E — batched carbohydrate geometry, one pass per trajectory
**Write scope:** `packages/core/src/dashboard/models/sugars/coords.py`,
`packages/core/tests/unit/test_sugar_coordinates.py` (new),
`packages/validation/src/detergent_validation/analysis/runs/consistency.py`,
`packages/validation/src/detergent_validation/analysis/runs/mapping_consistency.py`,
`packages/validation/src/detergent_validation/analysis/sugar_ensemble.py`,
`packages/validation/tests/unit/test_consistency_cg_samples.py`,
`packages/validation/tests/unit/test_consistency_displacement.py`,
`packages/validation/tests/unit/test_consistency_report.py`,
`packages/validation/tests/unit/test_mapping_consistency.py`,
`packages/validation/tests/unit/test_sugar_ensemble.py`.
**Measured problem:** `mapping-consistency` opens six passes over three files (120 072 frame decodes, ~1.7 s of pure
duplicate decoding) and calls `sugars.coordinates()` per frame (128–190 µs/frame ⇒ 2.6–3.8 s per 20k frames); its
batched equivalent computes the same 20k frames in 0.021 s (~120×). `pair_distances` is a per-pair Python loop (~50×).
**Change:** add `coordinates_many(data, frames, …)` beside `coordinates` in `coords.py` (sparse atom→bead weight matrix,
ring dilation and virtual sites as array ops), with `coordinates` kept as the reference; return samples **and** means
from one read per side in `consistency.py`; vectorise `sugar_ensemble.pair_distances`. Public per-frame readers keep
their signatures and `stride`/`limit` semantics.
**Acceptance:** `mapping-consistency.json` byte-identical on the real Glucose CG run (AA + CG sides, bead displacement,
bonded terms); `coordinates_many` equals `coordinates` on every frame of the real AA trajectory (exact float64
equality after the same ring arithmetic; the failing frame stops the lane); `10.9 s → ~3 s`; validation unit tests green.
**Risk to numbers:** low–medium (reimplementation); the frame-by-frame equivalence test is the gate.

### Wave 2 (one lane, depends on S6's `coordinates_many`)

#### S7 · Lane F — surfaces: one extraction pass, bounded envelope; osmotic and overlap loops
**Write scope:** `packages/validation/src/detergent_validation/analysis/runs/surfaces.py`,
`packages/validation/src/detergent_validation/analysis/runs/osmotic_pressure.py`,
`packages/validation/src/detergent_validation/analysis/runs/overlap.py`,
`packages/validation/tests/unit/test_surfaces.py`,
`packages/validation/tests/unit/test_osmotic_pressure.py`,
`packages/validation/tests/unit/test_overlap_analysis.py`,
`packages/validation/tests/unit/test_overlap_reader.py`.
**Measured problem:** `surfaces.generate` decodes the AA trajectory three times (AA, Mapped raw, Mapped ring-scaled:
80 024 frame reads and writes, 13.9 s serial) and calls `coordinates()` per frame for the mapped variants; `envelope`
evaluates every sphere over the whole 3-D grid (2 000 beads / 2.86 M cells = **113 s**); `osmotic-pressure` rebuilds an
`AtomGroup` and calls `center_of_mass()` per molecule per frame (188 µs/frame at 5 molecules); `overlap` seeks per frame
and does a per-pair norm (1.85 s/side).
**Change:** one AA pass writing AA + both mapped variants (with `coordinates_many`), so the AA file is decoded once; keep
the thread pool over `gmx sasa` legs and the deterministic join order; evaluate each envelope sphere only inside its own
bounding sub-box (outside it the contribution is negative, so the level-0 field is unchanged); precompute per-molecule
indices and use one gather + mass-weighted einsum for the COM; sequential iteration + one vector op per frame in
`overlap`. **Not** changing the reviewed SASA knobs, the extraction thread model, or any sampling.
**Acceptance:** `metadata.json` (`commands`, `source_sha256`, statistics), `surface-comparison-aa-cg.json` and each
variant's `surface.xtc`/`surface.gro` sha256 identical on a real CG+AA replay; `surfaces` wall 18.8 s → ≤15 s;
osmotic and overlap records identical (osmotic has no attempt in this workspace — its record is compared on the test
fixture plus a synthetic condition, and that is stated); `envelope` compared cell-for-cell against the current
implementation on the sugar systems and on synthetic bead clouds.
**Risk to numbers:** low–medium (surfaces extraction rewrite); the mesh and the SASA files are the gate.

### S8 · Integrator — review, commit, measure, close
1. Read `git status` in full before the gate; every path is either a lane's named file or restored/explained (the
   pre-existing `molecules/Glucose/*` deletions are not this round's and stay untouched).
2. Review each lane's diff; verify its acceptance evidence (byte-identical artifacts, the timing table).
3. Commit per slice, in dependency order (S2's stat guard before its links; S6 before S7), each with its measured
   before/after in the message; `scripts/gate_commit.sh <msg> <paths…>` runs the fast tier + ruff over the named paths.
4. Run the fast tier, `test_agents_contract.py`, `test_test_areas.py`, and one timed live replay per touched kind on the
   real workspace runs (read-only; copies under `/tmp`).
5. Update `docs/HANDOFF.md` (state, measurements, open items) and `AGENTS.md` *Invariants* for the staging rule S2
   introduces; `git add -f` this plan if it is revised (docs/plans is gitignored but tracked by force).
6. `scripts/mutation_check.py` after the last commit; record surviving mutants.

## Delegation map

| Wave | Lane | Slice | Write scope (disjoint) | Depends on | Owned check |
| --- | --- | --- | --- | --- | --- |
| 1 | A | S1 | pdc `pdc_assessment.py` + its unit test | — | `-m 'pdc and not slow'` |
| 1 | B | S2 | core `worker.py`, `files.py`, `analysis_coordinator.py` + staging tests | — | `-m 'analysis and not browser and not slow'` |
| 1 | C1 | S3 | core `frame_series.py`, `structures.py` + `test_frame_series.py` | — | `-m 'analysis and not browser and not slow'` |
| 1 | C2 | S4 | core `dihedral_fit.py`, `bonded_estimate.py`, `bartender_fit.py` + their tests | — | `-m 'bonded and not browser and not slow'` |
| 1 | D | S5 | core `trajectory_overview.py`, `equilibration_traces.py`, `energy_conservation.py` + tests | — | `-m 'analysis and not browser and not slow'` |
| 1 | E | S6 | core `sugars/coords.py`, validation `consistency.py`, `mapping_consistency.py`, `sugar_ensemble.py` + tests | — | `-m 'validation and not browser and not slow'` |
| 2 | F | S7 | validation `surfaces.py`, `osmotic_pressure.py`, `overlap.py` + tests | S6 | `-m 'validation and not browser and not slow'` |
| — | lead | S8 | `docs/HANDOFF.md`, `AGENTS.md`, this plan | all | fast tier + contract tests + gate + mutation |

Lane rules (from the proven workflow for this repository): a lane edits only its write scope, touches no
`tests/harness/` file, adds no dependency, commits nothing (`git add`/`commit` belongs to the integrator), runs its
tests serial with a private `MPLCONFIGDIR`, and returns: the diff summary, the byte-comparison commands and results, the
before/after timing table, and any acceptance point it could not meet (with the reason) rather than a weakened test.

## Evidence (2026-11-18 audit, per-lane `[M]` measured / `[R]` code-read)

- **Shared staging:** copy 0.24 s + hash 1.02 s + verify 1.00 s per 465 MB `[M]`; 786 MB hash 1.71/1.76 s, copy 0.43 s
  `[M]`; ≈5 s/GB/attempt, ≈9.4 s/GB for a kind that also stages a shared AA reference `[M]`.
- **gmx startup:** `gmx --version` 0.59–0.66 s `[M]`; pdc-structure makes 8–9 calls ⇒ 5–6 s fixed `[M]`.
- **pdc contact graph:** 44.2 ms/frame at 100 detergents, 3.59 s at 800 `[M]`; `query_pairs` + union-find 16× end to end
  (9.33 s → 0.57 s on the 200-frame MIC model), identical cluster series `[M]`.
- **pdc protein test:** 191 ms/frame at 100 detergents × 8 000 protein beads vs 8.1 ms with one KD-tree query `[M]`
  (re-measured for this plan).
- **frame-series:** full-window decode 1.06 s vs 0.01 s for sampled frames `[M]`; formatting 2.96 + 5.58 µs/atom ⇒
  21.4 s for 240 × 10 427 `[M]`.
- **per-term loops:** `measure_torsions` 20.02 s → 1.11 s `[M]`; `pair_series` ~2×; `overlap` 1.85 → 0.95 s/side `[M]`.
- **EDR:** 46 terms 4.90 s vs 3 terms 1.59 s `[M]`; overview 8.61 s of which `_energy` 4.68 s, `series_summary` 1.28 s,
  PNG 1.07 s `[M]`; equilibration-traces 7.6 s, energy-conservation 6.0 s published `[M]`.
- **mapping-consistency:** 10.86 s replay, 120 072 frame decodes, `coordinates` 128–190 µs/frame `[M]`; batched 0.021 s
  for 20k frames `[M]`.
- **surfaces:** published 18.8 s; extraction 13.9 s serial (AA 2.53 + mapped 4.71×2 + CG ~2) `[M]`; `gmx sasa` 4.85 s +
  0.73 s per variant, pool 1.85× `[M]`; `envelope` 45 atoms 0.04 s, 2 000 beads 113 s `[M]`.
- **osmotic:** 188 µs/frame (5 molecules); gather 61.9 µs (3.0×) `[M]`.
- **Concurrency:** one analysis per run, `max_concurrent_analyses=2` host-wide `[R]`; each attempt a separate
  `python -m dashboard.analysis` subprocess launched from PATH python `[R]`.

## Not in this plan (considered, and why)

- **`trajectory-overview`'s all-term EDR record.** Narrowing it would change `trajectory-overview.json` (the record
  publishes every term's summary and the drawn terms' columns). The measured 3.1× needs a contract decision by the user,
  not a performance slice. Threading and the consumer-specific term lists (S5) are the number-preserving part.
- **A `cKDTree` for `trajectory_overview._aggregates`.** The 2026-11-17 plan already measured a periodic-image KD-tree
  on the real pdc micelle (347k atom pairs, slower than the sphere prefilter it replaced), and the prefilter is 4.8×
  over the old matrix. Reopening it needs triclinic minimum-image verification for a bounded gain; S1 gets the clean
  KD-tree win where coordinates are already unwrapped.
- **Merging pdc-structure's two `gmx select` calls.** The cluster index is built from `all` + detergent (trjconv asks
  `1\n0\n`), the contacts index from protein + detergent (mindist asks `0\n1\n`); one merged index changes the group
  numbering and the recorded prompt answers for ~0.6 s. The wrong-group failure mode is silent, so the gain does not
  buy the risk.
- **Sampling changes** (`MAX_FRAMES`, stride, SASA frame subsampling, the extraction window). They change every
  published number and break pinned tests; they are the user's science decision.
- **numba / Cython.** Measured <10 % after S3–S6 (the floor is XTC decode ~0.85 s/20k frames and `gmx` startup), and the
  scientific stack is host-provisioned rather than declared. Compilation would add a build step for no measured need.
- **A direct `.edr` parser or a new dependency** for the AA overview: still the prior plan's "not yet justified"
  decision; the need is one analysis kind.
- **Raising `max_concurrent_analyses`.** Per-run single-analysis is load-bearing for cancel and the Recompute chain;
  disk is 95 % full and each extra attempt multiplies the staging cost S2 removes.

## Execution record

Wave 1 landed 2026-11-18 as six commits, each through `scripts/gate_commit.sh` (fast tier + ruff over its paths). The
fast tier was 3104 passed / 1 xfailed on every gate run; `ruff` clean on every named path; `test_test_areas.py`,
`test_module_layout.py` and `test_agents_contract.py` pass.

| slice | commit | measured before -> after (same staged trees) | numbers |
| --- | --- | --- | --- |
| S2 engine staging | `b8ff2df` | staging 1.64 s -> 0.0004 s; whole attempt 1.76 s -> 0.016 s (322 MB production xtc) | `ff-interactions.json` byte-identical through `worker.execute` |
| S3 frame-series | `9674954` | real 20 021-frame series 1.326 -> 0.176 s; 240 x 10 427 series 22.69 -> 9.49 s | `run-frames.pdb` + `frames.json` identical, 42 views x 2 corpora |
| S4 bonded terms | `b0a3e17` | `measure_torsions` 20.55 -> 2.32 s; `dihedral-fit` 20.07 -> 2.43 s; bartender 8.71 -> 7.53 s | three JSONs byte-identical; BARTENDER run for real |
| S5 energy reads | `091311c` | AA overview 13.43 -> 8.87 s, CG 16.97 -> 9.73; AA eq-traces 7.40 -> 1.63, CG 3.30 -> 1.50; AA energy-conservation 10.86 -> 4.59, CG 5.75 -> 3.04 | three JSONs byte-identical on both runs |
| S6 mapping consistency | `3fa907b` | publish 10.92 -> 4.37 s; frame decodes 120 072 -> 80 044; `coordinates_many` 0.92 us/frame vs 57.0 | report byte-identical; per-frame equality on 2 x 20 001 frames |
| S1 pdc criterion | `8875dd1` | graph 40.9 -> 2.8 ms/frame (100 detergents), 2 651.9 -> 26.7 (800); protein 186.0 -> 5.6 ms/frame | `pdc-structure.json` byte-identical on a synthetic leg; 500-system fuzz |

Two-decimal absolute seconds drift with host load (a simulation was running throughout); the same-invocation ratios
are the reliable figures, and every byte comparison was done in one invocation per slice.

### Deviations from this plan, and why

- **S2 is one commit, not three.** The stat guard and the links interleave in `worker.py`; a hand-built intermediate
  state would have been untested. The commit names the three changes and the ceiling, and the guard landed with the
  links in the same tree, in the order the plan required (guard first *in the code*, links after it).
- **S1 uses scipy's `connected_components` and a slack-plus-numpy decision.** A bare `query_pairs(contact_nm)` is not
  bit-exact at the cutoff (scipy's C distance disagrees with `np.linalg.norm` in the last bits), and the plan's
  prescribed `query(k=1, distance_upper_bound=nextafter(reach, inf))` loses a bead at exactly `reach`. The search runs
  at `contact_nm*(1+1e-12)` and numpy decides; the Python union loop was 19 of 22 ms at 100 detergents, so the
  components come from scipy. All three are pinned by the fuzz test.
- **S5's unique temp XVG had to release its placeholder.** `mkstemp` pre-creates the file, and GROMACS backs up an
  existing output as `#<name>.1#`; that backup is not a hidden name, so the worker published it as a 0-byte artifact.
  Found by the end-to-end replay through the real subprocess (the six JSON comparisons could not see an extra output),
  fixed by unlinking the placeholder before `gmx energy` writes and verified by re-running the replay: output set and
  all three artifacts identical to HEAD.
- **The staging invariant went to `PROJECT_GUIDE.md`, not `AGENTS.md`.** `AGENTS.md` is exactly at its 150-line
  contract budget (`test_agents_contract.py`); the rule is "how a subsystem works", which that file's own header sends
  to the guide. It is under *Run accounting: progress, analyses, structure*.
- **No completed pdc run exists in this workspace**, so S1's end-to-end proof is a synthetic 200-frame leg (100
  detergents, 8 000 protein beads), as the plan said. The workspace also gained and lost runs during the round (the
  live dashboard was in use), so replays name the runs that exist now.

### Wave 2 — S7 built (2026-11-18)

S7 landed in commit `e568a93` (`surfaces` one AA-derived pass for the mapped variants + bounded envelope, `osmotic`
gather/einsum, `overlap` vector op). Measured on the real `Glucose-CG-200ns-20261116` + pinned AA reference:

| item | before -> after |
| --- | --- |
| `surfaces` wall (published 18.8 s) | 17.2 s HEAD -> **15.0 s** idle host, 16.8 s under load |
| mapped-variant extraction (raw + ring-scaled) | 4.3 + 5.2 s -> **7.9 s for both** (one AA decode) |
| `envelope`, 2 000 beads / 3.2 M cells | 118.82 s -> **0.36 s** (326x), vertices/faces cell-equal |
| `osmotic` producer, 2 000 frames / 5 molecules | 0.922 s -> **0.592 s**; the COM arithmetic 111.7 -> 12.7 us/frame |
| `overlap` publish | 5.00 s -> **2.57 s**; series pass 4.82 -> 2.47 s |

Byte proof: **34/34 produced files**; `metadata.json` and `surface-comparison-aa-cg.json` raw-identical; every
variant's `surface.xtc`, `surface.gro`, `connolly.pdb` and `vdwradii.dat` sha256-identical; `sasa.xvg` numeric bodies
identical. The eight `*.log` files differ, and a HEAD-vs-HEAD control differs on the same files (and the XVG comment
blocks) — GROMACS writes a creation timestamp and a random quote into them; the control is what separates that from
this change.

**The single AA decode could not use `coordinates_many`.** The mapped variants pass the trajectory's float32
`frame.positions` to `sugars.coordinates`, whose bead centre of geometry is a **float32** mean; `coordinates_many`
promotes the block to float64. On the real 20 001-frame reference the two disagree on 18 378 of 20 001 frames after the
timestep's float32 store (19 799 for the ring-scaled path), and the written `surface.xtc` bytes change. The slice
therefore keeps the per-frame `coordinates` oracle and buys the one-decode saving only for the two mapped variants;
`coordinates_many` keeps its proven role where its caller already hands the oracle float64 (`mapping-consistency`).
The dtype sensitivity is a real property of `coordinates`, not a defect to "fix" silently — a future float64 batch
for surfaces would be a published-numbers change.

Remaining measured levers, none in this round: `mapping-consistency` still reads the CG trajectory twice (the second
read is core `bonded_terms.measure`); `surfaces` still decodes the AA file twice (once for its own variant, once for
the mapped pair) because two MDAnalysis readers of one file must not overlap, and its tail is the mapped variants'
`gmx sasa` legs after a serial 7.9 s pass.
