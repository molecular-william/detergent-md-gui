# Detergent MD automation

A local research dashboard for Martini/GROMACS work on detergents and the proteins they solubilise. It runs AA
molecule simulations, turns a coarse-grained bead assignment into fitted bonded terms, simulates that CG model, runs
protein–detergent complexes, and sweeps a sugar's osmotic pressure — staging, logging, assessing and reporting each
step, and keeping every input, tool version and command that produced a result.

Two workspaces, one for the model and one for the protein:

* **Detergent validation** (`/detergent-validation`) — build a bead assignment, fit and inspect its bonded terms,
  simulate it, read the results. Panels: Runs, Run view, New run (Single Molecule Simulations), CG Bead Assignment,
  CG Bond Interactions, Combinations, Mapping validation, Osmotic Series. Run types: `aa_only`, `aa_cg`,
  `cg_composition`, `osmotic`.
* **Protein-detergent simulations** (`/protein-detergent`) — set up a protein with its detergent, run the complex, read
  it. Panels: Runs, Run view, New run (Protein-Detergent Simulations), Complexes. Run type: `pdc`.

`molecules/DDM` is the worked reference molecule; any molecule with a compatible AA topology goes through the same
generic adapters. Generated parameters are hypotheses: a fit is an execution fact, never scientific validation.

## Start

From the repository root:

```bash
.venv/bin/python -m dashboard               # then open http://127.0.0.1:5000
```

One coordinator per configured workspace. The checkout selects `workspace/dashboard/` through
`config/dashboard-paths.json`; `DASHBOARD_WORKSPACE=/absolute/path` overrides it for an isolated instance. Restart the
process after changing Python code — routes and models are loaded at start, `static/` and templates are not.

## The model a run consumes

1. **A saved mapping** — a bead assignment over the molecule's heavy atoms, saved from CG Bead Assignment. One content
   identity is one saved mapping: a second save of the same assignment is refused (409) and the editor names the mapping
   that already holds it. A rename is an in-place save and keeps its identity.
2. **Its parameterization** — revisions of bonds, angles and dihedrals fitted to an AA reference by Fast-Forward
   (`ff_inter`) or BARTENDER (`-refit -owntraj` against our own mapped trajectory). Revisions are keyed by content hash,
   one is current, and the record lists the mappings that claimed it (`owners`). Producing one makes no MD.
3. **A run** — the AA half, then the mapping, then the CG half. An `aa_cg` run whose mapping carries a current revision
   consumes it and records that it did not fit; otherwise the run fits its own terms and says so in its artefacts.

## Run types

| Run type | What it does |
| --- | --- |
| `aa_only` | Solvation, neutralisation, minimisation, NVT, NPT, production, reference publication. 2 fs. |
| `aa_cg` | AA reference → trajectory mapping → CG parameterization → CG simulation → assessment → SASA. 20 fs production, 5 fs equilibration. |
| `cg_composition` | CG simulation, assessment and SASA from an immutable composition: no AA half, no settable settings. |
| `pdc` | Protein preparation (PDB2PQR rebuild and protonation, on by default, skipped when the tool is absent), system preparation, minimisation/NVT/NPT, CG assessment MD, micelle assessment, extension MD, final assessment, optional CG2AT2 back-mapping. |
| `osmotic` | One run owning N concentrations: each has its own directory and checkpoint and is resumable. Sugars only. |

## Repository layout

* `packages/core/` — the engine (`detergent-core`): `execution/` (coordination, stages), `models/` (mappings, bonded
  parameterizations, compositions, molecules), `analysis/`, `web/` (routes, templates, static JS). Import it as `dashboard`.
* `packages/validation/` — the detergent-validation feature (`detergent-validation`): the bonded, osmotic and
  refinement panel APIs and the osmotic series. `packages/pdc/` — the protein-detergent feature (`detergent-pdc`):
  the ten-stage pipeline, its adapter and scripts. The meta distribution at the root installs the engine and names
  both as the `det`/`prot`/`all` extras. A feature distribution joins a dashboard by advertising the
  `detergent_md.features` entry point (`docs/PROJECT_GUIDE.md`, *Adding a distribution*); installing the wheel is the
  whole act, and an install without one of them serves only the workspace it has.
