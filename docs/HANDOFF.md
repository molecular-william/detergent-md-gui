# Handoff and history

State, measurements and open items for this repository. `AGENTS.md` holds the rules; this holds the record they were
derived from. Read it before starting work on the DDM CG chain or the coordinator.

## Landed 2026-10-15: the gate, the mutation signal, and 29 property tests

**The gate the docs name exists in two places now, and the docs were right all along.** This file's "no CI" row
named `gate_commit.sh` as the repository's enforcement; a session on 2026-10-15 first reported that script as
absent from the machine, **and that report was wrong**. The error was a `find … -maxdepth 6`, which cannot reach
`~/.hermes/profiles/moldym/skills/software-development/detergent-md-dashboard/scripts/gate_commit.sh` -- ten levels
deep -- where the gate has lived since 2026-10-12 and where the skill's `references/verification-and-commit-gates.md`
documents it, browser-tier behaviour included. What was actually true is narrower and worth keeping: **the
repository carried no copy**, so a reader working inside the repo could not run the thing this file named.
`scripts/gate_commit.sh` (`c6ec468`, brought to full parity in the commit that corrected this paragraph) is that
copy: it resolves the repository from its own location so it needs no environment, captures each status from the
command itself rather than from a pipeline, gives `ruff` only the `.py` paths that still exist (a template parses as
Python; a deleted path arrives as `E902`), stages exactly the named paths with `git add -A --`, commits with
`git commit -F <message-file>`, and reports the browser tier on front-end paths without gating on it. Proven both
ways before it landed: a file with an unused import is refused with `gate: NOT committing (pytest 0, ruff 1)` and
nothing staged; its first real use caught an unused `pytest` import in a freshly written test file. Two copies of
one script is a trap of its own, so a behaviour change belongs in both -- or this file should name one of them.

**There is a mutation signal, confined to `analysis/` and the adapters.** `scripts/mutation_check.py` with
`scripts/mutants.json` (`901920a`) applies one mutation at a time, runs the test selection that mutant names, and
reports caught or survived -- eleven mutants, about four seconds each. Measured: **10 caught, 1 survived, 0 error,
0 stale**. The survivor is the control, a mutant whose replacement is its own target: a harness that cannot report
a survivor cannot tell "the tests caught this" from "the selection never ran". Three safeguards, one per way the
instrument could lie -- a target that does not occur exactly once is `stale` and fails the run; the file is
restored and the restore verified by hash; a module with an uncommitted change is refused rather than restored
over.

**What it found on its first run: the run card's range boundary was unpinned** (`2791f76`). Flipping
`aa.min <= cg.mean <= aa.max` to the strict form survived the whole fast tier, because every other fixture in
`unit/test_consistency_report.py` sits strictly inside the range or strictly outside it. The range is closed, and
the new test asserts both ends with values exact in binary (0.25, 0.5), so the comparison is *on* the boundary
rather than near it.

**Property tests, and the one defect the first of them found** (`ed5b2ab`). Three files under
`tests/dashboard/unit/`: `test_properties_mapping_schema.py` (arbitrary bodies; the ring-scale range from both
ends; the name and bead-count bounds measured after `strip()`), `test_properties_terms.py` (a written term read
back at every length; arbitrary text as well-formed or absent beads; the linkage's spread recomputed from the
result's own per-molecule means), `test_properties_mdp.py` (every key exactly once -- the `doubly defined`
refusal -- every value back through `cg._mdp_value`, the timestep on the atomistic half only, the barostat never
stamped). The validator property found the defect: `check_schema` read `data.get('representation_mode')` *before*
the isinstance test meant to refuse a non-dict, so that test was dead code and a list or `None` came back as an
`AttributeError` where the contract is the `ValueError` a route turns into a 400 -- latent rather than live, since
every mapping route goes through `routes/common.json_object`, which answers 400 first. `hypothesis>=6,<7` is
declared in `requirements-dashboard-tests.txt`.

