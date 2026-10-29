# Project guidance for coding agents

Rules and facts for working here. State and open items are in `HANDOFF.md`; repo layout, persistence, migration and
testing in `PROJECT_GUIDE.md`; scoring in `DDM_CALIBRATION.md`. Read `HANDOFF.md` before the DDM CG chain or coordinator.

## What belongs in this file
A line earns its place only if an agent could damage the project by not knowing it before opening any other file: a
rule, an invariant, a decision not to re-litigate, or a command. How a subsystem works belongs in `PROJECT_GUIDE.md`,
state and incidents in `HANDOFF.md`, scoring science in `DDM_CALIBRATION.md`.
`tests/dashboard/unit/test_agents_contract.py` enforces the budget and headings, and that every invariant names code.

## Goal
One local Python service orchestrating resumable GROMACS/Martini jobs -- AA to CG, protein-detergent, osmotic series --
with a Flask dashboard over persisted manifests and logs. Reproducible; outputs immutable; analyses derived from them.

## Where things are
- AA to CG: `execution/adapters/aa.py` then `cg.py` (the only CG stage pipeline), then Fast_Forward, then GROMACS; any
  molecule with a compatible AA topology runs it, and packaged `molecules/DDM` is the reference example.
- Protein-detergent: `pdc.py` owns the ten numbered stages, each running a repository `pdc_*.sh`; the placement science
  is `micelle/`. Osmotic series: `osmotic.py` with `osmotic_box.py`/`osmotic_mdp.py`.
- Tools resolve through `config/tools.json` and `execution/tools.py`: a declared path is verified or resolves to
  nothing, never to a substitute, and every manifest records the resolved version and path.
- `resources/` and `packages/` are the maintained trees: `packages/core` is the engine (`detergent-core`, import `dashboard`), `packages/validation`/`packages/pdc` are features (`detergent_validation`/`detergent_pdc`) that register through `dashboard/features.py`'s `detergent_md.features`
  entry point; the engine never imports one. Code map, routes and ownership: `PROJECT_GUIDE.md` *Source ownership*.

## Run contract
- Four run types: `aa_only`, `aa_cg`, `pdc`, `osmotic`; each adapter's `STAGES` is the order, `pdc`'s ten are
  `01_prepare` … `10_backmap`, and `pdc.LEGS`/`stage_by_name` name a leg or stage rather than a caller counting.
- A prepared run reads shared inputs in place: `inputs/inputs.json` names each by role/label/kind/root/path/sha256,
  `input_snapshot_sha256` digests that record, and every stage verifies it. No `.py` or copied `.sh` lives in a run:
  `stage_scripts`/`python_modules` pin repository code, and `mdp_profiles` names each MDP's reviewed profile.
- Every stage records start/end, command, environment, inputs, outputs, exit code and log path.
- A stage with nothing to do records `skipped` (exit 4) with `skip.json`; a stage `prepare` rules out gets no directory
  and is recorded `skipped` from `skipped_stages`. A legacy tree is migrated by `cli/migrate_run_layout.py`.
- Runs end `complete`, `failed`, `cancelled` or `blocked`.
- Stage lists and settings: `PROJECT_GUIDE.md` (*AA-only and shared-reference protocol*, *Dashboard workspace*).

## Invariants
- One content identity is one saved mapping: `save_draft` refuses a second (`DuplicateMapping`; the route answers 409
  with `existing`), and a rename is an in-place save, so it is not a duplicate.
- An AA-CG run always fits its own bonded terms (`cg.AA_CG_PROFILE`) unless its mapping carries a current revision,
  which it then consumes and records that it did.
- A parameterization belongs to the mapping: revisions keyed by content hash, one current (`make current`), and a claim
  list (`owners`) that decides when the revisions go. The panel deletes the parameterization
  (`DELETE /api/bonded-parameterizations/<content_hash>`); the editor deletes the mapping. No flat bonded-state store.
- New Run pins the AA source to the run a mapping's current revision names (`aa_reference.run_id`), and a null
  readiness answer is not an unlock.
- A mapping's identity must not depend on how its numbers were spelled: only `candidate_identity` normalises
  (`numbers_as_values`); the `canonical_sha256` digests are byte digests on purpose.
