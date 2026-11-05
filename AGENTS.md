# Project guidance for coding agents

Rules and facts for working here. State and open items: `docs/HANDOFF.md`; layout, persistence and procedures:
`PROJECT_GUIDE.md`; scoring: `DDM_CALIBRATION.md`.

## What belongs in this file
A line belongs here only if an agent could damage the project by not knowing it before opening another file: a rule, an
invariant, a decision not to re-litigate, or a command. How a subsystem works goes in `PROJECT_GUIDE.md`, incidents in
`HANDOFF.md`, scoring science in `DDM_CALIBRATION.md`.
`packages/core/tests/unit/test_agents_contract.py` enforces the budget and headings, and that every invariant names code
or a pointer.

## Goal
One local Python service orchestrating resumable GROMACS/Martini jobs -- AA to CG, protein-detergent, osmotic series --
behind a Flask dashboard over persisted manifests and logs. Reproducible; outputs immutable; analyses derived from them.

## Where things are
- AA to CG: `execution/adapters/aa.py` then `cg.py` (the only CG pipeline), then Fast_Forward, then GROMACS; any
  molecule with a compatible AA topology runs it, and `molecules/DDM` is the reference example. A `kind: "cg"` molecule
  (`molecules/aa.py`) is a pdc detergent only: never an `aa_only`/`aa_cg` source, never a bead-editor entry.
- Protein-detergent: `pdc.py` owns the ten stages, each running a repository `pdc_*.sh`; placement science is
  `micelle/`. Osmotic: `osmotic.py` with `osmotic_box.py`/`osmotic_mdp.py`.
- Tools resolve through `config/tools.json` and `execution/tools.py`: a declared path is verified or resolves to
  nothing, never a substitute; every manifest records the resolved version and path.
- `packages/` holds three distributions: `core` is the engine (`detergent-core`, import `dashboard`); `validation` and
  `pdc` are features registering through the `detergent_md.features` entry point, and the engine never imports one.
  Code map, routes and ownership: `PROJECT_GUIDE.md` *Source ownership*.
- Tests live in `packages/<name>/tests/{unit,integration,browser}`; `tests/harness/` holds the shared fixtures,
  plugins and the area table.

## Run contract
- Four run types: `aa_only`, `aa_cg`, `pdc`, `osmotic`; each adapter's `STAGES` is the order, `pdc`'s ten are
  `01_prepare` … `10_backmap`, and `pdc.LEGS`/`stage_by_name` name a leg rather than a caller counting.
- A prepared run reads shared inputs in place: `inputs/inputs.json` names each by role/label/kind/root/path/sha256 and
  `input_snapshot_sha256` digests it; `stage_scripts`/`python_modules` pin repository code and `mdp_profiles` names each
  MDP's reviewed profile, so no `.py` or copied `.sh` lives in a run.
- Every stage records start/end, command, environment, inputs, outputs, exit code and log path.
- A stage with nothing to do records `skipped` (exit 4) with `skip.json`; a stage `prepare` rules out gets no directory
  and is recorded `skipped` from `skipped_stages`. Legacy trees are migrated by `cli/migrate_run_layout.py`.
- Runs end `complete`, `failed`, `cancelled` or `blocked`.

## Invariants
- One content identity is one saved mapping: `save_draft` refuses a second (`DuplicateMapping`; the route answers 409
  with `existing`), and a rename is an in-place save, so it is not a duplicate.
- A parameterization belongs to the mapping: revisions keyed by content hash, one current (`make current`), and an
  `owners` claim list; the panel deletes it (`DELETE /api/bonded-parameterizations/<content_hash>`), the editor the
  mapping; no flat store.
- A mapping's identity must not depend on how its numbers were spelled: only `candidate_identity` normalises
  (`numbers_as_values`); the `canonical_sha256` digests are byte digests on purpose.
- New Run pins the AA source to the run a mapping's current revision names (`aa_reference.run_id`), and a null
  readiness answer is not an unlock.
- An AA-CG run always fits its own bonded terms (`cg.AA_CG_PROFILE`) unless its mapping carries a current revision,
  which it then consumes and records that it did.
