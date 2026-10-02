# Protein–detergent complex panel — implementation plan

> **For Hermes:** execute with the `subagent-driven-development` skill, one task per subagent, or by hand with
> `test-driven-development`. Execute **phase by phase** and stop for review at each phase boundary. The design
> decisions are already taken (the specification's final section) and this plan assumes them.

**Goal:** a second workflow that builds a protein–detergent complex, samples it to 1 µs of Martini CG MD with a
micelle-formation assessment in the middle, and back-maps the result — with the setup visible in an NGL viewer.

**Architecture:** a new adapter `dashboard/execution/adapters/pdc.py` owning `STAGES`, calling the existing
`micelle/` package for placement and the existing executor for stages, manifests and cancellation. The panel is a
thin client; the science lives in `micelle/` and the adapter.

**Tech Stack:** Python 3.12, Flask, Playwright, Martini 3, GROMACS 2026.3 (MPI), `martinize2` from vermouth, the
vendored NGL.js 2.3.1.

**Design:** `docs/superpowers/specs/2026-09-28-protein-detergent-complex-panel-design.md` — read it first.

**Tier commands (run from the repo root):**
- focused: `dashboard/.venv/bin/python -m pytest <path> -q -n 0 -p no:cacheprovider`
- fast: `dashboard/.venv/bin/python -m pytest -m 'not browser and not slow' -q -p no:cacheprovider`
- browser: `dashboard/.venv/bin/python -m pytest tests/dashboard/browser -q -n 2 -p no:cacheprovider`
- lint gate: `dashboard/.venv/bin/python -m ruff check dashboard tests --select F,E9,I`

**Do not predict tier counts.** Every `Expected:` below is either an exact assertion or "the new test passes",
with the tier count measured in the run that lands the commit. A count written from arithmetic has already cost
this repository a wrong commit message.

**Stage explicitly** (`git add <paths>`), never `git add -A`: `web/static/vendor/ngl.js` is a 1.25 MB blob and has
already been swept into an unrelated commit once.

---

## Phase A — the panel and the name

### Task A1: rename the existing tab

**Objective:** the tab and heading read "Single Molecule Simulations"; nothing else changes.

**Files:**
- Modify: `dashboard/web/templates/dashboard.html` (the nav button and the `#new` section heading)
- Test: `tests/dashboard/browser/test_new_run_browser.py`

**Step 1: write the failing test**

```python
def test_the_first_workflow_is_named_for_single_molecules(dashboard, live_page):
    page, errors = live_page
    page.goto(live_page.base_url)
    expect(page.locator('#tab-new')).to_have_text('Single Molecule Simulations')
    assert errors == []
```

**Step 2: run it and watch it fail**

`dashboard/.venv/bin/python -m pytest tests/dashboard/browser/test_new_run_browser.py::test_the_first_workflow_is_named_for_single_molecules -q -n 0 -p no:cacheprovider`
Expected: FAIL — the tab still reads "New Run".

**Step 3: change the copy**

Update the tab label, the section heading, and any test that asserts the old name
(`grep -rn "New Run\|New run" dashboard/web tests/dashboard` first — some tests assert the copy).

**Step 4: run the focused test, then the fast and browser tiers**

**Step 5: commit** — `feat: name the existing workflow for single molecules`

### Task A2: the new tab, empty

**Objective:** a third tab exists with the three sub-panels, wired like the others.

**Files:**
- Modify: `dashboard/web/templates/dashboard.html` (a `<button id="tab-pdc" role="tab">` plus
  `<section id="pdc" role="tabpanel" aria-labelledby="tab-pdc" hidden>` with cards: Setup, System view, Status)
- Modify: `dashboard/web/static/js/main.js` (register the tab and its module)
- Create: `dashboard/web/static/js/pdc.js` (a `createPdc()` returning `{mount}`)
- Test: `tests/dashboard/browser/test_pdc_browser.py`

**Step 1: failing test** — the tab switches, the three card headings are present, and the page reports no console
errors.
**Step 2: run, expect failure.** **Step 3: implement the markup and the module.** **Step 4: run.**
**Step 5: commit** — `feat: add the protein-detergent complex tab`

### Task A3: list what can be built

**Objective:** the panel's selectors are populated from what the repository actually holds.

**Files:**
- Create: `dashboard/web/routes/pdc.py` (`GET /api/pdc/catalog`)
- Modify: `dashboard/web/app.py` (register the blueprint)
- Modify: `dashboard/execution/adapters/pdc.py` (Create — `def catalog(project_root)` returning registered
  detergent templates from `molecules/*/micelle_template.json` and available protein inputs)
- Test: `tests/dashboard/integration/test_pdc_api.py`

**Step 1: failing test** — `GET /api/pdc/catalog` returns at least the DDM template, each entry carrying a name
and the template path, and a protein list that is empty rather than absent when no proteins are registered.
**Step 2: run, expect 404.** **Step 3: implement.** **Step 4: run.** **Step 5: commit.**

---

## Phase B — the setup pipeline

### Task B1: the adapter's contract

**Objective:** a seeded, validated payload and a `STAGES` list for the new run type.

**Files:**
- Create: `dashboard/execution/adapters/pdc.py`
- Modify: `dashboard/web/routes/runs.py:69` (the settings-key union must include the PDC specs)
- Modify: `dashboard/execution/coordination/` (admission must accept the `pdc` run type)
- Test: `tests/dashboard/unit/test_pdc_adapter.py`

**Step 1: failing test**

```python
def test_a_build_requires_a_seed_and_a_positive_aggregation_number():
    with pytest.raises(ValueError, match='seed'): pdc.validate_payload({'template': 'ddm', 'aggregation_number': 4})
    with pytest.raises(ValueError, match='aggregation'): pdc.validate_payload({'template': 'ddm', 'aggregation_number': 0, 'seed': 1})
    assert pdc.validate_payload({'template': 'ddm', 'aggregation_number': 4, 'seed': 1})['salt_molar'] == 0.15
```

**Step 2: run, expect ImportError.** **Step 3: implement `validate_payload` and `STAGES`.** **Step 4: run.**
**Step 5: commit** — `feat: pdc adapter contract`

### Task B2: the box rules, as pure functions

**Objective:** the x/y margin, the initial z, and the post-placement z extension, testable without GROMACS.

**Files:**
- Create: `dashboard/execution/adapters/pdc_box.py`
- Test: `tests/dashboard/unit/test_pdc_box.py`

**Step 1: failing test**

```python
def test_the_initial_box_uses_a_two_nanometre_margin_in_x_and_y_and_six_in_z():
    box = pdc_box.initial_box([[0, 0, 0], [4.0, 2.0, 1.0]], margin_nm=2.0, initial_z_nm=6.0)
    assert box == [8.0, 6.0, 6.0]          # extent + 2 x margin, and z exactly as asked

def test_the_box_is_extended_in_z_so_every_face_is_two_nanometres_away():
    box = pdc_box.extended_box([8.0, 6.0], [[-1.0, -1.0, -0.5], [1.0, 1.0, 2.5]], margin_nm=2.0)
    assert box[2] == 2.0 * 2.0 + 3.0        # max_z - min_z + 2 x margin
    assert box[:2] == [8.0, 6.0]            # x/y pass through: widening them would change the placed density
```

**Step 2: run, expect ImportError.** **Step 3: implement both functions, protein centred in the box.**
**Step 4: run.** **Step 5: commit** — `feat: pdc box rules`

### Task B3: the CG protein command, including the elastic network

**Objective:** the martinize2 invocation, asserted by its rendered command rather than by running it.

**Files:**
- Create: `dashboard/execution/adapters/pdc_protein.py`
- Test: `tests/dashboard/unit/test_pdc_protein.py`

**Step 1: failing test**

```python
def test_the_elastic_network_is_the_requested_one(tmp_path):
    (tmp_path / 'protein.pdb').write_text('ATOM\n')
    command = pdc_protein.martinize_command(tmp_path / 'protein.pdb', tmp_path)
    assert '-elastic' in command
    assert command[command.index('-ef') + 1] == '1000'    # kJ/mol/nm^2, the force constant asked for
    assert command[command.index('-eu') + 1] == '1.0'     # 10 A, in the nanometres the tool documents
    assert '-el' not in command    # -el is the lower bound, where the force is constant; the request is a cutoff
```

Verified against `martinize2 -h` rather than assumed: `-ef` is in kJ/mol/nm^2, `-el` and `-eu` are the lower and
upper cutoffs in nanometres, and the upper bound defaults to 0.9 nm. The request's "within 10 A" is therefore
`-eu 1.0`, and the bead selection stays with the force field, which is one backbone bead per residue.

**Step 2: run, expect ImportError.** **Step 3: implement (resolve the executable through
`execution/tools.py`, so a missing `martinize2` is a clear error rather than an empty command).**
**Step 4: run.** **Step 5: commit.**

### Task B4: detergent placement around the protein

**Objective:** the builder's packing and repacking called with the protein in place.

**Files:**
- Modify: `dashboard/execution/adapters/pdc.py`
- Test: `tests/dashboard/unit/test_pdc_placement.py`

**Step 1: failing test** — placement of 12 DDM templates around a small synthetic protein returns exactly 12
positions, all outside the protein's van der Waals volume, with tail beads pointing inward (assert the sign of the
dot product against the radial direction, not a picture).
**Step 2: run, expect failure.** **Step 3: wire `micelle.registry` + `micelle.packing` + `micelle.repack`.**
**Step 4: run.** **Step 5: commit.**

