# PDC preview: draw a refused placement and mark the problems in red

Status: **landed 2026-11-23** (a gate-refused placement is drawn dry, with its `problems` marked in red).
Measurements and checks are in `docs/HANDOFF.md`'s Current state.
Draft: `docs/design/drafts/2026-11-23-pdc-preview-problems.html`.
Companion plan: `docs/plans/2026-11-23-pdc-placement-and-box-controls.md`.

This item depends on that plan's **item 1** (place a detergent near a rejected site), because the red rings are
drawn from the rejected slots' own coordinates, which exist nowhere today. It does not otherwise touch items 2-4.

## Why

A preview the placement's gates refuse is a text-only answer today: `pdc_preview.preview` returns `_refusal(...)`
with `pdb: None`, the card removes every NGL component, and the reader cannot see what the inputs produced or where
the gate fired. The user's decision (2026-11-23): **if the system has issues, the picture is still drawn**, with the
offending beads and the locations that could not be filled marked in red. The run must still refuse exactly as it
does now.

## Decisions (user, 2026-11-23)

1. **Only refusals that have a geometry draw.** Placement-gate refusals only: head clearance, body clearance,
   detergent overlap, a short belt, a crowded shell. Template validation, protein preparation (pdb2pqr),
   coarse-graining (martinize2), model derivation and conformation-library refusals stay text-only -- there is no
   system to draw, and drawing the input in their place would be a picture of a different question.
2. **Marks.** A red ring at each belt slot the placement could not fill; a red bead at each bead inside a gate --
   the detergent bead and the protein bead it comes too close to, or both members of an overlapping pair. The
   reasons stay as text beside the picture; the marks never replace them.
3. **A short belt draws what fits** (N of M) with rings in the slots it could not fill, and the card states the
   count. The full requested set is never drawn at trial sites.
4. **Preview card only.** No run row, no export, no new gate, no change to the valid path's bytes.

## Data contract

`pdc_placement.place_detergents` adds `problems: [...]` to the record it returns, collected where the `issues`
sentences are collected, in the same order, with no second placement and no recomputation:

```
{'kind': 'head-clearance' | 'body-clearance' | 'overlap' | 'empty-slot',
 'detail': str,                      # the matching issue sentence, verbatim
 'molecule': int | None,             # 1-based index into `centers`; None for an empty slot
 'position_nm': [x, y, z],           # the mark's centre, in the placement's own frame
 'normal_nm': [x, y, z] | None,      # a ring's plane normal (the slot's outward direction); None for a bead mark
 'radius_nm': float,                 # the ring radius (the gate distance) or the bead mark's radius
 'protein_beads': [[x, y, z], ...]}  # the protein beads the mark is about, capped
```

- `empty-slot` replaces the bare `rejected` count in `_cylinder_sites`: the rejected slot keeps its own base
  coordinate, heading and height, and its reason. This is the same record item 1 of the companion plan needs.
- `head-clearance`: one entry per detergent whose head is inside `min_clearance_nm`, carrying the site and the
  nearest protein bead.
- `body-clearance`: one entry per site whose drawn body reaches inside `BEAD_CLEARANCE_NM`; `placed_bead_clearance`
  returns the offending (bead, point) pair as well as its minimum so the mark has a position.
- `overlap`: one entry per offending pair member (two marks per pair), each at that member's own centre and carrying
  the partner's centre in `protein_beads`, so both molecules are marked as the user's decision asks. The pair's
  identity comes from `validate_positions`' additive `overlap_pairs`; the four existing keys stay unchanged.
- Empty-slot marks sit at the slot's own base point with the failed gate's distance as `radius_nm` and the slot's
  outward normal; the per-slot reason is in the band's `rejected_slots` and the mark's `detail` is the matching
  `aggregation count` sentence, verbatim. The belt's `belt_offset_nm` is already applied to those positions, so the
  preview must not apply it again. `body-clearance` marks appear only where the drawn-body issue sentence exists
  (the conformation-library path).
- **Determinism.** Same seed -> byte-identical `problems`; coordinates rounded to six decimals; no `nan` (`nan`
  marks are dropped and the issue sentence carries the count instead, as the unplaced-bead path already does).
- **Cap.** `MAX_PROBLEMS = 200` marks in deterministic order (empty slots first, then molecules by index); beyond
  that, `problems_truncated` carries how many were left out and the sentences stay complete. A dense shell can
  otherwise put every protein bead inside a gate and turn one browser answer into thousands of marks.

