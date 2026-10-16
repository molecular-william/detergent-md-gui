# The Run view becomes two monitors

**Landed.** All five steps are in: `web/static/js/run-view-monitor.js` is one monitor (the old panel's per-run code
moved, not rewritten, with every id suffixed by side), `run-view.js` is the host, the template's section is the
shell, and the draft and its test are deleted together. Two deviations, both deliberate: the generate controls live
in the **frames** panel rather than in the transport row, because that is where a series is made and the row is what
*plays* one; and the panel's moments strip, its `fit on:` fragment select and its overwrite prompt all survive inside
each monitor rather than being narrowed to the draft's two controls.

The layout in `dashboard/web/static/run-view-draft.html` becomes the panel. That draft was built to be judged and it
has been: this record says what it becomes, what of the panel's own behaviour moves into it, and in what order so no
commit leaves the panel half a layout.

## The shape

- Two monitors side by side, each half the workspace.
- Per monitor, top to bottom: **choose a run** (a combo box with a text input that filters as you type, completed
  runs only, grouped by run type), the **canvas**, the **transport**, the **readout**, then three collapsed
  `<details>`: **what this run holds**, **frames**, **figures**.
- The pair opens on a coarse-grained run and the atomistic reference it names in `reference_run_id`.
- Each monitor steps by *time* (nanoseconds), and the link moves the other monitor to the same nanosecond rather
  than the same frame index: two series rarely share a cadence, and frame 40 on one side is rarely the same moment
  as frame 40 on the other.

## What moves where

| the panel today | becomes |
| --- | --- |
| the run list, its type/status/search filters | the two combos. The workspace scope stays: a monitor only ever offers the run types its section declares (`#run-view-scope`), and `pdc` runs are still not drawn here. |
| the moments strip, `ns a frame`, `fit on:`, `Generate trajectory`, the overwrite dialog | the frames panel of each monitor, unchanged in behaviour: the draft's two controls were a subset, and the panel's four are what a reader already has. |
| the legend, the readout, the delegation note, `what` and the identity line | per monitor. |
| the figures list | the figures panel of each monitor. |
| the old viewer, its `#run-view-*` ids, the list markup | deleted with the layout. |

## New, and already agreed

- **Pair presets**: one button pairs each monitor's coarse-grained run with its own reference, and another swaps the
  two monitors.
- **Remembered**: the pair and the collapse state of the six panels, in `localStorage`, so a comparison a reader
  returns to reopens as they left it.
- **Empty states on the canvas**: a monitor whose run publishes no frames says so under the canvas, not only inside
  a closed panel.

## Not doing, and recorded so nobody rebuilds it

Locking the two orientations together; a shared time bar above the pair; a third column; a focus notion for a shared
transport; moving the old scope controls into the header.

## How it lands

Each step is green on its own, and no step leaves a stand-in behind.

1. **The monitor factory.** `run-view.js`'s per-run work (holds, frames, figures, transport, readout, legend, the
   generate controls) is extracted into one factory scoped to a monitor root element, and mounted once in the
   existing markup with the existing ids. Behaviour and every current test are unchanged: this step is purely
   structural, and it is the step that decides whether the rest is mechanical.
2. **Two monitors.** The monitor markup is built for both sides, ids suffixed `-A` and `-B`, each with its own
   combo. The panel's browser tests are re-pointed at monitor `A` (mechanical: `#run-view-viewer` becomes
   `#run-view-viewer-A`), and the draft's own tests are adopted as the panel's, since they assert exactly the layout
   claims (two monitors, three collapsed panels each below their canvas, completed runs only, filtering as you type).
3. **The host behaviours.** The pair presets, the time link and the remembered state, each with its own test.
4. **The removal.** The old list, the old viewer and their markup (51 `run-view-` references in
   `templates/dashboard.html`) and their CSS go, and the workspace-navigation test that walks the old list is
   re-pointed at the combos.
5. **The draft.** `static/run-view-draft.html` and `tests/.../test_run_view_draft_browser.py` are deleted together,
   as their own headers say they will be, with nothing left at either path.
