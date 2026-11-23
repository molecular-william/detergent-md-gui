# Project guidance for coding agents

Rules and facts for working here. State and open items: `docs/HANDOFF.md`; layout, persistence and procedures: `PROJECT_GUIDE.md`; scoring: `DDM_CALIBRATION.md`.

## What belongs in this file
A line belongs here only if an agent could damage the project by not knowing it before opening another file: a rule, an
invariant, a decision not to re-litigate, or a command. How a subsystem works goes in `PROJECT_GUIDE.md`, incidents in
`HANDOFF.md`, scoring in `DDM_CALIBRATION.md`; `test_agents_contract.py` enforces the budget, headings and code-or-pointer invariants.

## Goal
One local Python service orchestrating resumable GROMACS/Martini jobs -- AA to CG, protein-detergent, osmotic series --
behind a Flask dashboard over persisted manifests and logs. Reproducible; outputs immutable; analyses derived from them.

## Where things are
- Runs: `aa.py` for an AA run; `cg_run.py` dispatches a CG run's parameterization to `cg.py` (mapping revision),
  the sugar adapter (published reference) or `composition.py` (derived). A `kind: "cg"` molecule is a pdc detergent
  only, never an AA source or bead-editor entry; a composition is a CG model with a molecule name, not a folder.
- Protein-detergent: `pdc.py` owns the ten stages, each running a repository `pdc_*.sh`; placement is
  `pdc_placement.py` (belt/cylinder) over `micelle/` (lattice and overlap gates). Osmotic: `osmotic.py` with
  `osmotic_box.py`/`osmotic_mdp.py`.
- Tools resolve through `config/tools.json` and `execution/tools.py`: a declared path is verified or resolves to
  nothing, never a substitute; every manifest records the resolved version and path.
- `packages/` holds three distributions: `core` is the engine (`detergent-core`, import `dashboard`); `validation` and
  `pdc` are features registering through the `detergent_md.features` entry point, and the engine never imports one.
  Code map, routes and ownership: `PROJECT_GUIDE.md` *Source ownership*.
- Tests live in `packages/<name>/tests/{unit,integration,browser}`; `tests/harness/` holds the shared fixtures,
  plugins and the area table.
- GitNexus is gone; do not reinstall it. graphify (`.agents/skills/graphify`, workspace-local) builds the gitignored
  `graphify-out/` through `.venv/bin/graphify`; navigation only, never a check -- use `query`/`path`/`explain`, and
  find callers by search and pin them with tests.

## Run contract
- Run types: `aa_only`, `cg`, `pdc`, `osmotic`; a `cg` run's `parameterization.kind` (revision, reference, composition)
  picks its adapter and `STAGES`; `pdc`'s ten directories are `01_prepare` … `10_backmap` in `pdc.STAGES`/`stage_by_name`,
  and `pdc.LEGS` names only the three equilibration legs (minimisation, NVT, NPT).
- A prepared run reads shared inputs in place from `inputs/inputs.json` (layout 4); `stage_scripts`/`python_modules`
  name the repository code with a version a not-yet-run stage re-checks, and `mdp_profiles` each MDP's profile, so no
  `.py` or copied `.sh` lives in a run. Detail: `PROJECT_GUIDE.md` *Run storage and lifecycle*.
- Every stage records start/end, command, environment, inputs, outputs, exit code and log path.
- A stage with nothing to do records `skipped` (exit 4) with `skip.json`; a stage `prepare` rules out gets no directory
  and is recorded `skipped` from `skipped_stages`.
- Migrations (`cli/migrate_run_layout.py`, `migrate_run_types.py`, `migrate_named_analyses.py`, `migrate_named_records.py`, `migrate_molecule_versions.py`, `migrate_mapping_identities.py`, `migrate_reference_pins.py`, `repair_reference_edition.py`) rewrite records once, verify their output, keep a `--rollback` ledger, and are never re-run by hand on already-migrated data.
- A run's status ends `completed`, `failed`, `cancelled` or `blocked`; `complete` is the last stage label.

## Invariants
- One name is one saved mapping (`records/<slug>.json`): `save_draft` refuses a name another model holds (409 with
  `existing`), a rename is an in-place save that moves the record and its revisions, and only the name addresses it
  (`legacy_hash` is a provenance stamp, not a lookup).
- A parameterization is addressed by that name: `<slug>.revisions/<n>`, highest current, deleted by name; only
  `Make current` changes what a run consumes (the shown revision is display-only).
- A mapping's identity must not depend on how its numbers were spelled: only `candidate_identity` normalises
  (`numbers_as_values`); the `canonical_sha256` digests are byte digests on purpose.
- A `cg` revision run consumes the revision it names (default current) and pins its AA source to that revision's
  `aa_reference.run_id`; a null readiness answer is not an unlock.
- A revision records the mapped starting coordinates it built; a `cg` run defaults to them and refuses `stored` with
  a reason when the revision has none, while `remap` re-reads the AA reference (`stage_coordinates.sh`).
- `ff_inter` writes `funct 9`: one `phi C mult` triplet per line, eight lines per dihedral. A reader that assumes
  `funct 1` refuses the topology; one that reads each line as a dihedral measures one torsion eight times, and a writer must collapse the block's lines (`refine`).
- `ff_assess` scores against histograms it does not make. A revision recording none still runs, and its assessment stage
  records `skipped` with that reason rather than scoring 0.00.
