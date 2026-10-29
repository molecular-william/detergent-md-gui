# What happens when a new run is initiated

A walkthrough of one New Run submission, from the browser to the first `mdrun`, and of everything a run
writes under `workspace/dashboard/runs/<id>/`. It is grounded in the current checkout: the code is the
authority, this file only follows it. Symbols are named rather than line-numbered, because line numbers move.

Companions: `docs/PROJECT_GUIDE.md` (run contract, stage lists, workspace layout) and `AGENTS.md` (invariants).

---

## 1. The short version

A New Run is a **JSON POST of identifiers and settings**, never files. The route admits it, the coordinator
turns it into one row in `jobs.sqlite3` plus one worker thread, and that thread creates the run directory,
re-checks readiness, lets the run type's adapter *write the run*, then executes the stages one at a time as
`bash -e -o pipefail <stage script>` with the stage's own directory as the working directory. Every stage
appends a record — command, environment, input hashes, output hashes, exit code, log path — to
`manifest.json`. When the last stage ends, the run is marked terminal and the analyses the run owes are queued
in a separate subprocess.

Four things a run consumes. Three are recorded by path and digest and read where they already live — the
molecule, the mapping, the parameterization; the fourth is the AA reference, which travels by a hand-off of its
own:

| Kind | Read from | In the run? |
| --- | --- | --- |
| Canonical molecule (`molecules/<id>/…`) | repo `molecules/` | **referenced** in `inputs/inputs.json` by aa_only (one entry per molecule file) and pdc (the imported protein, or a no-protein marker); aa_cg records the `molecule_snapshot` instead and derives its names from it |
| Mapping (bead assignment) | `workspace/dashboard/mapping_drafts/*.json` (or an absolute path outside the workspace) | **referenced** as a store/absolute entry; aa_cg exports `mapping.map`/`mapping.ndx`/`model.json` as generated data, pdc derives `detergent_CG.itp`/`.json` from it |
| Parameterization (fitted bonded terms) | `workspace/dashboard/parameterizations/` | **referenced**: the current revision's AA reference histograms are store entries; the revision record itself is re-written as generated data, and pdc adopts its topology as generated `detergent_CG.itp` |
| AA trajectory of a shared reference | another run's `stages/07_reference/` | **not copied and not in `inputs.json`**: `shared_reference` in the manifest plus `AA_REFERENCE_DIR`, re-resolved and re-verified before every stage |

The difference between "referenced" and "generated" is the whole point of the record: a referenced input
already existed when `prepare` ran (published in the repository, in a workspace store, or in another run) and
is pinned by path and sha256; a generated input is something `prepare` synthesized and wrote into `inputs/`.

---

## 2. Schematic: control flow

```text
 ┌───────────────────────────── Browser ──────────────────────────────┐
 │  New Run panel:  static/js/new-run.js   (pdc panel: pdc.js)        │
 │                  static/js/osmotic.js                              │
 │                                                                    │
 │  pre-flight GETs, no state written:                                │
 │    /api/molecules  /api/defaults  /api/readiness                   │
 │    /api/references /api/pdc/models /api/run/devices  /api/storage  │
 │                                                                    │
 │  submit:  POST /                     (aa_only, aa_cg, pdc,         │
 │                                       cg_composition)              │
 │           POST /api/osmotic/series   (one run owning N molalities) │
 └──────────────────────────────────┬─────────────────────────────────┘
                                    │ JSON: run_type, molecule_id, method,
                                    │ mapping_candidate, reference_run_id,
                                    │ settings… (no file uploads)
                                    ▼
 ┌────────────────────────── web/routes ──────────────────────────────┐
 │  runs.py:queue                              osmotic.py:series_api  │
 │    admission.validate_run_type()                                  │
 │    protocol.run_type_of()                                         │
 │    protocol.profile_for_run_type()   ← aa_cg ⇒ draft-smoke-       │
 │    protocol.adapter_for().settings_specs()/choice_specs()          │
 │      (the route keeps only keys the run type advertises)           │
 └──────────────────────────────────┬─────────────────────────────────┘
                                    ▼
 ┌──────────────── execution/coordination/coordinator.py ─────────────┐
 │  Coordinator.create_job()                                         │
 │    ├─ aa_cg: load mapping snapshot, resolve AA reference,          │
 │    │         cg.readiness();  no reference ⇒ create AA parent +    │
 │    │         one `waiting` consumer in the same transaction        │
 │    ├─ pdc / osmotic / cg_composition: own readiness                │
 │    ├─ resources.admit()  (concurrency, disk, scratch)              │
 │    ├─ Store.insert()  →  workspace/dashboard/jobs.sqlite3          │
 │    └─ Worker(); Thread(target=run_job)                             │
 └──────────────────────────────────┬─────────────────────────────────┘
                                    ▼  worker thread
 ┌──────────────────────────── Coordinator.run_job() ─────────────────┐
 │  mkdir runs/<id>/  +  runs/<id>/logs/                              │
 │  write initial manifest.json  (id, status=running, stages=[])      │
 │  take fcntl lease on runs/<id>/.worker.lock                        │
 │  adapter.readiness(metadata)          — re-checked server-side     │
 │  adapter.prepare(run_dir, metadata)   — writes stages/ and inputs/ │
 │    └─ the adapter writes the stages that will run, the data it     │
 │       synthesized into inputs/, and inputs/inputs.json             │
 │  run_inputs.verify_manifest()         — the record it just wrote   │
 │  manifest.json rewritten with layout_version 3, plan, tools,       │
 │    inputs, input_snapshot_sha256, stage_scripts, python_modules    │
 │  workflow.run(run_dir, log, execute=worker.execute)                │
 │      for each stage in the plan:                                   │
 │          verify inputs.json, the stage script and every module     │
 │          bash -e -o pipefail <stage script>  (cwd = stage)         │
 │          stdout/stderr → logs/<stage dir>.log                      │
 │          manifest stage entry updated with hashes/exit code        │
 │  manifest.status = completed                                       │
 │  run_completed() → analysis_coordinator queues owed analyses       │
 │  finish_job(): terminal DB write, artifact index, release lease,   │
 │                schedule_waiting() (starts a waiting CG consumer)   │
 └──────────────────────────────────┬─────────────────────────────────┘
                                    ▼
 ┌──────────────── analysis/worker.py (separate process) ─────────────┐
 │  python -m dashboard.analysis analyses/<kind>/<sig>/<aid>/request  │
 │  copies declared sources to a temp dir, runs the kind, publishes   │
 │  analyses/<kind>/<signature>/<attempt>/output/<source-key>/…       │
 └─────────────────────────────────────────────────────────────────────┘
```

