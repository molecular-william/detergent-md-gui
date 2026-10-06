# The concentration-series builder: osmotic pressure for a carbohydrate

**Status:** planned, not started. Written 2026-10-06, after finding that maltose already carries 200 ns of AA *and* CG
sampling (20,001 frames per leg, `dt 0.002 x 100,000,000` and `dt 0.02 x 10,000,000`), so the geometry leg is already
data-ready and this builder is what stands between us and the paper's third leg.

## The method, as the paper states it

Quoted from the paper, because four of its numbers replace choices this plan had made on its own authority, and it is
the record we build against:

> A rectangular box was created in which the solute molecules were confined in the z-direction by a flat-bottomed
> potential to the center of the box. At a distance of 2.52078 nm from the center of the box, a harmonic force with a
> force constant 1000 kJ/nm2 was applied to the solute molecules. The box dimensions were taken to be 10.08312 nm in
> z-dimensions and 5.04156 nm in x and y. Previous to each run, a random configuration of solute and solvent molecules
> was created with polyply placing solute molecules only in the center of the box and the solvent in the entire box.
> After energy minimization, this setup was subjected to a 10 ns equilibration using a Berendsen barostat. Production
> simulations were run for 500 ns ... at a pressure of 1 bar. The temperature matched the temperatures reported with
> the experimental data sets. Following Sauter and Grafmuller, the pressure was coupled only in z-dimensions. The
> osmotic pressure was computed from the trajectory by recalculating the total force exerted by the solute particles
> onto the flat-bottomed potential averaged over the two potentials. Subsequently that force is divided by the xy area
> of the box. The ensemble average as well as an error were computed from the time-series of the osmotic pressure.

What it fixes, in numbers:

| quantity | value | consequence here |
| --- | --- | --- |
| box | z 10.08312 nm, x = y 5.04156 nm | **fixed for the whole series**, so the dividing area is one number for all six conditions: 5.04156^2 = **25.4173 nm2** |
| confinement | flat within 2.52078 nm of the centre, harmonic 1000 kJ/mol/nm2 beyond | 10.08312 / 4 = 2.52078 exactly, so the walls sit at the quarter box |
| temperature | matched to the experimental dataset | **308.15 K** for maltose, from Ebrahimi & Sadeghi 2016 -- not this repository's 303.15 |
| build | solute in the centre only, solvent everywhere, placed with polyply | our placement code does this; polyply is not vendored, and that substitution is recorded rather than hidden |
| equilibration | 10 ns with a Berendsen barostat | not this repository's CG equilibration, which is v-rescale |
| production | 500 ns at 1 bar, pressure coupled only in z | the bar |
| the force | **recomputed from the trajectory**, averaged over the two potentials, divided by the xy area | the analysis needs z-coordinates, the two constants and the area -- **not** the pull machinery |
| the error | from the time series | a block average or the standard error of the mean over the production window, stated either way |

**Two decisions this plan made are superseded, and are left visible rather than deleted.** It chose a fixed water bead
count with the solute count derived and a box that follows; the paper fixes the box and lets both counts follow. And
it had the analysis read the pull force from the `.edr`; the paper recomputes it from the trajectory, which is both
faithful to the method and independent of how the restraint was applied -- which is why Task 0.1's verified answer
simplifies the analysis rather than enabling it. Task 1.1's arithmetic and Task 2.1's source are corrected below.

## Why this exists, and what the paper asks for

Grunewald et al. (JCTC 2022, `10.1021/acs.jctc.2c00757`) compares Martini 3 osmotic pressures against experiment for
eight monosaccharides and two disaccharides over **0-2.5 molal**, using a method that:

1. confines the solute near the centre of a large box with a **flat-bottomed potential**;
2. couples pressure **only in z**;
3. takes the osmotic pressure as the **mean restraining force divided by the xy area**;
4. samples **500 ns per condition** (Methods 5.3).

The repository has the analysis side of this -- `dashboard/analysis/validation/osmotic.py` already holds
`REQUIRED_MOLAL = (0.0, 0.5, 1.0, 1.5, 2.0, 2.5)`, `pressure_from_force(force_kj_nm, area_nm2)`, `validate_series` and
`run` -- and none of the system side. Card 4 ("Solution behaviour") has said so in its own words since it was written:
"Osmotic pressure and transfer free energy need a concentration-series system builder and a second solvent leg;
neither exists yet." This plan builds the first of those two.

The measured target for maltose is ready and verified against the source's own numbers (Task 0.3).

## Design decisions, so they can be argued with rather than discovered

