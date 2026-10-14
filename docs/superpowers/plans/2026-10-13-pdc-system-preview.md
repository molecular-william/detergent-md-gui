# A system preview inside the Protein-Detergent New Run panel

Status: **proposal, nothing built.** This is a plan and a mock for review; the panel, the route and the service
described here do not exist yet. The mock is beside this plan at
`docs/superpowers/drafts/2026-10-13-pdc-system-preview-draft.html` and carries five real placement frames, generated
for it by the pipeline's own code (see *What the mock is, and what it is not*).

The ask, verbatim: *"I would like for the 'new run' in 'protein-detergent' to have a panel that shows a preview of the
system."*

This plan's job is the design call that decides whether such a panel is honest: **where the picture's structure comes
from**. Everything else the panel has to say (what it does not show, what it costs, what happens with no protein)
follows from that answer.

## The design call: where the structure comes from

Three honest answers, and one dishonest one.

| | what it is | what it costs | what it can show |
| --- | --- | --- | --- |
| **(a)** run the whole builder into a scratch directory | `pdc_build.build` produces `system.gro`, `system.top`, `prepare_report.json`, the topologies and the placement snapshot | the coarse-graining step, **plus** a full prepared stage tree — **19 MB measured**, 16 MB of it the published Martini 3 ITP and 2.2 MB the derived detergent model | the builder's own verdict *and* picture |
| **(b)** render the build's own placement step | coarse-grain the selected chains, place the detergents, measure the box, render that frame | the same coarse-graining step, **plus 5–40 ms** for the placement | the frame the run itself records as its first snapshot |
| **(c)** render an illustrative schematic | a drawing that stands in for a system | nothing | a picture of a system these inputs do not produce |

**Chosen: (b).** The reasons are behavioural, not only economic.

**1. (b) is not a simplification of the build's picture — it *is* the build's picture.** The build leaves a **dry**
system: `pdc_build` writes `system.gro` (protein + detergent) and nothing solvates it. Water and ions arrive in the
*next* stage — `2_minimisation/minimise.sh`, whose opening act is `python pdc_solvate.py --topology system.top
--structure system.gro --salt-molar 0.15`, as `pdc.LEGS['Energy minimisation']['solvate']` states it. So "protein and
detergents in the box, no solvent" is not a reduced view; it is the artifact.

**2. The frame already exists as a first-class object, and the run records it.** `pdc_build.build` ends its placement
with `_record_placement`, which calls `pdc_snapshot.write_snapshot(stage, 'placement', stage/'system.gro',
title=f'placed system before dynamics ({name}, AN=…, mode=…)')`. That writes `1_system/snapshots/placement.pdb` and
indexes it in `1_system/snapshots.json`. The panel already has a series route for exactly this —
`GET /api/pdc/<job_id>/snapshots` merges every stage's index (`snapshot_entries`), and
`GET /api/pdc/<job_id>/snapshots/<relative>` serves one PDB; `GET /api/pdc/<job_id>/system.pdb` serves the same
coordinates through `pdc_view.system_pdb`. The preview is therefore the *same object the run will show*, before the
run exists. There is nothing to invent and nothing that can drift.

