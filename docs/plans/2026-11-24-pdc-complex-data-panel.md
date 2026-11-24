# Plan: a "PDC analysis" tab for protein-detergent runs — CG-only metrics from the two detergent papers

**Status: design agreed and the open items settled (2026-11-24); not implemented.** This document changes no code, registers no
kind, adds no route and edits no panel. It is the draft for review before the first edit.

It builds on `docs/plans/2026-11-09-pdc-analyses-definitions.md` (the definitions behind `pdc-structure`, the
planned `pdc-interaction-energy` and the optional `pdc-sdf`) and reuses that plan's vocabulary rather than inventing a
second one. The papers it takes its questions from are Lee et al., *JACS* 2016, 138, 15425 (short-chain detergents)
and Lee et al., *Biochemistry* 2020, 59, 2125 (branched detergents). Both are all-atom GROMOS studies; this panel is
for the Martini 3 coarse-grained runs, so only the structural/geometric claims transfer.

## 0. The decision in one paragraph

The pdc workspace gets one new tab, **PDC analysis**, which replaces the old **Complexes** tab (its build form and
system viewer are retired; New run builds, Run view shows the system). The tab shows, for one completed pdc run at a
time, the data the two papers' structural claims need: the existing `pdc-structure` measurements (micelle shape and
aggregation, RDFs, contacts) extended with **protein→tail RDF**, **protein–head and protein–tail contact groups** and
**water-bead contacts**; the run's existing `trajectory-overview` supplies **RMSD/RMSF/Rg/energy**. The producer
publishes PNG figures; the tab is a reader with tables and JSON/CSV downloads. It draws no conclusion, no
mild/harsh label, no pass/fail and no trend; the reader interprets. Thresholds are shown and tunable. Nothing is
computed automatically; a Compute button queues the analysis on a completed run.

## 1. Settled decisions (the grilling record)

| Question | Decision |
| --- | --- |
| Purpose | Data, not conclusions. The reader interprets. No verdict, no validation claim. |
| System class | **CG (Martini 3) only.** AA-only metrics are out; alpha-helicity and hydrogen bonds are not computed at all. |
| Runs | **Completed pdc runs only.** The analysis coordinator already refuses a running run. |
| Trend | **None.** No cross-run overlay, no slope/trend language. The per-frame series is data and stays in the JSON/CSV and the PNGs. |
| Placement | **Replace the Complexes tab.** The tab's internal panel id stays `complexes`; the visible label becomes **PDC analysis**. The New run tab is the build path; the Run view's structure is the system view. |
| Complexes retirement | Retire the build form, the system viewer and the old browser tests; remove `/api/pdc/<job>/system.pdb`. |
| Analysis home | Extend **`pdc-structure`** with the missing metrics. No second all-in-one kind; no duplicate RDF/contact/shape implementation. |
| Reuse | `pdc-structure`'s leg/sample/RDF/contacts/shape/aggregation; the run's `trajectory-overview` for RMSD/RMSF/Rg/energy; the run's recorded `tail_beads`. |
| New metrics | protein→tail RDF; protein–head and protein–tail contacts; water–head and water–tail bead contacts. |
| Thresholds | Tunable payload fields; defaults from the run and the existing constants; recorded in the report. |
| RMSD/RMSF/energy | Read the newest `trajectory-overview` record; do not recompute or duplicate it in `pdc-structure`. |
| Output | Separate PNGs per plotted metric (RDF, protein contacts, water contacts, shape, aggregation) published by the producer, plus the overview's own PNG; tables in the tab; JSON/CSV downloads. |
| Sampling | The existing convention: latest playable production leg, ≤ 200 frames, `stride = ceil(frames/200)`. Production only. |
| Compute | **Compute structure** queues `pdc-structure`; **Compute overview** queues `trajectory-overview` when it is missing. Both are cached ordinary attempts; the overview is readable in the Run view's Analysis card too. No automatic analysis. |

**Out of scope for v1:** alpha-helicity, hydrogen bonds, the all-atom hydration number, `pdc-interaction-energy`,
`pdc-sdf`, detergent mobility/residence times, cross-run overlays, trend/slope summaries, thresholds or pass/fail,
automatic analysis on run completion, and any new AA simulation.

## 2. What already exists, and what is reused

