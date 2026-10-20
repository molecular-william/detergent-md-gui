# Producing a CG parameterization, and consuming one

**Status: design for judgement.** Base draft: `docs/design/prototypes/parameterization-and-new-run.html`. This
supersedes the bonded half of `docs/design/prototypes/new-run-prototype.html`, whose step 04 already said *"Use CG Bond
Interactions to fit without simulating"* — the implementation went the other way (a run-level choice), and the
refactor now in flight removed that choice without giving the capability a home. This record gives it one.

## The model

A **parameterized CG molecule** is a mapping plus its bonded terms plus the provenance of those terms. It is not a run:
no MD, so it does not belong in Runs. It is produced in **CG Bond Interactions**, from a linked AA reference, and a
later AA–CG run consumes it.

    mapping (beads, rings, connections, exclusions, bead types)     ← the CG Bead Assignment panel
      └─ parameterization: bonds, angles, dihedrals, constraints    ← this panel
           · fitted by which engine, on which ensemble
           · with which options (-constraints threshold, torsion model)
           · against which AA reference (run id + hash)
           · checked by which re-derivations, with their numbers
      saved as revisions of the mapping, one of them current
    a run consumes the mapping and its current revision, and never re-fits a parameterized model

The pieces of that already exist in the tree and are worth naming, because this design assembles rather than invents:

* a mapping already carries `bonded_options` and `bonded_overrides` (`models/mappings/store.py:87`,
  `models/mappings/graph.py:74`) — the parameterization's home is already there;
* the panel already saves the torsion model **to the mapping** ("Save to mapping"), which is the grain this design
  follows;
* `/api/bonded-states` (GET/POST), `/api/bonded-states/automatic` (POST), `/<state_id>` (GET/PATCH/DELETE) and
  `/<state_id>/interactions` (GET) already exist in `web/routes/bonded.py`;
* `ff_inter` (Fast-Forward) fits from `2_mapping/mapped.{gro,xtc}` — which the mapper `sugar_mapping.py` produces from
  an AA reference in minutes of CPU and **no MD** (`execution/scripts/map_trajectory.sh`);
* `bartender_fit.py` already drives BARTENDER with `-refit -owntraj` and its sections
  (`bonds, constraints, angles, dihedrals`);
* `models/bonded.refine()` already re-fits declared torsions from `*_dihedrals.dat` when
  `bonded_options.torsion_model == 'circular-harmonic'`, refusing a broad torsion (`abs(mean) < 0.1`) rather than
  forcing one;
* `dihedral-fit` and `bonded-cross-check` declare inputs in stages 2 and 3 only, so both can run **before any CG MD**.

## Decisions

**D1 — The parameterization belongs to the mapping, and bonded states become its revisions.** A run consumes a
*model*, not a state id: there is no bonded-parameters control on the run panel, and its absence is the point. The
current revision is what a reader and a run read; older ones stay as history. Reversal cost: reintroduce a run-level
state select and give states an identity independent of their mapping.
*This is the biggest structural decision here.* Today "Bonded state" is a separate record selected beside a mapping;
under D1 the mapping's own revision line is the thing.

**D2 — Producing a parameterization is a job of this panel, not a run.** Its inputs are (mapping, AA reference, engine,
options); its outputs are the fitted terms, the diagnostics, the fit's provenance and the checks. It runs with status
and can be cancelled, and it is listed in the panel — not in Runs. Reversal cost: none, the alternative (a run type
that stops after stage 3) is rejected.

**D3 — Three engines, each saying which ensemble it saw.**
*Reference-informed automatic* (`/api/bonded-states/automatic`) — bead-type families with geometry as the fallback, no
AA frames, instant; its diagnostics name every fallback. *Fast-Forward* — `ff_inter` on the **mapped** AA trajectory,
with the `-constraints` threshold recorded, because that threshold decides whether a fitted pair becomes a constraint
or a spring. *BARTENDER* — `-refit -owntraj` against **our mapped trajectory**, not its own GFN sampling; the panel
must state the ensemble because the same command takes 40 s against one input and 400 s against another, and a number
without its ensemble is not a measurement. Reversal cost: per engine, a dropped control.