**One job per concentration, not one job per series.** The coordinator's unit is a job with a manifest and a terminal
status, and the 500 ns requirement is *per condition*. Six concentrations as six jobs means they queue two at a time
under the existing concurrency limit, fail independently, and carry their own duration in their own manifest. What
ties them together is a `series_id` string in the payload, which is a new manifest field and nothing more.

**The water count is fixed and the solute count follows.** Molality is moles of solute per kilogram of *water*, so a
box with a fixed solute count and a floating water count cannot express a requested molality at all. Build the box
from a fixed water bead count at the target density, then derive the solute count from the molality. The six boxes are
therefore slightly different sizes, which is the paper's own arrangement.

**The dividing area is recorded in the manifest, not recomputed later.** `pressure_from_force` needs the xy area, and
that area comes from the box the builder made. Recomputing it from the trajectory means two places could disagree
about the same number; recording it at build time means the analysis divides by exactly what was built.

**The restraint is GROMACS's own flat-bottom pull.** Its force is written to the `.edr`, which is the whole reason to
prefer it over a hand-rolled harmonic restraint whose force would have to be reconstructed as `k * dz`. **Task 0.1 settles it
against the installed build before anything else is written**, because the entire measurement design depends on the
answer -- and it has now settled it in the pull code's favour; see that task's result.

## Phase 0 -- verify before building

### Task 0.1: does the installed GROMACS accept a flat-bottomed pull restraint?

**Objective:** decide the restraint mechanism from the tool's own behaviour, not from memory.

**Files:** a scratch mdp in the session's scratch directory; no repository change.

**Step 1:** build the smallest possible grompp input -- a three-atom `[ moleculetype ]`, a `[ system ]`, a matching
`.gro` -- with `pull = yes`, two pull groups, `pull-coord1-geometry = distance`, `pull-coord1-type = flat-bottom`,
`pull-coord1-init = 1.0`, `pull-coord1-rate = 0`.

**Step 2:** run `gmx grompp`. Three outcomes, each of which decides something:

| outcome | meaning | consequence |
| --- | --- | --- |
| grompp succeeds | flat-bottom pulls are available | the restraint is the pull code, and its force is in the edr |
| "Unknown pull type" or similar | the keyword does not exist | fall back to a `[ position_restraints ]` flat-bottom in z, whose force is reconstructed as `k * max(0, z - z0)` per bead, and **say so in the report** |
| it fails for a missing group or topology instead | the keyword parsed | treat as available, and confirm on the first real build |

**Step 3: the answer, measured.** Run on 2026-10-06 against the build in use,
`/usr/local/gromacs/2026.3/bin/gmx`, with a three-atom topology, an index file naming two pull groups, and
`pull-coord1-type = flat-bottom`, `pull-coord1-init = 0.5`, `pull-coord1-rate = 0`:

```
$ gmx grompp -f probe.mdp -p probe.top -c probe.gro -n probe.ndx -o probe.tpr -maxwarn 5
Pull group  natoms  pbc atom  distance at start  reference at t=0
       1         1         0
       2         1         0       0.200 nm          0.500 nm
... 2 NOTEs, exit 0, probe.tpr written
```

**So the restraint is the pull code**, and the fallback above is not needed. Three consequences for what follows:

- the restraint force is the flat-bottom's own, reconstructible from the pull distance the `.edr` carries ("Pull coord
  1") together with `pull-coord1-k` and `pull-coord1-init` -- so Task 2.1 reads a distance, not an undocumented field;
- **grompp echoes the reference distance at t=0**, which is where the builder's applied restraint can be read back and
  recorded in the manifest rather than assumed;
- a two-group pull needs an index file, so the builder owns the index it writes. The analysis must not guess group
  ordering from the topology.

The probe is at `/home/wee/.hermes/profiles/moldym/cache/scratch/osmotic-probe/` (top, gro, ndx, mdp) and re-runs in
about a second. It is a scratch probe rather than a test because it asks about the installed build, not about this
repository's code -- the same reason the estimator's pinning against shaker's numbers was an experiment.

**Commit:** none. This is a measurement, and it belongs in the plan's record.

### Task 0.2: the paper's own method, read rather than recalled

**Files:** `docs/research/2026-09-24-martini3-carbohydrate-validation.md` (already holds the method summary).

The method note records the protocol but not the restraint's geometry -- whether the flat bottom acts along z alone or
confines a cylinder. The paper's Methods 5.3 (printed p. 7565) and, if needed, the SI's osmotic-pressure section have
it. **Read them before Task 1.2**, because the geometry decides whether the dividing area is the whole xy face or the
cross-section of a cylinder, and `pressure_from_force` assumes the former.

