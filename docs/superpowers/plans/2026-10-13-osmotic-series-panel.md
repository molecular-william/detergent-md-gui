# An Osmotic Series panel for Detergent validation

Status: **DRAFT — for review. Nothing is built.** This plan and the HTML mock beside it
(`docs/superpowers/drafts/2026-10-13-osmotic-series-panel-draft.html`) are the deliverable of the ask.

The ask, verbatim: *"For 'Detergent validation', I would like there to be a panel for setting up the osmolarity run,
there should be options of how many simulations to run in series (what concentrations are desired), and what sugar to
use."*

This panel is a **setup door for the `osmotic` run type**, which is already built and already run: an executor-side
run type (`dashboard/execution/adapters/osmotic.py`), a runner (`dashboard/execution/scripts/osmotic_simulation.sh`),
a queue route (`dashboard/web/routes/osmotic.py`), and an analysis
(`dashboard/analysis/runs/osmotic_pressure.py`, registered as the kind `osmotic-pressure`). A completed six-condition
series for maltose is part of the project's record. What does not exist is any way to set one up from the dashboard:
there is no `osmotic` string anywhere in `dashboard/web/static/`, so the six conditions that survived were queued by
hand.

## Why a panel rather than a form field

`#new` already serves four run types through one form, and the pdc work of 2026-10-12 showed what happens when a
fifth is bolted onto it: most of that form is redundant for the new path and some of it is unanswerable. Measured
against `dashboard/execution/adapters/osmotic.py` and
`dashboard/execution/coordination/admission.py`:

- `admission.validate_run_type` **refuses a `reference_run_id` for `osmotic`** — "An osmotic condition takes its
  solute from a mapping, not from a shared AA reference". So the New run form's AA-reference control is not merely
  redundant here, it is a control whose use is a 400.
- `osmotic.SETTING_SPECS` and `osmotic.CHOICE_SPECS` are the run type's whole vocabulary, and the New run route
  learned (in a comment at `routes/runs.py:123-126`) that the union of the AA and CG dialect tables is *not* it.
- A series is not one run: the route queues **one job per molality sharing a `series_id`**, so the control this panel
  most needs — an editable set of concentrations — has no home in a single-run form at all.

The Detergent validation workspace already registers an `osmotic-pressure` panel, in `PLANNED` and not in any
workspace's `tabs` (`dashboard/web/sections.py:73-74`, "not built yet; the reader exists and is tested"). That is the
reader. This panel is the door that produces what it reads.

## What the panel collects, and why each one

Every row names the real key and the file it is read from. This is the whole point of the table: the mock's fields are
the settings the existing pipeline reads, each under its own name.

| field | real key / source of truth | keep / drop / add |
| --- | --- | --- |
| Sugar | `molecule_id` (route body) | **add** — the run's solute |
| CG mapping for that sugar | `mapping_candidate` (route body; `create_job` resolves it to `mapping_snapshot`, which `prepare` sizes the box from) | **add** |
| Concentrations | `molalities` (route body; each job carries one as `osmotic_molality`) | **add** — the headline control |
| Duration per condition | `osmotic_production_ps` (`osmotic.DEFAULTS`, default 500000) | **add** |
| Equilibration | `osmotic_equilibration_ps` (default 10000) | show, advanced block |
| Trajectory output interval | `osmotic_output_interval_ps` (default 10.0) | show, advanced block |
| Temperature | `temperature_k` (`osmotic.SETTING_SPECS` 200–400, default 308.15) | keep, editable — it is the experimental dataset's, so it changes with the sugar |
| Method | `method` (route body, default `fast_forward`) | keep, **standing, not shown** — it is how the CG topology was fitted, not a choice this panel makes |
| Solute files | `solute_root` (route body; required by `admission`) | **add, resolved and shown, never typed** — see below |
| Series id | `series_id` (`osmotic.CHOICE_SPECS`) | server-generated; shown in the review, never a control |
| Box | `osmotic_box.BOX_NM` = (5.04156, 5.04156, 10.08312) nm | **show only** |
| Dividing area | `osmotic_box.dividing_area_nm2()` = 25.41733 nm² | **show only** |
| Confinement and its constant | `osmotic_box.CONFINEMENT_NM` 2.52078 nm, `CONFINEMENT_KJ_MOL_NM2` 1000 | **show only** |
| The wall's PLUMED constant | `osmotic_mdp.plumed_walls` writes `KAPPA = force_constant / 2` = 500 | **show only** |
| The restraint | `osmotic.REFERENCE_RESTRAINT` = 10000 kJ/mol/nm² on the bead's z, `refcoord-scaling = all` | **show only** |
| Salt | none — the runner's own note: "No ions are added, because the osmometry it compares against measured salt-free solutions" | **show only** |
| Seed | the runner's placement RNG, `random.Random(20261006)`; the mdps fix `gen-seed = -1` | **show only** |
| mdrun threads and ranks | `mdrun_ntomp` 4, `mdrun_ranks` 1 (`osmotic.DEFAULTS`, the measured best for this system with PLUMED loaded) | **show only** |
| Run type, Force field, Execution profile, AA reference source, Bonded parameters, SASA probe, box edge, CG/AA durations | — | **drop**: `osmotic` reads none of them, and a `reference_run_id` is refused outright |