**D4 — The AA reference is linked, not implied.** A picker over completed AA-only runs (the same list the run panel
uses), recorded with the model, and the default a later run inherits. A model whose reference is gone says so rather
than silently fitting against nothing. Reversal cost: drop the field and the run's default.

**D5 — The run panel's bonded step becomes read-only provenance**, with two honest states: *"this model is
parameterized — fitted with Fast-Forward against a54ac8f64710, revision 3, hash …, torsion model circular-harmonic"*
and the run promises to use it and not re-fit; or *"this model carries no parameterization — the run will fit it in
stage 3 and record that it did"*. The choice of fit-or-reuse is a property of the model, not of the run. Reversal
cost: restore a run-level choice, which is what the old prototype had.

**D6 — The checks belong to producing a parameterization.** `dihedral-fit` and `bonded-cross-check` need no CG
trajectory, so the panel runs them as part of the job and shows their numbers beside the terms they question. The same
two run as analyses of an AA–CG run, so the numbers are visible from either end. Reversal cost: keep them run-only.

**D7 — The manual interaction editor and the state name do not survive D1; the read-only constraints and
virtual-site parents do.** *Recorded deviation from `:108-110`, which says all four stay.* What stays: the 3D diagram,
and the two kinds no engine fits — the table states a constraint's own length and a virtual site's parents, marks both
read-only, and the `source` column names the mapping as theirs. What does not stay, and why:

* **A revision has no name to edit.** `### Stored fields` is what a revision is, and a name is not among them. D1
  replaced the flat, named bonded state with a numbered revision of the mapping; the approved prototype's strip is
  numbered (`1 ✓ · 2 ✓ · 3 current`) and strikes the state picker out on purpose. A name field would be a second
  identity beside `revision`, which is exactly what D1 removed.
* **No route stores an edit.** The six routes above are this slice's whole contract, and none writes a revision's
  terms: `parameterization.save` sits behind the fit job, and the record `PATCH` takes `current` only. The old editor
  wrote `/api/bonded-states`, which is a *different store* — a state is not a revision — so a Save there would report
  success and leave the strip and the table unchanged, which is the control that cannot act this repository's panels
  are not allowed to have. It is a deviation, not a preference: the capability has no home in the API this slice
  approved.

Restoration cost: one route (`POST /api/bonded-parameterizations/<content_hash>/revisions` over
`parameterization.save`, which already computes `sources`), the old editor and name field back beside it, and `name`
added to the revision's stored fields. Reversal cost of this entry: one route and one field, which is why the deletion
is written down here rather than designed around.

*Sign-off: requested from the owner, not given here — this entry states the deviation and its reason so the owner can
either accept it or take the restoration above. `dashboard/web/static/js/bonded.js` and the Interactions card point at
this entry rather than restating the argument.*