**3. It is the last thing the reader's inputs decide.** Protein, subunit ticks, detergent, template, mapping, count,
initialisation style, seed, box margins — each of those is consumed by the placement and by nothing before it.
Everything after (solvation, the equilibration legs, the assessment's removals, the back-map) is not the reader's to
see yet. A preview is worth exactly this: the part of the outcome that the form in front of the reader is still
choosing.

**4. It is deterministic in the seed, so it is a prediction and can be said to be one.** `pdc_placement`'s lattice
comes from `pack_micelle`, whose only use of the seed is the phase of the golden-angle set; its self-assembly draws
every centre from one `np.random.default_rng(seed)`, rejection-sampled against the protein clearance and the builder's
own 0.25 nm pairwise gate. Same seed, same system; different seed, different system. The panel can therefore say
*"this is the frame the run will build"* — a claim it could not make about anything it computed itself.

**5. (c) is refused explicitly, in the panel.** A schematic would look like a prediction while being a drawing. The
`encapsulation` route already sets this house rule for its own numbers — *"the panel renders what the server decided
rather than repeating the arithmetic in JavaScript"* — and the preview follows it: the only picture the panel will
draw is a set of coordinates the builder's own functions produced.

**6. What (a) would add, and why the mock does not offer it.** Once the coarse-grained protein exists, the rest of
`pdc_build.build` is milliseconds of file writing: the placement is 5–40 ms measured, and `write_topologies` and the
report are trivial. So (a)'s *marginal* cost over (b) is small — but its cost is not zero and its picture is the same
one, while it additionally writes a stage tree (19 MB) for a run that does not exist and takes on `system.top`'s own
failure mode (`exit 3` when the detergent is centres-only). **I did not offer (a) as a second action; if you want the
builder's whole verdict and its files, say so and it is a few lines in the same service.** Flagged under *Decisions
for the user*.

### The cost claim, measured rather than asserted

The premise "run the real builder (faithful, costs a build)" is not what the code says: **(a) and (b) share the same
expensive step.** Everything after the coarse-graining is milliseconds.

| step | measured | instrument |
| --- | --- | --- |
| `martinize2`, 231 residues (1AT9 chain A) | **6.74 s**, 224 MB peak RSS | `/usr/bin/time`, `martinize2 -ff martini3001 -elastic -ef 1000 -eu 1.0` |
| `martinize2`, 690 residues (1AT9 A+B+C) | **13.63 s**, 254 MB peak RSS | same |
| placement, no protein, lattice, 150 | **5.2 ms** | `pdc_placement.place_detergents`, in a venv probe |
| placement, no protein, self-assembly, 150 | **7.2 ms** | same |
| placement, protein, lattice, 150 | **13.9 ms** | same |
| placement, protein, self-assembly, 300 | **38.8 ms** | same |
| one placement frame, protein + 150 DDM | **198 961 bytes** (2 192 beads) | `pdc_view.system_pdb` output |
| one placement frame, empty micelle, 150 (60) | **156 136** (62 626) bytes | same |
| the coarse-grained protein alone | **50 768 bytes** | martinize2's `protein_cg.pdb` |
| a full prepared stage tree — what (a) adds | **19 MB** | `du -sh` on a scratch `pdc.prepare` output |

So the honest sentence for the panel is: *the expensive half is the coarse-graining, it depends only on the protein
and its chain ticks, so it is cached; the placement and everything the reader can still move are milliseconds.* The
mock carries that sentence in the card's *Cost* and *Kept* rows and the longer version in its disclosure.

## The two changes the user asked for (2026-10-14)

The report, verbatim: *"for the pdc system preview, I would like the beads to look twice as big, and I see that
currently the head of the detergent is facing the interior of the micelle, not the tail, so you should account for
that."* Both are landed; the second turned out not to be a picture at all.

### 1. The beads are drawn twice as large

One number in the mock: `radiusScale` 0.75 → **1.5** in its `show()`. NGL multiplies the ball's own radius by it, so
1.5 is twice 0.75; the sticks scale with the ball, so the model's own `CONECT` bonds stay visible.

**The app's viewer is a second place this number lives, and it is not changed here.** `pdc.js` draws the built system
with `ball+stick, {radiusScale: 0.75, aspectRatio: 2}` — the mock copied that — so the panel's card (T3) must carry
**1.5** when it is built, or the preview and the run view will draw the same frame at two different sizes. Flagged
rather than silently inherited; `pdc.js` is outside this change's scope.

The mock now says what the size is, in the two places a reader meets it: a *No bead sizes* line in the card's list —
a coarse-grained bead carries no element and no van der Waals radius, so the radius is chosen for reading, not
measured, and nothing in the picture says a head bead is bigger than a tail bead — and a comment in the viewer's own
code.

### 2. The orientation was the placement's, not the picture's — and it is fixed

**Verdict: the placement's.** The frames were faithful to the coordinates the pipeline produced; what the pipeline
produced was detergents with their heads in the micelle. Measured on the mock's own five frames, read back as text:

| measured | result |
| --- | --- |
| head beads' mean vs the detergent's own centre | **0.317 nm inward**, the same in every molecule of every frame |
| tail beads' mean vs the detergent's own centre | **0.845 nm outward**, the same everywhere |
| head further from the micelle's centre than the tail | **no, in 0 of 660 molecules** (150 in each of frames C, D, E, G; 60 in F) |
| detergent centres in the lattice frames | exactly **3.000 nm** from the micelle's centre, i.e. `pdc_placement.DEFAULT_RADIUS_NM` |
| frame D re-derived from the pipeline | **3 153 of 3 154 lines identical** (the one difference is the `REMARK` title the generator passed) — this frame *is* `pdc_placement.place_detergents(None, None, 150, seed=20261013, mode='lattice')` → `pdc_build.stamp` → `pdc_view.system_pdb`, not merely like it |

`pdc_view.system_pdb` applies no transform beyond nm → Å and the mock's viewer adds none, so nothing between the
placement and the screen could have flipped anything. The inversion was one sign in `pdc_build.stamp`: the axis it
rotated onto the placement's direction was `mean(tail) − mean(head)`, tail-ward, while the direction is the
placement's *outward* one — `pack_micelle` builds the lattice centres as *middle + radius × direction*, and
`pdc_placement._outward` is the self-assembled cloud's equivalent. A micelle's heads face that water and its tails
fill the core, and the run's own criterion says the same thing in code: `pdc_assessment` judges a micelle by *"a tail
bead within the contact distance of any protein bead"*, which a tail-outward placement can never satisfy.

**The fix** takes the head-ward axis (`mean(head) − mean(tail)`), in `dashboard/execution/scripts/pdc_build.py`, with
the convention it orients against now pinned by test rather than by prose: `tests/dashboard/unit/test_pdc_placement.py`
asserts that the placement's direction is the way **out** of the micelle (on the lattice exactly, and on the
self-assembled cloud as each centre's own heading), so the sign cannot be "fixed" in the direction instead. Measured
after it, on the same seed and the same DDM mapping: head beads' mean **+0.317 nm outward** of each detergent's own
centre, tails **−0.845 nm**, in **150/150** detergents on both generators (lattice: head radius 3.3167 nm, tail
2.1553; self-assembly: 3.2953 / 2.1383).

Fixed rather than reported, because it is a defect in **every run's own first snapshot**, not only in the preview: the
placement the run records is the placement the run simulates from.

### What the mock's frames are now, and what they are not

They are kept and labelled: real output of the placement code **before** this fix, showing a micelle inside out, and
they are the record of the defect and of its size. Regenerating them is not a re-run: the frames carry the detergent
model only up to each molecule's own rotation, so the model's original coordinate frame is not recoverable from them,
and re-deriving would draw a *different* legal frame (a different rotation about each molecule's axis), not the one
they hold. What the fix does to them is measured and small in every way except orientation: frame D after the fix has
the same **1650 beads**, the same **3 154 lines**, the same **156 136 bytes**, and the same `CONECT` and `REMARK`
lines — **1 650 lines differ, exactly the `HETATM` records**, because every bead rotated about its own detergent's
centre. So every other number the mock prints (bead counts, box, clearance, byte counts) is untouched by the fix and
still stands. The mock's banner and its card say which frames these are.

## What the preview is, exactly

- **Inputs:** protein, subunit selection, detergent, template, mapping, count, initialisation style, seed, box margin,
  initial z — the same fields `pdc.validate_payload` and `pdc_settings.json` carry, so the picture and the run are
  derived from one set of numbers.
- **Pipeline:** `pdc_build.select_protein` → the CG protein (martinize2 with the protocol's own
  `-elastic -ef 1000 -eu 1.0`) → `pdc_placement.place_detergents` → `pdc_box.initial_box` / `extended_box` →
  `pdc_build.stamp` (the mapping's own beads, rotated so each **head** points along its placement direction — the
  way out of the micelle, into the water; see *The two changes the user asked for*) → `pdc_view.system_pdb`.
- **Output:** a viewer file carrying the model's own bonds as `CONECT` records, exactly as the run's snapshot does.
  `pdc_view.system_pdb` writes one residue per molecule and the moleculetype's `[ bonds ] + [ constraints ]` per
  detergent; the panel's existing viewer switch (`pdc.js` sets `inferBonds:'none'` when the file has `CONECT`) is
  reused, because without it NGL guesses — *"90 bonds drawn on a placement frame the model bonds 60 ways"*, the
  measurement already in that file.
- **No protein:** `place_detergents(None, template, count, seed, …)` places the micelle around the box the count and
  radius define; there is no protein step and no coarse-graining at all. `pdc_build` already treats this as an
  ordinary build (`protein_free` is a field of its report and `system_EMPTY.top` is written with no protein row), so
  the preview has one code path and no special case.

## What the panel says it does not show

The panel states these in its own words; they are the reason the design call has to be visible and not merely made:

1. **No solvent and no ions.** The build leaves a dry system; water and salt are added in the first equilibration leg.
2. **Not the box the run will simulate.** This is the box the build writes — `x`/`y` from the protein's extent plus
   `box_margin_nm`, `z` at `initial_z_nm`. NPT equilibration changes it, so the density here is not the run's.
3. **Not a verdict on the micelle.** A placement is geometry, not dynamics; `pdc_assessment` decides after CG MD, and
   this panel never decides it.
4. **Not the final system.** The assessment leg removes the detergents that are not in the micelle and the back-map
   turns the surviving state atomistic; neither is here.
5. **Beads, not chemistry.** `pdc_view` writes a neutral stand-in element because a coarse-grained bead has no element;
   with a mapping the picture is that mapping's beads, and with none the build records one centre per molecule and
   writes no topology — and the panel says which of the two it is showing.

## When the build refuses

The placement has gates, and the preview must be able to report one instead of drawing. Those gates, as the code
orders them:

- `registry.validate_template` — a template that cannot build stops the stage **before anything is placed**
  (`pdc_build.build` returns 2 with `reasons` in `prepare_report.json`);
- `micelle.validation.validate_positions` — the builder's own packing gate;
- the protein clearance — `pdc_placement.MIN_CLEARANCE_NM = 0.5`, measured as the smallest distance from a placed
  centre to any protein bead, reported as `protein_clearance_nm` and appended to `issues`.

**Measured, on the protein the workspace actually holds:** 1AT9 with the default *pre-assembled* style places a
detergent **0.174 nm** from the protein at 150 detergents (0.179 nm at 60) — under the 0.5 nm the builder requires, so
`place_detergents` returns `valid: False` and the build would return 2. The same protein self-assembled places
cleanly (**0.525 nm**). The mock shows both: the refusal as the builder's own sentence with no picture, and the
self-assembled frame rendered. This is not a hypothetical state to design around — it is the default style on the
protein on disk, and a preview that drew a picture there would be drawing something the build refuses.

### Does one chain of 1AT9 rescue the lattice? Measured: no — and the refusal was never about the assembly

The obvious answer to a refusal is a smaller protein, and the panel already has the control (`protein_chains`, chain A
alone). It does not work, and the numbers say why. Measured with the placement code alone and the file's own
coordinates (no `martinize2`, no simulation; the structure copied into a scratch directory), seed 20261013:

| selection | lattice AN=150 | lattice AN=60 | one bead per residue (CA only) |
| --- | --- | --- | --- |
| A | **0.053 nm** | 0.154 nm | 0.198 nm |
| A+B | **0.034 nm** | 0.042 nm | 0.091 nm |
| A+B+C | **0.050 nm** | 0.036 nm | 0.061 nm |
| (self-assembly, A / A+B / A+B+C) | 0.564 / 0.503 / 0.534 nm — valid | | |

All three selections fail the 0.5 nm gate on the lattice, and **one chain is not close**: 0.053 nm is a tenth of what
is required, so this is not a "the trimer is too big" story. The CA-only column is the CG-resolution proxy for what
`martinize2` hands the placement (230 / 460 / 690 beads against the pipeline's own measured 0.174 nm for chain A at
150 — same order, same verdict), so the atomistic density is not doing the failing either.

**What is failing is the lattice's geometry, not the protein's size.** The lattice places the detergents on a
**sphere of the fixed `DEFAULT_RADIUS_NM` = 3.0 nm** around the protein's *centroid*, and uses no membrane frame at all.
1AT9's own coordinates: the atoms reach **3.270 nm** from the chain-A centroid (3.220 nm transversely in the slab,
3.584 nm along the membrane normal), so the shell passes *through* the protein — 1.0 % of chain A's heavy atoms lie
outside it, right where the sites land. The honest belt for a membrane protein is a *band* in the membrane plane at
the protein's own transverse radius plus the clearance it must keep: a cylinder at **r = 3.72 nm** (3.220 + 0.5),
sampled at 150 angles across the file's own bilayer half-thickness (1.48 nm, its own remark), measures **0.550 nm** —
it passes. The repo already models that frame (`micelle/orientation.py`'s axis/span/origin from the OPM metadata,
`micelle/geometry.candidate_score`'s belt band) and the placement does not call any of it.

**And self-assembly passing is not evidence the lattice could.** `_self_assemble` *rejects* every draw that lands
within `min_clearance_nm` of the protein before accepting it, so it can only hand back a placement that satisfies the
gate it is then judged by: its 0.50–0.56 nm is a rejection sampler's guarantee, not a measure of fit. Two consequences
worth stating where a reader meets them: a preview that says "switch to self-assembly and it works" is telling the
truth about the code and nothing about the belt, and the panel should not present the two styles as interchangeable.
Not fixed here — it is a placement-design question, not a preview one; recorded with the numbers so it is not
re-derived.


## Where it sits, and the geometry measured

**Decision: a new card at the head of the right column** (`.new-run-settings`), above the workflow strip and the
review. The form keeps its twelve columns and its 6 + 6 halves; only the preview card and its viewer host are new CSS
(proposed verbatim in the mock's `<style>`). Nothing about the T10 pairing work moves.

Measured in the browser, **at a 1700 × 1000 viewport**, with the app's own stylesheets linked in the app's own head
order (`dashboard.css, runs.css, new-run.css, mappings.css, compositions.css, pdc.css, layout.css, workspaces.css` —
`new-run.css` before `layout.css`, which is what puts the halves side by side):

| element | measured |
| --- | --- |
| working viewport | 1685 px (a 15 px scrollbar) |
| `#run-form.new-run-layout` | 1637 × 2247 px at x=24 |
| `.new-run-inputs` (left) | **809 × 1676** at x=24, y=512 |
| `.new-run-settings` (right) | **809 × 2247** at x=853, y=512 |
| side by side | yes — equal widths, different x, same y; gap 20 px (new-run.css's own `gap:20px`; layout.css's 16 px `.panel` gap does not reach the form) |
| preview card `.new-pdc-preview` | 809 × 1077 px |
| viewer host `#new-preview-viewer` | 759 × 320 px; NGL's drawing buffer 758 × 320 |
| first paired row `.new-pdc-detergent-pair` cells | 374 px at x=49 and 374 px at x=433, both y=648 |
| horizontal overflow | none |

At **1280 × 800** the same checks hold: the form is 1217 px wide, the halves are **599 px each** at x=24 and x=643
with the same y=629, the first paired row is 269 px + 269 px on one y, the viewer host is 549 × 320 (NGL's buffer
548 × 320), and there is no horizontal overflow. The stacking breakpoint is below both widths: `new-run.css` gives the
form one column at `max-width:900px`, and `layout.css` takes the spans to 12 at `max-width:1100px`.

Three things those numbers say:

- **The pairing is untouched.** The paired row still shares a y to the pixel, and the two halves are still equal and
  side by side. The preview adds no column and no span.
- **The right column is now 571 px taller than the left** (2247 vs 1676). That is the price of the card and its
  explanation. The disclosure is closed by default in the mock for exactly this reason: the reader-facing statements
  (cost, kept, what it does not show) stay visible, and the rationale is one click away.
- **`main`'s measure is 1800 px, not 1440.** `dashboard.css` sets `header,main{max-width:1440px}`, but
  `workspaces.css` is linked last and wins; at a 1700 px window the measure is therefore not capped. The earlier panel
  draft measured a 1652 px form because it linked only two stylesheets and no `main`; this mock reproduces the app's
  full head order, and the app's real numbers are the ones above.

### Sticky: my decision, easy to reverse

`.run-review` is `position:sticky; top:18px` today. Two sticky cards in one column overlap, and the preview is the one
that has to stay in view while the reader scrolls the left column to reach the count. The mock therefore gives the
preview card `position:sticky; top:18px` and sets the review below it back to `static`. **If you would rather keep
the review pinned, the preview becomes the static one — but then the picture scrolls out of view while the inputs are
being changed, which is the whole reason it is there.**

## The service and the route this needs

- **`GET /api/pdc/preview/placement`**, beside the existing `pdc` blueprint, with the panel's own spellings:
  `protein`, `chains` (comma-separated, as `pdc_encapsulation` already accepts), `molecule_id`, `template`,
  `mapping_candidate`, `aggregation_number`, `placement_mode`, `pdc_seed`, `box_margin_nm`, `initial_z_nm`.
  A GET because it is a derived, read-only answer about the inputs, the same shape as
  `GET /api/pdc/proteins/<entry>/encapsulation` the panel already calls.
- **Response:** `{valid, reasons, pdb, basis:{protein, chains, aggregation_number, placement_mode, seed, beads,
  box_nm, clearance_nm, mapping}, cost:{cg_cached, coarse_graining_seconds}}`. The `basis` block travels with the
  picture for the same reason the snapshot index carries a moment's criterion numbers: so a reader never has to guess
  which question the thing on screen answered.
- **A refusal is an answer, not a bad request.** `valid: false` with the builder's own `reasons`, as
  `prepare_report.json` states them at exit 2, so the panel renders them instead of inventing a message. A *malformed*
  request (an unknown protein, a chain the file does not name) is a 400 with `{error}`, exactly as
  `pdc_encapsulation` refuses. **This diverges from the estimate route, which returns 400 for its domain refusals** —
  see *Decisions for the user*.
- **Scratch, and what is kept.** The preview is not a run: no run directory, no manifest, nothing `/api/jobs` or the
  runs table can see. The coarse-grained protein goes to a scratch root (proposed `workspace/preview/cg/`, keyed by
  protein + chains + martinize2's hash + template), because it is the expensive half and depends on nothing the reader
  moves quickly; frames are derived per request and not kept. No stage of any run reads that directory — a run
  re-derives its own `1_system/snapshots/placement.pdb` in its own stage, which is the point of the snapshot design.

## What the mock is, and what it is not

The mock reproduces the **current** panel (the fieldset in `dashboard/web/templates/dashboard.html`, not the older
draft) and adds the preview card. Its five frames are real output, generated once by the pipeline's own functions
against the protein and mapping the workspace actually holds, each recorded with the numbers printed on the page. What
is stubbed is the service: the panel swaps between embedded frames instead of fetching, and says so in its banner.

**Three deviations were needed to obtain the frames, and each is a live defect in the stage rather than a choice the
preview makes.** They block *any* build with a protein, not just the preview:

1. **`pdc_build.cg_protein` reads a file the step never writes.** It globs `directory.glob('*.gro')` and raises
   `SystemExit('the CG protein step left 0 structures…')` unless exactly one `.gro` is there — while
   `pdc_protein.martinize_command` names its output `-x <out>/protein_cg.pdb`. Measured: a successful martinize2 run
   leaves `protein_cg.pdb` and `protein.top`, and `glob('*.gro')` is empty. **The build cannot get past
   coarse-graining for any protein.**
2. **The martinize2 command cannot succeed as written.** With no `-dssp`/`-ss`, martinize2 warns
   *"topology will be created without secondary structure information"* and then exits **2**: *"1 warnings were
   encountered after accounting for the -maxwarn flag. No output files will be written."* A successful run needs
   `-maxwarn 1` (or an explicit `-ss`), and the frames here were made with `-maxwarn 1`.
3. **A subunit selection can carry a ligand martinize2 cannot type.** `pdc_import.filter_chains` keeps `HETATM`
   records, so selecting 1AT9's chains keeps its retinal (`RET`); `martinize2 -ff charmm` cannot type `RET`, deletes
   the molecule and exits 1 with *"No molecule in the system. Nothing to write."* A protein-only file — which is what
   the panel's own optional *Prepare* step exists to produce — is what the frames were made from.

These are reported, not fixed: the fix belongs with the stage, and each deserves its own test. The preview's cost
claim and its refusal behaviour are unaffected by them, because both are statements about code that runs before the
broken step or beside it.

**A fourth defect in these same frames was not a deviation at all, and it is fixed rather than listed: the
placement's own orientation.** Every detergent in all five frames was stamped head-inward, tails-outward — the
inverse of a micelle — because `pdc_build.stamp` rotated the molecule's tail-ward axis onto a direction the
placement means as "outward". Measured, fixed and test-pinned above, under *The two changes the user asked for*.
The frames are kept as the record of it.

As a check on the panel's other half, the estimate route's own numbers for this protein and detergent (computed with
`analysis/runs/encapsulation`'s functions, the same ones the route calls): 1AT9 chain A **37.94 nm²** apolar, **228**
needed, **65.7 %** at 150 requested; all three chains **75.29 nm²**, **453**, **33.1 %**. Those are what the mock's
estimate card shows — the route's answers, not the mock's arithmetic.

## Decisions I made (mine, labelled — overrule any of them)

1. **(b) rather than (a)** as the preview, with the reasons above and the same coarse-graining cost in both. (a) is not
   offered as a second button; its marginal cost is small but it writes a 19 MB stage tree for a run that does not
   exist, and its picture is the same one.
2. **The card is at the head of the right column**, first, above the workflow strip.
3. **The preview card is the sticky one**; the review yields (see above).
4. **The picture is asked for, not streamed.** Coarse-graining is 7–14 s, so `Derive the preview` is a button; the
   panel marks the frame stale when the protein, the subunits or the mapping change, and re-derives automatically for
   the count, the style, the seed and the box margins, which need no new coarse-graining.
5. **A refusal renders as the builder's sentence and no picture** — never a picture of a system the build refuses.
6. **Nothing is written that a run reads**, and the preview creates no run, no job and no manifest.
7. **The empty micelle is a first-class case**, not a degenerate one: no coarse-graining, the cheapest preview the
   panel has, and the estimate beside it is the detergent's experimental number rather than a belt sizing.
8. **The viewer keeps the app's `inferBonds` rule**: the model's own `CONECT` bonds, NGL's guess switched off.

## Decisions for the user

1. **Sticky.** Preview sticky and review static (mine), or review sticky and preview static?
2. **(a) offered or not.** The mock offers only the placement. Do you want a second action that also writes the
   build's files and reports `system.top`'s outcome?
3. **The refusal's status code.** 200 with `valid:false` (matches `pdc_build`'s own report, breaks symmetry with the
   estimate route) versus 400 with `{error}` (matches `pdc_encapsulation`, loses the distinction between "your
   question was malformed" and "the build refuses these inputs").
4. **Where the CG cache lives** — `workspace/preview/cg/` is my proposal; the workspace has no scratch convention
   today, and this would be the first thing in it that is not a run.
5. **Card length.** The reader-facing statements are visible and the rationale is in a closed disclosure; if you want
   the whole argument visible, the card grows by ~400 px in a column that is already taller than its neighbour.

## Tasks

Each is test-first and lands with its own commit and gate run.

**T1 — the preview service.** A module (proposed `dashboard/models/` or `analysis/runs/`) that takes the inputs and
returns the frame, running `select_protein`, the CG protein, `place_detergents`, `pdc_box` and `pdc_view.system_pdb`.
Tests, against fixtures and never the workspace: an empty-micelle preview needs no coarse-graining at all; a template
that fails `validate_template` returns `valid:false` with its reasons and no coordinates; a placement that fails the
clearance gate returns the gate's own sentence; the same seed returns byte-identical coordinates and a different seed
does not; the returned PDB carries `CONECT` records for a run with a mapping and none for a centres-only build.
Acceptance: the service writes nothing outside its scratch root and creates no run.

**T2 — the route.** `GET /api/pdc/preview/placement`, with the query shape and response above. Tests: every field of
`basis` is present and equals the request's; an unknown protein and an unknown chain are 400s with the file's own
chain list (the spelling `pdc_encapsulation` already uses); a domain refusal is not a 400 unless decision 3 says so.

**T3 — the panel card.** The markup, the proposed CSS, the NGL stage built when the card is visible with a
`handleResize` on tab show and window change (measured: a stage built at one width keeps that buffer — a 548 px buffer
inside a 759 px host until it was asked to resize), the staleness rule from decision 4, and the facts rows. Tests
(browser): the two halves still sit side by side at 1700 px and 1280 px with the card present (equal widths, different
x); the paired rows still share a y; changing the count re-derives and changing a subunit tick marks the frame stale
rather than redrawing; a refusal shows the reason and no canvas.
The card's viewer draws beads at **twice `pdc.js`'s radius** (`radiusScale` 1.5 against that file's 0.75, the user's
ask); if the panel ships at the app's 0.75 the preview and the run view will disagree about the size of the same bead,
so either both move or the difference is stated.

**T4 — the three defects above**, as their own change: a `.gro`-or-`.pdb` reader in `cg_protein`, the missing
`-maxwarn`/`-ss` in `pdc_protein.martinize_command`, and `filter_chains`' treatment of `HETATM`. Each with a test;
none of them is a preview concern, but until they land no run with a protein can reach its own placement step, so the
preview's frames would be the only ones that exist.

**T5 — nothing to do for the estimate.** The mock's estimate card shows the encapsulation route's own answers,
recomputed here with the route's functions; no work is implied.

**T6 — the orientation: DONE, 2026-10-14.** `pdc_build.stamp` rotates the detergent's **head**-ward axis onto the
placement's direction (the way out of the micelle) instead of its tail-ward one, and `pdc_placement._outward`'s
docstring states the same convention. Tests, all in the fast tier: `test_the_placement_direction_is_outward_from_the_micelle_centre`
and `test_the_self_assembly_direction_is_outward_too` (the convention the stamp orients against, pinned in
`tests/dashboard/unit/test_pdc_placement.py`); `test_a_detergent_is_rotated_so_its_head_points_along_the_placement_direction`
(the old test renamed and inverted: it asserted the tail took the direction) and
`test_a_stamped_micelle_has_its_heads_toward_the_water_and_its_tails_in_the_core` (per detergent, over a real lattice
placement, the end-to-end shape of what a reader saw), both in `tests/dashboard/unit/test_pdc_build_stamp.py`.
Acceptance met: on the frame the mock holds, all 1 650 detergent beads rotate about their own molecule's centre and
nothing else moves; on a fresh lattice and a fresh self-assembled cloud, 150/150 detergents have their heads outward.
Two notes for whoever reads this next: the mock's five frames predate the fix and say so; and `pdc_view.system_pdb`
truncates bead names to four characters, so `TAIL1`/`TAIL2`/`TAIL3` all print as `TAIL` in the viewer file — harmless
to the picture (they are bonded and drawn identically) but a real collision for anything that reads names back.

## Not doing

- **Not drawing a schematic.** (c) is refused, in the plan and in the panel's own words.
- **Not rendering solvent or ions** the build does not have, guesses at, or could compute dishonestly.
- **Not predicting the micelle.** The assessment decides that, after CG MD, and this panel does not re-litigate it.
- **Not creating a run, a job or a manifest** from a preview, and not making it appear in the runs list.
- **Not touching the Complexes panel's own build door**, or what it sends.
- **Not adding controls to the panel.** The preview reads the fields that are already there.

## Verification

- `node --check` on every inline script of the mock, re-run after the bead-size change (it caught a real syntax error
  once: an unterminated template literal that silently stopped the whole preview script).
- The mock's own measurement script, printed on the page, measured in a browser at 1700 × 1000 and at 1280 × 800 with
  the app's stylesheets and `vendor/ngl.js` from the running dashboard.
- The frames: generated by `pdc_placement` / `pdc_box` / `pdc_build.stamp` / `pdc_view.system_pdb` themselves, with
  their bead and byte counts printed in the mock and in this plan; each frame's residue composition checked in the
  browser (1 650 `DET` for an empty micelle; 230 `PRO` + 150 `DET` for chain A).
- **The orientation (2026-10-14), measured rather than argued:** every frame's head beads 0.317 nm inward of each
  detergent's own centre and its tails 0.845 nm outward, in 660 of 660 molecules; every lattice centre exactly 3.000 nm
  from the micelle's centre; frame D re-derived from the pipeline line-for-line (3 153 of 3 154, the difference being
  the title). After the fix, the same frame has its 1 650 beads rotated and nothing else, the same byte count
  (156 136), and a fresh lattice and a fresh cloud both give 150/150 heads outward. All of it from a fresh interpreter
  against the checked-out tree — not from a long-lived session, whose stale import first reported the fix as having
  changed nothing.
- Tests: `tests/dashboard/unit/test_pdc_placement.py` and `tests/dashboard/unit/test_pdc_build_stamp.py` (see T6),
  which pass; the fast tier as a whole was **not** green when this landed, because another workstream was mid-flight in
  the same checkout (`osmotic.py` rewritten under a running test, T4's `cg_protein` tests written against a reader not
  yet in the tree). Recorded rather than tidied: the failures were in files this change does not touch, and the
  failing set changed between two consecutive runs of the same command.
- Once built: the fast tier, the browser tier, and `ruff check dashboard tests` (gate: F, E9, I).
