# The Analyses control for a completed run

**Draft for review.** This record specifies the control; `static/analyses-draft.html` is the live draft, and both it
and its test (`tests/dashboard/browser/test_analyses_draft_browser.py`) are deleted together when the control lands
in `runs.js`.

## The gap, measured

The route that queues an analysis on an **existing** run already exists and is generic:

    POST /api/jobs/<jid>/<kind>          # web/routes/analyses.py:122

It queues an analysis attempt against the run's own products. It never re-simulates.

Three things the request needs are therefore all present on the server and missing in the browser:

| what | where it is | where it is not |
| --- | --- | --- |
| the queue route | `routes/analyses.py:122` | no caller in `static/js/` except `analyses/<task>/cancel` (`runs.js:180`) |
| the kind table (label, declared inputs, whether it runs for every run) | `analysis/kinds.py:68` | not exposed over HTTP at all |
| the readers for a published report | `dihedral-fit`, `bonded-cross-check`, `mapping-consistency`, `surfaces`, `overlap` (`routes/analyses.py:22-118`) | the figures panel and the Mapping Validation panel render them, the run card does not link them |

`dihedral-fit`, `bonded-cross-check` and `bartender-fit` are registered kinds that no run type's stage list contains —
`kinds.py`'s own comment on `bartender-fit` reads *"Optional by design: nothing queues it."* So a run never produces
them, no button offers them, and the only way to ask for one today is `curl`.

E3 maltose CG (`22075892b606`) is the worked example:

* every declared input of `dihedral-fit` and `bonded-cross-check` is present, so both are queueable as the run stands;
* `bartender-fit` **cannot** run: it declares `1_AA-reference/prod/lig.{gro,xtc}`, that run's `stages/1_AA-reference/`
  holds only `aa_reference.sh`, and the run records `a54ac8f64710` as its AA reference
  (`reference_run_id`) and that run keeps its trajectory under `stages/07_reference/lig.{gro,xtc}`. The declared path does not match this workspace's AA layout. That mismatch is a
  real finding and is fixed separately, but it is also the reason the control must be able to say *why* it cannot run
  a kind.

## Where the control goes

