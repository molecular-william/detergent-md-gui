# PDC New run: belt form, slab coverage and blocked-slot placement

Status: built (2026-11-25; checks in the execution record below). **Partially superseded the same day:**
the 4 nm vertical spread is the band's **total** height (see
`docs/plans/2026-11-25-pdc-belt-outlier-repair.md`), so its default is now 2 nm of half-height internally,
and the far-head repair was added on top of this slice.

## What the user asked for

1. **Detergent belt and sampling**: each input label's subtext is the unit only (`nm`), the explanation moves into the
   info icon, and the section lays out as one three-column grid holding every control (initialisation style, count,
   belt gap, minimum body-bead distance, axial window, vertical spread, vertical offset).
2. **Vertical spread defaults to 4 nm.**
3. **Slab coverage** counts the hemispheric area of the detergent's free-end tail beads, not the head bead's disc:
   `coverage = 2 * pi * sum(r_edge^2)`, one term per free-end tail bead, so a branched detergent like LMNG (two tail
   ends) sums both. DDM: 2*pi*(0.264)^2 = 0.438 nm^2, LMNG: 2*2*pi*(0.230)^2 = 0.665 nm^2.
4. **Initial box Auto** must write exactly the box the preview draws (its `basis.box_nm`), not the extent route's
   belt-less footprint measurement.
5. **Starting box labels**: `Initial box x` / `Initial box y` / `Initial box z` with subtext `nm`, `Box margin` with
   subtext `nm`; the blank-field/cell explanation and the "each face" explanation move into the info icons. The prose
   paragraph under the box and the per-axis `box_notes` sentences are removed from the panel.
6. **Stage editors** (minimisation, NVT, NPT, production) are all collapsed on mount.
7. **Blocked belt slots**: when every in-band trial fails because the protein blocks the slot, try heights 0.5 nm and
   1.0 nm above and below the band's faces, re-measuring the local surface at each height, before leaving the slot
   empty.

## Decisions recorded

- Coverage arithmetic: user chose 2*pi*r^2 per free-end tail bead, summing both ends of a branched detergent.
- Layout: user chose one three-column grid for all seven controls.
- Fallback: user chose 0.5 and 1.0 nm beyond each band face, both sides.
- The free-end tail bead is read from the mapping's `connections` graph: a tail bead (the C/SC/TC family, not a virtual
  site) with degree one is a free end. A mapping that states no connections cannot answer and is refused with that
  sentence rather than given a guessed end.
- `belt_vertical_half_nm = 4.0` is the adapter default. The retired `belt_vertical_spread` still wins when an old
  payload states it and the nm key is absent: `_numbers` drops the injected 4.0 in exactly that case, so an old run,
  clone or preset keeps the band it was placed with.

## Tasks, in order

1. Backend defaults and help (`pdc.py`, `setting_help.py`): 4 nm default; drop the injected nm default beside a stated
   retired multiple; add `initial_x_nm`, `initial_y_nm`, `belt_offset_nm` help and update the box/belt sentences.
2. Backend coverage (`analysis/runs/encapsulation.py`, the encapsulation endpoint in `web/routes/pdc.py`): edge tail
   beads, hemispheric area, refusal for a mapping with no free tail end, agreement between saved mappings on that
   area, response keys `coverage_area_nm2` / `coverage_radii_nm` / `tail_ends`.
3. Backend placement (`execution/adapters/pdc_placement.py`): out-of-band height trials, honest volume/reach record.
4. Box Auto (`static/js/new-run-pdc.js`, the extent endpoint): Auto derives the preview and writes
   `basis.box_nm`; the extent route's now-unused `auto_initial_*` fields are removed.
5. Form (`templates/fragments/new-run-pdc.html`, `static/pdc.css`, `new-run-pdc.js`): the three-column belt grid,
   unit-only hints, the box labels and their info icons, no box prose/notes, closed stage editors, the coverage row's
   wording.
