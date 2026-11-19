# Plan · AA production output cadence

Status: **implemented 2026-11-19**. Draft:
`docs/design/drafts/2026-11-18-aa-production-output-cadence.html` (and the rendered `.png`).
Checks: fast tier **3128 passed / 1 xfailed**; browser tier **415 passed at `-n 8`**; ruff clean over every
changed Python path.

## What the user asked for (2026-11-19)

Explicit production output-cadence controls for AA runs: log interval, energy interval, trajectory
interval, trajectory precision, "and so on".

## Decisions taken by the user (2026-11-19)

1. **NPT production only.** NVT and NPT equilibration keep the derived cadence, as the CG
   equilibration leg does.
2. **The five named fields**: `nstlog`, `nstenergy`, `nstxout-compressed`, `compressed-x-precision`,
   `nstcomm`.
3. **A blank box keeps today's derivation**, so an untouched run's MDPs stay byte-identical.
4. **An explicit trajectory step count wins** over the run-wide `output_interval_ps` stride for that
   stage.

## Behaviour

Today `aa.mdp_values` derives, for every AA dynamics leg:

```
stride  = max(1, round(output_interval_ps / dt_ps))
nstxout-compressed = stride
nstenergy = nstlog = min(stride, 500)
```

The new settings are `aa_production_nstlog`, `aa_production_nstenergy`,
`aa_production_nstxtcout`, `aa_production_xtc_precision`, `aa_production_nstcomm` (steps, integers;
precision is the compressed-trajectory precision). They apply only to `aa-production-v1`:

| setting | MDP option | blank |
|---|---|---|
| `aa_production_nstlog` | `nstlog` | `min(stride, 500)` |
| `aa_production_nstenergy` | `nstenergy` | `min(stride, 500)` |
| `aa_production_nstxtcout` | `nstxout-compressed` | `stride` from `output_interval_ps` |
| `aa_production_xtc_precision` | `xtc-precision` | line absent (GROMACS default) |
| `aa_production_nstcomm` | `nstcomm` | line absent (GROMACS default) |

An explicit value replaces only its own option. The form hint says a blank trajectory box follows the
run-wide ps interval and that an explicit step count overrides it for production only.

## Files

| layer | files |
|---|---|
| adapter | `packages/core/src/dashboard/execution/adapters/aa.py` (`SETTING_SPECS`, integrals, `mdp_values`) |
| profile | `packages/core/src/dashboard/execution/mdp/profiles.py` (`xtc-precision`, `nstcomm` as variables) |
| form | `packages/core/src/dashboard/web/templates/dashboard.html` (five controls in the AA production editor) |
| JS | `packages/core/src/dashboard/web/static/js/new-run.js` (`AA_ONLY_FIELDS`) |
| help | `packages/core/src/dashboard/execution/settings_help.py` (aliases to the existing sentences) |
| tests | `packages/core/tests/unit/test_mdp_writer.py`, `packages/core/tests/browser/test_aa_new_run_browser.py` |

Defaults are not prefilled: the five settings are absent from `DEFAULTS`, so `/api/defaults` sends
none and the boxes start blank; their Default buttons clear them (`data-clear-default`).

## Checks

```
.venv/bin/python -m pytest packages/core/tests/unit/test_mdp_writer.py -q
.venv/bin/python -m pytest -m 'not browser and not slow' -q -n 8
.venv/bin/python -m pytest -m browser -q -n 8
.venv/bin/ruff check packages tests conftest.py
scripts/gate_commit.sh <message> <paths...>
```