### Task 0.3: the maltose target, ready and verified

**Files:** `resources/validation/carbohydrates/targets-v1.json` (add a maltose dataset), `targets.py` (a kind).

Source: Ebrahimi & Sadeghi, *Osmotic properties of carbohydrate aqueous solutions*, Fluid Phase Equilibria 417 (2016)
171-180, `10.1016/j.fluid.2016.02.030` -- vapor pressure osmometry at 308.15 K. Its equation 8,
`Phi = 1 + A1 m + A2 m^2 + A3 m^3 + A4 m^4 + A5 m^5`, with maltose monohydrate's coefficients
`0.024829, 0.077617, -0.117831, 0.065921, -0.011698` and `sigma = 0.0031`, evaluated through
`pi = -(R T / V_w) ln a_w` with `ln a_w = -Phi m M_w`:

| m (mol/kg) | 0.0 | 0.5 | 1.0 | 1.5 | 2.0 | 2.5 |
| --- | --- | --- | --- | --- | --- | --- |
| pi (bar) | 0.00 | 13.04 | 26.54 | 40.58 | 56.09 | 72.72 |
| +/- (bar) | 0.00 | 0.04 | 0.08 | 0.12 | 0.16 | 0.20 |

**Three checks, because a converted number is a derived number.** The two independent routes to pi (`V_w = 18.07
cm3/mol` and `rho_w = 994.03 kg/m3`) agree to 0.30%. The calculated `a_w` reproduces the paper's own *measured* `a_w`
column to +/- 0.00004 (at m = 0.4474 the paper prints 0.9918 and the calculation gives 0.99182). And equation 8
reproduces the printed `Phi` to within +/- 0.0015 across the six required molalities, inside the fit's own sigma.

**The uncertainty is the paper's stated fit sigma**, propagated as `pi * sigma / Phi`. The VPO measurement's own
per-point error is not given as a standard deviation in the sections read, so none has been invented. **A reader who
wants the measurement error will find it in the paper's tables, not in this repository.**

**The gap this leaves:** `targets.py`'s `ALLOWED` set has no osmotic kind, so the value cannot be registered as a
target yet -- but `osmotic.py` takes `target_pressure` and `target_uncertainty` per point from the payload, and
`validate_selection` checks only that a dataset exists and carries a citation. So the numbers are usable today and
become citable when this task adds the kind.

**Step 1 (failing test):** `test_a_maltose_osmotic_target_is_citable_and_reaches_the_leg`.

**Step 2:** add `osmotic_pressure` to `ALLOWED`; add a `maltose-osmotic-ebrahimi-2016` dataset carrying the six points
as `value`/`uncertainty` with the conversion stated in `conditions` and the DOI in `citation`.

**Step 3:** commit. `feat:` -- the osmotic target exists and is citable.

## Phase 1 -- the builder

### Task 1.1: the box, from a molality

**Objective:** one concentration in, one solvated system out, with the water mass fixed.

**Files:**
- Create: `dashboard/execution/adapters/osmotic_box.py`
- Reuse: `dashboard/execution/scripts/pdc_solvate.py` and `dashboard/execution/adapters/pdc_placement.py`
- Test: `tests/dashboard/unit/test_osmotic_box.py`

**A correction this task needed before it could be written.** The first version of this plan pointed at
`composition.py` for the counting. That is the wrong module: `composition.py` is a protocol wrapper (`STAGE_DEFS`,
`prepare_run`, `VERSION = 'cg-composition-v1'`) and holds no counting arithmetic at all. The repository's real
placement and solvation machinery is `dashboard/execution/scripts/pdc_solvate.py` together with
`dashboard/execution/adapters/pdc_placement.py`, built for the PDC work and shaped for exactly this: solvent
everywhere, solute placed deliberately.

**And the water constant must be read, never recalled.** Whether a Martini water bead is three waters or four decides
the bead's volume, and therefore the water count in a fixed box, and therefore every molality in the series. The mass
is not in the solvents itp's `[ atoms ]` block -- that block names the type `W` and nothing more -- it is in the
`[ atomtypes ]` of `martini_v3.0.0.itp`. Read it there and record it as a named constant with the file it came from,
the way `RADII_NM` records where the bead radii came from. Recalling it is how a series ends up at the wrong
concentration with every internal check still passing.

**The arithmetic, corrected to the paper's fixed box:**

