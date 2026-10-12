# Handoff and history

State, measurements and open items for this repository. `AGENTS.md` holds the rules; this holds the record they were
derived from. Read it before starting work on the DDM CG chain, the crons or the coordinator.

## Where things stand (2026-10-05, linkage and surfaces work)
Tree clean except untracked reference assets: vendored M3-Lipid duplicates, `.git-upstream/`, the user's PDFs. **The M3-Lipid set stays untracked by the user's instruction. Do not tidy it into the index.** Nothing pushed since pre-refactor baseline `e0504a3`. The branch is 294+ commits ahead of `origin/main`.

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

**`ddm-200ns-chain` (`42fbd11d10c5`, every 30 minutes, no LLM)** waits for it, then queues the CG arm that consumes it as its reference (`mapping_candidate_2bcc24c3e5f149fab1e4f11f5d80ae0e.json`, label "DDM CG from the 200 ns reference (matched sampling), published protocol, 20 ns"). **That arm is the first DDM run whose parameters were fitted from a 200 ns sample.** It either resolves the question or rules the sampling out. The job removes itself once it has acted; that path was exercised for real (created, removed, confirmed absent through `hermes -p moldym cron list`, recreated). Its output is `local`, so read it with `hermes -p moldym cron runs`.

Restart the coordinator after that arm completes. The user asked for this explicitly: the running process still held the Python module from before `cdb2ccc` and `767c90d`, so the linkage card and the envelope card showed their empty states. It was deferred so as not to orphan the 200 ns run's subprocess group; the window between the reference finishing and the CG arm starting is the natural seam. A later session restarted it, and both cards render since.

