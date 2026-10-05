# The membrane frame — implementation plan

> **For Hermes:** execute with the `subagent-driven-development` skill, one task per subagent, or by hand with
> `test-driven-development`. Execute **phase by phase** and stop for review at each phase boundary. The design
> decisions are taken in the specification's "Decisions" section; this plan assumes them.

**Goal:** give the pdc pipeline a real membrane frame — an orientation with a stated origin and thickness, a belt
derived from it, a box built in it, and a preview you can look at before queueing — fed by OPM structures imported
to a local-only directory.

**Architecture:** one shared geometry module, `micelle/frame.py`, defines the plane, the axis and the belt; the pdc
builders read it the way they already read `micelle.registry`. The importer writes into `workspace/`, which
`.gitignore` already ignores, so nothing downloaded can be committed.

**Tech Stack:** Python 3.12, Flask, Martini 3, `martinize2` from vermouth, GROMACS 2026.3 (MPI), the vendored
NGL.js 2.3.1.

**Design:** `docs/superpowers/specs/2026-10-05-membrane-frame-pdc-design.md` — read it first, and read its
"Corrections" section before touching a file.

**Tier commands (run from the repo root):**
- focused: `dashboard/.venv/bin/python -m pytest <path> -q -n 0 -p no:cacheprovider`
- fast: `dashboard/.venv/bin/python -m pytest -m 'not browser and not slow' -q -p no:cacheprovider`
- browser: `dashboard/.venv/bin/python -m pytest tests/dashboard/browser -q -n 2 -p no:cacheprovider`
- lint gate: `dashboard/.venv/bin/python -m ruff check dashboard tests --select F,E9,I`

**Do not predict tier counts.** Every `Expected:` below is either an exact assertion or "the new test passes", with
the tier count measured in the run that lands the commit. A count written from arithmetic has already cost this
repository a wrong commit message.

**Stage explicitly** (`git add <paths>`), never `git add -A`: `web/static/vendor/ngl.js` is a 1.25 MB blob and has
already been swept into an unrelated commit once.

**Never let a test touch the network.** The import is exercised through an injected fetcher; the real download is
the last phase and is done by hand, once.

---

## What has to be fixed, and what has to be built

The plan's own reading of the code changed the shape of this work, so the split is stated before the tasks.

**Fixed — the box is not built in a frame.** `dashboard/execution/adapters/pdc_box.py` builds the box from the
protein's own extent (`initial_box`) and extends z so every face clears the placed system by the margin
(`extended_box`). That rule is sound — it is *not* broken — but it centres the protein, not the membrane, so on a
protein with an asymmetric soluble domain the belt clears one face by 3.08 nm and the other by 4.62 nm (measured on
OPM 1qj8, below). It also has no idea where the membrane is.

**Fixed — the shape is never decided.** `box_shape` is absent from `DEFAULTS` (`pdc.py:42`) and not exposed in the
panel, so it arrives as `box_for`'s `'cubic'` default. For a membrane protein the largest dimension is normally z,
and a cube puts z on x and y as well: 2.2× the rectangular volume on 1qj8, buying nothing.

**Fixed — the builder measures its belt from the wrong origin.** `micelle/geometry.py:candidate_score` takes
`span=(-1,1)` nm and projects from `p.mean(0)`, the protein's centroid. `infer_orientation(protein)`
(`micelle/cli.py:25`) is called with no metadata, so that path records the principal-axis fallback at 0.35
confidence. **But this is the standalone builder's path — see the correction below — so this is coherence work, not
the thing that makes a run right.**

**Built — the belt does not exist.** `pdc_assessment.py` says so in its own docstring, and its artifact carries the
line "no belt is defined in this code base yet". The assessment's protein requirement is a tail bead within the
contact distance of *any* protein bead. So the belt is new work, and the assessment, the placement and the box are
its consumers.

**Built — the import.** There is no way to get an OPM structure into the catalogue except to place a file in
`molecules/*/` by hand, which is tracked by git.

**Built — the preview.** The panel design's own Goal promises the setup is "visible in an NGL viewer before anything
is run" (line 15) and no route serves that: every picture is addressed by `job_id`.

### The correction this plan had to make

