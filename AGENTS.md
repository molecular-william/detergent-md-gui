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
exit code, and log path. A stage with nothing to do records `skipped` -- exit 4,
with its reason in `skip.json` beside the script -- and the run carries on to the
next stage; nothing was attempted and nothing is owed. Runs terminate as
`complete`, `failed`, `cancelled`, or `blocked`.

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

## Handoff to the next session (2026-10-02)

The tree is clean apart from untracked reference assets (the vendored M3-Lipid duplicates, `.git-upstream/`, two of the
user's PDFs) -- **the M3-Lipid set stays untracked by the user's instruction; do not "tidy" it into the index**. Nothing
has been pushed since the pre-refactor baseline `e0504a3`; the branch is 270 commits ahead of `origin/main`.

### What landed since the 2026-09-28 handoff

| commit | what |
| --- | --- |
| `096eea0` | a molecule's own fitted terms are preferred -- the ranking's first key had never been able to fire |
| `3f2934c` | the tail takes the published named defaults, by the context the physical graph gives it |
| `30bb52e` | the plan's tail expectation corrected: one end bond and one middle, not two ends |
| `d56f388` | the three fixes as diagnosed: a "grouping defect" that turned out not to be one, a dead ranking key, and where each term comes from |
| `413ca48`..`9515921` | BARTENDER as an optional analysis (`analysis/runs/bartender_fit.py`), plus the four fix-ups its own runs forced |
| `edde530` | a placed detergent is the size its topology says it is -- the last x10 site |
| `34af539`, `0097fa2` | the pdc panel queues a build and chooses its mapping; a pdc run completes end to end |
| `e58ce02` | a stage with nothing to do records `skipped` (exit 4, `skip.json`) and the run carries on |
| `eb9a345`, `ab743f8`, `cf41557`, `3b2ceb5`, `7373f82`, `de1a838`, `7b9bd6d`, `77304a6` | the six pdc stage defects: tail beads from the run's own mapping, the snapshot script's missing entry point, the restart's seed and continuation, a ring closure passed as a dihedral, `genion -g`, a centering trjconv fed one answer, a phase shorter than its cadence |

### DDM's bonded terms today (measured with `detergent_cg.derive` on the live draft)

Reference terms **20**, geometric fallbacks **5** (they were 12 and 13 before `096eea0` + `3f2934c`).

| term | value | source |
| --- | --- | --- |
| `S1A-TAIL3` | 0.528 / 394.25 | BARTENDER's fit to this project's own AA ensemble |
| `S1B-S2A` | 0.280 / 9997.44 | the same fit |
| `TAIL1-TAIL2` | 0.500 / 2800 | `b_C1_C1_end` from `martini_v3.0.0_ffbonded_v2.itp` |
| `TAIL2-TAIL3` | 0.490 / 2800 | `b_C1_C1_mid` from the same file |
| the ring constraints | as the mapping wrote them | the mapping, at the scale 1.15 that `schema.py` and `validation.py` enforce |

The fitted terms live in `references/bartender/DDM.itp` with `DDM.source.json` for provenance, fitted on 2,001 frames
of the solute from run `2321ee23a536`. The rule that forced itself into the open while wiring the ranking: **a fit is
keyed by bead type**, so it cannot say *which* of two `C1|C1` bonds it fitted -- BARTENDER held both and either would
have been applied to both. Where a fit is ambiguous for a signature, the published context-aware default decides; where
it is unambiguous, the fit stands as the molecule's own measurement.

### The ring question: closed, and the earlier claim is withdrawn

An earlier handoff said DDM's ring 1 had one concrete defect, "a missing `SP4r`". **That is wrong and is withdrawn.**
`coords.py:189` fixes the partition to the paper's canonical pairs for every recognised hexopyranose, and the typing
reads that partition's chemistry. Measured on the reference's own `inputs/common/molecule/results/MMFF/lig1.itp`, with
a hydroxyl counted as an oxygen with one heavy neighbour:

- ring 1's `S1A` holds the **alkyl ether** (the tail attaches `C11-O-C12`, with that O inside S1A) and so has one
  hydroxyl -- four atoms, two oxygens, one hydroxyl, which is `SP1r` by the rule;
- ring 1's other two beads each hold one hydroxyl plus one ring oxygen -- also `SP1r`;
- ring 2's `S2B` holds two hydroxyls, which is the diol -- `SP4r`.

`SP4r` in ring 1 would require a diol the molecule does not have. The full table is in the plan.

What survives from that line of work is the reason the fitted reference matters: the published Martini 3 sugar set has
no entry for a sugar whose anomeric carbon carries an *alkyl* ether, which is what DDM's ring 1 is, so the molecule's
own fit is the only source that reaches that ring.

### E3, the transferability chain: complete

Four runs and two comparisons, all `completed`, queued by `~/.hermes/profiles/moldym/scripts/e3-chain.py`:

| leg | run | result |
| --- | --- | --- |
| maltose AA reference | `a54ac8f64710` | -- |
| maltose CG | `22075892b606` | 6/6 ring pairs and 6/6 bonded rows inside the AA reference's own range; displacement rmsd 0.0062 nm |
| trehalose AA reference | `0bfa1a39ef76` | -- |
| trehalose CG | `4e4ff51e7417` | 6/6 and 6/6 inside; rmsd 0.0046 nm |

Both comparisons are `diagnostic_only: true` and `scientifically_validated: false`, read from
`analyses/mapping-consistency/<hash>/<hash>/result.json`.

**Still unbuilt, and the reason those numbers sit unused:** nothing compares the same *bead types* across molecules.
Every analysis compares AA against CG within one run, so the paper's own transferability question -- do the same bead
types behave the same in sucrose, maltose and trehalose -- has no reader. That is Phase 3 of the plan.

### The three crons are quiet

`e3-chain` (`71a071938314`), `ddm-fit-chain` (`b4d8dfb2c7b8`) and `pdc-empty-micelle` (`eecb5a6b759f`) each fire every
10 minutes with no LLM and print nothing when there is nothing to do. Verified 2026-10-02 by running each by hand with
`--verbose`: the E3 chain says "nothing to do"; the DDM fit chain says "3 attempts, all failed; not trying again"; the
pdc chain says "already queued: 8a73fe6448f2 completed". Leave, pause or delete them as you prefer -- none of them will
move anything on its own.

### The coordinator is running

`http://127.0.0.1:5000`, concurrency 2 (`config/dashboard.json`), started persistent in-session, log at
`/home/wee/.hermes/profiles/moldym/cache/scratch/coordinator-run.log`. The database holds 31 jobs.

Runs worth keeping: the four E3 runs above, `2321ee23a536` (the DDM AA reference the fit targets), and
`8a73fe6448f2` (pdc, completed end to end -- five stages exit 0 and Back-mapping `skipped` with "the run has no
protein, so there is nothing to align"). Ignore the failed pdc probes and the three failed DDM `aa_cg` runs.

**`8a73fe6448f2`'s system is void for geometry.** It was built while `detergent_cg.bead_centres` divided by ten, so
every placed detergent was a tenth of its size. Fixed in `edde530` and verified on a fresh preparation (ring pairs
0.3136 / 0.3739 nm against constraints of 0.3610 / 0.4294). Its stages are honest evidence that the pipeline works; its
coordinates are evidence about nothing.

### Still open

| item | state |
| --- | --- |
| the ring scale (plan Task 2.3) | the one open decision. 1.15 is the project's convention and is schema-enforced; BARTENDER fitted those pairs *without* a scale and landed on the raw AA means within 1.4%. The four arms meant to settle it are **void** -- a published model failed identically, so the harness was at fault. A real pipeline run is the measurement |
| Task 2.4: a real DDM `aa_cg` run | the path still dies at `Constraint error in algorithm Lincs` (three attempts: `ab22b392bc25`, `1322f9e0782e`, `3a9c4a5ef67c`), unexplained since the harness control voided the arm comparison. Today's terms have never been simulated |
| BARTENDER as a queued analysis | the module is real and tested; no queued result has landed. Runs from before today carry an improper dihedral BARTENDER scans for >400 s, so a fit needs a model from today's generator or a caller's longer timeout |
| Phase 3: the cross-molecule reader | unbuilt |
| Phase 4: sucrose and maltose sources | `resources/validation/carbohydrates/targets-v1.json` is still `metadata_only`; lead is `10.1016/j.carres.2004.12.038` |
| pdc phases C-E | the pipeline runs end to end and the panel queues it; the unused parts are still unused |
| Card 3 of the Mapping Validation tab | the displacement summary shows; the per-bead picture and the Connolly surfaces do not |
| D1's other half | the run card does not deep-link the Mapping Validation tab with a run preselected |

### Standing decisions, not to be re-litigated

- CG time step 20 fs; the atomistic half 2 fs; `cg.mdp_integration` is the one place that decides it.
- The published M3-Lipid set is the project's standard source, recorded per run; it stays **untracked**.
- GLYCAM06 is dropped by the user's decision.
- Internal consistency is the primary evidence; the reference's own numbers are context, not a pass mark.
- A mapping-consistency panel reads the published artifact and never recomputes it.
- Do not delete simulation data during cleanup.

### Environment gotchas that cost time

- A running dashboard is two caches: Python routes and models are frozen at process start, `static/` and templates are
  re-read per request. Restart after a Python change; hard-reload after a JS change; a job queued before a fix runs the
  old code.
- GROMACS here is an MPI-only build (`gmx_mpi`): `-ntmpi` is invalid, `-ntomp` is the knob; the binary in use is
  `/usr/local/gromacs/2026.3/bin/gmx`.
- An analysis subprocess is handed a *work* directory whose files sit at the execution root, not under `stages/`;
  `analysis/runs/layout.py` resolves both spellings. A reader that spells only `stages/...` sees a complete run as
  empty.
- A mapping candidate's `molecule_snapshot` is a *file* record (`files`, `atom_order_sha256`), not a molecule record:
  it has no id for `CGNames` to resolve.
- A hydroxyl oxygen has **two** neighbours once its hydrogen is counted. Any check that says otherwise undercounts
  every sugar fragment, and this cost a wrong diagnosis twice.
- Relative and absolute paths both matter: the fast tier runs from the repository root with
  `dashboard/.venv/bin/python`.

### Verify

```
dashboard/.venv/bin/python -m pytest -m 'not browser and not slow' -q     # fast tier, 960 at last full run
dashboard/.venv/bin/python -m ruff check dashboard tests                  # gate: F, E9, I must exit 0
```

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