### AA-CG: one launch can create two rows

An AA→CG run without a completed reference is a `waiting` CG consumer plus an AA source that runs now:

```text
POST / (run_type=aa_cg, reference_run_id absent)
        │
        ├── row A: run_type=aa_only   status=queued    ← this one gets the worker
        └── row B: run_type=aa_cg     status=waiting   reference_run_id=A
                                          │
                      A completes ────────┘
                      ensure_service()/finish_job() → schedule_waiting()
                      resolve + verify A's 07_reference, row B → queued, new worker
```

`insert_many()` writes both rows in one SQLite transaction and refuses a consumer whose source row is absent.

---

## 3. Step by step

### 3.1 Pre-flight (nothing persisted)

`new-run.js` fills the form from `/api/defaults?run_type=…` (values are read from the MDP profiles and the
force-field registry, not from a table in the browser), asks `/api/readiness` (the run type's own answer:
molecule, tools, mapping, parameterization state), and `/api/references` lists completed `aa_only` runs whose
`07_reference/reference.json` still verifies. The pdc panel additionally asks `/api/pdc/models` and
`/api/pdc/preview/placement` (the latter caches only its martinize2 step under `workspace/dashboard/preview/`,
which no run reads).

### 3.2 The queue route

`dashboard/web/routes/runs.py:queue` (`POST /`):

1. `admission.validate_run_type` — refuses unknown run types and fields a type does not own (e.g. `aa_only`
   with `mapping_candidate`, a `cg_composition` without `composition_id`).
2. `protocol.run_type_of(data)` — absent `run_type` means the historical combined `aa_cg`.
3. `profile = data.get('profile') or protocol.profile_for_run_type(run_type)` — an `aa_cg` run is stamped
   `draft-smoke-reference`; every other type `standard`.
4. `settings = {k: data.get(k) for k in specs if data.get(k) not in (None, '')}` — the route forwards only the
   keys the run type advertises (`settings_specs() | choice_specs()`).
5. `Coordinator.create_job(...)`.

`/api/osmotic/series` does its own checks first (solute is a sugar, `solute_root` holds the required files,
every molality can be placed), then calls the same `create_job` with `run_type='osmotic'` and a settings dict
carrying `molalities` and a `series_id`.

### 3.3 `create_job`: record construction, admission, worker start

In `dashboard/execution/coordination/coordinator.py`.

| Run type | What happens before the row is inserted |
| --- | --- |
| `aa_only` | `aa_job_record()`: validate molecule id, `aa_molecules.selection()`, `aa.normalize_settings()`, `aa.readiness()`; `stage_plan` from `aa.STAGES` |
| `aa_cg` | load mapping snapshot (`models.mappings.get` + `draft_model.load`), resolve a named reference (`aa_references.resolve`), `cg.readiness()`, `cg.normalize_settings()`; if no reference, build the `aa_only` parent first |
| `cg_composition` | `compositions.get()` + `composition.readiness()`; artifacts must exist |
| `pdc` | `pdc.readiness(protein, template)`; `pdc.normalize_settings()`; `prepare_protein` forced off for a protein-free build |
| `osmotic` | `osmotic.readiness()` (sugar gate, mapping bead radii, `solute_root`, gmx) |

A retry that carries a molecule snapshot the store no longer matches is refused here (`Molecule files changed;
clone with a fresh selection instead`), so a retry cannot silently run against a changed molecule.
Then `resources.admit()` (concurrency, disk headroom, scratch), `Store.insert` (one row in the `jobs` table;
`data` is the whole JSON record), `self.WORKERS[jid] = Worker()` and a daemon thread running `run_job(jid)`.

The job id is `uuid4().hex[:12]`, which is also the run directory name and the only id ever used in paths.

### 3.4 `run_job`: the run directory and the adapter's `prepare`

`run_job` (`coordinator.py`) does, in order:

1. `mkdir runs/<id>/` and `runs/<id>/logs/`; for an in-place resume it reuses the existing directory.
2. Writes the **initial** `manifest.json`:
   `{id, status: running, stages: [], run_type, workflow_version, protocol_version, stage_plan, reference_run_id, shared_reference, molecule_id, molecule_snapshot, composition_id, composition_snapshot_sha256}`
   (only the keys the job record actually carries).
3. Takes an `fcntl` lease on `runs/<id>/.worker.lock` (held across the whole run and passed to subprocesses).
4. Re-runs `adapter.readiness(...)` — the same check the panel saw, enforced server-side.
5. Calls `adapter.prepare(run_dir, metadata)` and then verifies the record it wrote
   (`run_inputs.verify_manifest`). What `prepare` writes is the subject of section 5.
6. Reads the manifest the adapter wrote and rewrites it with `status: running`, `started_at`, id, run type
   and the molecule/composition identity the job carries.
7. `workflow.run(...)`.

Every run type now goes through the same two directories: `stages/`, holding one directory per stage that
will run, and `inputs/`, holding the generated data and the record. There is no layout fallback any more:
`workflow.stage_root` requires `stages/` for an execution, and the readers keep `analysis/runs/layout.stage_root`
(`stages/` when present, the root for a staged analysis work directory) because an analysis subprocess is handed
a stage-root copy rather than a run directory. `protocol.finish_prepared_run` is the
shared tail for AA-only and AA-CG: it removes the adapter's own record from `stages/`, mirrors the filled
`stages/` tree into `inputs/` (so generated data is kept beside the record), and calls
`protocol.write_prepared_manifest`. `write_prepared_manifest` is what every run type uses: it writes the
manifest's common keys (`layout_version: 3`, `stage_plan`, empty `stages`, `tools`, `environment` with the
host's devices, `prepared_at`), and, when given them, the `inputs` record with its `input_snapshot_sha256`,
`stage_scripts`, `python_modules` and the prepare-time `skipped_stages`.

**pdc, osmotic and composition do not mirror `stages/` into `inputs/`**: they write only generated data into
`inputs/` and call `write_prepared_manifest` directly, because their stage directories hold what a stage
itself writes when it runs rather than data prepared for it.

### 3.5 `workflow.run`: stage execution

`dashboard/execution/workflow.py:run`:

* Reads the stage contract from the manifest's run type (`protocol.adapter_for(...).stage_contract(metadata)`).
  The manifest's `stage_plan` is the run's own record of what it prepared; a migrated legacy run is read-only for
  the view and analysis paths, because its plan predates the current contract and its scripts were archived.
* Before every stage, re-verifies the run's input record when it has one (`run_inputs.verify_manifest`): a
  published, stored or generated input changed under a prepared run refuses the next stage, naming the file.
* Records a prepare-time skip without executing anything: `manifest.skipped_stages` names the stage and its
  reason, no directory exists, and the manifest entry is `skipped` with `command: []` and the reason. The run
  carries on, and a resume treats such a stage as part of the completed prefix.
* Skips stages already `completed`/`reused` (resume), verifying their declared output hashes first unless this
  is an in-place resume.
* For each stage, before execution:
  * re-hashes every recorded `python_modules` entry, then resolves the stage's script through
    `run_scripts.script_for` — the recorded repository file, re-hashed, or the stage's own copy in a legacy
    run. A changed repository script or helper refuses the stage, naming it.
  * hashes the **declared inputs** only (not the whole directory) into `inputs_sha256` (stage-relative) and
    `dependency_sha256` (stage-root-relative);
  * appends the stage entry to `manifest.json` with `status: running`, `command`, `cwd`, recorded environment,
    `started_at`, log path;
  * opens `logs/<stage directory>.log` (or `logs/resume-NNNN/<stage>.log` on a resumed attempt) and appends a
    `## <Stage name>` + `$ <command>` block to `logs/console.log`;
  * builds the environment (below);
  * validates the stage's declared inputs with `validate_stage_inputs`.
* Executes `["bash", "-e", "-o", "pipefail", "<stage script>"]` with `cwd=<stage directory>` via
  `Worker.execute` (own session, process group signalled only by the current worker). The script is the
  repository file `run_scripts.script_for` resolved, or a legacy run's own copy; `aa_only`'s is generated by
  `prepare`.
* Exit `4` is the fourth contract outcome: `skip.json` beside the working directory holds the reason; the
  stage is recorded `skipped` and the run carries on. Any other non-zero exit fails the stage and the run.
* Verifies every declared output exists and is non-empty, records `outputs_sha256`, `exit_code`, `ended_at`
  and `resource_usage` (`wall_seconds`, `openmp_threads`, `mpi_ranks`, `gromacs_flavour`, `gpu`,
  `output_bytes`).
* After the last stage: `manifest.status = completed`, then `run_completed(run_dir)` notifies the analysis
  coordinator.

#### The executor's environment

