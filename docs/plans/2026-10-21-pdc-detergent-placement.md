# Protein-detergent placement: bodies, orientations, and a shell measured from the selected subunits

> **For Hermes:** three changes to `dashboard/execution/adapters/pdc_placement.py` and one to `micelle/packing.py`. Each
> has a unit test that fails on today's code. Draft to look at: `docs/design/drafts/new-run-mdrun-and-placement.html`.

**Goal:** a placement whose detergents cannot intersect the protein, whose orientations are drawn rather than all
radial, and whose shell is sized by the hydrophobic region of the subunits the run actually includes.

**Measured state (2026-10-21):**

* `pdc_placement._self_assemble` (line 297) draws a site uniformly in `pdc_box.initial_box` and rejects it when it is
  within `MIN_CLEARANCE_NM = 0.5` of a protein **point** or `MIN_DISTANCE_NM = 0.25` of an earlier **site**. The
  detergent is a molecule 2–3 nm long; only its head site is tested. The module says so itself: *"What this cannot yet
  check is the detergent's own bead shape — the clearance uses the placed centres against the protein coordinates."*
  That is the clash in the preview.
* `_self_assemble` returns `_outward(middle, centers)` (line 337): every direction is the radial from the **cloud's**
  centre, so no orientation is random — the user's second observation, and it is the same vector for a detergent at the
  top and one at the side.
* `micelle.packing.pack_micelle` (line 7) builds centres as `protein.mean(0) + radius * direction`, with `radius` the
  `radius_nm` **setting** (default 3.0 nm). The protein's extent never enters. So a run with `protein_chains = ['A']`
  hands the placer a smaller point cloud — the chains *are* filtered (`pdc_preview.cache_key` folds chains in;
  `routes/pdc.py:241-253` validates them) — and gets the same 3 nm shell as the whole complex.
