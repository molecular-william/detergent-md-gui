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

## Handoff to the next session (2026-09-28)

Nothing is in flight and the tree is clean. Nothing has been pushed since the pre-refactor baseline `e0504a3`.

### The CHARMM36m reference run completed

Run `03875cf39790` (`workspace/dashboard/runs/03875cf39790/`) — `aa_only`, Sucrose,
`charmm36-feb2026_cgenff-4.6`, cube 2.5 nm / 494 waters, 303.15 K, 1 bar, seed 20260928, 8 ntomp,
`constraints = all-bonds`, `rlist = 1.2`, `nstlist = 20`, `verlet-buffer-tolerance = -1`.

| field | value |
| --- | --- |
| status | `completed`, all 7 stages exit 0, `error: null` |
| wall clock | 07:23:03 → 10:28:29 UTC = 3 h 05 min |
| production | 100,000,000 steps = 200 ns, wall 3 h 03 min 34 s |
| performance | **1568.873 ns/day** (0.110 ms/step) |
| frames | 20,001 at 10 ps |
| artefacts | `run.xtc` 109.8 MB, `run.gro`, `run.edr` 122 MB, `lig.xtc` 5.26 MB, `diagnostics.xvg` 16.2 MB, `reference.json` 328 KB |
| validated | `scientifically_validated: false` — SwissParam parameters under a CHARMM36 tree assume CGenFF 4.x compatibility rather than demonstrating it; the caveat is in the manifest |

1568.873 ns/day is 1.3% from the 8-thread benchmark (1589), so the mdrun sweep's numbers transfer to
production. Re-measure before quoting either number in a new context.

### Where this stands (2026-09-29, after the first end-to-end CG consumer runs)

The CG consumer path runs to completion for a sugar. Two `aa_cg` runs are in the live database, both
`completed`, all six stages exit 0, both off the shared CHARMM36m reference `03875cf39790` and the
mapping the runs themselves recorded:

| run | CG timestep | CG production | rate | wall clock |
| --- | --- | --- | --- | --- |
| `3168e92e052f` | 20 fs | 10 ns in 500,000 steps | 28,885 ns/day | 3 min 38 s |
| `abd5bf461c49` | 2 fs (before the fix) | 10 ns in 5,000,000 steps | 2,863 ns/day | 8 min 10 s |

The coarse-grained half integrates at 20 fs and the atomistic half at 2 fs; `cg.mdp_integration` is the one
place that decides it, because the adapter used to stamp 2 fs on both. Three failures stood between the first
queue and the first completion, each fixed and pinned by a test: the seeded topology named beads with the
reference's per-residue letters while `mapped.gro` said `B01..` (`grompp`: "Too many warnings (1)"); the fitted
temperature reached `ff_inter` as a float where its argument is an int; and the topology named two residues, so
MDAnalysis — and therefore `ff_assess` — saw two four-bead molecules instead of one eight-bead one
(`IndexError: axis 1 with size 4`). A run's CG topology is now one residue per molecule, beads `B01..`, which
is what `mapped.gro`, the `.map` and the `.ndx` already said.

The Mapping Validation tab is live: `GET /api/jobs/<id>/mapping-consistency` reads the record the analysis
published (it is not recomputed in the route), and `static/js/mapping-validation.js` renders card 1 (ring and
constraint pairs) and card 2 (bonded terms) with the reference entry carried as context. Cards 3 and 4 say why
they are empty instead of showing a substitute number. Card 1's agreement is by construction — those
constraints were fitted from the same atomistic reference they are compared against — so it checks that the
mapping, the mapped trajectory and the simulated trajectory are one assignment, and the panel says so on the
card. The reference's numbers are context and set no verdict.

### E3, the transferability chain (2026-09-30)