| Variable | Set to | Why |
| --- | --- | --- |
| `PATH` | `tools.search_path()` | the resolved tool installation, not the caller's |
| `MPLBACKEND` | `Agg` | no display in a worker |
| `OMP_NUM_THREADS` | `8`, then overwritten by the `-ntomp` value in `MDRUN_FLAGS` | GROMACS refuses a command line that disagrees with the environment |
| `PYTHON` | `sys.executable` | the interpreter this application runs, so `"$PYTHON" -m …` uses the venv |
| `PYTHONPATH` | the checkout (`environment.ROOT`) | the stage scripts import `dashboard.*` from the tree |
| `STAGE_DATA` | `<stage directory>/stage.json` | the per-stage record a script may read its own numbers from (the pdc legs read `inputs/<leg>.json` instead) |
| `RUN_SETTING_<KEY>` | every scalar run setting, upper-cased | one shared repository script serves every run; no value is stamped into a copy |
| `MDRUN_LAUNCHER`, `MDRUN_FLAGS`, `MDRUN_FLAGS_PME` | `aa.mdrun_command_flags` | the only builder of the device, ranks, threads and PME bracket |
| `AA_REFERENCE_DIR` | the verified source run's `stages/07_reference` | a shared reference is read where it lives |
| `MOLECULE_TYPE`, `INITIAL_ITP`, `FINAL_ITP` | `CGNames` | a stage does not guess the molecule's filenames |

The manifest's `environment` records `PATH`, `MPLBACKEND` and `OMP_NUM_THREADS` for the run, and each stage
entry records those plus `PYTHON`, `PYTHONPATH`, the mdrun flags, `AA_REFERENCE_DIR` when present and the
molecule names. `environment.devices` records every GPU the host reported at prepare.

### 3.6 The terminal write and follow-ons

`finish_job` (inside `run_job`):

* writes the run's terminal status into `manifest.json` and the DB row (`completed`, `failed`, `cancelled` or
  `blocked`), sets `reference_eligible` for a completed `aa_only` run;