### Task B5: solvent and ions

**Objective:** the solvate and genion commands, asserted by construction.

**Files:**
- Modify: `dashboard/execution/adapters/pdc.py`
- Test: `tests/dashboard/unit/test_pdc_solvation.py`

**Step 1: failing test** — the rendered commands contain `gmx solvate` with the Martini water and
`gmx genion -conc 0.15` after neutralisation, and the reported composition counts match the topology's molecule
counts.
**Step 2: run.** **Step 3: implement.** **Step 4: run.** **Step 5: commit.**

### Task B6: the system view

**Objective:** the built system, visible in NGL before anything runs.

**Files:**
- Modify: `dashboard/execution/adapters/pdc.py` (`system_pdb(...)`: protein and detergent beads only)
- Modify: `dashboard/web/routes/pdc.py` (`GET /api/pdc/<job-id>/system.pdb`)
- Modify: `dashboard/web/static/js/pdc.js` (mount the viewer, same pattern as `compositions.js`)
- Modify: `dashboard/web/static/pdc.css` (a sized host: NGL does not size itself to content)
- Test: `tests/dashboard/integration/test_pdc_system_view.py`, `tests/dashboard/browser/test_pdc_browser.py`

**Step 1: failing test** — the PDB has one HETATM per protein and detergent bead, no water and no ions, and a
`CONECT` per bond; the browser test asserts the stage loaded a component whose atom count equals the PDB's.
(The composition panel's `DRAWN_RADII`/`ATOMS` accessors are the pattern; the seam is published on the panel
element.)
**Step 2: run.** **Step 3: implement.** **Step 4: run, then the browser tier.** **Step 5: commit.**