- `ff_inter` writes `funct 9`: one `phi C mult` triplet per line, eight lines per dihedral. A reader that assumes
  `funct 1` refuses the topology; one that reads each line as a dihedral measures the same torsion eight times.
- `ff_assess` scores against histograms it does not make. A revision recording none still runs, and its assessment stage
  records `skipped` with that reason rather than scoring 0.00.
- A pdc belt is a torus when the protein states a membrane (`radius_nm` is then a floor under the measured
  centre-line) and a sphere when it does not; on either shape a detergent's body must clear the protein, not only its
  head site.
- `coordinator.automatic_analyses` is the one resolver for a run type's default analyses; `kinds.for_every_run()`
  is empty because the snapshot analysis is retired, and an `aa_cg` run still owes `dihedral-fit`/`bonded-cross-check`.
- A run's progress counts mdrun legs from the stage log and its ETA is GROMACS' own text; `percent` is `null` until a
  leg prints.
- `GET /api/jobs/<id>/structure?path=` writes the run's own bonds and constraints as CONECT and refuses a `.pdb`; a file
  carrying CONECT is never distance-guessed.
- A revision's terms name beads by their export name (`B01` is the first bead, virtual sites included), so anything
  that needs a position translates them first.
- The bonded scene draws one style per term kind (`bonded-plot.TERM_STYLES`), a fit job is polled by `?job_id=` never
  by the mapping's hash, and the panels draw the selected candidate's own molecule (`bonded.js:resolveStructure`).
- Carbohydrate validation is an immutable analysis on a completed source run: a `setup` analysis proves execution,
  never validity, and checked-in targets are citation metadata until molecule-specific measurements exist.
- `mdrun_gpu`, `mdrun_ntomp` and `mdrun_ranks` are the run's, not its reference's: `cg.run_settings` keeps them and
  `aa.mdrun_command_flags` is the only builder; a stage script states neither a device nor an offload scheme. A run
  records `environment.devices` and each stage `resource_usage.gpu`; the index is the CUDA ordinal, with the NVML
  row and PCI bus id beside it. An index the host lacks is refused at prepare, a host reporting none is not.
- Provenance is the `inputs.json` record and `stage_scripts` digests, not a copy: the one Martini 3 set lives at
  `workspace/dashboard/martini3` (`dashboard.martini3`), every run reads it in place, and `references/` is upstream.

## Engineering rules
- Test against fixtures, never the developer's workspace; build the record through the route the UI uses.
- Shared test fixtures hold the *construction*, never the meaning. A file keeps its arguments because copies drift.
- Trace inputs, state transitions, outputs and failure handling before editing.
- Keep force-field and tool versions and exact commands in run metadata; never silently overwrite a run.
- Validate uploaded structures, detergent definitions, resource limits and paths at trust boundaries.
- Stages are resumable, idempotent, cancellable and safe to run concurrently.
- Simulation outputs are immutable; analyses reference their source trajectory.
- GROMACS + Martini by default; anything else only with measured need.
- Test command construction, stage transitions, failure recovery and analysis parsing without long simulations.

## Do not
- Exercise a destructive control against the live workspace. Point it at a fixture, or inspect what the client sends.
- Delete simulation data, or rebuild a file to stand in for a lost record.
- Signal a PID from a previous coordinator session; only the current worker owns its subprocess groups.
- Treat a notebook as production orchestration, or a completed diagnostic as scientific validation.
- Assume a detergent has Martini parameters because it is available.