```
V_box      = 10.08312 * 5.04156**2              = 256.32 nm3    the paper's box, fixed for every condition
area       = 5.04156**2                         = 25.4173 nm2   the same divisor for all six
n_water    = (V_box - V_solute) / v_water        v_water from the bead's mass at the target density
n_solute   = requested_m * (kg of water in n_water) * N_A
achieved_m = n_solute / (kg of water)            recorded beside the requested one, always
```

**Step 1 (failing tests):** the box is the paper's three dimensions and the area is 25.4173 nm²; a requested 1.0 molal
gives a solute count whose *achieved* molality recomputes to 1.0 within a bead; doubling the requested molality
doubles the solute count and leaves the water count alone; a molality outside 0-2.5 is refused with the bound named;
a water bead count that cannot reach the requested molality at all is refused rather than silently rounded.

**Step 2:** implement, refusing a non-positive water count, a molality outside the paper's range, and a density that
would put the box below the cutoff.

**Step 3:** commit. `feat:` -- a box for one concentration.

### Task 1.2: the restraint and the mdp set

**Files:**
- Create: `dashboard/execution/adapters/osmotic_mdp.py`
- Test: `tests/dashboard/unit/test_osmotic_mdp.py`

Three mdps per condition -- minimization, equilibration, production -- differing from the CG half's in exactly three
ways, each of which is the method rather than a preference:

- **pressure coupling is semiisotropic with the xy compressibility zero**, so only z is coupled. This is the
  mechanism; `cg.py`'s `pcoupltype` must not be reused wholesale.
- **the restraint is the mechanism Task 0.1 settled**, applied to the solute's beads, and it is written by this
  module so the analysis can read back what was applied.
- **the production length is a parameter with the paper's 500 ns as its default**, not a constant, because a setup
  check must be able to run 5 ns of the same system.

**Step 1 (failing tests):** the xy compressibility is zero and the z one is not; the restraint block names the
mechanism Task 0.1 chose; `nsteps * dt` equals the requested duration in ps; an equilibration mdp keeps a thermostat
and a barostat; the production interval divides the duration exactly.

**Step 2:** implement.

**Step 3:** commit. `feat:` -- the osmotic mdps say what the method is.

### Task 1.3: the run

**Objective:** the series is a family of ordinary jobs, and each one is reproducible from its own manifest.

**Files:**
- Create: `dashboard/execution/adapters/osmotic.py`
- Modify: `dashboard/execution/stages.py` (the new run type), `dashboard/execution/adapters/__init__.py`
- Test: `tests/dashboard/unit/test_osmotic_adapter.py`

**Stages:** `build` (Task 1.1 + 1.2), `solvate`, `ions`, `minimize`, `equilibrate`, `produce`, `assess` -- the last
running `gmx energy` for the restraint force and the box's volume, and writing `assess.json` with the force, the area,
and the pressure `pressure_from_force` gives.

**The manifest carries:** the molality, `series_id`, the fixed water bead count, the derived solute count, the recorded
xy area, the restraint mechanism and its parameters, the resolved GROMACS path and build, and the exact commands.
Every one of those is what the analysis needs to divide a force by an area and be believed.

**Step 1 (failing tests):** a queued build records the molality and the area in the manifest; the stage list matches
`STAGES`; a condition whose production is shorter than 500 ns is accepted but marked in the manifest as short of the
paper's bar rather than refused.

**Step 2:** implement.

**Step 3:** commit. `feat:` -- the osmotic series runs as jobs.

### Task 1.4: queue the series

**Files:**
- Create: `dashboard/web/routes/osmotic.py` (`POST /api/osmotic/series`), registered in `dashboard/web/routes/__init__.py`
- Test: `tests/dashboard/integration/test_osmotic_api.py`

**One call, six jobs.** The route takes a molecule, a mapping, a representation, a duration per condition and an
optional tier, and queues one job per `REQUIRED_MOLAL`, all sharing a `series_id` the route generates. It validates
the molecule and the representation the way `queue_analysis` validates a carbohydrate validation -- refusing before
queueing, with the reason -- and returns the six job ids.

**Step 1 (failing tests):** six jobs for six molalities, all with the same `series_id`; a molality list outside
`REQUIRED_MOLAL` leaves the missing ones named in the refusal; an unknown molecule is refused before anything queues.

**Step 2:** implement.

**Step 3:** commit. `feat:` -- the series can be queued in one call.

## Phase 2 -- the analysis, which is mostly already written

### Task 2.1: read the force and divide

**Files:**
- Modify: `dashboard/analysis/validation/osmotic.py` (`run`), `dashboard/analysis/worker.py` (a kind, four places)
- Test: `tests/dashboard/unit/test_osmotic_analysis.py`

