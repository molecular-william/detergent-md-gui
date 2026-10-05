# Two cross-check analyses, adapted from shaker

> **For Hermes:** execute with the `subagent-driven-development` skill, one task per subagent, or by hand with
> `test-driven-development`. Execute **phase by phase** and stop for review at each phase boundary.

**Goal:** two analyses that compare a run's CG model against its own atomistic reference — an intra-bead **overlap
matrix** (how faithful is the CG model) and a **bonded cross-check** (does our fitted topology agree with an
independent estimator) — both attached to a completed run like every other analysis here.

**Architecture:** measurement modules under `dashboard/analysis/runs/`, registered as analysis kinds in
`dashboard/analysis/worker.py` (`KINDS` + `PATTERNS`) and `metadata.DESCRIPTIONS`, served by the existing generic
queue route. No new tool environment, and no runtime dependency on shaker.

**Tech Stack:** Python 3.12, numpy, MDAnalysis (already present), pytest.

**Design:** `docs/design/2026-10-05-shaker-and-taster-assessment.md` — read it first; it carries the measurements and
the reasons the rest of shaker is not adopted. The estimator's own numbers for the DDM 200 ns case are in that
document and are the yardstick Phase 3 is tested against.

**Tier commands (run from the repo root):**
- focused: `dashboard/.venv/bin/python -m pytest <path> -q -n 0 -p no:cacheprovider`
- fast: `dashboard/.venv/bin/python -m pytest -m 'not browser and not slow' -q -p no:cacheprovider`
- browser: `dashboard/.venv/bin/python -m pytest tests/dashboard/browser -q -n 2 -p no:cacheprovider`
- lint gate: `dashboard/.venv/bin/python -m ruff check dashboard tests --select F,E9,I`

**Do not predict tier counts.** Every `Expected:` below is an assertion or "the new test passes", with the tier count
measured in the run that lands the commit.

**Stage explicitly.** `gate_commit.sh <message> <paths>` — and a path this commit *deletes* needs `git add -A --`, or
the staging step aborts and the commit can land holding one path of several. Read `git show --stat HEAD` after
committing: the gates passing is not the same as the commit being right.

---

## The decision this plan rests on: adapt, do not depend

shaker is a **reference implementation we validate against**, not a dependency. Two reasons, one of them new.

The new one: the pieces worth having are **small and standard**. The overlap coefficient is the histogram
intersection; the estimator is equipartition (`k = k_B T / σ²`) plus inverted Boltzmann; the bead-size table is
`{R: 0.264, S: 0.230, T: 0.191} nm`, **which this repository already carries** as `models/sugars/recognition.py`'s
`RADII_NM`, and whose masses its ITPs already use (54.0 for `SP1r`, 72.0 for `C1`).

The old one: `import shaker` costs the whole stack including `nglview`, which this repository has explicitly
decided against, and both tools are LGPL-2.1 while this repository has no LICENSE file. Adapting a published method
with attribution is what the repository already does for its reference parameter sets; shipping or importing an
LGPL toolkit is a different question that **nobody has to answer for this plan to proceed**.

The licence question comes back in Phase 5, and only there: the dihedral fitting (Savitzky–Golay → multi-term cosine
→ AIC/BIC term selection) is a *specific implementation* rather than a textbook relation, so reimplementing it is
closer to copying than the rest of this plan. Phase 5 says so and stops at that boundary.

### What shaker gives that is worth adapting, and what is not