## The other stages' parameters, reviewed
- The AA half is right. `2321ee23a536` runs 2 fs with C-rescale NPT and then Parrinello-Rahman production at `ref-p = 1`: real pressure coupling at 1 bar, and the guide's 303.15 K for CHARMM36m.
- The CG half's barostat was missing and is fixed (`a20d844`). `cg.py`'s `mdp_integration` used to stamp `pcoupl: 'no'` over both mdps, so every CG production run was NVT with `ref_p` and `compressibility` as dead keys while the manifest recorded `pressure_bar: 1.0`. The templates carry C-rescale to equilibrate and Parrinello-Rahman at `tau_p = 12` to produce, and `cg.py` no longer overrides them. A grep for `pcoupl` in `cg.py` finds only a docstring saying it used to. Verified on arm D, the first arm ever to run the published protocol: mean pressure 1.36 bar against the NVT arms' −583 bar, the box contracting about 9% to the correct density. It failed anyway, and sooner.
- The CG equilibration is 5 fs (`c51e8db`, the user's decision). Same 10 ps as before, so 2,000 steps rather than 500. The template's `dt` decides it, and the adapter reads each file's own `dt` back when it turns the requested duration into a step count. The Martini 3 Methods exclude equilibration from the 20 fs rule without naming a value, so both 10 fs and 5 fs are defensible on the paper's authority. Neither is evidenced to help, which the six arms above show.
- Everything else is standard Martini 3 and matches the reference set: `dt` 20 fs in production, `rlist` 1.35 with `rcoulomb`/`rvdw` 1.1, reaction-field with `epsilon_r` 15, Verlet with `verlet-buffer-tolerance -1`, `nstlist` 20, frames every 10 ps.
- `ff_inter` is fitted at 303 K (`cg.fit_temperature` rounds the run's 303.15 for an int argument) and the thermostats are at 303.15 K, so the fit and the simulation agree.
- `-constraints 10000` (`75029f0`) is Fast_Forward's own default and it matters. A bond fitted above it becomes a rigid constraint, which is how DDM's inter-ring link (fitted at 12964.8) became rigid while maltose's (2985.6) stayed flexible.

## The four crons are quiet, and one of them removes itself
`e3-chain` (`71a071938314`), `ddm-fit-chain` (`b4d8dfb2c7b8`) and `pdc-empty-micelle` (`eecb5a6b759f`) fire every 10 minutes with no LLM. All three print nothing when they have nothing to do, verified by hand with `--verbose` and by reading their tick files; the pdc one used to print a line every tick. All three also read `/api/jobs` unpaged until an earlier session, so `e3-chain` could not see the maltose runs and reported "nothing to do" for a step it never looked at. They page to `total` now. The driver that POSTs a comparison additionally guards on a completed attempt existing, because the analysis memo key moves with any code change and a re-POST would rebuild it every tick.

`ddm-200ns-chain` (`42fbd11d10c5`, every 30 minutes) is the fourth and the only temporary one. A scheduled job recurs forever by default, so it takes itself off the schedule once it has done its one thing, and it reports and removes itself if the reference failed or has written nothing for six hours. A busy queue is the one case it stays for. Removal is `hermes -p moldym cron remove <id>`; **the profile flag is required**, because without it the command targets the default profile's own store and would not find the job. The result is verified against the store, with a loud line naming the command if it did not take.

## The coordinator
`http://127.0.0.1:5000`, concurrency 2 (`config/dashboard.json`), restarted for each Python change. The database holds 38 jobs (13 completed, 25 failed) and 7 saved mapping candidates. Log at `/home/wee/.hermes/profiles/moldym/cache/scratch/coordinator-run.log`.

Worth keeping: the four E3 runs, `2321ee23a536` (the DDM AA reference `dbc366ae772b` supersedes), `8a73fe6448f2` (pdc completed end to end), the six DDM arms above, and the two BARTENDER attempts that produced results (`a2a457cf9413` task `9a0d4e97180a`, `1322f9e0782e` task `f840a2186aaf`). The arms are the record of what was eliminated, so they are evidence even though every one failed. Ignore the failed pdc probes and the two earlier failed DDM `aa_cg` runs from 30 September.

**`8a73fe6448f2`'s system is void for geometry.** It was built while `detergent_cg.bead_centres` divided by ten. Every DDM arm dies before any production sampling, so their coordinates are evidence about the failure and about nothing else.

## Still open
| item | state |
| --- | --- |
| the DDM CG run, Task 2.4 | arm in flight. Six arms failed with a stochastic onset; the six candidate causes above are eliminated. `dbc366ae772b`'s CG arm is the first run whose parameters come from a 200 ns sample, and it is the current test |
| the tail-off control | superseded. It cannot be a mapping edit: the validator refuses a candidate that leaves heavy atoms unmapped ("Missing heavy atoms: 1 ... 12" for the dodecyl chain). It needs DDM's head as a molecule of its own, with its own AA topology. The user set it aside on 2026-10-05 |
| Phase 4: sucrose and maltose sources | `resources/validation/carbohydrates/targets-v1.json` is still `metadata_only` for both; lead is `10.1016/j.carres.2004.12.038`. The user deferred this on 2026-10-05 |
| pdc phases C-E | the pipeline runs end to end and the panel queues it. C is the contact-graph criterion and retry policy, since nothing judges whether the detergents contact the protein. D is back-mapping, the biggest of the three; CG2AT2 is not vendored yet. E is documentation |
| D1's other half | the run card does deep-link the tab with the run preselected, and a browser test pins it. What is missing is the numbered line D1 asked for, "CG 4 of 6 ring distances inside the AA spread", which is a bare button today |
| the iterative mapping refinement panel | README, five planned increments, none started: reference import, controlled variant generation, evidence execution, transparent ranking, human review gate |
| the micelle builder | paused at the user's request; `micelle/` is a partial skeleton and explicitly not a validated model |
| **no CI** | there is no `.github/workflows`. Enforcement is `gate_commit.sh`, a local script that runs the fast tier and ruff on named paths and blocks the commit. The browser and slow tiers run only when named; the gate reports the browser tier on front-end paths (`-n 6`) but does not gate on it |
| **no coverage or mutation signal** | 1,261 fast-tier tests with no signal on which are load-bearing. Mutation testing confined to `analysis/` and the adapters is the high-value use; three mutations on freshly written tests, three caught, in about a minute |
| **no property-based tests** | the mapping-schema validator, the MDP writer and the published-artifact readers are the fuzzable surfaces, including the regex that parses a term's beads (`"(1,A) - (1,B) - (2,A)"`) |
| a stray mapping candidate | `mapping_candidate_d17dac35a91a40ada85301877e70a7d1.json` is the head-only mapping built for the tail-off control. The validator refuses it for DDM runs, so it is inert, but it shows in the candidate picker. Delete it or keep it for the head-only molecule |

## Closed 2026-10-12
- The suffix `pyproject.toml` measurement ("79.3 s serial / 19.6 s with these flags") is gone from that file.
- No `skip` remains in the browser tier: it reports no skips at all.
- `config/benchmark.json` and `config/performance.json` are deleted; the launcher flags live in the adapters and the measured benchmark table in the skill reference `aa-run-protocol-and-performance.md`.
- The bead editor's 2D depiction is gone (`aa318e0`), and the bonded panel's wrong-molecule bug is fixed (`c6f018e`).
