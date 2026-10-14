# Project guidance for coding agents

Rules and facts for working here. State, measurements and open items live in `docs/HANDOFF.md`; read that before touching the DDM CG chain, the crons or the coordinator.

## Read first
- Repo layout, dashboard, persistence, migration, testing: `docs/PROJECT_GUIDE.md`.
- DDM calibration, score meaning, bonded state: `docs/DDM_CALIBRATION.md` first.
- Roadmap: `README.md`.
- Carbohydrate mapping/validation: `docs/research/2026-09-24-carbohydrate-validation-operations.md` + `docs/research/2026-09-24-martini3-carbohydrate-validation.md`. Read before touching recognizer, validation routes, analysis worker.
- Micelle builder: PAUSED. Design in `docs/superpowers/specs/`, `docs/superpowers/plans/`. `micelle/` = partial implementation, NOT a validated model.
- Protein-detergent *panel*: second workflow, not a profile of the single-molecule one. Spec `docs/superpowers/specs/2026-09-28-protein-detergent-complex-panel-design.md`, plan in `docs/superpowers/plans/`. Reuses `micelle/` for detergent placement + existing executor for stages. Nothing implemented. Back-mapping: CG2AT2 run from source, vendored under `tools/` when the stage is built -- its align method and Martini 3 fragment DB match the protocol.

## Goal
Reproducible local workflow for membrane-protein detergent sims: validate input, orient protein, build Martini CG system, run staged GROMACS jobs, convert CG to atomistic, run atomistic stages, calculate analyses, expose status and results in a dashboard.

## Repo facts
- Maintained AA to CG path: `execution/adapters/aa.py`, then `execution/adapters/cg.py`, then Fast_Forward, then GROMACS. Any molecule with a compatible AA topology runs it. Packaged `molecules/DDM` = reference example + smoke candidate. `cg.py` = the generic CG adapter, the only CG stage pipeline. No `ddm` shim.
- Maintained assets: `resources/`, `dashboard/`. Historical `memembed`, then `martinize`, then `insane`, then `cg2at`: NOT maintained. The `archive/MemProtMD/` tree earlier notes named is gone from the repository.
- Force fields local: CG takes `resources/forcefields/martini_v3.itp`; AA copies `resources/templates/small_mols_fast_forward/1_AA_reference/charmm36-jul2022.ff`; 29 MDP templates under `resources/templates/`. Detergent support + residue/topology coverage: verify per molecule.
- Tools declared in `config/tools.json`, resolved by `dashboard/execution/tools.py`. Declared path verified executable before use; a declaration that cannot be honoured resolves to NOTHING, never a substitute. Record resolved version + path in each run manifest. (`~/Downloads/gromacs-2026.0` = source tree, no built `gmx`. In use: `/usr/local/gromacs/2026.3/bin/gmx`.)
- Carbohydrate validation = immutable analysis attached to a completed source run. Representation modes `/api/mappings/representations`; target metadata `/api/mappings/validation-targets`; reports `/api/jobs/<run-id>/carbohydrate-validation`.
- Checked-in carbohydrate targets = citation metadata only until molecule-specific measurements + uncertainties supplied. `setup` analyses + short trajectories = diagnostic execution checks; they do NOT authorize a model or establish validation.
- Bead Assignment editor: ONE diagram now -- the 3D NGL overlay (heavy atoms; each bead a translucent sphere at the mean of its atoms). The 2D depiction went 2026-10-12 (`aa318e0`); the server's RDKit depiction STAYS because the mapping export bundle embeds its SVG. `POST /api/mappings/overlay3d` serves the files from `models/mappings/overlay3d.py`; it reads the assignment being edited, including an unsaved local draft.
- Bonded panel atoms come from the SELECTED candidate's own molecule (`bonded.js` `resolveStructure`), not the packaged reference. Reading the reference for every candidate drew sucrose/trehalose/maltose on DDM's atoms (fixed `c6f018e`). Do not reintroduce.
- Sucrose path provisional: recognizer handles one hexopyranose ring, preserves remaining graph as a draft. Generated Sucrose mappings = diagnostic inputs, not official Martini parameters.