- `coordinator.automatic_analyses` is the one resolver for a run type's default analyses: `kinds.default_for` is the
  only list, and a `cg` revision run owes exactly that list's kinds; one with nothing to do records `skipped`, never a
  fabricated pass.
- A pdc belt is a **cylinder** about the membrane normal: its surface is measured locally per site
  (`BELT_LOCAL_ANGLE_DEG` 10 deg, axial `belt_axial_window_nm`, plus `belt_gap_nm`); `min_body_gap_nm` gates body
  against body, and a rejected site tries bounded offsets before being left empty. No membrane keeps a sphere,
  where `radius_nm` is radius and floor (`pdc_placement._belt_cylinder`; `PROJECT_GUIDE.md` *Shapes, stages and series*).
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
- A run setting is advertised by its run type's adapter (`settings_specs()`/`choice_specs()`), which publishes the
  dialect's `SETTING_SPECS`/`CHOICE_SPECS`: `web/routes/runs.py` keeps only advertised keys, so an unadvertised setting
  is dropped without a word and the run silently uses the default.
- Provenance is the `inputs.json` record and `stage_scripts` names/versions (plus `provenance.json`, which gates nothing), not a copy: the one Martini 3 set lives at
  `workspace/dashboard/martini3/<version>/` (`dashboard.martini3`, witnessed by `martini3.json`), every run reads it in place, and `references/` is upstream; a molecule folder is `molecules/<id>/<version>/`; a mapping's molecule binding is `{molecule_id, version}`, and a shared AA reference is pinned by its edition.

## Engineering rules
- Read `docs/HANDOFF.md` before the first edit and leave it current: the next session starts there, not from your
  transcript.
- A Python change is live only after the dashboard restarts; `static/` is read per request. Check active jobs and
  worker leases first, then restart the unit -- a live check can compare a new page against an old engine.
- When a request is ambiguous, ask one round of numbered questions: the user decides the science; a UI change shows an
  HTML draft and a cross-layer change a plan in `docs/plans/` before code.
- `docs/plans/*` is gitignored but plan files are tracked: add a new one with `git add -f docs/plans/<file>.md`, or it
  silently stays untracked while `HANDOFF.md` cites it.
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
- An analysis attempt stages each source as a symlink; its producer publishes new files and never edits a staged
  input. `files.stat_snapshot` detects a write through the link; it does not prevent it (`PROJECT_GUIDE.md` *Run accounting*).
- GROMACS + Martini by default; anything else only with measured need.

## Do not
- Read files with shell commands (`cat`, `head`, `sed`): use read for files, glob for paths, grep for contents.
- One coordinator per workspace. Never kill by an unfiltered listener: DSH is 3080, the dashboard 5000.
- Push; the user pushes. Commit only after the relevant checks pass; `scripts/gate_commit.sh` is the gate.
- Clean or reset paths you are not changing: name the paths, and leave `git clean`, `git reset --hard` and a broad `git checkout` alone.
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
- Analyses batch with `np.vecdot`, so `packages/core/pyproject.toml` declares `numpy>=2`; another summation order moves
  a fitted angle across the +-180 branch cut.
- This GROMACS is an MPI-only build: `-ntomp` is the knob, `-ntmpi` is invalid. In use:
  `/usr/local/gromacs/2026.3/bin/gmx`.
- Internal consistency is the primary evidence; the reference's own numbers are context, not a pass mark.
- A mapping states its own ring scale and the guard is a range; ring scale is closed as the cause of the DDM failure,
  and fitted linkage values are not a diagnosis -- spend no further arm on either.
- The published M3-Lipid set is tracked at `references/M3-Lipid-Parameters` (Apache-2.0) and installed per workspace;
  update it deliberately, never per run. GLYCAM06 is dropped.
- The scheduled cron drivers and the mapping-refinement panel are cancelled; do not rebuild either.
- Insane 1.2.0 is the solvent placer for every CG/pdc run (`dashboard.execution.scripts.insane_solvate`, declared `insane` in `config/tools.json`); `gmx solvate` is not used. It replaced the replicated water box after measured water–head contacts fell inside the Martini bead radii.
- `-improperIncrement 10` goes to every BARTENDER fit, so impropers fitted since are not comparable with earlier ones.
- Phase 4 (sucrose and maltose experimental sources) is deferred, not abandoned.

## Verify
```
.venv/bin/python -m pytest -m 'not browser and not slow' -q      # fast tier; -m core|validation|pdc, or packages/<m>/tests, for one module
.venv/bin/python -m pytest -m browser -q -n 16 --dist worksteal   # browser tier
.venv/bin/python -m pytest -m slow -q -n 0                       # slow tier, serial
.venv/bin/ruff check packages tests conftest.py                 # F, E9, I must exit 0
scripts/gate_commit.sh <message-file> <paths...>                # fast tier + ruff over named paths
.venv/bin/python scripts/mutation_check.py                       # 11 mutants: 9 caught, 1 stale anchor, 1 control survived; run after committing
```
Eleven areas in `tests/harness/areas.py` cover the suite (`test_test_areas.py` fails on an unnamed module); compose an
area with a tier, e.g. `-m 'pdc and not browser and not slow'`. Counts drift: quote a fresh `pytest --collect-only -q`.
Private `MPLCONFIGDIR`; lint your own paths; the mutation script refuses a file with uncommitted changes, so it runs on
the committed tree.