---

## Phase B2 — wiring (added after Phase B: the plan's B tasks produced builders, not runnable stages)

Tasks B1–B6 produced the pipeline's decisions as tested functions: the contract, the box rules, the CG protein
command, the placement, the solvent and ion commands, and the viewer's writer. None of them is a *stage*. A `pdc`
job therefore cannot be created and run yet, and this phase is what closes that:

### Task B7: prepare a pdc run

**Objective:** a `pdc.prepare(stages_root, **kwargs)` that writes the stage directories and the shell scripts a run
executes, mirroring `cg.prepare`.

**Files:**
- Modify: `dashboard/execution/adapters/pdc.py` (`prepare`)
- Modify: `dashboard/execution/workflow.py` (dispatch on run type where it currently always calls `cg.prepare`)
- Test: `tests/dashboard/unit/test_pdc_prepare.py` (stage directories and script contents), plus an integration test
  that `POST /api/runs` with `run_type: pdc` creates a job whose plan names the pdc stages.

**Steps:** the scripts call the tested builders rather than restating them — box and placement through a small
`python -m` entry point that the stage runs, martinize2 as the command `pdc_protein` builds, solvate and genion as
`pdc_solvation` builds (with its group selection piped in), and the mdrun stages through `aa.mdrun_command_flags`
with the GPU bracket the CG launcher's tests pin. Every script must be assertable by reading it, in the style of
`test_aa_gromacs_invocation.py`: no `-ntmpi`, the elastic network's flags present, the margin and radius values
present.

### Task B8: dispatch the run to the pdc pipeline

**Objective:** a created pdc job runs its own stages rather than the CG ones.

**Files:** `dashboard/execution/coordination/coordinator.py` (or wherever the run type selects the stage plan),
test `tests/dashboard/integration/test_pdc_run.py`.

---

Phase C implements the decisions the user already took: the contact-graph criterion and the retry policy.

### Task B7a: prepare a pdc run — done 2026-09-30 (`2bb56ae`)