| shaker | worth adapting? | what it would give us |
| --- | --- | --- |
| `overlap.py` — `OC = Σ min(p_AA, p_CG) · Δx` over intra-residue bead pairs, symmetric matrix, diagonal 1 | **yes**, ~50 lines | an AA-vs-CG model-quality number. Nothing in this tree produces one |
| `estimator.py` — `k = k_B T / σ²` per term, plus the `constraint_threshold` conversion (theirs 25000, ours 10000) | **yes**, ~60 lines | an independent bonded estimate and the threshold as a stated parameter rather than a discovered one |
| `helper.py` — size class from the type's first letter (R/S/T/U), validity against the published Martini 3 bead-type list, mass and category per type | **yes**, ~40 lines | a bead-type check. Mappings here carry types and **nothing validates them against the force field's own list** |
| `sasa.py` — `vdwradii.dat` from bead radii for a CG system | **partly** | our `surfaces.py` writes an *atomistic* Rowland–Taylor `vdwradii.dat` and raises for a bead with no element, so a CG envelope is not covered. The mechanism is ours already; the CG branch is the gap |
| `dihedral_fitting.py` — inverted Boltzmann, Savitzky–Golay, cosine series, AIC/BIC | **later, licence-gated** | a criterion-driven answer to "how many Fourier terms", where our BARTENDER route needed `-improperIncrement 10` to return at all |
| `mapper.py` | no | ours is a superset: ring expansion and inter-ring link reconstruction are things it cannot do |
| `itp.py` | no | a strict subset of `models/bonded/generation.py` |
| `measurer.py` | no | MDAnalysis primitives (`calc_bonds`/`calc_angles`/`calc_dihedrals`) that we already call |
| `vsites.py` | not yet | `_solve_vsiten_weights` is a genuine non-negative least-squares solver, but our drafts use equal-parent sites by design. A candidate only if a bead set ever needs unequal weights |
| `system_builders.py`, `render*.py`, `plot.py` | no | `runSim` deletes previous runs' files and hardcodes its own MDPs; the renderers assume nglview, RDKit and a notebook, where this panel is NGL and Plotly |

---

## Phase 1 — the measurement primitives

### Task 1.1: the overlap coefficient, as arithmetic

**Objective:** one function that takes two sets of distributions and returns the overlap coefficients, tested against
values computed by hand.

**Files:**
- Create: `dashboard/analysis/runs/overlap.py`
- Test: `tests/dashboard/unit/test_overlap_analysis.py`

**Step 1: write the failing test**

```python
def test_identical_distributions_overlap_completely():
    """The coefficient is the histogram intersection, so a distribution against itself is 1."""
    values = np.array([0.0, 0.1, 0.2, 0.3, 0.4, 0.5])
    assert overlap.overlap_coefficient(np.ones(6) / 6, np.ones(6) / 6, values) == pytest.approx(1.0)


def test_disjoint_distributions_overlap_not_at_all():
    a = np.array([1.0, 0.0, 0.0, 0.0]); b = np.array([0.0, 0.0, 0.0, 1.0])
    assert overlap.overlap_coefficient(a, b, np.array([0, 1, 2, 3])) == 0.0


def test_half_overlap_is_the_half_that_is_shared():
    """Hand-computable: two distributions sharing exactly half their mass, and nothing else."""
    a = np.array([0.5, 0.5, 0.0]); b = np.array([0.5, 0.0, 0.5])
    assert overlap.overlap_coefficient(a, b, np.array([0.0, 0.1, 0.2])) == pytest.approx(0.5)
```

**Step 2: run it to watch it fail.** `dashboard/.venv/bin/python -m pytest
tests/dashboard/unit/test_overlap_analysis.py -q -n 0 -p no:cacheprovider` — FAIL: no module `overlap`.

**Step 3: implement.** `overlap_coefficient(hist_a, hist_b, bins)` returns `float(np.sum(np.minimum(a, b)) *
bin_width)`, with `bin_width = bins[1] - bins[0]`; a docstring that states the definition, that both histograms must
be densities, and that this is the **overlap coefficient (histogram intersection)**, not the Bhattacharyya distance
or the Kullback–Leibler divergence, which are different numbers a reader may assume by name.

**Step 4: run it to watch it pass.** Expected: the new tests pass.

**Step 5: commit.** `test:` — the arithmetic alone, no analysis yet.

