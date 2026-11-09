# New run settings: spec, flag and help-text impact

Date: 2026-11-09. Companion to `docs/design/drafts/2026-11-09-new-run-compact-settings.html` and
`docs/plans/2026-11-09-next-round.md` item 7 / decision 7. No production code.

## The gate

`packages/core/src/dashboard/web/routes/runs.py:207`:

```python
specs = set(adapter.settings_specs()) | set(adapter.choice_specs())
...
settings={k: data.get(k) for k in specs if data.get(k) not in (None, '')}
```

A form field whose name is not in the adapter's `SETTING_SPECS` or `CHOICE_SPECS` is dropped without an error and the
run uses the default. So a new control and its spec entry are **one edit**; a control without a spec is worse than no
control, because the panel shows a value the run never receives. This is the AGENTS.md invariant.

The specs are not currently sent to the client: `/api/defaults` returns `{values, sources, profile, force_fields}`.
The form's `min`/`max`/options are hard-coded in `dashboard.html` and `new-run.js`. Help text would therefore need a
new field in that answer, or a second route; otherwise the template restates the specs and drifts.

## Inventory: advertised versus rendered

Engine AA–CG adapters: `packages/core/src/dashboard/execution/adapters/aa.py` and `.../cg.py`. CG composes
`cg.SETTING_SPECS + aa.SETTING_SPECS + aa.CHOICE_SPECS`; the AA bound decides where both bound a key
(`cg.normalize_settings`). `aa.DEFAULTS` / `cg.stage_defaults` supply values.

| key | spec table | rendered in `dashboard.html` | notes |
| --- | --- | --- | --- |
| `aa_nvt_ps` | aa `SETTING_SPECS` | yes | duration |
| `aa_npt_ps` | aa | yes | duration |
| `aa_production_ps` | aa + cg | yes | duration |
| `aa_equil_ps` | cg | **no** | derived (`NVT + NPT`); intentionally not an input |
| `cg_equil_ps` | cg | yes | |
| `cg_production_ps` | cg | yes | |
| `cg_seed` | cg | **no** | **advertised but unrendered**; `new-run.js` `CG_FIELDS` already clones it |
| `temperature_k` | aa + cg | yes | |
| `pressure_bar` | aa | yes | accepted for aa_cg through `aa.SETTING_SPECS` |
| `output_interval_ps` | aa + cg | yes | |
| `box_nm` | aa | yes | |
| `aa_seed` | aa | yes | |
| `sasa_probe_nm` | cg | yes | CG-only (`cg-setting`) |
| `mdrun_gpu` | aa | yes | omitted on a host with no device (`devices.published_settings`) |
| `mdrun_ntomp` | aa | yes | |
| `mdrun_ranks` | aa | yes | MPI build: ranks go to `mpirun -np`, never `-ntmpi` |
| `mdrun_cpt` | aa | yes | no default by design; no Default button |
| `mdrun_nb` | aa `CHOICE_SPECS` | yes | `auto/cpu/gpu`; `gpu` dropped on a host with no device |
| `mdrun_pme` | aa `CHOICE_SPECS` | yes | as above |
| `box_shape` | aa `CHOICE_SPECS` | **no** | advertised but unrendered (cube default) |
| `force_field` | aa `CHOICE_SPECS` | yes | registry-backed |

Two existing gaps surfaced: **`cg_seed`** and **`box_shape`** are advertised but have no control. `cg_seed` matters
because it is stamped into the CG MDP (`gen-seed`, `ld-seed`) and is already carried by a clone; a fresh run cannot
choose it. `box_shape` is a deliberate omission review candidate (the dodecahedron was measured slower; the comment in
`aa.py` says so), so a compact form may keep it hidden or expose it under "Other run options" with that sentence.

## What "compact like the pdc form" means

Presentation only: `new-run-pdc.html` uses

```html
<details id="new-advanced"><summary>Other run options</summary>
  <div class="new-pdc-options">
    <section class="new-pdc-option-group"><h4 class="new-pdc-option-title">…</h4>
      <div class="new-pdc-option-rows">…labels…</div></section>
```

with a final `details.new-pdc-options-notes` explaining the numbers. The engine form has `.settings-grid` and no
groups. The draft proposes: always-visible **Sampling** (durations + output interval); **Ensemble and box**;
**Seeds**; and a `<details>` **Other run options** for execution. Reordering is template + `new-run.js` only; no spec.

## Info icons

### The pattern

A real `<button type="button" class="info-btn" aria-label="About …" aria-describedby="tip-…">` next to the label,
with a sibling `<span role="tooltip" id="tip-…">`. Show on `:hover` / `:focus-within`, toggle on click for touch,
Escape closes, and keep the button focus-visible. The help text must not be the only place a value is stated.

### The text source

One server-side map, not a template copy: the installed GROMACS version and its help are environment facts. Options:

1. `aa.MDRUN_HELP = {key: text}` and `cg.MDRUN_HELP`, merged into the `/api/defaults` answer
   (`web/routes/molecules.py:defaults_api`). No normalization impact; the map is read by the template/JS.
