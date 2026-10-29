# Detergent MD project guide

The local dashboard runs AA-only simulations from compatible molecule directories, AA→CG parameterization for any molecule with a compatible AA topology, a protein-detergent complex pipeline (`pdc`), and a sugar osmotic-pressure series. The packaged DDM example (`molecules/DDM`) is a worked reference. The micelle builder remains paused; see [the roadmap](../README.md#roadmap).

Read [DDM calibration](DDM_CALIBRATION.md) for scientific results and bonded-workspace limitations before changing DDM scoring, fitting, or carbohydrate mapping. For the carbohydrate validation panel, target registry, Sucrose diagnostic procedure, and paper-scale evidence boundary, read [Carbohydrate Validation Operations](research/2026-09-24-carbohydrate-validation-operations.md) and [Martini 3 carbohydrate validation](research/2026-09-24-martini3-carbohydrate-validation.md).

## Start and develop

From the repository root:

```bash
.venv/bin/python -m dashboard
```

Open http://127.0.0.1:5000. Run one coordinator per workspace. The historical .venv/bin/python packages/core/src/dashboard/app.py command remains supported.

Check active simulation and analysis jobs and worker leases before restarting. Stored process IDs must never be signalled as if owned by a new coordinator.

## Source ownership
Three distributions own the sources: `packages/core` is the engine (`detergent-core`, import `dashboard`), and the two
features are `packages/validation` (`detergent-validation`) and `packages/pdc` (`detergent-pdc`). The engine never
imports a feature; a feature imports the engine and registers through `dashboard/features.py`.

The engine (`packages/core/src/dashboard/`):
* app.py constructs the application. features.py discovers a feature and registers its blueprints, run types, analysis
  kinds, workspace and hooks (admission, prepare, create_settings, readiness, run_failed, layout, planned_skips,
  protein_topologies, kind_payload, priority, templates, static, panel_modules, styles); web/sections.py owns the
section order and the `DASHBOARD_TABS` filter.
A feature distribution advertises itself with the `detergent_md.features` entry point, so installing a wheel is
how a dashboard gains a workspace; the engine never imports one.
* execution/ owns coordination and stage execution: adapters/cg.py (generic CG stage pipeline), aa.py (AA-only),
  cg_names.py, composition.py, micelle.py (the micelle build adapter; `micelle/` remains the science owner), stages.py,
  workflow.py, environment.py, and coordination/ (coordinator, worker, admission, analysis_coordinator, resources,
  temporary, manifest).
* models/ owns molecular definitions: mappings/ (candidate schema, storage, context, graph, exports, suggestions,
  references, depiction over a public facade), bonded/, sugars/, compositions/, molecules/ (AA input discovery, model
  registry, evidence gates, draft models, packaged DDM source), repository.py (JSON record storage) and catalog.py.
* analysis/runs/ owns the readers every run type shares: layout.py (registered stage directories, roles, review order,
  topology resolvers), segments.py (registered segmenters), structures.py (the GROMACS structure and CONECT writer),
  statistics.py (block summaries), observability.py, bonded_terms.py, bonded_estimate.py, dihedral_fit.py,
  bartender_fit.py, references.py and figures.py. analysis/validation/carbohydrate_targets.py is the target registry
  that the mapping route and the validation analyses both read. kinds.py keeps the engine's own vocabulary
  (bartender-fit, bonded-cross-check, dihedral-fit, observables, plots, stability); a feature adds its rows.
* web/ owns the shell: the routes every run type shares (runs, mappings, catalog, maintenance, the analyses queue),
  templates/dashboard.html and the shell's static JS. cli/ owns the `detergent-dashboard` and `detergent-import-run`
  console scripts.

detergent-validation (`packages/validation/src/detergent_validation/`): web/routes/ (bonded, osmotic, refinement,
targets, the analyses payload and the comparison/diagnostics endpoints), execution/adapters/osmotic.py with
osmotic_box/osmotic_mdp and the series runner,
analysis/runs/ (mapping_consistency, transferability, overlap, surfaces, refinement, osmotic_pressure, consistency,
draft_geometry),
analysis/validation/ (report, targets, osmotic, geometry, transfer), analysis/sugar_ensemble.py, and kinds.py
(carbohydrate-validation, mapping-consistency, osmotic-pressure, overlap, refinement-score, surfaces, targets).

detergent-pdc (`packages/pdc/src/detergent_pdc/`): execution/adapters/ (pdc, pdc_import, pdc_preparation, pdc_protein,
pdc_placement, pdc_box, pdc_solvation, pdc_assessment), execution/pdc_preview.py, the repository `pdc_*.sh` scripts,
analysis/runs/encapsulation.py, layout.py (stage directories, roles, review order, detergent topology), segments.py
(the pdc segmenter and its markers), topologies.py (the protein's moleculetypes), view.py (the queued-run skip
preview), and web/routes/pdc.py (setup, system, micelle build). The panels' markup and browser code still live in the
shell (`templates/dashboard.html`, `static/js`); lifting them is the remaining front-end split.

### Adding a distribution
A feature is a distribution that advertises one entry point; installing it is the whole act of adding it to a
dashboard:

```toml
[project.entry-points."detergent_md.features"]
validation = "detergent_validation.feature"
```

The target is a module exporting `FEATURE = dashboard.features.Feature(...)` (or the `Feature` object itself). The
record is the contract: the blueprints to serve, the run types and their protocol builders, the analysis kinds it
owns, one workspace with its panels/blurbs/tab ids, recorded-code prefixes, code roots for the analysis fingerprint,
and the hooks its run type needs (admission, prepare, create_settings, readiness, run_failed, layout, planned_skips,
protein_topologies, kind_payload). `Feature.priority` decides registration order, because the shell opens on the first
workspace registered. Discovery reads installed metadata; `KNOWN` in `features.py` is only the fallback for an
editable checkout whose metadata predates the entry point, and a broken entry point fails at start-up rather than
disappearing. A feature's browser surface is its own too: `templates` joins the Jinja search path, `static` is served
under `url_for('feature_asset', ...)`, `styles` are linked before the shell's panel sheets, and `panel_modules` maps a
panel's DOM id to an ES module and its factory. The shell includes every registered `panels/<id>.html` and boots the
modules it was handed, so an install without a feature downloads neither its markup nor its scripts. Two surfaces are
still shared shell today: the New run form and the Run view carry the protein-detergent detail blocks in the engine.

The source-ownership list above is the maintained map; `dashboard/README.md` carries only dashboard-local setup notes.

## Environment
The interpreter lives in .venv/ at the checkout root. Existing virtual environments cannot be moved because launchers include absolute paths. Scientific resources and the local Fast_Forward package live under resources/. Fresh setup, from the repository root:

```bash
python -m venv --system-site-packages .venv
git clone --depth 1 https://github.com/Martini-Force-Field-Initiative/fast_forward resources/parameterizers/fast_forward
git -C resources/parameterizers/fast_forward apply "$PWD/resources/patches/fast_forward-dihedral-membership.patch"
.venv/bin/python -m pip install --no-build-isolation --no-deps ./resources/parameterizers/fast_forward
```

Fast_Forward also needs lmfit, cgsmiles, matplotlib, MDAnalysis, numba, pbr, pysmiles, tqdm and vermouth; `--no-deps` installs the package alone, so add any that are missing (`pip install lmfit cgsmiles` pulls asteval, dill and uncertainties with lmfit).

`resources/parameterizers/` is gitignored, which means the vendor tree and the installed package are both outside version control. A rebuilt virtualenv therefore loses the local patch and silently runs pristine upstream, where the `dihedrals` getter reports an empty system for every molecule and no angle is ever recognised as part of a dihedral, so restricted bending is never assigned. The tracked patch `resources/patches/fast_forward-dihedral-membership.patch` is the record, `unit/test_carbohydrates.py` fails when the installed fitter is not the vendored source, and the run manifest records the sha256 of the fitted `interaction_fit.py`. The patch was written against upstream commit `718ce2de`; tags `v0.0.2` and `v0.0.3` carry both defects too, so no tag can be pinned instead of patching.

Readiness checks tool executables and imports before launch. Every run captures resolved tool paths, versions, commands, environment, and input/script hashes. No package installation happens inside simulation jobs.

## Paths, state, canonical inputs
dashboard/paths.py owns application path configuration. A workspace contains jobs.sqlite3, runs/, uploads/, mapping_drafts/, parameterizations/, model_registry/, compositions/, proteins/, preview/ and martini3/. `proteins/` holds structures a pdc run imported (each with a sidecar recording its stated half-thickness and chains); `preview/` is the New Run panel's martinize2 cache, which no run reads. `martini3/` is the installed Martini 3 set every run reads in place -- the official lipidome ITPs, the sugar reference, its provenance and `martini3.json`, which records the upstream commit/DOI and every file's digest; it is installed from `references/` by the first reader and never written by a run. SQLite is the only live job store; old JSON job snapshots are not read.

The checkout selects workspace/dashboard/ in config/dashboard-paths.json. DASHBOARD_WORKSPACE=/absolute/path overrides that selection for an isolated instance. With neither setting, the legacy dashboard/ workspace is supported. Paths resolve at application construction; changing configuration requires a restart after all workers stop.

One serializer defines every digest this tree writes or compares: `files.canonical_json` (sorted keys, compact
separators), with `json_sha256` and `mappings.identity` both built on it. Stored copies of the other form are
migrated by `dashboard/cli/migrate_digests.py`, which rewrites a record only when re-serializing its own body
reproduces the stored digest and leaves the rest as it found them.

molecules/, references/, and resources/ remain canonical input sources. Reference indexing copies metadata and
hashes; it does not make another canonical copy of the original reference files. Each run records the inputs and
code it actually used: shared inputs by path and sha256 in `inputs/inputs.json`, generated data by value in
`inputs/`, and the repository scripts and helpers by digest in `stage_scripts`/`python_modules`.

Scientific reports live under reports/dashboard/; acceptance evidence lives under reports/validation/. Historical prototypes are under docs/design/prototypes/. Plans live under docs/plans/, one directory for every plan; docs/design/ records intent at its date. Root-level runs/ retains unrelated standalone benchmark output. The archived development tree `archive/dashboard-development-20260917/` earlier notes named is gone from this checkout (it was gitignored).

## Run storage and lifecycle
Every run type writes the same two trees beneath the configured workspace:

```text
runs/<id>/
  manifest.json
  inputs/
    inputs.json           # the input record: shared inputs by path and sha256, plus each generated file
    …                     # generated data only; aa_only/aa_cg also mirror their stages/ tree here
  stages/                 # one directory per stage that will run, empty until its script executes
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
An `inputs.json` entry is `{role, label, kind, root, path, sha256, bytes}` (plus `files` for a directory); `kind`
is `published`, `store`, `run-output` or `generated`, and `root` is `repo`, `workspace`, `run`, `runs` or
`absolute`. The manifest carries that record as `inputs` and hashes the whole document into
`input_snapshot_sha256`; `workflow.run` re-verifies it before every stage, so a published, stored or generated
input changed after prepare refuses the next stage by name. Generated data is written by value into `inputs/`;
nothing the run already had is copied. The code is not in the run either: `stage_scripts` names each stage's
repository script and `python_modules` the helpers its scripts import, each with a sha256 re-checked before the
stage starts. MDPs are rendered from the reviewed profiles in `dashboard/execution/mdp/profiles.py`, and the
manifest's `mdp_profiles` names the profile behind each file written. Output cadences are the run's own:
`nstlog`, `nstenergy` and `nstxtcout` reach the file from the panel (or the profile's default), and there is no
long-run widening rule. The New run inputs therefore control the file size and the sampling cadence directly. The CG dynamics files use the Martini 3 paper's Verlet list with two deliberate departures: `nstlist = 40`
(measured 8% faster per step than the paper's 20 on a 100 ns DDM micelle at the same tolerance and with the
same thermostat/barostat/volume statistics) and no `rlist` -- GROMACS sizes it at `grompp` from
`verlet-buffer-tolerance = 0.005` for the system at hand (1.554 nm for that micelle; the old pinned 1.35 nm
was the 20-step value and is wrong for a 40-step list). Minimisation profiles keep their pinned list because
nothing is integrated. The osmotic series builds its MDPs in `osmotic_mdp` and takes neither rule.

`stages/` belongs to every type: `aa_only` has `common/` plus `01_solvation` … `07_reference`; `aa_cg`
`1_AA-reference`, `2_mapping`, `3_initial_CG`, `4_CG_sim`, `5_assessment`, `6_SASA`; `pdc` the ten numbered
directories `01_prepare` … `10_backmap`; `osmotic` `01_simulate`; `cg_composition` its three screening stages. A
stage the settings say will not run has no directory at all: `pdc` records it in the manifest's
`skipped_stages` with its reason, and `workflow.run` records it `skipped` and carries on. A stage that exists and
finds nothing to do exits 4 with `skip.json`.

A topology names its dependencies by a path relative to the directory it is read in, because `grompp` resolves
`#include` from the working directory: the installed Martini set (`dashboard.martini3.include`), the run's generated
`inputs/` data, and -- for `pdc` -- the detergent's itp in `inputs/` and the protein's `cg/` tree under
`stages/02_system/`. Every `pdc` stage directory is one level under `stages/`, so the same spelling resolves from
the stage that wrote the file and from each sibling it is copied forward to. Only `system.gro` and `system.top` are
copied between stages: they are the writable working copies a leg edits, while the Martini libraries, the detergent
topology and the `cg/` tree are read where they live.

The layout before this one remains readable. Nine runs keep a byte copy of their prepared tree in `inputs/` and
copied `.py`/`.sh` helpers in their stages (`layout_version: 2`, the old file-hash map as the snapshot digest);
two `pdc` runs keep their stage directories at the run root. `analysis/runs/layout.stage_root` resolves both,
`dashboard/cli/migrate_run_layout.py` archives the old inputs and copied code (or moves the pdc tree under
`stages/`) and writes `legacy_layout.json`, and it never rewrites a manifest.

**Clone** creates a new run with changed settings, re-prepared against today's stores. Retry preserves
failed-attempt identity and settings in a new job, re-prepared against today's stores too, and refuses a molecule
snapshot the store no longer matches. Resume keeps the same run ID and database row and executes the current files already present
in the selected and downstream `stages/` directories. It uses the manifest's completed-stage prefix to choose the
restart point and does not restore files from `inputs/`: the input record is re-verified before each stage, so a
shared input changed since prepare refuses resume, while edits to the working stage files after the original
attempt take effect. The prior manifest and job metadata are recorded under `resume_history/`, while stage
directories and their existing scratch files remain in place. Prior analyses are marked superseded because a
rerun may change their source trajectories. Legacy copied-resume jobs remain readable; new resume requests
continue the selected run in place.

Cancellation targets process groups created by the current coordinator. Recovery marks interrupted active jobs and analyses failed. Orphan subprocess leases continue to block unsafe reuse and deletion. Logs and stage records retain commands, environment, start/end times, exit codes, hashes, and failure details.

SQLite transactions protect job updates and attachment/deletion relationships. Completed CG consumers keep their AA source protected from deletion. A waiting CG consumer occupies no simulation slot. AA failure blocks its waiting consumers; AA cancellation cancels them.

## AA-only and shared-reference protocol
See the **molecule directory contract**. Each molecule folder contains a matching ITP and GRO or PDB pair, optionally in nested SwissParam output directories, plus local topology dependencies. Missing metadata.json is generated without overwriting user metadata. PDB conversion happens in immutable run preparation; original coordinates remain unchanged. Checks reject traversal, symlinks, missing includes, unsupported directives, inconsistent atom order, and incompatible force fields. GROMACS preprocessing verifies parameter resolution.

aa-single-solute-v2 accepts one pre-parameterized neutral or charged solute and runs it under a chosen force
field. The registry in `dashboard/execution/forcefields.py` holds, per entry: the GROMACS tree, its water file
and moleculetype, its counterion names, the temperature its parameterisation assumes, the mdp block GROMACS
prescribes for it, where the tree came from, and the constraints choice. The default is the MacKerell Lab's
February 2026 CHARMM36 port in its CGenFF **4.6** variant (CHARMM36m by default, `define = -DUSE_OLD_C36`
selects the older set), chosen over the 5.0 variant because the CGenFF file version must match the version
that generated a solute's topology. July 2022 is kept as a second entry so earlier runs remain interpretable.
Stages are solvation, neutralization, minimization, NVT, NPT, NPT production, and reference publication.
Charged systems receive the entry's counterions — `SOD`/`CLA` for the CHARMM trees — and no extra salt is
added. Defaults: the entry's own temperature (303.15 K for CHARMM36m, because that is what the
parameterisation assumes), 1 bar, a **2.4 nm cubic box**, 100 ps NVT, 1000 ps NPT, 10000 ps production, 10 ps
trajectory interval, and a recorded random seed. Constraints are `all-bonds`, as the reference protocol
specifies; the GROMACS manual lists `h-bonds` for CHARMM36, and each entry records both so the deviation is
visible rather than implied. The box is a fixed cube because that is the protocol's box, and a solute that
cannot sit inside half its edge is refused during preparation rather than truncated: DDM (1.85 nm) needs an
explicitly larger box, sucrose (0.925 nm) does not. A molecule whose parameterisation version is unrecorded —
the SwissParam topologies — carries that caveat into its readiness report and into every manifest prepared
from it, without blocking the run. Simulation scripts use eight CPU threads. These defaults do not establish
equilibration or convergence.