## What the panel looks like

    CG BOND INTERACTIONS                                            [ … ]
    ┌ Model ────────────────────────────────────────────────────────────────────────┐
    │ Mapping      [ DDM · ring mapping          ▾ ]   beads 11 · 9 physical · 2 VS  │
    │ AA reference [ DDM · AA reference A · 10 ns ▾ ]  300 K · 10 ns · hash example A │
    │ Parameter    [ Fast-Forward fit ▾ ]  ▢ circular-harmonic torsions   scale [1.0] │
    │              thresholds recorded: -constraints 10000 · temperature 300 K        │
    │              [ Fit this model ]   builds the mapped trajectory first (minutes,  │
    │                                    no MD), then fits                            │
    └────────────────────────────────────────────────────────────────────────────────┘
    ┌ Job ──────────────────────────────────────────────────────────────────────────┐
    │ fitting 2/4 · mapping frames 3.0 MB · ff_inter: distances, angles, dihedrals    │
    │ [ Cancel ]                                                    started 14:31:02 │
    └────────────────────────────────────────────────────────────────────────────────┘
    ┌ Result · revision 3 (current) ─────────────────────────────────────────────────┐
    │ 34 terms · 6 constraints · torsion model circular-harmonic · fitted from         │
    │ mapped AA frames (20 001) against a54ac8f64710                                  │
    │ checks: dihedral-fit — 1 declared torsion, criterion k 9.03 vs fitted 36.64      │
    │         bonded-cross-check — 12 terms, 2 written as constraints here, springs    │
    │         there                                                                     │
    │ [ Save as revision ]  [ Compare with revision 2 ]  [ Open the checks … ]         │
    └────────────────────────────────────────────────────────────────────────────────┘
    ┌ Interactions ────────────────────────────┐ ┌ Molecular connectivity ──────────┐
    │ kind · beads · function · params · source │ │  the existing 3D bead diagram    │
    │ (the existing table, with a `source`      │ │  (selection drives the editor)    │
    │  column: reference | ff_inter | bartender │ │                                  │
    │  | manual)                                │ │                                  │
    └───────────────────────────────────────────┘ └──────────────────────────────────┘
    Revisions of this mapping:  1 ✓  ·  2 ✓  ·  3 current  ·  4 draft

What changed from today's panel: the AA-reference picker, the engine select with its options and cost, the job box,
the result box with provenance and the checks' numbers, a `source` column in the interactions table, and the revision
strip at the bottom. The 3D diagram, the manual interaction editor, the state name, and the read-only constraints and
virtual-site parents all stay as they are — except the editor and the state name, which the panel was built without;
D7 records that deviation, its reason and what would restore them.

## What the run panel looks like

    NEW RUN · AA–CG
    01 · MOLECULE          [ Maltose ▾ ]            molecules/Maltose · 45 atoms
    02 · CG MODEL          [ Maltose · E3 mapping ▾ ]
                           parameterization  revision 3 · Fast-Forward · 34 terms
                           AA reference      a54ac8f64710 · 300 K · 10 ns
                           torsion model     circular-harmonic, scale 1.0
                           [ Open in CG Bond Interactions ]    [ Re-parameterize… ]
    03 · STAGE SETTINGS    durations, temperature, seeds, mdrun flags — the numbers this
                           run uses (defaults from the profile, editable, one Default
                           button each)
    ─────────────────────────────────────────────────────────────────────────────────
    Run summary   Model     Maltose · E3 mapping · revision 3
                  AA source a54ac8f64710 (from the model)
                  Bonded    used as-is · this run does not re-fit
                  Stages    1 AA reference (reused) → 2 mapping → 3 CG parameterization
                            (rings, model's topology, checks) → 4 CG simulation →
                            5 assessment → 6 SASA
                  [ Launch AA–CG run ]

and, when the model carries no parameterization:

    Bonded    this model is not parameterized — stage 3 will fit it and record that it did
              [ Parameterize first in CG Bond Interactions… ]   (optional, not required)

Gone, and gone on purpose: *Execution* (a duration preset wearing a pipeline name), *Bonded parameters* and *Bonded
workflow* (a per-run choice of something the model now owns). `02 · CG MODEL` replaces the old *CG mapping* select,
because what a run consumes is a mapping **with** its parameterization.

## Questions to judge

1. **The fallback (D5):** a model with no parameterization — the run fits it (my recommendation, it keeps your rule
   that every AA–CG run produces a parameterized molecule) or refuses and sends you to the panel? Say which; it is one
   branch either way.
2. **BARTENDER's own sampling (D3):** offer only `-refit -owntraj` against our mapped trajectory (my recommendation,
   and the repository's own position — it measures against our AA reference, not against BARTENDER's GFN sampling), or
   also let it generate its own samples for a molecule you have never simulated?
