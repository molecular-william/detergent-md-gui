# Run lifecycle refactor

**Status: approved, implementing.** Design agreed 2026-10-27; this document is the task list. It supersedes the
layout and provenance sections of `docs/design/2026-10-27-run-initiation-lifecycle.md` once phase 4 lands.

## The outcome

One run model for all four run types, with shared inputs referenced in place and pinned by hash, code reused from
the repository instead of copied into runs, MDPs written from reviewed physics profiles, and PDC stages numbered in
execution order with nothing on disk for a stage that will not run.

Observable acceptance:

1. A prepared run of each type has `stages/`, `inputs/` and `logs/`; `inputs/` holds data only (`inputs.json` plus
   generated data), and the run contains no `.py` and no copied `.sh`.
2. `inputs.json` names every input with `role`, `label`, `kind`, `root`, `path`, `sha256`, and the manifest's
   `input_snapshot_sha256` is the digest of that record.
3. A shared input mutated after prepare refuses the next stage, naming the file; a helper code change refuses a
   re-run for the same reason.
4. PDC stages are `01_prepare … 09_backmap` in execution order; a stage whose setting says it will not run has no
   directory, no script and no `skip.json`, and the manifest records it skipped with its reason.
5. The six phases pass the fast tier; the final tree passes fast, browser and slow tiers and ruff.
6. A micelle-only protein-free PDC run with 100 ns of sampling reaches `complete` on the new pipeline.

Non-goals: no new run types, no UI redesign, no physics change, no deletion of simulation outputs, no multi-user
service, no change to the parameterization or bonded-editor contracts.

## Phase 1 — input model

Reference in place what exists when `prepare` runs; write by value only what `prepare` synthesizes.

- T1.1 `dashboard/execution/run_inputs.py`: entry constructors (published / store / run-output / generated),
  `write(run_dir, entries)`, `digest(entries)`, `resolve(entry)`, `verify(entry)`, and `path(run_dir, role)` for
  stage scripts. Tests in `tests/dashboard/unit/test_run_inputs.py`.
- T1.2 `protocol.write_prepared_manifest` takes the input record, writes `inputs` + `input_snapshot_sha256` and
  `layout_version: 3`; `finish_prepared_run` stops copying `stages/` into `inputs/`. `workflow.run` verifies every
  referenced entry before each stage. Old manifests without `inputs` keep the legacy directory digest.
- T1.3 `aa` adapter: force field and molecule files referenced; generated data (converted `.gro`, context, index,
  patched MDPs, scripts until phase 2) written into `inputs/`.
- T1.4 `cg` adapter: force field, parameterization revision and reference histograms referenced; mapping export,
  topologies, MDPs and SASA radii generated.
- T1.5 `cg_composition`: its four immutable artifacts referenced from their store (or recorded absolutely when they
  live outside the workspace); the screening stubs read the recorded path instead of a copy.
- T1.6 `pdc` and `osmotic` take the input model together with their layout change in phase 4, because both still write
  stage directories at the run root and the record has to be written where the layout is settled.
- T1.7 Readers: `layout` resolves a run's inputs from `inputs.json`, `clone`/fork-resume verify the record instead of
  a directory, run view lists the inputs with label and path.

## Phase 2 — code lives in one place, pinned

- T2.1 `Stage` gains an explicit repository script location; the executor runs it with the stage directory as cwd;
  the manifest records `stage_scripts` with each script's sha256 and the checkout version, and a mismatch refuses.
- T2.2 AA and CG: no `.py`, no `.sh` written into the run. `refine_bonded.py` imports `dashboard.models.bonded`;
  the standalone-copy invariant and its test are deleted.
- T2.3 PDC: no `.py`, no copied `.sh`; `_stamp_interpreter` deleted; run numbers travel in `stage.json`; helpers run
  as `"$PYTHON" -m dashboard.execution.scripts.<name>`.
- T2.4 Update the staging tests to assert the new rule (no code inside a run; each stage names its repository
  script; a changed helper refuses).

## Phase 3 — MDP writer and physics profiles

- T3.1 `dashboard/execution/mdp/`: one reviewed profile per stage (AA, CG, PDC legs, osmotic), a single writer, and
  a parity test that the generated file parses to the same key/value map as today's template for every profile.
- T3.2 Adapters call the writer. Template `.mdp` copies and `update_mdp` patches for run preparation are removed;
  `update_mdp` may remain only where a test fixture needs it.

## Phase 4 — one layout, PDC numbered in execution order

- T4.1 PDC `STAGES`: `01_prepare`, `02_system`, `03_minimisation`, `04_nvt`, `05_npt`, `06_assessment`,
  `07_micelle_assessment`, `08_extension`, `09_final_assessment`, `10_backmap`; one script per stage; human names
  unchanged. (The approved table in the design summary omitted the micelle assessment; the protocol has ten stages,
  one directory each.)
