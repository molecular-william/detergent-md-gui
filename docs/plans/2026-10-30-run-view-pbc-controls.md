# Run view: a taller canvas, one build action, ns per frame, and PBC options

Status: **implemented 2026-11-02** (approved 2026-10-30; see *Execution record*). Read `docs/HANDOFF.md` first.

## The report

The Run view player shipped on 2026-10-30 (`docs/plans/2026-10-30-run-view-trajectory.md`). The follow-up asks for
five things:

1. The NGL canvas should be taller.
2. The readout cell that says **how the bonds were decided** can be removed; it is not useful.
3. What is the difference between **Recompute frames** and **Build frames**?
4. The frame-rate argument should be **nanoseconds per frame**, not a number of frames (a stride is unintuitive).
5. What does **Assemble** mean, and can there be options for PBC and the other arguments of `gmx trjconv`?

The two questions are answered below so the plan is not blocked on them; items 1, 3, 4 and 5 are work.

## Verified current state (2026-10-30)

- Canvas: `packages/core/src/dashboard/web/static/run-view.css:24` sets `.run-view-viewer { height: 420px;
  min-height: 300px }`. Two monitors sit side by side (`.run-view-monitors`, two columns above 1080 px).
- Readout: `run-view-monitor.js:553` adds `['how the bonds were decided', parameters.reason]` to the readout under the
  canvas; `run-view-monitor.js:523` does the same in the no-renderer fallback; `run-view-structure.js:62`'s
  `loadParameters` supplies the `reason` strings. Six browser assertions in `test_run_view_browser.py`
  (lines 459-461, 479-480, 509-514, 536-537, 564-571) hold text from those strings.
- Buttons: `run-view-trajectory.js:80` is the top **Recompute frames** button (it only opens the
  `<details>` form), and `:135` is the form's **Build frames** submit (the only thing that queues).
  `:636` also says "Recompute frames" in the stale-series note.
- Frame rate: the payload key is `stride` (frames) — `run-view-trajectory.js:28`, form `:127-128`, submit `:405`;
  the producer converts nothing, it slices `selected[::stride]` (`frame_series.py:206-232`) and records
  `cadence_ns = dt × stride / 1000`.
- Assemble: `frame_series.py:344` (`_assemble`) is a **display-only** gather: each molecule not in the anchor is moved
  by whole box images to the protein's centroid (or the first molecule's when the run has no protein), then the anchor
  is centred at the origin. It is per frame, assumes an orthogonal box (there is a `# ponytail:` note), never writes
  the trajectory, and `series_pdb` says so in its REMARK.
- PBC precedent: the pdc and CG stage scripts already make their production output whole with
  `gmx trjconv -pbc mol -center` (`pdc_assessment.sh:43`, `pdc_extension.sh:36`, `cg_simulation.sh:56`). A run's raw
  `prod/run.xtc` is *not* whole; `prod/whole.xtc` is. The player offers both legs, so a raw segment can look split.
- The run has what a `trjconv` call needs: `b920391735dd/stages/06_assessment/prod/` holds `run.tpr`, `run.xtc`,
  `run.gro` and `whole.xtc`. AA runs publish `lig.tpr`/`lig.gro` under `07_reference/`.
- MDAnalysis 2.9 provides the transformations to do the same work in-process: `unwrap`, `NoJump`, `wrap`,
  `center_in_box`, `fit_rot_trans`, `fit_translation`.

## Answers to the user's questions

### Recompute frames vs Build frames

They are the same action. The top **Recompute frames** button opens (and prefills) the form; the form's **Build
frames** submit posts the attempt. Nothing is queued until that submit. The labels disagree about what the reader is
doing and the top one is wrong before a series exists, so the fix is to make it **one action with one name**: the top
control becomes a form toggle ("Frame options"), and the submit says "Build frames" when no attempt matches the form
and "Recompute frames" only when one does (the stale note points at that same control).

### What Assemble means

It is not a GROMACS PBC conversion and not a trajectory rewrite. It takes each frame and moves each detergent (or other)
molecule by *whole box vectors* so the molecules gather around the protein, then puts the protein at the origin. It
exists because the viewer draws one image and a raw trajectory can show a molecule split across the periodic boundary.
`prod/whole.xtc` already solved that with `trjconv -pbc mol -center`; Assemble is a second, display-only version of the
same intent. With real PBC/center options it should disappear as a separate switch (see the work below), keeping only
a compatibility path so attempts built with `assembled: true` still play and still say what they are.

## Work

### 1. Taller canvas

- Change `.run-view-viewer`'s height to a responsive value that grows with the window (e.g.
  `height: clamp(520px, 58vh, 760px); min-height: 420px`). Keep the two-monitor grid and the 390 px no-horizontal-scroll
  rule; NGL needs `handleResize()` on the existing `resize`/`dashboard:tab` listeners (already wired).