**State, measured 2026-10-15.** Tests: fast tier **1,687 passed** in ~30 s, browser **173** in ~85 s, slow **7**
in ~19 s, **1,867 collected**; `ruff check dashboard tests` exits 0, repo-wide `ruff check .` exits 1 on the 19
pre-existing `micelle/` findings. Branch **432 commits ahead of `origin/main`**, HEAD `2791f76`, tree clean apart
from the untracked reference assets. Store: **8 jobs, all completed** (6 `aa_only`, 2 `aa_cg`) and **5 saved
mapping candidates**. Coordinator on `http://127.0.0.1:5000`, pid 280798, started 2026-10-14 18:27, logging to
`~/.hermes/profiles/moldym/cache/scratch/dashboard-1827.log`. **No cron jobs are scheduled and none is to be rebuilt** -- the user cancelled
the scheduled drivers on 2026-10-15 (see the cancellation note below).

## Where things stand (2026-10-05, linkage and surfaces work)
Tree clean except untracked reference assets: vendored M3-Lipid duplicates, `.git-upstream/`, the user's PDFs. **The M3-Lipid set stays untracked by the user's instruction. Do not tidy it into the index.** Nothing pushed since pre-refactor baseline `e0504a3`. The branch is 426 commits ahead of `origin/main`, HEAD `fe30ef2` -- both **as of this 2026-10-05 snapshot**; measured on 2026-10-15 it is 432 / `2791f76`, in the section above.

## Landed 2026-10-12 → 2026-10-15: the protein-detergent chain and the run view
**The protein-detergent chain is a real pipeline now.** `execution/adapters/pdc.py` owns ten stages and runs its own `pdc_*.sh` scripts rather than the CG half's: Protein preparation (optional PDB2PQR rebuild+protonation, `prepare_protein`, off by default, skippable), System preparation, Energy minimisation, NVT equilibration, NPT equilibration, **CG assessment MD (production only — it reads `../4_npt/`, so the chain no longer equilibrates twice)**, Micelle assessment, CG extension MD, Final assessment, Back-mapping (CG2AT2, a toggle). The three equilibration legs run `resources/templates/protein_detergent/{minimisation,nvt,npt}.mdp` (`pdc.LEGS`), and only `1_system/prepare_system.sh` plus those legs are filled at prepare time (`pdc.GENERATED_STAGES`). The prepare step's rules live in `execution/adapters/pdc_preparation.py` (measured on 4iar: 20 of 928 beads were `nan`, 312 missing atoms across 25 residues).

**The protein belt is a torus.** With a stated membrane the lattice places detergents on a tube whose centre-line is the protein's slab circle and whose radius is the detergent's measured length, heads on the outer surface and tails facing the centre (`pdc_placement._belt_torus`, `SHAPE_TORUS`); `radius_nm` is a **floor** on that centre-line. A build with no stated membrane — the empty micelle, a packaged protein, an import that states none — keeps the old sphere, where `radius_nm` is the radius (`SHAPE_SPHERE`).

**Secondary structure is mdtraj's, through martinize2.** The CG stage asks martinize2 with the bare `-dssp` flag, which vermouth answers with `mdtraj.compute_dssp` (`pdc_build.SS_SOURCE`); `MDAnalysis.analysis.dssp` is the recorded fallback (`SS_FALLBACK_SOURCE`). The two disagree — 42 of 230 residues on 1AT9 — so the assignment's letters are written into the run report. `mdtraj` and `pdb2pqr` are declared in `requirements-dashboard-tests.txt`.

**The osmotic run type is one run owning N concentrations.** `settings.molalities` is the plan; each concentration gets its own directory and its own checkpoint, resumed with `gmx mdrun -cpi`; `series_on_failure` is `carry_on` or `stop`; the type is gated to sugars. The one-concentration `osmotic_molality` shape is removed from the vocabulary, not deprecated.