In the run card, inside the `analysis` `<details>` that already exists (`runs.js:52-59`, `.job-analysis`). The section
already lists **attempts** (`.analysis-tasks`, `runs.js:175-186`) and renders published figures. The control adds a
list **above** them:

    Analysis  <details>
      ── Available here ──────────────────────────────────────  ← new
      Dihedral terms · a criterion against the tool default      [ Queue ]
        reads: 2_mapping/mapped.gro, 2_mapping/mapped.xtc, 2_mapping/model.json,
               3_initial_CG/*_ff_inter.itp, 3_initial_CG/*initial*.itp        (all present)
      Bonded terms · our fit against the estimate                [ Queue ]
      BARTENDER bonded fit                                       [ Queue ] (disabled)
        cannot run: 1_AA-reference/prod/lig.gro is not in this run
      ── Attempts ────────────────────────────────────────────  ← existing
      dihedral-fit · completed · 41 s                            [ Cancel ]
      ── Figures ─────────────────────────────────────────────  ← existing

Nothing else in the card changes, and no other panel is touched. The Run view's monitor can inherit the same control
later; that is out of scope here because the monitor is a reader of one run and the card is where a run is acted on.

## Rules

1. **An analysis is queued only for a completed run.** Every kind reads products a completed run has; a run still in
   flight has neither a trajectory to map nor a topology to compare against. The control does not render the list for
   any other status, and the route refuses such a request for the kinds that validate their payload.
2. **A kind this run cannot answer is shown, disabled, with the input that is missing named in the path's own words.**
   Hiding it makes the reader ask "why is this missing?"; naming the path answers it and, in the `bartender-fit` case
   above, points straight at the mismatch.
3. **Availability is read from the run's own files, not from its record.** A kind is available when the artifact index
   holds each input the kind declares. The index is the same source the rest of the panel reads, so a run whose files
   were deleted reads unavailable rather than available-but-failing.
4. **Queueing is one attempt on an existing run, never a re-simulation**, and the button is disabled while an attempt
   is queued or running, so a second click cannot create a second attempt that the reader did not ask for. Cancel is
   the existing `POST /api/jobs/<jid>/analyses/<task>/cancel` (`runs.js:180`).
5. **Only kinds that take no payload get a bare button.** `carbohydrate-validation` requires `molecule_id`, a mapping
   snapshot and a target dataset (`routes/analyses.py:132-141`) and `snapshots` takes a cadence
   (`routes/analyses.py:142-155`); each keeps its own affordance, because a button that cannot name its own arguments
   is a button that fails in the worker.
6. **A published report is opened through the route that already reads it** — `dihedral-fit` and `bonded-cross-check`
   have readers, the rest are found by their own report path in the artifact index. Numbers are not re-rendered here:
   the Mapping Validation panel is where a report is read, and a second rendering of the same numbers is a second
   thing to keep in step.
7. **An attempt row states what the payload actually holds.** The jobs list sends an analysis row's `status`,
   `outputs`, `started_at` and `ended_at` and nothing else — no `progress` and no `error`. The run card's attempt line
   reads `task.progress || task.error` (`runs.js:177`) and therefore always renders the empty string after the status.
   The control shows the status and the duration the two timestamps give, and the card's line is corrected in the same
   pass. A failed attempt's own words are in its console artifact, not in this payload; the row links there.
8. **The list of kinds is one list, owned by the server.** `analysis/kinds.py` holds each kind's label, declared
   inputs and whether it runs for every run. The UI must not keep a second copy of that table, so the control needs one
   read endpoint (below). The draft hardcodes the three kinds and says so in its own banner.

## The one backend change

    GET /api/analysis-kinds
      → 200 {"kinds": [
             {"name": "dihedral-fit",
              "label": "Dihedral terms \u00b7 a criterion against the tool default",
              "inputs": ["2_mapping/mapped.gro", "2_mapping/mapped.xtc", "2_mapping/model.json",
                         "3_initial_CG/*_ff_inter.itp", "3_initial_CG/*initial*.itp"],
              "payload": null,                    # or a list of the keys the route requires
              "runs_for_every_run": false,
              "summary": "For every proper dihedral the topology declares ..."}]}

One endpoint, no writes, and it is the same table the coordinator queues from — so a kind added to `kinds.py` appears
in the control without a second edit. Everything else reuses routes that exist.

## What this control will not do

**It will not apply what a fit returns.** That is the step the E3 maltose question actually ends at, and it has no
dashboard path at all: the harmonics would have to be written into `stages/3_initial_CG/bonded_fit.json` under
`torsions` or `manual_overrides`, which `models/bonded/__init__.py:278-302` reads and applies to the topology, and then
the run re-queued. Editing `4_CG_sim/LIG1.itp` after the fact changes nothing — it is a run-time copy. The control
therefore ends at the numbers and links the report; applying them is the next piece of work, and it needs its own
decision about the constraint convention, because whether a fitted term becomes a rigid `[ constraints ]` row or a
spring depends on the run's `-constraints` threshold (this repository passes 10000; shaker's default is 25000).

## Ordered steps

1. `GET /api/analysis-kinds` over `analysis/kinds.py`'s table, with a unit test that fails if a kind's declared inputs
   are amended in one place only.
2. The card's *Available here* list in `runs.js`, rendering straight from that endpoint: label, the declared inputs
   with a present/absent mark read from the artifact index, and one Queue button per kind.
3. The disabled state with the missing input named, and the disabled state while an attempt is live, next to the
   existing attempt rows.
4. The report link per kind: the reader route where one exists, the artifact path otherwise.
5. Re-point the draft's own assertions into `test_runs_browser.py` (the card's file), then delete
   `static/analyses-draft.html` and `tests/dashboard/browser/test_analyses_draft_browser.py` together.

## Tests

* The draft's test drives the real draft against a planted completed run and **stubs the queue route**, so no test in
  any tier queues a real analysis: BARTENDER is minutes of CPU and `dihedral-fit` is uncounted. What is asserted is
  the request the control would make — method, path and body — not the attempt it would leave behind.
* The unavailable state is proved on a run that genuinely lacks an input, in the path's own words, so the sentence the
  reader sees is the sentence in the assertion.
* The absent-status case (a run that is not completed) is asserted as *absent*, not as disabled, because rule 1 makes
  the list not render at all rather than render something that cannot be used.

## Note for whoever wires it

A kind's reader and its queue route share one path — `GET /api/jobs/<jid>/dihedral-fit` reads the published report and
`POST` to the same path queues the analysis. The draft reads the GET on every render to decide whether to offer the
report link, which is correct but is one request per kind per render; batching it behind the proposed
`GET /api/analysis-kinds` (which can carry each kind's published state) is the tidier shape if the list grows.

## Open

* Does the run card or the Run view's monitor own the control long term? The card is proposed because action belongs
  where a run is listed; if the monitor gets it too, it should call the same module rather than re-implement the list.
* `bartender-fit`'s declared AA-reference input does not match this workspace's layout. Fixing it is a one-line change
  to the kind's inputs, but it changes what the kind can be queued against, so it wants its own review.