AA-only requires no CG mapping or Fast_Forward. New AA–CG launches create a separate AA source and waiting CG consumer, or attach an eligible completed source. /api/references lists completed technically eligible AA-only jobs; combined legacy runs are not relabelled or offered as new AA-only sources. Inherited AA settings are checked server-side and locked in the form.

Publication retains full-system GRO/TPR/XTC/CPT/EDR/log outputs and solute GRO/TPR/XTC. 07_reference/reference.json records atom order, finite frames, time coverage, composition, diagnostics with units, protocol, and artifact hashes. CG consumers read the shared source trajectory and write only their own mapped and CG products. Analysis scratch copies are temporary and counted in resource admission.

Completion, technical reference eligibility, and scientific validation are separate. The short AA adapter acceptance report demonstrates execution and sharing; it does not validate a molecular model.

## DDM draft execution test
An AA–CG run is queued under the profile its run type owns — `protocol.profile_for_run_type` answers `cg.AA_CG_PROFILE` (`draft-smoke-reference`) and `standard` for every other type, and the queue route and `/api/defaults` both read it. The panel offers no profile control and sends no `profile` key, so the durations a form shows are the durations the run uses; before that, `/api/defaults` fell back to `standard` while the run was stamped `draft-smoke-reference`, which would have queued a 100 ns CG production where the form showed 10 ns.

