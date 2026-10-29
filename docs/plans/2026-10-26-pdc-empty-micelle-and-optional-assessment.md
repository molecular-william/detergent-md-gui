# PDC New run: empty micelle, optional detergent removal, and preview view switches

Status: implemented (2026-10-26). The empty-micelle preview/controls, `remove_out_of_micelle`, the one-leg
duration rule, gated skips, back-map fallback, and the dynamic SVG are in the tree; fast and browser tiers are green.
The plan file name still says `optional-assessment`; the implemented choice is optional **removal**.

## Goal

The protein-detergent New run panel must support two more run shapes without pretending they are the protein
complex:

1. **Empty micelle**: no protein, so protein preparation has nothing to do and must be visibly skipped; the preview's
   **Bonds** and **Ribbon** view switches have no protein to act on and are disabled.
2. **Optional removal**: one explicit choice, **Remove out-of-micelle detergents**. Ticked, the run uses the regular
   CG assessment and detergent-removal-with-checkpoint pipeline. Unticked, that pipeline is absent: no micelle
   assessment, no removal/rebuild, no final assessment, and no checkpoint continuation. A single plain CG MD leg runs
   after NPT for the total requested time.

## What already works

- The empty micelle is already in the adapter and the panel: the protein select leads with
  `No protein · empty micelle`; `pdc.normalize_settings` sets `prepare_protein = false` when the payload has no
  protein; `pdc_prepare.py` writes `skip.json` with its reason and exits 4. The adapter also refuses an explicit
  `prepare_protein: true` for a protein-free build.
- `new-run.js` already omits `prepare_protein` and `protein_chains` from the payload when no protein is selected.
- The API already derives an empty micelle without coarse-graining (`pdc_preview`/`pdc_placement`); a direct
  `GET /api/pdc/preview/placement?template=...&aggregation_number=120...` with no `prepare_protein` returns
  `valid: true`, 1,320 beads, sphere radius 3.0 nm, box 9.93 × 9.95 × 9.95 nm. The panel currently cannot reach that
  result: `preparing()` is hard-coded `true`, so it sends `prepare_protein=true` and the preview refuses with
  "protein preparation (PDB2PQR) needs a structure". The workflow strip already says step 1 is "skipped if absent".
- The current chain requires `3_assessment` for removal: it writes `removed.json`/`kept.gro`; `CG extension MD` reads
  them. If removal is off, there is no checkpoint pipeline: the extension stage has no role, and the first CG MD leg
  is the only production leg. Its final structure must be the one back-map reads, instead of
  `4_extension/prod/run.gro`.

## Findings that need work

- `new-run.js` hard-codes `preparing = () => true`. That is harmless to the server payload while a protein exists,
  but the panel never states "skipped because empty micelle" and the stage strip still presents preparation as an
  active step.
- The **Bonds** and **Ribbon** checkboxes (`dashboard.html:258-266`) are always enabled. They are preview-only view
  switches, but with no protein there is no protein representation and no all-atom structure; Ribbon may still be
  checked and `loadPreview` may try to load a null structure.
- There is no optional-assessment setting. `pdc.DEFAULTS`, `pdc.CHOICE_SPECS`, `validate_payload`,
  `normalize_settings` and `stage_defaults` know nothing about it, and `STAGES` is static. `pdc_assess.py` assumes a
  structure exists; `pdc_extension.py` assumes `removed.json` exists.
- The New run panel has no place to state which stages a gate removes; the workflow diagram is static and its
  caption says only "a leg the run asks none of records skipped".

## Decision required — removal gate semantics

The checkbox is **Remove out-of-micelle detergents**, not "run the assessment". The plan adopts this reading:

- **Ticked (default):** `CG assessment MD` → `Micelle assessment` (cluster verdict + `removed.json`) →
  `CG extension MD` continues/rebuilds from that checkpoint → `Final assessment` → back-map.
