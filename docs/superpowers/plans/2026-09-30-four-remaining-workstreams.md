# Four remaining workstreams: pdc pipeline, the DDM detergent, the cross-molecule reader, the registry

> **For the implementer:** this plan is written to be executed task by task, with the failing test first and a
> commit per task. The fast tier is `dashboard/.venv/bin/python -m pytest -m 'not browser and not slow' -q
> -p no:cacheprovider`; the lint gate is `dashboard/.venv/bin/python -m ruff check .` (F, E9, I must exit 0).
> Measure every count you write down: this repository has been burned by expected-output lines that were predicted
> rather than run.

**Goal:** finish the four things that are visibly unfinished — make a protein-detergent run reach its last stage,
make the DDM detergent stable enough to be more than a smoke model, put the three sugar runs' numbers side by side,
and either give sucrose and maltose real experimental targets or record why they cannot have them.

**Architecture:** all four are changes to existing surfaces, not new subsystems. Two are bug fixes inside code that
already runs (the bonded-term writer, the draft detergent model); one is a reader over reports that already exist;
one is data entry into a registry whose schema is already written and validated.

**Order:** Phase 1 → Phase 2 → Phase 3 → Phase 4. Phase 1 is first because it is the only one that is blocked by a
single reproducible bug. Phase 3 needs no simulation at all and can be done at any time. Phase 4 is independent.

---

## Phase 1 — the pdc pipeline

State: `pdc.prepare` writes six stage directories and stage 1 builds a real system (verified: an 11-bead topology
derived from the saved DDM mapping, six detergents placed, `system.gro`, `system.top` and the first snapshot written).
Stage 2 runs solvation successfully and then `grompp` refuses our own draft:

    ERROR 1 [file detergent_CG.itp, line 50]: Duplicate atom index (6) in dihedrals

The draft's `[ dihedrals ]` block contains the same atom quadruple twice with different parameters
(`6 5 7 6 1 5 10 1` and `6 5 7 6 1 25 28 1`). Stages 3 to 6 have never run at all.

### Task 1.1: pin the duplicate as a failing test

**Objective:** make the refusal reproducible in a unit test, without GROMACS.

**Files:**
- Test: `tests/dashboard/unit/test_detergent_cg.py` (extend)
- Read: `dashboard/models/molecules/detergent_cg.py` (`derive`), `dashboard/models/bonded/generation.py`
  (`generate`, `_canonical_term_key`, the writer around lines 405-410)

**Step 1: write the failing test**

```python
def test_the_drafts_dihedrals_name_each_quadruple_once():
    """`grompp` refuses a topology that lists the same four atoms as two different dihedrals.

    The measured case: the DDM draft emits `6 5 7 6` twice, once with parameters 5/10 and once with 25/28, which is
    how the ring's closure gets walked from both ends.
    """
    draft = _ddm_draft()                     # the helper already in this file
    rows = _section_rows(draft['topology'], 'dihedrals')
    seen = [tuple(row[:4]) for row in rows]

    assert len(seen) == len(set(seen)), f'duplicated quadruples: {[q for q in seen if seen.count(q) > 1]}'
```

**Step 2: run it**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_detergent_cg.py::test_the_drafts_dihedrals_name_each_quadruple_once -q`
Expected: FAIL, naming the repeated quadruple. If it passes, the duplicate comes from somewhere else — stop and
find out where before continuing.

### Task 1.2: keep one term per quadruple, and say so when they conflict

**Objective:** the writer emits each canonical quadruple once; a dropped duplicate that disagreed is recorded rather
than silently lost.

**Files:**
- Modify: `dashboard/models/bonded/generation.py` (the dihedral packing and the `[ dihedrals ]` writer)
- Test: `tests/dashboard/unit/test_bonded_terms.py` (extend)

**Step 1: write the failing test for the choice**

```python
def test_two_terms_for_one_quadruple_leave_one_row_and_a_diagnostic():
    terms = [
        {'kind': 'dihedral', 'beads': ['A', 'B', 'C', 'A'], 'parameters': [5, 10]},
        {'kind': 'dihedral', 'beads': ['A', 'B', 'C', 'A'], 'parameters': [25, 28]},
    ]
    written, diagnostics = pack_terms(terms)

    assert len(written['dihedrals']) == 1
    assert any('quadruple' in line for line in diagnostics), 'the conflict has to be visible'
