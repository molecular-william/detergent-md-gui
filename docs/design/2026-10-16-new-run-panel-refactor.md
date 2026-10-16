# The New Run panel, the bonded contract, and Stage 3

**Status: decided, being built.** Written after the measurements below, before the code. The plan is
`docs/superpowers/plans/2026-10-16-new-run-panel-refactor.md`; the companion for the analyses control is
`docs/design/2026-10-16-analyses-control.md`.

## What was measured, from the store rather than from the code

`scripts/…` — the probe is scratch, the numbers are these. Every claim below is a count over the run store and the
runs' own staged files, because a branch's death is a fact about what ran, not about how the code reads.

| branch | evidence | verdict |
| --- | --- | --- |
| `profile = 'draft-smoke'` | 0 of 8 jobs | never used |
| `profile = 'draft-smoke-reference'` | 2 of 8 jobs — both `aa_cg` | the only AA–CG shape ever run |
| `profile = 'standard'` | 6 of 8 jobs — **all `aa_only`** | no AA–CG run has ever used it |
| `bonded_intent = 'fit_only'` / `'reuse_state'` | 0 of 8 jobs | never used |
| `bonded_state_id` carried | 0 of 8 jobs | never used |
| `BOND_STATE.itp` written | 0 of 8 runs | the reuse branch never executed |
| `bonded_fit.json` with a torsion / a torsion_model | 0 of 8 runs | the circular-harmonic pass never fired |

Consequence worth stating plainly, because it corrects an earlier reading of mine: the AA–CG run type under
`profile='standard'` has no mapping-staging block in `execution/adapters/cg.py` (the export, `sugar_mapping.py`,
`prepare_ring_constraints.py` and `refine_bonded.py` copies all sit inside
`if profile in ('draft-smoke','draft-smoke-reference')`, line 210). That is not a defect that broke a run — **no
AA–CG run has ever taken that profile** — it is an option the panel offers for a path that stages nothing. The fix is
to stop offering it, not to build it.

## What changes, and why

The owner's rule, which this record implements: *every AA–CG run produces a parameterized CG molecule; whether it is
validated is a separate question. Fitting is therefore always on for AA–CG runs, and a CG run handed a
pre-parameterized molecule never fits.*

### Decisions

**D1 — The AA–CG panel loses its `bonded_intent` and `bonded_state_id` selects, and the run contract loses both
fields.** Fitting is a property of the run type, not a per-run choice: `aa_cg` always fits, and the run types that
consume a pre-parameterized molecule (composition, `pdc`) never do. Reversal cost: one select plus two coordinator
branches (`coordination/coordinator.py:391-392, 416-421, 496`), which the store shows are unexercised.
*What is lost, named:* the "fit only, stop for review" gate. It is replaced by the fit's own record — a completed run
leaves `3_initial_CG/{final_itp}`, `*_ff_inter.itp` and `bonded_fit.json` on disk, and by the checks in D5. An
AA–CG run will no longer stop itself before simulating.

**D2 — The AA–CG panel loses its `profile` select.** It is a duration preset wearing a pipeline name: its only
non-duration effect is whether a mapping is staged (D2a), and every AA–CG run here has overridden its durations in
Stage settings anyway. The route stamps `'draft-smoke-reference'` for `run_type == 'aa_cg'` and the manifest records
it, so history keeps saying which shape ran. `standard` stays for `aa_only`, which is the only type that ever used
it. Reversal cost: re-add the select and the profile test.
*D2a — the mapping-staging block moves out of the profile test and keys on the run type:* the export, the three
script copies and the `refine_bonded.py` copy become unconditional for an AA–CG run. Reversal cost: restore the
`if profile in (...)` wrapper.

**D3 — Stage 3 is renamed `CG parameterization`.** It is not one tool's stage any more: it locks the rings, fits the
bonded terms, refines the declared torsions and records what each step did. The panel's label table maps **both
spellings** (`runs.js`), the recorded name stays in the step's description, and a browser test asserts the label over
a run whose manifest carries the *old* name. Reversal cost: revert the label table and the stage table entry.

**D4 — `prepare_ring_constraints.py` and `refine_bonded.py` are staged for every AA–CG mapping, and the implicit
predicates collapse to the path the runs prove.** `fit_topology.sh` currently branches on `[ -f … ]` for both. A
mapping with no rings has nothing to expand and the refine pass does nothing without a torsion model, so both scripts
can be present and inert. Reversal cost: restore the file tests.
*D4a — the refinement stays driven by the mapping*, never by a run setting: `bonded_options.torsion_model` (with
`torsion_scale`) is the only switch, because it changes the topology's terms and the mapping is what gets hashed into
the run.

**D5 — `dihedral-fit` and `bonded-cross-check` run with every AA–CG run.** They declare inputs in stages 2 and 3 only
(no CG trajectory), so they are re-derivations of what the fit wrote, available as soon as the fit exists. They run as
analyses, not inside the stage: a check must not be able to fail a stage. Reversal cost: drop them from the run
type's default analyses.

**D6 — The Analyses control on the run card is built to `docs/design/2026-10-16-analyses-control.md`**, over a new
`GET /api/analysis-kinds`. It is a separate slice: this record only fixes the contract it reads.

**D7 — The torsion-model switch is surfaced in the mapping editor (Bonded workspace), not in the run panel.** It is a
model property; the run panel should not be able to change terms invisibly.

### The seam contracts between the layers

Naming these here so that two agents building two layers cannot disagree about them:

* `analysis/kinds.py` gains `published()` — the kind table as JSON-safe dicts: `name`, `label`, `inputs`, `payload`
  (the keys a kind's route requires, or `null`), `runs_for_every_run`, `default_for_run_types`, `summary`. The web
  layer's `GET /api/analysis-kinds` serialises exactly this.
* `analysis/kinds.py` gains `default_for(run_type)` — the kinds an AA–CG run gets without being asked. The
  coordinator reads it; the route does not.
* The AA–CG run type's stamped profile is the string `'draft-smoke-reference'`, recorded in `manifest.json` under
  `profile` as it is today.
* The stage's new display name is `CG parameterization`; the old one (`CG topology (ff_inter)`) must still map to the
  same abbreviation in the panel for runs already on disk.

## Questions to judge before the build is called done

1. D1 removes the ability to stop an AA–CG run after fitting. Is the fit's own record plus D5's checks enough, or do
   you want a queue-time "stop after stage 3" that is not the bonded workflow's business?
2. D2 pins AA–CG to one profile. If you ever want a second AA–CG duration preset, it belongs in Stage settings
   (a saved set of durations), not in a profile select — say if you want that instead.
3. D5 makes the two checks default. They cost seconds against a run that costs hours; say if you would rather have
   them offered and not run.
