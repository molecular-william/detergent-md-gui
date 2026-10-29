# A Run view panel, in both workspaces

Status: **draft for review. Nothing built.** *(Corrected 2026-10-14: the panel landed in `98f5825` — registered in
both workspaces, scoped per workspace, with the transport row; the citations below were re-pointed to the moved code.
Read this as the plan it was, not as current state.)* Two things are handed over together: this plan and the layout draft
`docs/superpowers/drafts/2026-10-13-run-view-panel-draft.html`. The draft decides the layout; this plan decides the
scope, the routes and the bond rule. Their review is the next step, and the specification changes before any code.

The ask, verbatim: *"For both 'Detergent validation' and 'Protein-detergent simulations', there should be a panel for
visualizing selected AA or CG runs."*

A second ask, added the same day, answered by *Transport controls under the canvas* below — **this is the part that is
built first if the panel is split**:

> *"For the run view, I would like there to be buttons for playing the run in forward time, playing the run in reverse
> time, and a slider for choosing the frame to show and start at, similar to how NGLview widget works in Jupyter
> Notebooks. The buttons and slider should be in the same line and below the NGL visualization."*

## Why one new panel rather than two

The two workspaces hold different run types and the same reader question — "what did this run actually produce, and
does it look like what we said it was?" A panel registered in both workspaces, scoped to each workspace's own run
types, is one component and one bond rule. Two panels would be two viewers, two guards, and the second one would be
the one that forgets the guard.

## Current state, verified against the tree

- **The registry is the single place a panel is declared.** `dashboard/web/sections.py:24-25` (`validation` tabs) and
  `:37` (`simulations` tabs); `:44-54` `PANELS` (label + glyph); `:59-69` `PANEL_BLURBS`; `:87-97` `TAB_IDS`
  (slug → DOM id). The template writes the tab and the section from these, and `main.js` mounts by DOM id.
- **Stylesheet head order is fixed and load-bearing**: `dashboard/web/templates/dashboard.html:6-13` links
  `dashboard.css`, `runs.css`, `new-run.css`, `mappings.css`, `compositions.css`, `pdc.css`, then **`layout.css`**,
  then `workspaces.css`. `layout.css` states the twelve-column measure and the per-panel spans
  (`layout.css:44-63`), which is why it must come last; `new-run.css:2` states a competing two-column grid for
  `#run-form.new-run-layout` and loses to it only because of the order.
- **`/api/jobs` is the only run list.** `routes/runs.py:96-110`; `pagination()` caps `limit` at 100 and defaults to
  20, newest first. Its `view=summary` shape carries `run_type` (`web/views.py:24-28` `VISIBLE_FIELDS`). There is **no
  run-type filter and no cursor.** `pdc.js:71` already works around the page size with `?limit=100` — and pays for it
  by pulling the full record shape, `analyses[].outputs` included.
- **The three routes that serve a run's own pictures**:
  `GET /api/jobs/<id>/artifacts?media=1` and `GET /api/jobs/<id>/figures` (`routes/runs.py:252-270`, `.png`/`.svg`/
  `surface-comparison.html` only); `GET /api/jobs/<id>/artifacts/<relative>?inline=1` (`:273-284`, any file in the run
  directory, sandboxed CSP on `.html`); and the PDC trio `GET /api/pdc/<id>/snapshots`,
  `/api/pdc/<id>/snapshots/<stage>/<pdb>`, `/api/pdc/<id>/system.pdb` (`routes/pdc.py:95-147`). **There is no route
  that serves an individual trajectory frame**, and no route that serves a run's structure with its own bonds outside
  the PDC branch.
- **The guard the repository already has**: `pdc.js:229-231` — `if (/^CONECT/m.test(text)) parameters.inferBonds =
  'none'`. It exists because a file carrying the model's own bonds is otherwise drawn with NGL's distance guess
  *as well*: the vendored build parses CONECT records into `bondStore` and then still runs `Vm(structure,
  this.inferBonds)` with `inferBonds` defaulting to `'all'` (`static/vendor/ngl.js`, `PdbParser`). `pdc_view.py:13-19`
  records the measurement: a placement frame the model bonds 60 ways was drawn 90 ways, head beads onto tail beads.
- **Two NGL views still do not use the guard**: `mapping-ngl.js:100-104` loads the molecule PDB *and* the bead PDB
  with default parameters (both are `.pdb`), and `compositions.js:51` loads the preview PDB — which the server writes
  *with* CONECT (`models/compositions/topology.py:render_pdb`) — with default parameters, then adds a `line`
  representation over the beads (`compositions.js:81`). The molecule file's CONECT is read
  (`models/mappings/overlay3d.py:31-52`) and the beads' is not (`:83-106`: one `HETATM` per bead, element `C`).