**`solute_root` is resolved by the server, not typed into a field.** The route requires it and the adapter refuses a
run whose directory is missing one of `SOLUTE_FILES` = `solute.gro`, `solute.itp`, `water.gro`,
`martini_v3.0.0_solvents_v1.itp`. The six completed conditions used
`workspace/osmotic/maltose/`. A free-text filesystem path in a browser form is the wrong control for that, so the
panel shows the path the server resolved and blocks when a file is missing — the same shape as the pdc panel's
half-thickness honesty.

## The sugar: what can be built, and the refusal

The panel offers **one carbohydrate as the series' solute**, and a saved CG mapping is the gate, because the box is
sized from the mapping's beads: `prepare` calls `osmotic.solute_bead_radii(mapping_snapshot)`, which reads
`RADII_NM` (`dashboard/models/sugars/recognition.py`) for every non-virtual bead. No mapping, no radii, no box.

The sugar list comes from two places the repository already names, so nothing is invented:

- the carbohydrate folders under `molecules/` — **Maltose, Sucrose, Trehalose** (all three `valid` and `executable`
  from `GET /api/molecules`), each with a saved candidate from `GET /api/mappings?molecule_id=<id>`;
- the carbohydrates named by `resources/validation/carbohydrates/targets-v1.json`, which adds **Glucose** — a
  molecule the repository carries a citation and a measured partition free energy for, and has no folder and no
  mapping for.

Read live, the gate gives this table, and it is the table the panel renders:

| sugar | molecule folder | saved CG mapping | solute files | what the panel does |
| --- | --- | --- | --- | --- |
| Maltose | ✓ | ✓ (1 candidate) | ✓ `workspace/osmotic/maltose/` | offers it, ready |
| Sucrose | ✓ | ✓ (1 candidate) | ✗ | offers it, **blocked**: solute files not prepared |
| Trehalose | ✓ | ✓ (1 candidate) | ✗ | offers it, **blocked**: solute files not prepared |
| Glucose | ✗ | ✗ | ✗ | **refused with the reason** — no molecule folder, so no saved CG mapping |

The design, stated so it can be argued with: the selector carries every carbohydrate the repository names, and one
that cannot be built is shown with its blocker and **cannot be queued** — selecting it renders the refusal and
disables Start. "Refuse with a reason rather than offering it" is taken to mean *offer the reason, not the run*; a
list that silently omits a molecule leaves the reader unable to tell a missing mapping from a typo.

Two further facts are shown beside the sugar rather than hidden, because both are the repository's own standing
decisions:

- Sucrose's mapping is **provisional**: `AGENTS.md` records that the recogniser handles one hexopyranose ring and
  preserves the rest of the graph as a draft, and that generated Sucrose mappings are diagnostic inputs rather than
  official Martini parameters. The panel says so where Sucrose's blocker is shown.
- A completed series is not validation. The route's own answer carries `scientifically_validated: false`, and the
  panel repeats it.

## The series: the concentrations, the duration, the count

Three controls, and the default is the series that already exists.

- **Concentrations** — an editable list, one row per molality, each row removable and a button to add one. The
  default is the six the route already defaults to, `routes/osmotic.PAPER_MOLALITIES = (0.0, 0.5, 1.0, 1.5, 2.0,
  2.5)`: the five measured points Ebrahimi & Sadeghi report at 308.15 K, **plus the 0.0 control**. Each value is
  bounded by `osmotic_box.MOLALITY_RANGE = (0.0, 2.5)` and by the setting's own spec
  `osmotic_molality: ('Molality', 0.0, 2.5)`; a value outside it is refused by the route with the bound named
  (`test_a_molality_the_build_cannot_place_is_refused_and_the_series_is_not_half_created`), so the panel refuses it at
  the row and says which value and which bound.