| Piece | Where | What this plan does with it |
| --- | --- | --- |
| `pdc-structure` producer | `packages/pdc/src/detergent_pdc/analysis/runs/structure.py` | Extend with the three metrics, the thresholds, the report v2 and the PNGs. |
| Its kind row | `packages/pdc/src/detergent_pdc/kinds.py` | Keep the kind; add the payload validator through the feature if the thresholds need a queue-time 400. |
| Its read route | `packages/pdc/src/detergent_pdc/web/routes/pdc.py` | Keep `/api/jobs/<id>/pdc-structure`; add the figure paths to its answer. |
| The Run view section | `packages/pdc/src/detergent_pdc/static/js/run-view-pdc-analysis.js` | Keep as the in-context quick view. It reads the old keys; the new fields add a protein→tail first-peak card without a change. |
| `trajectory-overview` | `packages/core/src/dashboard/analysis/runs/trajectory_overview.py` | Read its newest record; do not recompute. `NG_2ydo` already has one (199 frames). |
| The run's `tail_beads` | `inputs/pdc-settings.json`, read by `pdc_assessment` | Reuse; head is "not tail" (`structure.py:321-326`); no new classification. |
| The production-leg resolver | `structure._leg`, `pdc_segments`, `layout` | Reuse; no new leg rule. |
| The sample and GROMACS tools | `gmx trjconv`, `gyrate`, `rdf`, `select`/`mindist` | Reuse; one extracted sample read by every tool. |
| The pdc feature's tab surface | `packages/pdc/src/detergent_pdc/feature.py` | Replace the panel module/template/label; keep the `complexes` id and the `pdcSetRun` hook. |

Measured facts behind the cost estimates (2026-11-23/24, read-only, on this host): `NG_2ydo` is 54,278 atoms,
20,001 frames at 25 ps, `whole.xtc` 5.9 GB; `gmx trjconv -skip 100` extracted the 200-frame sample in ~72 s;
`gmx rdf` ~8 s; `gmx mindist -on` ~6 s; MDAnalysis pair work ~5 s over 200 frames. The live producer check on
`DM_2ydo_144_libconf_500ns` (schema 2, five figures) took **4.5 min** end to end on 2026-11-24, against the earlier
~1.5–2 min estimate; the measured number is the one to quote.

## 3. The producer: `pdc-structure` schema v2

### 3.1 The leg and the sample (unchanged)

- The latest playable production leg of the run's own segmenter: extension when it ran, else assessment. No
  equilibration leg, no other trajectory. A run with the extension skipped records the assessment leg and the
  manifest's own `fallback_reason`; the report and the tab say so.
- At most 200 frames, `stride = max(1, ceil(frames_in_file / 200))`, one `gmx trjconv` sample read by every tool.
  The frame count and span come from `trajectory_header.read`, never by walking the file.
- The `NG_2ydo` run's extension stage is skipped, so its production leg is the CG assessment's; the manifest's own
  reason is carried. The tab must show the fallback sentence, not present the assessment leg as an extension leg.

### 3.2 The metrics (definitions)

**RDFs (`gmx rdf`, `-norm rdf`).** All four pairs on the extracted sample:

| first | second | `-ref` | `-sel` | `-excl` |
| --- | --- | --- | --- | --- |
| protein | head | protein selection | detergent and not tail | no |
| protein | **tail** (new) | protein selection | detergent and tail | no |
| head | head | head | head | yes |
| tail | tail | tail | tail | yes |

The protein selection is the existing one: everything that is not the detergent residue and not a solvent residue
(`W`, ions). Head is the run's detergent beads that are not `tail_beads`; tail is the recorded `tail_beads`. The bin
width and `r_max` are thresholds (§3.3); `r_max` is cut to half the shortest box edge, and the report records the
effective value.

**Contact groups (`gmx mindist -on`, minimum image, one contact per bead pair — never called a hydrogen bond).**

| first | second | cutoff | why |
| --- | --- | --- | --- |
| protein | head | `contact_nm` | the paper's head-facing interface |
| protein | tail | `contact_nm` | the paper's tail-facing interface |
| water (`W` only) | head | `water_cutoff_nm` | water-bead coordination near the head |
| water (`W` only) | tail | `water_cutoff_nm` | water-bead coordination near the tail |

The existing pooled `contacts` object (protein vs all detergent) stays for the Run view section and backward
compatibility. The new groups are the data the tab reads. Ions (`ION`) are not water; they stay out of the water
groups.

