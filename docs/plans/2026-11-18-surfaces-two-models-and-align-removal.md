# Plan · Surfaces: two models (AA vs Simulated CG), and the Align-trajectory tickbox gone

Status: **implemented 2026-11-18**. Draft:
`docs/design/drafts/2026-11-18-surfaces-two-models-and-align-removal.html` (and the rendered `.png`).
Checks: fast tier **3127 passed / 1 xfailed**; browser tier **415 passed at `-n 8`**; ruff clean over every
changed Python path.

## What the user asked for (2026-11-18)

1. The run-view **surfaces** calculation must drop the **Mapped raw** and **Mapped ring-scaled**
   variants; it should compare **CG and AA** only.
2. The run-view trajectory form's **Align trajectory** tickbox is redundant and must go.

## Decisions

### Surfaces

- `analysis/runs/surfaces.py:generate` builds **two** variants: `AA` (the atomistic reference) and
  `Simulated CG` (this run's coarse-grained trajectory). No mapped trajectory is written, no mapped
  `gmx sasa` leg is run, and the mapping's ring scale is not read.
- One mapped value survives, because the comparison itself needs it: the **first AA frame mapped onto
  the beads** (`sugars.coordinates(model, first_aa_frame)`) is the target the simulated CG frame is
  rigid-body fitted to (`align`, over beads that own atoms). It is one frame of positions, not a
  surface calculation and not a written trajectory; without it the AA and CG envelopes would not be
  in one frame of reference. The module comment states this.
- `metadata['statistics']`, `metadata['commands']` and the progress lines name only `AA` and
  `Simulated CG`; the per-variant directories are `aa/` and `simulated-cg/`. The AA/CG pair JSON and
  its two panels are unchanged.
- Analysis versioning: published attempts are immutable, so an older attempt keeps its four-variant
  statistics on disk. The run-view table now renders only `AA` and `Simulated CG`, so an old attempt
  reads consistently with a new one (the extra rows are simply not shown).

### Run view text

- The Shape section's "what the models are" block names **two** models, and its table caption says the
  AA row is the reference and the Simulated CG row is this run's own data.
- The surfaces-absent reason drops "the mapped" from its sentence: the analysis reads the atomistic
  and simulated trajectories.

### Align trajectory

- The `Align trajectory` checkbox is removed from the trajectory form markup, state, event handler and
  help sentence. The **Fit** and **Group** picks are the only fit controls and are never disabled; a
  recorded series restores them exactly as recorded. The default view is unchanged (`fit = none`,
  no group).

## Files

| layer | files |
|---|---|
| analysis | `packages/validation/src/detergent_validation/analysis/runs/surfaces.py` |
| run view | `static/js/run-view-mapping.js`, `web/routes/analyses.py` |
| trajectory | `packages/core/src/dashboard/web/static/js/run-view-trajectory.js` |
| tests | `packages/validation/tests/unit/test_surfaces.py`, `packages/validation/tests/browser/test_run_view_mapping_analysis_browser.py`, `packages/core/tests/browser/test_run_view_trajectory_browser.py` |

## Checks

```
.venv/bin/python -m pytest packages/validation/tests/unit/test_surfaces.py -q
.venv/bin/python -m pytest -m 'not browser and not slow' -q -n 8
.venv/bin/python -m pytest -m browser -q -n 8
.venv/bin/ruff check packages tests conftest.py
scripts/gate_commit.sh <message> <paths...>
```
