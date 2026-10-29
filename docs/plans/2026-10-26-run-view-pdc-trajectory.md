# Run view: a timed CG trajectory for protein-detergent runs

Status: implemented and live on `00b9ae6db23f`, 2026-10-26. Draft: `docs/design/drafts/2026-10-26-run-view-pdc-trajectory.html`.
Owner: Run view panel (`run-view.js`, `run-view-monitor.js`) and the `snapshots` analysis.

## Goal

The Run view's protein-detergent monitor must play the CG trajectory as one timed reel:

- one slider spans the two production stages, **CG assessment MD** then **CG extension MD**;
- the slider prints simulation time, with each stage's span labelled and a boundary where the system is rebuilt;
- a cadence control sets how many nanoseconds one displayed frame stands for, default **1 ns per frame**, and
  republishing the series honours it.

The two stages are separate trajectories with different atom counts (measured on `00b9ae6db23f`: assessment
11,708 atoms; extension 10,427 atoms). They are never concatenated into one file. The timeline is global; playback
switches the loaded trajectory file at the boundary.

## Decisions

| # | Decision |
| --- | --- |
| D1 | Bands are exactly `CG assessment MD` and `CG extension MD`. Equilibration legs stay in the segments table and outside the timed slider. |
| D2 | Time comes from measured frame times: the producer records `universe.trajectory.time` for every sampled frame. Requested durations (`settings.assessment_ns`, `settings.extension_ns`) are fallback metadata only. |
| D3 | The extension's own clock starts at 0, not at the assessment's end. The panel offsets later stages by the measured duration of earlier stages. |
| D4 | Cadence is sampling cadence, not wall-clock playback speed. `Generate trajectory` resamples and republishes through the existing `snapshots` analysis; default 1 ns/frame. |
| D5 | A series never silently truncates at `SERIES_CAP`. If a requested cadence needs more frames than the cap, sample evenly across the whole trajectory at the cap and record the cadence actually written; the panel reports both numbers. |
| D6 | Old published results without per-stage series keep working: the panel falls back to the current single-series playback and says the timed reel needs a recompute. |

## Current state

- `analysis/runs/layout.frame_source` resolves one trajectory; for a pdc run that is `4_extension/prod/whole.xtc`.
  So the published `CG-frames.pdb` holds extension frames only.
- `analysis/runs/segments.py` already reports the chain as ordered segments with `group` and `boundaries`; the panel
  draws it as a table. It does not claim frames or times (opening an xtc is expensive).
- `analysis/runs/observability.generate` samples one trajectory, writes one series and records:
  `frames`, `sampled`, `stride`, `interval_ns`, `duration_ns`, `frame_ps`, `requested_interval_ns`.
- `run-view-monitor.js` loads one multi-model PDB, attaches one `NGL.TrajectoryPlayer`, and labels the row by frame
  index only. The cadence field lives in the collapsed frames panel, not on the transport.
- Measured live run `00b9ae6db23f`: both `2_assessment/prod/whole.xtc` and `4_extension/prod/whole.xtc` hold 50,001
  frames at 2 ps, 100.0 ns each. The manifest requests 900 ns of extension; the file holds what actually ran.

## Acceptance criteria

1. Opening the Run view on a pdc run whose snapshots analysis has published the new shape draws one slider, two
   labelled bands, and a time readout. The bands are derived from the run record, not hard-coded to 100/900.
2. At the boundary the canvas switches from the assessment structure/trajectory to the extension's; the frame index
   and time stay monotonic.
3. The cadence control defaults to `1` ns/frame. Pressing Generate sends `interval_ns: 1` when the field is
   untouched, republishes the two series, and the new cadence appears in the readout.
4. Changing the cadence to 2 resamples at 2 ns/frame: half as many models, `times_ns` advancing by 2, and the slider
   still spans the whole measured run.
5. A run with no published series, a single frame, or a missing segment keeps the current disabled-with-reason
   behaviour rather than drawing a plausible empty slider.
6. The two monitors' time link seeks by global time, including across the boundary.
7. `GET /api/jobs/<id>/trajectory` still answers the same stage map; no new route is required.

## Result contract

The `snapshots` result's `result` object gains an optional `segments` list. The existing `series` object stays, set
to the last playable segment, so old readers keep working.