`pdc.prepare` writes the six stage directories and fills the first one; `dashboard/execution/scripts/pdc_build.py`
is stage 1's entry point, applying `pdc_box`, `pdc_placement` and `pdc_protein` rather than restating them. Stage 1
stops with exit 3 on the one thing it refuses to guess — the topology — because the detergent has no CG model yet
(B7c). 13 tests in `tests/dashboard/unit/test_pdc_prepare.py`.

### Task B8: dispatch the run to the pdc pipeline — done 2026-09-30 (`a161ce9`)

`pdc.PROTOCOL` answers the eight questions the other run types answer, `prepare_run` dispatches on the run type,
and a pdc job's prepared manifest names the six pdc stages. 7 tests in `tests/dashboard/unit/test_pdc_protocol.py`.

### Task B7b: the five remaining stage scripts

Stage 1 exists; stages 2-6 carry scripts that say they are not written and exit 3. Replace them.

- [ ] Stage 2 (CG assessment MD): `grompp` + `mdrun` through the same mdrun-flag builder the AA and CG adapters
      use, writing `prod/run.gro|tpr|xtc|cpt`.
- [ ] Stage 3 (micelle assessment): the criterion (`contact_nm`, `selection_threshold_fraction`) called once,
      writing `assessment.json` with the cluster sizes and the protein contact count, plus `kept.gro` and
      `removed.json`.
- [ ] Stage 4 (removal and bounded retry): continue from the checkpoint when the removed fraction is at or below
      the threshold, re-run with new velocities when it is above, bounded at `attempts_max`, every attempt
      recording its seed and its removal count.
- [ ] Stage 5 (extension): `convert-tpr -extend`, the criterion again, and the comparison with stage 3.
- [ ] Stage 6 (back-map): the CG2AT2 align call from D1 with `-silent`, failing loudly while D1 is unbuilt.
- [ ] Tests: each script is read the way `test_aa_gromacs_invocation.py` reads the AA ones (the commands, the
      flags, no `-ntmpi`), and the criterion is exercised on a fixture trajectory without a simulation.

### Task B7c: our own detergent model, and the topology assembly

Design: `../specs/2026-09-30-pdc-detergent-model-and-snapshots.md`. Stage 1 cannot write `system.top` while the
detergent's topology describes atoms and the structure holds one centre per molecule per detergent.

- [ ] Queue DDM's AA reference behind the E3 chain; save a molecule-scoped DDM mapping candidate (the recognizer
      for the glucose head, the 12-carbon tail finished by hand with Martini 3 bead types, provenance and limits
      recorded).
- [ ] A `draft-smoke` CG run off it, which is what produces our DDM CG topology and its fitted bonded terms.
- [ ] Stage 1: the template names our CG topology and coordinates, the placement stamps the mapped beads at each
      centre and direction, and `system.top` is assembled with the molecule names read from the two `.itp` files.
- [ ] Tests: the bead names the topology declares are the names the structure writes (the mismatch that cost three
      failed sugar runs), the `[ molecules ]` counts equal the beads present, and `grompp` accepts the pair.

### Task B7d: the snapshot series

- [ ] One sampling setting (10 ns apart, capped at 20 per stage) and the four states that are not frames:
      `placement`, `start`, each stage's end, and the production dumps through `trjconv -dump`.
- [ ] Each snapshot is written with the criterion's numbers, from the same function the verdict uses, together
      with the command, the time and the source checksum that produced it.
- [ ] The system view reads the series through the existing viewer route; the index is the record, not the panel.
- [ ] Tests: the series is derived rather than stored (a resumed run re-derives it), the initial state is always
      present, and a snapshot's numbers equal the assessment report's at the same time.

### Task C1: the assessment-phase stage

**Objective:** a 100 ns CG stage using the shared mdrun flags.

**Files:** `dashboard/execution/adapters/pdc.py`, test `tests/dashboard/unit/test_pdc_stages.py`

**Step 1: failing test** — the stage list names the assessment phase with its duration from the settings, and its
rendered mdrun command comes from `aa.mdrun_command_flags` (assert the flags, not the literals).
**Steps 2–5** as usual.

### Task C2: the micelle criterion

**Objective:** a pure function from coordinates to a verdict, tested on synthetic systems — no MD required.

**Files:**
- Create: `dashboard/execution/adapters/pdc_assessment.py`
- Test: `tests/dashboard/unit/test_pdc_assessment.py`

**Step 1: failing test**