A caller that names no mapping still falls back to the run-local `mapping_candidate_smoke.json`: a connected 11-bead draft covering all 35 heavy atoms with one documented S-bead size exception. C1 tail beads follow the local dodecane reference; polar bead assignments are uncalibrated chemical guesses. These are software test inputs, not a validated DDM model, and the panel requires a saved mapping before it can queue anything.

The AA half runs at its standard durations (100 ps NVT, 1000 ps NPT, 10000 ps production) and the CG half at 10 ps equilibration and 10000 ps production, in pure water at 300 K. Durations only; the thread budget comes from the stage settings, whose defaults are one MPI rank and eight OpenMP threads. It runs AA → ff_map → the mapping's current parameterization or `ff_inter` → CG → ff_assess → SASA with checks at each handoff. Every run is new; retry preserves the original data.

Scripts live in dashboard/execution/scripts/. Scientific assets are read where they live and named in the run's input record: SwissParam and CHARMM36 from their resource folders, Martini from the workspace's installed `martini3/` set (never from a run's own stage directories), the water boxes from the templates. The MDPs are written from the reviewed profiles rather than copied from the templates. `references/` is the vendored upstream of the Martini set -- the installation source and what the code parsers index -- and the install is digest-verified against it, so the two cannot disagree. No ENAP molecule or script is used. GROMACS 2026 TPRs are kept for simulation; analysis uses supported ligand GRO inputs with matching trajectories. Maintained `mdrun` launchers request CUDA offload on GPU 0 for nonbonded work with thread pinning; the AA stages put PME on the GPU as well, while the CG launcher leaves PME on the CPU and takes its budget from the stage settings. Verify the recorded command and GROMACS log when diagnosing hardware selection.

### Stage settings

The stage settings decide the `mdrun` budget and the nonbonded and PME schemes. One helper renders them for a generated AA stage command and for the CG stage scripts, which receive them as `MDRUN_LAUNCHER` and `MDRUN_FLAGS`, so a script and a generated command cannot disagree.

The CPU levers are `mdrun_ntomp` (OpenMP threads per rank) and `mdrun_ranks` (MPI ranks). On this host the ranks are separate processes under `mpirun`; a thread-MPI build would take them inside one process with `-ntmpi`, which is why the adapter asks the binary for its configuration instead of assuming, and records the answer as `resource_usage.gromacs_flavour` in the stage manifest. The product of ranks and threads is checked against the machine's cores before a stage is prepared.

`mdrun_nb` and `mdrun_pme` accept `auto`, `cpu` or `gpu`. `auto` emits no flag and leaves the profile's own flags untouched, which is what every run did before these settings existed; a named scheme *replaces* the flag it names rather than being appended after it, so the setting cannot be silently overridden by the profile. Choosing `gpu` for PME requires `gpu` for the nonbonded scheme, because GROMACS runs PME on the GPU only then. A run's manifest records the flags it used, and its `resource_usage` records the threads, ranks and build flavour.

Set up the isolated tool installation once from the repository root:

```bash
python -m venv --system-site-packages .venv
.venv/bin/python -m pip install --no-build-isolation --no-deps ./resources/parameterizers/fast_forward
```

Readiness invokes each tool's help to check imports as well as executable discovery. Run manifests record resolved tool paths, versions, and input/script hashes. Missing dependencies block execution rather than triggering installation inside a simulation.

5_assessment/validation.json records frame and atom counts, finite coordinates, AA/mapped COG agreement, and actual comparison reports. Inspect plots and SASA curves through the artifact browser. Completion means the execution checks passed; scientifically_validated remains false.

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
The web UI is two workspaces, `detergent-validation` and `protein-detergent` (`dashboard/web/sections.py`), each a set of panels reachable at its own URL segment (`/<workspace-slug>/<panel>`). `DASHBOARD_TABS` narrows an instance's panels by comma-separated slug; each named slug must exist in every installed workspace, and a name that does not fails when the app is constructed rather than as a 400 on the first page. Validation carries Runs, Run view, Single Molecule Simulations, Bead Assignment, Bond Interactions, Combinations, Mapping Validation and Osmotic Series; protein-detergent carries Runs, Run view, Protein-Detergent Simulations and Complexes. The template writes each section from the registry and `tabs.js` mounts it by DOM id.

### Runs
Background polling updates individual status fields every five seconds. Forms, expanded details, mapping edits, and scroll position are not rebuilt. Terminal runs can be manually deleted from their run card; active workers are protected. Tabs, form values, and mapping drafts are remembered in browser storage. Elapsed time is reported only when recorded; ETA is shown only when present in current GROMACS output. Legacy runs without timestamps show "Not recorded".

Each run card shows the workflow stages from its manifest and indexes files created inside the run directory. Artifact links are path-checked; SVG files are previewed in the card. The former default `snapshots` analysis is retired: no analysis frame series is produced, and a run holds only the structures and trajectories its own stages wrote.

### Run view
One run, its structures and its figures, registered in **both** workspaces and scoped per
workspace by `web/sections.py`'s `run_types` (validation: `aa_only`, `aa_cg`, `cg_composition`, `osmotic`;
protein-detergent: `pdc`). The panel asks `/api/jobs` for each in-scope type by name (`?run_type=`), so it
renders this workspace's runs rather than narrowing a page. AA and CG structures come from the artifact route;
a CG structure is sized from the model's own size classes and coloured by type family through
`static/js/ngl-beads.js`, with the legend drawn from the same table. The bond rule is one helper
(`static/js/run-view-structure.js`): a file carrying CONECT is drawn from those records and never guessed at,
a coarse-grained file is `inferBonds: 'none'` even without CONECT, and only an all-atom file with no CONECT is
left to the viewer's inference. There is no transport row or frame film: the snapshot analysis that published
a frame series is retired, so the canvas shows one static structure at a time. A `pdc` run is drawn here too,
and its CG chain is presented as **segments**: a
protein-detergent run rebuilds its system when the removal path takes detergents out, so its legs are not one
trajectory. `GET /api/jobs/<id>/trajectory` answers them in stage order (`analysis/runs/segments.py`) — each
entry's `structure`, `trajectory`, `atoms` and `group`, the `boundaries` where the atom count changes, and a
stage that only re-declares another's file marked `duplicate_of` rather than played twice — and the panel
renders one row per stage under the frames, `data-idle` for a stage with nothing to play and `data-boundary`
for the rebuild, with both counts. Legs sharing a `group` are one system a player may concatenate; a change of
group is where it must switch files (measured on `00b9ae6db23f`: 11,708 atoms through
minimisation/NVT/NPT/assessment, 10,427 in the extension). The table is rendered only for a pdc run. `GET
/api/jobs/<id>/structure?path=<run-relative .gro>` serves a coarse-grained structure with the run's own `[
bonds ]`/`[ constraints ]` written as CONECT (the topology located by
`analysis/runs/layout.coarse_topology(run_type)`: `3_initial_CG` for a single-molecule CG run, the detergent's
`02_system/detergent_CG.itp` for a pdc one; a single-molecule run still falls back to the manifest's
`FINAL_ITP`); a `.pdb` is refused to the artifact route.

The analysis subprocess reads a work directory holding only the patterns its kind declares (`kinds.py`), so a role the layout can resolve is still invisible there until the kind copies the files.

Analysis graphs expand inline: ff_assess PNG plots and a Plot SASA action that generates an image from measured AA/CG XVG data. Original XVG data are preserved; SVG artifacts remain previewable. Reads use byte offsets and bounded chunks; the display keeps up to 256 KB.

### Console
Select a run, pause display updates, copy the visible excerpt, or download its full log. New runs download a stage-log ZIP. Pausing affects the display only.

### New run
Shows the exact packaged input paths, executable availability, and missing workflow requirements. The same readiness check runs server-side on submission and retry. Unsupported methods and incomplete workflows cannot be queued. The dashboard accepts registered molecule directories; arbitrary uploads and SMILES are not offered.

Exposes AA/CG equilibration and production durations, temperature, trajectory output interval, and SASA probe radius. Each value has a Default button. Defaults come from the packaged Fast_Forward/CHARMM/Martini MDPs at the profile the run type owns: an AA–CG run's CG half starts at 10 ps equilibration and 10000 ps production, an AA-only run at the standard durations. Submitted settings are range-checked, converted to stage-specific nsteps, recorded in the manifest, and applied only inside that run directory.

Lists compatible completed AA runs for AA reference reuse. Selecting one records its ID and checksum as the run's
`shared_reference` and points `AA_REFERENCE_DIR` at the already-published reference; nothing is copied, the source
is re-verified before every stage, and its artifacts are never modified.

In the **protein-detergent** workspace the same panel queues a `pdc` run and reads its controls from
`execution/adapters/pdc.py` (`validate_payload`, `SETTING_SPECS`, `CHOICE_SPECS`): the detergent template and
protein, the **model** the belt is built from — `GET /api/pdc/models` lists that detergent's saved mappings a
build can reuse, joins each to its parameterization by content hash (a revision is keyed by content identity,
and a record's `owners` list is inferred, so a name is not an address), puts fitted ones first and labels
every entry with what it carries (`revision 2 · 11 beads · 26 terms · fitted 2026-10-22`, or `… · derived
terms`) — the **initialisation** style (`lattice` or `self-assembly`), an aggregation number, salt, a positive
integer seed, assessment/extension durations, the three equilibration legs (minimisation steps, NVT ps, NPT
ps), the protein **subunit** selection, whether the back-map runs, and the **Prepare protein** toggle
(`prepare_protein`, on by default wherever the build has a protein: the stage skips by name when `pdb2pqr` is
not resolvable). `GET /api/pdc/preview/placement` derives a live **system preview** — the frame the build
would write (protein + detergent in the box, before solvation) — through the build's own functions, caching
only the martinize2 protein step under the workspace's `preview/`; a gate that refuses is returned as a
reason, never as a drawn picture. Its `basis` carries the protein's **secondary structure** — the DSSP letters
martinize2 was given, keyed by the residue number the frame gives each residue, the `helix`/`sheet`/`coil`
class each falls in and their counts (`pdc_preview.SECONDARY_CLASSES`, one table) — so the card colours a
backbone bead by its residue's class and prints the assignment's own totals; a residue the frame cannot give
one class to (its number holds two residues of different classes) is left uncoloured rather than guessed at.
The basis also names the **all-atom protein those beads were coarse-grained from** --
`basis.protein_structure`, a cache key and the URL of `GET /api/pdc/preview/protein?key=`, which serves
`preview/cg/<key>/protein_selected.pdb` (the prepared structure instead, for a prepared derive) and refuses a
key that is not a cache entry name with 400 and an uncached one with 404 -- so the card draws it as a neutral
ribbon **under** the beads -- with the protein's bead representations drawn translucent over it and the
detergent's left solid, because at full opacity the beads hide the very atoms they were coarse-grained from --
and a build with no protein names neither. That ribbon is the structure the beads stand for; it does not
restate the classes, which are the beads' own residues'. The **Bonds** control switches the protein's
representations between `ball+stick` and `licorice` so the frame's own CONECT records read at preview scale,
and **Ribbon** shows or hides the ribbon; both send nothing, stay out of the derive's inputs and change no
derived value. The **encapsulation estimate** (`GET /api/pdc/proteins/<entry>/encapsulation`) reports how many
detergents the apolar surface implies. Structural import lands the file in the workspace's `proteins/` with a
sidecar.

### Osmotic Series
A sugar concentration series is **one run owning N concentrations** (`settings.molalities`), gated to sugars and built by `execution/adapters/osmotic.py`; the old one-concentration `osmotic_molality` shape is removed rather than deprecated. Each concentration gets its own directory (`condition_directory`) and its own checkpoint, resumed with `gmx mdrun -cpi` up to `osmotic_attempts_max` attempts, and a failed condition either carries on or stops the series (`series_on_failure`). The panel reads `GET /api/osmotic/catalogue`, queues the series with `POST /api/osmotic/series`, and reads the series as it stands from `GET /api/osmotic/conditions`. The dividing area and the water/solute counts are recorded at build time so the analysis divides by the number the build agreed to.

### CG Bead Assignment
Compare two candidates against the original DDM coordinates and bond graph. Drag or use arrow keys to rotate the atom view; edit bead names, sizes, and atom indices; add or remove beads; export JSON or save a new draft. The bead assignment is drawn in three dimensions only — the 3D NGL overlay, one translucent sphere per bead at the mean of its atoms (the 2D depiction went 2026-10-12, `aa318e0`); the server's RDKit depiction stays because the mapping export bundle embeds its SVG. A new draft never overwrites its parent and remains unvalidated.

Mapping checks cover heavy-atom coverage, duplicate assignments, unknown atoms, hydrogens, empty groups, disconnected groups, nominal bead sizes (R=4, S=3, T=2), and the ±1 per 10 heavy-atom mismatch guideline. Branching/shape exceptions need scientific justification. These checks do not validate bead chemistry, symmetry, bonded parameters, or physical behaviour. The original DDM candidates have structural findings; the connected smoke draft fixes coverage and connectivity but is still not a production model.

### CG Bond Interactions
Choose a saved mapping. The panel reads its parameterization — the revisions of bonded terms produced for it — and draws the mapping's own molecule as a Plotly 3D connectivity diagram with physical beads only. The interaction table lists the current revision's terms, or the mapping's own draft connectivity when it has no revision, with a **Source** column naming the engine that produced each term (`ff_inter`, `bartender`) or that the mapping did (a ring constraint, a virtual site).

**Fit this model** produces a revision; it makes no MD, so nothing from this panel appears in Runs.
Fast-Forward (`ff_inter`) and BARTENDER (`-refit -owntraj`, never its own sampling) build the mapped AA
trajectory from the linked AA-only reference first — minutes of CPU, paid once per (mapping, reference) pair —
then fit bonds, angles and dihedrals to it. The job box names the four steps (`mapped frames`, `fit`,
`checks`, `save`), shows the engine's log tail and an elapsed time, and can be cancelled. The two engines and
their options are read from `GET /api/bonded-parameterizations/engines`; every one of them needs an AA
reference. The checks — `dihedral-fit` and `bonded-cross-check` — re-derive terms from the same frames and are
recorded with the revision; a check that cannot run is recorded with its reason rather than failing the fit. A
Fast-Forward revision also records the AA reference's own interaction histograms (`<group>_<type>_distr.dat`)
that `refine_bonded` measures while fitting: the CG assessment scores against those files and never computes
them, so a run that consumes the revision stages them into its `3_initial_CG` — the directory `ff_assess`
reads as `-d` — verifying each digest. A revision that records none cannot be scored, but the run still
happens: `prepare` writes the empty inventory with the reason, and the assessment stage records `skipped` with
it, so the run completes without a score and the stage says why. Bartender measures none, and its own analysis
is unbuilt. Generated parameters are hypotheses, and a fit is not scientific approval.

Revisions accumulate on the mapping; `make current` chooses the one a run consumes, and a run that consumes a revision records that it did not fit. **Save to mapping** writes the torsion model and stiffness scale into the mapping file itself. **Delete this parameterization** removes what this panel is about — the revisions, the fit jobs that produced them, the frames those jobs built and the reference histograms recorded with them — through `DELETE /api/bonded-parameterizations/<content_hash>`, which needs `confirm: true` and refuses with `409` when the revision named is no longer current. The saved mapping itself is not touched: deleting a mapping is the editor's button, and this panel edits models.
The record lists the saved mappings that claimed it (`owners`); a save makes the claim, deleting a draft releases
it, and the revisions go with the last claim.

### Run controls and persistence
Delete is available only for completed, failed, or cancelled runs. The server checks that no current worker owns the run, removes its run directory and console log, then atomically removes its job record. If file cleanup fails, the record remains available for retry. Deletion is irreversible and confirmed in the browser.

Cancellation sets "Cancelling…" until the worker confirms process termination. The worker terminates only subprocess groups it created, escalating to kill when necessary. Saved PIDs from older sessions are never signalled. Runs whose workers are not owned by the current server cannot be controlled by it.

Resume continues the existing run ID after lease, dependency, and resource checks. The selected and downstream stage directories must exist and must not be symlinks; their current launchers, inputs, and outputs are executed as found. Retry and Clone create new run IDs after readiness checks; original logs and simulation outputs stay intact. In-place resume records its prior manifest and job metadata in `resume_history/` without replacing current stage directories. Job updates use SQLite transactions; immutable model and review records use atomic JSON replacement. Stage failures and cancellations are recorded in manifests.

JSON and log endpoints are under /api/jobs, /api/readiness, /api/mappings, /api/bonded-parameterizations, /api/compositions, /api/cg-models, /api/osmotic and /api/pdc. Mapping edits are stored in the configured workspace's mapping_drafts/ directory; original candidates stay under the canonical molecule source.

### Mapping exports and diagrams

The editor draws the same assignment in three dimensions with the vendored NGL viewer: the heavy atoms as ball-and-stick, and every bead as a translucent sphere at the centre of the atoms it maps, sized by its R/S/T class. Spheres are served as a file of one atom per bead and drawn as one representation per size class, because a representation carries a single radius scale. Clicking a sphere selects every atom that bead maps and clicking an atom selects that atom, both through the editor's own toggle, so the two views cannot hold different selections. `POST /api/mappings/overlay3d` serves both files; the unit conversion (a mapping context holds nanometres, a PDB file angstroms), the centres and the radii live in `models/mappings/overlay3d.py` with unit tests, and the browser behavior is covered by `tests/dashboard/browser/test_mapping_overlay3d_browser.py`.
Each candidate can export .ndx, .map, .gro, or a ZIP containing all three plus candidate metadata, source hash, and validation report. All files use matching bead IDs B01, B02, …; original display names remain in model.json. This avoids GRO name truncation and Fast_Forward's restriction to alphanumeric bead identifiers. Missing, repeated, unknown, or hydrogen assignments block export. Size and connectivity findings remain visible and recorded as review issues.

The .map header is [ molecule ] LIG1 <molecule_name>, as required by Fast_Forward. The .gro frame is calculated from equal-weight heavy-atom COGs, converted from ångströms to nm, and has no periodic box. These are review artifacts, not fitted parameters or a ready-to-run system. Original atom indices refer to the matching SwissParam ligand-only order.

RDKit, already present in the local environment, draws the 2D structure from SwissParam MOL2 after checking atom names/order and bonds against PDB and ITP. Circle radii represent the 2D extent of assigned atoms, not Martini physical radii. Diagrams update with mapping edits and export as self-contained SVG.

Carbohydrate validation is separate from mapping approval and is queued through the API rather than from a dashboard panel: `POST /api/jobs/<id>/carbohydrate-validation` takes the published `tc4` representation or the deterministic `physical_only_ring_constrained` derivative, which removes TC4 sites while retaining physical bead ownership and 1.15-scaled ring constraints. The controls that used to offer this from CG Bead Assignment were removed; the analysis, the queue route and the report endpoints are unchanged. A setup check is diagnostic-only. An evidence run requires cited targets and paper-aligned sampling before it can report `evidence_complete`.

### Analysis evidence
POST /api/jobs/<id>/observables reads the mapped trajectory and fitted ITP, excludes defined interactions, and writes analysis/unparameterized_observables.json with units, frame count, means, standard deviations, and 5th/95th percentiles. The dashboard exposes this from the Analysis graphs section.

POST /api/jobs/<id>/surfaces runs the local GROMACS sasa -q command on the energy-minimized AA structure and mapped CG frame, preserving both source PDB surfaces, SASA XVG files, checksums, parameters, and an XY comparison SVG. This is a geometric comparison only and remains scientifically unvalidated.

POST /api/jobs/<id>/stability records LINCS warning counts from stage logs, immutable trajectory checksums, and the actual local gmx check exit status/output tail in analysis/numerical_stability.json. Reports are diagnostic and do not approve a model.

POST/GET /api/jobs/<id>/targets stores schema-versioned transfer and partition free energies and other supported detergent properties with units, uncertainty, conditions, and citation. Optional measured values produce standardized residuals; absent measurements remain absent.

POST /api/jobs/<id>/refinement-score persists a versioned evidence breakdown in analysis/refinement_score.json, retaining native metric scales and explicitly listing missing evidence. The dashboard exposes this action; it is not an automatic ranking or scientific approval.

POST /api/jobs/<id>/carbohydrate-validation creates an immutable validation analysis attempt for a completed source run. The request records the mapping snapshot, representation mode, tier, target dataset, source hashes, tool versions, and protocol. Its report has the three required evidence keys: `mapped_geometry`, `transfer_free_energy`, and `osmotic_pressure`. Metadata-only or missing target datasets, missing octanol parameters, short trajectories, and incomplete concentration series remain `insufficient_data`; validation never changes mapping approval or production authorization.

### Models, analyses, and browser behavior
Each tab loads its data when activated, including keyboard and direct-link navigation. Shared catalogue requests are deduplicated and cached for ten seconds; saving or deleting models invalidates the relevant cache. Mapping editors retain unsaved edits across tab changes. New run debounces readiness checks and ignores cancelled or superseded responses. Runs pauses polling while another tab is open and refreshes on return.

The full APIs remain available. view=summary on /api/jobs, /api/mappings and /api/bonded-parameterizations returns compact catalogue and polling records; individual record endpoints retain full detail. /api/mappings/context supplies the source molecule and bead types. Mapping validation caches use candidate and source content, so changed scientific inputs invalidate previous results.

Derived analyses use isolated subprocesses, publish immutable outputs, and record actual source hashes, calculation settings, tool versions, and errors.
Unchanged requests reuse completed analysis products.

DDM remains the executable CG example. Standard production retains the reviewed scientific-model gate. Candidate screening requires a saved mapping; deleted historical mapping files are not restored as defaults. A save
whose beads, rings and connections hash to an already saved mapping's content is refused with 409 -- one content
identity is one model -- and the editor names the mapping that holds it instead of minting a second file; an
in-place save (a rename, or an edit to the same file) is the only way to keep a mapping's identity. Mapping exports, sugar virtual sites, fitting conventions, scoring interpretation, and known bonded UI gaps are documented in DDM calibration.

### Resource policy, backup, and rollback
config/dashboard.json controls concurrency, disk headroom, storage reservations, per-run and total limits, and retention review. Usage is monitored, not enforced by a filesystem quota, so it may overshoot between checks. Storage reports never delete automatically. Explicit deletion requires terminal status, no worker lease, and no retained AA-reference consumer. Model cleanup requires a reviewed, hash-verified migration inventory. Preserve unique reports and scientific evidence.

SQLite is authoritative. Back up the database with SQLite's backup facility while the coordinator is stopped, and back up model stores and run directories with it. Old generated state is not migrated into a fresh workspace.

```bash
.venv/bin/python -m dashboard.cli.reset_workspace --workspace /absolute/path --confirm
```

The reset command removes only its explicit generated-state list, recreates empty runtime directories, and writes reset-record.json. It refuses active service leases, symbolic-link roots, and missing confirmation. Never switch workspace roots while jobs are active.


Set {"workspace": "/new/workspace"} in config/dashboard-paths.json only after verification, while both workspaces remain stopped. Historical commands and manifests retain their original paths. Console display resolves recorded stage logs within the selected workspace; references and resume resolve run IDs there.

For the 2026-09 reorganization, original runtime stores were retained in archive/dashboard-development-20260917/runtime-original/. That tree is gitignored and is **gone from this checkout**; the workspace-migration hash/database proof lived beside it. The current workspace is the live store; never switch its root while jobs are active.

## Paused work
### Micelle builder
A native spherical single-detergent Martini micelle builder around membrane proteins. Paused at the user's request. The initial core (python -m micelle build --template ... --aggregation-number N --seed S --output DIR) validates a registered detergent template, creates a deterministic spherical center lattice, and writes geometry diagnostics. python -m micelle validate build/diagnostics reruns the checks.

The package is intentionally marked experimental until protein-aware packing, topology dependency closure, solvent and ions, GROMACS preprocessing, and dashboard submission are completed. It must not be used to claim a validated scientific model.

Approved design: docs/superpowers/specs/2026-09-14-detergent-micelle-builder-design.md.

Implementation plan: docs/plans/2026-09-14-detergent-micelle-builder.md.

### Membrane-protein workflow
The protein-detergent complex pipeline (`pdc`) is the maintained implementation of this workflow and runs end to end; see Source ownership and Dashboard workspace above. The historical `memembed -> martinize -> insane -> cg2at` chain is **not** maintained: the `archive/MemProtMD/` tree earlier notes named is gone from this checkout, and nothing in the maintained dashboard/ tree depends on it. The project goal it describes is met by `pdc`, whose back-map stage uses the CG2AT2 build vendored under `tools/cg2at/`.

## Verification
Canonical tier commands live in `AGENTS.md` (`## Verify`); `pytest.ini` owns worker defaults and counts. The three
tiers in use:

