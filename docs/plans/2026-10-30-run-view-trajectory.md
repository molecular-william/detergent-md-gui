# Run view: play a trajectory, and recompute its frames with arguments

Status: **open, next task.** Written 2026-10-30. Owner: next agent. Read `docs/HANDOFF.md` first (same date); it
points here.

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