**New panels.** A `Run view` in **both** workspaces (a chooser scoped per workspace by `web/sections.SECTIONS[...]['run_types']`, AA and CG structures through the artifact route, figures listed inline, the transport row under the canvas, `pdc` runs delegated to Complexes) — landed `98f5825`. The protein-detergent `New run` with a live **system preview** (`GET /api/pdc/preview/placement`, `execution/pdc_preview.py`) and the `prepare_protein` toggle, plus the encapsulation estimate and subunit/back-map choices. The `Osmotic Series` panel.

**Bead rendering and the bond rule.** One shared size table and one family colouring with an on-screen legend (`web/static/js/ngl-beads.js`: `BEAD_RADII_NM`, `BEAD_FAMILY_COLOURS`); `run-view-structure.js` decides the loader — a file carrying `CONECT` is drawn from those records and never guessed at, a coarse-grained file is `inferBonds: 'none'`, and only an all-atom file with no CONECT is left to the viewer's inference. `GET /api/jobs/<id>/structure` serves a run's coarse-grained structure with its own topology's bonds as CONECT.

**Snapshots run by default.** The `snapshots` kind carries `runs_for_every_run=True` (`kinds.py:194-205`) and `analysis_coordinator.queue_defaults` queues it for every run that reaches a terminal state; a run with no trajectory records `skipped` with the producer's reason and stays `complete`. The producer resolves the run's own layout (`observability.generate` → `layout.frame_source`): `07_reference/` for an AA-only run, `4_CG_sim/` for a consumer, and it records the trajectory, role and stride it used.

**The Run view's beads are drawn at 0.3, and the row can now produce the frames it plays.** `run-view.js`'s `BEAD_SCALE` (0.3) multiplies `ngl-beads.js`'s model radii at its own `applyBeadRadii` call -- the scale the New Run preview draws at too, so one mapped sugar is one size in the preview the reader judges and the run they then inspect. At 1 the beads read as one lump: a Martini 3 bonded pair sits 1.4-2.2 A apart at bead centres (measured on `a2a457cf9413`'s `stages/2_mapping/mapped.gro`, 1.40 A at the closest pair) while an S bead's own radius is 2.30 A, so every bonded pair overlaps by 2-3 A. The readout names the multiplier, the browser test asserts the class radius *and* the multiplier, and a source-level test holds the two panels to one number.

**A `Generate trajectory` control sits at the right of the frame slider.** It queues the `snapshots` analysis for the run on screen (`POST /api/jobs/<jid>/snapshots`) where that run has published no frame series, and is drawn disabled with its reason where it holds no `.xtc` under `stages/`. It reads the task's own status back rather than assuming one: `completed` re-reads the run, `failed` names the error. That re-read asks the route for `refresh=1`, and `runs.py`'s artifacts route now honours it: `artifact_index` is cached in the store and a *completed* run's index is otherwise frozen for the life of the process, so without it a run that had just published frames would show them only after a restart. The control's tests stub the queue route rather than clicking it against a live coordinator, which would start a real analysis.

**`a2a457cf9413` is the run this was built for.** It completed 2026-09-29, before `runs_for_every_run` landed, so it holds five `.xtc` files (`stages/4_CG_sim/md.xtc` the largest) and no `snapshots` attempt at all -- not even a `skipped` one. That is why its transport row drew two disabled buttons over an empty strip: every run that predates the default, plus any run whose analysis was skipped, is waiting for exactly this control.