* `tests/dashboard/` — unit, integration and browser tiers with isolated stores; never the developer's workspace.
* `molecules/`, `references/`, `resources/` — canonical scientific inputs; the CG force field is installed per
  workspace at `workspace/dashboard/martini3` from `references/M3-Lipid-Parameters/ITPs`, never from a copy in the tree.
* `tools/cg2at/` — CG2AT2, vendored, used by the `pdc` back-map stage with the `martini_3-0_charmm36` fragment DB.
* `config/` — workspace selection and declared tools (`config/tools.json`, resolved by `dashboard.execution.tools`;
  GROMACS here is `/usr/local/gromacs/2026.3/bin/gmx`, an MPI-only build, so `-ntomp` is the thread knob).
* `reports/dashboard/`, `reports/validation/` — scientific reports and acceptance evidence.
* `workspace/dashboard/` — runtime state: SQLite job store, runs, saved mappings, parameterizations, compositions.

## Documentation

* [AGENTS.md](AGENTS.md) — engineering rules, workflow contract, standing decisions, and the "do not" list.
* [docs/PROJECT_GUIDE.md](docs/PROJECT_GUIDE.md) — dashboard operation, paths, persistence, migration, testing.
* [docs/HANDOFF.md](docs/HANDOFF.md) — current state, open items and recent slices.
* [docs/DDM_CALIBRATION.md](docs/DDM_CALIBRATION.md) — DDM scientific status, scoring contract, known gaps.
* [docs/design/](docs/design/) — dated design records: intent at their date, not the current rules.
* [docs/plans/](docs/plans/) — every implementation plan: scope, tasks and execution records.
* [docs/superpowers/specs/](docs/superpowers/specs/) — the protein-detergent panel specification.
* [docs/research/](docs/research/) — carbohydrate mapping and validation operations.

## Verification

```bash
.venv/bin/python -m pytest -m 'not browser and not slow' -q      # fast tier
.venv/bin/python -m pytest -m browser -q -n 16 --dist worksteal   # browser tier
.venv/bin/python -m pytest -m slow -q -n 0                       # slow tier, serial
.venv/bin/ruff check packages tests                             # must exit 0
scripts/test_module.sh core|validation|pdc [fast|browser|slow]    # one distribution's tests
```

Tier counts and timings are measured in `pytest.ini`; for the current total, quote
`pytest --collect-only -q`. Export a private `MPLCONFIGDIR` before running a tier: four distance-diagnostic tests race on a
shared matplotlib cache. `scripts/gate_commit.sh <message-file> <paths...>` runs the fast tier and ruff over the named
paths and commits only when both are clean.

## Where the project stands

**Implemented and maintained.** The AA and CG adapters, the `pdc` pipeline with CG2AT2 back-mapping, the osmotic series,
the mapping editor, the CG Bond Interactions panel, and the two-monitor Run view (paired in simulation time, not by
frame index). The `memembed → martinize → insane → cg2at` chain earlier notes described is gone: `archive/MemProtMD/` is
not in this checkout, and `pdc` is what that goal became.

**Paused.** The native micelle builder (`micelle/`) — a spherical single-detergent Martini micelle around membrane
proteins, with a partial, unvalidated implementation. It must not be presented as a model. The protein-detergent
workflow it was meant to serve is implemented through `pdc`.

**Cancelled, not to be rebuilt.** The iterative mapping refinement panel (2026-10-15: the human review gate cost more than
the decision it supported) and the scheduled cron drivers (2026-10-15). The routes and the `refinement-score` analysis
that already existed stay.

**Landed after the 2026-10-21 drafts** (HTML drafts in `docs/design/drafts/`): the CG Bond Interactions two-column
layout (`docs/plans/2026-10-21-bond-panel-layout.md`), a choosable mdrun GPU recorded by name
(`2026-10-21-mdrun-gpu-device.md`), and body-aware, subunit-sized detergent placement
(`2026-10-21-pdc-detergent-placement.md`).

**Open items** are not tracked here. `docs/HANDOFF.md` holds the list with the measurement behind each one, and
`AGENTS.md` holds the decisions that closed the rest.