3. **D1's structural change:** states become revisions of the mapping. Do you want the old flat "Bonded state" list
   kept as a way to compare two arbitrary revisions, or is a revision strip on one mapping enough?
4. **Where the job is visible:** the panel only (my recommendation), or a line in Runs' activity as well?

## API

**Built and reviewed.** The backend landed in `44f8cc7`; the six routes, the panel (model card, Fit, job box,
result card, `source` column, revision strip) and the `02 · CG MODEL` card landed in `89e3e2c`. Four reviewers then ran
spec-then-quality over each workstream, and their findings were fixed before this line was written: an unfiltered
jobs answer for a mapping with no record, a duplicated job filter, three controls deleted against the spec, a
`fit()` post-await race, a fabricated `source` fallback, a wrong-mapping link, and stale state painted under a new
mapping's name. Deleting a saved mapping now takes its parameterizations with it unless another saved mapping
carries the same content hash. The two refactor findings are closed (`states.py`'s retired-key read is commented,
the retention fixtures key on what the cleanup reads).

## API

**What remains after this slice.** Nothing: the panel landed in `89e3e2c` (model card, fit job and cancel, result
card, `source` column, revision strip), and `02 · CG MODEL` on New Run shows which parameterization a run will use.
`4748261` carries the four reviewers' fixes. The two review findings named here were closed in `89e3e2c`:
`models/bonded/states.py:156` carries the line saying why it reads two retired keys, and the fixtures in
`test_temporary_validation_cleanup.py` key on what the cleanup reads.

**Status: built and tested.** `dashboard/models/bonded/parameterization.py` (the revision store),
`dashboard/models/bonded/fitting.py` (the job), `dashboard/execution/scripts/use_parameterization.{sh,py}` (stage 3
of a consuming run), the two stage-3/stage-5 shapes and the `prepare`/`readiness` additions in
`dashboard/execution/adapters/cg.py`, and `analysis.runs.bartender_fit.topology_from_fit`. The four tests that hold
it: `tests/dashboard/unit/test_bonded_parameterization.py`, `test_bonded_fitting.py`,
`test_cg_parameterization_consumption.py`, `tests/dashboard/integration/test_parameterization_flow.py`.

The routes are **not** in this slice — `dashboard/web/**` is the panel, coded against this. What follows is every
route it must add, the payload keys it sends, and the stored fields behind them.

### Routes the panel adds

| route | body the panel sends | answer | model call behind it |
| --- | --- | --- | --- |
| `POST /api/bonded-parameterizations` | `mapping` (the saved candidate snapshot, required), `engine` (required), `aa_reference` (12-hex AA-only run id; required — every engine left fits to an ensemble), `options` (optional, the four keys below), `molecule_root`, `timeout` | `201` and the job record | `fitting.start(mapping, engine=…, aa_reference=…, options=…, molecule_root=…, timeout=…)` |
| `GET /api/bonded-parameterizations?content_hash=&mapping_hash=` | — | `{summary, revisions, jobs}` where `summary` is `view(record)` and `revisions` is the whole history; with no hash, `{records}` (every stored record) | `parameterization.one/view/records/matches`, `fitting.jobs` |
| `GET /api/bonded-parameterizations/jobs?content_hash=` | — | `{jobs: [job record]}` newest first — a mapping's whole history | `fitting.jobs(content_hash=…)` |
| `GET /api/bonded-parameterizations/jobs?job_id=` | — | `{jobs: [that job] or []}`; the job box polls **this** while `status` is `queued` or `running`, because the id is the job it queued while the hash is a different question about a mapping | `fitting.jobs(job_id=…)` |
| `POST /api/bonded-parameterizations/jobs/<job_id>/cancel` | — | the job record with `status: cancelled` | `fitting.cancel(job_id)` |
| `PATCH /api/bonded-parameterizations/<content_hash>` | `current` (a revision number), `confirm: true` | the record, with that revision current | `parameterization.make_current` |
| `GET /api/bonded-parameterizations/engines` | — | `{engines: [{value, label, needs_reference}]}`, from `ENGINES`/`ENGINE_LABELS` | `parameterization.ENGINES`, `ENGINE_LABELS` |
| `GET /api/readiness` (existing) | — | gains the key `parameterization` (below) | `cg.PROTOCOL.readiness(metadata)` |