- Browser test: the canvas is at least the new minimum at a normal viewport, and the narrow-window test still has no
  horizontal scroll. Do not assert a computed pixel height that a font metric can move; assert the element's height is
  above the old 420 px and that the canvas inside it fills the host.

### 2. Remove "how the bonds were decided"

- Drop the readout row at `run-view-monitor.js:553` (and decide the no-renderer fallback at `:523` the same way: keep
  the counts; a renderer-less page has no other explanation, so keep at most a one-line "bonds are not guessed" there
  or drop it too — do not leave a second phrasing of the same removed cell).
- `loadParameters` returns `reason` only for this row; remove it (and the `served` branch's reason string in `draw`) if
  nothing else reads it. Keep `inferBonds` and `ext`; they decide how the file is drawn.
- Update the six browser assertions that quote those sentences: keep the ones that assert the readout *counts* and the
  bond rule's effect (drawn bonds, hidden CONECT), and delete the ones that only name the reason. Add one assertion
  that the removed text is absent, so the row cannot come back by accident.
- The structure route and the writer still state their provenance in REMARKs; this change is only about the panel's
  readout.

### 3. One build action

- Rename the top button to **Frame options** (it opens/closes the form; `aria-expanded` on it). The submit's label is
  state-dependent: **Build frames** when the form matches no attempt, **Recompute frames** when it differs from the one
  shown; while an identical attempt is queued/running the submit is disabled and says so.
- The stale-series note says "Recompute frames" and should point at the form by its new name, or simply say "change the
  options and build again".
- Test: one visible submit path; the top control does not queue; the submit's label follows the state; no two labels
  for the same click.

### 4. Nanoseconds per frame instead of frames per step

Replace the `stride` argument with `interval_ns` (a positive number, or null for auto):

- UI: label **ns per frame**, placeholder "auto (about 120 models)", with a hint that the server records the cadence it
  actually got. Remove the "Step (frames)" control and its tests.
- Server (`frame_series._settings`/`_sample_indices`): accept `interval_ns` (finite, > 0) or null; refuse a
  non-positive value. Convert with the trajectory's own step: `stride = max(1, round(interval_ns * 1000 / dt))`. A
  requested interval smaller than `dt` becomes one frame and the recorded cadence is `dt`, not the request.
  `interval_ns` with `dt <= 0` is refused with the same "this trajectory states no time step" sentence the window uses.
  Keep accepting the old `stride` key **only** so already-built attempts stay readable; never send it from the panel.
- Records: `frames.json` carries both the request (`args.interval_ns`) and the effective `cadence_ns`; the build
  sentence says "one model every N ns" rather than "every Nth frame"; the summary already prints the cadence.
- Lookup: the panel's argument comparison list becomes `trajectory, structure, start_ns, end_ns, interval_ns, atoms,
  pbc, center, fit, group` (see below). Existing attempts recorded with `stride` and `assembled` must still be found
  and played, with their recorded cadence shown; the simplest compatibility rule is: when a legacy attempt's payload
  has no `interval_ns` and its other keys match, treat it as the default form and label it "built with a frame step".
- Tests: a producer case for each of (a) auto, (b) an exact multiple of `dt`, (c) a non-multiple (the effective
  cadence is `dt × stride`), (d) smaller than `dt`, (e) `dt <= 0` refused; a browser case that the form sends
  `interval_ns` and the sentence reads in ns. Keep the caps tests: the auto value still aims at 120 models and the
  240-model refusal names the count.

### 5. Assemble, PBC and the `trjconv` arguments

The user asked for the options `gmx trjconv` has. The ones that make sense for *display* are the PBC treatment, a
centre group and a fit; the rest (`-ur`, `-ndec`, `-dump`, `-conect`, `-box`) either change nothing a PDB viewer reads
or are performance/format knobs, and should be listed as deliberately omitted in the guide rather than hidden.

Proposed argument shape (replaces `stride`/`assembled`; the panel offers only what the run can answer):

| key | values | meaning |
| --- | --- | --- |
| `pbc` | `none` (default), `mol`, `whole`, `res`, `atom`, `nojump`, `cluster` | `trjconv -pbc`; `none` is the file as the run wrote it |
| `center` | boolean | `trjconv -center`; centres the `group` in the box |
| `fit` | `none`, `trans`, `rot+trans` | `trjconv -fit`; reference is the first sampled frame |
| `group` | `protein`, `solute`, `fragment:<letter>` | the selection `center`/`fit` use; the run's mapping supplies fragment letters |

- `mol`/`whole` are the same operation for a molecule whose atoms are contiguous (`unwrap` on molecules); `res`/`atom`
  wrap into the box (`wrap`); `nojump` is history-dependent and must be applied to **every** frame of the window in
  order, not only to the sampled frames, or the jump detection changes the answer; `cluster` is the one operation
  MDAnalysis does not provide — either call `gmx trjconv -pbc cluster` for it or leave it out of this slice and say so.
- The producer already reads every frame in the window in one pass, so per-frame transforms are cheap; only `nojump`
  forces work on every frame rather than only the selected ones. Measure before choosing `gmx trjconv` subprocesses.
- Implementation order: do `pbc`/`center`/`fit` with MDAnalysis transformations first, and pin them with a
  **differential test** against `gmx trjconv` on a fixture: `-pbc mol -center` and `-pbc nojump` must put the same
  atoms at the same positions (within the PDB's 0.001 Å) as the GROMACS output for the same frames. If the fixture
  shows a difference the transformation does not capture, fall back to running `gmx trjconv` for that option and say
  why in the module.
- The writer must say what it did: `series_pdb` already writes an `assembled` REMARK and a fitted-series REMARK; add the
  PBC/centre sentence (or generalise `assembled` into "view modifications"), so a played file never claims raw
  coordinates. Keep the rule: never rewrite the trajectory, always say this is a view.
- `assembled` becomes a legacy key: accepted by the server, mapped to `pbc=mol` + `center=true` for old attempts. The
  form no longer offers it as a separate switch; the explanation moves into the new options' hint text.
- Group names: the engine must not name a feature's run type. `protein` comes from the run's protein topologies (or
  MDAnalysis's own selection), `solute` from the atoms the writer keeps, and a fragment from the run's mapping
  (`structures.read_subunits`), exactly as the current fit selection does.
- Caps unchanged: the model and byte caps still refuse before any frame is read; the interval conversion must not
  sidestep them.
- Confirm with the user which of `cluster`/`res`/`atom`/`nojump` are wanted before implementing all seven; the table
  above is the proposal, and the plan should ship `none|mol|whole|nojump` first if the rest are not wanted.

### 6. Tests and documentation

- Unit: interval conversion and records; each PBC/centre/fit option on a small MDAnalysis fixture (positions and box
  asserted); the `gmx trjconv` differential test (skip with a reason when `gmx` is absent); a missing `tpr` is not an
  error for the MDAnalysis path; the legacy `stride`/`assembled` arguments still produce a readable record.
- Integration: the queue payload with the new keys; the same arguments reuse the attempt; a changed interval is a new
  attempt; an old attempt still lists and its args are shown.
- Browser: the taller canvas; the removed readout text; the form's label and ns field; the submit label follows state;
  both workspaces; the narrow window.
- Live: `b920391735dd` (the empty micelle) is the surviving long pdc example; `00b9ae6db23f` was deleted by the user
  on 2026-10-30, so do not use it. A raw segment (`06_assessment/prod/run.xtc`) vs its whole sibling is the natural
  case for checking `pbc=mol` visually and numerically.
- Docs: `PROJECT_GUIDE.md`'s Run view paragraph (the arguments and the PBC options), `HANDOFF.md` state, and an
  execution record appended here. `README.md` does not describe the payload.
- Gate: fast/browser/slow tiers, ruff, mutation check as `AGENTS.md` says.

## Hazards

- **`nojump` is stateful.** Applying it only to sampled frames is a different picture from `trjconv -pbc nojump` over
  the whole window.
- **`cluster` needs a group and a tpr**, and is the operation the old empty-micelle display assembly was written to
  avoid (never pull separate micelles together with `trjconv -pbc cluster`; `AGENTS.md` says so). If it is offered, its
  help text must say what it does to a micelle.
- **A PBC option is not dynamics.** It changes the view of the frames, never the run; the file's REMARKs are part of
  the contract.
- **Existing attempts.** The payload keys change; the panel's lookup and the server's acceptance must keep old series
  playable, and the panel must not silently relabel one.
- **Cost.** `mol`/`whole`/`center`/`fit` on 120 models is cheap; `nojump` over a 50,001-frame window is the same walk
  the producer already makes, so no extra pass — measure before adding one.
- **Caps and size.** The interval conversion cannot produce more models than the auto cap without the existing refusal.
- **Triclinic boxes.** The current display assembly assumes orthogonality; MDAnalysis's transforms do not, so the new
  path should either handle box vectors or refuse with the sentence the assembly uses.

## Definition of done

- The canvas is taller at a normal viewport and the narrow-window layout still has no horizontal scroll.
- The readout no longer carries a "how the bonds were decided" cell; the tests that quoted it are gone and one pins
  its absence.
- One build action with one name; the top control opens the form, the submit labels itself Build/Recompute from state.
- The form takes ns per frame; a blank is auto; the record states the requested interval and the effective cadence;
  the build sentence reads in ns; the caps still refuse too many models.
- `pbc`, `center`, `fit`, `group` are recorded in `frames.json`/`result.json`, applied by the producer, stated in the
  PDB REMARKs, and pinned by a `gmx trjconv` differential test for at least `-pbc mol -center` and `-pbc nojump`.
- Old attempts (stride/assembled) remain findable and playable with their own recorded cadence.
- Tiers, ruff and the mutation check pass; the docs and this plan's execution record are updated.

## Execution record (2026-11-02)

Landed in four disjoint lanes, one integrator running the tiers and the docs.

### What shipped

- **Canvas**: `.run-view-viewer` is `height: clamp(520px, 58vh, 760px); min-height: 420px`. A browser test proves the
  host is taller than the old 420 px and that NGL's canvas fills it before and after a resize to 390 px (which also
  proves `handleResize` runs), with no horizontal scroll. The readout's bold values gained `overflow-wrap: anywhere`,
  fixing a pre-existing 390 px overflow the taller-canvas test exposed (a bead-size sentence embeds
  `stages/2_mapping/model.json`).
- **Readout**: the `how the bonds were decided` row and its no-renderer twin are gone; `loadParameters` no longer
  returns `reason`. Counts and the CONECT/guess behaviour assertions stayed, and two panels now pin the removed text's
  absence (after a positive count assert, so absence cannot pass on an unwritten readout). The CONECT test's timing
  signal moved to the caption/path it already asserted.
- **One build action**: `#run-view-build` is **Frame options**, a disclosure (`aria-expanded`/`aria-controls`) over a
  hidden form; it never posts. The submit is the only build and reads **Build frames** / **Recompute frames** /
  **Building frames…** from whether an attempt matches and whether it is in flight. The stale note points at the new
  control.
- **ns per frame**: `interval_ns` replaces `stride` in the form and payload. The producer converts it with the
  trajectory's own `dt` (`stride = max(1, round(interval_ns*1000/dt))`), records the effective `cadence_ns` beside the
  request, and says "one model every N ns" in the note and the summary. A request finer than `dt` is one frame at
  `dt`; `interval_ns` with `dt <= 0` is refused in the window's own words. The caps still refuse before a frame is
  read. Old `stride` payloads remain readable.
- **View options**: `pbc` (`none|mol|whole|nojump`), `center`, `fit` (`none|trans|rot+trans`) and `group`
  (`protein|solute|fragment:<letter>`) are applied in process with MDAnalysis transforms. `frames.json` records
  `view`, `legacy` and the request; `run-frames.pdb` carries a `REMARK 950 VIEW MODIFICATIONS` sentence (or none when
  the coordinates are raw) and the fit REMARK now names mode and group. `assembled`, `fit: protein|beads` and
  `fragment` are read as the view they described, kept in `args`, named in `legacy`, and the panel still finds and
  plays such attempts, labelled "built with a frame step".

### Deviations from the plan as written

- The writer is `analysis/runs/structures.py::series_pdb`; there is no `series_pdb.py`. Its `assembled` flag became
  `view`.
- Per the user's reduced scope, `res`, `atom` and `cluster` are not offered (they are named as deliberately omitted in
  the form's hint); no `gmx trjconv` subprocess path exists.
- `fit` now states *how* (`trans`/`rot+trans`) and `group` names the selection; the old `protein`/`beads` values were
  the selection, so they map to `rot+trans` + a group rather than being kept as fit values.
- The top control is a disclosure `<div>` rather than `<details>`: `aria-expanded` and `hidden` are written together,
  so a "Frame options" button cannot disagree with the form it names.

### Evidence

- `gmx trjconv` differential (MDAnalysis-built gro/xtc + grompp tpr fixture): max deviation **0.0 Å** for
  `-pbc mol -center` and for `-pbc nojump` (tolerance 0.001 Å), run in the slow tier.
- Tiers after the slice: fast **2,277 passed, 1 xfailed**; browser **258 passed**; slow **19 passed**; 2,555 collected;
  `ruff check packages tests conftest.py` clean; mutation check **10 caught / 1 survived** as documented.
- Legacy coverage: a unit case per interval conversion (auto, exact multiple, non-multiple, finer than the step,
  no `dt`), a mapping case per legacy key, an integration case that a legacy payload queues verbatim and still lists,
  and browser cases for a blank interval, the group show rule, and a legacy attempt found/played/labelled.

### Known limit

- Molecule identity for `pbc: mol/whole` is `(resname, resid)`, the only identity a `.gro` states. Exact for
  detergent/water/ion; a protein chain spans residues, so a chain crossing the boundary unwraps per residue and can
  differ from `gmx trjconv -pbc mol`. Recorded as a `ponytail:` note in `_declare_molecule_bonds`; the differential
  fixture is one residue and does not exercise it.
