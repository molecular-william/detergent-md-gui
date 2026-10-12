# Project guidance for coding agents

## Read first
- Repo layout, dashboard, persistence, migration, testing: `docs/PROJECT_GUIDE.md`.
- DDM calibration, score meaning, bonded state: `docs/DDM_CALIBRATION.md` first.
- Roadmap: `README.md`.
- Carbohydrate mapping/validation: `docs/research/2026-09-24-carbohydrate-validation-operations.md` + `docs/research/2026-09-24-martini3-carbohydrate-validation.md`. Read before touching recognizer, validation routes, analysis worker.
- Micelle builder: PAUSED. Design in `docs/superpowers/specs/`, `docs/superpowers/plans/`. `micelle/` = partial implementation, NOT a validated model.
- Protein-detergent *panel*: second workflow, not a profile of the single-molecule one. Spec `docs/superpowers/specs/2026-09-28-protein-detergent-complex-panel-design.md`, plan in `docs/superpowers/plans/`. Reuses `micelle/` for detergent placement + existing executor for stages. Nothing implemented. Back-mapping: CG2AT2 run from source, vendored under `tools/` when the stage is built -- its align method and Martini 3 fragment DB match the protocol.

## Goal
Reproducible local workflow for membrane-protein detergent sims: validate input -> orient protein -> build Martini CG system -> staged GROMACS -> CG to AA -> AA stages -> analyses -> dashboard.

## Repo facts
- Maintained AA->CG path: `execution/adapters/aa.py -> execution/adapters/cg.py -> Fast_Forward -> GROMACS`. Any molecule with a compatible AA topology runs it. Packaged `molecules/DDM` = reference example + smoke candidate. `cg.py` = the generic CG adapter, the only CG stage pipeline. No `ddm` shim.
- Maintained assets: `resources/`, `dashboard/`. Historical `memembed -> martinize -> insane -> cg2at` chain NOT maintained; the `archive/MemProtMD/` tree earlier notes named is gone from the repository.
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