- `ff_inter` writes `funct 9`: one `phi C mult` triplet per line, eight lines per dihedral. A reader that assumes
  `funct 1` refuses the topology; one that reads each line as a dihedral measures the same torsion eight times.
- `ff_assess` scores against histograms it does not make. A revision recording none still runs, and its assessment stage
  records `skipped` with that reason rather than scoring 0.00.
- `coordinator.automatic_analyses` is the one resolver for a run type's default analyses; `kinds.for_every_run()`
  is empty because the snapshot analysis is retired, and an `aa_cg` run still owes `dihedral-fit`/`bonded-cross-check`.
- A pdc belt is a torus when the protein states a membrane (`radius_nm` is then a floor under the measured
  centre-line) and a sphere when it does not; on either shape a detergent's body must clear the protein, not only its
  head site.
- A run's progress counts mdrun legs from the stage log and its ETA is GROMACS' own text; `percent` is `null` until a
  leg prints.
- Simulation admission is per GPU: `Coordinator.admit_device` compares the run's own `mdrun_gpu`, and
  `max_concurrent_runs` is a per-device ceiling, so runs on different GPUs start together.
- A run holds one frame series at `analyses/frame-series/` (`Kind.stable_directory`): each build replaces the pair
  through `files.atomic_copy`, `frames.json` last, and a failed build leaves the previous pair. The PDB carries one
  `CONECT` block after the last `ENDMDL` (`structures.series_pdb`), measured to bind every model in the viewer.
- `GET /api/jobs/<id>/structure?path=` writes the run's own bonds and constraints as CONECT and refuses a `.pdb`; a file
  carrying CONECT is never distance-guessed.
- A revision's terms name beads by their export name (`B01` is the first bead, virtual sites included), so anything
  that needs a position translates them first.
- The bonded scene draws one style per term kind (`bonded-plot.TERM_STYLES`), a fit job is polled by `?job_id=` never
  by the mapping's hash, and the panels draw the selected candidate's own molecule (`bonded.js:resolveStructure`).
- Carbohydrate validation is an immutable analysis on a completed source run: a `setup` analysis proves execution,
  never validity, and checked-in targets are citation metadata until molecule-specific measurements exist.
- `mdrun_gpu`, `mdrun_ntomp`, `mdrun_ranks` and `mdrun_cpt` are the run's, not its reference's: `cg.run_settings` keeps
  them and `aa.mdrun_command_flags` is the only builder, so a stage script states neither a device nor an offload
  scheme. Each stage records `resource_usage.gpu`; the index is the CUDA ordinal, with the NVML row and PCI bus id
  beside it. A host with no device (`devices.present`) offers no GPU setting and writes no GPU flag.
- A run setting is advertised in `SETTING_SPECS` or `CHOICE_SPECS` in the same edit: `web/routes/runs.py` keeps only
  advertised keys, so an unadvertised setting is dropped without a word and the run silently uses the default.
- Provenance is the `inputs.json` record and `stage_scripts` digests, not a copy: the one Martini 3 set lives at
  `workspace/dashboard/martini3` (`dashboard.martini3`), every run reads it in place, and `references/` is upstream.

## Engineering rules
- Read `docs/HANDOFF.md` before the first edit and leave it current: the next session starts there, not from your
  transcript.
- When a request is ambiguous, ask one round of numbered questions: the user decides the science; a UI change shows an
  HTML draft and a cross-layer change a plan in `docs/plans/` before code.
- Trace inputs, state transitions, outputs and failure handling before editing; fix the cause, measure before and
  after, and report each check's command and result. Reproduce a suspected pre-existing failure at HEAD first.
- Test against fixtures, never the developer's workspace, and build the record through the route the UI uses. Shared
  fixtures hold the *construction*, never the meaning -- a file keeps its arguments because copies drift.
- Test command construction, stage transitions, failure recovery and analysis parsing without long simulations. A
  feature that reads a *production* trajectory gets one timed live run before commit: fixture trajectories hide both
  its cost and its filesystem side effects.