```bash
.venv/bin/python -m pytest -m 'not browser and not slow' -q
.venv/bin/python -m pytest -m browser -q -n 16 --dist worksteal
.venv/bin/python -m pytest -m slow -q -n 0
```

Tests live under tests/dashboard/{unit,integration,browser}. Shared fixtures redirect every writable store; tests generate their own mapping candidates. The suite checks commands, lifecycle and recovery, quota and dependency guards, parsing, API contracts, and browser interactions without long simulations. Browser tests use installed Playwright and Chrome, temporary databases, and loopback servers.

Tiers answer "how expensive", areas answer "what about": `tests/dashboard/areas.py` holds one table of module patterns per area, applied as markers by `pytest_collection_modifyitems`, so `-m pdc` is the protein-detergent work, `-m 'mapping and not browser'` the bead editor without a browser, and `-m 'pdc and not browser and not slow'` that area's tool-free part. The areas are pdc, runs, bonded, analysis, infra, osmotic, mapping, carbohydrate, web, molecules and aa; they partition the suite exactly, which `unit/test_test_areas.py` enforces -- an unnamed module, a module two areas claim, or an area with no module fails that test. Order in the table decides an ambiguous name (a mapping test named `test_cg_mapping_script.py` is `mapping`, not `runs`), so a new file goes where its subject is, with the pattern that names it. Tier and area counts are measured in `pytest.ini`.