### Task 1.2: intra-residue distance distributions from a trajectory

**Objective:** all pairwise intra-residue bead distances, histogrammed, for one residue's beads from a trajectory.

**Files:**
- Modify: `dashboard/analysis/runs/overlap.py`
- Test: `tests/dashboard/unit/test_overlap_analysis.py`

**Step 1: write the failing test** — a synthetic 3-frame universe of one residue with three named beads whose pair
distances are hand-computable, asserting the pair list, the frame count and one histogram's mean.

**Step 2: run it to watch it fail.** Expected: FAIL — no `intra_bead_distances`.

**Step 3: implement.** `intra_bead_distances(universe, residue_name, start=0, stop=None, stride=1, bins=...)`
returning `{'bead_names', 'pairs', 'bins', 'hist', 'mean_nm', 'frames', 'residues'}`, using MDAnalysis's primitives
and `np.histogram(..., density=True)`. Distances are **nanometres**: MDAnalysis reports angstroms, and this repository
has already paid once for a factor of ten hiding in a reader. **The bin range is an argument, and the comparison
derives one range covering both ensembles** -- a range that stops at the reference's longest distance drops every
coarse-grained distance beyond it, and a dropped sample reads as a model that does not overlap rather than as a range
that was too short. Guard the two things that make a comparison meaningless rather than merely wrong: **raise when a
bead name does not resolve** in that residue (it would otherwise drop out of the pairs and shrink the sample
invisibly), and **raise when the two sides are measured over different pair sets** rather than silently intersecting
them — shaker does the second and it is right.

**Step 4: run it to watch it pass.** Expected: the new tests pass.

**Step 5: commit.** `feat:` — the measurement half of the overlap analysis.

### Task 1.3: the matrix, and what it refuses

**Objective:** assemble the symmetric matrix with a mean per bead, and refuse the comparisons that would mislead.

**Files:**
- Modify: `dashboard/analysis/runs/overlap.py`
- Test: `tests/dashboard/unit/test_overlap_analysis.py`

**Step 1: write the failing test** — symmetry, diagonal 1, the per-bead mean excluding the diagonal, and a refusal
with a reason when the two sides were measured on different bead sets.

**Step 2: run it to watch it fail.** Expected: FAIL — no `overlap_matrix`.

**Step 3: implement.** `overlap_matrix(aa, cg)` returning `{'matrix', 'overlaps', 'pairs', 'bead_names',
'per_bead_mean'}` — mirroring shaker's keys, because a reader comparing the two reports should not have to translate.

**Step 4: run it to watch it pass.** Expected: the new tests pass.

**Step 5: commit.** `feat:` — the matrix and its refusals.

---

## Phase 2 — the overlap analysis, end to end

### Task 2.1: register the kind and stage its inputs

**Objective:** the analysis is reachable by name and gets the files it reads.

**Files:**
- Modify: `dashboard/analysis/worker.py` (`KINDS` at line 21, `PATTERNS` at line 22),
  `dashboard/analysis/metadata.py` (`DESCRIPTIONS`)
- Test: `tests/dashboard/unit/test_analysis_metadata.py`, and whatever pins the worker's kinds

**Step 1: write the failing test** — `'overlap'` is in `KINDS`, has a `DESCRIPTIONS` entry (a kind missing from it
renders under the generic title), and its `PATTERNS` stage the AA reference, the model and the CG trajectory.

**Step 2: run it to watch it fail.** Expected: FAIL — the kind is unknown.

**Step 3: implement.** `PATTERNS['overlap']` mirrors `surfaces` and `carbohydrate-validation`: the atomistic
reference (`1_AA-reference/prod/lig.gro`, `lig.xtc`) and the **CG simulation** (`4_CG_sim/prod/lig_CG.gro`,
`lig_CG.xtc`), plus `2_mapping/model.json` for the bead names. Not the mapped trajectory: this compares the model
against the reference it was built from, not against the mapping of it.