- When work is parallel, lanes own disjoint files, one integrator runs the tiers and commits, and shared tables
  (`tests/harness/areas.py`) and a form's markup belong to the integrator. Before the gate the integrator reads
  `git status` in full: a path nobody named is restored or explained.
- Keep force-field and tool versions and exact commands in run metadata; never silently overwrite a run.
- Validate uploaded structures, detergent definitions, resource limits and paths at trust boundaries.
- Stages are resumable, idempotent, cancellable and safe to run concurrently.
- Simulation outputs are immutable; analyses reference their source trajectory. A reader that makes a tool cache beside
  its input (MDAnalysis' `*_offsets.npz`) opens the file through a symlink in a temporary directory, never in the run
  tree.
- GROMACS + Martini by default; anything else only with measured need.

## Do not
- Kill a process by an unfiltered listener: DSH is 3080, the dashboard 5000.
- Push; the user pushes. Commit only after the relevant checks pass; `scripts/gate_commit.sh` is the gate.
- Clean or reset paths you are not changing: name the paths, and leave `git clean`, `git reset --hard` and a broad
  `git checkout` alone.
- Exercise a destructive control against the live workspace. Point it at a fixture, or inspect what the client sends.
- Delete simulation data, or rebuild a file to stand in for a lost record.
- Signal a PID from a previous coordinator session; only the current worker owns its subprocess groups.
- Treat a notebook as production orchestration, or a completed diagnostic as scientific validation.
- Assume a detergent has Martini parameters because it is available.

## Standing decisions
- **The two fitting engines keep separate analyses** (2026-10-20, the user's decision): `ff_assess` for Fast-Forward,
  its own graphs for BARTENDER; unifying them is postponed, not planned, and a bartender model runs stage 5 `skipped`,
  never the FF baseline.
- CG production 20 fs, CG equilibration 5 fs, AA half 2 fs; each MDP is its reviewed `mdp.PROFILES` entry's own.
- This GROMACS is an MPI-only build: `-ntomp` is the knob, `-ntmpi` is invalid. In use:
  `/usr/local/gromacs/2026.3/bin/gmx`.
- Internal consistency is the primary evidence; the reference's own numbers are context, not a pass mark.
- A mapping states its own ring scale and the guard is a range; ring scale is closed as the cause of the DDM failure,
  and fitted linkage values are not a diagnosis -- spend no further arm on either.
- The published M3-Lipid set is tracked at `references/M3-Lipid-Parameters` (Apache-2.0) and installed per workspace;
  update it deliberately, never per run. GLYCAM06 is dropped.
- The scheduled cron drivers and the mapping-refinement panel are cancelled; do not rebuild either.
- `-improperIncrement 10` goes to every BARTENDER fit, so impropers fitted since are not comparable with earlier ones.
- Phase 4 (sucrose and maltose experimental sources) is deferred, not abandoned.
- GitNexus graph checks are not used here (removed 2026-11-03); find callers by search and pin them with tests.

## Verify
```
.venv/bin/python -m pytest -m 'not browser and not slow' -q      # fast tier; -m core|validation|pdc, or packages/<m>/tests, for one module
.venv/bin/python -m pytest -m browser -q -n 16 --dist worksteal   # browser tier
.venv/bin/python -m pytest -m slow -q -n 0                       # slow tier, serial
.venv/bin/ruff check packages tests conftest.py                 # F, E9, I must exit 0
scripts/gate_commit.sh <message-file> <paths...>                # fast tier + ruff over named paths
.venv/bin/python scripts/mutation_check.py                       # 11 mutants: 10 caught, 1 survived; run after committing
```
Eleven areas in `tests/harness/areas.py` cover the suite (`test_test_areas.py` fails on an unnamed module): pdc,
runs, bonded, analysis, infra, osmotic, mapping, carbohydrate, web, molecules, aa. Compose an area with a tier, e.g.
`-m 'pdc and not browser and not slow'`; counts are in `pytest.ini`. Private `MPLCONFIGDIR`; lint your own paths; the
mutation script refuses a file with uncommitted changes, so it runs on the committed tree.