The spec's "Why", as first written, attributes the belt defect to `micelle/cli.py:25` and `candidate_score` as though
a pdc run reached them. It does not. `candidate_score` is called only by `micelle/repack.py`, which is called only by
`micelle/cli.py:24` — the standalone builder. The pdc adapter imports `micelle.registry`, `micelle.packing` and
`micelle.validation`, and owns `pdc_box`, `pdc_placement`, `pdc_assessment` itself. The measurements that motivated
the design were taken on a real structure and stand; the *fix* has to land where a run actually goes, which is what
Phases B–D do.

---

## Phase A — the import, local by construction

### Task A1: fetch one structure to a local file, with its provenance

**Objective:** a named PDB id becomes a local structure plus a sidecar that records where it came from and what it
says about itself. No network call inside a build, ever.

**Files:**
- Create: `dashboard/execution/adapters/pdc_import.py`
- Test: `tests/dashboard/unit/test_pdc_import.py`

**Step 1: write the failing test**

```python
def test_the_half_thickness_is_read_out_of_the_file_it_was_downloaded_with():
    """The REMARK travels with the coordinates; the entry page's number does not."""
    text = 'REMARK      1/2 of bilayer thickness:   11.8\nATOM ...\n'
    assert pdc_import.membrane_statement(text) == {'half_thickness_nm': 1.18}


def test_a_structure_that_states_nothing_returns_nothing_rather_than_a_default():
    assert pdc_import.membrane_statement('ATOM ...\n') is None
```

**Step 2: run it to verify failure.** Expected: FAIL — no module `pdc_import`.

**Step 3: write the module.** `ASSET =
'https://biomembhub.org/shared/opm-assets/pdb/{pdbid}.pdb'` (the SPA host cannot be fetched from), a
`membrane_statement(text)` that parses the REMARK with a regex and returns `{'half_thickness_nm': value/10}` or
`None`, and

```python
def import_structure(pdbid, dest_dir, *, fetcher=None, fetched_at=None):
    """Write <pdbid>.pdb and <pdbid>.json into dest_dir and return the sidecar's record.

    `fetcher` and `fetched_at` are injected so a test never opens a socket and never reads a clock.
    """
```

The sidecar carries `pdbid`, `source_url`, `sha256`, `bytes`, `fetched_at`, and the statement when the file made
one. **A validate-the-id gate:** `re.fullmatch(r'[A-Za-z0-9]{4}', pdbid)` or raise — an id becomes a filename.

**Step 4: run it to verify pass.** Expected: the new tests pass.

**Step 5: commit**

```bash
git add dashboard/execution/adapters/pdc_import.py tests/dashboard/unit/test_pdc_import.py
git commit -m "feat: import an OPM structure to a local file with its provenance beside it"
```

**Done — `63731e6`.** 6 tests, all against an injected fetcher; fast tier 1015. One bug found by the test rather
than by review: the injected `fetched_at` is the stamp as recorded, and it was being handed to `datetime.isoformat`
as though it were a `datetime`. The reader's first signature took `(dest_dir, pdbid)`; Task A2's test drove it to
take the file instead, because a hand-placed structure need not be named after a PDB id.

### Task A2: the catalogue lists imports beside the packaged proteins

**Objective:** a run can name an imported structure, and a reader can tell where each entry came from.

**Files:**
- Modify: `dashboard/execution/adapters/pdc.py:151` (`_proteins`)
- Test: `tests/dashboard/unit/test_pdc_adapter.py`

**Step 1: write the failing test** — an isolated workspace holding `workspace/dashboard/proteins/1qj8.pdb` and its
sidecar, built by the shared fixture, not read from the developer's tree; assert the entry carries
`{'source': 'imported', 'half_thickness_nm': 1.18}` and that a packaged entry carries `'source': 'packaged'`.

**Step 2: run it to verify failure.** Expected: FAIL — no `source` key.

**Step 3: extend `_proteins`.** Scan both roots, keep the cap, label the source, and carry the half-thickness from
the sidecar when there is one. An import with no sidecar is listed as `'imported'` with no thickness — the pipeline
must handle a hand-placed file, because someone will place one.

**Step 4: run it to verify pass.** Expected: the new test passes.

**Step 5: commit**

```bash
git add dashboard/execution/adapters/pdc.py tests/dashboard/unit/test_pdc_adapter.py
git commit -m "feat: the protein catalogue lists imported structures beside the packaged ones"
```

