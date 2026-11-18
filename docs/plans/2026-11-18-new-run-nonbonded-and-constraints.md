# Plan · New run: one Nonbonded and constraints section for AA and CG

Status: **implemented 2026-11-18**. Draft:
`docs/design/drafts/2026-11-18-new-run-nonbonded-and-constraints.html` (and the rendered `.png`). Follows the
single-molecule form (`dashboard.html` `#run-form`) and the stage-settings work of
`docs/plans/2026-11-16-stage-settings-and-progress.md` and
`docs/plans/2026-11-17-pdc-per-stage-physics-and-box-estimate.md`.

Checks: fast tier **3128 passed / 1 xfailed**; browser tier **415 passed at `-n 8`** (the known
assessment-rescore and pdc `-n 16` contention flakes remain, both green solo); `ruff` clean over every
changed Python path. The layout test's two bounding-box reads now happen in one `evaluate`, so a late
molecule-check reflow cannot split them.

## What the user asked for

More input boxes inside the New run panel's **Stage settings** for the validation workspace:
`rlist`, `rvdw`, `rcoulomb`, `epsilon-rf` (CG), `vdwtype`, `vdw-modifier`, `nsttcouple`,
`nstpcouple`, `lincs-order`, `lincs-warnangle`, and the other nonbonded/constraint parameters
relevant to this project's AA and CG MD runs.

## Decisions taken by the user (2026-11-18)

1. **Both AA and all three CG kinds** (revision, published sugar reference, composition).
2. **One shared section per run**, not per-stage fields: one set applies to every dynamics leg
   (AA NVT/NPT/production; CG equilibration and production). Minimisation legs keep their
   reviewed values.
3. **The proposed parameter set** (table below); `rvdw-switch` and `coulombtype` included as
   discussed, with `epsilon-r` beside `epsilon-rf`.
4. **Hard-refuse invalid combinations** at the queue route with the form showing the same rule
   as a hint; GROMACS' reviewed defaults stay in force when a box is blank.

## Settings

One shared vocabulary, advertised by every adapter that accepts it. The setting key is the
form's `name`; the MDP key is what the writer states.

| setting | MDP key | kinds | reviewed default | bounds |
|---|---|---|---|---|
| `rlist` | `rlist` | AA, CG | AA 1.2 (force-field block); CG blank (GROMACS sizes it from the Verlet tolerance) | 0.1–5 nm |
| `rcoulomb` | `rcoulomb` | AA, CG | AA 1.2 (force-field block); CG 1.1 | 0.1–5 nm |
| `rvdw` | `rvdw` | AA, CG | AA 1.2 (force-field block); CG 1.1 | 0.1–5 nm |
| `rvdw_switch` | `rvdw-switch` | AA, CG | AA 1.0 (force-field block); CG blank (only relevant to a switched potential) | 0–5 nm |
| `vdwtype` | `vdwtype` (AA) / `vdw-type` (CG) | AA, CG | AA `cutoff` (Cut-off); CG `cutoff` | choice `cutoff`, `pme` |
| `vdw_modifier` | `vdw-modifier` | AA, CG | AA `force-switch`; CG `potential-shift-verlet` | choice `force-switch`, `potential-shift-verlet`, `potential-switch`, `none` |
| `nsttcouple` | `nsttcouple` | AA, CG | blank = GROMACS' `-1` rule | 1–10000, integer |
| `nstpcouple` | `nstpcouple` | AA, CG | blank = GROMACS' `-1` rule | 1–10000, integer |
| `lincs_order` | `lincs-order` | AA, CG | AA blank (GROMACS 4); CG 4 | 1–12, integer |
| `lincs_warnangle` | `lincs-warnangle` | AA, CG | AA blank (GROMACS 30°); CG 30 | 0–180, integer |
| `lincs_iter` | `lincs-iter` | AA only | blank (GROMACS 1) | 1–10, integer |
| `epsilon_r` | `epsilon-r` | CG only | 15 | 0–1000 |
| `epsilon_rf` | `epsilon-rf` | CG only | 0 | 0–1000 |
| `coulombtype` | `coulombtype` | CG only | `reaction-field` | choice `reaction-field`, `pme`, `cut-off` |