- **Duration per condition** — one number for the series, in ns in the UI and `osmotic_production_ps` on the wire.
  Default **500 ns** (`osmotic_mdp.DEFAULT_PRODUCTION_PS` = 500000 ps): the paper's own bar, Methods 5.3, and what
  all five measured conditions in the completed series ran.
- **The count** — a running `N runs · total ns`, recomputed on every add, remove and edit. It mirrors the route's own
  `count` and the plan's own bar: six conditions at 500 ns is 3000 ns, and at the measured ~2400 ns/day for one
  condition run alone that is about 1.25 days of wall clock.

The 0.0 control is a row like any other. It is worth saying what it is: with no solute there is no `plumed.dat`
(`osmotic_mdp.plumed_walls` refuses a zero molecule count) and therefore no `osmotic-pressure.json` — no wall to
push against. `condition_for` reports it as `measured: null`, and the reader shows the row rather than dropping it
(`test_the_control_is_a_row_and_not_a_missing_one`). The completed control ran 2 ns rather than 500; the panel gives
the series one duration and takes the control with it, which is the simpler contract and is flagged below.

## Series behaviour, stated rather than implied

- **One at a time.** Not a control: `config/dashboard.json` sets `max_concurrent_runs: 1` and the coordinator refuses
  to start a second run while one is busy ("Simulation capacity is busy"). The runner records the measurement behind
  that limit — ~2400 ns/day for one condition alone against ~291 each for four sharing cores — so the panel states
  the number and does not offer a fan-out.