**Done — `176edc5`.** 4 tests; fast tier 1015. The entry's key set is pinned the same for both sources, with
`half_thickness_nm` present and `None` when a structure states nothing. A path with no project-relative spelling is
reported absolute rather than dropped: a configured workspace can live outside the repository, and `prepare`
resolves `root / protein`, where pathlib lets an absolute right-hand side win.

### Task A3: import from the panel, with the id validated

**Objective:** a user can name a PDB id in the panel and get it listed, without a shell.

**Files:**
- Modify: `dashboard/web/routes/pdc.py`, `dashboard/web/static/js/pdc.js`, `dashboard/web/templates/dashboard.html`
- Test: `tests/dashboard/integration/test_pdc_api.py`

**Step 1: write the failing test** — `POST /api/pdc/proteins/import` with a body naming `1qj8` and the fetcher
monkeypatched: 201 with the record; a second POST of the same id is 200 and does not refetch; a body naming
`../../etc/passwd` or `1qj8.pdb` is 400 and writes nothing.

**Step 2: run it to verify failure.** Expected: FAIL — 404.

**Step 3: write the route and the control.** The route validates the id through the importer's gate *before*
touching the network, imports into the workspace protein directory, and returns the sidecar. The panel gets a text
field and a button; on success it reloads the catalogue and selects the new entry.

**Step 4: run it to verify pass.** Expected: the new tests pass.

**Step 5: commit**

```bash
git add dashboard/web/routes/pdc.py dashboard/web/static/js/pdc.js dashboard/web/templates/dashboard.html tests/dashboard/integration/test_pdc_api.py
git commit -m "feat: import an OPM structure from the panel, with the id validated at the boundary"
```

**Done — `591f47e`.** 5 integration tests and 2 browser tests; fast tier 1020, browser tier 57 passed 1 skipped. Two
findings came from the tests rather than from review: the field's `maxlength="4"` means the UI cannot express a
dotted name or a traversal path at all, so the refusal a user can actually meet is a four-character string the
server still declines; and `nope` is *accepted* by the format gate, because it is a well-formed four-letter id --
whether it names a structure is the fetch's question, not the gate's.

Phase A is live: the coordinator was restarted, `/api/pdc/catalog` now carries `source` and `half_thickness_nm`, and
`POST /api/pdc/proteins/import` answers 400 for `../etc/passwd` without touching the network. No structure has been
downloaded yet -- that is Phase G, by hand.

---

## Phase B — the frame, defined once

### Task B1: the frame module

**Objective:** one place that says which way the membrane faces, how thick it is, where its plane sits, and which
atoms are inside it.

**Files:**
- Create: `micelle/frame.py`
- Test: `tests/dashboard/unit/test_micelle_frame.py`

**Step 1: write the failing test**

```python
def test_the_belt_is_the_atoms_inside_the_slab_the_frame_states():
    frame = frame_module.MembraneFrame(plane_low_nm=-1.18, plane_high_nm=1.18, axis=(0.0, 0.0, 1.0))
    assert frame_module.belt_mask([[0.0, 0.0, 0.0], [0.0, 0.0, 1.5], [0.0, 0.0, -3.0]], frame) == [True, False, False]


def test_a_frame_can_be_stated_from_a_structure_and_its_sidecar():
    """OPM's frame is the xy-plane through z=0, so a structure's own coordinates need no rotation."""
    built = frame_module.frame_from_structure(half_thickness_nm=1.18)
    assert built.axis == (0.0, 0.0, 1.0) and built.plane_high_nm == 1.18
```

**Step 2: run it to verify failure.** Expected: FAIL — no module `micelle.frame`.

**Step 3: write the module.** A frozen `MembraneFrame` (the two planes, the axis, the half-thickness as the
difference, and a `source` string naming where the numbers came from), `belt_mask(points, frame)` projecting onto
the axis, `belt_extent(points, frame)` for the footprint, and `frame_from_structure(half_thickness_nm, source)`.
The half-thickness must be a *stated* number: constructing a frame without one is an error, not a default, because
the whole defect this replaces was a silent 1.0 nm.

**Step 4: run it to verify pass.** Expected: the new tests pass.

**Step 5: commit**

```bash
git add micelle/frame.py tests/dashboard/unit/test_micelle_frame.py
git commit -m "feat: one definition of the membrane frame and the belt it implies"
```