AA is PME, so `epsilon-r`/`epsilon-rf`/`coulombtype` are not offered there. CG profiles set
`constraints = none`, so the LINCS fields are shown but marked inert for CG (the values are still
recorded and written, and become meaningful if a CG model ever states constraints).

Out of scope: `DispCorr`, `comm-mode`, PME grid options (`fourier-spacing`, `pme-order`),
`coulomb-modifier`, cutoff scheme (Verlet is the only supported scheme).

## Invariant: an untouched run still renders the reviewed files byte for byte

Every reviewed value is also the form's prefill, so the payload always carries the shared keys.
`mdp_values` therefore emits an override **only when it differs from the reviewed value**
(numeric equality, or case-insensitive string equality). Each adapter passes the reviewed map:

- AA: `forcefields.entry(name).mdp` (the force-field block the writer renders).
- CG: `PROFILES[profile].settings` for the leg being written.

GROMACS is case-insensitive on enum values, so `stage_defaults` states the canonical lower-case
choice (`cutoff`, `force-switch`), and the writer maps a changed choice to the spelling GROMACS
documents (`Cut-off`, `PME`, `Force-switch`, …). A value equal to the reviewed one is dropped, so
the force-field block or profile keeps its own line and spelling.

Options the profile does not state (`nsttcouple`, `nstpcouple`, AA `lincs-*`) stay blank by
default and write no line; blank means GROMACS' own rule. The form's "Default" button clears those
(`data-clear-default`) and restores the reviewed value elsewhere.

## Validation (hard refusal at the queue route, and the form's hint)

Rules taken from the GROMACS 2026-rc manual and `src/gromacs/gmxpreprocess/readir.cpp`:

1. `rlist >= max(rcoulomb, rvdw)` — "With verlet lists rlist can not be smaller than rvdw or
   rcoulomb".
2. `rcoulomb == rvdw`, except PME electrostatics with `vdwtype = cutoff` may have
   `rcoulomb > rvdw` — "With Verlet lists rcoulomb!=rvdw is not supported (except for
   rcoulomb>rvdw with PME electrostatics)".
3. `vdwtype = pme` allows only `vdw_modifier` `none` or `potential-shift-verlet` — "With vdwtype
   = PME, the only supported modifiers are …".
4. A switched potential (`force-switch`, `potential-switch`) requires `0 < rvdw_switch < rvdw` —
   "With switched vdw forces or potentials, rvdw-switch must be < rvdw". GROMACS only warns at
   `rvdw-switch = 0`; the route refuses it because the warning means large energy errors.
5. `epsilon_rf != 0` requires `coulombtype = reaction-field`, and then `epsilon_rf >= epsilon_r`
   unless `epsilon_r = 0` — `readir.cpp`'s reaction-field checks.
6. AA only: `max(rlist, rcoulomb, rvdw) < box_nm / 2` — the existing `aa_box.check_cutoffs` rule,
   widened from `rlist` to every cut-off the run now owns, at the queue route and again at prepare.
7. All counts are integers (`nsttcouple`, `nstpcouple`, `lincs_order`, `lincs_warnangle`,
   `lincs_iter`).

A CG run's box is its AA reference's, so rule 6 is the AA half's; a CG pinned cut-off that
exceeds the reference box stays `grompp`'s refusal at prepare (the route has no box to measure).

The coupling interval need not be a multiple of `nstlist` (GROMACS states none); nothing is
invented. `epsilon_rf == epsilon_r` is a GROMACS warning, not an error, so it stays a form hint.

## Cross-layer changes

- **`execution/nonbonded.py` (new).** One vocabulary: the numeric bounds, the choice lists, the
  per-kind MDP-key maps, the canonical spellings, `stage_defaults` helpers, `overrides()` and
  `check()`. Adapters import it instead of restating tables.
