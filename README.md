# Detergent MD automation

A local research dashboard for Martini/GROMACS work on detergents and the proteins they solubilise. It runs AA
molecule simulations, turns a coarse-grained bead assignment into fitted bonded terms, simulates that CG model, runs
protein–detergent complexes, and sweeps a sugar's osmotic pressure — staging, logging, assessing and reporting each
step, and keeping every input, tool version and command that produced a result.

Two workspaces, one for the model and one for the protein:

* **Detergent validation** (`/detergent-validation`) — build a bead assignment, fit and inspect its bonded terms,
  simulate it, read the results. Panels: Runs, Run view, New run (Single Molecule Simulations), CG Bead Assignment,
  CG Bond Interactions, Combinations, Mapping validation, Osmotic Series. Run types: `aa_only`, `cg`, `osmotic`.
* **Protein-detergent simulations** (`/protein-detergent`) — set up a protein with its detergent, run the complex, read
  it. Panels: Runs, Run view, New run (Protein-Detergent Simulations), Complexes. Run type: `pdc`.

`molecules/DDM` is the worked reference molecule; any molecule with a compatible AA topology goes through the same
generic adapters. Generated parameters are hypotheses: a fit is an execution fact, never scientific validation.

## Install from a clone

A clone carries the source and the Martini 3 force field; the compiled tools and their checkouts (Fast-Forward,
BARTENDER, CG2AT2) live under `tools/`, which is provisioned separately and gitignored, so the checkout stays
reasonably small and every run still records the exact bytes and versions it used.

### 1. Python environment

You need Python 3.12 or newer. Every simulation stage runs a bash script, so the simulations need Linux or macOS; the
dashboard and the test suite run on both. GROMACS is covered in step 2.

The distributions declare only their dashboard imports, so the scientific stack is installed explicitly:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools wheel

# the engine and both features: a clone installs them from source, they are not on an index
.venv/bin/python -m pip install -e packages/core
.venv/bin/python -m pip install --no-deps -e packages/validation -e packages/pdc

# what the code imports but the packages do not declare
.venv/bin/python -m pip install numpy scipy matplotlib MDAnalysis numba networkx scikit-image openpyxl biotite
.venv/bin/python -m pip install lmfit cgsmiles pysmiles pbr tqdm

