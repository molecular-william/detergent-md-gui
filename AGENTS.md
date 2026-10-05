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
`execution/adapters/cg.py`: AA reference, trajectory mapping, CG
topology (`ff_inter`), CG simulation, CG assessment (`ff_assess`), and SASA
analysis. Only the stages that shell out to a published tool name it; the
mapping is this repository's own script, so it is named for what it does.

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

## Handoff to the next session (2026-10-05, after the linkage and surfaces work)

The tree is clean apart from the same untracked reference assets (the vendored M3-Lipid duplicates, `.git-upstream/`, the
user's PDFs) -- **the M3-Lipid set stays untracked by the user's instruction; do not "tidy" it into the index**. Nothing has
been pushed since the pre-refactor baseline `e0504a3`; the branch is 294 commits ahead of `origin/main`.

**One chain is in flight and a cron is waiting on it: read "The DDM chain in flight" below before starting anything.**

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
| `a20d844` | the CG half keeps the barostat its template prescribes; `cg.py` no longer stamps `pcoupl = no` |
| `da99e89`, `c51e8db` | the CG equilibration integrates at 10 fs, then 5 fs, by the user's decision |
| `8417284` | the navigation rail moves to the right of the content |
| `cdb2ccc` | the linkage compared across molecules -- the `inter` rows the pairs table structurally cannot reach |
| `767c90d` | card 3 draws the run's solvent-accessible envelope analysis |
| `4fc2513` | the BARTENDER fit returns: `-improperIncrement 10`, because the 1-degree default never converged |
| `672c196` | the migration script's only public door gets a test; the bonded module's tested privates documented |

The documentation commits between those are evidence too (`c46ae38`, `3ac600f`, `ab29fd0`, `6aca073`, and the later ones that
correct them): each records what an arm eliminated, and several were wrong about something a later measurement overturned.
Read them as a sequence, not as conclusions.

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

**The linkage, which this table structurally could not reach, is now compared too** (`cdb2ccc`). Every row above is a
constrained ring distance and therefore inside one residue, so the `inter` role never fired there and the interaction that
actually differs between disaccharides was absent from the table entirely. It lives in the comparison's `terms`, and for a
two-ring molecule `terms` is nothing but the linkage. Measured over the same three molecules:

| term | types | role | spread | maltose | sucrose | trehalose |
| --- | --- | --- | --- | --- | --- | --- |
| bonds | `SN6`/`SP1r` | inter | **19.92%** | 0.310 | 0.298 | 0.363 |
| angles | `SN6`/`SP1r`/`SP4r` | inter | 26.06% | 131.060 | 121.993 | 100.363 |
| angles | `SN6`/`SP1r`/`SP1r` | inter | 34.61% | 100.898 | 99.017 | 69.785 |
| dihedrals | `SN6`/`SP1r`/`SP4r`/`SP4r` | inter | withheld | −97.21 | +5.42 | −118.22 |

The same bead-type signature that agrees to 0.06–0.20% on the ring edges is **19.92% apart on the linkage bond**. A dihedral's
spread is withheld in the reader *and* in the card, because a mean of a wrapped angle is not a difference however it is
subtracted -- that is asserted, not merely commented.

### The DDM CG run: six arms, one failure, and the onset is stochastic

One mapping, one set of settings; each arm differs from the one before by a single variable. The failure time, re-read from
each run's own log rather than from the warning it was first quoted for:

| arm | run | the variable | failed at |
| --- | --- | --- | --- |
| A, control | `860eb013a82c` | rings at measured x 1.15, `-constraints 1000000000` | **858.4 ps** |
| B, measured scale | `e08dc53410f9` | rings at measured x 1.0 (needs `5a098b1`) | 199.6 ps |
| C, FF's threshold | `6404c3951674` | `-constraints 10000`, so the stiff link is rigid | 113.2 ps |
| D, barostat | `207ff34ce8bc` | the CG templates' Parrinello-Rahman restored (`a20d844`) | 72.5 ps |
| E, 10 fs equilibration | `5bb303eb9ff5` | the Methods' exception, first value | 445.9 ps |
| F, 5 fs equilibration | `c48c50265874` | the same idea taken further (the user's call) | **53.5 ps** |

**Arm E was read as a trend and was not one.** It looked like 2–6x the arms before it until F, the same idea taken further,
failed first of all -- and re-reading arm A's own log showed it had reached 858 ps, the longest of the six. The honest reading
is a stochastic onset across an order of magnitude (53–858 ps) for configurations whose physics barely differs, and none of
the six variables moved it out of that band. Everything after that was measured against that fact.

**Six candidate causes are eliminated by measurement**, each with the number that kills it: the ring scale (B); the stiff
harmonic link at k 12964.8 and the integration instability it implies (C); the missing barostat, whose absence showed as
−583 bar and whose restoration gave 1.36 bar and a 9% contraction to the right density (D); energy pumping (`md.edr` flat,
−14850 ± 120 kJ/mol); the box or a periodic image (2.54 nm clearance against a 1.35 nm cutoff); and the bonded-pair exclusion
convention (the published `SUCR` entry excludes only its ring virtual site, as ours does).

**Then the parameters were put under the same treatment and yielded a different kind of answer.** The link's *length* is not
a DDM defect: every one of our disaccharides states it at ~0.272 in its initial topology (maltose 0.272008, DDM 0.269607), so
the divergence from the published set's 0.357–0.417 is this pipeline's convention for this bead partition. Its *stiffness* is
not a discriminator either: sucrose's fitted link is 24030.9 and trehalose's is 77167.6, six times DDM's 12964.8, and both run
200 ns with zero LINCS warnings. And the particular fitted values are reproducible by resampling: cutting a stable sugar's
series into 2,001-frame windows gives mean 2.7776–3.2655 and sigma 0.1546–0.2148, and DDM sits at **2.7731 / 0.1563**. DDM's
fitted link is what a normal disaccharide's link looks like sampled that briefly.

The one column that separates DDM from all three stable molecules is the **sample size**: every sugar's parameters were fitted
from 20,001 mapped frames (a 200 ns AA reference) and DDM's from 2,001 (20 ns) -- its own reference run is labelled "DDM AA
reference (short)". That is not a diagnosis, it is a confound, and it is the one being removed now.

### The DDM chain in flight

`dbc366ae772b` is the same AA reference at 200 ns: same seed 20260928, same 4.0 nm box, same force field, only
`aa_production_ps` changed from 20,000 to 200,000. Its prepared production mdp is `dt = 0.002, nsteps = 100000000`,
`nstxout-compressed = 5000`, so the mapping stage will see 20,001 frames where it saw 2,001 -- and because the seed and
initial conditions are unchanged, **the new run contains the old one as its prefix**, which makes the comparison DDM against
DDM rather than an analogy with maltose.

Measured cost: the short reference ran at 676.9 and 590.5 ns/day in this box; the long one has been running at ~1250 ns/day.

**`ddm-200ns-chain` (`42fbd11d10c5`, every 30 minutes, no LLM)** waits for it and then queues the CG arm that consumes it as
its reference (`mapping_candidate_2bcc24c3e5f149fab1e4f11f5d80ae0e.json`, label "DDM CG from the 200 ns reference (matched
sampling), published protocol, 20 ns"). **That arm is the first DDM run whose parameters were fitted from a 200 ns sample**,
so it either resolves the question or rules the sampling out. The job removes itself once it has acted -- that path was
exercised for real (created, removed, confirmed absent through `hermes -p moldym cron list`, recreated) -- and its output is
`local`, so read it with `hermes -p moldym cron runs`.

**After that arm completes, restart the coordinator.** The user asked for this explicitly: the running process still holds the
Python module from before `cdb2ccc` and `767c90d`, so the linkage card and the envelope card show their empty states until
the restart. It was deferred deliberately, so as not to orphan the 200 ns run's subprocess group; the window between the
reference finishing and the CG arm starting is the natural seam.

### The other stages' parameters, reviewed

- **The AA half is right.** `2321ee23a536` runs 2 fs with C-rescale NPT and then Parrinello-Rahman production at `ref-p = 1` --
  real pressure coupling at 1 bar, and the guide's 303.15 K for CHARMM36m.
- **The CG half's barostat was missing and is fixed** (`a20d844`). `cg.py`'s `mdp_integration` used to stamp `pcoupl: 'no'`
  over both mdps, so every CG production run was NVT with `ref_p` and `compressibility` as dead keys while the manifest
  recorded `pressure_bar: 1.0`. The templates carry C-rescale to equilibrate and Parrinello-Rahman at `tau_p = 12` to
  produce, and `cg.py` no longer overrides them; a grep for `pcoupl` in `cg.py` finds only a docstring saying it used to.
  Verified on arm D, the first arm ever to run the published protocol: mean pressure 1.36 bar against the NVT arms' −583 bar,
  the box contracting about 9% to the correct density. It failed anyway, and sooner.
- **The CG equilibration is 5 fs** (`c51e8db`, the user's decision). Same 10 ps as before, so 2,000 steps rather than 500; the
  template's `dt` decides it and the adapter reads each file's own `dt` back when it turns the requested duration into a step
  count. The Martini 3 Methods exclude equilibration from the 20 fs rule without naming a value, so both 10 fs and 5 fs are
  defensible on the paper's authority -- and neither is evidenced to help, which the six arms above show.
- Everything else is standard Martini 3 and matches the reference set: `dt` 20 fs in production, `rlist` 1.35 with
  `rcoulomb`/`rvdw` 1.1, reaction-field with `epsilon_r` 15, Verlet with `verlet-buffer-tolerance -1`, `nstlist` 20, frames
  every 10 ps.
- `ff_inter` is fitted at 303 K (`cg.fit_temperature` rounds the run's 303.15 for an int argument) and the thermostats are at
  303.15 K, so the fit and the simulation agree.
- `-constraints 10000` (`75029f0`) is Fast_Forward's own default and it matters: a bond fitted above it becomes a rigid
  constraint, which is how DDM's inter-ring link (fitted at 12964.8) became rigid while maltose's (2985.6) stayed flexible.

### The four crons are quiet, and one of them removes itself

`e3-chain` (`71a071938314`), `ddm-fit-chain` (`b4d8dfb2c7b8`) and `pdc-empty-micelle` (`eecb5a6b759f`) fire every 10 minutes
with no LLM. All three print nothing when they have nothing to do, verified by hand with `--verbose` and by reading their
tick files: the pdc one used to print a line every tick. All three also read `/api/jobs` unpaged until an earlier session, so
`e3-chain` could not see the maltose runs and reported "nothing to do" for a step it never looked at; they page to `total`
now. The driver that POSTs a comparison additionally guards on a completed attempt existing, because the analysis memo key
moves with any code change and a re-POST would rebuild it every tick.

`ddm-200ns-chain` (`42fbd11d10c5`, every 30 minutes) is the fourth and the only temporary one: a scheduled job recurs forever
by default, so it takes itself off the schedule once it has done its one thing, and it reports-and-removes itself if the
reference failed or has written nothing for six hours. A busy queue is the one case it stays for. Removal is
`hermes -p moldym cron remove <id>` -- **the profile flag is required**, because without it the command targets the default
profile's own store and would not find the job -- and the result is verified against the store, with a loud line naming the
command if it did not take.

### The coordinator is running

`http://127.0.0.1:5000`, concurrency 2 (`config/dashboard.json`), restarted for each Python change. The database holds 38 jobs
(13 completed, 25 failed) and 7 saved mapping candidates. Log at
`/home/wee/.hermes/profiles/moldym/cache/scratch/coordinator-run.log`.

The running process predates this session's Python changes, so **its `/api/runs/transferability` has no `linkages` key and its
`/api/jobs/<id>/mapping-consistency` has no `surfaces` block** -- both cards show their empty states on the live instance
until the restart described above. The browser tier starts a fresh server, which is where both were verified.

Worth keeping: the four E3 runs, `2321ee23a536` (the DDM AA reference `dbc366ae772b` supersedes), `8a73fe6448f2` (pdc
completed end to end), the six DDM arms above, and the two BARTENDER attempts that produced results (`a2a457cf9413` task
`9a0d4e97180a`, `1322f9e0782e` task `f840a2186aaf`). The arms are the record of what was eliminated, so they are evidence
even though every one failed. Ignore the failed pdc probes and the two earlier failed DDM `aa_cg` runs from 30 September.

**`8a73fe6448f2`'s system is void for geometry** -- built while `detergent_cg.bead_centres` divided by ten. And every DDM arm
dies before any production sampling, so their coordinates are evidence about the failure and about nothing else.

### Still open

| item | state |
| --- | --- |
| the DDM CG run, Task 2.4 | **arm in flight.** Six arms failed with a stochastic onset; the six candidate causes above are eliminated. `dbc366ae772b`'s CG arm is the first run whose parameters come from a 200 ns sample, and it is the current test |
| the tail-off control | **superseded.** It cannot be a mapping edit -- the validator refuses a candidate that leaves heavy atoms unmapped ("Missing heavy atoms: 1 ... 12" for the dodecyl chain). It needs DDM's head as a molecule of its own, with its own AA topology. The user set it aside on 2026-10-05 |
| Phase 4: sucrose and maltose sources | `resources/validation/carbohydrates/targets-v1.json` is still `metadata_only` for both; lead is `10.1016/j.carres.2004.12.038`. The user deferred this on 2026-10-05 |
| pdc phases C-E | the pipeline runs end to end and the panel queues it. C is the contact-graph criterion and retry policy (nothing judges whether the detergents contact the protein); D is back-mapping, the biggest of the three -- CG2AT2 is not even vendored yet; E is documentation |
| D1's other half | the run card does deep-link the tab with the run preselected (a browser test pins it); what is missing is the *numbered* line D1 asked for -- "CG 4 of 6 ring distances inside the AA spread" -- which is a bare button today |
| the iterative mapping refinement panel | README, five planned increments, none started: reference import, controlled variant generation, evidence execution, transparent ranking, human review gate |
| the micelle builder | paused at the user's request; `micelle/` is a partial skeleton and explicitly not a validated model |
| **no CI** | there is no `.github/workflows`. Enforcement is `gate_commit.sh`, a local script that runs the fast tier and ruff on named paths and blocks the commit, so the browser and slow tiers never run unless someone types them |
| **no coverage or mutation signal** | 831 unit tests with no signal on which are load-bearing. Mutation testing confined to `analysis/` and the adapters is the high-value use -- three mutations on freshly written tests, three caught, in about a minute |
| **no property-based tests** | the mapping-schema validator, the MDP writer and the published-artifact readers are the fuzzable surfaces, including the regex that parses a term's beads (`"(1,A) - (1,B) - (2,A)"`) |
| a quarantined skip | `tests/dashboard/browser/test_dashboard_browser.py` skips a real behaviour with an explicit reason and nothing tracking it: fix or delete |
| a stale measurement | `pyproject.toml`'s pytest comment claims the whole suite is "79.3 s serial / 19.6 s with these flags"; measured on 2026-10-05 it is 41.3 s at `-n 8 --dist loadfile` |
| a stray mapping candidate | `mapping_candidate_d17dac35a91a40ada85301877e70a7d1.json` is the head-only mapping built for the tail-off control. The validator refuses it for DDM runs, so it is inert, but it shows in the candidate picker. Delete it or keep it for the head-only molecule |

### Standing decisions, not to be re-litigated

- CG time step 20 fs in production; the atomistic half 2 fs; `cg.mdp_integration` is the one place that decides it.
- The CG **equilibration** integrates at 5 fs (the user's decision, 2026-10-05).
- The published M3-Lipid set is the project's standard source, recorded per run; it stays **untracked**.
- GLYCAM06 is dropped by the user's decision.
- Internal consistency is the primary evidence; the reference's own numbers are context, not a pass mark.
- A mapping-consistency panel reads the published artifact and never recomputes it.
- Do not delete simulation data during cleanup.
- A mapping states its own ring scale, 1.15 by default and the recogniser's own value; the guard is a range, not a constant.
- The ring scale is **closed against**: it is not what breaks the DDM run, and no further arm should be spent on it.
- **The fitted linkage values are not a diagnosis.** Its length is shared with maltose, its stiffness is exceeded by two
  stable molecules, and its values are reproducible by resampling a stable one. Do not spend another arm on the link's
  parameters.
- Phase 4 (sucrose and maltose experimental sources) is deferred by the user, not abandoned.
- `-improperIncrement 10` is passed to every BARTENDER fit, so **that term's values will not match anything fitted before
  `4fc2513`** wherever a linkage dihedral is written as an improper. Accepted as the price of a fit that returns at all.

### Environment gotchas that cost time

- A running dashboard is two caches: Python routes and models are frozen at process start, `static/` and templates are
  re-read per request. Restart after a Python change; hard-reload after a JS change; a job queued before a fix runs the
  old code. A *stage script* and a *template* are the exception: both are read at prepare time, so an edit there reaches the
  very next run with no restart -- verified on arm C and again on the 5 fs equilibration.
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
  a panel, a driver, a script -- must pass `?limit=`. Never print that endpoint to a terminal: 38 jobs is >1 MB.
- A run's `md.log` may hold nothing at all when it died violently; the LINCS warnings and the segfault are in
  `logs/<stage>.log`, and the frame-by-frame evidence is in the stage's `md.edr` (`gmx energy`). A long production's own
  progress is in `stages/06_production/run.log`, and its step lines need `tr '\r' '\n'` before `grep` will see them.
- The surfaces analysis publishes a self-contained ~7 MB HTML. Serve it through
  `/api/jobs/<id>/artifacts/<run-relative-path>?inline=1` -- the route sets a sandboxed CSP on `.html` that permits inline
  scripts and eval, which is what the Plotly scene needs. Build the URL from the path the API returned, never from a
  filesystem path.
- Hermes cron: a job recurs forever unless something stops it; `hermes cron remove` needs `-p <profile>` or it targets the
  default profile's store; a no-agent job's empty stdout delivers nothing, which is the watchdog pattern.
- **Measure with the right instrument before believing a finding.** Three separate grep/AST checks in one session produced
  three false findings: `\|` is a literal pipe in ERE, so an alternation search matched nothing; an AST scan counting only
  `ast.Assert` reported `unittest`'s `self.assert*` tests as assertion-free; and a "prose assertion" search was matching
  `assert cond, "message"` -- the message, not the comparison. Each looked like a real defect in the test suite and none was.
  Also `ps -eo ... -p <pid>` lists *every* process, because `-e` wins.
- GitNexus needs a bigger buffer pool before it can index this repo:
  `GITNEXUS_LBUG_BUFFER_POOL_SIZE=4294967296 npx -y gitnexus@latest analyze --index-only`. Without it the load dies with
  `The LadybugDB buffer pool (256 MiB) was exhausted`. The index is in `.gitnexus/`, which `.gitignore` excludes.

### Verify

```
dashboard/.venv/bin/python -m pytest -m 'not browser and not slow' -q     # fast tier, 999 at last full run
dashboard/.venv/bin/python -m pytest -m browser -q -n 2                   # browser tier, 53 passed 1 skipped
dashboard/.venv/bin/python -m ruff check dashboard tests                  # gate: F, E9, I must exit 0
```

The whole suite is 1,057 tests (831 unit, 172 integration, 54 browser, 7 marked `slow`) and runs in 41.3 s at
`-n 8 --dist loadfile`.

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
