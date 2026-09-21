# Detergent MD project guide

The local dashboard runs AA-only simulations from compatible molecule directories and AA→CG parameterization for any molecule with a compatible AA topology. The packaged DDM example (`molecules/DDM`) is a worked reference. The broader membrane-protein workflow and the micelle builder remain paused project goals; see [the roadmap](../README.md#roadmap).

Read [DDM calibration](DDM_CALIBRATION.md) for scientific results and bonded-workspace limitations before changing DDM scoring, fitting, or carbohydrate mapping.

## Start and develop

From the repository root:

```bash
dashboard/.venv/bin/python -m dashboard
```

Open http://127.0.0.1:5000. Run one coordinator per workspace. The historical dashboard/.venv/bin/python dashboard/app.py command remains supported.

Check active simulation and analysis jobs and worker leases before restarting. Stored process IDs must never be signalled as if owned by a new coordinator.

## Source ownership
dashboard/app.py constructs the application. execution/ owns coordination and stage execution:
* execution/cg_adapter.py — generic CG stage pipeline
* execution/aa_workflow.py — AA-only stage pipeline
* execution/cg_workflow.py — molecule naming for CG runs
* execution/stages.py — declarative stage dataclass
* execution/admission.py — run-type admission rules
* execution/stage_io.py — environment, tool probes, MDP edits
* execution/coordinator.py — job lifecycle, workers, admission, recovery
* execution/analysis_coordinator.py — derived analysis jobs and immutable outputs
* execution/manifest.py — stage and run manifest helpers

models/ owns molecular definitions; analysis/ owns derived calculations; web/ owns routes and browser code. CLI utilities live in dashboard/cli/. HTTP URLs and browser storage keys remain stable through the source reorganization.

dashboard/README.md describes source ownership in detail and lists test commands.

## Environment
The interpreter lives in dashboard/.venv/. Existing virtual environments cannot be moved because launchers include absolute paths. Scientific resources and the local Fast_Forward package live under resources/. Fresh setup:

```bash
python -m venv --system-site-packages dashboard/.venv
dashboard/.venv/bin/python -m pip install --no-build-isolation --no-deps ./resources/parameterizers/fast_forward
```

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

**Clone** creates a new attempt with changed settings. Retry preserves failed-attempt identity and settings in a new job, rejecting changed canonical molecule inputs. Resume verifies saved inputs and upstream output hashes, then copies only reusable stages into a new attempt; it never overlays a failed attempt. Legacy jobs without original input hashes can be cloned but cannot safely resume.

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

Scripts live in dashboard/execution/scripts/. Only scientific assets (SwissParam, CHARMM36, Martini, MDP/water templates) are copied from local resource folders. No ENAP molecule or script is used. GROMACS 2026 TPRs are kept for simulation; analysis uses supported ligand GRO inputs with matching trajectories.

Set up the isolated tool installation once from the repository root:

```bash
python -m venv --system-site-packages dashboard/.venv
dashboard/.venv/bin/python -m pip install --no-build-isolation --no-deps ./resources/parameterizers/fast_forward
```

Readiness invokes each tool's help to check imports as well as executable discovery. Run manifests record resolved tool paths, versions, and input/script hashes. Missing dependencies block execution rather than triggering installation inside a simulation.

5_assessment/validation.json records frame and atom counts, finite coordinates, AA/mapped COG agreement, and actual comparison reports. Inspect plots and SASA curves through the artifact browser. Capture AA snapshots uses molecule-whole ligand coordinates in new runs. Completion means the execution checks passed; scientifically_validated remains false.

## Dashboard workspace
The web UI is a single page with four tabs.

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
Manages versioned bonded states for a selected mapping. Create, inspect, and revise states before using one in a simulation. States store exact mapping identity, source fit provenance, revision history, and the complete topology they will run. Saving as new preserves the source state; in-place revision requires the current revision number and appends one new revision.

### Run controls and persistence
Delete is available only for completed, failed, or cancelled runs. The server checks that no current worker owns the run, removes its run directory and console log, then atomically removes its job record. If file cleanup fails, the record remains available for retry. Deletion is irreversible and confirmed in the browser.

Cancellation sets "Cancelling…" until the worker confirms process termination. The worker terminates only subprocess groups it created, escalating to kill when necessary. Saved PIDs from older sessions are never signalled. Runs whose workers are not owned by the current server cannot be controlled by it.

Retry creates a new run ID after readiness checks; original logs and simulation outputs stay intact. Job updates use SQLite transactions; immutable model and review records use atomic JSON replacement. Stage failures and cancellations are recorded in manifests.

JSON and log endpoints are under /api/jobs, /api/readiness, and /api/mappings. Mapping edits are stored in the configured workspace's mapping_drafts/ directory; original candidates stay under the canonical molecule source.

### Mapping exports and diagrams
Each candidate can export .ndx, .map, .gro, or a ZIP containing all three plus candidate metadata, source hash, and validation report. All files use matching bead IDs B01, B02, …; original display names remain in model.json. This avoids GRO name truncation and Fast_Forward's restriction to alphanumeric bead identifiers. Missing, repeated, unknown, or hydrogen assignments block export. Size and connectivity findings remain visible and recorded as review issues.

The .map header is [ molecule ] LIG1 <molecule_name>, as required by Fast_Forward. The .gro frame is calculated from equal-weight heavy-atom COGs, converted from ångströms to nm, and has no periodic box. These are review artifacts, not fitted parameters or a ready-to-run system. Original atom indices refer to the matching SwissParam ligand-only order.

RDKit, already present in the local environment, draws the 2D structure from SwissParam MOL2 after checking atom names/order and bonds against PDB and ITP. Circle radii represent the 2D extent of assigned atoms, not Martini physical radii. Diagrams update with mapping edits and export as self-contained SVG.

See FAST_FORWARD_ALIGNMENT.md for the tutorial comparison, compatibility decisions, and scientific validation still required.

### Analysis evidence
POST /api/jobs/<id>/observables reads the mapped trajectory and fitted ITP, excludes defined interactions, and writes analysis/unparameterized_observables.json with units, frame count, means, standard deviations, and 5th/95th percentiles. The dashboard exposes this from the Analysis graphs section.

POST /api/jobs/<id>/surfaces runs the local GROMACS sasa -q command on the energy-minimized AA structure and mapped CG frame, preserving both source PDB surfaces, SASA XVG files, checksums, parameters, and an XY comparison SVG. This is a geometric comparison only and remains scientifically unvalidated.

POST /api/jobs/<id>/stability records LINCS warning counts from stage logs, immutable trajectory checksums, and the actual local gmx check exit status/output tail in analysis/numerical_stability.json. Reports are diagnostic and do not approve a model.

POST/GET /api/jobs/<id>/targets stores schema-versioned transfer and partition free energies and other supported detergent properties with units, uncertainty, conditions, and citation. Optional measured values produce standardized residuals; absent measurements remain absent.

POST /api/jobs/<id>/refinement-score persists a versioned evidence breakdown in analysis/refinement_score.json, retaining native metric scales and explicitly listing missing evidence. The dashboard exposes this action; it is not an automatic ranking or scientific approval.

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

Optional process parallelism is provided by requirements-dashboard-tests.txt. Install it with dashboard/.venv/bin/python -m pip install -r requirements-dashboard-tests.txt. Then use -n 4 for the fast suite, -n 2 for browser tests, and -n 1 for the slow marker:

```bash
dashboard/.venv/bin/python -m pytest -m 'not browser and not slow' -n 4 -q
dashboard/.venv/bin/python -m pytest -m browser -n 2 -q
dashboard/.venv/bin/python -m pytest -m slow -n 1 -q
```
Serial pytest commands require no additional runner plugin. Threaded execution is unsafe because tests patch shared dashboard module state.

## Focused validation
```bash
dashboard/.venv/bin/python -m pytest \
  tests/dashboard/unit/test_bonded.py \
  tests/dashboard/unit/test_bonded_states.py \
  tests/dashboard/integration/test_mapping_exports.py \
  tests/dashboard/integration/test_draft_execution.py \
  -q
node --check dashboard/web/static/js/main.js
```
Browser acceptance uses installed Playwright and Chrome:

```bash
dashboard/.venv/bin/python -m pytest tests/dashboard/browser -v
```

The suite exercises polling without state loss, mapping edits and draft persistence, console pause/follow/copy/download, and mobile layout using isolated test jobs. Worker tests cancel an actual short-lived subprocess without running MD.