**Water-bead contacts.** The water–head and water–tail counts are a **bead coordination count**, not the all-atom
hydration number: the papers' "5 Å of water" is an atomistic number, and a Martini W bead represents several waters.
The report's `definition` says exactly that, and the tab's copy must not call it "hydration number".

**Shape and aggregation.** Reused unchanged: `gmx gyrate` Rg, the numpy gyration-tensor shape numbers, the run's
own micelle criterion (`pdc_assessment.assess_micelle`) for membership and aggregation.

**RMSD/RMSF/Rg/energy.** Read from the run's newest `trajectory-overview` record; the tab shows the record's summary
values and links its PNG. Nothing is recomputed in `pdc-structure`; a run without an overview says "not computed" and offers
**Compute overview** (the core kind caches it; the same record is readable in the Run view).

**Not computed on Martini:** alpha-helicity (no backbone torsions; no `mkdssp` binary) and hydrogen bonds (`gmx hbond`
refuses a Martini topology). The report says so in its caveats where relevant.

### 3.3 Thresholds

Payload fields, validated at queue time and recorded in the report's `thresholds` block:

| key | default | allowed | applies to |
| --- | --- | --- | --- |
| `rdf_bin_nm` | `0.05` | 0.01–0.20 | RDF bins |
| `rdf_rmax_nm` | `2.0` | 0.5–4.0, then cut to ½ the shortest box edge | RDF range |
| `contact_nm` | the run's own `settings.contact_nm` (0.6 on `NG_2ydo`) | 0.2–1.5 | protein–head / protein–tail |
| `water_cutoff_nm` | `0.6` | 0.2–1.5 | water–head / water–tail |

The micelle criterion's `contact_nm` is the run's own and is **not** changed by the measurement threshold; the
report keeps `micelle.contact_nm` and the contact groups' own `cutoff_nm` distinct. A blank field means the default.
The effective values are recorded and shown. Changing any threshold is a new attempt (the kind identity includes the
payload).

### 3.4 Report schema v2

Every field is measured or is the method/sampling/caveat record the repository requires beside a number. The v1 keys
are retained; the additions are backward-compatible for the Run view section and any old record.

```json
{
  "kind": "pdc-structure",
  "schema_version": 2,
  "leg": {"name": "...", "stage_directory": "...", "trajectory": "...", "structure": "...",
           "chosen_by": "...", "fallback_reason": null},
  "sampling": {"frames_in_file": 0, "frames_sampled": 0, "stride": 0, "first_ns": 0.0, "last_ns": 0.0,
                "span_ns": 0.0, "frame_dt_ps": 0.0, "read": "..."},
  "thresholds": {"rdf_bin_nm": 0.05, "rdf_rmax_nm": 2.0, "contact_nm": 0.6, "water_cutoff_nm": 0.6},
  "micelle": {"definition": "...", "contact_nm": 0.6, "aggregation_number_requested": 0,
               "tail_beads": ["TAIL1", "TAIL2", "TAIL3"], "detergent_residue": "NG"},
  "shape_nm": {"rg": {"tool": "gmx gyrate", "weighting": "mass", "mean": 0.0, "sem": 0.0, "series": []},
                "gyration_eigenvalues_nm2": {"mean": [0.0, 0.0, 0.0]},
                "asphericity": {"mean": 0.0, "sem": 0.0},
                "relative_shape_anisotropy": {"mean": 0.0, "sem": 0.0},
                "subject": "detergent micelle"},
  "aggregation": {"largest_mean": 0.0, "cluster_count_mean": 0.0, "free_mean": 0.0,
                   "size_distribution": {"bins": [], "counts": []}},
  "rdf": [
    {"tool": "gmx rdf", "first": "protein", "second": "head", "r_nm": [], "g": [], "norm": "rdf",
     "excl": false, "normalization": "gmx rdf -norm rdf (bulk density per selection)",
     "bin_width_nm": 0.05, "r_max_nm": 2.0, "first_peak_nm": 0.0, "first_peak_g": 0.0},
    {"tool": "gmx rdf", "first": "protein", "second": "tail", "...": "same shape"},
    {"tool": "gmx rdf", "first": "head", "second": "head", "...": "same shape"},
    {"tool": "gmx rdf", "first": "tail", "second": "tail", "...": "same shape"}
  ],
  "contacts": {
    "definition": "beads of the second selection within r of the first, minimum image; not hydrogen bonds",
    "tool": "gmx mindist -on", "group": false,
    "cutoff_nm": 0.6, "mean": 0.0, "sem": 0.0,
    "series": {"time_ns": [], "contacts": []},
    "groups": [
      {"first": "protein", "second": "head", "cutoff_nm": 0.6, "mean": 0.0, "sem": 0.0,
       "series": {"time_ns": [], "contacts": []}, "definition": "bead pairs, not H-bonds"},
      {"first": "protein", "second": "tail", "cutoff_nm": 0.6, "...": "same shape"},
      {"first": "water", "second": "head", "cutoff_nm": 0.6, "...": "same shape",
       "definition": "W beads within r of head beads; a bead count, not an all-atom hydration number"},
      {"first": "water", "second": "tail", "cutoff_nm": 0.6, "...": "same shape"}
    ]
  },
  "figures": ["pdc-structure-rdf.png", "pdc-structure-contacts-protein.png", "pdc-structure-contacts-water.png", "pdc-structure-shape.png", "pdc-structure-aggregation.png"],
  "method": "prose: one bounded sample of one production leg; gmx gyrate / rdf / mindist; the run's own micelle criterion",
  "caveats": ["..."],
  "scientifically_validated": false,
  "protein_present": true
}
```