`run` already takes points and compares a measured pressure with a target. What it does not do is find the force: it
needs `assess.json` from Task 1.3 and the recorded area from the same run's manifest, and it must refuse to divide a
force by an area that came from a different run.

**The four registration places, learned the hard way in this repository:** `KINDS`, `PATTERNS`, `DESCRIPTIONS`, and the
dispatch arm with its own module import. A kind missing the fourth is accepted by the queue and then produces nothing.

**Step 1 (failing tests):** a force from a run and an area from a different run are refused with both ids named; the
residual is the measured minus the target; a target with no uncertainty is refused rather than compared.

**Step 2:** implement.

**Step 3:** commit. `feat:` -- the osmotic pressure is measured and compared.

### Task 2.2: the series, as one picture

**Files:**
- Modify: `dashboard/analysis/validation/report.py` (a series roll-up), `dashboard/web/views.py`
- Test: `tests/dashboard/unit/test_osmotic_series_report.py`

Six reports are six numbers; the leg is a curve. The roll-up takes every completed job with one `series_id`, orders
them by molality, and reports the pairs with their residuals **and the two conditions the paper's own discussion
names**: agreement is good below roughly 1.5 molal and deviates above it, and lower-than-experimental pressure means
excessive self-aggregation. A reader who sees one number without the other has been told less than the paper says.

**Step 1 (failing test):** a series missing a concentration reports which one, rather than drawing a curve through the
gap; a series with all six reports them in molality order.

**Step 2:** implement.

**Step 3:** commit. `feat:` -- the series is one comparison.

## Phase 3 -- the dashboard, which is the question being asked

How it fits, concretely, in the four places a user meets it:

| where | today | after this plan |
| --- | --- | --- |
| **New Run** (`dashboard.html`, `runs.js`) | profiles `standard`, `draft-smoke`, `draft-smoke-reference`, `aa-200ns` | a fifth: `osmotic-series`, with the molality set and the per-condition duration as the two parameters it exposes |
| **The run list** | one row per job | one row per job, with the six sharing a `series_id` shown grouped, so a series reads as one experiment rather than six |
| **Card 4, Solution behaviour** | a `blocked` badge and the sentence "a concentration-series system builder and a second solvent leg; neither exists yet" | the osmotic half becomes real: the curve, the paper's points, the residuals, and the 500 ns bar stated per condition |
| **The validation queue** | `POST /api/jobs/<id>/carbohydrate-validation`, tier `setup` or `evidence` | unchanged, plus the osmotic evidence tier refusing a series whose conditions are short of 500 ns, with the short ones named |

**Task 3.1: the run type in the form.** Modify `runs.js`, `dashboard.html`, `tests/dashboard/browser/test_runs_form_browser.py`. Tests first: the profile appears with its parameters; a molality outside the set is refused at the form with the bound named; a queued series reports how many jobs it made.

**Task 3.2: the card.** Modify `mapping-validation.js`, `dashboard.html`, `tests/dashboard/browser/test_mapping_validation_browser.py`. Tests first: with a complete series the card draws the curve with the paper's points and names the 1.5 molal caveat; with a partial series it names the missing concentration and draws nothing through the gap; with no series it says so in the card's own sentence rather than a blank frame.

**Task 3.3: the documentation.** Modify `docs/research/2026-09-24-carbohydrate-validation-operations.md` (the procedure and the state block), this plan (each task's measured numbers), and `CREDITS.md` if any of the above reuses a method.

## What this plan does not do, and says so

- **The second solvent leg.** Transfer free energy needs water *and* octanol and 19 lambda windows. It is the other
  half of card 4 and it is not in this plan.
- **The maltose partition free energy.** Still missing from the literature; without it the transfer leg cannot be
  compared with anything, no matter how the systems are built.
- **Any claim about the model.** A completed series proves the calculation ran. Agreement with the paper is evidence
  about Martini 3's maltose parameters and about our mapping of them, and disagreement is evidence about both at once
  -- which is why the report states the mapping it used and the two conditions above.
- **A 200 ns CG run.** Maltose has one (20,001 frames). If a shorter one is ever validated, the geometry leg's bar is
  the thing that fails, not the osmotic leg's.

## Verify

```
dashboard/.venv/bin/python -m pytest -m 'not browser and not slow' -q     # the fast tier
dashboard/.venv/bin/python -m pytest -m browser -q -n 2                   # the browser tier
dashboard/.venv/bin/python -m ruff check dashboard tests                  # F, E9, I must exit 0
```

Every commit in this plan runs through `gate_commit.sh`, which is what enforces the first and third by refusing the
commit rather than by being remembered.
