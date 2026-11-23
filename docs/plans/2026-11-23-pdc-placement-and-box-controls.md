# PDC placement fallback, wider membrane boxes, and box controls in Run configuration

Status: hand-off for the next agent (2026-11-23). No code changed for this hand-off.

Companion item (same session, user's decision 2026-11-23): `docs/plans/2026-11-23-pdc-preview-problem-markers.md`
-- a refused placement is still drawn, with its problems marked in red. It reads this plan's item 1 rejected-slot
records, so the order is item 1, then the preview item, then items 2-4.

## 1. Place a detergent near a rejected site

Current behaviour (`packages/pdc/src/detergent_pdc/execution/adapters/pdc_placement.py`,
`_cylinder_sites` + `_belt_trials`): each golden-angle site is tried at its own heading/height; if that base
head is closer than `min_clearance_nm`, the slot is rejected immediately. `_belt_trials` only runs after a base
head clears but fails the site-spacing or body gates. A slot whose trials all fail is left empty.

Requested: when the base coordinate is too close to the protein, sample **adjacent coordinates** until one meets
the distance criteria, instead of rejecting the slot. Keep the draw deterministic in the seed, keep the belt's
angular/height coverage even, and keep the edge gap/body/head gates authoritative. A placement that still has no
legal adjacent coordinate is still allowed to reject the slot, and must record the attempt and rejection so a
reader can see the capacity result rather than a silently smaller belt.

Acceptance:
- the same seed rebuilds byte-identical centres;
- every accepted head/body clears the existing gates;
- a request that cannot fit returns the current capacity/refusal path, not a fabricated list;
- tests measure a site that the old code rejected and the new code moved, plus the no-room case.

## 2. Increase the membrane box in x and y

`pdc_box.membrane_box` currently sets x/y to the protein's footprint plus `2 * box_margin_nm`; it does not include
the belt's cylinder radius or its own body reach (z does include `belt_reach_nm`). Requested: widen the membrane
box's x/y further so the belt and the solvent shell around it are not against the face. Measure the width against
the 1AT9 fixture and record the value before/after. The widening must not silently change the density the placement
was built at: either widen only after the placement (and state that in the report), or rebuild the placement's
volume together with the box; pick one and pin it with a test.

## 3. Box controls in Run configuration

Move the `box_margin_nm` and `initial_z_nm` controls out of the Stage-settings fieldset's **Salt, seed and box**
group and into the **Run configuration** card. Add explicit initial box values for x, y and z there, so the form
states the starting box rather than deriving x/y invisibly from the protein footprint. Wire the new/changed values
through all of:

- `pdc.DEFAULTS`/`SETTING_SPECS` (bounds and labels);
- `preview_choices`, `pdc_preview.preview`, `basis`, and the preview query/JS;
- `pdc_build` and `pdc_box` (the single box rule);
- `dashboard.web.stage_settings.PDC_GROUPS` (the fields must not appear in both cards);
- the New-run template, `NUMBERS`, preview cheap inputs and the default buttons;
- tests: form placement, preview request, build record, and the pairing/layout tests.

Keep the existing stage-settings values for old runs/presets readable; a missing initial x/y means today's derived
value, not zero. State in the field labels whether a value is a dimension or a margin, and keep the Auto control's
behaviour for z or replace it with an explicit Auto-all control (decision for the implementer; document it).