```

**Step 2: run, expect FAIL**; **Step 3: implement** — dedupe on `_canonical_term_key(kind, names)` while keeping
the *first* term by reference rank, then append a diagnostic naming the four atoms and both parameter sets;
**Step 4: run both tests, expect PASS**;

**Step 5: commit**

```bash
git add dashboard/models/bonded/generation.py tests/dashboard/unit/test_bonded_terms.py tests/dashboard/unit/test_detergent_cg.py
git commit -m "fix: one dihedral per atom quadruple, and a diagnostic when two disagreed"
```

### Task 1.3: drive stage 2 in the scratch harness

**Objective:** see solvation, ions, minimisation and a short production actually run, in scratch, outside the
coordinator — and record what the short MD does (it may still blow up; that is Phase 2's input, not a failure here).

**Files:** none; this is a measurement. Use the pattern already in place:

```bash
python - <<'PY'
from pathlib import Path
from dashboard.execution.adapters import pdc
run = Path('/home/wee/.hermes/profiles/moldym/cache/scratch/pdc-verify/run')
run.mkdir(parents=True, exist_ok=True)
pdc.prepare(run, template='molecules/DDM/micelle_template.json',
            settings={'seed': 20260930, 'aggregation_number': 6, 'box_margin_nm': 2.0, 'initial_z_nm': 6.0,
                      'salt_molar': 0.15, 'contact_nm': 0.6, 'selection_threshold_fraction': 0.1,
                      'snapshot_interval_ns': 20.0, 'snapshot_cap': 20, 'pdc_assessment_ns': 2}
            , project_root=Path.cwd(), mapping='mapping_candidate_2bcc24c3e5f149fab1e4f11f5d80ae0e.json')
PY
cd <run>/1_system && bash prepare_system.sh && cd ../2_assessment && bash assessment.sh
```

**Verification:** `logs/solvation.log` shows solvation, ions, minimisation, equilibration and production steps; the
stage's exit code is recorded; if it fails, the *last* error is written into this plan's Phase 2 section as the input
to Task 2.1.

### Task 1.4: exercise the stages nobody has run

**Objective:** stages 3 (assessment), 4 (extension), 5 (final assessment) and 6 (back-map) each run once in the
harness, and each defect they reveal becomes a task here.

**Method:** `cd <run>/3_assessment && bash assess.sh`, then `4_extension/extension.sh`, then `5_assessment/assess.sh`,
then `6_backmap/backmap.sh` (the last one needs the vendored CG2AT2 at `tools/cg2at/cg2at`). Record for each: exit
code, the artefact it wrote, and the first error if any. Do **not** batch the fixes: each defect gets its own test
and its own commit, in the pattern of Phase 1.

**Known suspects, from reading the declarations:** the assessment stages need the phase's `prod/run.gro` and
`prod/run.xtc` copied in (they declare them); the extension declares `system.top` and the three force-field files and
runs a `grompp` when it rebuilds after a removal; the back-map needs `../1_system/protein.pdb`, which for an empty
micelle is the placeholder header, so for a protein-free run the back-map should be skipped rather than run on a
comment.

### Task 1.5: the panel can queue a pdc run and choose its detergent mapping

**Objective:** the two panel gaps: no queue button, and no way to pick the mapping a build should use.

**Files:**
- Modify: `dashboard/web/routes/pdc.py` (add `GET /api/pdc/readiness` answering the same shape as the other run
  types, so the panel can show blockers)
- Modify: `dashboard/web/static/js/pdc.js`, `dashboard/web/templates/dashboard.html`
- Test: `tests/dashboard/unit/test_pdc_snapshots_route.py` (extend for the route),
  `tests/dashboard/browser/test_pdc_snapshots_browser.py` (extend for the button and the picker)

**Steps:** a select populated from `GET /api/mappings?molecule_id=<the template's molecule>`; a queue button that
POSTs the payload `pdc-first-run.py` uses (run_type `pdc`, method `bartender`, `template`, `mapping_candidate`,
`protein_free`); a readiness read before the POST. Keep the labels the panel already uses.

### Task 1.6: re-enable the scheduled run and record it