# pdc's DSSP and protonation steps, the test runner, and the browser driver
.venv/bin/python -m pip install -r requirements-dashboard-tests.txt
```

`pip wheel packages/* -w dist --no-deps` followed by `pip install --find-links dist "detergent-md-gui[all]"` is the
non-editable alternative.

### 2. Scientific inputs and third-party tools

Provision these once per clone. A declared path is the one the code uses; nothing is downloaded at run time, and a
missing tool is reported by readiness rather than replacing itself with something else.

| Tool | Needed for | Get it from | Put it at |
| --- | --- | --- | --- |
| GROMACS 2026.x | every simulation | <https://www.gromacs.org> (or your distribution, Spack, or conda) | any path with a working `gmx`; declare it |
| Fast-Forward (`ff_map`, `ff_inter`, `ff_assess`) | the AA→CG parameterization | <https://github.com/Martini-Force-Field-Initiative/fast_forward> | `tools/fast_forward` |
| BARTENDER + xtb | the CG Bond Interactions fit | the CGMartini tutorial archive (URL in the command below) | `tools/bartender/m3_bartender` |
| CG2AT2 | the `pdc` back-mapping stage | <https://github.com/owenvickery/cg2at> | `tools/cg2at` |
| Martini 3 force field | every CG run | shipped in this repository (upstream: <https://github.com/Martini-Force-Field-Initiative/M3-Lipid-Parameters>, Apache-2.0) | `references/M3-Lipid-Parameters` |
| the sugar reference | part of the same Martini set | shipped in this repository | `references/martini_v3.0.0_sugars_v2.itp` |
| PLUMED (optional) | the `osmotic` series | <https://www.plumed.org> | any path; declare it |

The Fast-Forward patch is not optional: without it its dihedral membership test is wrong, so restricted bending is
never assigned. The patch applies to upstream commit `718ce2de`, and the patch file itself is repository source under
`resources/patches/` -- only the checkout it applies to is provisioned.

`martinize2` (from the `vermouth` package) and `pdb2pqr` are installed by step 1 and resolve from the venv; they need
no download or declaration. The DSSP step asks vermouth for `mdtraj`, which step 1 also installs.

```bash
# Fast-Forward, patched and installed into the environment
mkdir -p tools
git clone https://github.com/Martini-Force-Field-Initiative/fast_forward tools/fast_forward
git -C tools/fast_forward checkout 718ce2de
git -C tools/fast_forward apply "$PWD/resources/patches/fast_forward-dihedral-membership.patch"
.venv/bin/python -m pip install --no-build-isolation --no-deps ./tools/fast_forward

# BARTENDER (its archive also carries the xtb build the configuration declares)
mkdir -p tools/bartender
curl -L -o /tmp/m3_bartender.zip \
  https://cgmartini-library.s3.ca-central-1.amazonaws.com/0_Tutorials/m3_tutorials/Parametrize_Small_Molecule/m3_bartender.zip
unzip -q /tmp/m3_bartender.zip -d tools/bartender
tar -xzf tools/bartender/m3_bartender/Bartender0.1.1.tgz -C tools/bartender/m3_bartender

# CG2AT2 (the back-map stage runs tools/cg2at/cg2at and reads its database/ tree in place)
mkdir -p tools
git clone https://github.com/owenvickery/cg2at tools/cg2at
```

PLUMED is needed only for the `osmotic` series, and the GROMACS build must have PLUMED support: `gmx mdrun -plumed`
loads a kernel at run time, and the code sets `PLUMED_KERNEL` from the `lib/` directory beside the declared `plumed`.

### 3. Declare the tools

`config/tools.json` is the one declaration `dashboard.execution.tools` reads. A declared path must be an executable
file or it resolves to nothing -- never to a different build of the same tool. A bare command name is resolved on the
dashboard's own search path (the environment's `bin` first, then the declared tools' directories, then `PATH`), and a
name that is not declared at all (`martinize2`, `pdb2pqr`) resolves the same way.

```json
{
  "gromacs": "/usr/local/gromacs/2026.3/bin/gmx",
  "fast_forward": "ff_map",
  "fast_forward_source": "tools/fast_forward",
  "fast_forward_commit": "61e407e60ffa0153fb2b5a028b065383619c2586",
  "bartender": "tools/bartender/m3_bartender/bartender",
  "xtb": "tools/bartender/m3_bartender/xtb-6.4.1/bin/xtb",
  "plumed": "/opt/plumed/bin/plumed"
}
```

The dashboard starts with none of these declared; each run type reports a missing tool at prepare time instead of
guessing at a substitute. Set `gromacs` to your own `gmx` (the value may also be the bare name `"gmx"`), and set
`fast_forward_commit` to the commit of your patched checkout if you provisioned a different one: the provenance is
recorded per run, and one test fails when the pin and the checkout disagree. Omit `plumed` if you do not run the
osmotic series.

### 4. Start

From the repository root:

```bash
.venv/bin/python -m dashboard                        # then open http://127.0.0.1:5000
.venv/bin/python -m dashboard --features validation  # only that feature; the default is every installed one
```

`detergent-dashboard` is the same entry point once the packages are installed. A feature that fails to load is skipped
and logged rather than stopping the dashboard; a name that matches no installed feature is an error. With no feature
installed the engine still serves its own workspace — Runs, Run view and New run for AA-only and AA-CG runs.

The first start creates `workspace/dashboard/` with its SQLite store and run directories; the Martini set is installed
into it the first time a CG reader needs it. One coordinator per configured workspace: the checkout selects `workspace/dashboard/` through
`config/dashboard-paths.json`, and `DASHBOARD_WORKSPACE=/absolute/path` overrides it for an isolated instance. Restart
the process after changing Python code — routes and models are loaded at start, `static/` and templates are not.

### 5. Check the installation

Open the dashboard; **New run** shows a readiness list and names every tool it cannot resolve. From a shell:

```bash
curl -s http://127.0.0.1:5000/api/jobs        # 200 with an empty or populated job list
```

The worked example is `molecules/DDM` (its atomistic input is under `molecules/DDM/results/MATCH`), and the run types
above say what each needs. Nothing is downloaded or installed by a run.

## The model a run consumes

1. **A saved mapping** — a bead assignment over the molecule's heavy atoms, saved from CG Bead Assignment. One content
   identity is one saved mapping: a second save of the same assignment is refused (409) and the editor names the mapping
   that already holds it. A rename is an in-place save and keeps its identity.
2. **Its parameterization** — revisions of bonds, angles and dihedrals fitted to an AA reference by Fast-Forward
   (`ff_inter`) or BARTENDER (`-refit -owntraj` against our own mapped trajectory). Revisions are keyed by content hash,
   one is current, and the record lists the mappings that claimed it (`owners`). Producing one makes no MD.
3. **A run** — for a `cg` run over a mapping's revision: the AA half, then the mapping, then the CG half. Such a run
   consumes its mapping's current revision and records that it did not fit; a mapping without one makes the run fit
   its own terms and say so in its artefacts. A published sugar reference and a composed CG model are the other two
   `cg` parameterization kinds: they carry their own coordinates and topology, so they have no AA half.

## Run types

| Run type | What it does |
| --- | --- |
| `aa_only` | Solvation, neutralisation, minimisation, NVT, NPT, production, reference publication. 2 fs. |
| `cg` | One CG run over three parameterization kinds: a saved mapping's revision (AA reference → trajectory mapping → CG parameterization → CG simulation → assessment → SASA), a published Martini 3 sugar reference, or a composed CG model (CG simulation, assessment and SASA from an immutable composition; no AA half, no settable settings). 20 fs production, 5 fs equilibration. |
| `pdc` | Protein preparation (PDB2PQR rebuild and protonation, on by default, skipped when the tool is absent), system preparation, minimisation/NVT/NPT, CG assessment MD, micelle assessment, extension MD, final assessment, optional CG2AT2 back-mapping. |
| `osmotic` | One run owning N concentrations: each has its own directory and checkpoint and is resumable. Sugars only. |

## Moving a run between workspaces

A run is two things: `workspace/dashboard/runs/<id>/` (manifest, stage files, logs) and a row in
`workspace/dashboard/jobs.sqlite3`. The dashboard reads the row — the Runs list pages the store, and every panel
resolves a run through it — so a directory copied in by hand is invisible until it is registered. The 12-character
run id is the identity mappings pin an AA source by (`aa_reference.run_id`), so a copy keeps it.

**Both workspaces at hand.** `detergent-import-run` copies the directory and the row together, and re-verifies the
copy against the receiving checkout before it is listed:

```bash
.venv/bin/detergent-import-run --run <id> \
  --from-workspace /path/to/sender/workspace/dashboard \
  --to-workspace   /path/to/receiver/workspace/dashboard      # dry run; add --apply to move
```

**Only the directory arrived** — `cp -r`, a zip, a colleague's checkout. Register it in place; the job row is
rebuilt from the manifest the run already carries. The Runs panel shows a banner above the table while `runs/` holds
directories with no row, and **Register copied runs…** lists them (AA-only first) and registers the ticked ones. The
same two steps are a route and a command:

```bash
.venv/bin/detergent-import-run --adopt --workspace /path/to/receiver/workspace/dashboard --run <id>   # dry run
.venv/bin/detergent-import-run --adopt --workspace /path/to/receiver/workspace/dashboard --run <id> --apply

curl -s http://127.0.0.1:5000/api/runs/unregistered                 # directories with no row
curl -s -X POST http://127.0.0.1:5000/api/runs/adopt \
  -H 'Content-Type: application/json' -d '{"run": "<id>"}'          # register one
```

Adoption verifies the copy's recorded inputs (`inputs/inputs.json`) against the receiving checkout, rebuilds the
run's analysis attempts from `analyses/*/*/*/manifest.json`, marks the row `adopted_at`, and derives the display
fields a manifest never carried (`label`, `created`, `method`, `profile`). It refuses a directory whose manifest still
says `running`, a copy whose recorded inputs do not match this checkout, and a `cg` run whose AA source is not
registered — adopt the source first. A `cg` run of the `revision` kind records the AA source it consumes; copy that
run too, or the run cannot resolve its reference.

**AA references travel, too.** A completed `aa_only` run is what Bond Interactions fits against, and its
`stages/07_reference/reference.json` records the force-field tree and molecule files it was built from, by digest.
Newer records name each source by a portable locator (`repo`/`workspace` + relative path), so they verify on any
checkout holding the same files; an older record's absolute path may not exist there, which is reported as a
provenance warning, not a failure — the run's own artifacts are still hashed and are what the trajectory is read
through. The Bond Interactions card states "provenance not re-checked here: N sources not on this machine" when that
happens, and a source that is present and has changed is still refused.

**What it needs, and what does not travel.** The receiving clone needs the same tracked inputs (`molecules/`,
`resources/templates/`, `config/`) at a compatible commit; it needs no sender database, and reading a completed run
needs no GROMACS. A run still marked running is not adoptable. The sender's display label and created date are not in
a manifest, so adoption derives them; analyses are rebuilt from their attempt records, and an attempt the sender left
running is adopted as failed because no worker here owns it.

## Repository layout

* `packages/core/` — the engine (`detergent-core`): `execution/` (coordination, stages), `models/` (mappings, bonded
  parameterizations, compositions, molecules), `analysis/`, `web/` (routes, templates, static JS). Import it as `dashboard`.
* `packages/validation/` — the detergent-validation feature (`detergent-validation`): the bonded, osmotic and
  refinement panel APIs and the osmotic series. `packages/pdc/` — the protein-detergent feature (`detergent-pdc`):
  the ten-stage pipeline, its adapter and scripts. The meta distribution at the root installs the engine and names
  both as the `det`/`prot`/`all` extras. A feature distribution joins a dashboard by advertising the
  `detergent_md.features` entry point (`docs/PROJECT_GUIDE.md`, *Adding a distribution*); installing the wheel is the
  whole act, and an install without one of them serves only the workspace it has.
* `packages/<name>/tests/` — each distribution's own unit, integration and browser tiers, with `tests/harness/`
  holding the fixtures, plugins and selection tables they share; isolated stores, never the developer's workspace.
* `molecules/`, `references/`, `resources/` — canonical scientific inputs; the CG force field is installed per
  workspace at `workspace/dashboard/martini3` from `references/M3-Lipid-Parameters/ITPs` (tracked here, Apache-2.0),
  never from a per-run copy.
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
* [docs/design/](docs/design/) — dated design records: intent at their date, not the current rules; its
  `drafts/` working files are local to the checkout and untracked.
* [docs/plans/](docs/plans/) — every implementation plan: scope, tasks and execution records. The directory
  is local to the checkout and untracked apart from its `README.md`, which states the convention.
* [docs/superpowers/specs/](docs/superpowers/specs/) — the protein-detergent panel specification.
* [docs/research/](docs/research/) — carbohydrate mapping and validation operations.

## Verification

The browser tier drives the installed Google Chrome through Playwright (`channel='chrome'`), so Chrome must be
present; `playwright install` is not needed for that channel.

```bash
.venv/bin/python -m pytest -m 'not browser and not slow' -q      # fast tier
.venv/bin/python -m pytest -m browser -q -n 16 --dist worksteal   # browser tier
.venv/bin/python -m pytest -m slow -q -n 0                       # slow tier, serial
.venv/bin/ruff check packages tests conftest.py                  # must exit 0
scripts/test_module.sh core|validation|pdc [fast|browser|slow]    # one distribution's tests
.venv/bin/python -m pytest packages/core/tests -q                 # one tree, all tiers (likewise validation/pdc)
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