* The torus branch is already measured (`_belt_torus` reads `slab_radius` from the in-slab points and the tube's radius
  from the detergent's own length); it is the sphere and the random cloud that ignore the protein.

**What MemProtMD does, from the record this repository holds**
(`docs/plans/2026-10-12-pdc-new-run-panel.md:60`): two routes, `PDB -> Memembed -> martinize2 ->
self-assemble -> CGMD -> CG2AT` and `PDB -> PDB2PQR -> minimisation`. In both, the protein arrives already oriented
(OPM, which is the step `memembed` would do), and the lipids are placed as **whole molecules in a membrane frame** —
head groups in the plane of the bilayer, tails along its normal, the protein's own volume excluded — with the
self-assembly route relying on CG MD to repair a rough initial cloud rather than on a careful initial lattice. Three
things follow, and all three are what this plan implements: place a molecule's **body**, orient it according to the
medium it sits in, and let the protein's own hydrophobic surface decide the shape.

---

### Task 1: the detergent's own beads decide what "clear" means

**Files:** modify `dashboard/execution/adapters/pdc_placement.py`; test
`tests/dashboard/unit/test_pdc_placement.py` (create if absent).

**Step 1 — the failing test.** A protein of two points 0.5 nm apart and a template whose tail reaches 3 nm along its
axis from the head:

```python
def test_no_detergent_bead_lands_inside_the_protein():
    protein = [[0.0, 0.0, 0.0], [0.5, 0.0, 0.0]]
    placed = place_detergents(protein, TAIL_3NM, 6, seed=7, mode='self-assembly')
    assert placed['valid'], placed['issues']
    for site, direction in zip(placed['centers'], placed['directions']):
        beads = molecule_beads(site, direction, TAIL_3NM)
        assert min(np.linalg.norm(bead - np.asarray(protein), axis=1).min() for bead in beads) >= 0.25
```

Today this fails: the site is 0.5 nm from the protein points, and the tail crosses them.

**Step 2 — the geometry.** Add one helper that turns the template into a body profile, and one that expands a
(site, direction) into bead positions:

```python
def detergent_profile(template) -> dict | None:
    """The molecule's own head-to-tail axis and each bead's offset along it and radially from it.

    `None` when the molecule states no coordinates: a profile invented from a length would be a guess the clearance gate
    then treats as a measurement -- the same reason `_belt_torus` refuses to build a tube without one.
    """

def body_beads(site, direction, profile) -> np.ndarray:
    """Every bead of one detergent, in world coordinates, for a head at `site` and a body along `direction`."""
```

Axis and head end are read from the molecule, not assumed: the head is the bead(s) carrying the polar/small family
the mapping already labels, and the axis is the principal component of the bead centres when no head is labelled.

**Step 3 — the gate.** In `_self_assemble` and in `_tube_sites`, replace "site vs protein points" with "body vs protein
points": reject a draw when any bead comes within `BEAD_CLEARANCE_NM = 0.25` (the existing overlap gate) of a protein
point. `MIN_CLEARANCE_NM` keeps its meaning for the **head** site and is reported as before. Rejection is not a nudge —
the existing doctrine ("an entry whose site lands within the clearance is refused and the ladder carries on").

**Step 4 — run.** `pytest tests/dashboard/unit/test_pdc_placement.py -q -n 0` → the new test passes, the existing
placement tests (torus, clearance refusal, nan beads) still pass.

**Step 5 — commit** `feat(pdc): the clearance is measured against the detergent's own beads`.

---

### Task 2: orientations are drawn, and heads face out

**Step 1 — failing test.**

```python
def test_self_assembled_orientations_are_not_all_one_direction():
    placed = place_detergents(protein, TEMPLATE, 8, seed=11, mode='self-assembly')
    unit = np.asarray(placed['directions']) / np.linalg.norm(placed['directions'], axis=1)[:, None]
    angles = [np.degrees(np.arccos(np.clip(unit[i] @ unit[j], -1, 1)))
              for i in range(len(unit)) for j in range(i)]
    assert max(angles) > 20, 'orientations are all radial'
```

**Step 2 — implementation.** In `_self_assemble`, draw each direction from the same generator that drew its site
(`gaussian(3)` normalised, which is uniform on the sphere), then flip it so the head points away from the protein:
`if dot(direction, site - nearest_protein_point) < 0: direction = -direction`. For an empty micelle there is no protein:
the flip uses the site's offset from the cloud centre. Determinism is unchanged — one `default_rng(seed)`, one draw
order, and the docstring says the seed is the whole of the randomness.

**Step 3 — the record says which policy was used.** `placement` gains
`'orientation_policy': 'random-outward'` (and `'radial'` for the lattice, whose directions are the shell's normals by
construction), so a report can tell the two apart without inspecting vectors.

**Step 4 — run, then commit** `feat(pdc): self-assembly draws orientations instead of one radial vector`.

---

### Task 3: the shell is sized by the subunits the run includes

**Step 1 — failing test.** A 4 nm rod, then the same rod's first half:

```python
def test_the_shell_follows_the_selected_subunits():
    whole = place_detergents(whole_rod, TEMPLATE, 40, seed=3, mode='lattice')
    half = place_detergents(half_rod, TEMPLATE, 40, seed=3, mode='lattice')
    assert half['band']['radius_nm'] < whole['band']['radius_nm'] * 0.75
    assert half['band']['radius_source'] == 'measured'
```

Today both come back at `radius_nm = 3.0` and the assertion fails on equality.

**Step 2 — the rule.** For a sphere placement the radius becomes

```
shell = max(radius_nm, extent_about_centroid(selected_points) + MIN_CLEARANCE_NM + profile.length_nm)
```

with `radius_nm` demoted to a **floor**, exactly the role it already plays for the torus's centre-line. The record keeps
both numbers and says which decided (`radius_source: 'measured' | 'floor'`), so a reader can tell a shell shaped by the
protein from one the setting enlarged — the rule the torus already follows.

**Step 3 — density is reported, not silently changed.** The aggregation number stays the user's number. The preview
record gains `'estimated_density_per_nm3'` (count over the shell's volume) and `'capacity_nm3_per_detergent'`, and the
panel shows them. When a smaller shell cannot hold the requested count, the existing count gate refuses with its
sentence (`validate_positions`) — a tight micelle that cannot hold 60 detergents must say so rather than place 60
overlapping ones or 30 quietly.

**Step 4 — the box follows too.** `_initial_box` already derives from the points handed in, so the self-assembly box
shrinks with the selection; assert it in the same test (`half['box_nm'] < whole['box_nm']`).

**Step 5 — route test.** `tests/dashboard/integration/test_pdc_preview_api.py`:

```python
whole = client.get('/api/pdc/preview/placement?protein=1at9_cg&chains=A,B&aggregation_number=40&mode=lattice').json
part = client.get('/api/pdc/preview/placement?protein=1at9_cg&chains=A&aggregation_number=40&mode=lattice').json
assert part['band']['radius_nm'] < whole['band']['radius_nm']
```

**Step 6 — browser.** The New run preview draws the returned coordinates already; assert the panel's sentence changes
between the two chain selections (the existing `test_pdc_preview_browser.py` has the route stub to extend).

**Step 7 — commit** `feat(pdc): the pre-assembled shell is measured from the selected subunits`.

---

### Task 5: the capacity is measured, and the number stays the user's

**Decided 2026-10-21:** the aggregation number is **not** scaled automatically. It stays the user's number; what the
placement adds is a *measurement of what the shell can hold*, so a refusal can say what would fit. The reasoning, in
the user's words accepted here: scaling needs a headgroup area we do not measure, and it would turn "can this many
detergents form a belt here" into an assertion about density that nothing in this project supports. Capacity measured
through the same gate the placement already uses invents nothing.

**Files:** `dashboard/execution/adapters/pdc_placement.py`; `dashboard/execution/pdc_preview.py`; the New run panel;
`tests/dashboard/unit/test_pdc_placement.py`.

**Step 1 — the failing test.**

```python
def test_a_shell_too_small_reports_the_count_it_could_hold():
    placed = place_detergents(small_region, TEMPLATE, 150, seed=5, mode='lattice')
    assert not placed['valid']
    capacity = placed['capacity_aggregation']
    assert 0 < capacity['count'] < 150
    # the number it reports is one the gate accepts, on every seed it was measured over
    for seed in capacity['seeds']:
        assert place_detergents(small_region, TEMPLATE, capacity['count'], seed=seed, mode='lattice')['valid']
```

**Step 2 — the measurement.** Bisect over the count against `place_detergents` itself, not against a formula:

```python
def capacity(points, template, requested, *, mode, radius_nm, min_clearance_nm, margin_nm, initial_z_nm,
             frame=None, seeds=(1, 2, 3)) -> dict:
    """The largest count every seed places validly, by bisection over the placer's own gate.

    A bisection between 1 and `requested`, `ceil(log2(requested))` placements per seed and no geometry written down
    twice: the answer is whatever the placement the run would build accepts, including the count, the overlap gate, the
    clearance and the bead-level body gate Task 1 adds. Costs milliseconds for 150.
    """
```

Recorded as `capacity_aggregation: {'count': N, 'seeds': [1, 2, 3], 'requested': 150}` on any placement that fails the
count gate, and `None` when the full count fits — a succeeded placement has nothing to report. The **preview** computes
it always (it is a read-only screen), so the panel can say "this shell holds about 46" before a run is queued.

**Step 3 — the sentence and the control.** `issues` gains one clause, built from the measurement:
`f'the shell holds about {count} at the 0.25 nm overlap gate (measured over {len(seeds)} seeds)'`. The panel renders it
with the builder's other sentences and offers **Use {count}**, which writes the number into the aggregation field. It
does not queue anything by itself.

**Step 4 — run.** The unit test above, plus one asserting that a shell which holds the full count reports
`capacity_aggregation is None`. Then the fast tier.

**Step 5 — commit** `feat(pdc): a refusal says how many detergents the shell can hold`.

**What this deliberately does not do:** change the user's number, or pick a density for a shape. A torus's capacity
scales with its centre-line's circumference and a sphere's with R³; one rule cannot serve both, and the measurement
sidesteps the question rather than guessing at it.

### Task 4: docs

`AGENTS.md`'s belt bullet gains one line: the sphere's radius is a **floor** under a measured shell too, and the
clearance is measured against the detergent's beads rather than its head. `docs/PROJECT_GUIDE.md` §pdc says the same in
prose. `docs/HANDOFF.md` records the preview measurements before and after (shell radius for whole vs one chain, minimum
bead–protein distance, orientation spread).

**Risks, stated up front:**

* A body-aware gate rejects more draws; the ladder is bounded (`DRAWS_PER_DETERGENT = 200`) so an impossible request
  becomes the count gate's sentence rather than a hang. Expect more `capacity` refusals for large counts in tight shells
  — that is the correct behaviour, and the panel must present it as such.
* `detergent_profile` needs the mapping's bead positions. A template that states none keeps today's head-only gate and
  records `'body_profile': None` with the reason, so a placement never silently claims a check it did not run.
* The torus is not re-derived here: its centre-line is already measured and its tube radius is the detergent's length.
  What changes for it is only the bead-level gate (Task 1), which makes its acceptance stricter, not looser.

**Decisions recorded (2026-10-21, by the user):**

1. **The aggregation number stays the user's.** A capacity report (Task 5) tells a refusal what would fit; nothing is
   scaled. Auto-scaling was rejected because it needs a headgroup area this project does not measure, and because it
   would assert a density the evidence does not support.
2. **The random cloud stays the default.** No `belt-seed` mode is built. The 100 ns assessment judges detergents that
   are outside the micelle (`selection_threshold_fraction = 0.10`), and that metric is calibrated against a cloud's own
   removal rate; a pre-seeded belt passes it by construction, so the test would stop being a test.
3. **The comparison is a measurement, not a code change.** One protein, one seed, two assessment legs — cloud versus
   rough belt — comparing `fraction_removed`, final aggregation number and belt thickness. Recorded as an open
   measurement in `docs/HANDOFF.md`; if it ever justifies the belt, it also needs a pass criterion that a pre-seeded
   arrangement cannot satisfy trivially, which is a change to the assessment, not to placement.

**Acceptance:** with the same seed and count, no detergent bead is within 0.25 nm of a protein bead in either mode;
orientation spread > 20° for self-assembly; one selected chain yields a smaller shell and a smaller box than the whole
complex, with `radius_source == 'measured'`; every existing placement test still passes.