- T4.2 `prepare` writes only stages that will run; the manifest records the skipped ones with their reason.
- T4.3 `workflow.run` records a prepare-time skip without a directory and continues.
- T4.4 `execution_root` is deleted; every reader uses `stages/`; `layout`, `worker`, `analyses` routes and the
  distance-diagnostics tests follow.

## Phase 5 — migration of the 11 existing runs

- T5.1 `dashboard/cli/migrate_run_layout.py` (one run or all, `--apply`, backup first): pack `inputs/` and copied
  helper scripts into `legacy_evidence.tar.zst`, delete the live copies, move PDC stage folders under `stages/`,
  write `legacy_layout.json`, never rewrite a manifest. Fixture tests, including a run whose digest no longer
  verifies.
- T5.2 Apply to the live workspace after a backup; verify every migrated run still opens in the run view and its
  analyses resolve.

## Phase 6 — documents and the acceptance run

- T6.1 Rewrite the lifecycle design record and the PROJECT_GUIDE layout/provenance sections; update AGENTS
  invariants that this changes; mark the reusable-assets plan as superseded where it now agrees.
- T6.2 Fast, browser and slow tiers, ruff.
- T6.3 Launch a micelle-only, protein-free PDC run with 100 ns of sampling (no extension, no back-map) through the
  New Run route; verify stages, manifest inputs, `prod/run.xtc` length, and that no `.py`/`.sh` was written into it.

## Progress

- Phase 1: landed. AA, CG, composition, pdc and osmotic name their existing inputs in `inputs/inputs.json`; only
  generated data is written by value. `workflow.run` re-verifies the record before every stage, and clone/retry write
  a new record from today's stores while in-place resume re-verifies the old one.
- Phase 2: landed for CG, pdc, osmotic and composition — no `.py`, no copied `.sh`; each stage runs the repository
  script recorded in `stage_scripts`, imports the helpers recorded in `python_modules`, and refuses a changed file.
  Exception: `aa_only` still writes its generated `run.sh` (synthesized from the run's settings, not copied) and
  records only `python_modules`.
- Phase 3: landed for AA, CG and pdc — every MDP is rendered from `dashboard/execution/mdp/profiles.py` and recorded
  in `mdp_profiles`, and the parity gate (`test_mdp_writer.py`) compares every profile with the old builder.
  Exception: osmotic's MDPs are still written by `osmotic_mdp.osmotic_mdps`; the reviewed `osmotic-*` profiles exist
  as the parity oracle but no adapter renders them, so osmotic records no `mdp_profiles`.
- Phase 4: landed. PDC writes `stages/01_prepare … 10_backmap`, only for stages that will run, and records the rest in
  `skipped_stages`; osmotic is under `stages/01_simulate`; every reader resolves `stages/` (with the run root kept as
  the legacy fallback), and the distance-diagnostics tests follow.
- Phase 5: applied to the live workspace on 2026-10-27. All 10 existing runs carry `legacy_layout.json` and
  `stages/`; `936b74bd3fa8` was deleted by the user before it was migrated. Archives use `pigz` when installed.
- Phase 6: documents are updated, the three tiers and ruff are green, and the acceptance run completed:
  `b920391735dd`, protein-free, 5,000,000 steps at 20 fs = 100 ns, four stages skipped with no directory,
  `stages/06_assessment/prod/whole.xtc` 0-100 ns, no `.py`/`.sh` in the run, snapshots published.

## Notes from implementation

- GitNexus impact analysis is unavailable in this environment (read-only `$HOME`; pnpm store lock). The substitute is
  grep caller lists plus differential tests; three read-only maps of the prepare writes and layout readers stand in
  for the graph until an index can be rebuilt where `$HOME` is writable.
- `run_inputs` records an `absolute` root for an input outside every configured root (an imported protein, a
  composition artifact in a test workspace), so the record never invents a relative path for it.
- T1.2's "stop copying `stages/` into `inputs/`" did not land as written: `finish_prepared_run` still mirrors the
  filled `stages/` tree into `inputs/`, which is how generated data survives beside the record, and for `aa_only` the
  mirror carries its generated `run.sh`. Only generated data is mirrored; no referenced input and no repository script
  is.
- T2.2's "no `.sh` in an AA run" is the AA generated `run.sh` exception above; all other run types execute the
  repository script in place.
- T4.4's `execution_root` deletion did not land: `environment.execution_root` remains as the legacy-compatible
  `stages/`-or-run-root resolver used by the executor and the resume paths, while the analysis readers use
  `analysis/runs/layout.stage_root`.
- `run_inputs.run_output` is defined but no adapter records through it: the shared AA reference stays a
  `shared_reference` manifest key plus `AA_REFERENCE_DIR`, re-verified from the source run's own record rather than
  duplicated as an input entry.

## Risks

- The 11 existing runs are the reference evidence for earlier conclusions; migration must archive, not destroy.
- Generated absolute paths make a run depend on this checkout and workspace; that is the accepted cost of sharing.
- Physics parity is the gate for phase 3: no profile replaces a template until the key/value comparison passes.
