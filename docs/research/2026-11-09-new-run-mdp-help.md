# New run help text and the MDP options it explains

Date: 2026-11-09. Companion to `docs/research/2026-11-09-new-run-settings-specs.md`; records where the New run
form's help text comes from and what the engine form now offers.

## The one map

`packages/core/src/dashboard/execution/settings_help.py:HELP` is the only copy of the text, keyed by the setting name
the form posts. `GET /api/defaults` returns it as `help` (and its attributions as `help_sources`), for every run type,
and `new-run.js:attachHelpIcons` renders one info button per entry. `dashboard.html` carries no help sentence: a
button with no entry in the map is simply not rendered, so a control cannot display a claim the server does not make.

- MDP option text: quoted from the GROMACS manual for `.mdp` options, 2026-rc edition --
  https://manual.gromacs.org/2026-rc/user-guide/mdp-options.html -- the edition this build (2026.3) documents.
  The manual's option names use dashes (`verlet-buffer-tolerance`); the map is keyed by the setting's underscore
  spelling. Two settings are spelled with their older GROMACS aliases by the reviewed profile (`nstxtcout`,
  `xtc_precision`); their text names the manual's current spelling (`nstxout-compressed`, `compressed-x-precision`).
- Execution flag text: quoted from `gmx mdrun -h` on the installed GROMACS 2026.3 MPI build, as
  `docs/research/2026-11-09-new-run-settings-specs.md` recorded it. `-ntmpi` is quoted only to say it is not offered:
  this build has no thread-MPI.
- Seeds and the box shape have no GROMACS entry, so their sentences are project text and say so (`PROJECT_HELP`).

## What the engine AA–CG form offers

- Sampling (durations, trajectory interval), Ensemble and box (temperature, pressure, box edge, **box shape**), and
  Seeds (`aa_seed`, **`cg_seed`**) stay visible. `box_shape` and `cg_seed` were advertised in
  `aa.CHOICE_SPECS`/`cg.SETTING_SPECS` with no control before this change; both are now rendered.
- **Other run options** is a collapsed `<details>` in the pdc panel's grouping: CG production output cadence,
  neighbour search and cutoffs, thermostat and barostat couplings, and execution. The MDP groups are hidden for
  `aa_only` and `cg_composition`: those run types write no engine CG MDP.
- The CG production overrides are `cg.PRODUCTION_OVERRIDES`, written into `cg-production-v1` through
  `Profile.variable`. The profile keeps its reviewed value as the default, so an untouched run renders the reviewed
  file byte for byte; `rlist` is appended only when named (the reviewed file deliberately omits it).
  `nstxtcout` has no default: the visible `output_interval_ps` owns the stride unless a run pins a step count.
- The execution additions are `mdrun_pmefft`, `mdrun_update` and `mdrun_tunepme`, all `'auto'` by default and
  emitting no flag; `gmx mdrun -h` says `-[no]tunepme` defaults to yes, so `on` writes `-tunepme` and `off`
  `-notunepme`. They are emitted by `aa.mdrun_command_flags`, the one builder both run halves read.

Not copied from pdc: salt, box margin, initial z, micelle contact, removal threshold, placement mode and seed shape.
They are self-assembly/placement science for a protein–detergent system, not one molecule in water.
