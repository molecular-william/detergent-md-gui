# shaker and taster: what they are, and what adopting them would take

## Status

Assessment, asked for by the user on 2026-10-05: "perhaps the code in these two repos can be used to simplify our
current code", then "let's see what it will take to refactor our code to use shaker". The estimator was not merely
read — it was **run against a real case in this repository**, so the numbers below are measurements.

- `github.com/Martini-Force-Field-Initiative/shaker` — LGPL-2.1, created 2026-02-25, 13 modules, ~160 KB of Python.
  Used here at `b76802192473b9386c9a160c0e9addf90f287cb2` (2026-09-21). 15 open issues, 0 forks.
- `github.com/Martini-Force-Field-Initiative/taster` — LGPL-2.1, created 2026-04-01. Partition coefficients (LogP)
  of Martini 3 small molecules by FEP/TI + MBAR.

## What taster is, and is not

Not a simplification: nothing in this repository computes partition coefficients, so there is nothing for it to
replace. It is a **validation instrument** — a molecule's CG parameters checked against experimental LogP — which is
Phase 4's question (experimental sources, deferred by the user) rather than a refactor. It needs an ITP, which we
have, and a FEP/TI budget. Recorded here so the deferred phase does not have to rediscover it.

## The estimator, measured

shaker's `bonded_estimator` was run on the DDM 200 ns reference's own mapped frames — the same 20,001 frames and the
same ten bead pairs that our Fast_Forward fit used, at the same 303.15 K. Both methods therefore saw identical input.

| pair | our fit | shaker, k<10000 | shaker, k<25000 |
| --- | --- | --- | --- |
| B01-B02 | constraint 0.298794 | bond 0.258 / 7878.5 | bond 0.258 / 7878.5 |
| B01-B03 | constraint 0.399659 | bond 0.349 / 6395.3 | bond 0.349 / 6395.3 |
| B02-B03 | constraint 0.300700 | bond 0.261 / 3655.9 | bond 0.261 / 3655.9 |
| B01-B11 | bond 0.431 / 2716.9 | bond 0.424 / 2424.4 | bond 0.424 / 2424.4 |
| B02-B05 | bond 0.334 / 6372.2 | bond 0.328 / 4055.8 | bond 0.328 / 4055.8 |
| B09-B10 | bond 0.447 / 2823.8 | bond 0.443 / 2464.9 | bond 0.443 / 2464.9 |
| B10-B11 | bond 0.448 / 2884.2 | bond 0.444 / 2423.3 | bond 0.444 / 2423.3 |
| B05-B06 | constraint 0.316070 | constraint 0.271 | constraint 0.271 |
| B05-B07 | constraint 0.424220 | constraint 0.367 | constraint 0.367 |
| B06-B07 | constraint 0.340351 | constraint 0.296 | bond 0.296 / 15515.3 |

Angles, ours against theirs: `B02-B01-B11` 137.802 / 137.71, `B03-B01-B11` 99.100 / 100.90, `B01-B02-B05`
114.080 / 120.22, `B03-B02-B05` 115.308 / 114.45, `B02-B05-B06` 120.452 / 120.45, `B02-B05-B07` 83.737 / 84.03,
`B09-B10-B11` 145.489 / 142.43, `B01-B11-B10` 143.522 / 140.85.

Four things it establishes:

1. **Geometries reproduce; stiffnesses do not.** The inter-ring link lands 0.328 against our 0.334 nm (2% apart) and
   six of eight equilibrium angles agree within about 1%. The force constants differ 2–3× in **both** directions —
   expected, because shaker estimates each term independently from its own histogram (equipartition, inverted
   Boltzmann) and its own docstring calls the result *initial* parameters, while Fast_Forward does a coupled
   distribution-matching fit. Complementary, not equivalent.
2. **It independently confirms the ring-scale finding.** Our ring constraints are the draft geometry × 1.15, not a
   fit; shaker *measures* the same pairs and reads them 0.03–0.06 nm shorter — the same direction and roughly the
   same size as `draft_geometry.py` found internally (6.4–20%, median 16.1%).
3. **It questions our ring 1.** Its k values for B01-B02 / B01-B03 / B02-B03 are 7878 / 6395 / 3656 — below both
   thresholds, so flexible bonds, where we write all six ring pairs as constraints. For ring 2 we agree (k
   15515–153646). Worth investigating, given rigidity is the thread the DDM arms kept pulling.
   **Independently reproduced on 2026-10-05 by this repository's own adapted estimator** on the same 20,001 frames:
   8903 / 7562 / 3775, free, with the same three pairs named — see the cross-check plan's Task 3.2, whose worst
   disagreement against shaker across all ten pairs is 3.9 pm in length and 18% in force constant.
4. **The threshold is in the signature**: `constraint_threshold=25000` by default against our 10000. Under their
   default, DDM's link at the time (fitted 12964.8) would never have become a constraint.

## Area by area: what a refactor would take