`pdc_preview.preview` on a refused placement:

- still builds the frame when `placement['centers']` has at least one row: the same `pdc_build.stamp`, the same
  centring, the same box rule (`_box` over the refused placement, so a band still sizes from the belt it drew);
- returns `valid: False` with the placement's `reasons` unchanged, `pdb` set, `basis['problems']` (every position
  translated by `centring.shift_nm`, and a mark whose molecule `_wrap` moved is moved by that same per-molecule
  shift) and `basis['problems_truncated']`;
- **no solvent placement** -- a refused frame is not the run's opening cell, and one Insane call per keystroke is
  cost the reader does not need; `basis.solvent_reason` says the picture is the dry frame;
- the PDB title says `refused placement preview (…)`;
- a refusal with no centres (unplaced protein beads, template/model/library/preparation) keeps today's
  `pdb: None` path unchanged.

## Work

1. `packages/pdc/src/detergent_pdc/execution/adapters/pdc_placement.py` -- collect `problems`; rejected slot
   records in `_cylinder_sites`; offending pair from `validate_positions` and from `placed_bead_clearance`. The
   `issues` sentences stay byte-identical.
2. `packages/pdc/src/detergent_pdc/execution/pdc_preview.py` -- build the refused frame, translate the marks, put
   them in `basis.problems`, skip the solvent.
3. `packages/pdc/src/detergent_pdc/static/js/new-run-pdc.js` -- `renderPreviewFrame` becomes the path for any body
   that carries a `pdb`, valid or not. Draw the marks as one `NGL.Shape` component: red rings built from
   `addCylinder` segments in each mark's own plane (`normal_nm`), red `addSphere` beads for bead marks. Keep a
   `previewProblems` handle on the host, replaced per draw. Show the reasons in a red banner above the picture, a
   legend line (red ring = slot not filled, red bead = a bead inside a gate), and the "N of M placed" sentence.
   `renderPreviewRefusal` stays for answers with no `pdb`. Update the viewer's `aria-label` with the counts. The
   launch buttons are unchanged -- the preview is not a gate, and it says the run would refuse.
4. `packages/pdc/src/detergent_pdc/templates/fragments/new-run-pdc.html` -- the banner and legend hooks. Classes
   only: `test_dom_ids.py` forbids ids a panel names in a selector that the single-molecule page does not render.
5. `packages/pdc/src/detergent_pdc/static/pdc.css` -- the red banner and legend, and the marks' legend row.
6. Docs: `PROJECT_GUIDE.md` *pdc preview* states the `valid: false` + `pdb` contract; HANDOFF after landing.

## Acceptance and checks

- **Placement unit:** a rejected belt slot keeps its coordinate, heading and reason; a too-close head records its
  detergent index and the nearest protein bead; an overlapping pair records both indices; a body-gate hit records
  its site; the same seed rebuilds byte-identical `problems`; no `nan`.
- **Preview unit:** a gate-refused placement answers `valid: false` with a non-empty `pdb`, `reasons` unchanged and
  `problems` present; every problem position lies inside `box_nm` after wrapping; a known mark moved by
  `centring.shift_nm`; a refused template/preparation still answers `pdb: None`.
- **Route:** `200` with `valid: false` + `pdb` for a gate refusal, and the JSON parses in a browser (no `NaN`).
- **Browser:** a stubbed gate-refused answer draws the viewer, the red banner and the mark component
  (`previewProblems`), with the legend and "N of M"; a stubbed refusal with no `pdb` keeps today's text-only path;
  the valid path is unchanged.
- **Valid path:** a valid derive's `pdb` and `basis` stay byte-identical to HEAD (pinned by the existing preview
  tests, plus a recorded before/after body for one fixture).
- **Live:** one derive on the 1AT9 fixture with a count that cannot fit, and one belt protein with a slot that is
  rejected -- preview only, no run, measured over the real route.
- Checks: `packages/pdc/tests` fast area, the pdc browser area, `ruff`, and the full fast tier before the gate.

## Non-goals and ceilings

- No mark in Run view; no PNG/PDB export; no new dependency; no change to refusal semantics or the launch gate.
- A mark is display-only: no run consumes `problems`, and the PDB remains the build's own geometry, not a claim
  that it is buildable. The banner, the state line, the PDB title and the marks' legend each say so.
- The belt rings depend on item 1's slot records. If item 1 is not landed, the preview item can still mark bead
  violations, of course -- but the empty-slot rings wait for it.