**Objective:** the `pdc-empty-micelle` cron job is paused (it would have queued runs that hit Task 1.1's bug). Once
Phase 1 lands, re-enable it and let one run complete end to end.

```bash
# via the cron tool: action 'resume', job_id eecb5a6b759f
```

---

## Phase 2 — the DDM detergent

State: the fitted run (`aa_cg`, mapping of the DDM candidate, 20 ns) gets past mapping and topology fitting and into
real CG dynamics at 2792 ns/day, then dies with

    Constraint error in algorithm Lincs at step 17967

Which means the constraints the draft asks for cannot be satisfied by the positions the placement stamps.

### Task 2.1: measure the mismatch between constrained length and stamped geometry

**Objective:** name the size of the disagreement instead of guessing at it.

**Files:**
- Create: `dashboard/analysis/runs/draft_geometry.py` — takes a draft (`detergent_cg.derive` output) plus the mapped
  structure and returns, per constrained pair, the constraint length and the mapped distance
- Test: `tests/dashboard/unit/test_draft_geometry.py`

**Verification:** the test builds a two-bead candidate with a known geometry and asserts the reported mismatch; then
run it on the DDM draft and record the largest mismatch **in this plan**. That number decides Task 2.3.

**Measured (2026-10-02).** `dashboard/analysis/runs/draft_geometry.py` (9 tests). Run on the DDM candidate
`mapping_candidate_2bcc24c3e5f149fab1e4f11f5d80ae0e.json` against the mapped structure of `aa_cg` run `1322f9e0782e`,
whose molecule is one 11-bead DDM:

| pair | constraint (nm) | mapped (nm) | over (nm) | over % |
| --- | --- | --- | --- | --- |
| S1A–S1C | 0.4294 | 0.3578 | +0.0717 | +20.04 |
| S2A–S2C | 0.4337 | 0.3675 | +0.0662 | +18.01 |
| S1A–S1B | 0.3610 | 0.3112 | +0.0498 | +15.99 |
| S2A–S2B | 0.3183 | 0.2742 | +0.0441 | +16.09 |
| S1B–S1C | 0.3391 | 0.3156 | +0.0235 | +7.45 |
| S2B–S2C | 0.3370 | 0.3167 | +0.0203 | +6.43 |

**Largest +0.0717 nm (+20.04%); median +16.09%.** Every constraint is longer than the geometry it will govern, because
the length is the pair's distance in the molecule's own MMFF structure times the ring scale 1.15, and the run's
molecule sits at a different conformer. Task 2.3's choice is between constraining only the pairs whose geometry is
close and writing the rest as bonds -- with this table as the reason.

**A second finding, from the same measurement — fixed.** The draft's *own* centre distance for those pairs was
0.0314-0.0377 nm against 0.2742-0.3675 nm mapped, a factor of about 10: `detergent_cg.bead_centres` divided the
structure's coordinates by ten while `bonded.generation._coordinates_nm` treats the same numbers as nanometres
already. The placement paid for it — the beads of one detergent in `pdc` run `8a73fe6448f2`'s `1_system/system.gro`
sat 0.021-0.037 nm apart while the topology's ring constraints asked 0.32-0.43 nm, an ~11x stretch at t=0 — and the
run completed and reported clusters anyway, which is why it was not visible. It is the same defect
`dashboard/models/sugars/units.py` records for the sugar writer and the mapping export; `bead_centres` was the
remaining site, and it now converts by the structure's own factor.

Verified after the fix, on a fresh `pdc` preparation: one placed detergent's ring pairs read 0.3136 and 0.3739 nm and
its tail spans 0.8173 nm, against the draft's own 0.3139 and 0.3734 nm and constraints of 0.3610 and 0.4294 nm — the
molecule is the size the topology describes, and the 15% the scale adds is the only stretch left at t=0.

That also refines this table's reading. The draft's own geometry and the mapped structure differ by ~4% for
`S1A–S1C` (0.3734 against 0.3578), so the scale accounts for most of the +20%: what Task 2.3 is deciding is whether a
ring held 15% wider than the atomistic reference is worth its stiffness, not whether two conformers disagree.

### Task 2.2: the tail takes the published named defaults

**Objective:** implement `docs/design/2026-09-30-named-bonded-defaults.md`: read the `#define` rows of
`references/M3-Lipid-Parameters/ITPs/martini_v3.0.0_ffbonded_v2.itp`, choose the context (`_end` for a bead with one
neighbour, `_mid` otherwise), rank them above the lipidome's per-molecule lines and below a detergent-specific
reference, and record the macro name in the term's provenance.

**Files:**
- Modify: `dashboard/models/bonded/generation.py` (the index and `_select_reference`)
- Test: `tests/dashboard/unit/test_named_defaults.py`

**Verification:** the DDM tail's two `C1|C1` bonds read 0.500 nm at the free terminus (TAIL1--TAIL2) and 0.490 nm on
the bond that runs on into the head (TAIL2--TAIL3), both k 2800, and the provenance names `b_C1_C1_end` /
`b_C1_C1_mid`.

**Corrected expectation (2026-10-02):** this originally expected "0.490 for the middle bond and 0.500 for the two end
bonds", which describes a four-bead chain. The tail is three beads, so only TAIL1 is a terminus and only its bond is an
end bond; TAIL3 is bonded to the head as well as to TAIL2, so neither of that bond's beads is a terminus. The rule
implemented is the one that produces this: a bond with a terminal bead on either side (degree 1 in the physical graph)
is an end bond.

### Task 2.3: the draft stops asking for constraints its geometry cannot hold

**Objective:** with Task 2.1's number in hand, either constrain only pairs whose mapped distance is close to the
constrained length, or write those pairs as flexible bonds. Whichever is chosen, the draft says which and why.

**Files:**
- Modify: `dashboard/models/molecules/detergent_cg.py` (the `[ constraints ]` decision)
- Test: `tests/dashboard/unit/test_detergent_cg.py`

**Measured with BARTENDER (2026-10-02).** The user suggested the tool and it was run: it is vendored at
`tools/bartender/m3_bartender/` (declared in `config/tools.json`, and `cg.py` says today that no stage invokes it),
and it fits bonded parameters given a geometry, a trajectory and an `.inp` built by the script it ships from an
AA-to-CG `.ndx` plus a CG topology. Two reconciliations were needed: the exporter's `.ndx` names the 9 physical beads
while our topology's atoms run to 11 with the ring virtual sites (so the topology was renumbered and
`virtual_sitesn` dropped), and `-owntraj` takes DCD/multi-PDB, so the trajectory came out of MDAnalysis.

    bartender -refit -owntraj solute_heavy.dcd -noplot DDM_heavy.gro DDM_bartender.inp