## Where things stand (2026-10-05, linkage and surfaces work) — continued
### Landed
| commit | what |
| --- | --- |
| `a9c2b07` | cross-molecule signature says when its molecules named different edges (`pairs_match`) |
| `c46a632` | cross-molecule comparison route and card (Phase 3 surface), plus the panel's unpaged job read |
| `34392d6` | the reader's answer written under Task 3.3 |
| `8b9534a` | complex panel hint is the template's own limitation; a browser test red since `34af539` |
| `5a098b1` | a mapping states the ring distance scale its geometry was built with (arm B) |
| `75029f0` | CG topology lets Fast_Forward constrain its stiffest bonds (`-constraints 10000`, was 1000000000) |
| `c0a0b85`, `bff44f9` | ring head-to-head and arm C: what failed, and the six causes eliminated |
| `a20d844` | CG half keeps the barostat its template prescribes; `cg.py` no longer stamps `pcoupl = no` |
| `da99e89`, `c51e8db` | CG equilibration integrates at 10 fs, then 5 fs, by the user's decision |
| `8417284` | navigation rail moves right of the content |
| `cdb2ccc` | the linkage compared across molecules: the `inter` rows the pairs table cannot reach |
| `767c90d` | card 3 draws the run's solvent-accessible envelope analysis |
| `4fc2513` | BARTENDER fit returns: `-improperIncrement 10`, because the 1-degree default never converged |
| `672c196` | migration script's only public door gets a test; bonded module's tested privates documented |
| `aa318e0` | bead editor keeps one diagram (3D only); workspace subtitle shortened |
| `c6f018e` | bonded diagram draws the candidate's own molecule, not the packaged reference |
| `ce77222` | the delete test waits for the panel it clicks |
| `47346a1` | `AGENTS.md` compressed; history moved here |

Documentation commits between those are evidence too (`c46ae38`, `3ac600f`, `ab29fd0`, `6aca073`, and the later ones that correct them). Each records what an arm eliminated. Several were wrong about something a later measurement overturned. Read them as a sequence, not as conclusions.

## Phase 3 closed: same bead type across sucrose, maltose and trehalose
`GET /api/runs/transferability?ids=...` reads each run's own published comparison and the mapping from its own manifest. Card 5 of Mapping Validation draws it. Measured over `a2a457cf9413`, `22075892b606`, `4e4ff51e7417`:

| bead types | maltose | sucrose | trehalose | spread | molecules named |
| --- | --- | --- | --- | --- | --- |
| `SN6`/`SP1r` | 0.4222 | 0.4230 | 0.4226 | 0.20% | same edge each |
| `SN6`/`SP4r` | 0.3161 | 0.3160 | 0.3159 | 0.06% | same edge each |
| `SP1r`/`SP1r` | 0.3130 | 0.4019 | 0.4027 | 24.08% | **different**: `1B–1C`, `1A–1C`, `2A–2C` |
| `SP1r`/`SP4r` | 0.3464 | 0.3244 | 0.3339 | 6.57% | **different**: three edges against three others |

The 24% is not a transfer failure. It is one molecule's `B–C` ring edge against two others' `A–C`, three different bonds sharing two types. Reporting it as-is would answer the paper's question wrongly, which is why a signature carries `pairs_match` and the card names the edges behind every mean. Where the same edge is named in all three molecules, the types agree to 0.2% and 0.06%.

The linkage, which that table cannot reach, is compared too (`cdb2ccc`). Every row above is a constrained ring distance inside one residue, so the `inter` role never fired there and the interaction that actually differs between disaccharides was absent. It lives in the comparison's `terms`. For a two-ring molecule `terms` is nothing but the linkage. Measured over the same three molecules:

| term | types | role | spread | maltose | sucrose | trehalose |
| --- | --- | --- | --- | --- | --- | --- |
| bonds | `SN6`/`SP1r` | inter | **19.92%** | 0.310 | 0.298 | 0.363 |
| angles | `SN6`/`SP1r`/`SP4r` | inter | 26.06% | 131.060 | 121.993 | 100.363 |
| angles | `SN6`/`SP1r`/`SP1r` | inter | 34.61% | 100.898 | 99.017 | 69.785 |
| dihedrals | `SN6`/`SP1r`/`SP4r`/`SP4r` | inter | withheld | −97.21 | +5.42 | −118.22 |

The signature that agrees to 0.06–0.20% on ring edges is **19.92% apart on the linkage bond**. A dihedral's spread is withheld in the reader and in the card, because a mean of a wrapped angle is not a difference however it is subtracted. That is asserted, not merely commented.

## The DDM CG run: six arms, one failure, and the onset is stochastic
One mapping, one set of settings. Each arm differs from the one before by a single variable. The failure time, re-read from each run's own log rather than from the warning it was first quoted for:

| arm | run | variable | failed at |
| --- | --- | --- | --- |
| A, control | `860eb013a82c` | rings at measured x 1.15, `-constraints 1000000000` | **858.4 ps** |
| B, measured scale | `e08dc53410f9` | rings at measured x 1.0 (needs `5a098b1`) | 199.6 ps |
| C, FF's threshold | `6404c3951674` | `-constraints 10000`, so the stiff link is rigid | 113.2 ps |
| D, barostat | `207ff34ce8bc` | the CG templates' Parrinello-Rahman restored (`a20d844`) | 72.5 ps |
| E, 10 fs equilibration | `5bb303eb9ff5` | the Methods' exception, first value | 445.9 ps |
| F, 5 fs equilibration | `c48c50265874` | the same idea taken further (the user's call) | **53.5 ps** |

Arm E was read as a trend and was not one: it looked like 2–6x the arms before it until F, the same idea taken further, failed first of all. Arm A's own log showed 858 ps, the longest of the six. The honest reading is a stochastic onset across an order of magnitude, 53–858 ps, for configurations whose physics barely differs. None of the six variables moved it out of that band.

Six candidate causes are eliminated by measurement, each with the number that kills it. The ring scale (B). The stiff harmonic link at k 12964.8 and the integration instability it implies (C). The missing barostat: its absence showed as −583 bar, its restoration gave 1.36 bar and a 9% contraction to the right density (D). Energy pumping (`md.edr` flat, −14850 ± 120 kJ/mol). The box or a periodic image (2.54 nm clearance against a 1.35 nm cutoff). The bonded-pair exclusion convention: the published `SUCR` entry excludes only its ring virtual site, as ours does.

Then the parameters got the same treatment and gave a different kind of answer. The link's length is not a DDM defect: every one of our disaccharides states it at ~0.272 in its initial topology (maltose 0.272008, DDM 0.269607). The divergence from the published set's 0.357–0.417 is this pipeline's convention for this bead partition. Its stiffness is not a discriminator either: sucrose's fitted link is 24030.9 and trehalose's is 77167.6, six times DDM's 12964.8, and both run 200 ns with zero LINCS warnings. The fitted values are reproducible by resampling: cutting a stable sugar's series into 2,001-frame windows gives mean 2.7776–3.2655 and sigma 0.1546–0.2148, and DDM sits at **2.7731 / 0.1563**. DDM's fitted link is what a normal disaccharide's link looks like sampled that briefly.

One column separates DDM from all three stable molecules: the **sample size**. Every sugar's parameters were fitted from 20,001 mapped frames, a 200 ns AA reference. DDM's came from 2,001, 20 ns; its own reference run is labelled "DDM AA reference (short)". That is not a diagnosis, it is a confound, and it is the one being removed.

## The DDM chain in flight
`dbc366ae772b` is the same AA reference at 200 ns: same seed 20260928, same 4.0 nm box, same force field, only `aa_production_ps` 20,000 to 200,000. Its prepared production mdp is `dt = 0.002, nsteps = 100000000`, `nstxout-compressed = 5000`: the mapping stage sees 20,001 frames where it saw 2,001. Seed and initial conditions are unchanged, so **the new run contains the old one as its prefix**. That makes the comparison DDM against DDM, not an analogy with maltose.

Measured cost: the short reference ran at 676.9 and 590.5 ns/day in this box. The long one has been running at ~1250 ns/day.

The CG arm that consumes this reference -- `mapping_candidate_2bcc24c3e5f149fab1e4f11f5d80ae0e.json`,
"DDM CG from the 200 ns reference (matched sampling), published protocol, 20 ns" -- was **never queued**: the
scheduled driver that was to queue it is cancelled, so queueing it is a deliberate manual act now, and the item it
served is written off below.

Restart the coordinator after that arm completes. The user asked for this explicitly: the running process still held the Python module from before `cdb2ccc` and `767c90d`, so the linkage card and the envelope card showed their empty states. It was deferred so as not to orphan the 200 ns run's subprocess group; the window between the reference finishing and the CG arm starting is the natural seam. A later session restarted it, and both cards render since.

## The other stages' parameters, reviewed
- The AA half is right. `2321ee23a536` runs 2 fs with C-rescale NPT and then Parrinello-Rahman production at `ref-p = 1`: real pressure coupling at 1 bar, and the guide's 303.15 K for CHARMM36m.
- The CG half's barostat was missing and is fixed (`a20d844`). `cg.py`'s `mdp_integration` used to stamp `pcoupl: 'no'` over both mdps, so every CG production run was NVT with `ref_p` and `compressibility` as dead keys while the manifest recorded `pressure_bar: 1.0`. The templates carry C-rescale to equilibrate and Parrinello-Rahman at `tau_p = 12` to produce, and `cg.py` no longer overrides them. A grep for `pcoupl` in `cg.py` finds only a docstring saying it used to. Verified on arm D, the first arm ever to run the published protocol: mean pressure 1.36 bar against the NVT arms' −583 bar, the box contracting about 9% to the correct density. It failed anyway, and sooner.
- The CG equilibration is 5 fs (`c51e8db`, the user's decision). Same 10 ps as before, so 2,000 steps rather than 500. The template's `dt` decides it, and the adapter reads each file's own `dt` back when it turns the requested duration into a step count. The Martini 3 Methods exclude equilibration from the 20 fs rule without naming a value, so both 10 fs and 5 fs are defensible on the paper's authority. Neither is evidenced to help, which the six arms above show.
- Everything else is standard Martini 3 and matches the reference set: `dt` 20 fs in production, `rlist` 1.35 with `rcoulomb`/`rvdw` 1.1, reaction-field with `epsilon_r` 15, Verlet with `verlet-buffer-tolerance -1`, `nstlist` 20, frames every 10 ps.
- `ff_inter` is fitted at 303 K (`cg.fit_temperature` rounds the run's 303.15 for an int argument) and the thermostats are at 303.15 K, so the fit and the simulation agree.
- `-constraints 10000` (`75029f0`) is Fast_Forward's own default and it matters. A bond fitted above it becomes a rigid constraint, which is how DDM's inter-ring link (fitted at 12964.8) became rigid while maltose's (2985.6) stayed flexible.

## The cron drivers: cancelled by the user, 2026-10-15
The scheduled drivers are cancelled and every mention of them has been removed from this file and from the skill.
Nothing is scheduled, checked today: `~/.hermes/profiles/moldym/cron/jobs.json` reads `{"jobs": []}`, `cron/output/`
holds no files, and `hermes -p moldym cron list` answers "No scheduled jobs in profile 'moldym'". **Do not rebuild
one.** What they were, in one line: a no-LLM job that woke on a timer, asked the live API what already existed,
queued only the next thing that did not, and took itself off the schedule when finished. The narration of what each
one did went with them, deliberately -- what survives that matters is that the DDM arm one of the four existed to
queue was never queued, and that item is written off below.

## The coordinator
`http://127.0.0.1:5000`, concurrency 2 (`config/dashboard.json`), restarted for each Python change. Measured from `workspace/dashboard/jobs.sqlite3` on 2026-10-15: **8 jobs, all completed** (6 `aa_only`, 2 `aa_cg`) and **5 saved mapping candidates** -- the sixth was the stray head-only candidate, deleted through `DELETE /api/mappings/drafts/<name>` on 2026-10-15 with a byte-exact copy of it kept at `~/.hermes/profiles/moldym/cache/scratch/mapping_candidate_d17dac35a91a40ada85301877e70a7d1.json` (sha256 `4fdb9c92…`, the file's own). (The figure this section carried earlier — 38 jobs, 13 completed — described a workspace that no longer exists.)

**The process, measured 2026-10-15 16:40: pid 280798, started 2026-10-14 18:27, `PPID` 1 (the shell that launched it is gone), cwd the repository root, and it logs to `/home/wee/.hermes/profiles/moldym/cache/scratch/dashboard-1827.log`.** It is serving code whose every file predates it (the newest is `pdc_preparation.py` at 18:19, the process at 18:27), so no restart is owed. The path this section used to name, `…/scratch/coordinator-run.log`, is a stale file from an earlier process -- it stops at 2026-10-13 13:04 -- and a reader who tails it concludes the dashboard is dead.

**Most of that list no longer exists, and saying so is the point of this paragraph.** Measured on 2026-10-15 with `find workspace/dashboard/runs -name "*<id>*"` and a query against `jobs.sqlite3`: the runs that survive are the eight the store still holds -- the four E3 runs (`a2a457cf9413`, `22075892b606`, plus the two AA references `a54ac8f64710`, `0bfa1a39ef76`), the two earlier sucrose runs (`13ba0a087fad`, `03875cf39790`), the second AA reference (`38f54e67f13d`), and `dbc366ae772b` (the 200 ns DDM reference). Gone from both the store and the disk: `2321ee23a536`, `8a73fe6448f2` (the pdc run that completed end to end), every one of the six DDM arms (`860eb013a82c`, `e08dc53410f9`, `6404c3951674`, `207ff34ce8bc`, `5bb303eb9ff5`, `c48c50265874`), and `1322f9e0782e` -- the BARTENDER run whose fitted link is quoted throughout the arms section above. Their numbers remain evidence about what the old code did; their directories do not exist to re-read, and a lost record has no substitute, so do not go looking for them in a later session and do not rebuild a file at the same path to stand in for one.

**`8a73fe6448f2`'s system is void for geometry.** It was built while `detergent_cg.bead_centres` divided by ten. Every DDM arm dies before any production sampling, so their coordinates are evidence about the failure and about nothing else.

## Still open

Checked against the tree, the live store and the running app on 2026-10-15. A row that was paid, or that was never
true, is marked rather than carried forward.

| item | state (2026-10-15) |
| --- | --- |
| the DDM CG run, Task 2.4 | **written off by the user, 2026-10-15.** Six arms failed with a stochastic onset and the six candidate causes are eliminated. `dbc366ae772b` -- the 200 ns reference the matched-sampling arm consumes -- is `completed`; that arm was never queued, its driver is cancelled, and no schedule may be rebuilt. The sampling question stays answered by the cheaper resampling control: a stable sugar cut into 2,001-frame windows reproduced DDM's fitted link (mean 2.7776, sigma 0.1546 against 2.7763/0.1563) |
| the tail-off control | superseded. Not a mapping edit: the validator refuses a candidate that leaves heavy atoms unmapped ("Missing heavy atoms: 1 ... 12" for the dodecyl chain), so it needs DDM's head as a molecule of its own with its own AA topology. The user set it aside 2026-10-05 |
| Phase 4: sucrose and maltose sources | `resources/validation/carbohydrates/targets-v1.json` still carries `availability: metadata_only` for both entries (re-read 2026-10-15); lead is `10.1016/j.carres.2004.12.038`. Deferred by the user 2026-10-05 |
| pdc phase C, the retry half | the contact rule **exists**: `micelle/validation.assess_micelle` builds the tail-bead contact graph, judges the largest cluster against the aggregation number, and reports `protein_contact_count` with its own stated limitation. What does not exist anywhere is a retry policy -- `grep retry` over `pdc_assessment.py`, `pdc_assess.py` and `micelle/validation.py` finds nothing |
| pdc phase D, back-mapping | **paid, and the earlier row was wrong.** CG2AT2 is vendored under `tools/cg2at/` (a clone dated 2026-09-30, `cg2at -> database/bin/cg2at.py`) and `dashboard/execution/scripts/pdc_backmap.sh` drives it; `docs/PROJECT_GUIDE.md:258` says the same. The sentence "CG2AT2 is not vendored yet" described the tree before that clone |
| pdc phase E | documentation; the pdc depth reference is `references/pdc-workflow.md`. Nothing else is claimed open here |
| D1's other half | **paid.** `runs.js:consistencyLine` renders the numbered line -- "Consistency: CG 6 of 6 ring distances inside the AA observed range" -- off the `consistency` field `/api/jobs` already carries, measured on both `aa_cg` runs as `{'compared': 6, 'outside': 0, 'pairs': 6}`. D1 asked for "inside the AA *spread*"; the card says *range* deliberately, because the spread is the cross-molecule comparison on the mapping-validation tab. A browser test pins the line |
| the iterative mapping refinement panel | **cancelled by the user, 2026-10-15.** The human review gate made the workflow more complicated than the decision it supported. No panel is built and no further increment is planned. What was already landed stays: `/api/refinement/reviews`, `/api/refinement/variants` and the `refinement-score` analysis kind, all from 2026-09-24/25, reachable and tested. Deleting them is a separate decision, not implied by this one |
| the micelle builder | paused at the user's request; `micelle/` is a partial skeleton and explicitly not a validated model |
| **no CI** | still no `.github/workflows` -- the path does not exist. Enforcement is `gate_commit.sh`: the script has lived in Hermes's skill directory since 2026-10-12 (and the skill's `references/verification-and-commit-gates.md` documents it), and as of 2026-10-15 the repository carries its own copy at `scripts/gate_commit.sh` (`c6ec468`) so a reader inside the repo can run it. It runs the fast tier and `ruff` over the named paths, stages only those paths, blocks on any finding, and reports the browser tier without gating on it. The browser and slow tiers still run only when named |
| **no coverage signal** | no coverage configuration and no per-line signal on which tests are load-bearing. Unchanged |
| **a mutation signal exists, and it is narrow** | `scripts/mutation_check.py` + `scripts/mutants.json` (`901920a`): 11 mutants confined to `analysis/` and the adapters, 10 caught, 1 survived (the control), about 4 s each. Extending the list is the next work here |
| **property-based tests** | three files landed (`ed5b2ab`): the mapping validator, the term reader and the MDP writer. Still unfuzzed: the published-artifact readers beyond `term_beads`, the export writers, and `pdc_placement`'s geometry |
| a stray mapping candidate | **closed 2026-10-15.** Deleted through `DELETE /api/mappings/drafts/<name>`; a byte-exact copy is kept at `~/.hermes/profiles/moldym/cache/scratch/mapping_candidate_d17dac35a91a40ada85301877e70a7d1.json` (sha256 `4fdb9c92…`) in case the head-only molecule is ever built. 5 candidates remain |

## Closed 2026-10-15
- The gate the "no CI" row named also exists inside the repo as `scripts/gate_commit.sh` (`c6ec468`, parity with the
  skill's own copy in the commit after it), proven refusing a red ruff and landing the commit after that.
- A mutation signal, confined to `analysis/` and the adapters, with a control that survived (`901920a`).
- 29 tests: 28 property tests over the validator, the term reader and the MDP writer, plus the range-boundary test
  the mutation check asked for (`ed5b2ab`, `2791f76`).
- The validator's dead type check, which raised `AttributeError` for a non-dict body instead of the `ValueError` a
  route turns into a 400 (`ed5b2ab`).
- The stray head-only mapping candidate, deleted through the route with a copy kept (`d17dac35…`).
- Three rows of this file that were wrong: D1's numbered line (present), CG2AT2 (vendored), the refinement panel
  (the spec was withdrawn). Two more that had gone stale without being paid: the fast-tier count and the cron
  list.
- Two user decisions, taken on 2026-10-15 after this verification: the scheduled cron drivers were cancelled and
  every mention of them removed; the mapping refinement panel was cancelled and its spec withdrawn.


## Closed 2026-10-12
- The suffix `pyproject.toml` measurement ("79.3 s serial / 19.6 s with these flags") is gone from that file.
- No `skip` remains in the browser tier: it reports no skips at all.
- `config/benchmark.json` and `config/performance.json` are deleted; the launcher flags live in the adapters and the measured benchmark table in the skill reference `aa-run-protocol-and-performance.md`.
- The bead editor's 2D depiction is gone (`aa318e0`), and the bonded panel's wrong-molecule bug is fixed (`c6f018e`).