Optional process parallelism is provided by `requirements-dashboard-tests.txt`. That file also carries the test-only imports `playwright` (browser tests), `vermouth` (sugar topology) and `mdtraj` (pdc secondary structure; see below), so install it before running the full suite:

```bash
.venv/bin/python -m pip install -r requirements-dashboard-tests.txt
```

Use the commands above; do not re-state worker counts here. Threaded execution is unsafe because tests patch shared dashboard module state.

### Environment gaps

Tier and area counts are measured in `pytest.ini`; quote a fresh `pytest --collect-only -q` rather than a copy. `.venv/bin/ruff check packages tests` exits 0; repo-wide `ruff check .` is clean. Two further instruments sit beside the tiers: `scripts/gate_commit.sh <message-file> <paths...>` runs the fast tier and `ruff` over the paths it is given and commits only when both are clean, and `scripts/mutation_check.py` reports which tests notice a one-line change in an engine or feature analysis module or execution adapter (11 mutants, 10 caught, 1 survived -- the control).

The two tests that used to skip by design on a missing vendor tree now run, because the Fast_Forward source tree is provisioned and patched:

| Test | Previously | Now |
| --- | --- | --- |
| `integration/test_mapping_exports.py::test_fast_forward_parser_reads_names_and_order` | skipped: `map_file_parers.py` absent | passes against the vendored source |
| `unit/test_carbohydrates.py::test_ff_dihedral_membership_controls_restricted_bending` | skipped: `interaction_fit.py` absent | passes; it pins both local patches |

