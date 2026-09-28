# Detergent MD project guide

The local dashboard runs AA-only simulations from compatible molecule directories and AA→CG parameterization for any molecule with a compatible AA topology. The packaged DDM example (`molecules/DDM`) is a worked reference. The broader membrane-protein workflow and the micelle builder remain paused project goals; see [the roadmap](../README.md#roadmap).

Read [DDM calibration](DDM_CALIBRATION.md) for scientific results and bonded-workspace limitations before changing DDM scoring, fitting, or carbohydrate mapping. For the carbohydrate validation panel, target registry, Sucrose diagnostic procedure, and paper-scale evidence boundary, read [Carbohydrate Validation Operations](research/2026-09-24-carbohydrate-validation-operations.md) and [Martini 3 carbohydrate validation](research/2026-09-24-martini3-carbohydrate-validation.md).

## Start and develop

From the repository root:

```bash
dashboard/.venv/bin/python -m dashboard
```

Open http://127.0.0.1:5000. Run one coordinator per workspace. The historical dashboard/.venv/bin/python dashboard/app.py command remains supported.

Check active simulation and analysis jobs and worker leases before restarting. Stored process IDs must never be signalled as if owned by a new coordinator.

## Source ownership
dashboard/app.py constructs the application. execution/ owns coordination and stage execution:
* execution/adapters/cg.py — generic CG stage pipeline
* execution/adapters/aa.py — AA-only stage pipeline
* execution/adapters/cg_names.py — molecule naming for CG runs
* execution/adapters/composition.py — molecule-combination runs
* execution/adapters/micelle.py — protein-detergent micelle prototype (paused)
* execution/stages.py — declarative stage tables
* execution/workflow.py — shared stage execution, provenance and resumable state
* execution/environment.py — environment, tool probes, MDP edits
* execution/coordination/coordinator.py — job lifecycle, workers, admission, recovery
* execution/coordination/worker.py — subprocess stage execution
* execution/coordination/admission.py — run-type admission rules
* execution/coordination/analysis_coordinator.py — derived analysis jobs and immutable outputs
* execution/coordination/resources.py, temporary.py — limits and scratch lifetime
* execution/coordination/manifest.py — stage and run manifest helpers

models/ owns molecular definitions, grouped by concept: mappings/ (candidate schema, storage, context, graph, exports, suggestions, references, depiction over a public facade), bonded/ (interaction library, state records, generation), sugars/ (ring recognition, coordinate construction, constrained topology, validation), compositions/ (reference-backed assembly and immutable Molecule Combination snapshots), molecules/ (AA input discovery, model registry, evidence gates, draft models, packaged DDM source), plus repository.py (JSON record storage) and catalog.py (CG model catalogue). analysis/ owns derived calculations: validation/ (targets, geometry, transfer free energy, osmotic pressure, reports) and runs/ (references, observability, refinement, surfaces), with metadata.py and worker.py at the root. web/ owns HTTP routes — one module per concept under web/routes/ — templates and browser code. CLI utilities live in dashboard/cli/. HTTP URLs and browser storage keys remain stable through the source reorganization.

dashboard/README.md describes source ownership in detail and lists test commands.

## Environment
The interpreter lives in dashboard/.venv/. Existing virtual environments cannot be moved because launchers include absolute paths. Scientific resources and the local Fast_Forward package live under resources/. Fresh setup, from the repository root:

```bash
python -m venv --system-site-packages dashboard/.venv
git clone --depth 1 https://github.com/Martini-Force-Field-Initiative/fast_forward resources/parameterizers/fast_forward
git -C resources/parameterizers/fast_forward apply "$PWD/resources/patches/fast_forward-dihedral-membership.patch"
dashboard/.venv/bin/python -m pip install --no-build-isolation --no-deps ./resources/parameterizers/fast_forward
```

Fast_Forward also needs lmfit, cgsmiles, matplotlib, MDAnalysis, numba, pbr, pysmiles, tqdm and vermouth; `--no-deps` installs the package alone, so add any that are missing (`pip install lmfit cgsmiles` pulls asteval, dill and uncertainties with lmfit).

`resources/parameterizers/` is gitignored, which means the vendor tree and the installed package are both outside version control. A rebuilt virtualenv therefore loses the local patch and silently runs pristine upstream, where the `dihedrals` getter reports an empty system for every molecule and no angle is ever recognised as part of a dihedral, so restricted bending is never assigned. The tracked patch `resources/patches/fast_forward-dihedral-membership.patch` is the record, `unit/test_carbohydrates.py` fails when the installed fitter is not the vendored source, and the run manifest records the sha256 of the fitted `interaction_fit.py`. The patch was written against upstream commit `718ce2de`; tags `v0.0.2` and `v0.0.3` carry both defects too, so no tag can be pinned instead of patching.

Readiness checks tool executables and imports before launch. Every run captures resolved tool paths, versions, commands, environment, and input/script hashes. No package installation happens inside simulation jobs.

## Paths, state, canonical inputs
dashboard/paths.py owns application path configuration. A workspace contains jobs.sqlite3, runs/, uploads/, mapping_drafts/, bonded_states/, model_registry/, and compositions/. SQLite is the only live job store; old JSON job snapshots are not read.

The checkout selects workspace/dashboard/ in config/dashboard-paths.json. DASHBOARD_WORKSPACE=/absolute/path overrides that selection for an isolated instance. With neither setting, the legacy dashboard/ workspace is supported. Paths resolve at application construction; changing configuration requires a restart after all workers stop.

molecules/, references/, and resources/ remain canonical input sources. Reference indexing copies metadata and hashes; it does not make another canonical copy of the original reference files. Each run takes immutable snapshots of the inputs and executable helpers it actually used.

Scientific reports live under reports/dashboard/; acceptance evidence lives under reports/validation/. Historical prototypes are under docs/design/prototypes/. Archived development artifacts and relocation inventories are under archive/dashboard-development-20260917/. Root-level runs/ retains unrelated standalone benchmark output.

## Run storage and lifecycle
New attempts use this layout beneath the configured workspace:

```text
runs/<id>/
  manifest.json
  inputs/                 # prepared inputs and executable snapshots, checksummed
  stages/                 # separate execution directories per stage
  logs/                   # console.log plus separate stage logs
  analyses/<kind>/<request-key>/<attempt-id>/
    request.json
    manifest.json
    console.log
    sources.json
    progress.json
    result.json
    output/<source-key>/
```
Old flat layouts remain readable. Original snapshots and stage names are retained; source-package moves do not rewrite captured scripts or historical manifests.

**Clone** creates a new run with changed settings. Retry preserves failed-attempt identity and settings in a new job, rejecting changed canonical molecule inputs. Resume keeps the same run ID and database row and executes the current files already present in the selected and downstream `stages/` directories. It uses the manifest's completed-stage prefix to choose the restart point, without hashing or restoring files from `inputs/`; edits made after the original attempt therefore take effect on resume. The prior manifest and job metadata are recorded under `resume_history/`, while stage directories and their existing scratch files remain in place. Prior analyses are marked superseded because a rerun may change their source trajectories. Legacy copied-resume jobs remain readable; new resume requests continue the selected run in place.

Cancellation targets process groups created by the current coordinator. Recovery marks interrupted active jobs and analyses failed. Orphan subprocess leases continue to block unsafe reuse and deletion. Logs and stage records retain commands, environment, start/end times, exit codes, hashes, and failure details.

SQLite transactions protect job updates and attachment/deletion relationships. Completed CG consumers keep their AA source protected from deletion. A waiting CG consumer occupies no simulation slot. AA failure blocks its waiting consumers; AA cancellation cancels them.

## AA-only and shared-reference protocol
See the **molecule directory contract**. Each molecule folder contains a matching ITP and GRO or PDB pair, optionally in nested SwissParam output directories, plus local topology dependencies. Missing metadata.json is generated without overwriting user metadata. PDB conversion happens in immutable run preparation; original coordinates remain unchanged. Checks reject traversal, symlinks, missing includes, unsupported directives, inconsistent atom order, and incompatible force fields. GROMACS preprocessing verifies parameter resolution.

charmm36-single-solute-v1 accepts one pre-parameterized neutral or charged solute with CHARMM36 July 2022 and CHARMM TIP3P. Stages are solvation, neutralization, minimization, NVT, NPT, NPT production, and reference publication. Charged systems receive SOD/CLA counterions; no extra salt is added. Defaults: 300 K, 1 bar, 1.5 nm padding, 100 ps NVT, 1000 ps NPT, 10000 ps production, 10 ps trajectory interval, recorded random seed. Simulation scripts use eight CPU threads. These defaults do not establish equilibration or convergence.

AA-only requires no CG mapping or Fast_Forward. New AA–CG launches create a separate AA source and waiting CG consumer, or attach an eligible completed source. /api/references lists completed technically eligible AA-only jobs; combined legacy runs are not relabelled or offered as new AA-only sources. Inherited AA settings are checked server-side and locked in the form.

Publication retains full-system GRO/TPR/XTC/CPT/EDR/log outputs and solute GRO/TPR/XTC. 07_reference/reference.json records atom order, finite frames, time coverage, composition, diagnostics with units, protocol, and artifact hashes. CG consumers read the shared source trajectory and write only their own mapped and CG products. Analysis scratch copies are temporary and counted in resource admission.

Completion, technical reference eligibility, and scientific validation are separate. The short AA adapter acceptance report demonstrates execution and sharing; it does not validate a molecular model.

## DDM draft execution test
In New run, choose DDM draft smoke test under Execution. This explicit option uses the run-local mapping_candidate_smoke.json: a connected 11-bead draft, covering all 35 heavy atoms with one documented S-bead size exception. C1 tail beads follow the local dodecane reference; polar bead assignments are uncalibrated chemical guesses. These are software test inputs, not a validated DDM model. Standard parameterization retains its reviewed-model gate.

The profile runs 10 ps NVT equilibration and 50 ps NVT production for both AA and CG, in pure water at 300 K, using one MPI rank and four OpenMP threads. It runs AA → ff_map → ff_inter → CG → ff_assess → SASA with checks at each handoff. Every run is new; retry preserves the draft profile and original data.

Scripts live in dashboard/execution/scripts/. Only scientific assets (SwissParam, CHARMM36, Martini, MDP/water templates) are copied from local resource folders. No ENAP molecule or script is used. GROMACS 2026 TPRs are kept for simulation; analysis uses supported ligand GRO inputs with matching trajectories. Maintained AA and CG `mdrun` launchers request CUDA offload on GPU 0 for nonbonded and PME work (`-nb gpu -pme gpu -pmefft gpu`) with thread pinning; verify the recorded command and GROMACS log when diagnosing hardware selection.

Set up the isolated tool installation once from the repository root:

```bash
python -m venv --system-site-packages dashboard/.venv
dashboard/.venv/bin/python -m pip install --no-build-isolation --no-deps ./resources/parameterizers/fast_forward
```

Readiness invokes each tool's help to check imports as well as executable discovery. Run manifests record resolved tool paths, versions, and input/script hashes. Missing dependencies block execution rather than triggering installation inside a simulation.

5_assessment/validation.json records frame and atom counts, finite coordinates, AA/mapped COG agreement, and actual comparison reports. Inspect plots and SASA curves through the artifact browser. Capture AA snapshots uses molecule-whole ligand coordinates in new runs. Completion means the execution checks passed; scientifically_validated remains false.

## Dashboard workspace

### Molecule Combination

The Molecule Combination tab builds an immutable coarse-grained candidate by
combining one of the 15 reference-backed Martini sugar fragments with a named
carbon-tail recipe. The browser submits identifiers and choices only; the
server reparses `references/martini_v3.0.0_sugars_v2.itp`, checks the source
hash, applies the selected linkage profile, and writes a new composition
snapshot. The two initial recipes are `Linear C1` and `Linear C1/C2 terminal`.
Saved records are reported as `candidate-unvalidated` and are never promoted to
scientific validation by a successful preview, save, or screening run.

Saved compositions are available in CG Bond Interactions through the unified CG
model catalog. `cg_composition` runs are independent of the AA-to-CG workflow
and contain only CG simulation, CG assessment, and CG SASA stages; they do not
fabricate or require an AA reference. Composition artifacts and their hashes
are immutable, so changing a choice creates another record.
The web UI is a single page with five tabs.

### Runs
Background polling updates individual status fields every five seconds. Forms, expanded details, mapping edits, and scroll position are not rebuilt. Terminal runs can be manually deleted from their run card; active workers are protected. Tabs, form values, and mapping drafts are remembered in browser storage. Elapsed time is reported only when recorded; ETA is shown only when present in current GROMACS output. Legacy runs without timestamps show "Not recorded".

Each run card shows the six or seven workflow stages from its manifest and indexes files created inside the run directory. Artifact links are path-checked; SVG files are previewed in the card. When an AA 3-run.xtc and matching 3-run.tpr exist, Capture AA snapshots writes first/middle/last PDB coordinates and SVG XY review images under snapshots/. Snapshot generation never invents frames; old or incomplete runs report the missing trajectory inputs.

Analysis graphs expand inline: ff_assess PNG plots and a Plot SASA action that generates an image from measured AA/CG XVG data. Original XVG data are preserved; SVG artifacts remain previewable. Reads use byte offsets and bounded chunks; the display keeps up to 256 KB.

### Console
Select a run, pause display updates, copy the visible excerpt, or download its full log. New runs download a stage-log ZIP. Pausing affects the display only.

### New run
Shows the exact packaged input paths, executable availability, and missing workflow requirements. The same readiness check runs server-side on submission and retry. Unsupported methods and incomplete workflows cannot be queued. The dashboard accepts registered molecule directories; arbitrary uploads and SMILES are not offered.

Exposes AA/CG equilibration and production durations, temperature, trajectory output interval, and SASA probe radius. Each value has a Default button. Defaults come from the packaged Fast_Forward/CHARMM/Martini MDPs; the draft profile substitutes its bounded 10/50 ps diagnostic durations. Submitted settings are range-checked, converted to stage-specific nsteps, recorded in the manifest, and applied only inside that run directory.

Lists compatible completed AA runs for AA reference reuse. Selecting one copies its identity-checked ligand reference into the new run, records its ID and checksum, and marks AA reference as skipped; source artifacts are never modified.

### CG Bead Assignment
Compare two candidates against the original DDM coordinates and bond graph. Drag or use arrow keys to rotate the atom view; edit bead names, sizes, and atom indices; add or remove beads; export JSON or save a new draft. The 2D chemical diagram shows stereochemistry and bead circles over assigned atoms; it can be downloaded as standalone SVG. A new draft never overwrites its parent and remains unvalidated.

Mapping checks cover heavy-atom coverage, duplicate assignments, unknown atoms, hydrogens, empty groups, disconnected groups, nominal bead sizes (R=4, S=3, T=2), and the ±1 per 10 heavy-atom mismatch guideline. Branching/shape exceptions need scientific justification. These checks do not validate bead chemistry, symmetry, bonded parameters, or physical behaviour. The original DDM candidates have structural findings; the connected smoke draft fixes coverage and connectivity but is still not a production model.

### CG Bond Interactions
Select a saved CG mapping and then one of the bonded states belonging to that mapping. The workspace shows the current interaction terms and a local Plotly 3D connectivity diagram with physical beads only. Select at most two beads in the diagram and use **Create interaction** to add a draft bond; the interaction table exposes the GROMACS function and labeled parameters for editable bonds, angles, and dihedrals. Constraints and virtual-site records remain read-only.

**Generate automatic bonded state** does not run Fast Forward. It creates a non-persistent draft with a local deterministic reference-consensus algorithm: mapping connectivity supplies candidate bonds, angles, and length-three paths; the generator indexes read-only CG ITPs under `references/` (explicit atomistic `references/**/AA/` trees are excluded), matches bead-type sequences with molecule/detergent-specific sources preferred, and records source paths, line numbers, hashes, selected functions, and parameters. Reference bonds and angles are used directly when available. Unmatched bonds use mapped bead-center distance with a provisional force constant, unmatched angles use a geometry-derived harmonic term, and dihedrals are emitted only when a reference topology supplies a matching term. Conflicting reference signatures are resolved deterministically and reported in per-term provenance; the generated topology keeps mapping constraints, virtual sites, and exclusions. **Save as new state** creates a new immutable state and leaves the selected state unchanged. The button is disabled until the draft has editable terms and unsaved changes. **Run short CG validation** queues a bounded smoke run for a saved state, while **Delete state** requires confirmation and is blocked when runs reference that state. The five workspace actions are the supported bonded-state workflow; mapping exports and approval controls are handled elsewhere.

### Run controls and persistence
Delete is available only for completed, failed, or cancelled runs. The server checks that no current worker owns the run, removes its run directory and console log, then atomically removes its job record. If file cleanup fails, the record remains available for retry. Deletion is irreversible and confirmed in the browser.

Cancellation sets "Cancelling…" until the worker confirms process termination. The worker terminates only subprocess groups it created, escalating to kill when necessary. Saved PIDs from older sessions are never signalled. Runs whose workers are not owned by the current server cannot be controlled by it.

Resume continues the existing run ID after lease, dependency, and resource checks. The selected and downstream stage directories must exist and must not be symlinks; their current launchers, inputs, and outputs are executed as found. Retry and Clone create new run IDs after readiness checks; original logs and simulation outputs stay intact. In-place resume records its prior manifest and job metadata in `resume_history/` without replacing current stage directories. Job updates use SQLite transactions; immutable model and review records use atomic JSON replacement. Stage failures and cancellations are recorded in manifests.

JSON and log endpoints are under /api/jobs, /api/readiness, /api/mappings, /api/compositions, and /api/cg-models. Mapping edits are stored in the configured workspace's mapping_drafts/ directory; original candidates stay under the canonical molecule source.

### Mapping exports and diagrams
Each candidate can export .ndx, .map, .gro, or a ZIP containing all three plus candidate metadata, source hash, and validation report. All files use matching bead IDs B01, B02, …; original display names remain in model.json. This avoids GRO name truncation and Fast_Forward's restriction to alphanumeric bead identifiers. Missing, repeated, unknown, or hydrogen assignments block export. Size and connectivity findings remain visible and recorded as review issues.

The .map header is [ molecule ] LIG1 <molecule_name>, as required by Fast_Forward. The .gro frame is calculated from equal-weight heavy-atom COGs, converted from ångströms to nm, and has no periodic box. These are review artifacts, not fitted parameters or a ready-to-run system. Original atom indices refer to the matching SwissParam ligand-only order.

RDKit, already present in the local environment, draws the 2D structure from SwissParam MOL2 after checking atom names/order and bonds against PDB and ITP. Circle radii represent the 2D extent of assigned atoms, not Martini physical radii. Diagrams update with mapping edits and export as self-contained SVG.

Carbohydrate validation is separate from mapping approval and is queued through the API rather than from a dashboard panel: `POST /api/jobs/<id>/carbohydrate-validation` takes the published `tc4` representation or the deterministic `physical_only_ring_constrained` derivative, which removes TC4 sites while retaining physical bead ownership and 1.15-scaled ring constraints. The controls that used to offer this from CG Bead Assignment were removed; the analysis, the queue route and the report endpoints are unchanged. A setup check is diagnostic-only. An evidence run requires cited targets and paper-aligned sampling before it can report `evidence_complete`.

See FAST_FORWARD_ALIGNMENT.md for the tutorial comparison, compatibility decisions, and scientific validation still required.

### Analysis evidence
POST /api/jobs/<id>/observables reads the mapped trajectory and fitted ITP, excludes defined interactions, and writes analysis/unparameterized_observables.json with units, frame count, means, standard deviations, and 5th/95th percentiles. The dashboard exposes this from the Analysis graphs section.

POST /api/jobs/<id>/surfaces runs the local GROMACS sasa -q command on the energy-minimized AA structure and mapped CG frame, preserving both source PDB surfaces, SASA XVG files, checksums, parameters, and an XY comparison SVG. This is a geometric comparison only and remains scientifically unvalidated.

POST /api/jobs/<id>/stability records LINCS warning counts from stage logs, immutable trajectory checksums, and the actual local gmx check exit status/output tail in analysis/numerical_stability.json. Reports are diagnostic and do not approve a model.

POST/GET /api/jobs/<id>/targets stores schema-versioned transfer and partition free energies and other supported detergent properties with units, uncertainty, conditions, and citation. Optional measured values produce standardized residuals; absent measurements remain absent.

POST /api/jobs/<id>/refinement-score persists a versioned evidence breakdown in analysis/refinement_score.json, retaining native metric scales and explicitly listing missing evidence. The dashboard exposes this action; it is not an automatic ranking or scientific approval.

POST /api/jobs/<id>/carbohydrate-validation creates an immutable validation analysis attempt for a completed source run. The request records the mapping snapshot, representation mode, tier, target dataset, source hashes, tool versions, and protocol. Its report has the three required evidence keys: `mapped_geometry`, `transfer_free_energy`, and `osmotic_pressure`. Metadata-only or missing target datasets, missing octanol parameters, short trajectories, and incomplete concentration series remain `insufficient_data`; validation never changes mapping approval or production authorization.

### Models, analyses, and browser behavior
Each tab loads its data when activated, including keyboard and direct-link navigation. Shared catalogue requests are deduplicated and cached for ten seconds; saving or deleting models invalidates the relevant cache. Mapping editors retain unsaved edits across tab changes. New run debounces readiness checks and ignores cancelled or superseded responses. Runs pauses polling while another tab is open and refreshes on return.

The full APIs remain available. view=summary on /api/jobs, /api/mappings, and /api/bonded-states returns compact catalogue and polling records; individual record endpoints retain full detail. /api/mappings/context supplies the source molecule and bead types. Mapping validation caches use candidate and source content, so changed scientific inputs invalidate previous results.

Derived analyses use isolated subprocesses, publish immutable outputs, and record actual source hashes, calculation settings, tool versions, and errors.
Unchanged requests reuse completed analysis products.

DDM remains the executable CG example. Standard production retains the reviewed scientific-model gate. Candidate screening requires a saved mapping; deleted historical mapping files are not restored as defaults. Mapping exports, sugar virtual sites, fitting conventions, scoring interpretation, and known bonded UI gaps are documented in DDM calibration and Fast-Forward alignment.

### Resource policy, backup, and rollback
config/dashboard.json controls concurrency, disk headroom, storage reservations, per-run and total limits, and retention review. Usage is monitored, not enforced by a filesystem quota, so it may overshoot between checks. Storage reports never delete automatically. Explicit deletion requires terminal status, no worker lease, and no retained AA-reference consumer. Model cleanup requires a reviewed, hash-verified migration inventory. Preserve unique reports and scientific evidence.

SQLite is authoritative. Back up the database with SQLite's backup facility while the coordinator is stopped, and back up model stores and run directories with it. Old generated state is not migrated into a fresh workspace.

```bash
dashboard/.venv/bin/python -m dashboard.cli.reset_workspace --workspace /absolute/path --confirm
```

The reset command removes only its explicit generated-state list, recreates empty runtime directories, and writes reset-record.json. It refuses active service leases, symbolic-link roots, and missing confirmation. Never switch workspace roots while jobs are active.


Set {"workspace": "/new/workspace"} in config/dashboard-paths.json only after verification, while both workspaces remain stopped. Historical commands and manifests retain their original paths. Console display resolves recorded stage logs within the selected workspace; references and resume resolve run IDs there.

For the 2026-09 reorganization, original runtime stores are retained in archive/dashboard-development-20260917/runtime-original/; the hash/database proof is archive/dashboard-development-20260917/workspace-migration.json. To roll back the workspace selection, stop the dashboard and select that archive directory. Preserve the current workspace first: the archived original does not contain work created after cutover.

## Paused work
### Micelle builder
A native spherical single-detergent Martini micelle builder around membrane proteins. Paused at the user's request. The initial core (python -m micelle build --template ... --aggregation-number N --seed S --output DIR) validates a registered detergent template, creates a deterministic spherical center lattice, and writes geometry diagnostics. python -m micelle validate build/diagnostics reruns the checks.

The package is intentionally marked experimental until protein-aware packing, topology dependency closure, solvent and ions, GROMACS preprocessing, and dashboard submission are completed. It must not be used to claim a validated scientific model.

Approved design: docs/superpowers/specs/2026-09-14-detergent-micelle-builder-design.md.

Implementation plan: docs/superpowers/plans/2026-09-14-detergent-micelle-builder.md.

### Membrane-protein workflow
The broader memembed -> martinize -> insane -> cg2at chain is a project goal. Historical assets are under archive/MemProtMD/. Nothing in the maintained dashboard/ tree depends on it.

## Verification
```bash
dashboard/.venv/bin/python -m pytest -m 'not browser and not slow' -q
dashboard/.venv/bin/python -m pytest -q
dashboard/.venv/bin/python -m pytest -m 'not browser' -q
dashboard/.venv/bin/python -m pytest -m browser -q
```

Tests live under tests/dashboard/{unit,integration,browser}. Shared fixtures redirect every writable store; tests generate their own mapping candidates. The suite checks commands, lifecycle and recovery, quota and dependency guards, parsing, API contracts, and browser interactions without long simulations. Browser tests use installed Playwright and Chrome, temporary databases, and loopback servers.

Optional process parallelism is provided by requirements-dashboard-tests.txt. That file also carries the test-only imports `playwright` (browser tests) and `vermouth` (sugar topology), so install it before running the full suite. Install it with dashboard/.venv/bin/python -m pip install -r requirements-dashboard-tests.txt. Then use -n 4 for the fast suite, -n 2 for browser tests, and -n 1 for the slow marker:

```bash
dashboard/.venv/bin/python -m pytest -m 'not browser and not slow' -n 4 -q
dashboard/.venv/bin/python -m pytest -m browser -n 2 -q
dashboard/.venv/bin/python -m pytest -m slow -n 1 -q
```
Serial pytest commands require no additional runner plugin. Threaded execution is unsafe because tests patch shared dashboard module state.

### Environment gaps

Measured on this checkout with `dashboard/.venv/bin/python -m pytest -m 'not browser and not slow' -q -p no:cacheprovider`: **309 passed, 19 deselected, no skips**.

The two tests that used to skip by design on a missing vendor tree now run, because the Fast_Forward source tree is provisioned and patched:

| Test | Previously | Now |
| --- | --- | --- |
| `integration/test_mapping_exports.py::test_fast_forward_parser_reads_names_and_order` | skipped: `map_file_parers.py` absent | passes against the vendored source |
| `unit/test_carbohydrates.py::test_ff_dihedral_membership_controls_restricted_bending` | skipped: `interaction_fit.py` absent | passes; it pins both local patches |

Both still resolve their path through `tests/dashboard/tool_paths.py` instead of a literal path, so a missing vendor tree skips with a reason rather than failing for a reason unrelated to the code under test. Provisioning is not the whole story on its own: pristine upstream passes the parser test and fails the membership test, which is why the tracked patch is part of setup (see Environment). `unit/test_carbohydrates.py::test_installed_fast_forward_is_the_vendored_source` fails when the installed package is not the vendored source, so a rebuilt virtualenv cannot silently revert to upstream behaviour.

Measured toolchain on this machine: GROMACS 2026.3 at `/usr/local/gromacs/2026.3/bin/gmx` (CUDA, OpenMPI), Fast_Forward 0.0.1.dev1 built from the patched vendor tree (fitter sha256 `0ab9252d…`), MDAnalysis 2.9.0, numba 0.61.2, vermouth 0.15.0. `config/tools.json` declares those tools and `dashboard/execution/tools.py` is the one resolver: a declared path is verified executable before it is used, a declared command name is resolved on the composed search path (the workspace virtualenv, the declared tools' directories, then the inherited `PATH`), and a declaration that cannot be honoured resolves to nothing rather than to a substitute. Readiness reports such a declaration as a check, not a blocker. The guide's earlier text named a hard-coded `~/Downloads/gromacs-2026.0` build; that path appears nowhere in the code now. The same file pins the Fast_Forward source revision (`fast_forward_source`, `fast_forward_commit` = `61e407e6…`, the local commit carrying the two dihedral fixes on top of upstream `718ce2de`); each run's tool report records it as `fast_forward_source`, and the vendored-source guard in `unit/test_carbohydrates.py` fails when the checkout or its cleanliness disagrees with the pin.

`unit/test_mapping_references.py` derives the expected reference ranks from the sources present rather than asserting ranks 1-3: `references/M3-Small-Molecules/` and `references/M3-Bible/` are partial clones, so `models/martini_v3.0.0_small_molecules_v1.itp` and `src/MartiniCGSmilesDB_v6.xlsx` are missing and `load_index` reports rank 1 only (verified: 1 source, 50 records, no diagnostics). Provisioning those files widens the index without changing the test.

`vermouth` was missing from requirements-dashboard-tests.txt until this review and accounted for two further failures in `unit/test_carbohydrates.py`.

## Focused validation
```bash
dashboard/.venv/bin/python -m pytest \
  tests/dashboard/unit/test_bonded.py \
  tests/dashboard/unit/test_bonded_states.py \
  tests/dashboard/integration/test_mapping_exports.py \
  tests/dashboard/integration/test_mapping_workspace_api.py \
  -q
node --check dashboard/web/static/js/main.js
```
Browser acceptance uses installed Playwright and Chrome:

```bash
dashboard/.venv/bin/python -m pytest tests/dashboard/browser -v
```

The suite exercises polling without state loss, mapping edits and draft persistence, console pause/follow/copy/download, and mobile layout using isolated test jobs. Worker tests cancel an actual short-lived subprocess without running MD.