6. Tests: unit/integration for coverage and placement, browser for the form (grid geometry, defaults, Auto, labels,
   collapsed editors), the extent API's dropped fields, the pairing contract.

## Acceptance criteria

- The belt and sampling section renders seven controls in one three-column grid; every hint is a bare unit.
- A fresh form shows `belt_vertical_half_nm = 4`; its Default button restores 4.
- The coverage estimate reports `2*pi*sum(r_free_tail^2)` and the panel names the tail area it divides by.
- Auto writes exactly the three numbers the preview card prints for its box; a preview that draws nothing leaves the
  fields untouched and says why.
- The starting-box group shows only the four labelled controls (plus Auto/Default); no prose paragraph, no
  `box_notes` line.
- Every stage editor is closed on mount.
- A belt slot the in-band trials cannot place is retried at +-(half_band + 0.5) and +-(half_band + 1.0) nm before it
  is recorded as empty.
- Fast tier, the touched browser files and ruff pass; HANDOFF.md is updated.

## Markup sketch (the integrator owns this)

```html
<div class="new-pdc-belt-grid">
  <label>Initialisation style<select name="pdc_placement_mode">…</select></label>
  <label><span class="new-pdc-count-label">Detergents in the belt</span><span class="setting-control"><input
      name="aggregation_number" …></span></label>
  <label data-belt-only>Belt–protein gap <span class="hint">nm</span> …</label>
  <label data-belt-only>Minimum body-bead distance <span class="hint">nm</span> …</label>
  <label data-belt-only>Local surface axial window <span class="hint">nm</span> …</label>
  <label data-belt-only>Vertical spread <span class="hint">nm</span> … </label>
  <label data-belt-only>Belt vertical offset <span class="hint">nm</span> …</label>
</div>
```

`data-belt-only` labels hide in self-assembly and for an empty micelle (the estimate card keeps its own
`#new-belt-block` wrapper).

## Execution record (2026-11-25)

- Form: the three-column belt grid, unit-only hints, the box labels/info icons, the removed prose and note line,
  and the collapsed stage editors are in `new-run-pdc.html` / `pdc.css` / `new-run-pdc.js`, with browser coverage in
  `test_pdc_new_run_browser.py`, `test_pdc_pairing_browser.py` and `test_pdc_preview_browser.py` (the last now asserts
  the note line is gone).
- Defaults/help: `pdc.DEFAULTS['belt_vertical_half_nm'] = 4.0`, the retired-multiple precedence in `_numbers`, the new
  `initial_x_nm`/`initial_y_nm`/`belt_offset_nm` help, and the matching default in `feature._box_warnings`,
  `preview_choices` and `pdc_preview.preview`. `test_pdc_adapter.py` pins the default and the old-multiple rule.
- Coverage: `encapsulation.edge_tail_beads`/`coverage_area_nm2` and the route's `coverage_area_nm2` /
  `coverage_radii_nm` / `tail_ends`; the route also sizes the `mapping` the form selected, so a molecule whose saved
  drafts disagree (LMNG: 0.665 vs 0.876 nm^2) is sized from the chosen model and unnamed requests state the
  disagreement. Unit/integration/browser tests updated.
- Auto: writes the preview's `basis.box_nm`; the extent route's `auto_initial_*` fields are removed with their tests
  (`test_pdc_extent_api.py`), and the browser case stubs the preview route to prove the numbers come from it.
- Placement: `BELT_TRIAL_BEYOND_NM` out-of-band trials in `_cylinder_sites`, with `placed_axial_max_nm` and the
  volume that uses it; unit tests in `test_pdc_placement.py`/`test_pdc_build_band.py`.
- Checks: fast tier 3,208 passed / 1 xfailed; full browser tier 430 passed (`-n 16 --dist worksteal`); pdc fast area
  869 / 1 xfailed; ruff clean. Dashboard restarted with no active jobs; live 2ydo estimates: DDM 0.4379 nm^2
  (needed 83.5 of 192), LMNG 0.6648 nm^2 with two ends (needed 55.0).