with `solute_heavy.dcd` = 2,001 frames of the DDM AA reference's solute (run `2321ee23a536`), heavy atoms only, in
the molecule's own order — so the fit targets **our** ensemble, not BARTENDER's own GFN sampling.

| pair | ours | fitted | AA reference (mean ± sd, 2001 frames) | ours vs AA | fitted vs AA |
| --- | --- | --- | --- | --- | --- |
| S1A–S1B | 0.3610 | 0.310 | 0.3102 ± 0.0030 | +16.4% | −0.1% |
| S1A–S1C | 0.4294 | 0.359 | 0.3578 ± 0.0049 | +20.0% | +0.3% |
| S1B–S1C | 0.3391 | 0.299 | 0.2948 ± 0.0116 | +15.0% | +1.4% |
| S2A–S2B | 0.3183 | 0.275 | 0.2749 ± 0.0031 | +15.8% | 0.0% |
| S2A–S2C | 0.4337 | 0.367 | 0.3682 ± 0.0079 | +17.8% | −0.3% |
| S2B–S2C | 0.3370 | 0.299 | 0.2956 ± 0.0131 | +14.0% | +1.2% |

The target is the AA reference's own **ensemble** mean, not one frame: against a single frame two of the fitted pairs
looked 5% short, and against the ensemble they are 1.4% short at worst. All six fitted lengths sit inside the
reference's own spread, so the fit reproduces the geometry the molecule actually has, and our 1.15 scale is the only
thing pushing the constraints away from it.

So this task is narrower than it was written: the choice is not constraints versus bonds — BARTENDER kept the rings as
constraints and commented out the matching `[bonds]` rows itself, which is our structure too — it is whether the ring
scale of 1.15 should survive. The fitted lengths say no; what they do not say is whether a constrained ring should use
the measured mean (which is what the fit converged to) or something else.

The same run fitted the terms we currently guess, which is where the larger gain is: the head–tail junction S1A–TAIL3
at 0.528 nm with k 394, the tail steps at 0.440/2441 and 0.538/386, and per-term angle constants (147.2° k 90.3, 142.0°
k 18.5) where the draft uses blanket values. Its rmsd column flags the two ring pairs it fits worst (4.23, 4.64)
against 0.36–1.36 for the rest. A constraint's force constant is unused by GROMACS, so for the rings the fitted
*lengths* are the answer and for the junction and tail the constants are.

**Decided by the user, 2026-10-02.**