## Engineering rules
- Test against fixtures, NEVER the developer's workspace. A test that read a candidate out of `workspace/dashboard/mapping_drafts/` by filename passed only while that file existed and reported nothing about the code. Shared fixtures redirect every writable store: build the record you need.
- Trace inputs, state transitions, outputs, failure handling before edits.
- One local Python orchestration service; subprocess GROMACS jobs; persisted manifests + logs.
- Keep force-field/tool versions + exact commands in run metadata. Never silently overwrite runs.
- Validate uploaded structures, detergent definitions, resource limits, paths at trust boundaries.
- Stages: resumable, idempotent, cancellable, safe for concurrent runs.
- Simulation outputs immutable; derived analyses reference source trajectories.
- GROMACS + Martini by default. Other platforms only with measured need.
- Test command construction, stage transitions, failure recovery, analysis parsing without long simulations.

## Workflow contract
- AA-only runs use `STAGES` from `execution/adapters/aa.py`: solvation, neutralization, minimization, NVT equilibration, NPT equilibration, NPT production, reference publication.
- CG runs consume an AA reference (own parent AA-only job, or a completed shared reference) and run `STAGES` from `execution/adapters/cg.py`: AA reference, trajectory mapping, CG topology (`ff_inter`), CG simulation, CG assessment (`ff_assess`), SASA analysis. Only stages shelling out to a published tool name it; the mapping is our own script, named for what it does.
- Every stage records start/end, command, environment, inputs, outputs, exit code, log path.
- Stage with nothing to do records `skipped` = exit 4, reason in `skip.json` beside the script; run carries on. Nothing attempted, nothing owed.
- Runs terminate `complete`, `failed`, `cancelled`, or `blocked`.

## Do not
- Exercise a destructive control against the live workspace to see what it does. Point at a fixture, or inspect what the client would send. Two saved mapping candidates were destroyed by clicking Delete against real data.
- Treat notebooks as production orchestration without extracting + testing behavior.
- Assume every available detergent has Martini parameters.
- Delete simulation data during cleanup unless the user explicitly asks.
- Signal stored PIDs from a previous coordinator session; only the current worker owns its subprocess groups.
- Promote a completed diagnostic analysis to scientific validation. Completion proves execution, not model validity.

## Carbohydrate validation hand-off
Operations note holds the full Sucrose procedure, target IDs, report locations, paper-scale evidence requirements. Stable workflow:
1. Restart dashboard after adding a molecule or changing route/catalogue code (process loads endpoints at start).
2. **CG Bead Assignment**: generate + save a molecule-scoped candidate; keep its provenance + limitations.
3. **Single Molecule Simulations**: launch the saved mapping with the `draft-smoke` profile; wait for AA source + CG consumer.
4. Queue a validation attempt against the completed source run: `POST /api/jobs/<run-id>/carbohydrate-validation`, supported representation, cited target dataset, `Setup check` first. The dashboard controls that offered this were removed; analysis, queue route, report endpoints remain.
5. Open figures via the run artifact route `/api/jobs/<run-id>/artifacts/<relative-path>?inline=1`. Use the path `/api/jobs/<run-id>/artifacts` returned; never build a URL from a filesystem path.
Sucrose diagnostic records in the operations note = preserved examples, not a substitute for a fresh run after changing inputs or code.