- **The structures a live run actually holds** (read from `workspace/dashboard/runs/`, 14 runs: 6 `osmotic`,
  6 `aa_only`, 2 `aa_cg`; every PDC run was deleted today):
  - `aa_only` (`03875cf39790`): `stages/07_reference/lig.gro` (the published AA solute), whole-box `.gro` at
    `01_solvation/`, `02_ions/`, `03_minimization/`, `04_nvt/`, `05_npt/`, `06_production/`; the trajectory
    `stages/07_reference/lig.xtc`; **no `.png`/`.svg` at all**, and **no `snapshots/` directory**.
  - `aa_cg` (`22075892b606`): `stages/2_mapping/mapped.gro` (the mapped CG solute in the model's bead order),
    `stages/4_CG_sim/{boxed,solvated,min,eq,md}.gro`, the CG topology `stages/3_initial_CG/LIG1.itp`, the mapping
    `stages/2_mapping/model.json` (each bead's `size` class and `export_name`), the trajectories
    `stages/4_CG_sim/{eq,md}.xtc`, and five figures under `stages/5_assessment/` + `stages/3_initial_CG/`.
  - No run of any type has a `snapshots/` directory. `analysis/runs/observability.py:119-157` (`generate`, with its
    helpers `_sample_indices` `:96-103`, `_stride` `:106-108`, `_frames_series` `:111-116`) writes them. *(Corrected
    2026-10-14: when this plan was written that producer hard-coded `stage='1_AA-reference'` looking for
    `prod/lig.gro` + `prod/lig.xtc` — a layout an `aa_only` run does not have (its solute lives at `07_reference/`)
    and an `aa_cg` run does not have either (its AA half is a *shared reference*, `stages/1_AA-reference/` holding
    only the stage script) — so the `snapshots` kind (`analysis/kinds.py:194-205`) had produced nothing for any of
    the 14 live runs. The landed producer instead resolves the run's own layout through `layout.frame_source`, and
    the kind carries `runs_for_every_run=True`, so it runs for every run with a trajectory.)*
  - A `.gro` loaded into this vendored NGL draws **no bonds at all** — the GRO parser has no bond inference and the
    files carry none. The invented-bond failure lives entirely on the `.pdb` path.

### What the vendored NGL build does with frames (measured on this box, 2026-10-14)

The transport row is only honest if both its frames and its playback come from the viewer, so the build was driven
directly: `static/vendor/ngl.js` (NGL 2.3.1 per `ngl.js.source.json`) in Chromium, through the class the bundle exports
(`e.TrajectoryPlayer=hg`) — the same player the nglview widget drives from Python.

- **A multi-model file without `asTrajectory` is not a trajectory.** A 41-`MODEL` PDB loaded with
  `{ext: 'pdb', inferBonds: 'none'}` came back as **one structure of 328 atoms, `structure.frames` empty, no
  trajectory** — every model concatenated into a single picture of the molecule drawn 41 times over. The same bytes
  with `asTrajectory: true` give `structure.frames.length === 41`.
- **`loadFile` does not attach the trajectory by itself.** After the `asTrajectory` load, `component.trajList` is
  still empty; `component.addTrajectory()` is what creates it (`trajList[0].trajectory.frameCount === 41`). The only
  place the bundle calls `addTrajectory()` for you is inside the default-representation path, which this panel does not
  use. A row built on the assumption that the trajectory is there renders a plausible picture with a dead slider.
- **The player's defaults are `{step:1, timeout:50, start:0, end:frameCount-1, mode:'loop', direction:'forward'}`**,
  and `_next()` fixes what the ends do: at the end of the range `mode:'once'` **pauses and clamps** to `end`
  (forward) or `start` (backward); `mode:'loop'` **wraps** to `start`/`end`; `direction:'bounce'` **flips direction**
  and keeps running. `play()` starts from **the frame on screen** (`Math.ceil(currentFrame/step)*step`), except at the
  far end of the direction, where it rewinds to the other end; `stop()` pauses and jumps back to `parameters.start`.
  Measured: forward from frame 7 for 600 ms → frame 11; backward from 20 for 600 ms → 15; `once` at frame 25 → stays
  on 25 and `isRunning` goes false; `once` backward at frame 0 → rewinds to the last frame and plays down;
  `loop` at 25 → wraps to 0 and advances; `bounce` with `start 20, end 25` from 24 → flips at 25 and comes back;
  `stop()` with `start=5` → frame 5.
- **Rate:** 11 frames advanced in 1000 ms at `timeout: 100`, 19 at `timeout: 50` — the parameter is milliseconds per
  frame, and playback is driven by `requestAnimationFrame`.
- **A hidden tab does not play.** With the same page in a background tab the player advanced **0 frames** and
  `requestAnimationFrame` ticked **0 times in a second**; after `Page.bringToFront` it ticked 61 times a second and the
  player ran at the rate above. A hidden panel is a hidden tab, so a panel that starts playing while unselected shows
  its last frame and nothing else.
- **A PDB trajectory carries no time.** `trajectory.deltaTime` is 0 and `getFrameTime(i)` returns 0 for every frame,
  so no time can be printed from the renderer for frames that arrive as PDBs — see D15.
- `setFrame(n)` is what moves the drawn atoms (atom 0's x went 14.000 → 8.330 between frames 0 and 40), and
  `signals.frameChanged` fires on it — which is how the row's readout and the strip keep step with the playhead.

## What a run offers to look at, and which route serves it

| what | route | use it? |
| --- | --- | --- |
| a stage's own structure file | `GET /api/jobs/<id>/artifacts/<rel>?inline=1` | **yes, for `.gro`** — the only door that exists for a run's own stage files |
| the run's figures | `GET /api/jobs/<id>/figures` | **yes** — the run's own `.png`/`.svg`/`surface-comparison.html`, opened inline through the artifact route |
| one figure, embedded | `GET /api/jobs/<id>/artifacts/<rel>?inline=1` | yes, for the interactive `.html` (the route sets the sandboxed CSP it needs) |
| a PDC run's snapshots and built system | `GET /api/pdc/<id>/snapshots`, `/system.pdb` | **yes, but delegated** — see the overlap section |
| a trajectory frame of an `aa_only`/`aa_cg` run | — | **no route exists.** Not invented, not faked in JavaScript |
| a CG structure with the model's own bonds | — | **no route exists.** T3's, and it is the only new endpoint this plan asks for |
| the frames the transport row plays | `GET /api/jobs/<id>/artifacts/analyses/snapshots/<signature>/<attempt>/<output_directory>/snapshots/AA-frames.pdb?inline=1` | **yes** — one multi-model PDB, loaded `asTrajectory: true`, read out of the `snapshots` analysis's own published attempt (see the note under T4); a run with no trajectory publishes none and the row is drawn and disabled with its reason |
| the run record (stages, tools, provenance) | `GET /api/jobs/<id>` | yes, for the identity line |

Two things the panel must **not** do: read a `.xtc` in the browser (binary, and no pairing route), and build a viewer
URL from a filesystem path (AGENTS.md; the API hands back run-relative paths, and the route is what turns one into a
URL).

## Transport controls under the canvas

Two play buttons and one frame slider, **on one line, directly below the NGL canvas**, in the manner of the nglview
widget. What that widget actually is, read from its own source rather than from memory — `nglview/widget.py`
(`_create_player`), `nglview/js/src/widget_ngl.ts` (`createIPlayer`) and ipywidgets' `widget_int.py` / `widget_int.ts`:

- The controls are **one row**: `HBox([Play(max=max_frame, interval=100), IntSlider(max=max_frame)])`, with `jslink`
  binding slider value ↔ the widget's `frame`, and both maxima ↔ `max_frame`. The slider **is** the frame index.
- `interval=100` ms per step and `step=1`; the Play button's `repeat` flag **defaults to false**, so its `animate()`
  steps to `max` and then sets `_playing` false — **it stops at the end**, and a separate retweet button turns looping
  on.
- It is **not** below the canvas: the row is appended into `stage.viewer.container` at `position:absolute; bottom:5%;
  left:10%; opacity:.7` and `display:none` until the pointer enters the canvas. The ask inverts both of those
  ("below the NGL visualization", and there to be read without hovering), and that is what this panel builds.

Decisions, each stated in the panel as well as here:

- **D11 — the row is two buttons and a slider, in that order, on one line under the canvas**: `◀` play in reverse,
  `▶` play forward, then the frame slider carrying its `n of m` readout. Nothing else goes in the row — no step
  buttons, no rate field, no mode dropdown, no stop button: a pause is the running direction's own button pressed
  again (what nglview's single Play button does), and the slider's own frame is where playback starts, so there is no
  "jump to start" affordance to add. Reversal: one more control in the row, and the row is no longer the ask's row.
- **D12 — at the ends, playback stops** (`mode: 'once'`, NGL's own parameter): forward stops on the last frame,
  reverse on the first. Reversal: `loop` wraps to the other end, `bounce` flips and never stops. Rejected as the
  default because a run watched forward from frame 0 that silently wraps makes the run's last frame indistinguishable
  from its first — the one thing this panel exists to keep straight. Both alternatives are one `setParameters` call
  away, and the draft's demo block lets you watch all three.
- **D13 — the rate is fixed at 100 ms a frame (ten a second)**, nglview's own `interval`, printed on the row so a
  reader can tell what rate they are watching. It is **not a control**; the ask fixes the row's contents. NGL's own
  player default is 50 ms, and the panel follows the widget the ask names. Reversal: a `fps` field or a rate menu, and
  a fourth element in the row.
- **D14 — the slider is bound to the trajectory's frame** (`min: 0 … max: frameCount - 1, step: 1`), and that frame is
  both the one shown and the one playback starts from — NGL's own `play()` rule (`Math.ceil(currentFrame/step)*step`,
  rewinding to the other end only when the playhead already sits at the far end). `parameters.start` stays 0 so every
  frame stays reachable in reverse; the alternative, the slider also setting `start`, makes reverse playback refuse to
  go below it. Reversal: a second slider for `start`/`end`, which is a range control the ask did not ask for.
- **D15 — the slider prints the frame index and never a time.** It reads `frame 12 of 40`; a time appears only when
  the trajectory itself declares one (`trajectory.deltaTime` non-zero, read through NGL's `getFrameTime`). Frames
  served as PDBs declare none — measured, `deltaTime 0` and `getFrameTime(i) === 0` for every i — so a panel printing
  "12.0 ps" beside them would be inventing it. Where the frames came from, and the stride they were sampled at, is
  said in words beside the row instead.
- **D16 — the strip follows the playhead and never starts it.** A strip button sets the frame the way the slider does
  and stops there; the pressed state moves **only** when the playhead is exactly on a saved frame, so a strip of three
  sampled moments lights up three times a pass and not in between. This keeps the strip's empty reason (D6) visible
  for the 14 live runs, and keeps the strip from implying a saved moment is "current" while the playhead sits between
  two of them.
- **D17 — where the viewer finds no frames, the row is drawn and disabled**, with the reason in each control's
  `title`, in the row's own readout, and in the paragraph under it: the loaded file holds one frame, and no route
  serves the run's trajectory. That is the state of all 14 live runs today, and the draft shows it. Reversal: hide the
  row instead, which tells the reader less than a disabled control that says why.

## Choosing a run

- One fetch of `GET /api/jobs?limit=100&view=summary`, filtered in the browser by the **workspace's own run types**:
  `validation` → `aa_only`, `aa_cg`, `cg_composition`, `osmotic`; `simulations` → `pdc`. The summary shape is the
  point: `pdc.js:71` fetches the full shape for a list and pays `analyses[].outputs` for it.
- Within that scope, three controls: **run type** (rendered only when the scope holds more than one), **status**
  (default `completed` — a queued run has no structures yet), and **search** over id, label and molecule. The list is
  a 12 px table: `id · label · molecule · type · status · created`.
- The endpoint caps at 100 and offers no cursor, so the panel states its own count — *"showing N of M runs in this
  workspace; the list is capped at 100"* — rather than silently truncating. T5 removes the cap's meaning by asking the
  route for a `run_type` filter; until then the number is stated.
- **How a reader finds a run**: the list is one door; the other is a link. Each Runs-table row grows a "View run"
  link to `/<workspace-slug>/run-view?run=<id>`, and the panel reads `?run=` at mount — the same deep-link contract
  `pdc.js:82-86` already implements for Complexes, so a link written by hand or by another panel lands on the run
  already drawn.

## AA versus CG: what is drawn, and how bonds are decided

The panel never hands a file to NGL's distance inference on the strength of its extension. One helper decides, and
every load goes through it:

1. **A file that carries CONECT** (`/^CONECT/m`, `pdc.js:229-231`'s own test) → `{inferBonds: 'none'}`, and the bonds
   drawn are the model's. This is the PDC snapshots and `system.pdb`, and it is any PDB the server writes.
2. **A coarse-grained structure** — a `2_mapping` or CG-stage path, or a run of type `aa_cg`/`cg_composition`/`pdc` →
   `{inferBonds: 'none'}` as well. A CG bead is a radius stand-in, so a distance guess is wrong by construction even
   when the distances look plausible. A `.gro` takes this branch and draws **no** bonds, because this NGL build's GRO
   parser infers none; the caption says the model's bonds are in the run's `.itp` and names it.
3. **An all-atom file with no CONECT** — the only case NGL's own inference is left on, because on real chemistry it
   reproduces the bonds. For an `aa_only` run this is the run's molecule PDB under `stages/common/molecule/`; the
   whole-box `.gro` files are served as-is and drawn bondless.

What the reader sees, and what each says:

- **An AA run (`aa_only`)**: the published reference `stages/07_reference/lig.gro` first, then the stage `.gro`s
  before it. The `.gro` files are drawn bondless with a caption naming the file and the atom count; the molecule's
  PDB is drawn `ball+stick` on element with its chemistry inferred. Frames: the strip is present and **empty with a
  reason** — *"this run recorded no frame snapshots; the trajectory is `stages/07_reference/lig.xtc` and no route'
  serves a single frame of it"* — and the transport row under the canvas is drawn with both buttons and the slider
  disabled for that same reason (D17). Figures: this run has none, and the panel says so.
- **A CG run (`aa_cg`)**: `stages/2_mapping/mapped.gro` (the mapped model itself) first, then `4_CG_sim/min,eq,md.gro`.
  Beads are drawn as spheres, sized from the run's own `stages/2_mapping/model.json` size classes when it is readable
  and uniform otherwise — with the caption saying which, because a bead's radius is a claim. Bonds: none drawn, with
  the caption naming `stages/3_initial_CG/LIG1.itp` as where the model's `[ bonds ]` and `[ constraints ]` are, and
  saying that the panel draws none rather than guessing them. Frames: the same empty strip, naming
  `stages/4_CG_sim/md.xtc`, and the same drawn-but-disabled transport row. Figures: five, listed and opened inline.
- **A PDC run**: the chooser offers them; the panel does not draw them (the overlap section).

### Why the guard is not only a flag

`inferBonds: 'none'` is necessary and not sufficient. The three branches above are the rule, and the readout beside
the canvas reports **what the renderer resolved** — the component's atom count and bond count, read back from the
loaded structure — not what the panel intended to send. A guard asserted only on the request is a guard that cannot
fail, and these two failure modes (a selection matching nothing, an inference quietly adding bonds) both render as a
plausible picture with a clean console.

## Overlap with what already exists, named

| existing surface | what it already draws | what this panel does |
| --- | --- | --- |
| **Runs** (`#runs`, both workspaces; `runs.js`) | run table, per-run artifact list, **`RunFigureViewer`** with zoom/pan over `/api/jobs/<id>/figures`, distance diagnostics, console | **complements.** The panel does not rebuild the zoomable gallery: figures are listed and opened inline through the artifact route, and the hint says the zoomable view is the Runs panel. The panel adds what Runs has never had — a 3D structure view and a run-scoped chooser. |
| **Complexes** (`#pdc`; `pdc.js`, `/api/pdc/<id>/snapshots`) | the built system and the whole snapshot series of a PDC run, with each moment's criterion numbers | **duplicates it for PDC runs, so it must not.** The panel's PDC state says *"this run's system and snapshots are drawn in Complexes"* and links to `/protein-detergent/complexes?run=<id>`; the panel draws nothing for a PDC run. |
| **Mapping Validation** (`#validation`) | numbers: ring/constraint pairs, bonded terms, shape, across molecules | none. Different question; no shared control. |
| **Bead Assignment** (`#mappings`, incl. the 3D overlay) | one molecule's heavy atoms + its beads | none directly, but `mapping-ngl.js` is the first of the two call sites carrying the bond defect — T6. |

The one genuine overlap is **figures** (Runs already shows them) and the one that would be a duplicate is **PDC**
(Complexes already shows it). Both are answered by the panel *not* doing them, which is why D5 and D9 exist.

## Decisions, each with what reversing it costs

- **D1 — one panel, registered in both workspaces**: slug `run-view`, DOM id `runview`, glyph `⬓`,
  label "Run view", blurb *"one run, its structures, its frames and its figures"*. Reversal: two registrations, two
  URLs, and the shared component splits into two viewers with two guards.
- **D2 — the run list is scoped to the workspace's own run types** (validation: `aa_only`, `aa_cg`,
  `cg_composition`, `osmotic`; protein-detergent: `pdc`). Reversal: one unfiltered list, and the reader picks their
  workspace's kind out of another workspace's runs.
- **D3 — the run list says its own cap** (one page of 100, no cursor). Reversal: none until a workspace passes 100
  runs; then T5's filter is the fix, not a bigger page.
- **D4 — structures come from the artifact route.** Reversal: a bespoke structure route now, which T3 builds anyway
  for the CG bond case.
- **D5 — figures are listed here, zoomed in the Runs panel.** Reversal: mount a second `RunFigureViewer` here (~1
  module reuse, and two figure galleries to keep in step).
- **D6 — no frames are offered for `aa_only`/`aa_cg`/`cg_composition`, because no route serves one.** The strip shows
  the `snapshots` analysis artifacts when they exist and says plainly when they do not; the transport row (D11–D17)
  plays the same frames, so it is disabled with the same reason until T4 writes them. Reversal: T4 (make the frame
  producer read the `07_reference` layout) plus a frame sampler route — real work, and its own panel control.
- **D7 — the three-branch bond rule above**, with `inferBonds: 'none'` whenever a file carries CONECT **or** is
  coarse-grained. Reversal: none available; the alternative is drawing bonds the model does not have, which is the
  defect this panel exists not to repeat.
- **D8 — CG beads are sized from the run's own `model.json` when readable**, uniform otherwise, caption saying which.
  Reversal: uniform spheres everywhere, which is honest but loses the one place the run states a bead's size class.
- **D9 — PDC runs delegate to Complexes.** Reversal: fold Complexes' viewer here and leave Complexes as the build
  door; that is a bigger change than this ask and would take the snapshot strip away from the panel that shows the
  criterion numbers beside it.
- **D10 — deep link `?run=<id>` plus a "View run" link on each Runs-table card.** Reversal: the run is found only by
  searching a list, which is the thing the ask is about.
- **D11–D17 — the transport row**, decided in *Transport controls under the canvas* above: two buttons and the frame
  slider on one line under the canvas (D11), stop at the ends (D12), a fixed 100 ms a frame (D13), the slider bound to
  the frame shown and started from (D14), the slider printing an index and never a time (D15), the strip following the
  playhead and never driving it (D16), and a drawn-but-disabled row that says why (D17).

## Tasks

Test-first, one commit each with its own gate run. Paths are exact.

**T1 — register the panel.** `dashboard/web/sections.py` (`tabs` for both workspaces, `PANELS`, `PANEL_BLURBS`,
`TAB_IDS`); `dashboard/web/templates/dashboard.html` (one `<section id="runview">`, hidden unless `panel ==
'run-view'`); `dashboard/web/static/js/main.js` (import + mount case). Tests: a unit test that both workspaces list
`run-view` and that `panel_label('run-view', …)` and `tab_id('run-view')` resolve, so no workspace renders a tab that
resolves to no section; a browser test that `/detergent-validation/run-view` and `/protein-detergent/run-view` both
render the section and that the other panels' labels are unchanged. Acceptance: validation goes from six tabs to
seven — the rail already carries seven (`layout.css:30-41`), so no rail change.

**T2 — the layout.** New `dashboard/web/static/run-view.css`, linked **after `pdc.css` and before `layout.css`**, and
the spans added to `layout.css` beside `.pdc-workspace`'s (`layout.css:61-63`). Tests: a browser test asserting the
two columns sit side by side at 1600 px (different `x`, each near its share of the panel) and stack below 1100 px,
plus the existing 390 px no-overflow guard (`test_lazy_loading.py`). **Acceptance, measured in the draft:** see the
draft's own geometry note below — the head order is what makes the two columns, and reversing it stacks them.

**Measured in the draft on 2026-10-14** (Chromium, 1600 px window → 1585 px panel, 0 px horizontal overflow). The head
order, read off the page: `dashboard.css → runs.css → new-run.css → mappings.css → compositions.css → pdc.css →
layout.css → workspaces.css` — `new-run.css` third, `layout.css` seventh, and the two inline blocks in their places
around it. **The transport row (T8), on all three blocks that carry one:** controls `36×29 @ top 1474 / centre-y
1488.4`, `36×29 @ 1474 / 1488.4`, `880×19 @ 1479 / 1488.4` → tops spread 5 px, **centres spread 0 px**, tallest control
29 px, so they are on one line; the row is `x 568 y 1474 w 968 h 29`, **inside the panel** (`x 24…1561, y 867…2738`);
the **canvas's bottom is 1466, the row's top 1474** → the canvas is above it; row right 1536 against panel right 1561 →
no overflow. At **1100 px** and at **390 px** the columns stack as designed and the row is still one line, still inside
the panel, still under the canvas, with **0 px** of horizontal overflow at both widths.

**Two traps the row's own stylesheet has to handle**, both measured while building the draft:

1. `dashboard.css:1` sets `label{margin:12px 0;font-weight:600}`, `input{padding:9px}` and
   `label>input:not([type=checkbox]){display:block;width:100%;margin-top:5px}`. Un-normalised, the slider's label
   carries a 12 px top *and* bottom margin, which sets the flex line's cross size to **60 px** while the controls are
   29–36 px: a "row" 24 px taller than anything in it, with the buttons 4 px off the label's top. `run-view.css`
   states `margin:0; width:auto; padding:0` on the row's label and slider — the same normalisation `new-run.css:77` and
   `mappings.css:25` already carry, and the numbers above are what they buy.
2. `dashboard.css` paints `button{background:var(--accent); color:white}`, so any pill this sheet repaints white must
   state its own `color`. The draft's run-list ids and its frame-strip labels were **white on white** — invisible, and
   invisible in a still as well as on screen — until it did.

Two stills sit beside the draft: `...-run-view-panel-draft-transport-demo.png` (the row working, over the 41 synthetic
frames) and `...-run-view-panel-draft-transport-disabled.png` (the row as every live run shows it: one frame in the
file, both buttons and the slider disabled, the reason under it).

**T3 — the bond rule, and the one new route.** A shared helper (in `run-view.js`, or a small module both it and the
two existing call sites import) that returns the load parameters from the file text, the run type and the path;
`GET /api/jobs/<id>/structure?path=<run-relative .gro|.pdb>` in `routes/runs.py`, writing the run's own
`[ bonds ]` + `[ constraints ]` as CONECT through `execution/adapters/pdc_view.py:molecule_bonds`/`system_pdb`
(already tested by `tests/dashboard/unit/test_pdc_view.py`), locating the topology by the rule `pdc_snapshot.
topology_path` uses, and refusing with a reason when it cannot be read. Tests: unit, on a hand-made `.gro` + `.itp`,
asserting the CONECT set equals the moleculetype's bonds (not a superset), and that a structure whose beads do not
match the `[ atoms ]` order comes back unbonded with the REMARK; integration, that the route 404s outside the run
directory. Acceptance: the reader sees the model's own bonds for a CG run, and **no** bond the model does not have.

**T4 — frames, or an honest empty strip.** Either wire the `snapshots` kind to the `aa_only` layout
(`analysis/runs/observability.py:119-157`, with `layout.frame_source` at `:131`: resolve `07_reference/lig.gro` + `lig.xtc` as well as `1_AA-reference/
prod/…`, and record which layout it read) so the artifact route serves the published `AA-first.pdb` — or ship the strip
empty with its reason. The first is a small change to a tested function and makes the strip real for the six `aa_only`
runs; the second is honest and costs the ask's word "frames". **Recommend the first.** Tests: the resolver returns the
`07_reference` pair for an `aa_only` run and the `prod/` pair for a consumer run, and names the one it used.
  Reading the layout is also what gives the transport row something to play, and the three frames the kind writes
  today (`AA-first/middle/last.pdb`) are not a trajectory. So the first branch writes one more artifact: a
  **multi-model PDB** sampled from the same trajectory at a stated stride (MDAnalysis
  writes N frames in one call), with the stride and the source path recorded beside it. The panel then makes **one**
  request for the whole series and loads it `asTrajectory: true`; assembling a trajectory client-side out of N
  per-frame files is the thing this avoids. Tests: the file's `MODEL` count equals the requested sample count, and each
  frame's atom count equals the solute's.
  **Where the panel reads it (corrected 2026-10-14, measured against the landed producer):** the frames now exist
  without anyone asking — the `snapshots` kind runs for every run that reaches a terminal state, samples 40 frames,
  and skips with a named reason where there is no trajectory. It publishes the way every analysis does, inside its own
  attempt: `analyses/snapshots/<signature>/<attempt>/result.json`, whose `output_directory` names the content-addressed
  root, with the files under `…/<output_directory>/snapshots/{AA,CG}-frames.pdb`. So there is no run-root `snapshots/`
  path to read: the panel finds the newest `analyses/snapshots/*/*/result.json`, joins the attempt directory with the
  record's `output_directory` (and the record's `outputs_sha256` names the published files), and asks the artifact
  route for that run-relative path. The producer is deliberately **not** asked to publish outside its attempt
  (`references/published-analysis-addressing.md`).

**T5 — the run-type filter on `/api/jobs`.** `routes/runs.py:96-110` + `database().page(…, run_type=…)`. Reversal
cost stated in D3. Tests: a filtered page returns only that type and keeps `total` consistent.

**T6 — the two existing call sites.** `mapping-ngl.js` and `compositions.js` take the same guard: both load `.pdb`
files whose beans are radius stand-ins, and `compositions.js`'s file carries CONECT the viewer currently doubles. A
separate commit, before this panel ships, so the new panel is not the only NGL view that gets it right. Measured
before/after on the same file: bond count read back from the component. Tests: a browser test asserting the loaded
component's bond count equals the file's CONECT count for the bead file. **Decide with the user whether this is in
scope now** — it is a behaviour change to two panels they can see.

**T7 — the door from Runs.** A "View run" link on each Runs-table row (`runs.js` + `job-template` in
`dashboard.html`) to `/<slug>/run-view?run=<id>`, and the `?run=` read at mount. Tests: browser — the link lands on
the panel with that run drawn.

**T8 — the transport row.** `run-view.css` gains its rules (`display: flex; flex-wrap: nowrap; align-items: center;
gap: 8px` — one line, the slider the flexible item); `run-view.js` gains the row: two buttons, one `input[type=range]`,
`const FRAME_MS = 100`, `const END_MODE = 'once'`, and a `TrajectoryPlayer` per loaded structure, created only once
`component.addTrajectory()` has produced a trajectory (**measured: without that call there is no trajectory to drive,
and `loadFile` does not make one**). The row sets `aria-pressed` on the button whose direction is running, binds the
slider to `frameCount - 1` and calls `traj.setFrame(...)` on `input`, reads `currentFrame` back from the trajectory for
its readout, and leaves all three controls disabled with a non-empty `title` when `frameCount < 2`. The structure load
passes `asTrajectory: true` whenever the panel asked for a sample series (**measured: without it a 41-model PDB draws
328 atoms in one picture and no trajectory at all**). Tests: browser, driving the row and asserting on the renderer —
forward advances `trajectory.currentFrame`, reverse decreases it, `once` stops at the last frame and leaves the
playhead there, the slider's `max` equals `frameCount - 1`, moving the slider moves the frame and the pressed state,
and a one-frame structure disables all three controls with a reason in the `title`. Second browser test, geometry: the
row's three controls share a row (`|Δy| < half a row`), the row sits inside the panel, and the canvas's bottom edge is
above the row's top edge.

## Acceptance

- Both workspaces render the panel; no other panel's label, id or order moves.
- The run list is scoped to the workspace's own run types and states its cap.
- An AA run and a CG run each draw the structures they hold, and the reader can tell which file is on screen, how many
  atoms it has, and where its bonds were decided.
- **No bond is drawn that the model does not have**, in any of the three branches, verified by reading the bond count
  back off the loaded component rather than by asserting the parameters sent.
- Frames are either shown from artifacts that exist, or the strip says why they are not.
- The transport row is two play buttons and the frame slider on one line under the canvas; playback stops at the ends;
  the row states its rate and its frame count; a structure holding one frame leaves the row disabled **with the
  reason** in it.
- Playback is driven by the renderer's own player (`TrajectoryPlayer` `direction`/`mode`/`step`/`timeout`), verified by
  reading `trajectory.currentFrame` back, never by asserting the parameters handed to it.
- `dashboard/.venv/bin/python -m pytest -m 'not browser and not slow' -q`, `-m browser`, and
  `ruff check dashboard tests` all clean.

## Out of scope

- Not a frame extractor of its own beyond T4; not an `.xtc` parser in the browser.
- Not removing Complexes' viewer, and not moving its snapshot strip.
- Not adding a run-type filter to the browser's job polling, or touching `/api/jobs`'s page size.
- Not claiming that a run looks right, or that a completed run is validated. The panel draws what a stage wrote.

## Questions for the user

1. **T6 (the two existing NGL views that invent bonds) now, or after?** My recommendation: now, as its own commit, so
   the guard has one implementation and the panels agree.
2. **T4: make the frame producer read the `aa_only` layout** (the strip becomes real for six runs), or ship the strip
   empty with its reason? My recommendation: make it read the layout — the ask names frames, and with it write the one
   `AA-frames.pdb` sample series (T4's extension) so the transport row has a run to play rather than three moments. How
   many samples should that file carry? The row is worth having past a few dozen; my recommendation is **40**, evenly
   spaced over the trajectory, with the file naming its stride.
3. **PDC runs: delegate to Complexes (D9), or should this panel become the one place a run is looked at**, with
   Complexes keeping only its build door?
4. **A rail tab in the validation workspace makes seven.** That is what the rail was built for, so nothing needs to
   move — but the seventh label is now "Run view" beside "Runs". Keep both, or should this be a section inside Runs?
5. **CG bead radii: the run's `model.json` size classes (D8), or uniform spheres** with the caption saying so?
6. **The transport row's rate and its ends.** Fixed at 100 ms a frame and stopping at the end (D12/D13, which is what
   the nglview widget's Play button does), or would you rather have a rate control and a loop/bounce toggle in the row?
   My recommendation: the fixed rate and the stop, with the alternatives in the draft's demo block to watch first.
7. **The `AA-frames.pdb` sample count** (T4's extension): 40 evenly spaced frames, or another number and stride? The
   stride is what a reader has to be told, so it goes in the panel whichever way it lands.