- **On failure of one condition**, the rest of the series **carries on**. This is the existing route's contract and
  not a new one: `POST /api/osmotic/series` creates every condition up front and refuses *before* creating anything if
  any of them is wrong, so once the series exists a failed condition does not cancel its siblings. The reader already
  reports a gap rather than drawing a curve through it (the plan's Task 2.2). A "stop the series on the first failure"
  option is offered, and taking it means queueing one condition at a time instead of as a batch — a driver, which is
  a task below rather than a checkbox the route already honours.

## The physical setup the pipeline reads, shown with the values the run will use

An expandable block, read-only, one line each with the file it comes from:

| shown value | value | source |
| --- | --- | --- |
| Box | 5.04156 × 5.04156 × 10.08312 nm (256.286 nm³) | `osmotic_box.BOX_NM` |
| Dividing area | 25.41733 nm² | `osmotic_box.dividing_area_nm2()` |
| Confinement | flat within 2.52078 nm of the box centre, 1000 kJ/mol/nm² beyond | `osmotic_box.CONFINEMENT_*` |
| Walls | PLUMED, `UPPER_WALLS`/`LOWER_WALLS`, `KAPPA = 500` (half the paper's constant, written by `plumed_walls`) | `osmotic_mdp.plumed_walls` |
| Restraint | the reference bead `REF`, restrained to the box centre in z at 10000 kJ/mol/nm², `refcoord-scaling = all` | `osmotic.REFERENCE_RESTRAINT` |
| Salt | none added | the runner's own note |
| Seed | placement `random.Random(20261006)`; mdps `gen-seed = -1` | `osmotic_simulation.sh`, `osmotic_mdp._lines` |
| Temperature | the dataset's; 308.15 K for maltose | `temperature_k`, `osmotic_box.temperature_source` |
| mdrun | `-ntomp 4 -nb gpu -gpu_id 0 -pin on`, 1 rank | `osmotic.DEFAULTS`, the runner |

## What this panel will not do

- **No fan-out.** One condition at a time, by the concurrency limit above; the panel shows the reason rather than a
  control to change it.
- **No queueing without the reader asking.** The panel collects and reviews; nothing is created until Start run is
  pressed, and the review states the series id and the count first.
- **Nothing that claims the series validates a model.** A completed series is execution and measurement. The route
  returns `scientifically_validated: false`, `osmotic_pressure.publish` divides a force by an area and says nothing
  about the model, and the panel's own review line is the repository's: *Execution success does not establish
  scientific validation.*
- **No second door to the same route.** The panel posts to the existing `POST /api/osmotic/series`; it does not grow
  a parallel queue path.

## Tasks

Each task is test-first and would land with its own commit and gate run. **Nothing here is built.**

**T1 — the panel exists in the validation workspace, and nowhere else.** Register a panel slug `osmotic-series`
(`sections.py`: `PANELS`, `TAB_IDS`, `PANEL_BLURBS`, and a section in `SECTIONS['validation']['tabs']`), a template
section, and a static `osmotic.css`/`osmotic.js` pair. The `osmotic-pressure` reader slug stays registered; whether it
is folded into this panel or kept beside it is the open decision below.
Tests: browser — `/detergent-validation/osmotic-series` renders the sugar, the concentrations, the duration and the
count; `/protein-detergent/` and the other validation panels are unchanged.
Acceptance: the rail label is "Osmotic Series", the heading is the panel's own, and no other panel's label moves.

**T2 — the catalogue route, so the sugar list is what the server decided.** `GET /api/osmotic/catalogue` returns, per
carbohydrate: `molecule_id`, `label`, `mappings` (from `mappings.list_candidates(context=…)`), `solute_root`,
`solute_files_present`, `ready`, `blockers`, and a reason for anything named but not buildable. Nothing about
readiness is recomputed in JavaScript — the panel renders the answer.
Tests: with a fixture molecule holding no candidate, the route returns `ready: false` and the blocker *names the
missing mapping*; with the fixture's four `SOLUTE_FILES` present and a candidate, it returns ready; a carbohydrate in
the targets registry with no folder is returned as named-but-not-buildable with that reason.
Acceptance: no molecule on disk without a mapping is ever reported `ready: true`.

**T3 — the concentrations and the count.** The editable list: add, remove, edit, a Reset to `PAPER_MOLALITIES`, a
per-row bound check against 0.0–2.5, and a live count and total ns.
Tests: browser — adding a row raises the count by one and the total by the duration; removing one lowers both;
duration 500 with four rows reads `4 runs · 2000 ns`; a row of 3.0 is refused with the bound named and excluded from
the count; Reset restores exactly `(0.0, 0.5, 1.0, 1.5, 2.0, 2.5)`.
Acceptance: the count equals `len(molalities)` and the total equals `len(molalities) * duration` in every state.

**T4 — the refusal.** The sugar selector's blocked and refused states: a sugar with a mapping but no `solute_root`
(or a missing `SOLUTE_FILES` entry) blocks with that file named; a sugar with no saved CG mapping is refused with that
reason; the queue is disabled in both, and Start is disabled with it.
Tests: browser — selecting the no-mapping sugar renders the refusal text and disables Start; a fixture sugar whose
`solute_root` is missing `water.gro` names `water.gro`; ready again when the file is restored.
Acceptance: the refusal always names the object that is missing, never a generic "cannot run".

**T5 — the review and the queue.** The review summary (sugar, mapping, N runs, total ns, duration, the standing
values, series id) and a Start that posts `{molecule_id, mapping_candidate, molalities, osmotic_production_ps,
temperature_k, solute_root, series_id?}` to `POST /api/osmotic/series` and reports the returned `count` and
`series_id`. Start is disabled unless the catalogue says ready.
Tests: browser — with a ready sugar the review reads the six conditions and 3000 ns and Start is enabled; the posted
body carries `molalities` as the numbers on screen; pressing Start against a stub reports the count and creates
nothing in the fixture's store without it.
Acceptance: the panel sends exactly the keys the route reads, and nothing the route would refuse.

**T6 — the series as it stands.** A read-only table fed by the existing `GET /api/osmotic/conditions`: molality,
molecules, measured bar, the paper's bar and uncertainty, the ratio, and the control row with no measurement. No
curve is drawn through a gap.
Tests: browser — the six rows of the completed series render with the control unmeasured; a missing molality is named
rather than interpolated.
Acceptance: the panel recomputes none of the numbers; it renders the route's answer.

**T7 — "stop the series on the first failure", if the user wants it.** The batch route cannot stop siblings that are
already queued, so this is a small driver that queues one condition and waits, plus the panel control. Files: the
driver (a script beside the runners), the panel, tests that it queues the second only after the first terminates and
stops on a failed status.
Acceptance: with the option off, the panel posts to the existing route unchanged and nothing new runs.

## Not doing

- Not removing or changing `POST /api/osmotic/series`, `GET /api/osmotic/conditions`, the adapter, the runner or the
  analysis. The panel is a door onto what exists.
- Not adding a control for a value the run type does not read (method, profile, threads, box, kappa, salt, seed).
- Not claiming the series validates a mapping. It executes a method and measures a pressure; the residual against the
  paper's points is evidence about both the model and the mapping at once.

## Verify

```
dashboard/.venv/bin/python -m pytest -m 'not browser and not slow' -q     # the fast tier
dashboard/.venv/bin/python -m pytest -m browser -q -n 6                   # the browser tier
dashboard/.venv/bin/python -m ruff check dashboard tests                  # F, E9, I must exit 0
```

Nothing in this plan has been run: no code was written, no test added, no commit made.