```json
{
  "frames": 100000,
  "role": "pdc_timeline",
  "series": { "...": "the last segment, for compatibility" },
  "segments": [
    {
      "name": "CG assessment MD",
      "stage": "CG assessment MD",
      "role": "pdc_assessment",
      "atoms": 11708,
      "frames": 50001,
      "frame_ps": 2.0,
      "series_file": "snapshots/CG-assessment-frames.pdb",
      "sampled": 100,
      "times_ns": [0.0, 1.0, 100.0],
      "interval_ns": 1.0,
      "start_ns": 0.0,
      "end_ns": 100.0,
      "source": "measured",
      "aligned": null
    },
    {
      "name": "CG extension MD",
      "stage": "CG extension MD",
      "role": "pdc_extension",
      "atoms": 10427,
      "frames": 50001,
      "frame_ps": 2.0,
      "series_file": "snapshots/CG-extension-frames.pdb",
      "sampled": 100,
      "times_ns": [0.0, 1.0, 100.0],
      "interval_ns": 1.0,
      "start_ns": 100.0,
      "end_ns": 200.0,
      "source": "measured",
      "aligned": null
    }
  ]
}
```

Rules:

- `times_ns` is the measured local trajectory time of every sampled model, in nanoseconds.
- `start_ns`/`end_ns` are the **global** timeline span; the second segment is offset by the first's measured
  duration.
- `source` is `measured` or `metadata`. `metadata` is used only when the trajectory states no usable time step;
  the record then also carries `requested_interval_ns` and the panel labels the span as requested, not measured.
- The PDB itself also writes `REMARK 950 MODEL <n> TIME <t> NS` before each `MODEL`, so a reader with the file
  alone can recover the times.
- `interval_ns` is the cadence the file actually holds, as `_cadence_ns` already computes it.

## Work

### 1. Producer: sample the two pdc stages

Files: `dashboard/analysis/runs/observability.py`, `dashboard/analysis/runs/segments.py`,
`dashboard/analysis/kinds.py`, `dashboard/execution/adapters/pdc_view.py`.

1. Add the assessment's files to the `snapshots` kind sources:
   `2_assessment/prod/run.gro`, `2_assessment/prod/whole.xtc`, `2_assessment/prod/run.xtc`.
   The extension's three are already there, as is `1_system/*.itp`.
2. Add one ordered constant beside `segments.PDC_STAGES` naming the timeline stages, e.g.
   `PDC_TIMELINE_STAGES = ('CG assessment MD', 'CG extension MD')`. Do not match on string literals in the producer.
3. Split `observability.generate`:
   - `generate(...)` keeps its signature and branches on `segments.is_pdc(run_dir)`.
   - `_generate_single(...)` is the current body.
   - `_generate_pdc(...)` resolves the two stages through `segments.pdc_segments`, skips a stage with no trajectory or
     a `duplicate_of`, and for each one:
     - opens `mda.Universe(structure, trajectory)`;
     - samples with `_series_indices`;
     - writes `CG-<slug>-frames.pdb` through `pdc_view.series_pdb`;
     - measures `times_ns` from `universe.trajectory[index].time / 1000`;
     - records its own `frames`, `frame_ps`, `sampled`, `interval_ns`, `duration_ns`, `aligned`.
   - `_generate_pdc` returns `{'frames': sum, 'files': [...], 'role': 'pdc_timeline', 'segments': [...],
     'series': last_segment_series}`.
   - The dispatch uses the two-series shape only when **both** `PDC_TIMELINE_STAGES` resolve to a playable,
     non-duplicate stage with structure and trajectory. A partially written pdc run falls back to the existing
     `_generate_single` path unchanged.
4. `segments.pdc_segments` must not be the only place that knows the timeline ordering. The producer and the
   timeline contract both read `PDC_TIMELINE_STAGES`.
5. Extend `pdc_view.series_pdb` to accept per-model times (a list parallel to `frames`) and write the `REMARK 950
   MODEL ... TIME ...` line inside each `MODEL` block. A caller with no times writes the current note only.
6. Fix `_series_indices` for D5: when `len(range(...)) > cap`, return an evenly spaced list of `cap` indices across
   `0..n_frames-1`; the recorded `interval_ns` becomes the actual spacing, not the requested one. Add
   `requested_interval_ns` beside it. This is the only behaviour change for non-pdc runs; it prevents a 900 ns
   extension at 1 ns/frame from publishing only its first 200 ns.
7. No moments for the pdc timeline (CG already writes none). Keep the all-atom path untouched.

### 2. Panel: read the timeline and play a reel

Files: `dashboard/web/static/js/run-view-monitor.js`, `dashboard/web/static/js/run-view.js`,
`dashboard/web/static/run-view.css`.

1. `publishedSnapshots` returns `segments` from `record.result.segments` as well as the current `frames`, `moments`
   and `series`. One reader, not a second tree walk: it already parses the newest `result.json`.
2. `loadRun` builds the reel only when `segments.length > 1` and every `series_file` resolves under the attempt
   directory. Otherwise keep the existing single-series path. A run with no `segments` sets a note: "This run's
   published series predates the timed CG reel; Generate trajectory republishes it."
