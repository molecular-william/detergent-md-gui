# New Run panel and bonded contract: implementation plan

> **For Hermes:** execute with `subagent-driven-development`, one child per layer, parent commits. The design record
> is `docs/design/2026-10-16-new-run-panel-refactor.md`; read it, do not work from a summary of it.

**Goal:** make the AA–CG run type fit its own bonded parameters always, remove the two controls that made that a
per-run choice, and make the fit's two checks part of every AA–CG run.

**Architecture:** four layers, disjoint files. The execution layer (adapter, coordinator, stage script) owns what a
run does; the analysis layer owns the kind table and its two new accessors; the web layer owns the panel, the label
table and the mapping-level torsion switch; the parent owns the docs and every commit.

## Why

The owner's rule: every AA–CG run produces a parameterized CG molecule — validation is a separate question — and a CG
run handed a pre-parameterized molecule never fits. Today the panel asks the user to choose fitting behaviour twice
("Bonded parameters", "Bonded workflow") and to choose a "Execution" profile whose only non-duration effect is whether
the run is staged a mapping at all.

## Current state, verified

* `dashboard/execution/adapters/cg.py:190` — `prepare(… profile='standard', …, mapping_candidate=None,
  bonded_state_snapshot=None, bonded_intent='fit_and_simulate', …)`.
* `…/cg.py:210` — the only block that exports `2_mapping/{model.json,mapping.map,mapping.ndx,README.txt}`
  (`:211-215`) and copies `sugar_mapping.py` (`:233`), `prepare_ring_constraints.py` (`:236`) and
  `refine_bonded.py` (`:217`) sits inside `if profile in ('draft-smoke','draft-smoke-reference')`.
* `…/cg.py:224-232` — the `bonded_intent == 'reuse_state'` branch writing `BOND_STATE.itp`; `:277-280` the manifest's
  `mapping_candidate`/`mapping_sha256`; `:314-346` `readiness()`, whose mapping check is also inside the profile test;
  `:420-421` the keys the run type accepts.
* `dashboard/execution/coordination/coordinator.py:391-392` — `bonded_state_snapshot`/`bonded_intent` into the work
  item; `:416` `stop_after='CG topology (ff_inter)' if … 'fit_only'`; `:418-421` the fit-only run recording a bonded
  state revision; `:429-436` `create_job`'s signature and the stored intent; `:490-496` the `reuse_state` refusal.
* `dashboard/execution/scripts/fit_topology.sh` — `if [ -f prepare_ring_constraints.py ]` and
  `if [ -f refine_bonded.py ]`, both implicit predicates over a file copied under a profile gate.
* `dashboard/analysis/kinds.py:68` — `TABLE`; `:89` `bonded-cross-check`; `:119` `dihedral-fit`; `:64`
  `runs_for_every_run`; `:268` the accessor that returns the kinds with that flag.
* `dashboard/web/templates/dashboard.html:370` the `profile` select, `:378` `bonded_state_id`, `:379`
  `bonded_intent`, `:380` the sentence explaining them.
* `dashboard/web/static/js/new-run.js:148` the field list, `:283` the AA–CG payload, `:17-18` `AA_FIELDS`/`CG_FIELDS`.
* `dashboard/web/static/js/runs.js:166` the stage-label table (the abbreviation a completed run displays).
* `dashboard/models/bonded/__init__.py:215-224` the only two keys `bonded_options` accepts
  (`torsion_model`, `torsion_scale`) and the error if the scale is used without the model; `:287` the gate that reads
  it; `:292` the written row shape.
* Measured, from the store: `profile` = standard 6 (all `aa_only`), draft-smoke-reference 2 (both `aa_cg`);
  `bonded_intent` = default 6, `fit_and_simulate` 2, `fit_only`/`reuse_state` 0; `bonded_state_id` carried by 0 jobs;
  `BOND_STATE.itp` in 0 runs; `bonded_fit.json` with any torsion in 0 runs.

## Design

1. **The run type owns fitting.** `aa_cg` always fits; a run type that consumes a pre-parameterized molecule never
   does. No per-run intent, no per-run state selection.
2. **The profile stops being a panel choice for AA–CG.** The route stamps `'draft-smoke-reference'`; the manifest
   records it; `standard` stays available to `aa_only`, which is the only type that has used it.
3. **The mapping is staged unconditionally for an AA–CG run** — the export and the three script copies leave the
   profile test. A mapping with no rings has nothing to expand, and the refine pass does nothing without a torsion
   model, so both scripts are staged always and inert when unused.
4. **Stage 3 is `CG parameterization`** — rings, fit, refine, record. The panel maps both spellings.
5. **The refinement's only switch is the mapping's** `bonded_options.torsion_model`, surfaced in the Bonded workspace.
6. **`dihedral-fit` and `bonded-cross-check` run with every AA–CG run** as analyses (they read stages 2 and 3 only).
7. **The Analyses control** (`docs/design/2026-10-16-analyses-control.md`) is the next slice; this plan fixes only the
   `analysis/kinds.py` accessors it will read.

## Seam contracts (both sides of every cross-layer call)