`READY` and `FAILED` for a job: `failed` carries `error` and `log_tail`; a run-side reader that finds
`manifest.bonded` (below) needs nothing from these routes.

### The fit job's request keys

`engine` is one of `fast-forward`, `bartender`. (A third, `reference-informed`, read the mapping alone and produced a
revision nobody had fitted; it and its panel button were removed 2026-10-20. `bonded.generation` and
`POST /api/bonded-states/automatic` remain — they build bonded states, not parameterizations.) `options` is any subset of
`constraints_threshold` (kJ/mol/nm², default 10000 — Fast_Forward's own default; above it a fitted pair becomes a
constraint), `temperature_k` (default 300), `torsion_model` (`legacy` | `circular-harmonic`, default: read off
`mapping.bonded_options`, D4a) and `torsion_scale` (0.1–3, only with `circular-harmonic`). `aa_reference` may carry a
resolved reference from the caller (`reference=`) instead, which is what the route should do after resolving it the
way every other AA-reference consumer does.

### Stored fields

**Record** — `workspace/parameterizations/records/<mapping content hash>.json`:
`mapping_hash`, `mapping_content_hash`, `revision` (the current number), `current` (the current revision), `revisions`
(oldest first), `updated_at`. Selected by **content** identity, so a renamed candidate keeps its revisions; the
candidate identity is recorded on every revision as provenance. `workspace/parameterizations/work/<content
hash>-<AA run id>/` holds the pair's mapped frames, engine output and checks; `.../jobs/<job_id>.json` and
`<job_id>.log` hold the jobs.

The content hash is `identity.candidate_identity`'s digest, and that function now hashes a number as its **value**:
`1` and `1.0` are the same number. It has to, because the panel reads the mapping as JSON, hands it to JavaScript and
posts it back, and JS has no integer type — a stored `1.0` returns as `1`. While the two spellings hashed differently,
one mapping had two identities (the file's and the posted snapshot's) and a fit was filed under a digest no saved
mapping addressed: the panel read "no parameterization" for a mapping it had just fitted, and its job poll, which asked
by the mapping's hash, found no job and sat on `queued`. Reads fall back to `identity.legacy_content_identity` for
records written before the change; nothing writes with it.

**Revision** — every field a run and a reader needs, all set by the store or the job:
`revision`, `created_at`, `mapping_hash`, `mapping_content_hash`, `engine`, `engine_command` (the invocation, when a
tool ran), `engine_default_source` (the `source` column's default for this engine), `engine_terms` (the engine's own
rows, which is how a geometry fallback is told from a reference value), `options{constraints_threshold,
temperature_k, torsion_model, torsion_scale}`, `temperature_source`, `ensemble{frames, trajectory, source}` —
`frames: null` means *this engine read no ensemble*, never `0` — `aa_reference{run_id, reference_sha256,
molecule_identity, temperature_k, production_ns} | null`, `topology` (the complete ITP), `terms{kind: count}`,
`sources[{id, kind, beads, source}]` (`reference` | `ff_inter` | `bartender` | `geometry` | `mapping` | `manual`;
computed by the store from the topology, the mapping and `engine_terms`, so it cannot disagree with the terms),
`refinement` (`bonded.refine`'s report, or null), `diagnostics`, `checks{dihedral-fit, bonded-cross-check}` (each a
published report, or `null`, or `{error}` — a check that could not run is a recorded fact and never a failed fit),
`notes[]`, `scientifically_validated` (always `false`; a caller cannot set it).

`parameterization.revision_sha256(revision)` is the digest of the stored fields minus `created_at`: it is what a run
records to name the exact terms it consumed.