1. *Compare* the two ring candidates head to head rather than argue them: constraining at the distance the molecule
   has, against BARTENDER's fitted lengths. Both keep our 11-bead topology with its ring virtual sites and our other
   terms, so the six ring lengths are the only difference; the current draft (scale 1.15) runs as the control, since
   it is the configuration that fails.
2. BARTENDER becomes an **optional** stage — declared, runnable, and not part of a default pipeline. Its inputs are
   the physical-bead renumbering and a DCD of the AA reference's solute, both of which exist as scratch work today.
3. The vendored M3-Lipid set's benchmark directory and property workbook stay **untracked by decision**, not by
   accident; the source file records that.

### Task 2.4: re-run the fit and record what the model does

**Objective:** the honest measurement the smoke/fitted question has been waiting for.

**Method:** queue the `aa_cg` run for DDM against the completed reference `2321ee23a536` (its AA reference is done),
with the current code. Record: how far the CG run gets, its rate, and either completion or the first failure. Write
the outcome into `docs/design/2026-09-30-named-bonded-defaults.md` under a new "Measured" heading. If it still fails,
say what the next hypothesis is rather than starting a refit.

---

## Phase 3 — the cross-molecule reader

State: three CG runs published `analysis/mapping_consistency.json` (sucrose `a2a457cf9413`, maltose `22075892b606`,
trehalose `4e4ff51e7417`). Each compares AA against CG within its own run, and each now agrees to 0.0% by
construction. Nothing puts the same bead type side by side across molecules, which is the only reading that can say
whether our bead types transfer.

### Task 3.1: the reader

**Objective:** one function that takes the three published reports and returns, per bead-type pair, each molecule's
numbers.

**Files:**
- Create: `dashboard/analysis/runs/transferability.py`
- Test: `tests/dashboard/unit/test_transferability_reader.py`

**Contract:**

```python
def compare(reports: dict[str, dict]) -> dict:
    """`{molecule: report}` in, per bead-type pair out.

    Rows are keyed by the *bead types* the pair joins -- ('SP1r', 'SP1r') for a ring edge, ('SN6', 'SP1r') for a
    junction -- never by atom index or residue number, because those are exactly what differs between molecules.
    Each row carries, per molecule: the mean, the standard deviation, and the run's own delta against its AA
    reference. A pair that appears in one molecule only is reported with the molecules that have it, not padded.
    """
```