3. Replace `draw` + `attachRow` with:
   - `drawTimeline(job, segments)`: loads each series into its own NGL component (`asTrajectory: true`,
     `addTrajectory()`), hides all but the active one, applies bead radii and the existing bond rule per component,
     `autoView()` on the active one.
   - `attachReel(components, segments)`: the transport gets a reel descriptor
     `{components, segments, offsets, totalFrames, times}`. A segment's global frame range is
     `[offset, offset + sampled - 1]`; global time is its `times_ns[local]` (already offset in the record).
4. Playback: keep the current controls and `FRAME_MS`/`END_MODE`, but drive a `requestAnimationFrame` loop over the
   global index because `NGL.TrajectoryPlayer` cannot cross files. On a segment change: pause, hide the old
   component, show the new one, `setFrame(local)`, `autoView()` only on the first draw (the boundary can move the
   camera; the plan keeps one `autoView` per segment, not per frame). At the ends, stop (D12).
5. `transport` API:
   - `frames` = total reel frames.
   - `frameNow()` = global frame.
   - `setFrame(global)` maps to the segment and local frame.
   - `nanosecondOf(global)` returns `times_ns[global]` (or null).
   - `frameFor(ns)` bisects the flat times array; returns the nearest global frame.
   - `frameNow` and `seek` stay for the existing time link (`run-view.js` needs no change).
6. Stage bands:
   - Render one `.transport-band` per segment inside `.transport-timeline`, flex-grow proportional to its measured
     duration (not frame count), with `<b>Assessment</b>` / `<b>Extension</b>` and the full stage name plus
     `start – end ns`.
   - A boundary rule at the segment edge; active band coloured while the playhead is in it.
   - `onFrame` updates the band's `data-active`, the playhead position, the readout
     (`126.0 ns · frame 126 of 199 · CG extension MD · 10,427 atoms`) and `aria-valuetext`.
   - No line through the labels: the playhead is a marker above the bands; the slider thumb is the track's playhead.
7. Cadence control: move `ns a frame` out of the frames sub-panel onto the transport row. Default value `1`.
   - `queueGeneration` sends `interval_ns` = the field's number, or `1` when blank, for a pdc timeline. Every other
     run type keeps blank = the producer's even spread and its `40 frames` placeholder, so their request stays `{}`.
   - The Generate label stays. It already prompts before replacing a published series; update the prompt to name
     both series and the cap.
8. Selection:
   - The published series appears as one row in the holds table, labelled with both stages.
   - Clicking it restores the reel. Clicking an ordinary structure hides the reel and disables the transport with
     the existing reason.
9. `run-view.js` `follow` is unchanged: it already seeks by `nanosecondOf`/`frameFor`. Verify it works when the
   target monitor has a reel.
10. Remove the `Pair each monitor with its reference` control. It is not needed: the panel already pairs the first
    monitor's run with its reference while picking the initial pair (`pickInitial` calls `referenceOf`), and the
    button's `pair()` only changes the second monitor when pressed. Delete the button, its `#run-view-pair` handle,
    the `pair()` function and its listener; keep `referenceOf`, which `pickInitial` still uses. Leave the rest of the
    `run-view-pairing` row (swap, time link, status note) in place.
11. Disable `Open the zoomable figures in Runs` for the protein-detergent workspace. Today it only calls
    `selectTab('runs')`, and the Runs gallery holds no pdc-specific analysis plots to open, so the control promises
    something that is not there. Render the button `disabled` with a `title` naming the reason when this workspace's
    `run_view_scope.types` is `['pdc']`; leave it enabled in Detergent validation, where the figures exist. Do not
    remove the `data-go` attribute: disabled buttons cannot fire it, and re-enabling is then a one-attribute change
    when pdc figures land. Add a browser assertion that it is disabled in the pdc workspace and enabled in
    validation.

### 3. Tests

Fast tier (unit/integration):

- `tests/dashboard/unit/test_snapshot_frames.py`:
  - a pdc fixture with two small trajectories writes two series and a `segments` list with measured times;
  - the second segment's `start_ns` equals the first's `end_ns`;
  - a duplicate stage is skipped;
  - a stage with no time step records `source: 'metadata'` and requested times, never measured ones;
  - update `test_a_cadence_finer_than_the_cap_is_capped_and_still_states_its_cadence`: a 500 ns trajectory at
    1 ns/frame returns `cap` evenly spaced indices, the last index is the last frame, and `interval_ns` is the
    actual spacing (about 2.5, not 1.0).
- `tests/dashboard/unit/test_run_segments.py`: add `PDC_TIMELINE_STAGES` membership/order test.
- `tests/dashboard/integration/test_snapshot_cadence_api.py`: the published result's `segments` and `series` are
  both readable through the existing artifact route; `/trajectory` is unchanged. (The similarly named
  `test_pdc_snapshots_route.py` is a unit test for the separate per-stage `snapshots.json` endpoint and is not
  touched.)