### Task B2: the importer's statement becomes a frame the adapter can use

**Objective:** the sidecar's half-thickness reaches the pipeline as a frame, and a file with no statement produces
no frame rather than a guessed one.

**Files:**
- Modify: `dashboard/execution/adapters/pdc.py` (`_proteins` entry, or wherever the entry is consumed)
- Test: `tests/dashboard/unit/test_pdc_adapter.py`

**Step 1: write the failing test** — a catalogue entry with `half_thickness_nm: 1.18` yields a `MembraneFrame` with a
`source` naming the file's REMARK; an entry without one yields `None`, and the build then takes the existing
protein-extent path.

**Step 2: run it to verify failure.** Expected: FAIL — no frame is constructed.

**Step 3: implement.** One helper turning an entry into `MembraneFrame | None`; no other behaviour changes yet.

**Step 4: run it to verify pass.** Expected: the new test passes.

**Step 5: commit**

```bash
git add dashboard/execution/adapters/pdc.py tests/dashboard/unit/test_pdc_adapter.py
git commit -m "feat: a catalogue entry's stated half-thickness becomes a membrane frame"
```

### Task B3: the builder measures its belt from the membrane plane

**Objective:** the standalone builder's belt origin and thickness match the frame, so the repository holds one
definition and not two. This is coherence work for `micelle/cli.py`; it does not change a pdc run's arithmetic.

**Files:**
- Modify: `micelle/geometry.py` (`candidate_score`), `micelle/repack.py`, `micelle/orientation.py`,
  `micelle/cli.py`
- Test: `tests/dashboard/unit/test_micelle_geometry.py`

**Step 1: write the failing test** — on the OmpX-like case (atom-mean z +0.73 nm, extent −2.26..+3.80), the belt
fraction measured from the plane is 46.6% of the atoms where the centroid band gives 39.1%; assert both numbers
against a small committed fixture, and assert the default (no origin given) still measures from the centroid.

**Step 2: run it to verify failure.** Expected: FAIL — `candidate_score` takes no origin.

**Step 3: implement.** `candidate_score(point, protein, axis=(0,0,1), span=(-1,1), radius=3., min_distance=.25,
origin=None)` — measuring from `origin` when given, from `p.mean(0)` when not, so no existing call changes
behaviour. `repack` gains `origin=None` and passes it through. `infer_orientation`'s OPM branch reads
`opm['span']`, and `OrientationReport` gains `origin`, defaulting to `(0,0,0)` so the field is additive. `cli.py`
passes both when the named protein has a frame.

**Step 4: run it to verify pass.** Expected: the new tests pass and the fast tier is unchanged apart from the
additions.

**Step 5: commit**

```bash
git add micelle/geometry.py micelle/repack.py micelle/orientation.py micelle/cli.py tests/dashboard/unit/test_micelle_geometry.py
git commit -m "fix: the builder's belt is measured from the membrane plane, and its thickness is the stated one"
```

---

## Phase C — the box and the placement in the frame

### Task C1: the box rule

**Objective:** a box centred on the membrane plane, clearing whichever sticks out further — the protein or the belt —
by the margin, with today's rule intact for a protein that states no membrane.

**Files:**
- Modify: `dashboard/execution/adapters/pdc_box.py`
- Test: `tests/dashboard/unit/test_pdc_box.py`

**Step 1: write the failing test**

```python
def test_the_box_centres_the_membrane_plane_and_clears_the_larger_of_protein_and_belt():
    # an asymmetric protein: the case where today's protein-centred box gives asymmetric belt clearance
    points = [[0.0, 0.0, -2.26], [0.0, 0.0, 3.80]]
    box = pdc_box.membrane_box(points, half_thickness_nm=1.18, margin_nm=2.0)
    assert box[2] == 2 * (3.80 + 2.0)                 # 11.60, not 10.07


def test_a_protein_with_no_stated_membrane_keeps_todays_box_exactly():
    assert pdc_box.membrane_box([[0.0, 0.0, 0.0], [4.0, 2.0, 1.0]], half_thickness_nm=None) == [8.0, 6.0, 6.0]
```

**Step 2: run it to verify failure.** Expected: FAIL — no `membrane_box`.