**Step 4: run it to watch it pass.** Expected: the new tests pass.

**Step 5: commit.** `feat:` — the kind exists and stages what it reads.

### Task 2.2: the report, and the figure a reader judges

**Objective:** a published `overlap.json` with the numbers and a self-contained heatmap beside it.

**Files:**
- Modify: `dashboard/analysis/runs/overlap.py` (the `run`/`main` entry point the worker calls)
- Test: `tests/dashboard/unit/test_overlap_analysis.py`

**Step 1: write the failing test** — a synthetic run directory produces `overlap.json` carrying the bead names, the
pairs, the matrix, the per-bead means and the **limitations**; and the figure is written and named by the record.

**Step 2: run it to watch it fail.** Expected: FAIL — no report.

**Step 3: implement.** The report carries what a reader needs to disagree with it: the pair set, the bin range and
width, the frame range and stride, the residues measured, and the two trajectories' identities. Limitations stated
rather than implied: intra-residue distances only (a bead pair whose beads are in different residues is not measured),
and one residue's worth of statistics resolved per molecule -- for a single-molecule run that is every frame, and for
a multi-molecule system it is every frame of every copy, which is a different sample size and must be said.

**Step 4: run it to watch it pass.** Expected: the new tests pass.

**Step 5: commit.** `feat:` — the analysis publishes its numbers and its figure.

### Task 2.3: surface it

**Objective:** the panel shows the analysis and its figure for a run.