- `tests/dashboard/unit/test_pdc_snapshot.py` (writer coverage) or a focused addition: per-model
  `REMARK 950 MODEL … TIME …` lines; a caller with no times writes none.

Browser tier:

- `tests/dashboard/browser/test_run_view_transport_browser.py` (or a sibling
  `test_run_view_pdc_timeline_browser.py` if the fixture does not fit) with a pdc fixture:
  - two `.transport-band`s with the measured spans;
  - the slider's `max` is `total frames - 1`;
  - dragging across the boundary changes the readout stage and the visible component;
  - cadence input defaults to `1`;
  - Generate posts `interval_ns: 1`;
  - the time link seeks the other monitor by time, not frame;
  - at 390 px the panel has no horizontal scroll (`scrollWidth <= innerWidth`), the existing guard.
- Reuse the pdc fixture in `tests/dashboard/browser/`; do not add a new run.

Run the narrow file first, then the tiers from `AGENTS.md`. `ruff check dashboard tests` must exit 0.

### 4. Live proof (after the code lands)

1. Restart the dashboard (Python changed).
2. `POST /api/jobs/00b9ae6db23f/analyses/recompute {"kind":"snapshots"}` with the panel's new default payload
   (`interval_ns: 1`).
3. Open the protein-detergent Run view on `00b9ae6db23f` and check: two bands 0–100 / 100–200 ns (measured),
   200 frames at 1 ns, playback switches from 11,708 to 10,427 atoms at 100 ns, and the series PDBs carry CONECT.
4. Record the counts in `docs/HANDOFF.md`; the previous handoff already records that nobody has watched the pdc
   series draw.

## Edge cases

- **Requested vs measured**: the extension may be shorter than requested (this run: 100 ns of a requested 900).
  The slider uses measured time and the readout says so. Do not pad the response.
- **Cap**: if the run is longer than `cap × cadence`, republish at the cap with the actual cadence and show both
  numbers. Never publish only the first 200 ns.
- **No trajectory/no time step**: keep the existing `skipped`/`NoTrajectory` contract; the panel draws the reason.
- **Duplicate stage** (`Final assessment`): excluded from the reel; still in the segments table.
- **Layout**: pdc stages are at the run root, not under `stages/` (measured). The producer runs in a work directory
  where they are copied to the root, so `segments.present` covers both spellings.
- **Old results**: no `segments` → single-series path and a note; do not infer a timeline from requested durations.
- **Memory**: two ~100-model CG PDBs are loaded at once; NGL can hold both. Do not preload every segment if a future
  run type has many.

## Files touched

| File | Change |
| --- | --- |
| `dashboard/analysis/runs/segments.py` | `PDC_TIMELINE_STAGES`; no change to existing shape |
| `dashboard/analysis/runs/observability.py` | branch pdc; per-segment sampling; measured times; cap fix |
| `dashboard/analysis/kinds.py` | add assessment sources to `snapshots` |
| `dashboard/execution/adapters/pdc_view.py` | `series_pdb(..., times_ns=...)` writes per-model `REMARK` |
| `dashboard/web/static/js/run-view-monitor.js` | reel transport, stage bands, cadence on the row |
| `dashboard/web/templates/dashboard.html` | drop the `#run-view-pair` button; disable the figures button for pdc |
| `dashboard/web/static/js/run-view.js` | drop the pair button handle, `pair()` and its listener |
| `dashboard/web/static/run-view.css` | timeline/band/playhead/cadence rules, responsive |
| tests | as above |
| `docs/HANDOFF.md` | live proof after the code lands |

`run-view.js` and `dashboard.html` need no change: the transport keeps `attach`, `frames`, `frameNow`, `setFrame`,
`nanosecondOf`, `frameFor`, `seek`, `onFrame`.

## Open items (decide while building, do not guess)

1. **Blank cadence**: today blank means the even 40-sample spread. The request makes 1 the default. Proposal: the
   panel sends `1` for a pdc timeline and keeps blank = spread for other run types; after the change, document
   whether blank survives at all.
2. **Camera at the boundary**: one `autoView()` per segment is proposed. If the rebuilt system jumps, either keep
   the first segment's camera or fit each once; measure both and record the choice.
3. **Playback rate**: `FRAME_MS` stays 100 ms (ten frames a second). The new control is simulation time per frame,
   not wall-clock. Confirm that is the intended reading.
4. **2-D monitor link**: a pdc reel linked to an AA series links by time. The AA series' own `times_ns` is not
   published yet; the existing `interval_ns × frame` fallback remains for that side.

## Non-goals

- Concatenating the two trajectories into one file.
- Adding equilibration legs to the timed slider.
- A server-side route that opens an `.xtc` to count frames.
- Rebuilding the run's assessment or extension.
- Changing the segments table's meaning.
