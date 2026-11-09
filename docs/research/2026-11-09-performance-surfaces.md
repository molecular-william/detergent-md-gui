# Surfaces generation: cost map, measurements, and a bounded-parallel proposal

Lane C of `docs/plans/2026-11-09-performance-follow-up.md` (section "C. Surface generation"). Evidence gathered
2026-11-09 against two completed runs, read-only. No tracked file was edited; this file is the lane's one artifact.
Nothing was written into `workspace/` or `.bench-surfaces/`, and the dashboard was not touched.

Method: the five source files were copied into a private `/tmp` scratch root (not symlinked into a run tree, so
MDAnalysis' `*_offsets.npz` cache was written only to the scratch copies), then `surfaces.generate`'s phases were
replayed with `time.perf_counter()` around each one. GROMACS is `/usr/local/gromacs/2026.3/bin/gmx`. Host: **nproc
72**, 251 GB RAM, `/tmp` on tmpfs. Totals below are one run each, no repetition (a rerun is ~83 s; variance was not
measured, so treat sub-second numbers as order-of-magnitude).

## 1. What `generate(run)` actually does

`packages/validation/src/detergent_validation/analysis/runs/surfaces.py`

- Opens one `mda.Universe` for the AA pair and one for the CG pair (lines 47-48), checks the CG atom count/names
  against `model.json` (49-50), builds Rowland–Taylor AA radii and Martini CG radii (51-58).
- Builds `variants`: `AA`, `Mapped raw`, `Mapped ring-scaled` (only when `model['rings']`), `Simulated CG` (60-62).
- **Per variant, serial (67-94):** creates `analysis/surfaces/<label>/`, then
  1. iterates a trajectory and writes `surface.xtc` (Mapped variants iterate the **AA** reader and transform each
     frame through `carbohydrates.coordinates`; AA iterates AA; Simulated CG iterates CG), writing `surface.gro`
     from frame 0 and remembering `first[label]` (72-82);
  2. writes `vdwradii.dat` (83);
  3. runs `gmx sasa` over the **whole** trajectory at `-ndots 240`, `-probe PROBE`, `-surface all` (84-87);
  4. runs a second `gmx sasa` over the one-frame `surface.gro` that also writes `snapshot-sasa.xvg` and
     `connolly.pdb` (88-91);
  5. parses `sasa.xvg` into mean/SD/start/end (92-94).
- Then, serial: aligns Simulated CG to Mapped raw (95-96), `envelope()` marching-cubes per variant (97-98), builds
  and writes the Plotly HTML figure (99-125), writes `surface-comparison-aa-cg.json` (126-145), then `metadata.json`
  (146-147). `aa`/`cg` trajectories close in `finally` (148-149).

The kind is `sources_only(surfaces.generate)` (`kinds.py:84-96`), so it receives only `(work)` — no payload and no
progress callable.

## 2. Measured cost

Sources: run `619ab118abd6` AA side (`stages/07_reference/lig.gro`, `lig.xtc`), run `67bc79a995d6` for
`stages/2_mapping/model.json` and `stages/4_CG_sim/prod/lig_CG.{gro,xtc}` — the live LMNG `surfaces` pairing.

| input | atoms | frames | timestep | size |
|---|---|---|---|---|
| `lig.gro` / `lig.xtc` (AA) | 157 | 20 001 | 10 ps (200 ns) | 13 955 560 B |
| `lig_CG.gro` / `lig_CG.xtc` | 23 (4 virtual sites) | 20 001 | 10 ps (200 ns) | 3 764 940 B |

`model['rings']` is true, so four variants run.

| variant | XTC write | of which coordinate transform | `gmx sasa` full | Connolly snapshot | parse | **variant total** |
|---|---|---|---|---|---|---|
| AA | 2.74 s | — | **43.32 s** | 0.59 s | 0.06 s | **46.71 s** |
| Mapped raw | 8.41 s | 5.50 s | 3.35 s | 0.73 s | 0.04 s | **12.53 s** |
| Mapped ring-scaled | 12.47 s | 9.31 s | 3.20 s | 0.68 s | 0.08 s | **16.43 s** |
| Simulated CG | 2.47 s | — | 3.35 s | 0.63 s | 0.06 s | **6.51 s** |

Post-processing: `envelope()` AA 0.40 s, other variants < 0.05 s each; Plotly `make_subplots`+traces 0.09 s; the
`write_html(..., include_plotlyjs=True)` 0.11 s (it embeds Plotly). **Measured generation wall: 83.0 s**, which
matches the plan's "about 90 s" live attempt once the worker's source copy/hash and imports are added.

`gmx sasa` peak RSS on the AA case: **45 760 kB** (measured with `/usr/bin/time -v`). It is effectively one core:
43.45 s wall for the same run. Inference: `gmx sasa` is not domain-decomposed here, so four concurrent processes
occupy about four cores and under 200 MB — trivial beside 72 cores / 251 GB.

**The AA variant is the long pole: 43.3 s of 83 s is its single `gmx sasa` call.** Everything else, including all
four XTC extractions (26.1 s) and all Connolly snapshots (2.6 s), is secondary.

## 3. What the published artifacts feed (Connolly finding)

Grep across `web/routes`, `web/views.py`, validation `static/js`, templates, metadata/record shape, and tests:

- **`sasa.xvg` (full trajectory) is published data.** `metadata['statistics'][model]['xvg']` → the route
  `mapping_consistency_api` re-bases it through `exposed()` (`packages/validation/.../web/routes/analyses.py:87-91`,
  response field `statistics[].xvg`) → `paintShape` draws the 2D "SASA over time" chart from it
  (`static/js/run-view-mapping.js:699`). The browser test pins the two series
  (`tests/browser/test_run_view_mapping_analysis_browser.py:511-521`).
- **`surface-comparison-aa-cg.json` is published data**: the Shape panel's two mesh panels + markers
  (`analyses.py:100-102`, `run-view-mapping.js` surfacePairMarkup). Its meshes come from `envelope()`.
- **`surface-comparison.html` is the fallback figure**: `metadata['comparison_html']` → `newest_surfaces(...,
  figure_key='comparison_html')` (`core/.../web/routes/analyses.py:72-81`) → `surfaces.figure`; the JS falls back to
  it only when `aa_cg_comparison` is absent (older attempts), with a **Recalculate surfaces** button.
- **`snapshot-sasa.xvg`, `connolly.pdb`, `connolly.log` have no consumer anywhere.** They are written (lines
  88-91) and named only in `metadata['commands']`; the rendering prose mentions "Connolly dot files are
  downloadable separately". They do **not** feed the figure, the meshes, the statistics or the AA/CG panel JSON.

Conclusion: the one-frame Connolly snapshot is **evidence-only provenance**, not a published statistic. It costs
~2.6 s total (~3% of the attempt). Keep it: removing or making it optional is a science/user decision (plan open
decision 4), not a producer optimisation, and it is cheap. Do not delete existing immutable evidence.

## 4. The progress seam

- The worker's `progress(phase)` closure writes `<attempt>/progress.json` (`packages/core/src/dashboard/analysis/
  worker.py:93-94`) and is called at 95, 132, 144, 149, 175.
- The producer is invoked as `TABLE[kind].run(work, request.get('payload', {}))` (`worker.py:141`). The work
  directory is a `TemporaryDirectory` under the attempt, so the producer never learns the attempt path and has no
  way to report a phase.
- Each analysis is its **own subprocess**: the coordinator runs `python -m dashboard.analysis <request>`
  (`execution/coordination/analysis_coordinator.py:310-311`; `analysis/__main__.py` calls `execute`). So state set
  in the child cannot leak into the parent or another analysis.
- Consumers read exactly `progress.json['phase']`: `routes/analyses.py:181` and `views.py:360-362`, rendered as the
  task's progress line. `test_run_view.py:155-168` pins that read for both the full and summary views; no test pins
  the writer's phase strings.

Options considered:

| option | shape | change | trade-off |
|---|---|---|---|
| **env var + tiny helper (recommended)** | worker sets `DASHBOARD_ANALYSIS_PROGRESS = str(attempt/'progress.json')` around the `run` call; shared `progress.report(phase)` reads it and `files.atomic_json`s `{'phase': …}` | ~6 lines in a new `dashboard/analysis/progress.py`, 4 lines in `worker.execute` | process-global, but the worker is a dedicated process; works from threads and child processes; must set/clear in `try/finally` so in-process tests don't leak; visible to `gmx` children (harmless) |
| contextvar | `ContextVar` set/reset in `worker.execute`; helper reads it | similar size | tighter scoping, no env pollution; **not inherited by new threads or subprocesses**, so per-variant reports must stay on the main thread; if a producer ever reports from a pool thread it silently does nothing |
| extend the `Kind` signature | `run(work, payload, progress)` | touches `Kind`, `sources_only`, `source_hook`, and every callable/row | most explicit, but large churn for one producer; not warranted now |

Recommendation: **env var naming the progress file plus `dashboard/analysis/progress.py::report(phase)`**. It is the
smallest change, it survives the producer's future thread pool, and the one-process-per-analysis fact removes the
usual objection to process-global state. The helper is a no-op when the variable is absent (direct calls, tests,
fixtures). New module changes `code_fingerprint_files()` (it walks the packages), which correctly invalidates prior
attempt signatures — expected.

## 5. Proposed producer change (no science change)

Constraints held fixed: `-ndots 240`, full-trajectory frame set, `PROBE`, `-surface all`, `-output all`, the four
variant definitions and the radii tables. Nothing below adds, drops or reinterprets a variant.

### (a) Concurrent `gmx sasa`, pipelined after each extraction

The important detail is **when** jobs are submitted. Extracting all variants first and only then running four
`gmx sasa`s in parallel would be 26 s + 46.7 s ≈ 73 s — almost no gain. Submitting each variant's `gmx` work as soon
as its `surface.xtc` is closed overlaps the 26 s of extraction with the 43 s AA `gmx sasa`:

```
with ThreadPoolExecutor(max_workers=min(len(variants), os.cpu_count() or 1)) as pool:
    futures = {}
    for label in variant order:
        work = ...; first[label] = _write_variant(...)      # main thread, stateful MDAnalysis readers
        progress.report(f'Surfaces: {label} · gmx sasa')
        futures[label] = pool.submit(_gmx_and_parse, label, work, gmx)
    results = [(label, future.result()) for label, future in futures.items()]
```

Measured inputs give an estimated wall of ~47-49 s (AA extraction 2.7 s + AA `gmx` 43.3 s + snapshot 0.6 s +
post-processing ~0.6 s; the other three variants finish at ~23.6 s, ~40 s and ~32.6 s, all inside the AA shadow) —
**~1.7× faster, ~35 s saved**. This is an inference from the phase table, not an end-to-end measurement.

Bound: `min(len(variants), os.cpu_count() or 1)` = **4** on this host. Each `gmx sasa` is one core and 45 MB peak;
four is far below 72 cores / 251 GB and bounds disk/IO to the four already-written XTCs. Each variant already has
its **own** `analysis/surfaces/<label>/` working directory, so concurrent commands cannot collide. Keep the existing
timeouts (300 s full, 120 s snapshot).

Failure attribution: do not let the first exception kill the loop. Collect `future.result()` in variant order,
catching per variant, then raise one error naming every failed label with that variant's stderr tail (last 2000
chars), e.g. `RuntimeError('surface variants failed: Mapped raw: …; Simulated CG: …')`. This is the plan's
"join/diagnose failures per variant". Commands are returned per variant and concatenated **in variant order** after
the join so `metadata['commands']` stays deterministic; `stats` and `first` keep their current insertion order.

### (b) XTC extraction: keep it sequential on the main thread

Do **not** parallelise MDAnalysis readers. Sharing the `aa` Universe across threads is unsafe: `trajectory` holds one
mutable `ts` (frame index, time, dimensions) and `universe.atoms.positions` is shared state; two iterations would
interleave frames. Two Universes over the same real XTC are also hazardous because MDAnalysis writes
`*_offsets.npz` beside the input (the repository invariant), so concurrent readers race on that cache; making them
safe would mean a per-variant symlinked/copied trajectory in a temp directory each.

More importantly, it buys no wall time here: extraction totals 26.1 s and is fully hidden under the 43.3 s AA
`gmx sasa` once submissions are pipelined. A shared single AA pass (one AA read writing AA + both mapped XTCs,
applying each transform) would save ~5 s of CPU and one 13 MB re-read, but not the wall clock; it couples three
variants in one loop. Recommendation: **land (a) first; consider the shared AA pass only as a later micro-optimism**
if a profile on a smaller host shows extraction no longer hidden. The AA variant's own `surface.xtc` is also a
byte-for-byte copy of the staged AA trajectory; reusing the staged `lig.xtc` is tempting (~2.7 s) but relies on the
staged `surface.gro`-from-frame-0 distinction, so leave it unless measured and reviewed.

### (c) Per-variant progress phases

`generate()` calls `progress.report(...)` on the main thread at:

1. `'Surfaces: extracting AA'`, then each variant's extraction;
2. at submit: `'Surfaces: <label> · gmx sasa'` (last submitted wins; the UI shows one line);
3. as futures complete: `'Surfaces: <label> done'` and, after all, `'Surfaces: envelopes and figure'`.

A single `phase` string cannot represent four concurrent commands; the honest reading is "which surface is running"
via the submit messages and completion count. If the UI later wants all four, add a `phases` dict to
`progress.json` and teach both consumers to prefer `phase` — but that is a second shape, not needed for this slice.

### Code shape (files/functions)

`packages/validation/src/detergent_validation/analysis/runs/surfaces.py`
- module constants `NDOTS = 240`, `SASA_TIMEOUT = 300`, `SNAPSHOT_TIMEOUT = 120`; keep `PROBE` imported.
- `_sasa_commands(gmx)` → the two exact argv lists (pure, testable).
- `_write_variant(label, universe, reader, radii, model, work)` → writes `surface.xtc`/`surface.gro`/`vdwradii.dat`,
  returns the frame-0 positions (today lines 71-83).
- `_gmx_variant(label, work, gmx)` → runs the two commands in `work`, writes `sasa.log`/`connolly.log`, returns
  `(commands, sasa_values)`; raises a label-carrying error on failure (today lines 84-94).
- `generate(run_dir)` → setup, the extract-and-submit loop above, joined results, then the unchanged alignment,
  envelope, figure, pair JSON and metadata blocks.

`packages/core/src/dashboard/analysis/progress.py` (new)
- `report(phase: str) -> None`; reads `DASHBOARD_ANALYSIS_PROGRESS`; writes `{'phase': phase}` with
  `files.atomic_json` when set, no-op otherwise.

`packages/core/src/dashboard/analysis/worker.py`
- around `TABLE[kind].run(...)` (line 141), set the env var to `str(attempt/'progress.json')` and clear/restore it in
  `finally`. No change to the existing `progress()` closure or the consumer contract.

No new dependency; `concurrent.futures` is stdlib.

## 6. Tests to add/update

- **New `packages/validation/tests/unit/test_surfaces.py`** (there is no unit test for this producer today; the only
  surfaces tests are fixtures):
  - `_sasa_commands` returns exactly the reviewed knobs: `-ndots '240'`, `-probe str(PROBE)`, `-surface all`,
    `-output all`, `sasa.xvg`, and the snapshot's `surface.gro`/`snapshot-sasa.xvg`/`connolly.pdb`. This pins "no
    science change" without running GROMACS.
  - failure attribution: monkeypatch `subprocess.run` to fail for one label, assert the joined error names that
    label and includes its stderr tail, and assert the other variants were still attempted.
  - per-variant progress: monkeypatch `progress.report` and a fake variant runner; assert the extract/submit/done
    phases are reported in variant order.
  - the variant set: `rings` present → four variants; absent → three; no drop/reinterpretation.
- **New `packages/core/tests/unit/test_analysis_progress.py`**: `report` writes the phase when the env var is set,
  is a silent no-op when absent, and `worker.execute` exposes the variable to `TABLE[kind].run` (fake kind) and
  clears it afterwards.
- **Unchanged**: `test_run_view.py:155-168` still pins the consumer read (the phase string stays free text); the
  browser/integration fixtures (`publish_surfaces` in `test_run_view_mapping_analysis_browser.py`,
  `test_mapping_consistency_api.py`) still describe the published record and need no update because the record
  shape, file names and paths are untouched.
- `test_analysis_kinds.py` keeps passing: the `surfaces` row is unchanged (`sources_only`, same sources, same
  title/units).

## 7. Risks and open points

- **Threading scope**: only `subprocess.run` runs in the pool; no MDAnalysis object is touched off the main thread.
  Review must keep that true.
- **Failure semantics change**: today the first failing variant aborts immediately; proposed code runs the others
  too and raises a joined error. That is the requested attribution, but it can spend time on variants after an
  early failure.
- **Determinism**: the science outputs are unchanged; only `commands` ordering (preserved) and `wall_seconds`
  (already variable) move. `source_sha256` and file names are untouched.
- **Estimate vs measurement**: the ~47 s figure is inferred from phase times; it should be confirmed by one timed
  end-to-end rerun on a completed run before landing, as the plan's "benchmark on one completed run" asks.
- **New module drives a new analysis signature** (fingerprint walks packages), so prior `surfaces` attempts stop
  satisfying a re-queue — correct, but worth stating in the commit.
- **Not decided here**: making the Connolly dot files optional (plan open decision 4). They are evidence-only and
  cost ~2.6 s; leave them, and let the user decide.
- **Host dependence**: on a low-core host the pool degenerates to one variant at a time and extraction contends with
  `gmx`; the pipeline still works, just with less gain.
