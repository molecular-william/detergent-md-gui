# Plan: trajectory-overview hot paths (aggregate search, frame access, XVG parse)

Status: implementing (2026-11-17). Evidence: profiling the real analyses on this workspace — the AA overview
(`Glucose-AA-202ns-20261113`, 20k frames) took 18.5 s end to end, of which `gmx energy` + statistics were 11 s; the pdc
micelle overview (`DDM_micelle_192_1conf_1us-2`, 4001 frames, 9028 atoms, 192 detergents) took 91.7 s, of which
`_aggregates` was 80.8 s. A cancelled overview of that same pdc run sat at 32 s in the run record, which is what a
reader saw.

## Slices

### 1. `_aggregates`: test molecule bounding spheres before atom pairs
`analysis/runs/trajectory_overview.py`. The pairwise matrix measured every detergent atom against every other
(2,112² = 4.5M distances per sampled frame, ~420 ms). Two molecules cannot touch unless their bounding spheres do, and
that test is one 192×192 comparison: 2,450 of 18,336 molecule pairs survive it on the pdc micelle. Only those pairs pay
for atom-level minimum-image distances, in bounded blocks so no (atoms × atoms) array is materialised. Both tests are
exact, so the grouping cannot change. A KD-tree over periodic images was measured and rejected: a dense micelle makes
it return 347k atom pairs, slower than the matrix it replaced.

### 2. Frame access: use MDAnalysis' offset cache
`trajectory_overview.run` decoded every frame in the segment so that ~200 sampled ones could be kept, because a seek
without an offsets cache rescans from the file start. MDAnalysis writes `_offsets.npz` beside the trajectory it opened
— in an analysis attempt that is the staged copy in the work tree, never the run — and the first indexed read pays one
header scan. Measured: 4001-frame micelle 3.3 s → 0.17 s for its 201 frames; 20k-frame AA 1.5 s → 0.02 s.

### 3. `readers.xvg_columns`: parse the data block with numpy
The per-line float conversion cost 1.33 s on the 59 MB all-terms XVG an `.edr` read produces; `np.loadtxt` over the
filtered rows does the same job in one C pass. A ragged or malformed file falls back to the per-line reader, and a
data block without legends is still named positionally.

## Not done

- A direct `.edr` reader: it would remove the 0.63 s menu call and the 3.2 s all-term XVG write per EDR (most of the AA
  overview's remaining time), but it is a new binary-format parser or a new dependency, and the measured need (one
  analysis kind) does not yet justify either.
- Vectorising `series_summary` across columns (2.24 s for 46 terms): a second estimator change in one commit, with
  numbers compared against earlier records; follow-up, not this slice.
- The `surfaces` (20 s) and `mapping-consistency` (13 s) producers: different code paths, not profiled.

## Verification

- Equivalence tests: a reference pairwise `_aggregates` against the new search over randomised configurations
  (compact micelle, split threshold, mixed molecule sizes including single-atom ions, a small box that spans faces);
  the XVG fast path against the per-line reader cell for cell, plus a ragged file and a legend-free file.
- Benchmarks: HEAD's implementation and the working tree's on the same staged work trees (old and new code loaded
  from separate trees in separate processes), reporting cold and warm wall time and byte-identical
  `trajectory-overview.json`; plus micro-benchmarks of `_aggregates` per frame and `xvg_columns` on a real 59 MB XVG.
- Existing suite: `packages/core/tests/unit/test_run_trajectory_overview.py`, the analysis area, then the fast tier.

## Measured result (2026-11-17, this box)

HEAD's implementation and the working tree's were run in separate processes against identical staged work trees
(symlinks to the real sources, offsets cache removed before each run), once cold and once warm:

| | before | after | change |
|---|---|---|---|
| AA overview, 20k frames (`Glucose-AA-202ns`) | 13.84 / 12.80 s | 12.62 / 12.09 s | −9% (energy-dominated; 11 s of it is `.edr` reading) |
| pdc overview, 4001 frames / 192 detergents | 85.60 / 87.08 s | 19.90 / 19.59 s | **4.3×** |
| `_aggregates`, one micelle frame | 417.2 ms | 86.0 ms | **4.8×**, identical grouping |
| frame access, AA 20k / pdc 4001 | 0.836 s / 3.259 s | 0.010 s / 0.165 s | 84× / 20× |
| `xvg_columns`, 59 MB / 46-term / 100k-row XVG | 1.19 s | 0.46 s | 2.6× |

`trajectory-overview.json` is **byte-identical** between the two implementations for both runs (207,657 and 20,083
bytes), so every recorded number is unchanged. A fuzz check of the aggregate search against the pairwise reference
over 60 random systems (varied molecule sizes, boxes and thresholds) found no grouping difference.

What remains in the pdc overview is still the aggregate search (191 frames × 86 ms ≈ 16 s): a cell-list or a
molecule-level incremental contact graph would be the next step, and the AA overview is now mostly `gmx energy`.