**Step 3: implement.** `membrane_box(points, half_thickness_nm, margin_nm=2.0, shape='rectangular')`: x and y from
the larger of the protein and belt footprints plus the margin; z = 2 × (max(|furthest atom from the plane|,
half_thickness) + margin); and `half_thickness_nm=None` delegates to the existing rules unchanged. `initial_box`
and `extended_box` keep their signatures and their four tests.

**Step 4: run it to verify pass.** Expected: the new tests pass and the existing four box tests still pass.

**Step 5: commit**

```bash
git add dashboard/execution/adapters/pdc_box.py tests/dashboard/unit/test_pdc_box.py
git commit -m "feat: a box in the membrane frame, with the protein-extent rule as the fallback"
```

### Task C2: the box's shape becomes a stated decision

**Objective:** a membrane protein takes a rectangular box; the shape stops being an unset parameter that silently
means cubic.

**Files:**
- Modify: `dashboard/execution/adapters/pdc.py` (`DEFAULTS` line 42, `SETTING_SPECS` line 49),
  `dashboard/web/templates/dashboard.html`, `dashboard/web/static/js/pdc.js`
- Test: `tests/dashboard/unit/test_pdc_adapter.py`

**Step 1: write the failing test** — `box_shape` defaults to `'rectangular'` for a build carrying a frame and to
`'cubic'` otherwise; the value `'hexagonal'` is refused with a message naming the two accepted values; the panel
sends it and the control offers both.

**Step 2: run it to verify failure.** Expected: FAIL — `KeyError: 'box_shape'`.

**Step 3: implement.** Add `box_shape` to `DEFAULTS`, `SETTING_SPECS` and the panel; validate against the two values
`box_for` accepts, at the same trust boundary as the other settings.

**Step 4: run it to verify pass.** Expected: the new test passes.

**Step 5: commit**

```bash
git add dashboard/execution/adapters/pdc.py dashboard/web/templates/dashboard.html dashboard/web/static/js/pdc.js tests/dashboard/unit/test_pdc_adapter.py
git commit -m "feat: a membrane protein takes a rectangular box, and the shape is a stated default"
```

### Task C3: the placement is belt-aware

**Objective:** detergent clearance keeps the soluble domain clear and the belt is where detergents are placed.

**Files:**
- Modify: `dashboard/execution/adapters/pdc_placement.py`
- Test: `tests/dashboard/unit/test_pdc_placement.py`

**Step 1: write the failing test** — with a frame, a candidate beside the soluble domain is refused and one beside
the belt is accepted; with no frame, the placement is byte-for-byte what it is today for the same seed.

**Step 2: run it to verify failure.** Expected: FAIL — `place_detergents` takes no frame.

**Step 3: implement.** `place_detergents(..., frame=None)`: the clearance gains the belt as a *preferred* surface
without weakening the existing protein clearance gate, and `frame=None` keeps today's path exactly.

**Step 4: run it to verify pass.** Expected: the new tests pass.

**Step 5: commit**

```bash
git add dashboard/execution/adapters/pdc_placement.py tests/dashboard/unit/test_pdc_placement.py
git commit -m "feat: the placement puts the belt at the belt, with the soluble domain cleared"
```

---

## Phase D — the assessment's belt test

### Task D1: the belt replaces "any protein bead"

**Objective:** the criterion the spec asks for becomes the criterion the report computes — and the report stops
carrying a limitation that no longer applies.

**Files:**
- Modify: `dashboard/execution/adapters/pdc_assessment.py`
- Test: `tests/dashboard/unit/test_pdc_assessment.py`

**Step 1: write the failing test** — with a frame, a cluster whose tails touch only the soluble domain fails the
protein requirement and a cluster touching the belt passes, where today both pass. Assert the report's
`limitations` no longer says no belt exists, and that without a frame the old rule stands *and still says so*.

**Step 2: run it to verify failure.** Expected: FAIL — the limitation line is asserted absent.

**Step 3: implement.** A frame becomes an input; the contact rule reads `belt_mask` over the protein's bead
positions when one is given. The limitation string is replaced by a statement of what was actually tested — belt or
any-bead — because a report that overstates its criterion is worse than one that admits a gap.

**Step 4: run it to verify pass.** Expected: the new tests pass and the existing assessment tests still pass.

**Step 5: commit**

```bash
git add dashboard/execution/adapters/pdc_assessment.py tests/dashboard/unit/test_pdc_assessment.py
git commit -m "feat: the assessment tests the belt when the build states one, and says which it tested"
```