**Job** — `id`, `status` (`queued` | `running` | `completed` | `failed` | `cancelled`), `mapping_name`, `molecule_id`,
`mapping_hash`, `mapping_content_hash`, `engine`, `options`, `aa_reference`, `reference_run_id`, `reference_sha256`,
`molecule_root`, `timeout`, `steps` (`('mapped frames', 'fit', 'checks', 'save')`), `step`, `completed_steps`,
`progress{done, total, detail}`, `work`, `log`, `created_at`, `started_at`, `ended_at`, `error`, `revision` (the
revision the job stored), `revision_sha256`, `cancelled_at`, `log_tail`, `scientifically_validated`.

### What the run side records

**`manifest.json` gains `bonded`** on every AA–CG run:
`consumes_parameterization` (bool), `fitted` (bool — its negation, spelled out because both are read),
`revision`, `engine`, `torsion_model`, `terms`, `revision_sha256`, `aa_reference`, `source` (one sentence). The stage
contract is resolved **from this field**, so the coordinator, a resume and a test all see the same plan the run was
prepared with; a run prepared before the field existed reads as a run that fitted, which is what it did.

**`readiness()['parameterization']`** is D5's read-only provenance for the panel:
`{parameterized, revision, engine, engine_label, terms, torsion_model, checks, aa_reference, revision_sha256,
statement}` — `statement` is the sentence the panel shows, either *"this model is parameterized — fitted with
Fast-Forward fit (ff_inter) against a54ac8f64710, revision 3, hash …, torsion model circular-harmonic; the run uses
it and does not re-fit"* or *"this model carries no parameterization — the run will fit it in stage 3 and record that
it did"*.

### What a consuming run stages, and what it writes

`3_initial_CG/parameterization.json` — the mapping's current revision, staged by `prepare`. The stage script becomes
`3_initial_CG/use_parameterization.sh` (with `use_parameterization.py` beside it), its declared outputs become
`('mapped.tpr', '{final_itp}', 'parameterization_used.json')`, and stage 5's declared inputs lose the two
`*_distr.dat` patterns — an atomistic reference distribution is a fit's output and this stage produced none, which
the run's own `limitations` says in words. The stage writes the model as `{final_itp}` and as
`{stem}_ff_inter.itp`, the name the two checks and the analysis layer's declared sources (`3_initial_CG/*_ff_inter.itp`)
are written against, and it writes `parameterization_used.json` — `{fitted: false, statement, revision, engine,
torsion_model, torsion_scale, constraints_threshold, temperature_k, ensemble, aa_reference, topology,
topology_sha256, revision_sha256, checks_published_with_the_revision, scientifically_validated}` — and deliberately
**not** `bonded_fit.json`: a stage that skips its fit must not leave the artefact a fitting stage leaves.

### Readings this slice had to choose

1. **BARTENDER's ensemble.** D3 says `-refit -owntraj` "against our mapped trajectory". Built as
   `analysis.runs.bartender_fit.run`, which hands BARTENDER *our AA reference's own trajectory read through our
   mapping's `.ndx`* — the repository's existing invocation, which is never its own GFN sampling. The revision records
   exactly that (`ensemble.source`, `ensemble.trajectory = 1_AA-reference/prod/lig.xtc`), so the number travels with
   what it measured. A reading that passed `2_mapping/mapped.xtc` to BARTENDER instead would need a different
   `bartender.inp` and could not be verified here without the tool.
2. **`{stem}_ff_inter.itp` for a model that was not fitted by `ff_inter`.** The two checks and the analysis layer's
   declared sources select that name (and only it, for a run), so a model under any other name leaves them reading the
   coordinate seed beside it. The name means *the fit's interaction topology*; the revision's `engine` says which tool
   fitted it, and `parameterization_used.json` says the run did not.
3. **The record is selected by content identity.** A rename keeps its revisions; a changed bead assignment does not.
   Same doctrine as `bonded.states.belongs_to`, and it matters here because a revision is what a run reads.

