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
    box = pdc_box.extended_box([0, 0, 0], [[-1.0, -1.0, -0.5], [1.0, 1.0, 2.5]], margin_nm=2.0)
    assert box[2] == 2.0 * 2.0 + 3.0        # max_z - min_z + 2 x margin
    assert box[0] == box[1] == 6.0          # x/y untouched by the extension
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
def test_the_elastic_network_is_between_ca_pairs_within_one_nanometre_at_the_requested_force_constant():
    command = pdc_protein.martinize_command('protein.pdb', out_dir='.', force_field='martini3')
    assert command[:1] == ['martinize2']
    assert '-elastic' in command and command[command.index('-ef') + 1] == '1000'
    assert command[command.index('-el') + 1] == '10'      # 10 A = 1.0 nm
```

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

## Phase C — sampling and assessment

Phase C needs open decision 1 (the micelle criterion) and 3 (the retry policy) from the specification.

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