## Standing decisions, not to be re-litigated
- CG production 20 fs; AA half 2 fs; `cg.mdp_integration` is the one place deciding it.
- CG **equilibration** 5 fs (user's decision, 2026-10-05).
- Published M3-Lipid set = project standard source, recorded per run; stays **untracked**.
- GLYCAM06 dropped (user's decision).
- Internal consistency = primary evidence; the reference's own numbers = context, not a pass mark.
- A mapping-consistency panel reads the published artifact and never recomputes it.
- Do not delete simulation data during cleanup.
- A mapping states its own ring scale (1.15 default, or the recogniser's value); the guard is a range, not a constant.
- Ring scale is **closed against**: not what breaks the DDM run; spend no further arm on it.
- **Fitted linkage values are not a diagnosis.** Length shared with maltose, stiffness exceeded by two stable molecules, values reproducible by resampling a stable one. Spend no further arm on the link's parameters.
- Phase 4 (sucrose + maltose experimental sources) deferred by the user, not abandoned.
- `-improperIncrement 10` goes to every BARTENDER fit, so that term's values will not match anything fitted before `4fc2513` wherever a linkage dihedral is written as an improper. Accepted price of a fit that returns at all.

## Environment gotchas that cost time
- A running dashboard is two caches: Python routes/models frozen at process start; `static/` + templates re-read per request. Restart after a Python change; hard-reload after a JS change; a job queued before a fix runs old code. Exception: a *stage script* and a *template* are read at prepare time, so an edit reaches the next run with no restart (verified on arm C and the 5 fs equilibration).
- GROMACS here = MPI-only build (`gmx_mpi`): `-ntmpi` invalid, `-ntomp` is the knob. In use: `/usr/local/gromacs/2026.3/bin/gmx`.
- An analysis subprocess gets a *work* directory whose files sit at the execution root, not under `stages/`; `analysis/runs/layout.py` resolves both spellings. A reader spelling only `stages/...` sees a complete run as empty.
- A mapping candidate's `molecule_snapshot` is a *file* record (`files`, `atom_order_sha256`), not a molecule record: no id for `CGNames` to resolve.
- A hydroxyl oxygen has TWO neighbours once its hydrogen counts. Any check saying otherwise undercounts every sugar fragment; cost a wrong diagnosis twice.
- Relative + absolute paths both matter: the fast tier runs from the repository root with `dashboard/.venv/bin/python`.
- `/api/jobs` pages at 20 (limit capped 100), newest first. Anything filtering the job list (panel, driver, script) must pass `?limit=`. Never print that endpoint to a terminal: 38 jobs is >1 MB.
- A run's `md.log` may be empty when it died violently; LINCS warnings + the segfault are in `logs/<stage>.log`; frame-by-frame evidence in the stage's `md.edr` (`gmx energy`). A long production's progress is in `stages/06_production/run.log`, and its step lines need `tr '\r' '\n'` before `grep` sees them.
- The surfaces analysis publishes a self-contained ~7 MB HTML. Serve via `/api/jobs/<id>/artifacts/<run-relative-path>?inline=1` -- the route sets a sandboxed CSP on `.html` permitting inline scripts + eval, which the Plotly scene needs. Build the URL from the path the API returned, never from a filesystem path.
- Hermes cron: a job recurs forever unless something stops it; `hermes cron remove` needs `-p <profile>`; a no-agent job's empty stdout delivers nothing (the watchdog pattern).
- **Measure with the right instrument before believing a finding.** Three grep/AST checks in one session gave three false findings: `\|` is a literal pipe in ERE (alternation search matched nothing); an AST scan counting only `ast.Assert` reported `unittest`'s `self.assert*` tests as assertion-free; a "prose assertion" search matched `assert cond, "message"` -- the message, not the comparison. Also `ps -eo ... -p <pid>` lists EVERY process, because `-e` wins. And `find ... | head -3` hides a real hit: a present file read as absent that way.
- GitNexus needs a bigger buffer pool to index this repo: `GITNEXUS_LBUG_BUFFER_POOL_SIZE=4294967296 npx -y gitnexus@latest analyze --index-only`. Without it: `The LadybugDB buffer pool (256 MiB) was exhausted`. Index in `.gitnexus/` (gitignored).

## Verify
```
dashboard/.venv/bin/python -m pytest -m 'not browser and not slow' -q     # fast tier: 1617, ~30 s
dashboard/.venv/bin/python -m pytest -m browser -q -n 6                   # browser tier: 166, ~85 s
dashboard/.venv/bin/python -m pytest -m slow -q -n 0                      # slow tier: 7
dashboard/.venv/bin/python -m ruff check dashboard tests                  # gate: F, E9, I must exit 0
```
Suite = 1,790 tests (1,617 fast + 166 browser + 7 slow), measured 2026-10-14. The browser tier runs at `-n 6` on this
box's 72 cores; the fast tier at `-n 8` in ~30 s.
Repo-wide `ruff check .` exits 1 on the ~23 pre-existing `micelle/` findings, unchanged.

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