- **Unticked:** no `Micelle assessment`, no `removed.json`/`kept.gro`, no removal or rebuild, no `CG extension MD`,
  no `Final assessment`. **One plain CG MD leg** runs after NPT for the total requested time
  (`pdc_assessment_ns + pdc_extension_ns`; the form's two durations are folded into that leg). Back-map reads the
  production leg's final structure instead of `4_extension/prod/run.gro`.

This is a deliberate one-leg reading of "the CG MD just runs for the specified time". If the second duration should
be ignored instead of added (e.g. run only `pdc_extension_ns`), that is a one-line change in the duration rule, not a
different pipeline.

## Proposed behaviour

### Empty micelle

- `preparing()` becomes `() => Boolean(field('protein').value)`.
- When no protein:
  - the workflow's **1 · Prepare** node and the review's preparation row say `skipped · empty micelle`;
  - the payload omits `prepare_protein` and `protein_chains` (already true);
  - the server records the usual `skipped` stage with its reason, or the stage is omitted from the plan if the
    adapter can express it; prefer `skipped` because the run contract already has that outcome and the run table
    draws it.
- Bonds and Ribbon:
  - add one `syncPreviewControls()` called on load and on protein change;
  - with no protein, disable both inputs, uncheck Ribbon, and set a `title`/hint: `disabled · an empty micelle has no
    protein`; `loadPreview` must not request a ribbon when the flag is absent;
  - with a protein, restore both to their previous/default state (Bonds off, Ribbon on).
- Preview remains available for the empty micelle: detergent beads only, no ribbon. `preparing()` must return
  `false` so `prepare_protein` is not sent; the actual API preview (without that flag) already succeeds.
- Placement for an empty micelle: `pack_micelle` with no protein points takes the 120 golden-angle directions from
  `golden_angle_directions(120, seed)` and places head sites at `3.0 * direction` nm; directions are radial. This is
  the `radius_nm=3.0` floor (`radius_source=floor`), not a measured protein shell. The box is measured around those
  points plus `box_margin_nm`. With a mapping the preview stamps the 11 DDM beads per site; without one it records a
  single centre per molecule. `DEFAULT_RADIUS_NM` is the number to expose if the sphere itself is to be resized.

### Optional removal

- Add one boolean setting, proposed `remove_out_of_micelle`, default `true`, in:
  - `pdc.DEFAULTS`, `CHOICE_SPECS` (`Remove out-of-micelle detergents`, `(True, False)`),
  - `validate_payload`/`normalize_settings` (strict bool),
  - `pdc-settings.json` and the manifest settings.
- New run UI: a checkbox with the exact label **Remove out-of-micelle detergents** and this dependency stated:
  - On: after `CG assessment MD`, the micelle is judged; detergents outside it are removed and the extension
    continues/rebuilds from the checkpoint.
  - Off: no micelle assessment, no removal/rebuild, no final assessment. The assessment leg still runs as CG MD, the
    extension continues its checkpoint, and back-map runs from the extension's final structure. Both durations still
    apply.
- Stage behaviour:
  - `3_assessment`: when off, skip with `skip.json` ("detergent removal was not requested"); do not write
    `removed.json` or `kept.gro`.
  - `CG extension MD`: when off, skip with the reason; it has no checkpoint to continue. Do not run the extension
    script at all.
  - `5_assessment`: when off, skip with the reason.
  - `CG assessment MD`: when off, run as the only plain CG MD leg, for `pdc_assessment_ns + pdc_extension_ns`. Keep
    its stage name (the directory and scripts are historic), but the panel/review calls it the CG production leg.
  - Back-map: when off, read `2_assessment/prod/run.gro` instead of `4_extension/prod/run.gro`; the stage
    declaration must carry both candidate inputs, and the script chooses by the setting.
- The run view has **one** CG production series instead of assessment + extension; the run table must not imply a
  removal decision or an extension was made.
- Empty micelle: the same gate applies. With it on, the criterion can still remove detergents outside the largest
  cluster; with it off, the empty micelle simply runs the two CG MD legs.

### Dynamic SVG workflow diagram

The current diagram is a static SVG in `dashboard.html` (`new-pdc-workflow-svg`) with fixed nodes 1-10. It is already
wrong for an empty micelle and will be wrong for every setting this plan adds. Make it a render of the same state the
review uses, not a second copy of the pipeline.

- Replace the static `<g class="new-pdc-flow">` with a container the panel fills from `renderWorkflowDiagram()`; keep
  `<defs>`/the arrow marker and the existing node CSS. The render reads:
  - `protein` (empty vs selected);
  - `pdc_placement_mode` and `aggregation_number`;
  - `remove_out_of_micelle`;
  - `backmap`;
  - `pdc_assessment_ns` / `pdc_extension_ns`.
- Render the **active path only**, not ten nodes with dead arrows:
  - no protein: omit Prepare/Coarse-grain; start `Build the micelle` (golden-angle sphere, count) → `Equilibrate`
    (minimise · NVT · NPT) → production;
  - protein: `Prepare` (PDB2PQR, or `skipped` when preparation is off/unavailable) → `Coarse-grain` (martinize2) →
    `Place the belt` (count/style) → `Equilibrate`;
  - removal on: `Sample CG assessment MD (assessment ns)` → `Judge micelle` → `Extend (extension ns)` →
    `Final assessment` → `Back-map` (if `backmap`);
  - removal off: one `CG MD (assessment + extension ns)` → `Back-map` (if `backmap`); no Judge/Extend/Final nodes.
  - backmap off: end at `Result` with `CG system + records`, not an atomistic result.
- Add a small caption under the SVG listing stages that are skipped by the current settings, with their reason
  (`empty micelle`, `removal not requested`, `back-map off`). The diagram itself shows what will run.
- Update the SVG's `<title>`, `<desc>`/`aria-label` and each node's `data-stage` with every render; browser tests can
  assert the active sequence without depending on coordinates.
- Keep the layout readable at the panel's width: the active path is at most six nodes; reflow rather than shrinking
  text. The existing CSS classes (`new-pdc-flow-node`, `new-pdc-backmap-node`, etc.) stay the visual vocabulary; add
  only a `.is-skipped`/`.is-production` class if a label needs it.
- The diagram must not become a second stage contract: derive node names from the same helper/state as the review and
  payload, and let `pdc.STAGES` stay the execution source. If a stage is renamed, the diagram follows the panel's
  copy, not a hard-coded index.

## Work breakdown

1. **Adapter contract**
   - `pdc.py`: `remove_out_of_micelle` setting, choice spec, default, validation, `pdc-settings.json`; a small
     `skip_reason(stage, settings)` helper for the two assessment stages.
   - `pdc_assess.py` / `pdc_assessment.sh`: skip when the setting is false.
   - `pdc_extension.sh` / `pdc_extension.py`: skip when false; no missing-removal fallback is needed.
   - `pdc_assess.py` / final assessment script: skip when false.
   - `pdc_backmap.sh` (and the `Back-mapping` stage inputs): select `2_assessment/prod/run.gro` when removal is off,
     `4_extension/prod/run.gro` when on.
   - `CG assessment MD` duration: when off, `assessment_ns + extension_ns`; when on, `assessment_ns` as today.
2. **New run panel**
   - `new-run.js`: checkbox label/help, payload (`remove_out_of_micelle`), summary/review/workflow copies, the
     disabled Bonds/Ribbon and empty-micelle preparation fixes, and `renderWorkflowDiagram()` called on every input
     that changes the chain (protein, placement/count, removal, back-map, both durations).
   - `dashboard.html`: the checkbox near the two durations, with the dependency text.
3. **Tests**
   - Empty micelle: payload has no `prepare_protein`; preview derives; Bonds/Ribbon disabled; no ribbon request.
   - Removal on: existing chain unchanged; `removed.json` and rebuild path still exercised.
   - Removal off: `3_assessment`, `CG extension MD` and `5_assessment` skipped; one `CG assessment MD` leg runs for
     the sum of the two durations; back-map reads `2_assessment/prod/run.gro`; run is `completed` with skipped
     stages and one production series.
   - Browser test for the checkbox label/state and the empty-micelle disabled controls.
   - Diagram tests: protein/removal-on shows Prepare→Coarse-grain→Place→Equilibrate→Sample→Judge→Extend→Final→Back-map;
     empty micelle shows Build micelle with no Prepare/Coarse-grain; removal-off shows one Sample→Back-map and no
     Judge/Extend/Final; back-map-off ends at Result; duration labels follow the fields; `<title>`/`aria-label` update.
4. **Docs**
   - `PROJECT_GUIDE.md` run contract/stage list; `HANDOFF.md` after the build; this plan.

## Risks and open items

- **Duration rule** is the main open item: this plan adds the two requested durations for the single leg. If the
  second field should be ignored, change the sum to `pdc_extension_ns` alone.
- **Back-map input** changes with removal off; the stage declaration and script both need the conditional path, or
  the run would read a missing `4_extension` file.
- The run view and automatic analyses must accept one production series instead of two when removal is off.
- The SVG is a view of the panel's state, not an executor. If it disagrees with the review, the review and the stage
  contract win; keep the two rendered from the same helper rather than patching labels independently.
- Empty micelle assessment: `pdc_assessment.assess_micelle` accepts no protein; when removal is on, verify a
  micelle-only run still reports cluster size rather than refusing. When removal is off, this stage is skipped.
- The existing `prepare_protein` default/refusal and stage skip are already correct; do not duplicate them in the
  panel with a second readiness gate.
- The 1 us extension bug (rebuilt path kept assessment `nsteps`) is fixed separately; this plan does not change it.
- The plan file name still says `optional-assessment`; the behaviour is now optional **removal**. Rename the file
  when the plan is accepted if the path is not already referenced elsewhere.