```python
def test_a_compact_cluster_of_tails_is_in_the_micelle_and_a_loose_one_is_not():
    tight = build_tails(cluster_radius=0.4)      # within the 0.6 nm contact distance
    loose = build_tails(cluster_radius=2.5)
    assert pdc_assessment.verdict(tight, requested=12, contact_nm=0.6)['largest_cluster'] == 12
    assert pdc_assessment.verdict(loose, requested=12, contact_nm=0.6)['not_in_micelle']  # names the detergents
    # A protein-free build uses the same criterion with the belt requirement switched off.
    assert pdc_assessment.verdict(tight, requested=12, contact_nm=0.6, protein=None)['largest_cluster'] == 12
```

**Step 2: run, expect ImportError.** **Step 3: implement the contact graph and the cluster report, recording the
contact distance and the cluster sizes.** **Step 4: run.** **Step 5: commit.**

### Task C3: removal and the bounded retry

**Objective:** the fraction rule, the seeded re-run, and the attempt history.

**Files:** `dashboard/execution/adapters/pdc.py`, test `tests/dashboard/unit/test_pdc_retry.py`

Decided: the threshold is **10% of the requested aggregation number**, floored at one detergent, and the loop is
bounded at **3 attempts**. A retry re-seeds **velocities only** — the placed system is kept, so attempts differ in
one documented way.

**Step 1: failing test** — removing 3 of 40 detergents continues from the checkpoint; removing 5 of 40 (over 10%)
starts a fresh assessment phase whose recorded seed differs from the first attempt's; the attempt list stops at
three; and a build whose placed coordinates change between attempts fails the test that compares them.
**Steps 2–5** as usual.

### Task C4: the extension phase

**Objective:** 900 further ns continued from the retained checkpoint, with a final assessment.

**Files:** `dashboard/execution/adapters/pdc.py`, test `tests/dashboard/unit/test_pdc_extension.py`

**Step 1: failing test** — the extension command uses `gmx convert-tpr -extend 900000` (ps) against the
assessment checkpoint, and the final report compares the two verdicts rather than replacing the first.
**Steps 2–5** as usual.

---

## Phase D — back-mapping (CG2AT2, decided)

### Task D1: vendor CG2AT2 and build its align stage

**Objective:** the final snapshot converted to atomistic detail with the align method of the tool the user named.

**Files:**
- Modify: `dashboard/execution/adapters/pdc.py` (`backmap_command`)
- Modify: `config/tools.json` (declare the CG2AT2 path, so a missing tool is a clear error rather than an empty
  command — the repository verifies a declared path before use and resolves to nothing when it cannot be honoured)
- Test: `tests/dashboard/unit/test_pdc_backmap.py`

**Step 1: fetch the tool and record its provenance.** It runs from source with no installation
(`github.com/owenvickery/cg2at`, GPL-3.0). Vendor it under `tools/cg2at/` (gitignored, like `tools/bartender/`),
record the resolved release or commit, and confirm its requirements are met — it needs Python 3, GROMACS, numpy
and scipy, all of which this host already has. Do **not** install it through conda: the environment here is a
venv over a conda base, and touching the base is not this task's business.

**Step 2: write the failing test**

```python
def test_the_back_mapping_uses_the_align_method_with_martini_3_fragments(tmp_path):
    command = pdc.backmap_command(tmp_path / 'final.gro', tmp_path / 'protein.pdb', tmp_path / 'aa_input.pdb')
    assert 'cg2at.py' in ' '.join(command)
    assert command[command.index('-o') + 1] == 'align'          # the method the request names
    assert command[command.index('-fg') + 1] == 'martini_3-0_charmm36'   # these runs are Martini 3
    assert '-silent' in command                                  # a stage must not block on a question
    assert command[command.index('-c') + 1].endswith('final.gro')
    assert command[command.index('-a') + 1].endswith('aa_input.pdb')
```

**Step 3: run it and watch it fail** (ImportError, then the missing flag).

**Step 4: implement the command builder and declare the tool path.**

**Step 5: run it, plus the fast tier and the lint gate.**

**Step 6: commit** — `feat: pdc back-mapping through vendored CG2AT2`

**Step 7: only then attempt a real conversion**, on a small system, and record in the manifest that the align
method invokes GROMACS internally (a short minimisation and a steered-MD morph), so the stage needs a log and a
timeout like any other.

---

## Phase E — documentation

### Task E1: point the roadmap and the guide at this workflow

**Files:** `README.md` (the roadmap section), `docs/PROJECT_GUIDE.md` (a short section beside the existing
workflow descriptions), `AGENTS.md` (the micelle paragraph: the builder is no longer paused-only; the panel now
exists and the science still lives in `micelle/`).

