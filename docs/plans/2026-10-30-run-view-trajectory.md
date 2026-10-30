# Run view: play a trajectory, and recompute its frames with arguments

Status: **built 2026-10-30.** Written 2026-10-30. The execution record is at the end; read `docs/HANDOFF.md` for
state and open items.

## The report

"Run view" (the shared, engine-owned panel in both workspaces) can no longer play a simulation trajectory, or
recompute the frames of one. Recomputing should offer comboboxes for the arguments it takes.

## Current state, verified

1. **There is no player.** `run-view-monitor.js` loads `/api/jobs/<id>/trajectory` only to build the segment table
   (through a feature's `runSelected` hook) or to show the endpoint's `why` sentence. The file contains no
   `requestAnimationFrame`, no series load and no playback state. There is no recompute control.
2. **The player was removed, not broken.** It last existed at `d3ca13d^` ("refactor(run-lifecycle)", 2026-10-27):
   `git show d3ca13d^:dashboard/web/static/js/run-view-monitor.js` (~627 lines removed) holds the film, the
   frame-row, the play controls and the "Generate trajectory" control. Earlier design commits: `405e996` (the
   player and per-segment table), `325fe7f` (a pdc series must be coarse, bonded and correctly named). The retired
   `snapshots` kind and its tests are recoverable from the same parent:
   `git show d3ca13d^:dashboard/analysis/kinds.py` (`_snapshots` and its `Kind` row),
   `git show d3ca13d^:dashboard/analysis/runs/observability.py` (frame sampling and fitting),
   `git show d3ca13d^:tests/dashboard/unit/test_snapshot_frames.py` (596 lines of argument/edge-case coverage),
   `git show d3ca13d^:tests/dashboard/browser/test_pdc_snapshots_browser.py`.
3. **The series writer survived, unused.** `analysis/runs/structures.py::series_pdb` writes multi-model PDB with
   per-model `CONECT`, bead families, `REMARK 950 MODEL <n> TIME <t> NS`, and the remarks a fitted or assembled
   series must carry. Nothing calls it today.
4. **The vendored NGL cannot read XTC or TRR** (`grep -c XTC ngl.js` = 0; `modelStore` exists). Playback therefore
   needs a server-written multi-model file; it cannot stream the stage's `.xtc` into the viewer.
5. **A live path bug blocks even the structure picture.** `analysis/runs/segments.py::relative()` reports a path
   under `stages/` *without* the prefix, while `GET /api/jobs/<id>/structure` and `.../artifacts/<path>` resolve
   from the run root. Measured on the live run `00b9ae6db23f`:

   ```
   /api/jobs/00b9ae6db23f/structure?path=4_extension/prod/run.gro          -> 404
   /api/jobs/00b9ae6db23f/structure?path=stages/4_extension/prod/run.gro   -> 200
   /api/jobs/00b9ae6db23f/artifacts/4_extension/prod/run.xtc?inline=1      -> 404
   /api/jobs/00b9ae6db23f/artifacts/stages/4_extension/prod/run.xtc?inline=1 -> 200
   ```

   The panel shows `... could not be read (404)`. The contract test still writes its fixture at the run root
   (`integration/test_run_trajectory_route.py::pdc_run`), so the suite is green while the product is not.
6. `segments.py` deliberately reports no frame count: counting a 2.6 GB xtc takes ~43 s. The player must not count
   frames on page load; the series builder is where frames are read.

## Goal

1. Run view plays a run's own trajectory, for both workspaces, with play/pause, seek, frame step and a time readout.
2. A **Recompute frames** control offers comboboxes for the arguments below; it builds an immutable analysis series
   and the player loads it. Recomputing with different arguments creates a new attempt and keeps the old one.
3. The existing live runs (`00b9ae6db23f`, `b920391735dd`) render their structure and play their trajectory.

## Design

### Phase 0 — the path contract (prerequisite, separate commit)

- Decide one spelling: the trajectory response must return paths the `/structure` and `/artifacts` routes accept.
  Preferred: `segments.relative()` returns the path relative to the **run root**, i.e. including `stages/`; keep
  `layout._spellings` for reading legacy trees. Alternative: teach both routes `layout._spellings`. Pick one and
  say why in the commit.
- Update `integration/test_run_trajectory_route.py` to build the real layout (`stages/...`) and assert the URL
  spellings; add an assertion that fetching every `structure_url` and `trajectory_url` in the answer is 200 (a
  route-level check, not a shape check). Keep a legacy-layout case if migrated runs must stay readable.
- Acceptance: the live URLs above answer 200 and Run view draws the structure.

### Phase 1 — the `frame-series` analysis

- New row in `analysis/kinds.py`: `frame-series`, **on demand only** (never in `for_every_run()`/`default_for`).
  The retired `snapshots` row is the reference; do not resurrect its automatic cadence.
- Payload arguments (the combobox sources; validated server-side, and recorded in `result.json`):
  - `trajectory` — a playable segment from `/api/jobs/<id>/trajectory` (required; resolved through `layout`),
  - `structure` — defaults to the segment's structure; needed for the topology and bead names,
  - `start_ns`, `end_ns` — floats, optional; default the whole file,
  - `stride` — frames, optional; default "auto" aiming at ≤ 120 models,
  - `fit` — `none` | `protein` | `beads` (MDAnalysis alignment; `align_on` selects a fragment from the mapping for
    the bead case, as the retired control did),
  - `atoms` — `all` (water excluded) | `beads` | `ca`; the pdc default should be `beads` at first,
  - `assembled` — boolean, the display assembly the writer already has REMARKs for.
- Input recording: the analysis signature must include the chosen trajectory. `Kind.sources` is pattern-based; add a
  small payload-driven source hook (a callable on the row, or resolve in the producer and have the worker hash the
  chosen files) rather than hashing every `.xtc` in the run. Keep `POST /api/jobs/<jid>/<kind>` and the `known()`
  check unchanged.
- Producer: `analysis/runs/frame_series.py` — MDAnalysis `Universe(structure, trajectory)`, iterate the selected
  frame indices, build `frames` in the `read_gro` shape `structures.series_pdb` takes, pass `times_ns`, and write
  `run-frames.pdb`, `frames.json` (`times_ns`, frame indices, args, counts) and `result.json` (args, models, atoms,
  bytes). Enforce caps: refuse > 240 models and an estimated PDB > ~250 MB; for pdc prefer `atoms=beads`.
- Panel lookup: newest `frame-series` attempt whose recorded args equal the form; otherwise offer Build.

### Phase 2 — the player (engine panel, both workspaces)

- `run-view-monitor.js`: a "Trajectory" block above the segment table.
  - Segment select, from `/trajectory` playable entries (a run may hold several systems; atom counts differ at a
    rebuild boundary, so one segment at a time — "play all" is a later opt-in, not phase 1).
  - When a series exists: Play/Pause, frame slider, −1/+1, speed select (0.5×/1×/2×), loop, and
    `t = 12.5 ns · model 37/120` from `frames.json`.
  - Build/Recompute button; a lazy load — never download a series on mount.
  - Load with NGL `loadFile(seriesUrl, {ext: 'pdb'})`, step the models by the mechanism the retired player used
    (`d3ca13d^` code); destroy the previous series component on replace; keep the structure component intact.
  - Empty states: the endpoint's `why` sentence; a failed attempt shows its error and log tail; a series older than
    the trajectory says it is stale and offers Recompute.
- Feature extensions stay as they are: pdc's `runSelected` segment table remains, and the player reads the engine's
  own `segments` answer, so both modules get the same controls.

### Phase 3 — the Recompute form (comboboxes)

- A small dialog or inline form with the Phase-1 arguments as controls: Segment (select), Atoms (select), Fit
  (select + fragment select when beads), Start/End (number, ns), Step (number, frames, "auto" default), Assemble
  (checkbox). Show the estimated model count and size; Submit disabled while queued.
- Submit → `POST /api/jobs/<jid>/frame-series` → poll the attempt (the dihedral-fit pattern) → on success swap the
  series, keep the current relative time when possible, and print the build line ("Built from NVT equilibration,
  0–100 ns, every 50th frame, beads, aligned on the protein").
- Recompute prefills from the current series; changing any combobox is what makes it a new attempt.

### Tests

- Unit: payload validation and caps; `series_pdb` output (model count, `TIME` remarks, fitted/assembled remarks);
  argument equality used by the panel lookup.
- Integration (fast, synthetic): the harness `cg_fixture_run` writes a small `.xtc`; queue `frame-series`; assert
  the artifact has N models, `frames.json` times, args in `result.json`; same args reuse the newest attempt;
  different args create a new one; oversized request refused.
- Integration (path contract): the Phase-0 URLs (200 for current and legacy layouts).
- Browser: stub `/trajectory` plus a series; Play advances the model and time, Pause stops, the slider seeks;
  Recompute submits the selected combobox values (assert the payload) and swaps the series; run it in both
  workspaces (the panel is shared — set `run_view_scope`).
- Live acceptance: `00b9ae6db23f` structure 200 and a playable series; `b920391735dd` likewise; pdc segments
  selectable across the rebuild boundary.

### Hazards

- Trajectories are up to 2.6 GB; never count frames on page load; stream and cap in the producer.
- Series size: ~0.9 MB/model for an 11,708-atom pdc system; 120 models ≈ 110 MB. Prefer `beads` for pdc, cap the
  default model count, and reuse attempts.
- Analysis queue: dedupe/concurrency, storage quota, attempt pruning; outputs are immutable and belong to the run.
- Migrated runs: paths through `layout`; `duplicate_of` segments must not be offered twice; a run with no stage tree
  keeps the `why` sentence.
- Engine/feature boundary: no feature vocabulary in the engine panel; only the segment table is extended.
- Do not rebuild the retired automatic `snapshots` cadence or the timed film's transport semantics unchanged —
  this is an on-demand series plus a player.

## Definition of done

- The Phase-0 URLs answer 200; the suite asserts it rather than asserting shapes.
- Play/pause/seek/step works in both workspaces with the series' own times.
- Recompute with each argument (segment, atoms, fit, start/end, stride, assemble) produces a new attempt, visibly
  recorded beside the player; the previous attempt is kept.
- Caps and failure states are tested; the panel never downloads a series on mount.
- `pytest` tiers, `ruff` and the mutation check as `AGENTS.md` requires.

## Execution record (2026-10-30)

**Built in two commits and this record:** Phase 0, the path contract (`e7e6ad8`), then the analysis, producer,
player and resource cap (`d635763`); the documentation follows. Every phase was verified against the two live runs before this record was
written.

### What was decided where the plan left a choice
- **Phase 0 spelling**: the run-root spelling (a current run keeps `stages/`), because that is what `/structure` and
  `/artifacts` resolve. Legacy root-layout runs keep their own spelling. The route test now builds `stages/…` and
  fetches every URL the answer carries; it also covers a `.pdb` structure, which the structure route refuses, so the
  answer names the artifact route for it.
- **Payload validation lives in the source hook**, not in the Kind row: `Kind.payload` stays empty so
  `test_kinds_published` keeps passing and the generic queue route stays untouched. A bad payload is a `ValueError`
  from `sources()` before any attempt exists, which the app maps to `400` and no task.
- **`structure` is required** rather than defaulting to the segment's own: the producer only sees the staged work
  directory, so the panel names both files from the `/trajectory` answer it already holds.
- **`atoms`**: `all` and `beads` both write every atom (a CG system's atoms are beads, and `series_pdb` drops water and
  ions); `ca` writes only `name CA` and claims no bonds. The default is `beads`.
- **`fit` record**: `frames.json.fit` is the record object (`reference`, `atoms`, `rmsd_nm`, `target`, `of`) or `null`
  when unfitted -- the mode itself is in `args.fit`.
- **Assembly** moves each molecule by whole periodic images to the protein (or the first molecule) and centres the
  anchor; it is display-only and the file says so. Orthogonal boxes only (`# ponytail:` in `_assemble`).
- **Producer sampling**: frame numbers come from the trajectory's first time and its `dt` (a GROMACS `.xtc` writes a
  fixed step), and the sampled frames are collected in **one sequential pass**. Measured: the first version indexed
  the trajectory at random, and every access to the live 2.5 GB `.xtc` cost 1.7 s (a 101-model build took 215 s), and
  reading all 50,001 times first added 40 s. The two fixes -- one pass, and the topology columns read once per frame
  instead of once per atom -- brought the whole-file build to 44 s.
- **The panel's POST uses its own 120 s timeout**: the shared `api()` client caps requests at 10 s, and the queue
  hashes the chosen trajectory (5.8 s measured for 2.5 GB, worse cold), so the shared helper could report "refused"
  for an attempt it had in fact queued.
- **`asTrajectory: true` is required** when the series PDB is loaded: this vendored NGL parser only builds trajectory
  frames for a multi-model PDB when that option is set; `addTrajectory()` alone yields `frameCount === 0`.
- **`run-view.js` collapse memory is keyed by `<details>` id**, because inserting the argument form's own `<details>`
  above the three sub-panels would have shifted every remembered index by one.
- **`max_run_bytes` raised 30 -> 40 GiB**: `00b9ae6db23f` is 34.08 GiB, so the per-run admission check refused to
  analyse it (34.08 GiB + the 2.55 GiB source copy already exceeded 30 GiB). A configuration limit, not code.

### Verification (all run 2026-10-30)
- `test_frame_series.py` **39 passed**; `test_frame_series_analysis.py` **6 passed**; the new browser file **11
  passed**; `test_run_view_browser.py` 24 and the run-view scope/navigation files 37 together.
- Fast tier `-m 'not browser and not slow'`: **2,249 passed, 1 xfailed**; browser tier `-m browser -q -n 16`:
  **251 passed**; `ruff check packages tests conftest.py`: clean.
- Live acceptance (a server on the same checkout, a hardlinked workspace holding the two runs):
  - `/trajectory` on `00b9ae6db23f`: 14/14 segment URLs answer 200.
  - `00b9ae6db23f` extension, whole 100 ns, auto stride: 120 models, 0-99.246 ns, 10,427 atoms, 20.3 MB, 210,480
    CONECT records, 120 `TIME` remarks; the same payload returned `200` with the same attempt, `stride: 1000` queued
    `202` and completed; the producer took 44 s.
  - `b920391735dd` assessment, `assembled: true`: 120 models, 8,604 atoms, 15.7 MB, 180,000 CONECT records.
  - The recorded-symlink trap: b920 keeps `stages/02_system/detergent_CG.itp` as a link into `inputs/`, which the
    strict request-path guard first refused, leaving the played series unbonded. Request-named paths stay strict;
    recorded inputs with a target inside the run are staged under their stage spelling, and a unit test pins both
    directions.
- Not done, deliberately: "play all" across the rebuild boundary (the plan calls it a later opt-in); a true
  run-level progress percentage (an open item in `HANDOFF.md`, unrelated).
