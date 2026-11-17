# Plan: equilibration statistics report the final half

Status: **built** (2026-11-17). The equilibration panels and the overview's stage row state a single `mean` per
term, taken over the whole leg. For an equilibration leg that number mixes the transient with the plateau; what a
reader wants to compare against the target is the value the leg settled at. So the displayed statistic becomes the
mean of the **final 50 %** of the leg's samples, and the record keeps both numbers.

## Work

- `analysis/runs/equilibration_traces.py`: each term records `second_half_mean` beside `mean` (both already come from
  `series_summary`; the record is the only thing that dropped it). No other field changes.
- `web/static/js/runs-equilibration.js`: the per-term caption shows the final-half mean, labelled as such, and falls
  back to `mean` when reading a record published before this field existed.
- `analysis/runs/trajectory_overview.py`: the stage-trace entries already carry `second_half_mean` (the summary is
  spread whole); the figure title states the final-half mean instead of `mean`, with the same fallback.
- No change to any `series` summary in the record itself (RMSD, Rg, aggregate counts are not equilibration metrics),
  and no change to the `mean` value that older consumers and comparisons read.

## Verification

- Unit: a ramping series whose final half differs from its mean shows the final-half value in the record and the
  difference is what the panel would draw; the existing mean assertion still passes.
- Browser: the equilibration panel's caption reads the final-half number (route stub with a record carrying both), and
  still renders when the stub carries only `mean`.
- `ruff` and the fast tier; the gate commits.

## Built

`equilibration_traces._trace` records `second_half_mean` beside the unchanged `mean`; the Run row's equilibration
panel shows `final-half mean <value>` (falling back to a labelled `mean` for records published before the field), and
the trajectory overview's stage-trace titles state the same final-half value. Tests: a ramping leg whose final-half
mean (302.5) differs from its mean (301.5), the overview's exact stage titles, and the browser panel showing both the
new value and the legacy fallback.