## Handoff 2026-10-05 (linkage + surfaces work)
Tree clean except untracked reference assets (vendored M3-Lipid duplicates, `.git-upstream/`, user's PDFs). **M3-Lipid set stays untracked by the user's instruction -- do not tidy it into the index.** Nothing pushed since pre-refactor baseline `e0504a3`; branch 294+ commits ahead of `origin/main`.

### Landed
| commit | what |
| --- | --- |
| `a9c2b07` | cross-molecule signature says when its molecules named different edges (`pairs_match`) |
| `c46a632` | cross-molecule comparison route + card (Phase 3 surface); panel's unpaged job read |
| `34392d6` | reader's answer under Task 3.3 |
| `8b9534a` | complex panel hint = template's own limitation (browser test red since `34af539`) |
| `5a098b1` | a mapping states the ring distance scale its geometry was built with (arm B) |
| `75029f0` | CG topology lets Fast_Forward constrain stiffest bonds (`-constraints 10000`, was 1000000000) |
| `c0a0b85`, `bff44f9` | ring head-to-head + arm C: what failed; six causes eliminated |
| `a20d844` | CG half keeps its template's barostat; `cg.py` no longer stamps `pcoupl = no` |
| `da99e89`, `c51e8db` | CG equilibration 10 fs, then 5 fs (user's decision) |
| `8417284` | navigation rail right of content |
| `cdb2ccc` | linkage compared across molecules -- the `inter` rows the pairs table cannot reach |
| `767c90d` | card 3 draws the run's solvent-accessible envelope analysis |
| `4fc2513` | BARTENDER fit returns: `-improperIncrement 10` (1-degree default never converged) |
| `672c196` | migration script's only public door tested; bonded module's tested privates documented |

Documentation commits between them are evidence too (`c46ae38`, `3ac600f`, `ab29fd0`, `6aca073`, and the corrections): each records what an arm eliminated; several were wrong about something a later measurement overturned. Read as a sequence, not conclusions.

### Phase 3 closed: same bead type across sucrose, maltose, trehalose
`GET /api/runs/transferability?ids=...` reads each run's own published comparison + the mapping from its manifest; card 5 of Mapping Validation draws it. Measured over `a2a457cf9413`, `22075892b606`, `4e4ff51e7417`:

| bead types | maltose | sucrose | trehalose | spread | molecules named |
| --- | --- | --- | --- | --- | --- |
| `SN6`/`SP1r` | 0.4222 | 0.4230 | 0.4226 | 0.20% | same edge each |
| `SN6`/`SP4r` | 0.3161 | 0.3160 | 0.3159 | 0.06% | same edge each |
| `SP1r`/`SP1r` | 0.3130 | 0.4019 | 0.4027 | 24.08% | **different**: `1B-1C`, `1A-1C`, `2A-2C` |
| `SP1r`/`SP4r` | 0.3464 | 0.3244 | 0.3339 | 6.57% | **different**: three edges vs three others |

24% is not a transfer failure: one molecule's `B-C` ring edge against two others' `A-C`, three bonds sharing two types. A signature carries `pairs_match`; the card names the edges behind every mean. Where the SAME edge is named in all three, types agree to 0.2% / 0.06%.

Linkage (unreachable by that table) now compared too (`cdb2ccc`). Every row above is a constrained ring distance inside one residue, so the `inter` role never fired and the interaction that differs between disaccharides was absent. It lives in the comparison's `terms`; for a two-ring molecule `terms` = the linkage. Same three molecules:

| term | types | role | spread | maltose | sucrose | trehalose |
| --- | --- | --- | --- | --- | --- | --- |
| bonds | `SN6`/`SP1r` | inter | **19.92%** | 0.310 | 0.298 | 0.363 |
| angles | `SN6`/`SP1r`/`SP4r` | inter | 26.06% | 131.060 | 121.993 | 100.363 |
| angles | `SN6`/`SP1r`/`SP1r` | inter | 34.61% | 100.898 | 99.017 | 69.785 |
| dihedrals | `SN6`/`SP1r`/`SP4r`/`SP4r` | inter | withheld | -97.21 | +5.42 | -118.22 |

Signature agreeing to 0.06-0.20% on ring edges is **19.92% apart on the linkage bond**. Dihedral spread withheld in reader AND card: a mean of a wrapped angle is not a difference however subtracted (asserted, not commented).

### DDM CG run: six arms, stochastic onset
One mapping, one settings set; each arm differs by one variable. Failure time re-read from each run's own log:

| arm | run | variable | failed at |
| --- | --- | --- | --- |
| A control | `860eb013a82c` | rings at measured x 1.15, `-constraints 1000000000` | **858.4 ps** |
| B measured scale | `e08dc53410f9` | rings at measured x 1.0 (needs `5a098b1`) | 199.6 ps |
| C FF threshold | `6404c3951674` | `-constraints 10000`, stiff link rigid | 113.2 ps |
| D barostat | `207ff34ce8bc` | templates' Parrinello-Rahman restored (`a20d844`) | 72.5 ps |
| E 10 fs equil | `5bb303eb9ff5` | Methods' exception, first value | 445.9 ps |
| F 5 fs equil | `c48c50265874` | same idea further (user's call) | **53.5 ps** |

Arm E was read as a trend and was not one: it looked like 2-6x the earlier arms until F failed first of all, and arm A's own log shows 858 ps -- longest of the six. Honest reading: stochastic onset across an order of magnitude (53-858 ps) for configurations whose physics barely differs; none of the six variables moved it out of that band.

Six candidate causes eliminated by measurement, each with its number: ring scale (B); stiff harmonic link at k 12964.8 + the integration instability it implies (C); missing barostat -- absence showed as -583 bar, restoration gave 1.36 bar and a 9% contraction to the right density (D); energy pumping (`md.edr` flat, -14850 +/- 120 kJ/mol); box or periodic image (2.54 nm clearance vs 1.35 nm cutoff); bonded-pair exclusion convention (published `SUCR` excludes only its ring virtual site, as ours does).

Parameters then got the same treatment, different kind of answer. Link *length* is not a DDM defect: every one of our disaccharides states ~0.272 in its initial topology (maltose 0.272008, DDM 0.269607), so divergence from the published 0.357-0.417 is this pipeline's convention for this bead partition. Link *stiffness* not a discriminator either: sucrose fitted 24030.9, trehalose 77167.6 (six times DDM's 12964.8), both run 200 ns with zero LINCS warnings. Fitted values reproducible by resampling: cutting a stable sugar's series into 2,001-frame windows gives mean 2.7776-3.2655, sigma 0.1546-0.2148; DDM sits at **2.7731 / 0.1563**. DDM's fitted link is what a normal disaccharide link looks like sampled that briefly.

Only column separating DDM from the three stable molecules: **sample size** -- every sugar fitted from 20,001 mapped frames (200 ns AA reference), DDM from 2,001 (20 ns; its reference run labelled "DDM AA reference (short)"). Not a diagnosis, a confound, and the one being removed.

### DDM chain in flight
`dbc366ae772b` = same AA reference at 200 ns: same seed 20260928, same 4.0 nm box, same force field, only `aa_production_ps` 20,000 -> 200,000. Production mdp `dt = 0.002, nsteps = 100000000`, `nstxout-compressed = 5000` -> mapping stage sees 20,001 frames where it saw 2,001. Seed + initial conditions unchanged, so **the new run contains the old one as its prefix** (DDM against DDM, not an analogy with maltose).

Cost: short reference ran 676.9 and 590.5 ns/day in this box; long one ~1250 ns/day.

`ddm-200ns-chain` (`42fbd11d10c5`, every 30 min, no LLM) waits for it, then queues the CG arm consuming it as reference (`mapping_candidate_2bcc24c3e5f149fab1e4f11f5d80ae0e.json`, label "DDM CG from the 200 ns reference (matched sampling), published protocol, 20 ns"). **First DDM run whose parameters come from a 200 ns sample** -- either resolves the question or rules sampling out. Job removes itself once acted (path exercised for real: created, removed, confirmed absent via `hermes -p moldym cron list`, recreated); output is `local`, read with `hermes -p moldym cron runs`.

Restart the coordinator after that arm completes: the process then running held Python from before `cdb2ccc`/`767c90d`, so the linkage + envelope cards showed empty states. Deferred deliberately to avoid orphaning the 200 ns run's subprocess group; the seam is between the reference finishing and the CG arm starting. A later session restarted it (both cards render since).

### Other stage parameters, reviewed
- AA half right: `2321ee23a536` runs 2 fs with C-rescale NPT then Parrinello-Rahman production at `ref-p = 1` (real pressure coupling, 1 bar; guide's 303.15 K for CHARMM36m).
- CG barostat was missing, fixed (`a20d844`): `cg.py`'s `mdp_integration` stamped `pcoupl: 'no'` over both mdps, so CG production was NVT with `ref_p`/`compressibility` dead keys while the manifest recorded `pressure_bar: 1.0`. Templates carry C-rescale to equilibrate, Parrinello-Rahman at `tau_p = 12` to produce; `cg.py` no longer overrides. `grep pcoupl cg.py` finds only a docstring saying it used to. Verified on arm D (first arm to run the published protocol): mean pressure 1.36 bar vs the NVT arms' -583 bar, box contracting ~9% to correct density. It failed anyway, and sooner.
- CG equilibration is 5 fs (`c51e8db`, user's decision): same 10 ps, so 2,000 steps not 500. Template's `dt` decides; adapter reads each file's own `dt` back when converting duration to step count. Martini 3 Methods exclude equilibration from the 20 fs rule without naming a value, so 10 and 5 fs are both defensible -- and neither is evidenced to help (six arms).
- Rest standard Martini 3, matches reference set: `dt` 20 fs production, `rlist` 1.35 with `rcoulomb`/`rvdw` 1.1, reaction-field `epsilon_r` 15, Verlet with `verlet-buffer-tolerance -1`, `nstlist` 20, frames every 10 ps.
- `ff_inter` fitted at 303 K (`cg.fit_temperature` rounds the run's 303.15 for an int argument); thermostats 303.15 K. Fit and simulation agree.
- `-constraints 10000` (`75029f0`) = Fast_Forward's own default, and it matters: a bond fitted above it becomes a rigid constraint -- how DDM's inter-ring link (12964.8) became rigid while maltose's (2985.6) stayed flexible.

### Crons: three quiet, one self-removing
`e3-chain` (`71a071938314`), `ddm-fit-chain` (`b4d8dfb2c7b8`), `pdc-empty-micelle` (`eecb5a6b759f`): every 10 min, no LLM. All print nothing when idle (verified by hand with `--verbose` and by reading tick files; the pdc one used to print a line every tick). All three read `/api/jobs` unpaged until an earlier session, so `e3-chain` could not see the maltose runs and reported "nothing to do" for a step it never looked at; they page to `total` now. The comparison-POSTing driver also guards on a completed attempt existing: the analysis memo key moves with any code change, so a re-POST would rebuild every tick.

`ddm-200ns-chain` (`42fbd11d10c5`, every 30 min) = fourth, the only temporary one: scheduled jobs recur forever, so it removes itself after its one act, and reports-and-removes itself if the reference failed or wrote nothing for six hours. A busy queue is the one case it stays for. Removal: `hermes -p moldym cron remove <id>` -- **profile flag required**, else it targets the default profile's store and misses the job. Verified against the store, with a loud line naming the command if it did not take.

### Coordinator
`http://127.0.0.1:5000`, concurrency 2 (`config/dashboard.json`), restart for each Python change. DB holds 38 jobs (13 completed, 25 failed), 7 saved mapping candidates. Log `/home/wee/.hermes/profiles/moldym/cache/scratch/coordinator-run.log`.

Keep: the four E3 runs, `2321ee23a536` (DDM AA reference; `dbc366ae772b` supersedes), `8a73fe6448f2` (pdc end to end), the six DDM arms, and the two BARTENDER attempts that produced results (`a2a457cf9413` task `9a0d4e97180a`, `1322f9e0782e` task `f840a2186aaf`). The arms are the record of what was eliminated -- evidence even though every one failed. Ignore failed pdc probes and the two failed DDM `aa_cg` runs from 30 September.

`8a73fe6448f2`'s system is VOID for geometry -- built while `detergent_cg.bead_centres` divided by ten. Every DDM arm dies before production sampling, so their coordinates are evidence about the failure and nothing else.

### Still open
| item | state |
| --- | --- |
| DDM CG run, Task 2.4 | arm in flight. Six arms failed, stochastic onset; six candidate causes eliminated. `dbc366ae772b`'s CG arm = first run whose parameters come from a 200 ns sample |
| tail-off control | superseded. Cannot be a mapping edit -- validator refuses a candidate leaving heavy atoms unmapped ("Missing heavy atoms: 1 ... 12" for the dodecyl chain). Needs DDM's head as its own molecule with its own AA topology. User set it aside 2026-10-05 |
| Phase 4: sucrose + maltose sources | `resources/validation/carbohydrates/targets-v1.json` still `metadata_only`; lead `10.1016/j.carres.2004.12.038`. Deferred by user 2026-10-05 |
| pdc phases C-E | pipeline runs end to end, panel queues it. C = contact-graph criterion + retry policy (nothing judges whether detergents contact the protein); D = back-mapping, biggest -- CG2AT2 not vendored yet; E = documentation |
| D1's other half | run card deep-links the tab with the run preselected (browser test pins it); missing is the NUMBERED line D1 asked for ("CG 4 of 6 ring distances inside the AA spread") -- a bare button today |
| iterative mapping refinement panel | README, five planned increments, none started: reference import, controlled variant generation, evidence execution, transparent ranking, human review gate |
| micelle builder | paused at user's request; `micelle/` partial skeleton, explicitly not a validated model |
| **no CI** | no `.github/workflows`. Enforcement = `gate_commit.sh` (fast tier + ruff on named paths, blocks the commit). Browser + slow tiers run only when named; the gate reports the browser tier on front-end paths (`-n 6`) but does not gate on it |
| **no coverage or mutation signal** | 1,261 fast-tier tests, no signal on which are load-bearing. Mutation testing in `analysis/` + adapters = the high-value use (three mutations on fresh tests, three caught, ~1 minute) |
| **no property-based tests** | fuzzable surfaces: mapping-schema validator, MDP writer, published-artifact readers, including the regex parsing a term's beads (`"(1,A) - (1,B) - (2,A)"`) |
| a stray mapping candidate | `mapping_candidate_d17dac35a91a40ada85301877e70a7d1.json` = head-only mapping for the tail-off control. Validator refuses it for DDM runs (inert) but it shows in the candidate picker. Delete, or keep for the head-only molecule |

### Standing decisions, not to be re-litigated
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

### Environment gotchas that cost time
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

### Verify
```
dashboard/.venv/bin/python -m pytest -m 'not browser and not slow' -q     # fast tier: 1261, ~14 s
dashboard/.venv/bin/python -m pytest -m browser -q -n 6                   # browser tier: 71, ~43 s
dashboard/.venv/bin/python -m pytest -m slow -q -n 0                      # slow tier: 7
dashboard/.venv/bin/python -m ruff check dashboard tests                  # gate: F, E9, I must exit 0
```
Suite = 1,339 tests (1,261 fast + 71 browser + 7 slow), measured 2026-10-12. Browser tier at `-n 2` takes 109 s for the same 71; this box has 72 cores.
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