**Step 1:** write the prose. **Step 2:** read it back and delete any claim the code does not support — in
particular do not describe back-mapping as working while Task D1 is expected-to-fail.
**Step 3: commit** — `docs: document the protein-detergent workflow`

---

## Acceptance for the whole feature

- A build with the shipped DDM template and a small protein can be set up, viewed in NGL, run through a 100 ns
  assessment, assessed, continued to 1 µs, and assessed again, with every stage's command, environment, inputs,
  outputs and exit code recorded as the repository requires.
- The assessment is reproducible from the run's artifacts alone: the criterion, its parameters, the cluster sizes
  and the removal log are all in the report.
- A deliberately impossible packing request writes diagnostics and produces no run.
- Identical inputs and seed reproduce identical setup coordinates.
- Nothing in the panel claims validation: the product is `candidate-unvalidated`, and the report says the
  assessment is a proxy for aggregate formation rather than evidence of equilibration.

## Measured status of the pipeline (2026-10-02)

B7b's scripts exist and have been driven stage by stage in a scratch run, not reasoned about. Each defect below was
found by running the stage and reading what it said; each is fixed with the test that fails without it, and each
commit is named because the plan's checkboxes are worth only what the running pipeline says they are worth.

| stage | state |
| --- | --- |
| 1 system | complete — box, placement, an 11-bead topology derived from the run's own mapping |
| 2 CG assessment | complete — solvation, ions, minimisation, equilibration, production (17,176 ns/day), centering, start frame, one snapshot recorded and judged |
| 3 micelle assessment | complete — `assessment.json`, `kept.gro`, `removed.json`; a six-detergent run judges `largest cluster 3 of 6` |
| 4 removal and retry | reaches the removal, reduces the topology to the detergents that stay, re-solvates, minimises and equilibrates; the extension itself is the last thing to drive |
| 5 final assessment | complete — `assessment.json`, `kept.gro` (22 atoms: the two detergents that stay), `removed.json` |
| 6 back-map | refuses correctly: exit 3 with `back-mapping needs CG2AT2 under tools/ (task D1); tools/cg2at/cg2at is not there` — the declared behaviour while D1 is unbuilt |

Seven defects stood between "the run reaches stage 2" and "stage 4 rebuilds the system", all of the same kind: a file
or an option that two pieces of the pipeline disagreed about.

- `7373f82` a ring closure was emitted as a dihedral, with one atom at both ends
- `de1a838` `genion` was passed `-g`, which this GROMACS does not have
- `7b9bd6d` a centering `trjconv` was fed one answer where it asks two
- `77304a6` a phase shorter than its snapshot cadence recorded nothing; it now records its start frame
- `eb9a345` the criterion could not find the tail beads, because the shipped template names no roles: the run's own
  mapping now answers when the template cannot
- `ab743f8` `pdc_snapshot.py` had no `__main__` guard, so every stage call of it was a silent no-op — the real reason
  two phases recorded nothing, after the cadence and the tail beads had both been fixed for their own reasons
- `01842b6`, `87da51e`, `79f67b5`, `cf41557`, `3b2ceb5` the extension stage could not re-solvate (no `ions.mdp`),
  reduced the *water* instead of the detergent, handed `genion` a topology that still described an earlier solvation,
  carried the solvent into the structure the restart was supposed to re-solvate, wrote `gen-seed` twice, and paired
  `gen-vel = yes` with the template's `continuation = yes`
- `48f611b` the extension phase recorded no snapshot, because the fallback looked for a `prod/start.gro` the restart
  path never writes; a phase can now name what it began from

The lesson worth keeping: five of the seven were invisible from the code and obvious from one line of a tool's
stderr, and my first two diagnoses of the silent snapshots were wrong in ways that only running the file exposed.

Still open in Phase 1: the panel's queue button and mapping picker, and re-enabling the paused `pdc-empty-micelle`
cron.

The decision that paragraph used to ask for is settled, by the user: a stage with nothing to do records `skipped`
(exit 4, with its reason in `skip.json`) and the run carries on. The back-map is its first user -- a protein-free
complex run has no protein to align, so it skips rather than failing the run. A stage that lacks a tool it needs still
fails loudly (the back-map keeps exit 3 for a missing CG2AT2), because that is a run that could have been attempted.

`AGENTS.md` states the contract and is write-protected: the sentence that belongs there -- stage `skipped`, exit 4,
reason in `skip.json`, run carries on -- still needs the user's approval, so the code carries the behaviour and the
file does not yet carry the words.