Both still resolve their path through `tests/dashboard/tool_paths.py` instead of a literal path, so a missing vendor tree skips with a reason rather than failing for a reason unrelated to the code under test. Provisioning is not the whole story on its own: pristine upstream passes the parser test and fails the membership test, which is why the tracked patch is part of setup (see Environment). `unit/test_carbohydrates.py::test_installed_fast_forward_is_the_vendored_source` fails when the installed package is not the vendored source, so a rebuilt virtualenv cannot silently revert to upstream behaviour.

Measured toolchain on this machine: GROMACS 2026.3 at `/usr/local/gromacs/2026.3/bin/gmx` (CUDA, OpenMPI),
Fast_Forward 0.0.1.dev1 built from the patched vendor tree (fitter sha256 `0ab9252d…`), MDAnalysis 2.9.0,
numba 0.61.2, vermouth 0.15.0. `config/tools.json` declares those tools and `dashboard/execution/tools.py` is
the one resolver: a declared path is verified executable before it is used, a declared command name is
resolved on the composed search path (the workspace virtualenv, the declared tools' directories, then the
inherited `PATH`), and a declaration that cannot be honoured resolves to nothing rather than to a substitute.
A name that is not declared at all (`martinize2`, `pdb2pqr`) falls back to the same search path (`tool_path`'s
`shutil.which`). Readiness reports such a declaration as a check, not a blocker. The guide's earlier text
named a hard-coded `~/Downloads/gromacs-2026.0` build; that path appears nowhere in the code now. The same
file pins the Fast_Forward source revision (`fast_forward_source`, `fast_forward_commit` = `61e407e6…`, the
local commit carrying the two dihedral fixes on top of upstream `718ce2de`); each run's tool report records it
as `fast_forward_source`, and the vendored-source guard in `unit/test_carbohydrates.py` fails when the
checkout or its cleanliness disagrees with the pin.

Two more tools enter through `requirements-dashboard-tests.txt` (`mdtraj`, `pdb2pqr`), and neither is test-only. A pdc CG stage asks martinize2 for secondary structure with the bare `-dssp` flag, which vermouth answers with `mdtraj` (`mdtraj.compute_dssp`) and with nothing else — without it the stage records a fallback to `MDAnalysis.analysis.dssp`, and the two routes disagree (42 of 230 residues on 1AT9), so the assignment's letters are written into the run report. `pdb2pqr` is the optional `prepare_protein` step; `pdc.readiness` reports it as a check, and a run that asks for the step refuses by name when the tool is not resolvable.

`unit/test_mapping_references.py` derives the expected reference ranks from the sources present rather than asserting ranks 1-3: `references/M3-Small-Molecules/` and `references/M3-Bible/` are partial clones, so `models/martini_v3.0.0_small_molecules_v1.itp` and `src/MartiniCGSmilesDB_v6.xlsx` are missing and `load_index` reports rank 1 only (verified: 1 source, 50 records, no diagnostics). Provisioning those files widens the index without changing the test.

`vermouth` was missing from requirements-dashboard-tests.txt until this review and accounted for two further failures in `unit/test_carbohydrates.py`.

## Focused validation
```bash
.venv/bin/python -m pytest \
  tests/dashboard/unit/test_bonded.py \
  tests/dashboard/unit/test_bonded_parameterization.py \
  tests/dashboard/integration/test_mapping_exports.py \
  tests/dashboard/integration/test_mapping_workspace_api.py \
  -q
node --check dashboard/web/static/js/main.js
```
Browser acceptance uses installed Playwright and Chrome:

```bash
.venv/bin/python -m pytest tests/dashboard/browser -v
```

