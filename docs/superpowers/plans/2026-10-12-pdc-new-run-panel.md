# A New Run panel for Protein-Detergent Simulations

Status: **draft for approval.** Nothing here is built. The HTML mock of the panel is beside this plan at
`docs/superpowers/drafts/2026-10-12-pdc-new-run-panel-draft.html`.

## Why a separate panel

`#new` today serves four run types through one form: `aa_only`, `aa_cg`, `cg_composition`, and now protein-detergent.
For a protein-detergent run most of that form is not merely redundant, it is unanswerable. Measured against
`execution/adapters/pdc.py`:

- `pdc.STAGES` start at **System preparation** from `protein.pdb` + `system_EMPTY.top` + `detergent.itp`. There is no
  AA-reference stage and no fitting stage, because the detergent arrives **parameterized** as a file. So "AA reference
  source", "Bonded parameters", "Bonded workflow" and "Method: Fast_Forward" have nothing to act on.
- `pdc.validate_payload` reads `seed`, `aggregation_number`, `template`, `protein`. **It does not read `method`.**
  That control is vestigial for this path — the panel offers a choice the adapter ignores.
- Candidate screening (`draft-smoke` profiles and the hint that explains them) belongs to mapping development. The
  detergent here is already mapped and saved; screening it from a run panel is the wrong door.

## What the panel must collect, and why each one

| field | source of truth | keep / drop / add |
| --- | --- | --- |
| Detergent | `molecules/`, filtered to **detergents only** | keep, narrowed |
| Detergent template | `/api/pdc/catalog` (`registered_type`, `limitations`) | keep |
| CG mapping | `/api/mappings?molecule_id=<detergent>` | keep, narrowed to that detergent |
| Membrane protein | `/api/pdc/catalog` proteins, with an **OPM download** | add to this panel |
| Detergent count | `aggregation_number` (default 150, 1..1000) | keep, moved up: it is the headline number |
| Encapsulation estimate | **new computation**, see below | add |
| Assessment / extension duration | `pdc_assessment_ns` 100, `pdc_extension_ns` 900 | keep |
| Salt | `salt_molar` 0.15 | keep |
| Seed | `pdc_seed` (required; no default, so two builds are comparable or not at all) | keep |
| Box margin, initial z, contact distance | `box_margin_nm` 2.0, `initial_z_nm` 6.0, `contact_nm` 0.6 | keep, folded into an advanced block |
| Removal threshold, snapshot interval/cap | `selection_threshold_fraction` 0.10, `snapshot_interval_ns` 20, `snapshot_cap` 20 | keep, advanced block |
| Run label | free text | keep |
| Run type, Method, Force field, Execution profile | — | **drop** |
| Bonded parameters, Bonded workflow, AA reference source | — | **drop** |
| Temperature, pressure, box edge, AA durations, CG durations, mdrun threads/ranks, Nonbonded/PME scheme, SASA probe, trajectory interval, AA seed | — | **drop**: the pdc protocol fixes these, and a control that writes a value nobody reads is worse than no control |

Panel heading becomes **Protein-Detergent Simulations**, parallel to "Single Molecule Simulations" on the other
workspace. Proposed wording decision, easy to overrule: the heading changes, the rail tab keeps its short label
("New run"), because the rail is 200 px wide and a five-word tab wraps there.

## The encapsulation estimate — new work, and what it is not

No belt and no hydrophobic-surface computation exists in this code base; `pdc_assessment.py`'s own docstring says the
criterion is implemented "at its simplest defensible form" for that reason. So this is a real piece of work, not a UI
label.

**Method** (a flat-area estimate, computed from the structure, no simulation):

1. Per-residue solvent-accessible area of the membrane protein, from `gmx sasa` on the deposited structure.
2. Restrict to the **transmembrane slab**: `|z - centre| <= half_thickness`, where `half_thickness_nm` comes from the
   OPM annotation the import already returns. That slab is the surface a belt must cover.
3. Sum the area of the slab's **apolar** residues (A, V, L, I, M, F, W, P).
4. `needed = apolar_area / head_area`, with `head_area = pi * r_head^2`, `r_head` from the head bead's Martini size
   class in the detergent's own mapping.
