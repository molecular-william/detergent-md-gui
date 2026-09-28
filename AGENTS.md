# Project guidance for coding agents

## Continuing existing work

Read [docs/PROJECT_GUIDE.md](docs/PROJECT_GUIDE.md) for repository layout,
dashboard operation, persistence, migration, and testing. For DDM
calibration, score interpretation, or bonded-state work, read
[docs/DDM_CALIBRATION.md](docs/DDM_CALIBRATION.md) first. Planned work is
listed in the roadmap section of [README.md](README.md).
For carbohydrate mapping or validation work, read
[docs/research/2026-09-24-carbohydrate-validation-operations.md](docs/research/2026-09-24-carbohydrate-validation-operations.md)
and the scientific method note
[docs/research/2026-09-24-martini3-carbohydrate-validation.md](docs/research/2026-09-24-martini3-carbohydrate-validation.md)
before changing the recognizer, validation routes, or analysis worker.

The protein-detergent micelle builder is paused. Its design lives under
`docs/superpowers/specs/` and `docs/superpowers/plans/`; a partial
implementation exists under `micelle/` and is not a validated scientific
model.

The protein-detergent *panel* is a second workflow, not a profile of the single
molecule one. It is specified in
`docs/superpowers/specs/2026-09-28-protein-detergent-complex-panel-design.md`,
with its task breakdown in the matching plan under `docs/superpowers/plans/`.
It reuses `micelle/` for detergent placement and the existing executor for
stages; no part of it is implemented yet. Back-mapping uses CG2AT2, run from
source and vendored under `tools/` when that stage is built, because its align
method and its Martini 3 fragment database match the protocol.

## Goal

Build a reproducible local workflow for membrane-protein detergent
simulations: validate input, orient protein, build a Martini coarse-grained
system, run staged GROMACS jobs, convert CG to atomistic, run atomistic
stages, calculate analyses, and expose status/results through a web
dashboard.

## Current repository facts

- The maintained AA→CG path is `execution/adapters/aa.py ->
  execution/adapters/cg.py -> Fast_Forward -> GROMACS`. Any molecule with a
  compatible AA topology runs through it; the packaged `molecules/DDM` tree
  supplies the reference example and smoke candidate. `cg.py` is the generic CG
  adapter and the only CG stage pipeline; there is no `ddm` shim.
- `archive/MemProtMD/` preserves Colab notebooks, legacy scripts, force-field
  files, example structures, MDP files, and archives. Maintained workflow
  assets live under `resources/` and `dashboard/`. The historical
  `memembed -> martinize -> insane -> cg2at` chain is not maintained.
- `martini_v3.itp`, `martini_v300.zip`, `insane3.py`, and `mdp_files/` are
  local assets. Detergent support and residue/topology coverage must be
  verified per molecule.
- Tool locations are declared in `config/tools.json` and resolved by
  `dashboard/execution/tools.py`: a declared path is verified executable before use,
  and a declaration that cannot be honoured resolves to nothing rather than to a
  substitute. Record the resolved version and path in each run manifest.
  (`~/Downloads/gromacs-2026.0` is a source tree with no built `gmx`; the build in
  use on this machine is `/usr/local/gromacs/2026.3/bin/gmx`.)
- Carbohydrate validation is an immutable analysis attached to a completed
  source run. The dashboard exposes representation modes at
  `/api/mappings/representations`, molecule-specific target metadata at
  `/api/mappings/validation-targets`, and reports at
  `/api/jobs/<run-id>/carbohydrate-validation`.
- The checked-in carbohydrate targets are citation metadata only until
  molecule-specific measurements and uncertainties are supplied. `setup`
  analyses and short trajectories are diagnostic execution checks; they do
  not authorize a model or establish scientific validation.
