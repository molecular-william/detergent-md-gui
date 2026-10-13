# A New Run panel for Protein-Detergent Simulations

Status: **T1, T2, T3, T6 and T7 built and committed (2026-10-13).** T4's OPM download was wired by T2's own work — the
panel drives the existing import, including its half-thickness honesty — so it is done in substance. **T5** (end to end)
and **T8** (the registry's experimental numbers) remain open, and T8 waits on the user's experimental aggregation
numbers. The HTML mock of the panel is beside this plan at
`docs/superpowers/drafts/2026-10-12-pdc-new-run-panel-draft.html`.

Redlines from the first review (2026-10-13) are folded in: the workflow chain this panel states, the two pipeline
changes it implies (self-assembly, and minimisation + equilibration before the assessment leg), the empty-micelle
screen, the registry's experimental aggregation number, and two columns for the layout.

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
| Encapsulation estimate | **new computation**, see below | add — **protein runs only**: an empty micelle has no belt to size |
| Experimental aggregation number | `detergents.json`, per entry, with its citation | **add**: shown beside the count, and it is what the empty-micelle screen shows instead of an estimate |
| Protein preparation | PDB2PQR, then energy minimisation | **add**, optional: MemProtMD ships this as its own workflow |
| Elastic network | `martinize2 -elastic -ef 1000 -el 10` | already in the spec; shown as a step so the strip states what runs |
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

## The workflow this panel describes

The panel states the chain it runs, because half its fields only mean something inside that chain. It follows
MemProtMD's own two routes (README, `pstansfeld/MemProtMD`), quoted rather than paraphrased:

- **Self Assembly**: `PDB -> Memembed -> martinize2 -> self-assemble -> CGMD -> CG2AT`
- **Energy Minimise**: `PDB -> PDB2PQR -> minimisation` — a separate workflow there, optional here.

| step | tool | notes |
| --- | --- | --- |
| 1 Prepare (optional) | PDB2PQR, then EM in water | missing side chains and protonation; prepared once and reused by later runs |
| 2 Coarse-grain | `martinize2` | Martini 3, elastic network over Cα pairs within 1.0 nm at 1000 kJ/mol — already the spec's protocol |
| 3 Self-assemble | our builder, then CG MD | detergents placed at random; the belt finds its own arrangement (change 1 below) |
| 4 Sample | `gmx mdrun` | minimisation, equilibration, then the assessment leg — **none of which the protocol does today** (change 2) |
| 5 Judge | `pdc_assessment` | micelle counted, the rest removed, >10% removed re-runs the leg up to three times |
| 6 Extend, back-map | `gmx convert-tpr -extend`, then CG2AT2 | `-o align`; the extended state is what gets back-mapped |

**Memembed is skipped, and the plan says so rather than leaving a silent gap:** our input is an OPM structure, already
oriented in the membrane. That is the step OPM does for us.

### Two changes to the pipeline, both bigger than a panel

1. **Self-assembly instead of placing a pre-formed belt.** The spec's protocol step 3 places detergents on the micelle
   builder's deterministic lattice and then repacks. MemProtMD's self-assembly route — and the requested workflow —
   places them **at random** and lets CG MD form the belt. That is a change to the build the pdc pipeline drives, so it
   needs its own task and its own test rather than a control in this panel. Both cases use it: an empty micelle
   self-assembles the same way, which is how a reference micelle is normally made.
2. **Minimisation and equilibration before the assessment leg.** The protocol goes from the built system straight into
   100 ns of CG MD. EM, then NVT, then NPT is the standard sequence for a CG system built from a mapping, and MemProtMD
   minimises too. This changes `pdc.STAGES`, so it is a pipeline task with a measured acceptance: one stage per step,
   recording `skipped` where it has nothing to do.

### A run with no protein

Choosing **No protein · empty micelle** changes the screen, not the pipeline:

- No belt, so **no encapsulation estimate**, no protein fields, and no belt heading. The count stays **as an input**:
  it is the micelle's size — the first mock hid it inside the belt block, which the review caught.
- In the estimate's place, the detergent's **experimental aggregation number** from the registry, beside the count.
- The workflow strip greys the protein clauses in steps 3 and 5 and says why.
- The workflow card sits at the **top of the right column**, above the review: what will run is read before the resolved
  values, which is the order the second review asked for.

### The registry carries the experimental number, with its citation

`detergents.json` entries grow `aggregation_number` and `aggregation_number_source`. The rule is the project's
existing one: a checked-in value is **citation metadata until a molecule-specific measurement and its uncertainty are
supplied**, so a number without a source is not written down at all. Until an entry has one, the panel shows "not
recorded yet" — a micelle size quoted without a source would be indistinguishable from one the panel guessed. DDM's
entry has no number today, and the mock says exactly that.

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

**Done (2026-10-13).** `detergents.json` — 95 entries, no reader before this — is read by
`models/molecules/detergent_registry.py`; `GET /api/detergents` resolves it against the molecules on disk; `sections.py`
gains `panel_labels`. Measured: 21 tests, 7 of them browser, for T1 and T2 together — a molecule the registry does not
name is refused by name, and every other panel's label is asserted unchanged.

**T2 — the panel's pdc mode.** The template gains a pdc fieldset, rendered only for that workspace; `new-run.js`
branches on its workspace slug, drops the controls listed above and shows the pdc ones. Files:
`dashboard/web/templates/dashboard.html`, `dashboard/web/static/js/new-run.js`, `dashboard/web/static/new-run.css`.
Tests: browser — opening `/protein-detergent/new-run` shows no "Run type", no "Method", no "AA reference source", no
"Bonded parameters", and does show the detergent list, the protein picker, the count and the settings; opening
`/detergent-validation/new-run` is unchanged.

**Done (2026-10-13).** The pdc fieldset renders for the protein-detergent workspace only; Run type, Method, AA
reference source and Bonded parameters are gone, and the count stays an input in both modes. Measured: the two columns
sit side by side at 1700 px (`816|816` of a 1652 px form) and at 1280 px (`606|606` of 1232), and stack below the 900 px
breakpoint (1000 px). Two tests found two real defects rather than papering over them: the template heading read
whichever panel was open, and the select carried a catalogue id where prepare needs the template's file path.

**Two columns, and how this panel already gets them.** The form is `#run-form.new-run-layout`: `layout.css` gives it a
12-column grid and `.new-run-inputs` / `.new-run-settings` span 6 each, and the app links `layout.css` *after*
`new-run.css` so that rule wins. The mock missed both — the form carried no `id`, and its stylesheets were linked in
the other order — and stacked into one column; it now carries the id and keeps the app's head order. The browser test
should assert the two halves sit side by side (different `x`, each about half the form's width), not merely that both
exist.

**T3 — the estimate.** The function, its route, and a test with a hand-made structure whose apolar area is known by
construction, so the arithmetic is pinned independently of `gmx sasa`. Files: new module under
`dashboard/models/` (or `analysis/runs/`), `dashboard/web/routes/pdc.py`, its tests. Acceptance: a protein with no
membrane annotation is refused with a reason, not given a made-up slab.

**Done (2026-10-13).** The module is `analysis/runs/encapsulation.py`, the route
`GET /api/pdc/proteins/<entry>/encapsulation`. Measured: 34 tests, 25 unit and 9 integration; the load-bearing fixture
is derived by hand (2 x 4*pi*(0.175 + 0.191)^2 = 3.366681 nm^2 against a measured 3.366681, the residue being the
Fibonacci mesh's float32). A modified residue (MSE) was recorded as *not* counted as apolar at this commit — that
defect is fixed in the commit that follows — and the panel wiring is `ed7441a`: 7 browser tests, browser tier 93,
rendering the server's answer verbatim and recomputing nothing.

**T4 — the OPM download inside the panel.** Reuse `/api/pdc/proteins/import` (it exists, and the Complexes panel
already drives it), including its honesty: an import that finds no membrane annotation says so. Files:
`new-run.js`, the template. Tests: browser — an import adds the structure to the picker and states the
half-thickness it found.

**T5 — end to end.** Fill the panel for a real detergent and protein, and reach the readiness line; queue nothing.
Files: one browser test. Acceptance: the readiness blockers name what is missing and nothing else.

**T6 — self-assembly in the build.** Placing detergents at random instead of on the builder's lattice (change 1), with
the seed recorded so a build is reproducible and a different seed is a different build. Files: the pdc builder,
`docs/superpowers/specs/2026-09-28-protein-detergent-complex-panel-design.md` (protocol step 3 rewritten, its lattice
step kept as the other mode). Tests: a build places exactly N detergents inside the box with no overlap on the
protein, the same seed reproduces the placement, a different seed does not, and the manifest records which mode built
the system. Acceptance: the existing placed-belt build still runs, so this lands as a mode and not as a replacement
until a real run says the self-assembled belt is better.

**Done (2026-10-13).** `pdc_placement.place_detergents` gains `mode=`: `lattice` (unchanged, still the default, so no
existing build moves) and `self-assembly`, a seeded cloud inside the placement box, rejection-sampled against protein
clearance (0.5 nm) and the builder's own pairwise gate (0.25 nm). Measured on a 4x4x2 nm protein fixture, 20
detergents, seed 11: protein clearance 0.5717 nm, closest detergent pair 0.3836 nm, every centre inside the placement
box; seed 11 reproduces byte-identically and seed 12 does not; the lattice mode's centres are byte-equal to
`pack_micelle`'s. T6 and T7 landed as one commit, both touching `adapters/pdc.py`: 23 tests, 14 of them for the stage
chain.

**T7 — minimisation and equilibration before the assessment leg** (change 2). Files:
`dashboard/execution/adapters/pdc.py` (`STAGES`), its MDP templates under `resources/templates/`, stage tests. Tests:
the stage plan gains one pair per step in order (minimisation, NVT, NPT, then assessment), each stage records
`skipped` when it has nothing to do, and the chain's added cost is stated in the plan once measured. Acceptance: a
diagnostic run reaches the assessment leg; the equilibrium legs are reported with their wall time, not assumed cheap.

**Done (2026-10-13).** `pdc.STAGES` gains three pairs in order ahead of "CG assessment MD", every pre-existing stage
name and relative path unchanged (a test pins it, because `pdc_extension.py`, the snapshot scripts, `analysis/kinds.py`
and `routes/pdc.py` name `1_system/2_assessment/...` literally). Measured, on a 400-bead water box: grompp
1.6 / 1.3 / 1.2 s, minimisation 2000 steep steps 2.5 s, NVT 1000 steps 2.5 s, NPT 100 steps 2.8 s. The default chain
is 5 ns of equilibration, split 0.5 ns NVT + 4.5 ns NPT after the AA half's shape; dt 0.005 ps is the standing
CG-equilibration decision, and the couplings and cut-offs are the CG half's own. Full fast tier 1298 passed, browser
tier 82, ruff clean on `dashboard` and `tests`. One gap recorded rather than papered over: the assessment script still
equilibrated of its own accord, so a run equilibrated twice — collapsed in `60283f5`, which also renamed the shared
stage scripts to pdc's own.

**T8 — the registry's experimental numbers, and the empty-micelle branch.** `detergents.json` gains
`aggregation_number` + `aggregation_number_source` per entry, absent meaning not recorded; the detergent route returns
them; the panel shows the number beside the count and, with no protein, shows it *instead of* the estimate. Files:
`detergents.json`, the detergent route, `new-run.js`, the template, tests. Tests: a browser test that an entry with no
number renders "not recorded yet" and one with a number renders both the number and its source; and that choosing
"No protein · empty micelle" hides the estimate and the protein clauses and keeps the count. Acceptance: no number is
written into the file that does not carry a source.

## Not doing

- Not removing the Complexes panel's build door, and not changing what it sends.
- Not adding controls for values `pdc` does not read (temperature, pressure, box edge, thread counts).
- Not claiming the estimate validates encapsulation. It sizes an input; the assessment decides.