2. A reviewed JSON resource, if the text is considered documentation rather than adapter data.

Either way the map is keyed by setting name, and a test asserts the same map the form renders (no third copy).

### Exact text on this host

`/usr/local/gromacs/2026.3/bin/gmx --version`: GROMACS 2026.3, precision mixed, **MPI library MPI** (Open MPI 4.1.2),
OpenMP enabled (max 128 threads), AVX_512. `gmx mdrun -h` says, verbatim:

- `-ntomp <int> (0)` — “Number of OpenMP threads per MPI rank to start (0 is guess)”
- `-ntmpi <int> (0)` — “Number of thread-MPI ranks to start (0 is guess)” — **quoted, never offered**: thread-MPI is
  not this build; mdrun aborts on `-ntmpi` (AGENTS.md standing decision).
- `-gpu_id <string>` — “List of unique GPU device IDs available to use”
- `-nb <enum> (auto)` — “Calculate non-bonded interactions on: auto, cpu, gpu”
- `-pme <enum> (auto)` — “Perform PME calculations on: auto, cpu, gpu”
- `-pmefft <enum> (auto)` — “Perform PME FFT calculations on: auto, cpu, gpu”
- `-update <enum> (auto)` — “Perform update and constraints on: auto, cpu, gpu”
- `-cpt <real> (15)` — “Checkpoint interval (minutes)”
- `-nsteps <int> (-2)` — “Run this number of steps (-1 means infinite, -2 means use mdp option, smaller is invalid)”
- `-npme <int> (-1)` — “Number of separate ranks to be used for PME, -1 is guess”

Durations (`aa_nvt_ps` …), temperature, pressure, box edge, seeds and the SASA probe are MDP values; `gmx mdrun -h`
has no text for them. If they carry an icon, the sentence is project-authored and must say so.

## Proposed additions and their exact impact

Only the first needs no server change. Each of the rest adds a spec **and** a flag emission, so each changes command
construction and needs a test that the old command is byte-identical for `auto`/absent.

| setting | spec | emission today | change |
| --- | --- | --- | --- |
| `cg_seed` | already in `cg.SETTING_SPECS` | MDP `gen-seed`/`ld-seed` from the value | add the input; no other change |
| `mdrun_pmefft` | add `aa.CHOICE_SPECS['mdrun_pmefft'] = ('PME FFT scheme', ('auto','cpu','gpu'))` | hard-coded `-pmefft gpu` in both `mdrun_launch`'s scheme and `mdrun_command_flags`' GPU bracket | remove the hard-coded flag and emit it from the setting; `auto` keeps the bracket unchanged |
| `mdrun_update` | add `aa.CHOICE_SPECS['mdrun_update'] = ('Update and constraints', ('auto','cpu','gpu'))` | not emitted | emit `-update <choice>` only when not `auto` |
| `mdrun_tunepme` | add a boolean choice (`(True, False)`, like pdc's `backmap`) | not emitted | emit `-[no]tunepme` only when named; needs a reviewed default |
| `box_shape` | already in `aa.CHOICE_SPECS` | not rendered | optional: render in Other run options with the "dodecahedron measured slower" sentence |

Do **not** add: `-ntmpi` (invalid build), `-npme` (rarely useful for one molecule; no measured need), `-nt` (redundant
with ranks × threads), `-nsteps` (durations own it).

MDP-level values from the pdc form (`nstlog`, `nstenergy`, `nstxtcout`, `xtc_precision`, `nstcomm`, `nstlist`,
`verlet_buffer_tolerance`, `rlist`, `rcoulomb`, `rvdw`, `tau_t`, `tau_p`, `compressibility`) are a separate change: the
engine's MDP writer and `mdp_profiles` must accept them, and `SETTING_SPECS` alone is not enough. Their help cannot be
copied from `gmx mdrun -h`.

## Cross-layer checklist

- `aa.py` / `cg.py`: spec and choice entries; help map; `mdrun_command_flags` emission; `cg.run_settings` keeps the
  new mdrun keys (the run's, not its reference's).
- `packages/core/src/dashboard/web/routes/molecules.py:defaults_api`: include the help map.
- `packages/core/src/dashboard/web/templates/dashboard.html`: grouped markup, one field per spec key actually offered.
- `packages/core/src/dashboard/web/static/js/new-run.js`: help rendering/toggle, clone handling for new keys, no
  duplicated min/max if the server can supply them.
- `packages/core/tests/browser/test_new_run_browser.py`, `test_aa_new_run_browser.py`: the field renders, posts, and
  the tooltip is reachable by keyboard; a committed command test for `auto`/absent flags.
- Docs: the Lead owns `docs/HANDOFF.md`/`docs/PROJECT_GUIDE.md`.

## Open decisions (plan decision 7)

1. Which extra settings are in scope — only `cg_seed`, or the three mdrun flags too?
2. Are MDP-level options (pdc-style cadence/cutoffs/couplings) wanted for the engine form, or is "compact" only about
   grouping and help?
3. Help source: adapter-served map (recommended) or template text?
4. `dashboard.html` is shared markup; the Lead must own or assign the form edit. This research lane does not edit it.