```
analysis/kinds.py::published() -> list[dict]
    keys: name, label, inputs (list[str]), payload (list[str] | None), runs_for_every_run (bool),
          default_for_run_types (list[str]), summary (str)
analysis/kinds.py::default_for(run_type: str) -> list[str]      # names, for the coordinator
the AA-CG run type's stamped profile: 'draft-smoke-reference'    # recorded in manifest.json["profile"]
stage display name: 'CG parameterization'                        # was 'CG topology (ff_inter)'
```

## Phases

### Phase A — execution layer (child A)

Files: `dashboard/execution/adapters/cg.py`, `dashboard/execution/coordination/coordinator.py`,
`dashboard/execution/scripts/fit_topology.sh`, `tests/dashboard/**` covering those.

* A1 replace the profile gate around the mapping block with the run type (`metadata['run_type']`, or a parameter the
  route passes — say which in the report and keep `prepare`'s signature honest).
* A2 stamp `'draft-smoke-reference'` for `aa_cg` when no profile is supplied, and record it in the manifest as today.
* A3 drop `bonded_state_snapshot`/`bonded_intent` from `prepare` and from the work item; delete the `reuse_state`,
  `fit_only` branches, the `stop_after` call and the `bonded_state_id` refusal; keep `models/bonded` untouched.
* A4 collapse the two `[ -f … ]` predicates in `fit_topology.sh` to unconditional calls, and keep the script's own
  comment that says why they may be inert.
* A5 rename the stage in `STAGE_DEFS` to `CG parameterization` and check nothing keys on the old string outside the
  panel's label table (grep it, report the hits).
* A6 in `coordinator.py`, queue `kinds.default_for('aa_cg')` for a completed AA–CG run exactly the way the run's
  existing automatic kinds are queued — read how `runs_for_every_run` reaches the queue today before adding a second
  path. `kinds.default_for` may not exist yet: if child B has not landed it, call it defensively, report the seam, and
  leave the call site compiling.

### Phase B — analysis layer (child B)

Files: `dashboard/analysis/kinds.py`, `dashboard/analysis/metadata.py` (only if a label lives there),
`tests/dashboard/unit/**` for the table.

* B1 add `default_for_run_types` to the `Kind` record and set `('aa_cg',)` on `dihedral-fit` and
  `bonded-cross-check`, with the sentence in the record saying why those two and not the rest.
* B2 add `published()` and `default_for(run_type)` exactly as the seam block names them, JSON-safe, no dashboard
  objects leaking into the dicts.
* B3 tests: every kind's `payload` matches what `routes/analyses.py` actually requires for it (read the route, do not
  guess); `default_for('aa_cg')` returns the two names; a kind marked `runs_for_every_run` is not in
  `default_for_run_types`.

### Phase C — web layer (child C)

Files: `dashboard/web/templates/dashboard.html`, `dashboard/web/static/js/new-run.js`,
`dashboard/web/static/js/runs.js`, `dashboard/web/static/js/bonded.js`, `dashboard/web/routes/**` (only the run-route
profile stamp if the route is where A2 puts it), `tests/dashboard/browser/**`.

* C1 remove the `profile`, `bonded_state_id` and `bonded_intent` controls from the AA–CG fieldset and the sentence
  that explained them; keep the mapping select and the AA-reference select.
* C2 stop sending the three keys from the AA–CG payload; the AA-only panel keeps its profile select untouched.
* C3 add one facts line to the panel stating what an AA–CG run does by itself: it fits its own bonded parameters from
  the AA reference, and the refinement follows the mapping.
* C4 map both stage spellings in `runs.js`'s label table, keep the recorded name in the step's description, and add a
  browser test over a run whose manifest carries `CG topology (ff_inter)` asserting the visible abbreviation plus the
  recorded words.
* C5 surface `bonded_options.torsion_model` (and `torsion_scale` beside it) in the Bonded workspace, disabled unless
  `circular-harmonic` is chosen — the model already validates both keys, so this is the control only.

### Phase D — parent

`docs/HANDOFF.md`; the `detergent-md-dashboard` skill (a rule about removing a profile-gated branch); re-run the fast
tier after the verify line; one gate commit per coherent group, none by a child.

## Acceptance

* Fast tier green (`-m 'not browser and not slow'`) with the count measured in the same pass; `ruff` zero over the
  named paths.
  **Measured at landing** (commit `b56cddb`, 22 files, 927 insertions): fast tier **1735 passed** (1718 before, +17
  from the new tests), `ruff` exit 0 over 17 Python paths, browser tier **195 passed** (190 before, +5).
* Browser tier green, including the new stage-name test.
* `ruff`/pyright clean over the touched Python.
* A scratch `prepare()` probe for the AA–CG run type into a scratch directory (never `workspace/`): `2_mapping/model.json`,
  `sugar_mapping.py`, `prepare_ring_constraints.py` and `refine_bonded.py` all present with no profile passed, and
  `manifest.json["profile"] == 'draft-smoke-reference'`.
* The adapter refuses no longer: grep `bonded_intent|bonded_state_id|stop_after` across `dashboard/` and report every
  remaining hit; the only acceptable hits are in `models/bonded` and the frozen history records.
* The eight existing runs still read correctly in the panel (label test for the old stage spelling).
* Numbers written back under each task in this file as they are measured.

## Out of scope

* The Analyses control itself (D6) — next slice, spec on disk.
* A BARTENDER fit as a stage, and the `standard` AA–CG path (dropped, not built).
* Re-fitting anything for the eight existing runs; their records are frozen history and stay as they are.