- **`execution/mdp/writer.py`.** A `Profile.variable` option that names an option already in
  `settings` (the force-field block's `vdwtype`, for example) **replaces** it; matching is by
  folded name (`_`/`-`, case), so no duplicate option line and the existing spelling is kept.
  A variable option the profile does not state is still appended only when named.
- **`execution/mdp/profiles.py`.** `_AA_DYNAMICS_VARIABLE` gains the AA MDP keys;
  `_CG_EQUILIBRATION_VARIABLE` and `_CG_PRODUCTION_VARIABLE` gain the CG MDP keys. Neither
  minimisation profile changes. Comments state each new option's role and the CG-inert LINCS note.
- **`adapters/aa.py`.** Advertise the 11 AA keys in `SETTING_SPECS`/`CHOICE_SPECS`;
  `stage_defaults` adds the force-field-reviewed values for the form; `normalize_settings` uses a
  defaults dict without them (so a CG revision run does not inherit the AA half's cut-offs through
  `cg_settings | aa_settings`), then calls `nonbonded.check(..., reaction_field=False, box_nm=...)`;
  `mdp_values` adds the differing overrides to NVT/NPT/production; `prepare`'s cut-off check uses
  the largest effective cut-off.
- **`adapters/cg.py`.** A `SHARED_OVERRIDES` table for the 13 CG keys; `rlist`/`rcoulomb`/`rvdw`
  move out of `PRODUCTION_OVERRIDES` into it, so they now apply to equilibration and production.
  Advertise them; `stage_defaults` adds the reviewed defaults; `_normalize_cg_settings` validates;
  `mdp_values` adds the differing overrides to both dynamics legs.
- **`adapters/composition.py`.** Derives the numeric keys from `cg.SETTING_SPECS` automatically;
  add the three choice tables and the validation call.
- **`validation/.../sugar_cg.py`.** Add the shared keys to `CG_SETTINGS` and the three choices;
  validate.
- **`execution/settings_help.py`.** One manual-derived sentence for each new setting (the form
  already renders the info button from this map).
- **`web/stage_settings.py`.** A `Nonbonded and constraints` group after the stage groups for
  AA and CG, so the read-back shows the shared values once rather than under "Run settings".
- **`web/templates/dashboard.html`.** The section after the CG stage editors (inside the
  Stage settings fieldset): a hint, then the 14 controls in the four-across grid with
  `aa-setting` / `cg-setting` classes only where a control is one kind's.
- **`web/static/js/new-run.js`.** `SHARED_AA_FIELDS` / `SHARED_CG_FIELDS` added to the four
  field lists (`CG_PRODUCTION_FIELDS` drops the three moved keys); the Default handler clears a
  `data-clear-default` control when the current kind has no reviewed value.
- **Docs.** `docs/design/drafts/2026-11-18-new-run-nonbonded-and-constraints.html` (this round's
  draft), this plan, and a `HANDOFF.md` entry after the checks pass.

Backwards compatibility: a saved preset or an old payload that names `rlist`/`rcoulomb`/`rvdw`
still works; for a CG run those values now reach the equilibration leg as well as production
(the setting is shared by decision). No key is renamed.

## Tests

- Unit (`packages/core/tests/unit/test_nonbonded_settings.py`, plus existing parity tests):
  untouched AA and CG renders are byte-identical; each setting reaches both dynamics legs and no
  minimisation leg; each refusal rule above (with its message); integral counts; every adapter
  publishes the keys (extend `test_each_cg_kind_publishes_the_stage_settings_it_runs`).
- Integration: a queue payload carrying the shared keys keeps them in the prepared record
  (`test_jobs_stage_settings_api.py` / `test_aa_inputs.py` neighbours); a bad combination answers
  400 with the named rule.
- Browser: the section appears for AA, CG revision, reference and composition; AA/CG-only
  controls hide correctly; prefills are the reviewed numbers; a Default click restores/clears;
  the section submits and clones.

## Checks

```
.venv/bin/python -m pytest packages/core/tests/unit/test_mdp_writer.py packages/core/tests/unit/test_nonbonded_settings.py -q
.venv/bin/python -m pytest packages/core/tests/unit packages/core/tests/integration -q -n 0 -p no:cacheprovider
.venv/bin/python -m pytest -m browser -q -n 16 --dist worksteal
.venv/bin/ruff check packages tests conftest.py
scripts/gate_commit.sh <message-file> <paths...>
```