The suite exercises polling without state loss, mapping edits and draft persistence, console pause/follow/copy/download, and mobile layout using isolated test jobs. Worker tests cancel an actual short-lived subprocess without running MD.


## Module notes

Detail that matters while editing one module and would only be in the way in `AGENTS.md`. Each subsection names the
code it describes; if the two disagree, the code is right and this is stale.

### Run accounting: progress, analyses, structure

`web/progress.py` counts mdrun legs in the stage log (`gmx mdrun -deffnm`) and the step within the current one, because
a three-leg script stage (`cg_simulation.sh`: min, eq, md) has no single GROMACS estimate and a tool stage
(`assess.sh`) prints no step at all. It streams the log -- leg markers stand at the start of legs -- and reports
`percent: null` rather than 0 when a leg has not printed yet. The ETA is GROMACS' own text, so the two numbers answer
different questions.

`coordinator.automatic_analyses` is the one resolver the queueing path asks -- `kinds.for_every_run()` plus
`kinds.default_for(run_type)`. `for_every_run()` is empty because the snapshot analysis is retired; an `aa_cg` run still
owes `dihedral-fit` and `bonded-cross-check`.

The owed kinds are worked through **one at a time**, because `queue` takes one analysis per run and refuses a second
with `RunBusy` while the first holds the worker. `analysis_coordinator.drain` queues what it can and names the rest in
`owed`; `analysis_coordinator.chain` drains again when an attempt settles, which is how a three-kind list finishes with
nobody pressing anything. A *failed* attempt does not chain -- the kind is not current by signature, so draining from it
would queue itself again -- and waits for `POST /api/jobs/<id>/analyses/recompute`, the Analysis graphs panel's
Recompute button. That route asks the same resolver, so it cannot request a set the run does not owe, and `queue`
fingerprints the analysis code, so pressing it after a code change starts fresh attempts and pressing it with nothing
changed starts none. `owed` is what the panel reports as still waiting.

`GET /api/jobs/<id>/structure?path=<run-relative .gro>` writes the run's own `[ bonds ]` and `[ constraints ]` as
CONECT, locating the topology by `analysis/runs/layout.cg_topology` and naming it from the manifest's `FINAL_ITP`. A
`.pdb` is refused. Readers never distance-guess a file that carries CONECT, and a coarse-grained file is
`inferBonds: 'none'` even without it.

### Re-scoring the assessment (`execution/assessment_rescore.py`)

Stage 5 is not an analysis: its score matrix and distance distributions are the stage's own outputs, written once
when the run ran, so Recompute -- which re-queues *analyses* derived from those outputs -- cannot repair a matrix
drawn against a revision that carried no pairwise references. `POST /api/jobs/<id>/assessment/rescore` stages a second
attempt instead, beside the first and with no new MD: `prepare` resolves the run's mapping to its **current**
parameterization revision, stages that revision's histograms into `stages/5_assessment@<n>/references/` through
`cg.stage_distributions` (one copy rule, one digest check), records the digests of the repository `assess.sh` and
the two scripts it calls (no copy is made), and writes `attempt.json`. `run` executes it in a background thread and appends `{attempt, directory,
started_at, ended_at, exit_code, status, references, revision, mapping_hash, log}` to the manifest's
**`assessment_attempts`** -- a key of its own, append-only, so `stages` is never touched, the first attempt's
directory is never written to, and a non-zero exit is recorded as a failed attempt rather than failing the run (which
stays `completed`). Numbering is the recorded count plus one, and never a number already on disk. Refusals are
`RunConflict` (409) with their own sentences: no assessment stage, a run that has not finished, no CG trajectory, no
current revision, and a revision with no pairwise family -- the last carrying `stage_distributions`'s own reason,
which names how many histograms it holds and how many pairs it would need.

`5_assessment@<n>` sits beside `5_assessment` in the same stage root, so `assess.sh`'s `../4_CG_sim/prod/` still
resolves. The two directories it reads are named rather than written in: `INITIAL_DIR` is the run's own
`3_initial_CG` (where `-i` finds the ITP the run simulated) and `REFERENCES` is what `-d` is handed and what the
pairwise gate counts -- the same directory for a run as it executes, the attempt's staged references for a re-score,
and the skip reason says which one it checked. In the panel, `/figures` shows the newest attempt's figures and counts
the earlier attempts as superseded (`analysis/runs/figures.current_figures`), and `/distance-diagnostics` reads the
newest attempt that published one.

### Panels: invariants and the 3D scene

A mapping whose current revision names `aa_reference.run_id` pins New Run's AA source: the picker is disabled, the AA
half's stage settings are filled from that run's recorded settings and locked, and deleting the source is not offered.
The panel clears its readiness answer whenever it re-asks, so a null answer is not an unlock; release happens on a
mapping change.

A fit job is polled by `?job_id=`, never by the mapping's hash: the hash is a mapping's history, the id is the job the
panel queued. Bead size and family colouring come from one table in `ngl-beads.js` (`BEAD_RADII_NM`,
`BEAD_FAMILY_ORDER`/`BEAD_FAMILY_COLOURS`/`BEAD_FAMILY_LABELS`), and the on-screen legend is drawn from that same table
(`renderBeadLegend`), so a new family is one entry.

A revision's terms name beads by their **export** name -- `B01` is the mapping's first bead, virtual sites included
(`mappings/exports.py`) -- so anything that needs a position translates them first. The scene did not, and drew no
bonded term at all until it did.

The 3D scene has one style per term kind (`bonded-plot.TERM_STYLES`): bonds the mapping's green; constraints a darker
shade of it, left on the bond they fix; angles amber **arcs** between the two arms at alpha 0.7, radius 35% of the
shorter arm; dihedrals green dashed at alpha 0.7, drawn as spine **and** arc -- the spine names the four atoms and is
stepped off the bonds by 1.8% of the molecule's diagonal, seeded per (kind, bead set) so a re-render moves nothing and
`ff_inter`'s eight harmonics of one torsion coincide, while the arc is the torsion itself, projected onto the plane
perpendicular to the central bond and swept **signed** between the two outer atoms, because the two signs are different
torsions; impropers slate dash-dot; virtual sites violet dotted. A virtual site is drawn twice: an open diamond as a
bead (a solid circle reads as an atom the model lacks) and a violet star from the site to each parent, because the term
names the site alone and the parents live on the mapping's bead record.

The bonded panels draw the selected candidate's own molecule (`bonded.js:resolveStructure`), never the packaged
reference: reading the reference for every candidate drew sucrose, trehalose and maltose on DDM's atoms.

### Mapping identity and deletion

`identity.candidate_identity` hashes numbers as values (`numbers_as_values`), so `1` and `1.0` are one identity: a
mapping is read as JSON, posted back by a browser, and JS has no int. Hashing spellings differently gave one mapping two
identities -- the file's and the posted snapshot's -- and a fit was filed under a digest no saved mapping addressed.
Reads fall back to `legacy_content_identity` for records written before that. Only `candidate_identity` normalises;
`canonical_sha256` and the file/snapshot digests are byte digests on purpose.

`save_draft` refuses a second draft whose beads, rings and connections hash the same (`DuplicateMapping`, naming the
file that holds it); `POST /api/mappings/drafts` answers 409 with `existing`; the editor disables Save-as-new from the
validation result's `duplicate_file` and names the file in `#automatic-message`. A rename is an in-place save, so it is
not a duplicate.

A parameterization is produced by `POST /api/bonded-parameterizations` (engines `fast-forward` and `bartender`, the
latter restricted to `-refit -owntraj`). Every engine fits to an AA ensemble, so `aa_reference` is required, and the
request makes no MD. The record carries a claim list (`owners`): a save claims the mapping, a draft delete releases its
claim, and the revisions go with the last claim (`parameterization.release`); a record written before claims existed
answers `why`, so the store falls back to asking the drafts on disk. Deleting a saved mapping also deletes the fit jobs
and staged frames built for it, which is why that one route (`DELETE /api/mappings/drafts/<name>`) says what went with
it, while the panel's own control deletes the parameterization and leaves the mapping alone.

### Scoring inputs: `ff_inter` and `ff_assess`

`ff_inter` writes `funct 9`, not `funct 1`: one `phi C mult` triplet per line, eight lines for one quadruple, so eight
lines are one dihedral with eight harmonics. A reader that assumes `funct 1` refuses the topology; one that treats each
line as a dihedral measures the same torsion eight times. `dihedral_fit.read_declared_dihedrals` merges them and
compares the whole curve; `bonded_terms` keeps the lines.