* refreshes the artifact index (the `artifacts` table; the run's tree is indexed lazily);
* closes the worker lease, drops the worker and calls `schedule_waiting()` so a CG consumer waiting on this AA
  source can start;
* if the run of an osmotic series failed and asked `series_on_failure: stop`, stops its siblings.

Analyses (`analysis_coordinator.run_completed`) are queued on a short-lived thread once the run is actually
free. `queue_defaults` → `drain` queues, one at a time, `kinds.for_every_run()` (`snapshots` for every run with
a trajectory) plus `kinds.default_for(run_type)` (`dihedral-fit`, `bonded-cross-check` for `aa_cg`). Each attempt
executes `python -m dashboard.analysis <attempt>/request.json` in its own process and writes under:

```text
runs/<id>/analyses/<kind>/<signature>/<attempt-id>/
  request.json        # run path, kind, payload, code signature, dependencies
  manifest.json       # the task record (status, outputs, …)
  sources.json        # copied source → sha256
  progress.json       # last phase
  console.log
  result.json         # result, output_directory, source/output hashes, tools, wall_seconds
  output/<source-key>/…   # the published files, one immutable set per source-key
```

An analysis with nothing to sample records `skipped` instead of failing the analysis.

---

## 4. Schematic: where the bytes move

```text
 PUBLISHED INPUTS (repo, read-only)                 RUN DIRECTORY (workspace, writable)
 ───────────────────────────────────                ───────────────────────────────────
 molecules/<id>/{itp,gro,pdb,metadata,…}   ──named──▶ inputs/inputs.json entry (kind=published)
                                            not copied  (aa_only: one entry per molecule file)

 force-field tree (registry entry)         ──named────▶ inputs.json entry (aa_only, kind=published,
                                                          a directory entry with its file-hash digest)
 workspace/dashboard/martini3/*.itp         ──named────▶ inputs.json entries (aa_cg, pdc, osmotic:
   (installed once from references/,                    kind=published, root=workspace) -- the three libraries,
    digest-verified; see §7)                            the sugar reference and its provenance
 water.gro, vdwradii_AA.dat                 ──named────▶ inputs.json entries (aa_cg, kind=published)
 protein-detergent template topology       ──named────▶ inputs.json entry (pdc, kind=published)

 molecules/<id>/molecule.itp               ──generated shim──▶ inputs/common/molecule/molecule.itp
                                                            (#include "<store path>")
 mapping_drafts/<file>.json                ──named────▶ inputs.json entry (kind=store)
                                            ──export──▶ stages/2_mapping/{mapping.map,mapping.ndx,
                                                          model.json,README.txt} (+ draft-source.json)
 parameterizations/<hash>/revisions/<n>/   ──named────▶ inputs.json entries (reference histograms)
                                            ──write──▶ stages/3_initial_CG/{parameterization.json,
                                                         distributions.json}
                                            ──adopt──▶ inputs/detergent_CG.itp (pdc)

 another run: runs/<aa>/stages/07_reference/  ──verify only, no copy──▶ AA_REFERENCE_DIR
                                                         + manifest `shared_reference`

 generated by prepare. AA/CG write it under stages/ and mirror it into inputs/; pdc, osmotic and
 composition write only into inputs/:
   aa_only:  context.json, solute.ndx, run.mdp, system.top, molecule.gro,
             the stage scripts (generated, not copied), molecule.itp shim
   aa_cg:    2_mapping export, 3_initial_CG topologies/mdps, 4_CG_sim MDPs + system_EMPTY.top,
             5_assessment/references.txt, 6_SASA/CG/vdwradii.dat
   pdc:      pdc-settings.json, system_EMPTY.top, detergent_CG.itp/.json, the MDPs, the legs' records,
             extension.ps, water.gro, protein.pdb (no-protein marker only)
   osmotic:  conditions.json, conditions/<dir>/{mdp set, reference.itp, osmotic_condition.json}
   cg_composition: nothing (inputs/ holds only inputs.json)

 REPOSITORY CODE (never copied into a run)
 dashboard/execution/scripts/*.sh   ──executed in place, cwd = stage directory; digest in `stage_scripts`
 dashboard/**/*.py helpers          ──imported in place; digest in `python_modules`
```

---

## 5. What each run type writes during `prepare`

### `aa_only` — `execution/adapters/aa.py:prepare_run`

Writes generated data into `stages/`, then `finish_prepared_run` mirrors it into `inputs/` and writes
`manifest.json`.

```text
stages/
  common/
    molecule/
      molecule.gro         generated from the source PDB when needed (+ conversion record)
      molecule.itp         generated one-line include naming the stored topology by absolute path
    context.json           protocol version, settings, molecule snapshot, FF digests, preparation record
    solute.ndx             generated index
  01_solvation/{run.sh,system.top,run.mdp}
  02_ions/{run.sh,run.mdp}
  03_minimization/{run.sh,run.mdp}
  04_nvt/{run.sh,run.mdp}
  05_npt/{run.sh,run.mdp}
  06_production/{run.sh,run.mdp}
  07_reference/{run.sh}
inputs/                    generated data above, byte-for-byte mirror of stages/ (no manifest.json)
  inputs.json              the input record
manifest.json              layout_version 3, input record + digest, stage plan, tools, environment,
                           python_modules, mdp_profiles
```

The stage scripts are **generated strings**, not files copied from `scripts/`: `gmx editconf/grompp/solvate`,
`gmx genion` (+ a `"$PYTHON" -m dashboard.analysis.runs.references solvent-index` call), four `grompp`+`mdrun`
pairs, then `07_reference/run.sh` (`gmx trjconv`, `convert-tpr`, `energy`, then
`"$PYTHON" -m dashboard.analysis.runs.references publish ..`), which writes
`07_reference/{lig.gro,lig.xtc,lig.tpr,diagnostics.xvg,reference.json}`. The three Python helpers the scripts
call are recorded in `python_modules` and run from the checkout; the force-field tree and the molecule's own
files are recorded in `inputs` and never copied. `mdp_profiles` names the reviewed profile behind each of the
six MDPs.

### `aa_cg` — `execution/adapters/cg.py:prepare` + the adapter's `_protocol_prepare`

```text
stages/
  1_AA-reference/            empty: the stage is recorded `reused` and the source is read in place
  2_mapping/
    mapping.map, mapping.ndx, model.json, README.txt   the mapping export (generated)
    draft-source.json                    the loaded mapping snapshot, verbatim
  3_initial_CG/
    <RES>_initial.itp                    generated by draft_model.initial_topology
    topol.top, initial.mdp
    [parameterization.json, distributions.json]        only for a run that consumes a revision
  4_CG_sim/
    inputs/{minimization,eq,md}.mdp      written from the reviewed profiles
    system_EMPTY.top                     generated include/molecule table
  5_assessment/references.txt            the directory stage 5 scores against
  6_SASA/{AA,CG}/vdwradii.dat            CG radii generated from bead sizes R/S/T
inputs/                                    mirror of the generated stage tree (no code, no manifest)
  inputs.json                              published Martini/water/radii/sugar entries and the revision's
                                           reference histograms (store entries)
manifest.json                              stage_scripts (six), python_modules, mdp_profiles,
                                           shared_reference, force_field provenance, bonded{}
```

`shared_reference` is recorded in the manifest and the source AA run's `07_reference` is **not** copied and not
listed in `inputs`. The `AA reference` stage is recorded `reused` with `command: []`; every later stage receives
`AA_REFERENCE_DIR=<source run>/stages/07_reference`, and the input check skips the `1_AA-reference/prod/`
patterns. The source is re-verified (`aa_references.resolve` → `verify`) at prepare and again before each
stage. The atomistic force-field tree is deliberately absent: this run type never reads it, and its digest
stays in the manifest's `force_field` provenance.

### `pdc` — `execution/adapters/pdc.py:prepare`

Writes only the stage directories that will run — empty until their scripts execute — and generated data into
`inputs/`. There are ten stages, numbered in execution order:

| Directory | Stage (human name) | Not written when |
| --- | --- | --- |
| `01_prepare` | Protein preparation | the run has no protein, or `prepare_protein` is off |
| `02_system` | System preparation | never |
| `03_minimisation` | Energy minimisation | `minimisation_steps` is 0 |
| `04_nvt` | NVT equilibration | `nvt_ps` is 0 |
| `05_npt` | NPT equilibration | `npt_ps` is 0 |
| `06_assessment` | CG assessment MD | never (it also carries the extension's duration when removal is off) |
| `07_micelle_assessment` | Micelle assessment | `remove_out_of_micelle` is off |
| `08_extension` | CG extension MD | `remove_out_of_micelle` is off |
| `09_final_assessment` | Final assessment | `remove_out_of_micelle` is off |
| `10_backmap` | Back-mapping (CG2AT2) | the run has no protein, or `backmap` is off |

A skipped stage has **no directory, no script and no `skip.json`**: `pdc._skipped_stages` writes the reason
into the manifest's `skipped_stages`, and `workflow.run` records it `skipped` and carries on. Only the settings
decide this — a stage script never decides a settings-driven skip at run time.

```text
stages/<NN_stage>/        empty at prepare; a leg copies only the previous phase's system.gro/system.top
inputs/
  inputs.json             the input record
  pdc-settings.json       the run's numbers and decisions, including force_field.root and the model
  system_EMPTY.top        the pre-detergent topology
  detergent_CG.itp/.json  generated from the mapping (or the template when none was given)
  protein.pdb             only for the no-protein build: a marker file, not a structure
  assessment.mdp, the legs' mdps, ions.mdp, extension.mdp, minimization.mdp, equilibration.mdp
  <leg>.json              each equilibration leg's own record (its mdp, source phase, checkpoint)
  extension.ps, water.gro
manifest.json             skipped_stages, stage_scripts (all ten), mdp_profiles (only written files),
                          settings, protein, template, tools, limitations
```

The Martini 3 libraries are named in `inputs` as the workspace's installed set (§7) and every `grompp` step reads
them there; the template's topology, the protein and the mapping are named the same way (or recorded absolutely
when they live outside the workspace). Nothing a leg reads is copied: `system.top` names each dependency by a path
relative to the stage directory it is read in, so the copy of `system.top` a leg carries forward resolves from any
sibling. The only files a leg copies in are the previous phase's `system.gro` and `system.top`, which it goes on to
edit. The MDPs are written from `dashboard/execution/mdp/profiles.py` profiles.

### `osmotic` — `execution/adapters/osmotic.py:prepare`

```text
stages/01_simulate/          the series driver's working directory; the generated per-condition records are
                             copied beside it at prepare (conditions.json, conditions/<dir>/…)
inputs/
  inputs.json                the solute's four files (store or absolute) and the Martini ITP (published)
  conditions.json            ordered conditions + series_on_failure + attempts_max
  conditions/<dir>/          the mdp set, reference.itp and osmotic_condition.json (+ control.json at 0 M)
manifest.json                series record, stage_scripts, python_modules
```

One stage (`Osmotic series`) drives all conditions; each condition has its own `attempts.json`, checkpoints and
`built.json`/`system.top`/`prod/md_whole.xtc` outputs. Its MDPs are still rendered by
`osmotic_mdp.osmotic_mdps` (the reviewed `osmotic-*` profiles exist and the parity gate compares them), so this
run type is the one that does not record `mdp_profiles`.

### `cg_composition`

Writes a deliberately minimal, offline screening run: `stages/1_CG-simulation/`, `stages/2_CG-assessment/`,
`stages/3_CG-SASA/` (empty directories; the stages run the repository's composition scripts), the four
immutable composition artifacts named in `inputs` (store entries, or absolute when outside the workspace; no
copy is made), `inputs/inputs.json`, and a manifest that says `execution_kind: screening-stub` and that no
GROMACS MD ran.

---

## 6. Files a run writes *during* execution

| File | Written by | Content |
| --- | --- | --- |
| `manifest.json` | coordinator + `workflow.run` | stage ledger; updated atomically at every transition |
| `logs/console.log` | `workflow.run` | one `## Stage` + `$ command` block per stage, plus failure lines |
| `logs/<stage dir>.log` (or `logs/resume-NNNN/…`) | stage subprocess stdout/stderr | full stage console |
| `runs/<id>/.worker.lock` | `Coordinator.lease` | flock guard; never signalled as a PID |
| `skip.json` | a stage that had nothing to do | its reason; exit 4. A prepare-time skip has no directory, so no `skip.json` |
| stage outputs | the stage scripts | see each adapter's `STAGES`/`STAGE_DEFS` and section 5 |
| `analyses/<kind>/…` | `analysis/worker.py` | immutable attempt record + output set (post-run) |

Everything structured goes through `files.atomic_json` (temp file + `os.replace`); a run is never rewritten
by a later run, and a completed run's `stages/` is not touched (analyses copy their sources).

---

## 7. On-disk layouts

```text
workspace/dashboard/
  jobs.sqlite3                ← the only live job store (table `jobs`, table `artifacts`)
  martini3/                   ← the installed Martini 3 set every run reads, with its `martini3.json` record of the
                                upstream commit and every file's digest. Installed once from `references/` by the
                                first reader (`dashboard/martini3.py`); never written by a run, never copied into one.
  runs/<id>/
    manifest.json
    inputs/inputs.json        the input record: {role,label,kind,root,path,sha256,bytes[,files]}
    inputs/…                  generated data (aa_only and aa_cg mirror their stages/ tree here; pdc, osmotic
                              and composition write only generated data)
    stages/                   every run type's stage directories
    logs/{console.log, <stage>.log, resume-NNNN/…}
    analyses/<kind>/<signature>/<attempt>/{request,sources,progress,result,manifest}.json
                                             console.log  output/<source-key>/…
    .worker.lock

  aa_only:        stages/{common,01_solvation … 07_reference}
  aa_cg:          stages/{1_AA-reference,2_mapping,3_initial_CG,4_CG_sim,5_assessment,6_SASA}
  cg_composition: stages/{1_CG-simulation,2_CG-assessment,3_CG-SASA}
  pdc:            stages/{01_prepare … 10_backmap}
  osmotic:        stages/01_simulate
```

An `inputs` entry is `{"role", "label", "kind", "root", "path", "sha256", "bytes"}` for a file and adds
`"files"` (a count) for a directory; `kind` is `published`, `store`, `run-output` or `generated`, and `root`
is `repo`, `workspace`, `run`, `runs` or `absolute`. `run_inputs.write` records every file under `inputs/`
that is not `inputs.json` as a `generated` entry, refuses a duplicate `(root, path, role)`, and
`run_inputs.digest` hashes the whole document (`{"inputs": […]}`) into the manifest's
`input_snapshot_sha256`. A manifest edited after the fact, or an input changed since prepare, is refused
before the next stage runs.

### The layout before this one, and the migration

Ten runs predated it (a failed `pdc` run that could not finish its assessment was deleted by the user before it
was migrated). Nine `aa_only`/`aa_cg` runs kept a byte copy of their prepared stage tree in `inputs/` and copied
`.py`/`.sh` helpers inside their stages (their manifests record `layout_version: 2` and the old file-hash map as
`input_snapshot_sha256`); two `pdc` runs kept their stage directories at the run root, with no `stages/`, no
`inputs/` and no input snapshot.

`dashboard/cli/migrate_run_layout.py` was applied to the live workspace on 2026-10-27: it archives the old
`inputs/` and copied code, or a pre-numbering pdc stage tree, to `legacy_evidence*.tar.gz` (written with `pigz`
when installed), proves the archive reads back as the tree it was made from, deletes or moves the live copies,
and writes `legacy_layout.json`. `manifest.json` is never rewritten, so a migrated run's old
`input_snapshot_sha256` stops verifying and its own record says why. All ten surviving runs now have `stages/`
and `legacy_layout.json`.

A migrated run is a **read-only record** for the view and analysis paths: its plan predates the current stage
contract, its helper copies are archived, and its `inputs/` is gone.

**The Martini 3 copies were migrated the same day, by a script that no longer exists.** Every run prepared before the
shared install carried its own copies of the three Martini libraries in each stage directory that ran `grompp`, and
(each pdc run) its own `detergent_CG.itp` beside them. `cli/migrate_shared_itps.py` replaced a copy with a **relative
symbolic link** -- to `workspace/dashboard/martini3/<name>` for a library, to the run's own `inputs/detergent_CG.itp`
for the detergent's topology -- only when the bytes were identical, and left everything else alone. It rewrote no
manifest, no `inputs.json` and no topology; the recorded output digests still verify because a hash follows the link.
Applied to the live workspace: 11 runs inspected, 47 files considered, 44 linked, 3 left as they were
(`22075892b606`, `a2a457cf9413`, `ce1318485197` each carry a `martini_v3.0.0_solvents_v1.itp` with two extra
antifreeze-water moleculetypes the published file does not have), and each run that gained a link holds a
`shared_layout.json` recording what it links to and what was left alone. `00b9ae6db23f`'s six `detergent_CG.itp` copies
stay: its `inputs/` was archived by the layout migration, so the run has no other copy to link to. Runs prepared from
now on need no migration at all. The install itself is `workspace/dashboard/martini3/` -- 33 ITPs, the sugar reference
and its provenance, the licence and `martini3.json` -- installed from `references/` on first use and verified against
that record before a run reads it. Readers still resolve its `stages/` and its
legacy directory spellings (`layout.PDC_STAGE_DIRECTORIES`), and `run_inputs.verify_manifest` keeps the old
directory-digest path for a manifest with no `inputs`; resume, fork-resume and clone of a migrated run are not
offered by this layout (use the archive if those bytes are needed).

---

## 8. The AA reference hand-off, in detail

1. Source run (`aa_only`) publishes `stages/07_reference/reference.json` with `reference_eligible: true`, frame
   count/times, diagnostics, `molecule_identity`, and a sha256 map covering `lig.gro`, `lig.xtc`, `lig.tpr`,
   the molecule files, the force-field sources and the production artifacts.
2. A CG run names it as `reference_run_id`; `aa_references.resolve` verifies the run is a **completed**
   `aa_only` run, verifies every recorded hash still matches, checks molecule identity and (where supplied)
   settings agreement, and returns the directory.
3. `cg.prepare` records `shared_reference = {source_run_id, sha256}` on the consumer's manifest and marks
   `reference_reused: true`. The reference is not an entry in `inputs`: it already has its own verified record
   and re-verifying that is stronger than a second digest.
4. `workflow.run` re-resolves it before every stage, exports `AA_REFERENCE_DIR`, and skips the atomistic
   inputs from the stage's own input check.
5. The source run cannot be deleted while a consumer references it (`Store.delete_with_cleanup` guards
   `reference_run_id` / live `resume_of`), and the consumer's completed analyses keep using the source's
   `07_reference` via `analysis/worker.source_entries`.

A mapping whose **current parameterization revision** names an `aa_reference.run_id` pins the New Run panel's
AA source; that is a UI lock plus a server-side check, not a copy.

---

## 9. Resume, retry, clone — the differences that matter

| Action | New id? | Directory | What is reused |
| --- | --- | --- | --- |
| `POST / (new)` | yes | new | nothing |
| `POST /api/jobs/<id>/clone` | yes | new | source settings re-validated and re-prepared; the mapping candidate and molecule id are the source's, and the store is read as it is now |
| `POST /retry/<id>` (failed only) | yes | new | source settings, mapping and molecule snapshots, re-prepared against today's stores; a molecule snapshot the store no longer matches is refused |
| `POST /api/jobs/<id>/resume` | **no** | same | current files on disk; the completed-stage prefix; prior manifest archived under `resume_history/NNNN/` |
| fork resume (`resume_of`, shared CG) | yes | new | source record verified, generated data copied, upstream stage outputs verified and recorded `reused` |

Clone and retry create a new job and therefore a new `inputs.json`: the inputs are named again from the stores
as they are now, which is what makes them a new record rather than a copy of the old one.

Resume in place does **not** restore from `inputs/`: it executes the current files in the selected and
downstream stage directories, re-verifying the input record before each stage (a shared input changed since
prepare refuses resume), marks prior analyses `superseded`, and records `resume_count`, `resume_from`,
`resume_in_place`. The journal (`resume_journal.json`) lets an interrupted preparation be finished or rolled
back. A fork resume (`workflow.prepare_resume`) verifies the source manifest's record, copies `inputs/` into
the new run and into its `stages/` (leaving `inputs.json` out of the stage tree), and marks the upstream stages
`reused` after verifying their declared outputs.

---

## 10. Things worth knowing before changing this path

* **The route only forwards advertised settings.** A setting the adapter does not publish is silently dropped
  before the job exists. This is a known failure mode (the pdc placement mode was dropped once) — adding a
  panel control means adding it to `SETTINGS_SPECS`/`CHOICE_SPECS` as well.
* **`prepare` is the run type's, not the coordinator's.** The coordinator no longer filters settings or
  assembles stage arguments; do not reintroduce that here.
* **A run is data plus a record, not a copy.** Do not write a published, stored or run output into a run: name
  it in `inputs/inputs.json`. Do not stamp a value into a generated script: the script is a repository file and
  reads its numbers from the environment (`RUN_SETTING_*`) or its `inputs/<stage>.json` record.
* **A topology names its dependencies by a path relative to the stage it is read in.** GROMACS resolves `#include`
  from the working directory, so `system.top` carries `../../../../martini3/…`, `../../inputs/detergent_CG.itp` and
  `../02_system/cg/…` — valid from every `stages/NN_*` sibling, which is why the copy a leg carries forward still
  resolves. Nothing may copy a topology somewhere else and run `grompp` in it.
* **There is one Martini 3 set, installed, not vendored per reader.** `references/` is upstream; every consumer
  (adapters, catalogue, bead types) reads `workspace/dashboard/martini3/`, whose digests are checked against the
  record before use and refused when they disagree. `resources/templates/` holds no Martini library.
* **The AA-CG stage plan has two shapes.** A mapping with a current parameterization consumes it
  (`use_parameterization.sh`, no in-run fit, `bonded.consumes_parameterization = true`); otherwise the run fits
  (`fit_topology.sh`). The manifest records which happened, and later readers resolve the plan from the
  manifest, not from the mapping.
* **A skip is an answer, in two forms.** A stage `prepare` already knows will not run gets no directory and is
  recorded from `skipped_stages` with its reason; a stage that runs and finds nothing to do exits 4 and writes
  `skip.json`. Do not turn either into a failure, and do not give a prepare-time skip a directory to explain.
* **The stage log path is derived, not stored free-form.** `manifest.stage_log_path` anchors a recorded
  absolute path back onto the run, so a moved workspace still opens its own logs.
* **A changed `.sh` or helper refuses a re-run.** `stage_scripts` and `python_modules` are digests of the
  checkout the run was prepared against; editing one and resuming the run is refused by name. Prepare a new
  run instead.
* **The generated AA `run.sh` is the one shell file inside a run.** It is synthesized from the run's settings,
  not copied from `dashboard/execution/scripts/`; every other run type executes the repository script in place.


---

## 11. Worked example: the 100 ns micelle-only acceptance run

`b920391735dd` was queued on 2026-10-27 to prove the path end to end: a protein-free DDM micelle, the DDM
mapping's fitted revision, `remove_out_of_micelle=false`, `backmap=false`.

- `create_job` recorded it as `pdc`; the adapter's `prepare` wrote `layout_version: 3`, a ten-entry
  `stage_plan`, 19 `inputs` entries (1 published repo file, 3 installed Martini 3 files, 1 saved mapping, 14
  generated files), all ten `stage_scripts`, and `skipped_stages` for Protein preparation, Micelle assessment, CG
  extension MD, Final assessment and Back-mapping.
- Only five directories exist under `stages/`: `02_system`, `03_minimisation`, `04_nvt`, `05_npt`,
  `06_assessment`. The run holds no `.py` and no `.sh`.
- `inputs/assessment.mdp` is `pdc-assessment-v1` with `nsteps = 5,000,000` at `dt = 0.02` (99 ns assessment plus
  the 1 ns extension, folded because removal is off).
- The run completed in about 17 minutes of wall clock on the GPU; `stages/06_assessment/prod/whole.xtc` holds
  50,001 frames ending at 100,000 ps, and its `snapshots` analysis published. The run view shows the four ruled-out
  stages as skipped, with their reasons, and nothing missing.
