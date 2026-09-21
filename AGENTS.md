# Project guidance for coding agents

## Continuing existing work

Read [docs/PROJECT_GUIDE.md](docs/PROJECT_GUIDE.md) for repository layout,
dashboard operation, persistence, migration, and testing. For DDM
calibration, score interpretation, or bonded-state work, read
[docs/DDM_CALIBRATION.md](docs/DDM_CALIBRATION.md) first. Planned work is
listed in the roadmap section of [README.md](README.md).

The protein-detergent micelle builder is paused. Its design lives under
`docs/superpowers/specs/` and `docs/superpowers/plans/`; a partial
implementation exists under `micelle/` and is not a validated scientific
model.

## Goal

Build a reproducible local workflow for membrane-protein detergent
simulations: validate input, orient protein, build a Martini coarse-grained
system, run staged GROMACS jobs, convert CG to atomistic, run atomistic
stages, calculate analyses, and expose status/results through a web
dashboard.

## Current repository facts

- The maintained AA→CG path is `aa_workflow -> cg_adapter -> Fast_Forward ->
  GROMACS`. Any molecule with a compatible AA topology runs through it; the
  packaged `molecules/DDM` tree supplies the reference example and smoke
  candidate. `dashboard/execution/ddm.py` is a thin compatibility shim over
  `cg_adapter.py`.
- `archive/MemProtMD/` preserves Colab notebooks, legacy scripts, force-field
  files, example structures, MDP files, and archives. Maintained workflow
  assets live under `resources/` and `dashboard/`. The historical
  `memembed -> martinize -> insane -> cg2at` chain is not maintained.
- `martini_v3.itp`, `martini_v300.zip`, `insane3.py`, and `mdp_files/` are
  local assets. Detergent support and residue/topology coverage must be
  verified per molecule.
- `~/Downloads/gromacs-2026.0` appears to be a source/build tree; locate the
  built `gmx` before execution and record version/path in each run manifest.

## Engineering rules

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

AA-only runs use `aa_workflow.STAGES`: solvation, neutralization,
minimization, NVT equilibration, NPT equilibration, NPT production, and
reference publication. CG runs consume an AA reference — their own parent
AA-only job or a completed shared reference — and run `cg_adapter.STAGES`:
AA reference, trajectory mapping (`ff_map`), CG topology (`ff_inter`), CG
simulation, CG assessment (`ff_assess`), and SASA analysis.

Every stage records start/end time, command, environment, inputs, outputs,
exit code, and log path. Runs terminate as `complete`, `failed`, `cancelled`,
or `blocked`.

## Do not

- Treat notebooks as production orchestration without extracting and testing
  their behavior.
- Assume every available detergent is represented by Martini parameters.
- Delete simulation data during cleanup unless the user explicitly requests
  it.
- Signal stored process IDs from a previous coordinator session; only the
  current worker owns its subprocess groups.
- Promote a completed diagnostic analysis to scientific validation. Completion
  proves execution, not model validity.

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