---

## Phase E — the preview

### Task E1: a preview route

**Objective:** a build that has not been queued can be looked at, drawn by the same writer the run viewer uses.

**Files:**
- Modify: `dashboard/web/routes/pdc.py`
- Test: `tests/dashboard/integration/test_pdc_api.py`

**Step 1: write the failing test** — `GET /api/pdc/preview?protein=&template=&aggregation_number=&seed=` returns a
PDB naming the protein, the detergents and the box edges; two calls with the same arguments return byte-identical
bodies; nothing is written outside the workspace; a request naming a template that does not exist is 400.

**Step 2: run it to verify failure.** Expected: FAIL — 404.

**Step 3: implement.** Build only the placement and the box — no topology, no solvent, no job — and render through
`pdc_view`'s existing writer, so one renderer serves both and the preview cannot drift from the build.

**Step 4: run it to verify pass.** Expected: the new tests pass.

**Step 5: commit**

```bash
git add dashboard/web/routes/pdc.py tests/dashboard/integration/test_pdc_api.py
git commit -m "feat: preview a build's placement and box before it is queued"
```

### Task E2: the panel shows the preview

**Objective:** choosing a protein and a count draws the setup without queueing a run.

**Files:**
- Modify: `dashboard/web/static/js/pdc.js`, `dashboard/web/templates/dashboard.html`
- Test: `tests/dashboard/browser/test_pdc_browser.py`

**Step 1: write the failing browser test** — set the protein and the aggregation number, press preview, and assert
the NGL stage is holding the preview (its own remark or count), not a run's snapshot. Assert on what the stage
loaded, not that a canvas exists.

**Step 2: run it to verify failure.** Expected: FAIL — no preview control.

**Step 3: implement.** A preview control beside the settings that loads the returned PDB into the existing stage,
and states which of the two things the viewer is showing — the preview or a run's system — because both now use one
stage.

**Step 4: run it to verify pass.** Then run the whole browser tier, because this page's other tests share the stage:
`dashboard/.venv/bin/python -m pytest tests/dashboard/browser -q -n 2 -p no:cacheprovider`

**Step 5: commit**

```bash
git add dashboard/web/static/js/pdc.js dashboard/web/templates/dashboard.html tests/dashboard/browser/test_pdc_browser.py
git commit -m "feat: the setup is visible in the viewer before anything is run"
```

---

## Phase F — the documents

### Task F1: record that the belt is a build, not a repair

**Objective:** the spec stops implying the belt exists, and the panel spec stops claiming the builder already checks
it.

**Files:**
- Modify: `docs/superpowers/specs/2026-10-05-membrane-frame-pdc-design.md`,
  `docs/superpowers/specs/2026-09-28-protein-detergent-complex-panel-design.md`

**Steps:** add the spec's "Corrections" section — the belt does not exist (`pdc_assessment.py:14`) and the
`candidate_score`/`infer_orientation` path is the standalone builder's, not a run's; fix the panel spec's §3 claim
that clearance "uses the builder's existing hydrophobic-belt / soluble-domain checks"; and record the resolved open
questions, with the user's decision that fetched structures live locally only.

**Commit**

```bash
git add docs/superpowers/specs/2026-10-05-membrane-frame-pdc-design.md docs/superpowers/specs/2026-09-28-protein-detergent-complex-panel-design.md
git commit -m "docs: the belt is being built, not fixed -- correct the spec's own account of the code"
```

---

## Phase G — one real protein, end to end

### Task G1: import 1qj8 and build it

**Objective:** the arithmetic is proven on a real structure, not only on a fixture.

**Not a test.** This opens a socket once, by hand.

**Steps:** import `1qj8` through the panel's own route; confirm the sidecar's half-thickness is 1.18 nm and its
sha256 matches the file; queue a small build against a detergent template; then read the run's own records and
report: the box dimensions against Task C1's arithmetic, the shape, the belt the placement scored against, the
assessment's criterion, and the viewer's picture of the protein with detergents at the belt. Note the wall-clock
cost of the box change, because the membrane frame buys symmetry with volume and the price should be known before
anyone runs a 1 µs job in it.

**Deliverable:** a paragraph in the handoff with the run id, the numbers, and anything that did not behave as this
plan said it would.