The three-molecule check (the paper's own disaccharide transferability test) is queued and, once the gateway is
running, drives itself: `~/.hermes/profiles/moldym/scripts/e3-chain.py`, scheduled as cron job `e3-chain` every
10 minutes with no LLM. Each tick reads the live API and does the next thing that exists to do — maltose CG run,
trehalose mapping and reference, trehalose CG run, then both comparisons — and prints nothing when there is
nothing to do, so a quiet tick sends no message. It only calls the endpoints the panel's buttons call.

| leg | state |
| --- | --- |
| maltose reference | `a54ac8f64710` — restarted from solvation this morning by the coordinator's recovery (the machine was off overnight), ETA 13:08 HKT |
| maltose CG run | queued by the driver once the reference completes (~13:25) |
| trehalose | molecule added by the user and tracked (`cf6b830`); reference ~13:30-16:35, CG run ~16:50 |
| comparisons | both queued by the driver (~17:00) |

The driver is idempotent and safe to run by hand (`--verbose` reports what it sees). **A build item comes with
it**: nothing compares the same bead types *across* molecules yet — every analysis compares AA against CG within
one run — so when the chain lands the numbers exist and no analysis or panel presents them.

### PDC: what is actually missing (checked 2026-09-30)

Earlier notes said "phases C–E remain" without saying why nothing has ever run. The precise state: Phase B's
builders exist and are unit-tested (`adapters/pdc_box.py`, `pdc_placement.py`, `pdc_protein.py`,
`pdc_solvation.py`, `pdc_view.py`), `pdc.py` carries the catalogue, `SETTING_SPECS` and the six-stage `STAGES`
contract — and **nothing writes the stage scripts `STAGES` names**. `grep prepare_system.sh` finds the string
only in `STAGES` itself, and `workflow.prepare_run` calls `cg.prepare` unconditionally, so a `pdc` job cannot be
created at all. That is tasks B7 (`pdc.prepare`) and B8 (dispatch on run type) in
`docs/superpowers/plans/2026-09-28-protein-detergent-complex-panel.md`, and it is the next PDC work: six stage
directories and their scripts over a `python -m` entry point that calls the tested builders, the dispatch, and
tests that read the scripts the way `test_aa_gromacs_invocation.py` reads the AA ones.

### Still open

- Phase B experiments E1–E5 (spec §Phase B): a second independent AA reference, CG geometry at paper scale,
  transferability across sucrose/maltose/trehalose, the osmotic-pressure series (needs a concentration-series
  builder), water-octanol transfer (needs an AA octanol topology).
- Card 3 (shape and volume) has no figure yet: the displacement summary is shown, the per-bead picture and
  Connolly surfaces are not. Card 4 is blocked on the system builder above.
- D1's other half: the run card does not yet carry the line that deep-links this tab with a run preselected.
- `resources/validation/carbohydrates/targets-v1.json` is still `metadata_only`, so no experimental path is
  evidence-complete.
- An analysis is handed a *work* directory whose files sit at the execution root, not under `stages/`; both
  spellings resolve through `analysis/runs/layout.py`. A reader that spells only `stages/...` sees a complete
  run as empty.
- A run's `molecule_snapshot` in a mapping candidate is a *file* record (`files`, `atom_order_sha256`), not a
  molecule record: it has no id for `CGNames` to resolve.

### The ensemble comparison tool (delivered 2026-09-29)

Built and measured before the CG runs above existed; no re-run of the simulation was needed.

```python
from dashboard.analysis import sugar_ensemble as se
se.format_report(se.run('workspace/dashboard/runs/03875cf39790', molecule='Sucrose', entry_name='SUCR'))
```

Over 20,001 frames: ring 1 is reproduced within 4.4%, all three constraints inside the published
ranges. Ring 2 is systematically short — **A–B −16.0% with std 0.0035, outside the published range**,
A–C −9.6% outside, B–C −6.6% inside. The same gap appeared on the earlier run under a different
force-field tree, so it is a property of the reference mapping, not of one run or of sampling. Build
the tool as a surface (a route plus a panel section) over these two functions, referencing the
completed run immutably, with the ring-2 A–B gap presented as the diagnostic it is rather than as a
pass/fail. Pin it with a test.

### Open items, each with its evidence

| item | state |
| --- | --- |
| PDC panel phases B5–B6 | landed but never exercised end to end (no PDC simulation has run); phases C–E remain. Re-checked 2026-09-29: the live jobs table holds two jobs, both `aa_only` and both completed |
| Docs debt from `75de474` | **paid in `6d83cad`** — `AGENTS.md`, `DDM_CALIBRATION.md`, `PROJECT_GUIDE.md` and `dashboard/README.md` all state that the controls were removed and the analysis is queue-through-API only. Verified 2026-09-29 |
| `static/vendor/ngl.js` | **closed in `48408cf`** — tracked with its provenance in `ngl.js.source.json`. Verified 2026-09-29 |
| mapping panel tests | **closed 2026-09-30** — the save and delete paths *do* have browser coverage: `test_dashboard_browser.py` clicks `#save-mapping-inplace` (91), `#delete-mapping` (96) and `#save-mapping-editor` (167) against a test workspace, and asserts the disabled states before each. The row was stale; re-checked rather than trusted |
| destroyed records | two Maltose mapping candidates lost at 16:12 during test runs and unrecoverable; DDM's unscoped candidate was deleted with a byte copy kept in `~/.hermes/profiles/moldym/cache/scratch/deleted-mapping_candidate_5c8ccfb716274fd9b653b2effaa71bf2.json` |
| `.ipynb_checkpoints/` | **not a risk**: the same bytes are tracked at `architecture-review-20260924.html` (md5 `19150e0c1e2c89c31e6f0247f0ae7a68` for both files). Verified 2026-09-29 |
| 7.3 sweep | **done in `f9690b0`** — the shims are gone; `tests/dashboard/{conftest,factory,support}.py` remain. Verified 2026-09-29 |
| diagnostics | **colour scale fixed 2026-09-30** (`630f1cc`): `COLOUR_SCALE_NM = 0.1` for every run, `colour_scale()` the one place it is decided, the record says `per_run: false` plus `clipped`. The "same result written to two JSON files" half was verified paid: the writer emits only the stratified name, which `test_the_writer_emits_only_the_stratified_file` asserts |
| GLYCAM06 | **dropped 2026-09-30 by the user's decision** — not to be pursued. The AmberTools/acpype installs stay on the machine; nothing in the tree depends on a Glycam-Web topology |

Four rows of this table were already paid before the handoff was written, which is why they carry the commit that
paid them. They were verified against the tree on 2026-09-29 and not taken on trust.

### What the ensemble tool's numbers are, and are not

Measured on `03875cf39790` on 2026-09-29, the two rings are the other way round from the first reading of this
table's neighbour: residue 1 is the **fructofuranose** (`identify_furanoses`: 5-ring, oxygen 4) and residue 2 is
the **glucopyranose** (`identify_hexoses`: 6-ring, oxygen 10), which is what the reference's own numbers say too
(residue 2's 0.376/0.468/0.359 against its free `GLC` entry's 0.380/0.470/0.396). So the short pair is the
**glucose** ring's A–B, and the fructose ring agrees within 4%.

The obvious suspect — that our fragment split puts different atoms in the beads — was tested and refuted. A bead
has to be a connected set, so the glucose ring's eleven atoms admit ten arc cuts; filtering those by the bead types
the reference names (SN6 / SP4r / SP1r) leaves exactly **one** partition, and it is the one the recognizer already
produces. Reordering `identify_furanoses` cannot be used to probe this: its carbon order also drives the shared
exocyclic-oxygen ownership rule and a reorder produces a mapping with one atom in two beads.

The standing goal is **internal consistency, not reproduction**: our CG model should reproduce the AA structures
available to us, with the reference's numbers as context rather than as a pass mark. Any tool built over these
numbers should say which of the two it is comparing.


### Environment gotchas that cost time this session

- A running dashboard is two caches: Python routes and models are frozen at process start, `static/`
  and templates are re-read per request. Restart after a Python change; hard-reload after a JS change;
  a job queued before a fix runs the old code.
- `static/js/shared.js`'s `api()` returns the response body itself — only `/distance-diagnostics` wraps its
  payload in `data`. A new tab is a button plus a `<section>` in `dashboard.html` and a mount case in
  `main.js`'s `dashboard:tab` listener; `tabs.js` derives the tab list from the DOM, so there is no second
  list to keep in step. Verify a JS change with the browser cache disabled (`Network.setCacheDisabled` plus
  `Page.reload(ignoreCache=True)`), or the previous module is what gets inspected.
- An analysis subprocess is handed a *work* directory whose files sit at the execution root, not under
  `stages/`; `analysis/runs/layout.py` resolves both spellings. A reader that spells only `stages/...` sees a
  completed run as empty.
- GROMACS here is an MPI-only build (`gmx_mpi`): `-ntmpi` is invalid, `-ntomp` is the knob.
- Relative and absolute paths both matter: the fast tier runs from the repository root with
  `dashboard/.venv/bin/python`.

### Verify

```
dashboard/.venv/bin/python -m pytest -m 'not browser and not slow' -q     # fast tier, 771 at last full run
dashboard/.venv/bin/python -m ruff check .                                # gate: F, E9, I must exit 0
```

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