- The CG Bead Assignment editor shows one assignment two ways from one source: a 2D depiction
  with bead circles at the mean of their atoms, and a 3D NGL overlay drawing the heavy atoms
  with each bead as a translucent sphere at that same centre. `POST /api/mappings/overlay3d`
  serves both files from `models/mappings/overlay3d.py`, and both read the assignment being
  edited, including an unsaved local draft.
- The current Sucrose path is provisional: the automatic recognizer handles
  one hexopyranose ring and preserves the remaining connected graph as a
  draft. Treat generated Sucrose mappings as diagnostic inputs, not official
  Martini parameters.

## Engineering rules

- Test against fixtures, never against the developer's workspace. A test that read a mapping
  candidate out of `workspace/dashboard/mapping_drafts/` by filename passed only while that
  file happened to exist, so it reported nothing about the code and turned red the moment the
  file was gone. Shared fixtures redirect every writable store; build the record you need.

- Trace inputs, state transitions, outputs, and failure handling before
  edits.
- Prefer one local Python orchestration service and subprocess-based GROMACS
  jobs with persisted manifests and logs.
- Keep force-field/tool versions and exact commands in run metadata. Never
  silently overwrite runs.
- Validate uploaded structures, detergent definitions, resource limits, and
  paths at trust boundaries.
- Make stages resumable, idempotent, cancellable, and safe for concurrent
  runs.
- Keep simulation outputs immutable; derived analyses reference source
  trajectories.
- Use GROMACS and Martini by default. Add other platforms only with measured
  need.
- Test command construction, stage transitions, failure recovery, and analysis
  parsing without requiring long simulations.

## Workflow contract

AA-only runs use `STAGES` from `execution/adapters/aa.py`: solvation,
neutralization, minimization, NVT equilibration, NPT equilibration, NPT
production, and reference publication. CG runs consume an AA reference — their
own parent AA-only job or a completed shared reference — and run `STAGES` from
`execution/adapters/cg.py`: AA reference, trajectory mapping (`ff_map`), CG
topology (`ff_inter`), CG simulation, CG assessment (`ff_assess`), and SASA
analysis.

Every stage records start/end time, command, environment, inputs, outputs,
exit code, and log path. Runs terminate as `complete`, `failed`, `cancelled`,
or `blocked`.

## Do not

- Exercise a destructive control against the live workspace to see what it does. Point it at
  a test fixture, or inspect what the client would send instead of sending it; two saved
  mapping candidates were destroyed by clicking Delete against real data to watch the request.

- Treat notebooks as production orchestration without extracting and testing
  their behavior.
- Assume every available detergent is represented by Martini parameters.
- Delete simulation data during cleanup unless the user explicitly requests
  it.
- Signal stored process IDs from a previous coordinator session; only the
  current worker owns its subprocess groups.
- Promote a completed diagnostic analysis to scientific validation. Completion
  proves execution, not model validity.

## Carbohydrate validation hand-off

Use the operations note for the complete Sucrose procedure, target IDs, report
locations, and the paper-scale evidence requirements. The stable workflow is:

1. Restart the dashboard after adding a molecule or changing route/catalogue
   code so the process loads current validation endpoints.
2. In **CG Bead Assignment**, generate and save a molecule-scoped candidate;
   preserve its provenance and limitations.
3. In **Single Molecule Simulations**, launch the saved mapping with the `draft-smoke` profile and
   wait for the AA source and CG consumer to complete.
4. Queue a validation attempt against the completed source run through
   `POST /api/jobs/<run-id>/carbohydrate-validation` with a supported
   representation and a cited target dataset, running `Setup check` first. The
   dashboard controls that used to offer this were removed; the analysis, its
   queue route and its report endpoints remain.
5. Open generated figures through the run artifact route
   `/api/jobs/<run-id>/artifacts/<relative-path>?inline=1`. Use the artifact
   path returned by `/api/jobs/<run-id>/artifacts`; do not construct a URL from
   the absolute filesystem path.

The current Sucrose diagnostic records are documented in the operations note.
They are preserved examples, not a replacement for a fresh run after changing
inputs or code.

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