| area | shaker | ours | verdict |
| --- | --- | --- | --- |
| Map AA trajectory → CG | `map_aa2cg`, centre of geometry, dict mapping keyed by **atom names** | `ff_map -mode COG` **plus** `finalize_mapping.py` (46 lines) **plus** our own `sugar_mapping.py` (90 lines, MDAnalysis) | **no.** Our mapper does COG *and* ring expansion *and* inter-ring link reconstruction, which shaker has no concept of. Ours is a superset of theirs |
| Write initial topology | `write_initial_CGitp`: `[ moleculetype ]` + `[ atoms ]`, `TYPe` placeholder when untyped | `models/bonded/generation.py`, 754 lines: 26 terms with per-term provenance, ring constraints from the draft geometry, exclusions, virtual sites | **no.** Theirs is a strict subset; adopting it would lose the provenance rule the whole model rests on |
| Run a simulation | `runSim`: bundled MDPs, `maxwarn=1`, hardcoded `-pin on -nt 8`, CWD outputs, and `cleanOldRun=True` which **deletes previous runs' files** | the stage/manifest/cancellation layer | **no, and our rules already say so**: "Never silently overwrite runs", "Do not delete simulation data during cleanup", "one local Python orchestration service and subprocess-based GROMACS jobs with persisted manifests and logs" |
| Compare distributions | `measure_bonded_terms` + `plot_bonded_distributions` | `distance_diagnostics.py` (109), `mapping_consistency.py` (120), `transferability.py` (185) | **partial yes.** The measurement function is clean and fast (20,001 frames × 10 pairs in ~2 s); the plots are notebook-shaped and our panel is not |
| Assess model quality | `assess_overlap_matrix`: AA-vs-CG intra-bead distance overlap coefficients with Martini 3 tolerance checks | nothing equivalent | **yes — the one genuine add.** It is the quantitative version of the internal consistency this repository already privileges |

## The dependency shape that governs every area

`import shaker` pulls **all thirteen modules**: `shaker/__init__.py` imports `render` (→ `nglview`, the Jupyter
widget this repository already decided against) and `render_2d` (→ `rdkit`). A single function therefore costs the
whole stack. That is not a reason to refuse it; it is a reason to add it the way the repository already adds
things: **its own virtualenv, declared in `config/tools.json`, resolved by `execution/tools.py`, invoked as a
subprocess, pinned by commit and recorded in each run's tool report** — never imported into `dashboard/.venv`.

Two decisions are the user's and not mine:

- **Licence.** Both are LGPL-2.1 and this repository has **no LICENSE file at all**. Using them as a separately
  installed tool is one question; vendoring them under `tools/` the way `bartender` and `cg2at` are vendored is
  another, with different obligations.
- **Whether a second tool environment is worth its operational cost** for one analysis. The repository already
  carries Fast_Forward's, so the pattern exists; the question is whether this earns a second one.

## What I recommend, in order

1. **Add the overlap analysis.** Net-new, published method, and it fits the analysis framework exactly: immutable,
   attached to a completed source run, referencing the trajectory it read. It would have caught ring 1.
2. **Add a bonded cross-check analysis** built on `measure_bonded_terms` + `bonded_estimator`, reporting our fitted
   value against shaker's per term, with the commit, the temperature and both thresholds in the report. The
   experiment above is its prototype — it is what makes the ring-1 question visible without anyone re-deriving it.
3. **Do not adopt** `map_aa2cg`, `write_initial_CGitp` or `runSim`, for the reasons in the table.
4. **The readability win is already in our own tree — DONE, `b35063e`.** `map_trajectory.sh` branched on a *file's
   existence*: `if [ -f sugar_mapping.py ]` ran our mapper, else `ff_map` followed by a 46-line script. The branch
   that called `ff_map` never executed, which the run record proves rather than suggests: all 18 CG runs in this
   workspace had `sugar_mapping.py` present, none wrote `mapped_raw.xtc`, and every one recorded
   `max_coordinate_error_nm: 0`. So one mapper stayed and the other path was deleted, with the frame times, boxes and
   mapping-validation record that the deleted script also carried already being written by the mapper. The
   independent COG check was not deleted with it -- it lives in `validate_run.py`, a different script, which
   reconstructs every bead from the AA coordinates and fails the mapping above 0.002 nm. What went with the branch
   was also a false requirement: readiness no longer demands `ff_map` as a tool, since nothing invokes it. The
   rings-less mapping, which only the deleted branch ever served, now has five tests against hand-computable
   centres of geometry. The stage was named after the tool it used to call, so it was renamed too (`1c6c0fa`), with
   the 21 runs that recorded the old name keeping their own words and their shared abbreviation.

## Open

- The experiment's scripts, venv and pinned clone live in
  `~/.hermes/profiles/moldym/cache/scratch/shaker-exp/`; both estimator runs re-execute in about two seconds each.
- Nothing here has been measured on the *angles* as a fit: only the equilibrium values were compared, and the
  force-constant disagreement is not yet explained beyond the method difference.
- taster's internals were read from its README and repository metadata only, not exercised.