**Step 1: write the failing test** with three hand-built report documents (never the live workspace — the
repository's rule is that a test builds the record it needs);

**Step 2-4:** TDD as usual; **Step 5: commit.**

### Task 3.2: the surface

**Objective:** a route and a card, so the reading is visible where the other validation cards are.

**Files:**
- Modify: `dashboard/web/routes/analyses.py` (a `GET /api/runs/transferability` taking run ids)
- Modify: `dashboard/web/static/js/mapping-validation.js` (a third card, next to ring pairs and bonded terms)
- Test: `tests/dashboard/unit/test_transferability_api.py`, and a browser test alongside the existing
  `test_mapping_validation_browser.py`

**The card must say, in its own words:** this compares our model across molecules, not against experiment; the
per-run agreement is 0.0% by construction, so what moves here is the *spread*; and the reference's linkage
stiffnesses differ per disaccharide (6200 sucrose, 9000 trehalose, 11250 the α1→4 linkage), so the linkage is
expected **not** to transfer even if the rings do.

### Task 3.3: publish it over the three real runs

**Objective:** the answer, stated plainly, with the numbers behind it: which bead types carry one set of numbers
across the three molecules and which do not.

---

## Phase 4 — the registry

State: `resources/validation/carbohydrates/targets-v1.json` carries measured water–octanol partition targets for
glucose (-17.81 ± 0.57) and trehalose (-21.52 ± 0.29), both from Table S2 of DOI 10.1021/acs.jctc.2c00757, and
`metadata_only` for sucrose and maltose with a `missing` note saying what would fill them.

### Task 4.1: look for the sources that would fill sucrose and maltose

**Objective:** either find citable numbers or record, in the registry itself, that a search was made and what it
covered.

**Method:** the M3 paper's own bibliography cites `10.1016/j.carres.2004.12.038` for trehalose's logP, whose title
(the citation line in the SI) covers octanol–water partition coefficients of glucose **and sucrose** — so that paper
is the first place to look for sucrose. For maltose, look for the same quantity at the same temperature.

**Deliverable:** either the numbers with their own uncertainties and a citation, or an extension of the `missing`
note naming what was searched. No number goes in without a source that states it.

### Task 4.2: enter what is found, extend the test

**Files:**
- Modify: `resources/validation/carbohydrates/targets-v1.json`
- Test: `tests/dashboard/unit/test_carbohydrate_targets_registry.py`

**Verification:** every entered target passes the analysis's own validator, the value agrees with the source's own
convention (the test already checks the 5.708 × logP relation), and the uncertainty is the source's rather than a
convention of ours.

### Task 4.3: say on the API which molecules can and cannot be evidence-complete

**Objective:** a reader of `/api/mappings/validation-targets` can tell at a glance which carbohydrate datasets are
filled and which are blocked, without opening the JSON.

**Files:** modify the route; extend its test. Include the `missing` text in the payload.

---

## What "done" looks like, per workstream

    pdc pipeline   a queued pdc run reaches stage 6 and its artefacts exist; the panel can start one and pick its
                   mapping; the scheduled job is enabled
    DDM detergent  the draft's constraints are justified by its own geometry, the tail uses the published named
                   defaults, and one fit run's outcome is recorded — including if it still fails
    cross-molecule a card that puts the same bead types across sucrose, maltose and trehalose, with the transfer
                   question answered and the linkage's non-transfer explained rather than hidden
    registry       sucrose and maltose either carry sourced numbers or a recorded reason, and the route shows which
                   is which

## Standing rules for whoever executes this

- One task, one commit. Measure before writing a number down, including test counts.
- Never drive a destructive control against the live workspace: scratch runs go under
  `~/.hermes/profiles/moldym/cache/scratch/`, and tests build their own records.
- A coordinator restart kills whatever run is in flight. Check the job list first; if a run is live, either wait or
  resume it deliberately afterwards.
- Python in the coordinator is frozen at process start: a change to routes or models needs a restart before it is
  observable through the API.

## The three fixes, as diagnosed (2026-10-02, later)

The user's decisions: fix the ring, take the tail from the published bonded file, and use BARTENDER's fitted values for
the linkage. Working out what each fix actually is changed two of them.

**The ring is a grouping defect, not a typing one.** The typing rule lives in `dashboard/models/sugars/coords.py` and
is the paper's: a bead holding two hydroxyls is the `SP4r` diol fragment, a four-atom bead with two oxygens and no
diol is `SP1r`, a three-atom bead with one oxygen is `SN6`. Measured on the candidates, with the hydroxyls counted from
the molecule's own graph:

| molecule | ring 1 beads, hydroxyls | diol bead | types |
| --- | --- | --- | --- |
| DDM | 1, 1, 1 | none | SP1r, SP1r, SP1r |
| Maltose | 2, 1, 1 | S1A | SP4r, SP1r, SP1r |

Both went through the same code, so the typing is faithful and `SP1r` is the correct answer for the three beads DDM
produced. DDM's ring 1 has four hydroxyls available and the recogniser put one in each bead, where maltose -- the same
ring type -- puts two in one. The recognition algorithm's own description says "diols first", which is the rule that
did not fire. So the fix is in where the ring is cut, and it has to be made without disturbing sucrose or maltose,
whose groupings are verified against the published entries.

**A dead ranking key, found on the way.** `_select_reference` prefers a molecule-specific reference by testing
`molecule_name in path`, where `molecule_name` is the mapping's *whole* name (`DDM draft from the automatic
recogniser (Martini 3)`). That is never a substring of a reference path, so the ranking's first key is always false: a
BARTENDER reference could sit in `references/` and never be chosen. The match has to be made on the molecule (its id,
or a token of the name) before the fitted terms can be preferred.

**Where each term will come from**, once those two are fixed:

| term | source | rank |
| --- | --- | --- |
| the molecule's own fitted terms | `references/bartender/DDM.itp`, written from `gmx_out.itp` with the mapping's `[ atoms ]` so the index can key it by type | molecule-specific, first |
| the C1 tail | `martini_v3.0.0_ffbonded_v2.itp`'s `#define` rows: `b_C1_C1_mid` 0.490 / `b_C1_C1_end` 0.500, both k 2800, with the context chosen from the physical graph (a bond with a terminal bead on either side is an end bond, and DDM's three-bead tail therefore has one of each) | named defaults, second |
| whatever neither covers | the lipidome's per-molecule lines, then geometry | as today |
