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

## Handoff to the next session (2026-10-05)

The tree is clean apart from the same untracked reference assets (the vendored M3-Lipid duplicates, `.git-upstream/`, two of the
user's PDFs) -- **the M3-Lipid set stays untracked by the user's instruction; do not "tidy" it into the index**. Nothing has been
pushed since the pre-refactor baseline `e0504a3`; the branch is 279 commits ahead of `origin/main`.

### What landed since the 2026-10-02 handoff

| commit | what |
| --- | --- |
| `a9c2b07` | a cross-molecule signature says when its molecules named different edges (`pairs_match`) |
| `c46a632` | the cross-molecule comparison gets a route and a card (Phase 3's surface), plus the panel's unpaged job read |
| `34392d6` | the reader's answer written under Task 3.3 |
| `8b9534a` | the complex panel's hint is the template's own limitation -- a browser test red since `34af539` |
| `5a098b1` | a mapping states the ring distance scale its own geometry was built with (the ring experiment's arm B) |
| `75029f0` | the CG topology stage lets Fast_Forward constrain its stiffest bonds (`-constraints 10000`, was 1000000000) |
| `c0a0b85`, `bff44f9` | the ring head-to-head and arm C: what failed, and the six causes each measurement eliminated |

### Phase 3 is closed: the same bead type across sucrose, maltose and trehalose

`GET /api/runs/transferability?ids=...` reads each run's own published comparison plus the mapping from its own manifest, and
card 5 of the Mapping Validation tab draws it. Measured over `a2a457cf9413`, `22075892b606`, `4e4ff51e7417`:

| bead types | maltose | sucrose | trehalose | spread | the molecules named |
| --- | --- | --- | --- | --- | --- |
| `SN6`/`SP1r` | 0.4222 | 0.4230 | 0.4226 | 0.20% | the same edge each |
| `SN6`/`SP4r` | 0.3161 | 0.3160 | 0.3159 | 0.06% | the same edge each |
| `SP1r`/`SP1r` | 0.3130 | 0.4019 | 0.4027 | 24.08% | **different**: `1B–1C`, `1A–1C`, `2A–2C` |
| `SP1r`/`SP4r` | 0.3464 | 0.3244 | 0.3339 | 6.57% | **different**: three edges against three others |

The 24% is not a transfer failure: it is one molecule's `B–C` ring edge against two others' `A–C`, three different bonds
sharing two types. Reporting it as-is would have been a wrong answer to the paper's own question, which is why a signature now
carries `pairs_match` and the card names the edges behind every mean. What holds: where the *same* edge is named in all three
molecules, the types agree to 0.2% and 0.06%.

**Not answerable from this data: the linkage.** Every published row is a *constrained* pair, so the glycosidic link never
appears and the `inter` role never fires; the link's geometry is in the comparison's `terms`, and nothing compares those
across molecules yet.

### The DDM CG run: three arms, three failures, and six causes eliminated

One mapping, one reference (`2321ee23a536`), one set of settings; each arm differs from the one before by a single variable.

| arm | run | the variable | outcome |
| --- | --- | --- | --- |
| A, control | `860eb013a82c` | rings at measured x 1.15, `-constraints 1000000000` | Lincs, 125-200 ps |
| B, measured scale | `e08dc53410f9` | rings at measured x 1.0 (needs `5a098b1`) | Lincs, 125-200 ps |
| C, FF's threshold | `6404c3951674` | `-constraints 10000`, so the stiff link is rigid | Lincs at step 5640, 112.8 ps |

Every arm is verified in its own files rather than by intent: B's `2_mapping/ring_targets.json` is 0.310205 -> 0.310205 where
A's is 0.310205 -> 0.356736, and C's `3_initial_CG/DDM.itp` writes `2 5 1 0.273` inside `[ constraints ]` with the harmonic
form under an undefined `#ifdef FLEXIBLE`.

Eliminated by measurement, each with the number that kills it: the ring scale (B); the stiff harmonic link at k 12964.8 and the
integration instability it implies (C); energy pumping (`md.edr` flat, -14850 +/- 120 kJ/mol across all 113 ps); the box or a
periodic image (2.54 nm clearance against a 1.35 nm cutoff); the missing barostat and its -583 bar (the maltose control sits at
-526 bar and completes 200 ns through the same scripts); the bonded-pair exclusion convention (the published `SUCR` entry
excludes only its ring virtual site, as ours does).

**What is left: the failure is DDM-specific and starts on a bead adjacent to the ring-1/ring-2 link** (atoms 2-3, then 2-5,
then 5-6 across the three arms), while the two-molecule sugars run the identical pipeline to 200 ns. The next experiment is
therefore a control, not another variant: **the same mapping with the three `C1` tail beads removed**, which makes DDM a
two-ring sugar comparable to the two that work. It survives and the tail is implicated; it fails and the linkage is.

### The other stages' parameters, reviewed

- **The AA half is right.** `2321ee23a536` runs 2 fs with C-rescale NPT and then Parrinello-Rahman production at `ref-p = 1` --
  real pressure coupling at 1 bar, and the guide's 303.15 K for CHARMM36m.
- **The CG half runs NVT.** `cg.py:140`'s `mdp_integration` stamps `pcoupl: 'no'` on both mdps of the CG stage, so the CG
  production is at fixed volume, `ref_p = 1.0` and `compressibility` are dead keys, and the recorded `pressure_bar: 1.0` never
  reaches it. Measured mean pressure: -583 bar on arm C, -526 bar on the maltose run that completes. Not fatal for a small
  solute -- the maltose control proves that -- but any density error is permanent, and the manifest claims a barostat it does
  not have. **Worth a decision, not a silent fix.**
- The CG equilibration is 10 ps (500 steps at 20 fs), from the `draft-smoke` profile. Thin, and it is the profile's number
  rather than a measured one.
- Everything else is standard Martini 3 and matches the reference set: `dt` 20 fs, `rlist` 1.35 with `rcoulomb`/`rvdw` 1.1,
  reaction-field with `epsilon_r` 15, Verlet with `verlet-buffer-tolerance -1`, `nstlist` 20, frames every 10 ps.
- `ff_inter` is fitted at 303 K (`cg.fit_temperature` rounds the run's 303.15 for an int argument) and the thermostats are at
  303.15 K, so the fit and the simulation agree.

### The three crons are quiet, and their blindness is fixed

`e3-chain` (`71a071938314`), `ddm-fit-chain` (`b4d8dfb2c7b8`) and `pdc-empty-micelle` (`eecb5a6b759f`) fire every 10 minutes
with no LLM. All three now print nothing when they have nothing to do, verified by hand with `--verbose` and by reading their
tick files: the pdc one used to print a line every tick. All three also read `/api/jobs` unpaged until this session, so
`e3-chain` could not see the maltose runs and reported "nothing to do" for a step it never looked at; they page to `total`
now. The driver that POSTs a comparison additionally guards on a completed attempt existing, because the analysis memo key
moves with any code change and a re-POST would rebuild it every tick.

### The coordinator is running

`http://127.0.0.1:5000`, concurrency 2 (`config/dashboard.json`), restarted for each Python change. The database holds 34 jobs;
6 saved mapping candidates. Log at `/home/wee/.hermes/profiles/moldym/cache/scratch/coordinator-run.log`.

Worth keeping: the four E3 runs, `2321ee23a536` (the DDM AA reference all three arms consumed), `8a73fe6448f2` (pdc completed
end to end), and the three DDM arms above -- they are the record of what was eliminated, so they are evidence even though
every one of them failed. Ignore the failed pdc probes and the two earlier failed DDM `aa_cg` runs from 30 September.

**`8a73fe6448f2`'s system is void for geometry** -- built while `detergent_cg.bead_centres` divided by ten. And every DDM arm
dies before any production sampling, so their coordinates are evidence about the failure and about nothing else.

### Still open

| item | state |
| --- | --- |
| the DDM CG run, Task 2.4 | still fails. Six causes eliminated by measurement; the next step is the tail-off control named above |
| the CG half's missing barostat | `pcoupl: 'no'` while `pressure_bar: 1.0` is recorded, and the CG half cannot relax its density. A decision for the user |
| BARTENDER as a queued analysis | the module is real, tested, and its fit is in `references/bartender/DDM.itp`; no queued analysis has produced a result |
| Phase 4: sucrose and maltose sources | `resources/validation/carbohydrates/targets-v1.json` is still `metadata_only` for both; lead is `10.1016/j.carres.2004.12.038`. The user deferred this on 2026-10-05 |
| the linkage across molecules | every published row is a constrained pair, so the `inter` role never fires; nothing compares link geometry across molecules |
| pdc phases C-E | the pipeline runs end to end and the panel queues it; the unused parts are still unused |
| D1's other half | the run card does deep-link the tab with the run preselected (a browser test pins it); what is missing is the *numbered* line D1 asked for, which is a bare button today |
| Card 3's Connolly surfaces | the per-bead chart is drawn and pinned by a browser test; the Connolly surface picture is not, and the card says so |

### Standing decisions, not to be re-litigated

- CG time step 20 fs; the atomistic half 2 fs; `cg.mdp_integration` is the one place that decides it.
- The published M3-Lipid set is the project's standard source, recorded per run; it stays **untracked**.
- GLYCAM06 is dropped by the user's decision.
- Internal consistency is the primary evidence; the reference's own numbers are context, not a pass mark.
- A mapping-consistency panel reads the published artifact and never recomputes it.
- Do not delete simulation data during cleanup.
- A mapping states its own ring scale, 1.15 by default and the recogniser's own value; the guard is a range, not a constant.
- The ring scale is **closed against**: it is not what breaks the DDM run, and no further arm should be spent on it.
- Phase 4 (sucrose and maltose experimental sources) is deferred by the user, not abandoned.

### Environment gotchas that cost time

- A running dashboard is two caches: Python routes and models are frozen at process start, `static/` and templates are
  re-read per request. Restart after a Python change; hard-reload after a JS change; a job queued before a fix runs the
  old code. A *stage script* is the exception: it is copied from `execution/scripts/` at prepare time, so an edit there
  reaches the very next run with no restart -- verified on arm C.
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
- `/api/jobs` is paged at 20 by default (limit capped at 100), newest first. Anything that filters the job list --
  a panel, a driver, a script -- must pass `?limit=`. Never print that endpoint to a terminal: 34 jobs is >1 MB.
- A run's `md.log` may hold nothing at all when it died violently; the LINCS warnings and the segfault are in
  `logs/<stage>.log`, and the frame-by-frame evidence is in the stage's `md.edr` (`gmx energy`).
- GitNexus needs a bigger buffer pool before it can index this repo:
  `GITNEXUS_LBUG_BUFFER_POOL_SIZE=4294967296 npx -y gitnexus@latest analyze --index-only`. Without it the load dies with
  `The LadybugDB buffer pool (256 MiB) was exhausted`. The index is in `.gitnexus/`, which `.gitignore` excludes.

### Verify

```
dashboard/.venv/bin/python -m pytest -m 'not browser and not slow' -q     # fast tier, 981 at last full run
dashboard/.venv/bin/python -m pytest -m browser -q -n 2                   # browser tier, 49 passed 1 skipped
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