The `result.json` names the per-metric PNGs in `files` (and can keep a `figure` key for the existing index); the worker
publishes every file the producer leaves in the attempt directory. The `pdc-structure` route adds the figure paths
derived from `source` (the record's own attempt output directory), so the tab does not have to guess a sibling path.

### 3.5 Figures

One PNG per plotted metric, matplotlib `Agg` (`MPLBACKEND=Agg` is already in the analysis environment), in the
style of `trajectory_overview`'s `_figure`:

- `pdc-structure-rdf.png` — the four `g` curves on one axis (protein→head, protein→tail, head–head, tail–tail),
  with the first peaks marked; a legend names each pair.
- `pdc-structure-contacts-protein.png` — protein–head and protein–tail per-frame counts.
- `pdc-structure-contacts-water.png` — water–head and water–tail per-frame counts.
- `pdc-structure-shape.png` — Rg and the shape numbers over the sampled frames.
- `pdc-structure-aggregation.png` — largest cluster and free detergents per frame.
- The overview's `trajectory-overview.png` is the core kind's own; the tab shows it, the producer does not redraw it.

The time axis is the sampled frames' own nanoseconds. The figures carry the sample size and the cutoff in their
titles or a footnote. No fit, slope or trend annotation.

## 4. The panel: "PDC analysis"

### 4.1 Replacement and retirement

- The pdc workspace's fourth tab keeps the **`complexes` panel id** and the tab id; the visible label changes from
  "Complexes" to **"PDC analysis"** (settled). Keeping the id preserves `?run=` links, `window.pdcSetRun`, and the
  engine's `main.js` hook (`panels.complexes`), which need no change.
- The new panel module is `js/pdc-analysis.js` (`createPdcAnalysis`); the template is the existing
  `templates/panels/pdc.html` (its `#pdc` section replaced); the stylesheet is `pdc.css` (dead panel classes removed).
- **Retired:** the old build form (protein/template/mapping/Queue the build) and the old system viewer (`#pdc-viewer`,
  NGL, bead radii, bonds, import). The New run tab is the build path; the Run view's structure card is the system
  view. The old panel's browser tests are retired.
- **Kept:** the shared endpoints the New run form still uses (`/api/pdc/catalog`, `/api/pdc/models`,
  `/api/pdc/proteins/import`, `/api/pdc/conformations/*`, `/api/pdc/proteins/<entry>/*`). The dead
  `/api/pdc/<job>/system.pdb` route is removed with the panel, after a grep for consumers.
- **Kept:** the Run view section `run-view-pdc-analysis.js` (the quick view). It reads `pdc-structure`; the new
  protein→tail RDF appears in its first-peak cards through the existing generic `rdfLabel` without a change.

### 4.2 Layout and states

The tab is one card:

- **Run** select (completed pdc runs; `?run=<id>` opens one), **Compute structure**, and **Compute overview**
  (shown when the overview is missing).
- An **Options** disclosure with the four thresholds; blank means the server default; the effective values are shown
  after a build. Changing an option and pressing Compute is a new attempt.
- A **data** region with:
  - the leg/sample line and the `scientifically_validated: false` / method / caveats;
  - **Micelle**: Rg, asphericity, anisotropy, largest cluster, free detergents, clusters; the separate
    `pdc-structure-shape.png` and `pdc-structure-aggregation.png`;
  - **RDF**: the `pdc-structure-rdf.png`; a table of first peaks (protein→head, protein→tail, head–head, tail–tail);
  - **Contacts**: the `pdc-structure-contacts-protein.png` and `pdc-structure-contacts-water.png`; a table of the
    four groups' mean ± SEM and cutoff;
  - **RMSD/RMSF/Rg/energy**: the `trajectory-overview` summary table and its PNG; when missing, "not computed" and
    **Compute overview** (queues the core kind; the cached attempt is readable in the Run view's Analysis card);
  - **Downloads**: the `pdc-structure.json`, a CSV of the tables/series, and links to the PNGs.
- **States**: no run selected; selected run not completed; no `pdc-structure` record ("Nothing computed yet" +
  Compute); a running attempt; a published v1 record (the new metrics "not measured" + Compute); a published v2;
  no `trajectory-overview` (the overview block says "not computed" and offers **Compute overview**); no protein
  (the protein–detergent groups are `null`, the tab says why); the fallback assessment leg (the manifest's
  sentence, and "not comparable with an extension leg").
- **No** verdict, no mild/harsh label, no pass/fail, no cross-run overlay, no trend/slope language.

### 4.3 Data sources and flow

| Step | Endpoint | Notes |
| --- | --- | --- |
| Run list | `GET /api/jobs?limit=100` | filter `run_type === 'pdc'` and `status === 'completed'` |
| Record | `GET /api/jobs/<id>/pdc-structure` | 404 = never computed; the answer includes `attempt`, `published_at`, `source`, and the figure paths |
| Overview | `GET /api/jobs/<id>/analyses?view=summary` | find the newest completed `trajectory-overview`; read its JSON and PNG through `GET /api/jobs/<id>/artifacts/<path>?inline=1` |
| Compute structure | `POST /api/jobs/<id>/pdc-structure` | body = the four thresholds (or `{}` for the defaults); the generic queue route |
| Compute overview | `POST /api/jobs/<id>/trajectory-overview` | when the overview is missing; the core kind caches its attempt; the Run view's Analysis card reads the same record |
| Poll | `GET /api/jobs/<id>/analyses?view=summary` | until the attempt settles; then refetch the record |
| Figures | `GET /api/jobs/<id>/artifacts/<path>?inline=1` | the PNG paths from the record/route |

The tab has two buttons: **Compute structure** queues `pdc-structure`; **Compute overview** queues the core
`trajectory-overview` when it is missing. Both write ordinary analysis attempts. The overview's attempt is cached on
the run and is read by the Run view's Analysis card as well as this tab; the tab shows "not computed" only until that
attempt exists.

The `setRun` hook: the new panel's `setRun(id)` selects the run in the picker and loads it, so the engine's
`window.pdcSetRun` (used by the Run view and the browser tests) keeps working.

## 5. Files and tests

| File | Change |
| --- | --- |
| `packages/pdc/src/detergent_pdc/analysis/runs/structure.py` | add the protein→tail RDF, the contact groups, the water contacts, the thresholds, the report v2, the per-metric PNGs |
| `packages/pdc/src/detergent_pdc/kinds.py` | keep the kind; the payload contract if the validator lives here |
| `packages/pdc/src/detergent_pdc/feature.py` | `panel_modules` -> `js/pdc-analysis.js`; label "PDC analysis"; the `kind_payload` validator for the thresholds |
| `packages/pdc/src/detergent_pdc/templates/panels/pdc.html` | replace the old build/viewer markup with the new tab |
| `packages/pdc/src/detergent_pdc/static/js/pdc.js` | **removed**; its build/viewer functions are retired |
| `packages/pdc/src/detergent_pdc/static/js/pdc-analysis.js` | **new**; run picker, the two Compute buttons, options, data, downloads |
| `packages/pdc/src/detergent_pdc/static/styles/pdc.css` | remove the retired panel classes; style the new tab |
| `packages/pdc/src/detergent_pdc/web/routes/pdc.py` | add the figure paths to the `pdc-structure` answer; remove `/api/pdc/<job>/system.pdb` with the panel |
| `packages/core/src/dashboard/web/static/js/main.js` | no change if the `complexes` id and `setRun` stay |
| `packages/pdc/tests/unit/test_pdc_structure_analysis.py` | protein→tail entry, contact groups, water counts, thresholds, schema v2, figures |
| `packages/pdc/tests/integration/test_pdc_structure_analysis.py` (or the existing integration test) | queue/read the new payload and figures |
| `packages/pdc/tests/browser/test_pdc_complex_data_browser.py` | **new**: the tab, run picker, `?run=`, Compute, options, states, no verdict |
| `packages/pdc/tests/browser/test_pdc_browser.py`, `test_pdc_run_selection_browser.py`, `test_pdc_bead_radii_browser.py`, `test_pdc_bonds_browser.py`, `test_pdc_import_browser.py` | retire (settled); the New run / Run view coverage stays |
| `packages/core/tests/unit/test_kinds_published.py` | only if a `kind_payload` validator is added |
| `tests/harness/areas.py` | the new `test_pdc_*` files auto-match the pdc area; no edit unless a name leaves the pattern |
| `docs/HANDOFF.md` | one current-state entry after the live run |

The Run view section's browser test (`test_pdc_analysis_section_browser.py`) stays; the new RDF pair is additive.

## 6. Acceptance

The repository's existing acceptance form applies and is not reopened: method, sampling, cutoffs and caveats beside
every number; pinned parsing/geometry tests; no record labelled validation; no threshold.

Checks:

1. **Unit** — the new RDF pair, the contact groups, the water counts, the thresholds/defaults/validation, the report
   v2, the per-metric PNGs (non-empty, named), and the retained v1 keys.
2. **Integration** — queue `pdc-structure` with a threshold override on the fixture run; read the route; the report and
   the figures; the old section still reads the v1 keys.
3. **Browser** — the new tab replaces the old panel; the run picker lists completed pdc runs only; `?run=`;
   Compute structure posts and polls; the second Compute overview queues the core kind and its cached record is
   readable in the Run view; the options; the empty/old-schema/no-protein/fallback states; the drag-free data
   render; no verdict/trend text; `window.pdcSetRun` selects a run.
4. **Retirement** — the old panel's tests are gone; the New run and Run view tests are green; the dead
   `system.pdb` route is gone; the shared endpoints still answer.
5. **Live** — one timed `pdc-structure` run on `NG_2ydo` (completed; extension skipped, so the assessment leg): the
   leg/sample line, the report, the per-metric PNGs, the tab; the ~1.5–2 min measured; the fallback-leg sentence.
6. **Tiers** — the pdc area, the full fast tier, the browser tier, `ruff`, and `scripts/gate_commit.sh` with the
   changed paths; `docs/HANDOFF.md` updated after the live run.
7. **Cleanup** — the `/api/pdc/<job>/system.pdb` route is removed with its route test; a grep proves no consumer.

## 7. Decisions settled (2026-11-24)

| Open item | Decision |
| --- | --- |
| Tab label | **PDC analysis**. |
| Thresholds | The current defaults: 0.05 nm bin, 2.0 nm r_max, the run's own 0.6 nm contact, 0.6 nm water. |
| Dead `system.pdb` route | Removed with the retired panel (grep first). |
| Old panel tests | Retired; the New run / Run view coverage stays. |
| No `trajectory-overview` | A second **Compute overview** button; the core kind caches its attempt; the Run view's Analysis card reads the same record. |
| Figures | A separate PNG per plotted metric (RDF, protein contacts, water contacts, shape, aggregation); the overview keeps its own PNG. |

The plan's technical defaults are adopted: the feature's `kind_payload` validator for the thresholds; v1 records show
"not measured" with a Compute action; the contact default is the run's `settings.contact_nm`; the route derives the
figure paths from the record's `source`.

## 8. Order of work

1. Producer v2 + unit tests (definitions, thresholds, report, the per-metric PNGs).
2. Kind/feature payload validator + the route's figure paths + remove the dead `system.pdb` route + integration test.
3. Panel replacement (`pdc-analysis.js`, template, CSS, feature registration, the two Compute buttons); retire the
   old panel UI.
4. Browser tests; retire the old panel tests; the Run view section test; the separate figures.
5. Live `NG_2ydo` run; the fallback/no-protein states; the second **Compute overview** path; the full tiers; the gate.
6. `docs/HANDOFF.md`; the plan's measured numbers pasted back here.

Nothing in this document is a measurement of the new metrics. The first timed live run on a completed pdc run is the
one that replaces the cost estimates in §2 with numbers, before any copy or handoff claims one.