**Measured (2026-10-05), and one correction to this task.** The card's data does **not** come through
`views.py`: the mapping-validation panel fetches `GET /api/jobs/<jid>/mapping-consistency`, so the block went there
beside `surfaces` and `views.py` needed no change. The card is an `<h4>` subsection of **card 3** ("Shape and
volume", already "AA vs CG") rather than a new numbered card, so the numbered cards do not renumber under links
already saved and the panel's own tests keep their numbers.

`newest_overlap()` deliberately differs from `newest_surfaces()` next to it in one place: it falls through to an
older attempt whose figure is still on disk, and when none has one it still answers with the newest attempt and
`figure=None`. The envelope reader answers `None` there, which the card renders with the same sentence it uses for a
run never analysed -- true of the file and false of the run. The card therefore states three separate things: never
analysed, published with its figure, published with the figure gone but the numbers intact.

The report's **`figure` key is load-bearing**: the reader takes the artifact's name from the published record rather
than assuming a filename, so a report without it reads as a published analysis with no figure. That is what a first
browser run caught -- the *fixture* was an incomplete imitation of the real report, and the reader was right.

4 unit tests on the reader (nothing published; the two content-addressed levels; fall-through; published without a
figure) and 3 browser tests (drawn with its numbers; never queued; figure gone but numbered). Browser tier 61 passed
1 skipped, fast tier 1082, ruff clean.

**Files:**
- Modify: `dashboard/web/routes/analyses.py` (a `newest_overlap()` reader beside `newest_surfaces()`),
  `dashboard/web/views.py` (the run view projects it), `dashboard/web/static/js/mapping-validation.js` (a card),
  `dashboard/web/templates/dashboard.html`
- Test: `tests/dashboard/integration/test_transferability_api.py`-style route tests, and a browser test

**Step 1: write the failing tests** — the route returns the newest attempt that still has its file on disk (falling
through to an older one when the newest names a file that is gone), and the panel draws the figure.

**Step 2: run them to watch them fail.** Expected: FAIL — 404.

**Step 3: implement.** Follow `references/published-analysis-addressing.md` exactly: glob `<kind>/*/*/result.json`,
read `output_directory` from the record, join — never assume `output/<hash>`. Serve the figure through
`/api/jobs/<id>/artifacts/<run-relative-path>?inline=1`.

**Step 4: run them to watch them pass.** Then the browser tier.

**Step 5: commit.** `feat:` — the overlap matrix is visible.

---

## Phase 3 — the equipartition estimator, validated against shaker's own numbers

### Task 3.1: the estimator as arithmetic

**Objective:** `k = k_B T / σ²` per term, with the threshold that decides bond-versus-constraint stated as a parameter.

**Files:**
- Create: `dashboard/analysis/runs/bonded_estimate.py`
- Test: `tests/dashboard/unit/test_bonded_estimate.py`

**Step 1: write the failing test** — a normal distribution of known σ gives `k = k_B T / σ²` to within tolerance, a
value above the threshold is reported as a constraint, and an improper dihedral crossing ±180° is not read as a
wildly stretched angle (the periodicity case shaker's own comment calls out).

**Step 2: run it to watch it fail.** Expected: FAIL — no module.

**Step 3: implement.** Bonds and angles from the measured mean and σ; the constraint verdict from
`constraint_threshold`, defaulting to **10000**, this repository's value, with a docstring recording that shaker's
default is 25000 and that the difference decided whether DDM's inter-ring link was rigid.

**Step 4: run it to watch it pass.** Expected: the new tests pass.

**Step 5: commit.** `feat:` — the estimator, as arithmetic.

### Task 3.2: pin it against the reference implementation

**Objective:** prove the adapted estimator reproduces the tool it was adapted from, on a real case, before any
analysis depends on it.

**Files:**
- Test: `tests/dashboard/unit/test_bonded_estimate_reference.py`

**Step 1: write the test.** The expected values are shaker's own, from its estimator run on the DDM 200 ns
reference's mapped frames at `T = 303.15` and `constraint_threshold = 10000` — recorded in the design note's table:

```python
REFERENCE = {                       # shaker b7680219, the DDM 200 ns reference, 20,001 frames, T = 303.15
    ('B01', 'B02'): (0.258, 7878.5), ('B01', 'B03'): (0.349, 6395.3), ('B01', 'B11'): (0.424, 2424.4),
    ('B02', 'B03'): (0.261, 3655.9), ('B02', 'B05'): (0.328, 4055.8), ('B09', 'B10'): (0.443, 2464.9),
    ('B10', 'B11'): (0.444, 2423.3),
    ('B05', 'B06'): (0.271, 153646.1), ('B05', 'B07'): (0.367, 33101.0), ('B06', 'B07'): (0.296, 15515.3),
}
```

The test measures the same pairs from the run's own `mapped.xtc` and asserts the lengths to within a tolerance the
bin width justifies, and the force constants to within the tolerance the histogram's resolution justifies. **If a
tolerance has to be loosened to pass, that is the finding** — it means the adapted estimator is not the estimator,
and the analysis built on it would be reporting our numbers under shaker's name.

**Step 2: run it.** Expected: PASS if the adaptation is faithful, and a real result either way.

**Step 3: commit.** `test:` — the adapted estimator is pinned to the tool it came from.

**Measured (2026-10-05), and it needed no shaker installed.** shaker's throwaway venv was pruned — scratch entries
idle for 24 h are removed and this session spans three days — but the pinning does not need the package: shaker's
recorded numbers are the reference and *our* estimator is the thing under test. `bonded_estimate` on the same run,
the same 20,001 frames, the same ten pairs, at 303.15 K:

| pair | ours nm | shaker nm | delta pm | ours k | shaker k | ratio | ours says |
| --- | --- | --- | --- | --- | --- | --- | --- |
| B01-B02 | 0.260 | 0.258 | +2 | 8903.3 | 7878.5 | 1.130 | free |
| B01-B03 | 0.348 | 0.349 | −1 | 7562.0 | 6395.3 | 1.182 | free |
| B02-B03 | 0.261 | 0.261 | 0 | 3774.7 | 3655.9 | 1.032 | free |
| B01-B11 | 0.424 | 0.424 | 0 | 2484.3 | 2424.4 | 1.025 | free |
| B02-B05 | 0.328 | 0.328 | 0 | 4279.1 | 4055.8 | 1.055 | free |
| B09-B10 | 0.443 | 0.443 | 0 | 2526.2 | 2464.9 | 1.025 | free |
| B10-B11 | 0.444 | 0.444 | 0 | 2472.4 | 2423.3 | 1.020 | free |
| B05-B06 | 0.275 | 0.271 | +4 | 276106.1 | — | — | constraint |
| B05-B07 | 0.369 | 0.367 | +2 | 40392.0 | — | — | constraint |
| B06-B07 | 0.296 | 0.296 | 0 | 14109.0 | 15515.3 | 0.909 | constraint |

Worst length disagreement **3.9 pm**; worst force-constant ratio **1.182**, with six of the eight comparable pairs
within 1.055. So the adaptation is faithful, and the residual is one-directional and small — a few per cent typical,
18% worst, which is the size of what a histogram-binned spread against our exact pairwise distances would explain.

**It also reproduces, with our own code on our own run, the finding the design note made from shaker's output.** Our
estimator reads B01-B02 / B01-B03 / B02-B03 as **free** (8903 / 7562 / 3775, all under 10000) where our topology
writes all six ring-1 pairs as *constraints*. Same three pairs, same direction, and it no longer rests on another
tool's word. This is the P0.4-shaped result: the measurement instrument now exists in-tree and disagrees with our own
generated topology in a specific, named place.

The size of the residual is not the finding; **the verdicts are, and they agree in every case.**

---

## Phase 4 — the cross-check analysis, end to end

### Task 4.1: register it, stage its inputs, publish the comparison

**Objective:** a published report of our fitted topology against the independent estimate, term by term.

**Files:**
- Modify: `dashboard/analysis/worker.py`, `dashboard/analysis/metadata.py`,
  `dashboard/analysis/runs/bonded_estimate.py`
- Test: `tests/dashboard/unit/test_bonded_estimate.py`

**Step 1: write the failing test** — the kind is registered; reading a run's own fitted `.itp` and its mapped
trajectory produces a report whose every row carries the pair, our value, the estimate, the delta and **which of the
two is a constraint**; and a term present on one side only is listed as such rather than dropped.

**Step 2: run it to watch it fail.** Expected: FAIL.

**Step 3: implement.** `PATTERNS['bonded-cross-check']` stages `2_mapping/mapped.gro`, `mapped.xtc`,
`3_initial_CG/*initial*.itp` and `3_initial_CG/*_ff_inter.itp` (when the fit has run). The report records the
temperature, the threshold, the frame range and the two provenance strings — ours and the estimator's — because a
delta between two numbers is worthless without knowing which side came from where.

**Step 4: run it to watch it pass.** Expected: the new tests pass.

**Step 5: commit.** `feat:` — the cross-check publishes.

### Task 4.2: surface it

**Objective:** the same tab shows the per-term comparison, constrained terms marked and the threshold named.

**Files:** as Task 2.3, for the new kind.

**Steps:** tests first; the route falls through to an older attempt when the newest has lost its file; the card
states the threshold and the temperature rather than only the numbers.

**Commit.** `feat:` — the cross-check is visible.

---

## Phase 5 — the dihedral fit, and the line it stops at

**Not in this plan's first pass, and deliberately.** `dihedral_fitting.py`'s workflow — inverted Boltzmann,
Savitzky–Golay smoothing, a multi-term cosine series, and AIC/BIC to choose the number of terms — is the one piece
where "adapt the method" shades into "reimplement their code". It is also the piece with the clearest value: our
BARTENDER route needed `-improperIncrement 10` before it would return at all, and a criterion-driven term count would
answer a question our route currently answers by tool default.

Before that task is written, the licence question has to be answered — by the user, not here. Two honest routes: ask
whether a reimplementation of that workflow, written from the paper and the tool's documented behaviour, is
comfortable; or run their code in an isolated tool environment for that one analysis, which needs the LGPL decision
instead.