5. Report `needed`, the requested `aggregation_number`, and `requested * head_area / apolar_area` as a fraction.

**What it is not.** It treats the protein as a flat surface: no curvature, no packing, no shape. It says "N detergents
is roughly the right order" and never "the micelle forms". The run's own assessment is what decides that, and it
already reports it. The panel must show the number with that sentence attached, or it is inviting the reader to
mistake a sizing aid for a verdict.

**Where it lives:** a function taking coordinates + a slab + a head radius (testable with a hand-made structure,
no simulation) behind `GET /api/pdc/proteins/<entry>/encapsulation?molecule_id=<detergent>&aggregation_number=N`.
The route returns the numbers *and* the method string and the caveat, so the panel renders what the server decided
rather than repeating arithmetic in JavaScript.

## Detergents only: the registry that already exists

`detergents.json` at the repository root is a name-to-SMILES map of **95** detergents (DDM, SB3-10/12/14,
C10-Betaine, ...). **Nothing in the code base reads it** — verified by grep. It is the natural registry for
"detergents only": the panel's molecule list filters to the short codes that registry names, and the file stops being
a dead asset. A molecule that is not in it cannot be picked here, which is the point.

## Decisions I have already made, with reasons

- **One section, two modes**, rather than a second panel with its own URL. The registry keys a slug to one DOM id and
  `new-run` is the slug in both workspaces, so a second section means a second slug and a second URL
  (`/protein-detergent/pdc-run`), which breaks every existing link for no gain the user asked for. The panel branches
  on the workspace slug it was mounted under.
- **The rail keeps "New run"**; the panel heading carries the new name. (Overrule if you disagree.)
- **The panel sends only what `pdc` reads.** A control whose value no stage consumes is a control that lies.
- **The Complexes panel keeps its own build door.** It queues builds from the template catalogue; this panel is for a
  run the reader configures. Two doors to the same pipeline is already true, and closing one is not in this ask.

## Tasks

Each task is test-first and lands with its own commit and gate run.

**T1 — the registry grows two facts.** A per-workspace panel label (the registry is keyed by slug today, so
`simulations.new-run` cannot differ from `validation.new-run`), and a detergent list built from `detergents.json`.
Files: `dashboard/web/sections.py`, `dashboard/models/molecules/…` (or the route that lists molecules),
`dashboard/web/routes/molecules.py`. Tests: a unit test that both workspaces label their new-run panel differently,
and one that a non-detergent is refused and DDM allowed. Acceptance: no other panel's label moves.

**T2 — the panel's pdc mode.** The template gains a pdc fieldset, rendered only for that workspace; `new-run.js`
branches on its workspace slug, drops the controls listed above and shows the pdc ones. Files:
`dashboard/web/templates/dashboard.html`, `dashboard/web/static/js/new-run.js`, `dashboard/web/static/new-run.css`.
Tests: browser — opening `/protein-detergent/new-run` shows no "Run type", no "Method", no "AA reference source", no
"Bonded parameters", and does show the detergent list, the protein picker, the count and the settings; opening
`/detergent-validation/new-run` is unchanged.

**T3 — the estimate.** The function, its route, and a test with a hand-made structure whose apolar area is known by
construction, so the arithmetic is pinned independently of `gmx sasa`. Files: new module under
`dashboard/models/` (or `analysis/runs/`), `dashboard/web/routes/pdc.py`, its tests. Acceptance: a protein with no
membrane annotation is refused with a reason, not given a made-up slab.

**T4 — the OPM download inside the panel.** Reuse `/api/pdc/proteins/import` (it exists, and the Complexes panel
already drives it), including its honesty: an import that finds no membrane annotation says so. Files:
`new-run.js`, the template. Tests: browser — an import adds the structure to the picker and states the
half-thickness it found.

**T5 — end to end.** Fill the panel for a real detergent and protein, and reach the readiness line; queue nothing.
Files: one browser test. Acceptance: the readiness blockers name what is missing and nothing else.

## Not doing

- Not removing the Complexes panel's build door, and not changing what it sends.
- Not adding controls for values `pdc` does not read (temperature, pressure, box edge, thread counts).
- Not claiming the estimate validates encapsulation. It sizes an input; the assessment decides.