## Standing decisions
- **The two fitting engines keep separate analyses** (2026-10-20, the user's decision): `ff_assess` for Fast-Forward,
  its own graphs for BARTENDER, because its analysis is its own. Unifying them is postponed, not planned, and a
  bartender model runs with stage 5 `skipped` and its reason -- do not route it through the Fast-Forward baseline.
- CG production 20 fs, CG equilibration 5 fs, AA half 2 fs; each MDP is its reviewed `mdp.PROFILES` entry's own.
- This GROMACS is an MPI-only build: `-ntomp` is the knob, `-ntmpi` is invalid. In use:
  `/usr/local/gromacs/2026.3/bin/gmx`.
- Internal consistency is the primary evidence; the reference's own numbers are context, not a pass mark.
- A mapping states its own ring scale and the guard is a range. Ring scale is closed against as the cause of the DDM
  failure, and fitted linkage values are not a diagnosis -- spend no further arm on either.
- The published M3-Lipid set is the standard source, recorded per run, and stays untracked. GLYCAM06 is dropped.
- The scheduled cron drivers and the mapping-refinement panel are cancelled; do not rebuild either.
- `-improperIncrement 10` goes to every BARTENDER fit, so impropers fitted since are not comparable with earlier ones.
- Phase 4 (sucrose and maltose experimental sources) is deferred, not abandoned.

## Verify
```
.venv/bin/python -m pytest -m 'not browser and not slow' -q      # fast tier; -m core|validation|pdc for one module
.venv/bin/python -m pytest -m browser -q -n 16 --dist worksteal   # browser tier
.venv/bin/python -m pytest -m slow -q -n 0                       # slow tier, serial
.venv/bin/ruff check packages tests                             # F, E9, I must exit 0
scripts/gate_commit.sh <message-file> <paths...>                           # fast tier + ruff over named paths
.venv/bin/python scripts/mutation_check.py                       # 11 mutants: 10 caught, 1 survived
```
Eleven areas in `tests/dashboard/areas.py` cover the suite (`test_test_areas.py` fails on an unnamed module): pdc,
runs, bonded, analysis, infra, osmotic, mapping, carbohydrate, web, molecules, aa. Compose an area with a tier, e.g.
`-m 'pdc and not browser and not slow'`; counts are in `pytest.ini`. Private `MPLCONFIGDIR`; lint your own paths.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **detergent_md** (1775 symbols, 4945 relationships, 139 execution flows).

> Index stale? Run `node .gitnexus/run.cjs analyze --index-only` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? Bootstrap with `npx`, `bunx`, or `pnpm dlx` — e.g. `bunx gitnexus@latest analyze` (npm 11 npx crash; #1939).

## Always Do

- **MUST run impact before editing.** Use `impact({target: "symbolName", direction: "upstream"})` or `node .gitnexus/run.cjs impact "symbolName" --direction upstream --repo .`; report callers, processes, and risk. Never substitute grep for graph analysis.
- **MUST analyze graph changes before committing.** Use `detect_changes({scope: "all"})` (MCP) or `node .gitnexus/run.cjs detect-changes --scope all --repo .` (CLI fallback). `partial: true` or `truncated: true` is not a clean check — a zero means unseen, not unaffected; re-run it. For regression review: `detect_changes({scope: "compare", base_ref: "main"})` or `node .gitnexus/run.cjs detect-changes --scope compare --base-ref "main" --repo .`.
- MUST warn on HIGH/CRITICAL `risk` pre-edit; never use `riskSharedAxes` to waive a HIGH/CRITICAL `risk` warning. Compare File/symbol: MCP File omits axes; Graph-RAG expands File.
- **MUST treat `risk: UNKNOWN` as unresolved, not as low.** An empty caller set is not evidence the symbol is unused — it can also mean the callers are not resolvable by the index (plain-object property access, dynamic dispatch, cross-language calls). `impact` pairs `UNKNOWN` with a `riskNote` saying so. Confirm with a text search before treating the symbol as safe to change or delete; do not proceed on the strength of a zero.
- **MUST use `query({search_query: "concept"})` for concepts/flows, `context({name: "symbolName"})` for a named symbol, or `impact` for blast radius, on read-only callers, dependencies, imports, or execution flow.** Graph first; text search only for empty/`UNKNOWN`/literals.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method before MCP/CLI impact analysis.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis, and never read `UNKNOWN` as an all-clear — it means the walk could not answer, which is the one verdict that requires confirming by other means.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit before MCP/CLI graph change analysis.

## Resources

| Resource | Use for |
| --- | --- |
| `gitnexus://repo/detergent_md/context` | Codebase overview, check index freshness |
| `gitnexus://repo/detergent_md/clusters` | All functional areas |
| `gitnexus://repo/detergent_md/processes` | All execution flows |
| `gitnexus://repo/detergent_md/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
| --- | --- |
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
