# Plan: accelerating `pdc-structure` (and a GMXLens evaluation)

Status: **R1 built and verified 2026-11-26; R2 researched only.** Question: where does the ~4.5 min of `pdc-structure`
go, and is [GMXLens](https://github.com/drvahidzarezade-Bioinf/gmxlens) useful for it? Answer: the cost is not the
numerics, it is `gmx mindist` counting water-bead contacts; R1 cuts an attempt from **224 s to ~78 s** (measured
**108.5 s → 53.5 s** on the OG run, with every contact, RDF, aggregation and shape number identical), and the only
published number it can move is one water–head count in one frame (one bead pair, GROMACS' own undercount). R2 could
take the DM attempt to ~45 s. GMXLens is **not worth adopting**; two of its ideas are already the repo's practice and
one (autocorrelation-corrected error bars) is a science decision, not a speed one.

## 1. What was measured, and where

Live attempt: `DM_2ydo_144_libconf_500ns-2`, attempt
`analyses/pdc-structure/0001-20261125` — the run in HANDOFF's "4.5 min" sentence
([`docs/HANDOFF.md:248`](../HANDOFF.md)). Its own manifest dates it **224.4 s** (`started_at` 16:46:10.387,
`ended_at` 16:49:54.781, `manifest.json`); the 4.5 min figure evidently included queue/staging.

Host: 72 cores, 251 GB RAM, `gmx` 2026.3 (mixed precision, MPI-only build), GROMACS env `OMP_NUM_THREADS=8`. **No
CUDA device is reachable from this session** (`nvidia-smi` cannot talk to the driver), although the run's own stage
record names an `NVIDIA RTX 5000 Ada Generation` (`stages/06_assessment` `resource_usage.gpu`), so GPU timings are
the one thing not measurable here.

Method: every command was re-run on the attempt's published `sample.xtc` (33 MB, 199 frames, 31 801 atoms, box
15.66 × 15.66 × 14.68 nm), copied to `/tmp`, with the exact argv recorded in `pdc-structure.json`
(`commands`, `sampling`); the extraction alone was re-run from the run's `whole.xtc` (3.44 GB, 20 001 frames) read
in place and written to `/tmp`. The producer is
[`packages/pdc/src/detergent_pdc/analysis/runs/structure.py`](../../packages/pdc/src/detergent_pdc/analysis/runs/structure.py).

| step | one-shot wall | share | how |
|---|---|---|---|
| `gmx mindist` water–head (`-d 0.6`, 28 772 W vs 1 152 head beads) | **108.0 s** | 48 % | measured |
| `gmx mindist` water–tail (28 772 vs 432) | **41.6 s** | 19 % | measured |
| `gmx trjconv` extraction from `whole.xtc` (stride 101) | **44.4 s** | 20 % | measured (42.3 s on a repeat) |
| `gmx rdf` ×4 (protein→head 2.31, protein→tail 1.73, head–head 3.58, tail–tail 1.86) | 9.5 s | 4 % | measured |
| `gmx mindist` protein–head 2.71, protein–tail 1.78, pooled protein–detergent 3.24 | 7.7 s | 3 % | measured |
| `gmx trjconv -pbc cluster` on the sample | 2.6 s | 1 % | measured |
| MDAnalysis aggregation pass (`_measure`, `structure.py:431`) | 2.0 s | 1 % | measured (199 frames, 14.5 ms/frame incl. decode) |
| `gmx gyrate` | 1.2 s | 0.5 % | measured |
| `gmx select` ×2 (index files for the mindist calls) | 1.3 s | 0.6 % | measured |
| five PNGs (`write_figures`, `structure.py:611`) | 1.7 s | 0.8 % | measured |
| 10 XVG parses + `pdc-structure.json` | 0.1 s | — | measured |
| **sum** | **220.1 s** | | vs 224.4 s recorded; the 4 s gap is interpreter start + staging, inferred |

Two measured facts that reframe the question: (a) MDAnalysis decoding is *not* the cost — 199 frames decode in
0.45 s; (b) `gmx mindist -d` costs what the group product implies (28 772 × 1 152 = 33 M pairs/frame here,
0.54 s/frame), not what a neighbour search would — which is why two calls are 67 % of the attempt.

## 2. GMXLens, feature by feature

Read at commit `9503753` (2026-08-25). MIT (`LICENSE`), version 0.3.0; dependencies include `PySide6`, `mdtraj`,
`pymbar`, `pandas` ([`pyproject.toml`](https://github.com/drvahidzarezade-Bioinf/gmxlens/blob/main/pyproject.toml)).

| GMXLens feature (source) | verdict | why here |
|---|---|---|
| Batched contact-matrix GEMM (`_contact_freq_blocks`, [core.py:3655](https://github.com/drvahidzarezade-Bioinf/gmxlens/blob/main/gmxlens/analysis/core.py#L3655); `contact_pairs`, [gpubackend.py:136](https://github.com/drvahidzarezade-Bioinf/gmxlens/blob/main/gmxlens/gpu/gpubackend.py#L136)) | **borrow the framing, not the code** | float32 `A·Bᵀ` with no PBC/minimum image and CA-only selection; on this system it would need unwrapping and would move counts at the cutoff. The real fix is elsewhere: `scipy.spatial.cKDTree` (see R1) |
| Memory-bounded block sizing (`max_bytes=256 MB`, `ComputeContext.rows_per_block`, [compute.py:300](https://github.com/drvahidzarezade-Bioinf/gmxlens/blob/main/gmxlens/compute.py#L300)) | not needed | 251 GB RAM, and the per-frame streaming already in `_measure` is the same idea |
| Streaming reductions, no `(frames, atoms, 3)` array ([`_memsafe.py:8`](https://github.com/drvahidzarezade-Bioinf/gmxlens/blob/main/gmxlens/analysis/_memsafe.py#L8)) | already the repo's practice | `_measure` walks frames lazily |
| One-decode trace cache (`build_trace`, [core.py:414](https://github.com/drvahidzarezade-Bioinf/gmxlens/blob/main/gmxlens/analysis/core.py#L414), `~/.gmxlens/trace_cache`) | not applicable | sample decodes in 0.45 s; the 20 analyses it serves do not exist here |
| Frame-index cache (`_offsets.npz` beside the trajectory, [index_traj.py:22](https://github.com/drvahidzarezade-Bioinf/gmxlens/blob/main/gmxlens/io/index_traj.py#L22)) | **idea useful, location forbidden** | AGENTS.md forbids a tool cache in the run tree; the sample (33 MB) is far below its 100 MB threshold; and the source scan it avoids is better attacked by time-range seeking (R2) |
| GPU SASA, Shrake–Rupley ([gpubackend.py:82](https://github.com/drvahidzarezade-Bioinf/gmxlens/blob/main/gmxlens/gpu/gpubackend.py#L82), CPU fallback with `cKDTree` at [core.py:2996](https://github.com/drvahidzarezade-Bioinf/gmxlens/blob/main/gmxlens/analysis/core.py#L2996)) | not applicable | `pdc-structure` computes no SASA; `surfaces` has its own envelope |
| Autocorrelation-corrected SEM (Sokal window, [core.py:2199](https://github.com/drvahidzarezade-Bioinf/gmxlens/blob/main/gmxlens/analysis/core.py#L2199); write-up generator [methods_stats.py:37](https://github.com/drvahidzarezade-Bioinf/gmxlens/blob/main/gmxlens/interpret/methods_stats.py#L37)) | **borrow later, as an option** | ~40 lines of numpy over the existing series; it *changes* published `sem`, so it is the user's call, not a perf tweak |
| Multi-replicate study orchestration ([study/orchestrate.py](https://github.com/drvahidzarezade-Bioinf/gmxlens/blob/main/gmxlens/study/orchestrate.py)) | not applicable | the dashboard already orchestrates runs |
| PySide6 desktop GUI ([gui/app.py](https://github.com/drvahidzarezade-Bioinf/gmxlens/blob/main/gmxlens/gui/app.py)) | not applicable | Flask dashboard; a second workbench would be a second source of truth |
| MM-GBSA, claims/verdicts, ligand detection ([io/loader.py:132](https://github.com/drvahidzarezade-Bioinf/gmxlens/blob/main/gmxlens/io/loader.py#L132)) | not applicable | protein–ligand oriented; its residue tables do not even know Martini `W`/head/tail names |

**Adopt the package itself? No.** It is a second workbench (GUI, own CSV/JSON schema, own provenance), its contact
code is not PBC-aware for a periodic micelle, it has no test directory, and it would add `PySide6`/`mdtraj`/`pymbar`
to a repo whose production dependency set is deliberately GROMACS + the scientific stack. Borrow algorithms only.

## 3. Ranked recommendations

### R1 · Replace the water-bead `gmx mindist` counts with one `cKDTree` pass — **built**, 224 s → ~78 s
**Measured**: a per-frame `cKDTree` over the 28 772 W beads with `boxsize`, summing `query_ball_point(..., 6.0 Å)`
for head and tail, took **2.9 s for both groups (14.5 ms/frame)** and reproduced the published counts **199/199
frames for water–tail** and **198/199 for water–head**. The single differing frame (157) is a `gmx mindist`
*undercount*: published 3 939, brute-force minimum-image double-precision 3 940, KD 3 940; no pair lies within
0.019 Å of the cutoff, so it is not a tie. Cost removed: 149.6 s of 224 s.

**Built** in [`structure.py`](../../packages/pdc/src/detergent_pdc/analysis/runs/structure.py): `_measure` collects
the W/head/tail indices and computes the two water groups with `periodic_contact_counts` (a periodic `cKDTree` plus
a numpy minimum-image cutoff decision); `_contact_groups` reads those counts and stops issuing the water `mindist`
calls; the protein groups and the pooled v1 count stay on `gmx mindist -on`; a triclinic box (no rectangular
`boxsize`) keeps GROMACS for every group. `_contact_groups` also names `mindist`'s `-o`/`-od` outputs and unlinks
them, so the stray `mindist.xvg` / `#mindist.xvg.N#` artifacts are no longer published by the remaining calls.

**Verified on the OG run** (`OG_2ydo_130_libconf_500ns_2nm_gap`; its manifest settings were repaired from its own
`inputs/pdc-settings.json`, recorded in HANDOFF): a replay of the producer
on the same staged sources and the same `contact_nm: 0.5` payload took **53.5 s**, against the published attempt's
**108.5 s**. Every contact group's mean, SEM and per-frame series, the pooled count, all four RDF curves, the
aggregation numbers and the shape numbers are **identical**; the only record changes are the method/caveats text,
the water groups' `tool`, and the removal of the three water `mindist` commands. The water/tail group matched
GROMACS 199/199 frames here too. The DM run's one-pair `mindist` undercount is disclosed in the record's caveat, so
the "numbers do not change" rule is not silently broken: the KD count is the more correct minimum-image count and
the difference is one pair.

**Risk (now handled)**: the repo's "numbers do not change" gate would otherwise fail on that one pair. The record
states the implementation and the possible one-pair difference; no other number moves.

### R2 · Extract the sample in parallel time ranges + `trjcat` — 44.4 s → 11.7 s
**Measured**: `gmx trjconv -b/-e` *does* skip frames without decoding (last 10 % of `whole.xtc` in 5.4 s, not 44 s),
while `-dt`/`-skip` decode all 20 001 frames (42.9 s each). Four grid-aligned ranges (`0–126 249`, `126 250–252 499`,
`252 500–378 749`, `378 750–500 000` ps) run as four concurrent processes: **11.72 s wall**, parts 50/50/50/49 frames,
`gmx trjcat` merge 1.4 s, `-pbc cluster` 2.4 s, and the resulting `gyrate.xvg` data rows are **identical to the
published 199/199** (max |ΔRg| = 0). Saving: ~31 s.

**Touch**: `run` (`structure.py:820-833`) and `sample_arguments` (`:104`): partition the frame grid
(`stride × dt_ps`, from `trajectory_header.read`) into `K = 4` ranges, spawn `gmx trjconv` per range with
`-b/-e/-dt`, merge with `gmx trjcat`, then cluster as today; record every command in `commands`. Fall back to the
single pass when `dt_ps`/`first_ns` is absent (the `-skip` path) or the sample is smaller than `K` chunks.

**Verify**: `gmx check` shows 199 frames and the same first/last times; `gyrate.xvg`, `rdf-*.xvg` data rows and
`pdc-structure.json` identical to the pre-change replay (measured true for the split above).

**Risk**: the split's frame phase depends on `-b` landing exactly on the sample grid; a boundary frame can be
duplicated (an earlier attempt with non-aligned ranges produced 200 frames — caught by `gmx check`, not by eye). The
seeking behaviour is GROMACS 2026.3's, pinned in `config/tools.json`.

### R3 · Do nothing yet on the remaining 17 s
`gmx rdf` (9.5 s) cannot be merged: GROMACS rejects multiple `-ref` selections (`Too many values`, measured), so
the four calls are four passes over a 33 MB file. Figures 1.7 s, MDAnalysis 2.0 s, gyrate 1.2 s, cluster 2.6 s, the
two `select` calls 1.3 s — each is already at the noise floor of a 45 s attempt after R1+R2. A GPU path is not
recommended: no CUDA device is reachable here, the KD pass is already 14.5 ms/frame on one core, and GMXLens' GPU
kernels are float32/PBC-free. Autocorrelation-corrected SEMs are worth doing as a *science* question, with their own
plan and re-baselined numbers.

**Projected end to end**: 224 s → ~78 s with R1 (built; measured 108.5 s → 53.5 s on OG, ~2×) → ~45 s with R2
(researched, not built), i.e. 5×, with five PNGs, four RDF pairs and four contact groups unchanged.

## 4. Unknowns and risks

- One attempt was measured; repeats differ by ~5 % (extraction 42.3 vs 44.4 s). The host is shared (72 cores), timings
  ran alone; no thermal/IO control.
- GPU timings are unmeasured (no driver access in this session) even though the run's stage 6 reports an RTX 5000 Ada.
- R1's single-pair difference is a `gmx mindist` undercount, not a KD error, but the repo's byte-identical gate does
  not know that. Deciding to keep `mindist` for water forfeits 67 % of the attempt.
- R2 assumes `dt_ps` and `first_ns` are present; the `-skip` fallback (no time grid) keeps today's single pass.
- Water group size is run-specific: `mindist` is `O(N_W · N_head)` and the KD pass is `~O(N_W log N_W)`, so the win
  grows with box size; a much larger system favours R1 even more.
- GMXLens at 0.3.0 has no tests and one author; anything borrowed must be reimplemented and checked here.