`ff_assess` scores against pre-computed reference distributions (`<group>_<type>_distr.dat` in its `-d` directory) and
does not make them. `ff_inter -dists -dist-matrix` writes them while fitting -- both families, through the tool's own
`interaction_distribution` and on its own bins (599 rows for `distances`, six hundred edges from `np.arange(0, 30, 0.05)`;
a hand-rolled 600-row or 0.01-nm grid is a different array) -- so `parameterization.save` copies and hashes every
`*distr.dat` beside the revision (`records/<content>.revisions/<n>/`; the tool's own glob, so the distance histograms
travel too) and `cg.prepare` stages them into `3_initial_CG` for a consuming run, recording how many are the pairwise
family (`distributions.json` `pairs`, and `bonded.reference_pairs` in the manifest).

The pairwise family (`<resid>_<a>_<resid>_<b>_distances_distr.dat`, one per bead pair, `n(n-1)/2` of them) is the one
that decides whether the stage can score at all: `score.py` `continue`s past a pair whose file is missing and leaves its
cell at 0.00, which reads **identical**. So a revision that records none still runs, but `prepare` writes an inventory
with that reason and stage 5 exits 4 with it (`skipped`) rather than printing an all-zero matrix; the stage asks the
directory it hands `-d` how many pair histograms are there, and reads the inventory from `3_initial_CG`, where `prepare`
writes it.

BARTENDER models get their own analysis instead (per-parameter `Bond_Hooke`/`Angle_Hooke`/`Cosine`/`Ryckaert-Belleman`
figures, 0.001 nm / 1 deg / 10 deg bins, bonded terms only) and cannot feed `ff_assess`'s histograms; unifying the two
is postponed. A bartender-parameterized mapping therefore runs with stage 5 `skipped` and its own sentence.

### Shapes, stages and series

A pdc belt is a **torus** when the protein states a membrane: the slab circle is the tube's centre-line, the tube radius
is the detergent's measured length, and `radius_nm` is a floor under that centre-line (`_belt_torus`, `SHAPE_TORUS`). A
build with no stated membrane keeps a **sphere** (`SHAPE_SPHERE`) whose radius is `radius_nm` or the selected beads'
extent about their centroid plus the clearance plus the detergent's length, whichever is larger: `radius_nm` is a
floor there too, and `radius_source` records which number won -- only an empty micelle, with nothing to measure, has
`radius_nm` itself. Protein secondary structure is martinize2's `-dssp`, which vermouth answers with mdtraj
(`pdc_build.SS_SOURCE`), and MDAnalysis' own DSSP is the recorded fallback (`SS_FALLBACK_SOURCE`); the two disagreed on
42 of 230 residues of 1AT9, and the assignment travels in the run report and — keyed by the residue numbers the
preview frame gives each residue — in the New Run preview's `basis` (see *New run*).

Protein-detergent stages run the repository's own scripts (`pdc_prepare.sh`, `pdc_system.sh`, `pdc_leg.sh`,
`pdc_assessment.sh`, `pdc_assess.sh`, `pdc_extension.sh`, `pdc_backmap.sh`), each recorded by path and digest in the
manifest's `stage_scripts`; no script is written into the run. The ten stage directories are numbered in execution
order (`01_prepare` … `10_backmap`), and a stage the settings rule out gets no directory at all -- what it would have
done is recorded in `skipped_stages`. `Energy minimisation`, `NVT` and `NPT` (`pdc.LEGS`, mdps under
`resources/templates/protein_detergent/`) are the equilibration, and `CG assessment MD` is production only, reading
`../05_npt/`.

The osmotic run type is one run owning N concentrations, listed in `settings.molalities` and gated to sugars: each
concentration gets its own directory and its own checkpoint (resumed with `gmx mdrun -cpi`), and `series_on_failure` is
`carry_on` or `stop`. The old one-concentration shape (`osmotic_molality`) is removed from the vocabulary, so it cannot
be rebuilt by accident.

### The detergent's own terms: a fitted mapping or the derivation

A mapping that carries a **current parameterization revision** is what a pdc build simulates: `pdc.prepare` resolves
the record by the content identity of the candidate it derived from (`parameterization.content_identity` /
`parameterization.one`) and writes that revision's topology as `detergent_CG.itp`. The revision's `[ atoms ]` name
column is rewritten to the mapping's bead names and nothing else is touched (`detergent_cg.adopt`), because
`pdc_build.stamp` writes the mapping's names into `system.gro` and `grompp` reconciles the two by name; a topology
whose atom count, bead types or molecule name disagrees with the mapping is refused there rather than failing three
stages later. A mapping with no record, or none current, keeps the derivation from the Martini 3 references and the
geometry, and `settings.detergent_model` says which happened: `source` is `the mapping's current parameterization` with
`parameterization {content_hash, revision, engine, created_at, scientifically_validated, aa_reference}` and
`term_kinds`, or `the mapping's derived topology: N reference terms, M fallbacks`. `pdc._limitations` states the same
in the run's own words, naming the revision and the AA run it was fitted from. The bead **positions** come from the
mapping either way, so the placement is identical.

### Back-mapping

CG2AT2 is vendored under `tools/cg2at/` (`tools/cg2at/cg2at`); `pdc_backmap.sh` runs its **align** method with the
`martini_3-0_charmm36` fragment DB. The `memembed`, `martinize`, `insane` and `cg2at` package names earlier notes named
are not maintained trees, and no `archive/` exists in this checkout.

A detergent is converted from a fragment written out of its own mapping: `execution/scripts/cg2at_fragment.py` turns a
mapping, the molecule's topology and its coordinates into the `[ BEAD ]`-sectioned PDB and itp CG2AT2 reads, and
`extend_forcefield` builds a force-field directory beside the vendored tree (a symlink farm, `ffnonbonded.itp` rewritten)
that carries the molecule's `[ atomtypes ]` and `[ pairtypes ]`, because GROMACS refuses those sections in a molecule itp
once a moleculetype has been read. Four details of the fragment's shape and two of the force field's are measured in the
modules themselves; the tests are `test_cg2at_fragment.py`.

The converted complex is then neutralised: `execution/scripts/pdc_neutralise.py` runs `grompp` and `genion -neutral` over
the conversion's own topology, because CG2AT2 returns the atomistic protein's protonation states against the ions the CG
system carried and nothing balancing them (measured on the 4iar/DDM complex: -5). It writes `neutralisation.json` with the
charge before and after, each moleculetype's share and the ions it added, and renames the water moleculetype (CG2AT2 writes
`tip3p`, its residues are `SOL`, and `genion` matches solvent by moleculetype name).

CG2AT2's own `-maxwarn` budget is hard-coded (1 for the minimisation and merge grompp calls, 2 for the steering leg) and the
converted complex trips three warnings: a duplicate dihedral line in CHARMM's `ffbonded.itp`, a `-D NP` macro its mdp
defines and its topology does not use, and Ewald in a system with net charge. The first two are noise; the third is what
the neutralisation answers. Until that leg passes, the tool's `-o align` output is not produced and `FINAL/final_cg2at_aligned.pdb`
does not exist: the stage therefore claims `FINAL/final_cg2at_de_novo.pdb`, which is a whole converted complex, and says in
`backmap.log` which of the two it produced.

### mdrun device and stage flags

`mdrun_gpu` (an integer CUDA ordinal, default 0) is the only statement of the device. `aa.mdrun_command_flags` is the
only builder that writes `-gpu_id`, and it fills `MDRUN_FLAGS` (the nonbonded bracket) and `MDRUN_FLAGS_PME` (PME
offloaded), which `workflow.py` puts in each stage's environment; a stage script therefore states neither a device nor
an offload scheme, and `em` keeps PME on the CPU as it always did. `execution/devices.py` probes the host with
`nvidia-smi` and asks the driver API (`cuDeviceGet`/`cuDeviceGetPCIBusId`) for CUDA's own order: `detect()` reports
the CUDA ordinal as `index`, keeps `nvidia-smi`'s row as `nvml_index`, and carries `bus_id` so the two enumerations
can be checked. `detect()` is cached for 30 s per process; `in_use()`, `describe()` and `require()` read the same
record, and prepare refuses an index the host reports and does not have, by name, with the devices that do exist.
`GET /api/run/devices` feeds the New run select and its sharing note; `views.gpu_name` puts the device's name in the
run view, read from the manifest rather than from the form.
