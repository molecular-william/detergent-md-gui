# A system preview inside the Protein-Detergent New Run panel

Status: **built, 2026-10-14.** The card, the service (`dashboard/execution/pdc_preview.py`) and the route
(`GET /api/pdc/preview/placement`) are in the tree and covered by tests; the mock beside this plan is the design the
reader approved, and *As built* below is what the code does where that differs or goes further. The rest of this
document is the design call that decided it, kept as written.

The mock is beside this plan at
`docs/superpowers/drafts/2026-10-13-pdc-system-preview-draft.html` and carries five real placement frames, generated
for it by the pipeline's own code and **re-derived 2026-10-14 through the placement's orientation fix** (see *The two
changes the user asked for (2026-10-14)*).

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

## The two changes the user asked for (2026-10-14, first round: bead size and orientation)

The report, verbatim: *"for the pdc system preview, I would like the beads to look twice as big, and I see that
currently the head of the detergent is facing the interior of the micelle, not the tail, so you should account for
that."* Both are landed; the second turned out not to be a picture at all.

### 1. The beads are drawn at the model's own radius, doubled for the preview

The picture's bead size is now the module's, `dashboard/web/static/js/ngl-beads.js`: each bead is drawn at the radius
its size class has in the model (R 0.264 / S 0.230 / T 0.191 nm, `models/sugars/recognition.RADII_NM`) times a scale
of **2**, the preview's reading aid. The scale is a separate knob from the table on purpose — moving it cannot
corrupt the radii the model states — and the module's tests hold the table, the stand-ins and the scale.

**Measured in a browser, not eyeballed**, off the two buffers the `ball+stick` representation draws from (the
sphere's `radius` attribute is the drawn ball, the cylinder's is the drawn stick; both are in Ångströms and the view
matrix is 1). On a run-shaped frame — every bead written with the `C` stand-in, so every bead an R — the ball is
drawn at **5.28 Å** in the preview (2 × the model's 2.64 Å) and the stick at **1.32 Å**.

**The run view draws the same bead at the model's own radius** (`BEAD_RADIUS_SCALE` = 1): the panel and the preview
therefore differ by exactly the factor the module states, and neither keeps its own copy of the table. The earlier
draft of this section had `pdc.js` at `radiusScale: 0.75` and the card at 1.5; both are now the module's parameters,
so the two cannot drift and the built card has nothing to remember.

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

## The two changes the user asked for (2026-10-14, second round: thinner bonds, and the frames re-derived)

The report, verbatim: *"For the pdc system preview, maybe the bonds can look a bit thinner. Also in the mock, the
detergent head is facing the interior of the micelle, which should be reversed."* The first is a drawing number; the
second was the pre-fix record still being the picture on the page.

### 3. The bonds are thinner, and the beads are the size they were

`ball+stick` draws the ball at `atomRadius × radiusScale × aspectRatio` and the stick at `atomRadius × radiusScale` —
the two knobs are independent, which is what makes this a one-number change: holding `radiusScale × aspectRatio = 1`
keeps the ball at the bead's own radius while `radiusScale` thins every bond. It went from **1/2 to 1/4** in
`ngl-beads.js` (`BEAD_STICK_FRACTION`, with `BEAD_ASPECT_RATIO` 4 buying the ball back), and the mock's own copy of
the numbers moved with it.

**Measured in a browser on the drawn buffers**, before → after: the ball **2.64 Å** (R; 2.30 S, 1.91 T) unchanged in
both, the stick **1.32 Å → 0.66 Å** for a tail bond and **1.15 Å → 0.575 Å** for a sugar bond — exactly half, with the
ball untouched. In the mock, which draws the preview's 2× scale, the ball is 5.28 Å and the stick went 1.32 Å → 0.66 Å.
A browser test reads both numbers off the buffers
(`tests/dashboard/browser/test_pdc_bead_radii_browser.py`), and a fast-tier test holds the mock's copy of the numbers
to the module's (`tests/dashboard/unit/test_ngl_beads.py`), so the picture the reader approves and the panel that gets
built cannot draw one bead two ways.

### 4. The frames are the fixed orientation now — re-derived through the code, not rotated by hand

The five frames were regenerated on 2026-10-14: `pdc.prepare` into a scratch directory (the protein copied in, the
mapping read, nothing written under `workspace/`), `pdc_build.build` — **exit 0 for all five**, because the three
defects the first draft had to work around are fixed in the tree, which is why the frames now come from the build's own
code path — then `pdc_placement.place_detergents` → `pdc_build.stamp` → `pdc_view.system_pdb`. Measured:

| frame | the lines that differ from the pre-fix frame | everything else |
| --- | --- | --- |
| C (1AT9 chain A, self-assembly, 150) | 1 650, all `HETATM`, all detergent beads — the 542 protein records and the 1 500 `CONECT` records identical | 3 696 lines, 198 961 bytes — same |
| G (A+B+C, self-assembly, 150) | 1 650, all `HETATM`, all detergent beads — the 1 626 protein records and the `CONECT` records identical | 4 780 lines, 284 604 bytes — same |
| D (empty micelle, lattice, 150) | 1 650, all `HETATM` | 3 154 lines, 156 136 bytes — same |
| E (empty micelle, self-assembly, 150) | 1 650, all `HETATM` | 3 154 lines, 156 141 bytes — same |
| F (empty micelle, lattice, 60) | 660, all `HETATM` | 1 264 lines, 62 626 bytes — same |

So every other number the mock prints — bead counts, box, clearance, byte counts — is the number it printed before, and
the mock's `META` did not have to change at all. **The proof, three ways.** (1) Each frame re-derived a second time in a
fresh interpreter and a separate scratch tree is **byte-identical** (sha256), so what is embedded is the code's output
and not an edit of it. (2) Against the pre-fix frames the differing lines are exactly the detergent `HETATM` records;
the molecule centres move by at most 5×10⁻⁵ nm and every intramolecular distance is preserved to 2×10⁻⁴ nm — a rigid
rotation about each molecule's own centre, which is what the fix is — with the protein records byte-identical. (3) The
orientation itself, measured on the regenerated frames: each molecule's head beads lie **0.3167 nm outward** of its own
centre along the placement direction and its tails **−0.8447 nm**, in **660 of 660** molecules; the pre-fix frames read
−0.3167 and +0.8447, 0 of 660. Two cross-checks: the same geometry survives the build's own `system.gro` (every
coordinate agrees to within half the `.gro`'s rounding step, 0.0005 nm), and in a browser, on the file the mock
actually loads, every detergent's head is the outer one — 150/150 on the empty-micelle frame, and 150/150 with the head
mean further from the protein than the tail mean on the trimer frame.

**The pre-fix frames are kept as a record** — of the defect and of its size, the −0.3167 / +0.8447 above — but they are
no longer what the page shows. They were not patched in place: the model's own coordinate frame is not recoverable from
a stamped frame, so the corrected frames had to be re-derived, which is what the paragraph above measures. What the fix
does *not* change is any number the mock prints.

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
`micelle/geometry.candidate_score`'s belt band) and at the time of this measurement the placement did not call any of
it.

**Correction, 2026-10-14: the placement calls it now, and this is what that changes.** `pdc_build.build` reads the
frame from the protein file's own REMARK and hands it to `pdc_placement.place_detergents`, which places the lattice as
a **band** in that frame when the file states a membrane (`SHAPE_BAND`, the site's heading being its own outward
direction). Measured today on the build's own coarse-grained chain A (542 beads), seed 20261013, 150 detergents:
shape `belt-band`, band radius **3.6408 nm**, slab radius 3.1408 nm, clearance from the protein **0.5436 nm —
valid**. The same call with `frame=None` — a protein whose file states no membrane, which is every packaged protein —
is the sphere and still refuses at 0.174 nm. So the refusal the mock demonstrates belongs to the sphere, not to 1AT9's
own file, and the mock's branch says so in place; a band frame is not in the mock, which is why that branch shows a
refusal state rather than a picture. Nothing else in this section changes: the sphere's numbers, the samplers'
guarantee and the note that self-assembly passing proves nothing about a band all stand.

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

### Sticky: my decision, easy to reverse — **reversed, 2026-10-14, on measurement**

`.run-review` is `position:sticky; top:18px` today, and the plan above proposed giving the preview that position and
setting the review back to `static`. **It was tried and taken out again.** A card 1280 px tall stuck at `top:18px` is
taller than the viewport it sticks in, so it is painted over everything after it in the column — including the review's
own *Start run* button: two existing browser tests (`test_pdc_subunits_browser.py`, `test_pdc_backmap_browser.py`)
could no longer click the button and timed out waiting for it, which is what a reader would have found too. So the
preview scrolls with the column and the review keeps the stickiness it always had. The mock's own card was 1077 px and
its ruler was a page taller than a viewport, which is why the defect did not show up there; the built card is taller
because it carries the reader-facing statements *and* the Cost/Kept rows the server fills in.

Two smaller lessons from the same measurement, both about selectors rather than layout: a class two cards share is a
selector neither owns, and an unqualified selector for it then matches two elements. The preview's refusal paragraph
and its disclosure therefore have their own hooks (`.new-pdc-preview-refusal`, `.new-pdc-preview-explanation`) with the
shared styling grouped in the CSS, rather than borrowing `.new-pdc-verdict`/`.new-pdc-explanation` — the first attempt
did borrow them and broke the estimate's own browser tests, which is exactly the kind of breakage the panel's
selector-based tests are for.

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

## As built (2026-10-14): what the code does, and the three things that changed under the plan

The route, the service and the card are as proposed above, with four divergences worth naming and three things about
them that were only true once the code was written.

**Where it lives.**

| | |
| --- | --- |
| service | `dashboard/execution/pdc_preview.py` — `preview(...)`, `coarse_grained(...)`, `cache_key(...)`, `resolve_mapping(...)` |
| route | `dashboard/web/routes/pdc.py` — `GET /api/pdc/preview/placement`, `preview_choices`, `preview_cache_root` |
| card | `dashboard/web/templates/dashboard.html` (`.new-pdc-preview`), `dashboard/web/static/new-run.js` (`createPdcNewRun`), `dashboard/web/static/new-run.css` |
| cache | `<workspace>/preview/cg/<key>/` — `preview/cg` is `pdc_preview.CACHE_DIRECTORY`, and the route resolves it against the *workspace*, never the repository |

**The cache key, and therefore what invalidates an entry:** `sha256(CACHE_FORMAT, protein file bytes, chains,
resolved martinize2 bytes, force field + elastic constants)[:16]`. So the four things that rebuild a coarse-grained
protein are the protein's own content, the chain ticks, the tool that builds it, and a change to the protocol's
elastic-network constants. Nothing else does — which is what makes the count, the style and the seed re-derive
without paying for it. An entry that cannot be *read* is removed rather than re-used, so a half-written file (two
previews of one protein at once) cannot leave a frame that fails identically forever. No run reads this directory,
no stage writes it, and a preview creates no run, no job and no manifest.

**Divergences from the plan's own proposal.**

1. `basis` gained `template`, `detergent`, `residue`, `placement_shape`, `band_radius_nm` and
   `detergent_representation`, and `cost` gained `detergent_seconds`, `cg_bytes`, `cg_key` and `seconds` — the card
   prints what the derive *measured* rather than restating the plan's headline (see the numbers below), and it says
   which of the two pictures it is showing (a mapping's beads, or one centre per molecule).
2. **The tool is resolved, not named.** `pdc_build.cg_protein` now takes `executable=`, and the route hands it
   `tools.tool_path('martinize2')`. This is not tidiness: measured in a plain interpreter, `subprocess.run
   (['martinize2', ...])` raised `FileNotFoundError` while `tools.tool_path` resolved the same tool at
   `dashboard/.venv/bin/martinize2` — a stage gets its PATH from `tools.search_path()`, and a web request does not.
   A route that had passed the bare name would have looked correct in every stubbed test and failed on every preview.
3. `pdc_view.read_moleculetype_text` was split out of `read_moleculetype`, so the preview reads the topology it just
   derived instead of writing a scratch file only to read it back. The `source` it is given is
   `detergent_CG.itp` — the name a run writes that same derivation under — and it is what the PDB's own REMARK
   names.
4. A mapping of another molecule is a 400 (`the mapping … is of X, not of Y`), and a template whose *files* are
   missing is a refusal with `registry.load_template`'s own sentence — the case `pdc_build.build` turns into exit 2.

**The three things that changed since this plan was written.**

1. **The band, and therefore the refusal.** `pdc_build.build` reads the membrane from the protein file's REMARK and
   hands it to `place_detergents`, so a protein that states one is placed as a band in its plane. Measured through
   the built service on the workspace's own 1AT9, seed 20261013, 150 detergents, chain A: `placement_shape` =
   `belt-band`, band radius **3.6408 nm**, clearance **0.5436 nm — valid**. The plan's 2026-10-14 correction is
   therefore the whole story and the mock's refusal branch is the *sphere's*, which is what the built card says in
   place: a refusal is rendered with the builder's sentence, and when the shape that refused is the sphere the card
   adds that this is the shape a build takes when the protein's file states no membrane — that the file's own
   statement is what decides the shape, and that the sphere's refusal is not a verdict on the protein. The mock's
   `REFUSAL` constant and its "this mock carries no band frame" paragraph are mock-only and are not in the panel.
2. **One table for the beads, and the panel reads it.** `new-run.js` imports `BEAD_RADIUS_PARAMETERS` and
   `applyBeadRadii` from `ngl-beads.js` and passes its own `PREVIEW_BEAD_SCALE = 2` at the call — the module's rule
   for every bead view, and `tests/dashboard/unit/test_ngl_beads.py` now names `new-run.js` among them and holds the
   panel's scale to the mock's, so the picture the reader approved and the picture in the app cannot differ.
3. **The bond guard.** The card loads every frame with `inferBonds: 'none'`. A coarse-grained bead is written with a
   neutral stand-in element and has no covalent radius, so NGL's distance guess draws head beads onto tail beads
   (`pdc.js` measured 90 bonds on a frame the model bonds 60 ways). With a mapping the file carries the model's own
   bonds as `CONECT` records and no guessed bond is drawn; with none — a centres-only build, one bead per molecule —
   there is nothing to draw and nothing is invented. Both cases are asserted in the browser tier, the second by
   count (three beads, zero bonds).

### The cost, measured through the built service

1AT9 (`workspace/dashboard/proteins/1at9.pdb`), the DDM mapping the store holds, 150 detergents, seed 20261013,
lattice, this machine:

| derive | wall | coarse-graining | mapping → beads | placement | beads | PDB | CG protein |
| --- | --- | --- | --- | --- | --- | --- | --- |
| chain A, **cold** | **9.07 s** | 8.24 s (martinize2) | 0.80 s | 0.007 s | 1 142 | 95 645 B | 50 768 B |
| chain A, **warm** | **0.11 s** | cached | 0.074 s | 0.005 s | 1 142 | 95 645 B | 50 768 B |
| A+B+C, cold | 16.47 s | 16.41 s | 0.018 s | 0.011 s | 2 226 | 181 281 B | 152 292 B |
| empty micelle, 150 | 0.03 s | none | 0.017 s | 0.001 s | 600 | 52 827 B | — |
| empty micelle, centres only, 60 | 0.0005 s | none | — | 0.001 s | 60 | 5 221 B | — |

The frame is byte-identical for the same seed and differs for another (measured, both directions). The one number
worth explaining is the mapping's own derivation: **0.80 s on the first call in a process, 0.017–0.074 s after it**,
because `models/bonded/generation` reads the published reference set once per process; the plan's "milliseconds" is
true of a warm service and not of the first question a restarted one answers. The coarse-graining is what the cache
removes, and it is 98 % of a cold derive.

The plan's own headline figures are unchanged as *expectations* and are what the card's disclosure states: martinize2
6.7 s for one 231-residue chain and 13.6 s for 690 residues (measured here at 8.2 s and 16.4 s through the service,
which also pays the stage's read-back). The card's Cost row prints what *this* derive paid, not the expectation.

### The rest of the plan, as built

Everything under *What the preview is, exactly*, *What the panel says it does not show*, *When the build refuses*,
*Where it sits* and *Decisions I made* is implemented as written, with two exceptions the measurement forced:

1. **Decision 3 (sticky) is reversed** — see *Sticky* above: the card is taller than a viewport and covered the
   review's own launch button, which two existing browser tests measurement-caught.
2. The card's refusal paragraph and its disclosure carry their own classes rather than borrowing
   `.new-pdc-verdict`/`.new-pdc-explanation`, because an unqualified selector for those then matched two elements
   (again two existing browser tests said so). The styling is still one rule each, grouped in `new-run.css`.

And two things the panel gained that the plan did not name, both because the built card renders what the server
measured rather than a fixed sentence: the Cost row prints *this* derive's own numbers, and the Kept row names the
cache entry (`preview/cg/<key>`, its size, and that frames are not kept). The plan's headline figures are what the
disclosure states as expectations, labelled as measured on this machine with 1AT9.

### The card, measured in the running app (2026-10-14)

With the dashboard serving the panel and a real derive behind it — 1AT9 chains A+B+C, 150 DDM detergents, the DDM
mapping, at a 1700 × 1050 viewport:

| element | measured |
| --- | --- |
| `#run-form.new-run-layout` | 1637 × 2452 px at x=24 |
| `.new-run-inputs` (left) | 809 × 1773 at x=24 |
| `.new-run-settings` (right) | 809 × 2452 at x=853 |
| side by side | yes — equal widths, different x, same y=416; no horizontal overflow |
| preview card `.new-pdc-preview` | 809 × 1280 |
| viewer host | 759 × 320; NGL's drawing buffer 758 × 320 |
| first paired row cells | 374 px at x=49 and 374 px at x=433, both y=552 |

And what the card showed, from the real route and the real martinize2: `3,276 beads · box 10.05 × 9.84 × 11.08 nm ·
clearance from the protein 0.505 nm`, belt band radius 3.64 nm, cost `martinize2 16.6 s (1626 beads) · placement
0.012 s · mapping to beads 0.645 s`, kept `preview/cg/e4502b1a46f998c7 (149 KB)`, 1 500 drawn bonds (150 molecules ×
4 `[ bonds ]` + 6 `[ constraints ]` — the model's own, none guessed). Unticking a subunit turned the state line amber
and left the picture in place, and clearing the protein derived the empty micelle in place: `1,650 beads · box
9.96 × 9.97 × 9.96 nm · no coarse-graining`.

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
placement means as "outward". Measured, fixed and test-pinned above, under *The two changes the user asked for*; the
frames in the mock are the **fixed** ones as of 2026-10-14, re-derived through the corrected code with only their
detergent `HETATM` records changed, and the pre-fix measurement (−0.3167 / +0.8447 nm) is kept as the record of the
defect.

As a check on the panel's other half, the estimate route's own numbers for this protein and detergent (computed with
`analysis/runs/encapsulation`'s functions, the same ones the route calls): 1AT9 chain A **37.94 nm²** apolar, **228**
needed, **65.7 %** at 150 requested; all three chains **75.29 nm²**, **453**, **33.1 %**. Those are what the mock's
estimate card shows — the route's answers, not the mock's arithmetic.

## Decisions I made (mine, labelled — overrule any of them)

1. **(b) rather than (a)** as the preview, with the reasons above and the same coarse-graining cost in both. (a) is not
   offered as a second button; its marginal cost is small but it writes a 19 MB stage tree for a run that does not
   exist, and its picture is the same one.
2. **The card is at the head of the right column**, first, above the workflow strip.
3. **The preview card is the sticky one**; the review yields (see above) — **reversed 2026-10-14: the card is static and
   the review keeps its stickiness.** The card is taller than a viewport, so sticking it covered the launch button.
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

**T1 — the preview service. DONE, 2026-10-14.** A module (proposed `dashboard/models/` or `analysis/runs/`) that takes the inputs and
returns the frame, running `select_protein`, the CG protein, `place_detergents`, `pdc_box` and `pdc_view.system_pdb`.
Tests, against fixtures and never the workspace: an empty-micelle preview needs no coarse-graining at all; a template
that fails `validate_template` returns `valid:false` with its reasons and no coordinates; a placement that fails the
clearance gate returns the gate's own sentence; the same seed returns byte-identical coordinates and a different seed
does not; the returned PDB carries `CONECT` records for a run with a mapping and none for a centres-only build.
Acceptance: the service writes nothing outside its scratch root and creates no run.

**T2 — the route. DONE, 2026-10-14.** `GET /api/pdc/preview/placement`, with the query shape and response above. Tests: every field of
`basis` is present and equals the request's; an unknown protein and an unknown chain are 400s with the file's own
chain list (the spelling `pdc_encapsulation` already uses); a domain refusal is not a 400 unless decision 3 says so.

**T3 — the panel card. DONE, 2026-10-14.** The markup, the proposed CSS, the NGL stage built when the card is visible with a
`handleResize` on tab show and window change (measured: a stage built at one width keeps that buffer — a 548 px buffer
inside a 759 px host until it was asked to resize), the staleness rule from decision 4, and the facts rows. Tests
(browser): the two halves still sit side by side at 1700 px and 1280 px with the card present (equal widths, different
x); the paired rows still share a y; changing the count re-derives and changing a subunit tick marks the frame stale
rather than redrawing; a refusal shows the reason and no canvas.
The card's viewer draws what `ngl-beads.js` draws, through that module's own parameters: the model's radius per size
class, times the preview's scale of **2**, with bonds at `BEAD_STICK_FRACTION` (a quarter of the bead since
2026-10-14) and `aspectRatio` **4** to keep the ball at the model's radius. The mock carries its own copy of those
numbers — a standalone page cannot import a module — and `tests/dashboard/unit/test_ngl_beads.py` holds the two copies
together, so the card has nothing of its own to remember.

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
Two notes for whoever reads this next: **the mock's five frames are the fixed ones** (re-derived 2026-10-14, see
*The two changes the user asked for, second round*), and the pre-fix measurement is kept in this plan as the record of
the defect rather than in the draft; and `pdc_view.system_pdb` truncates bead names to four characters, so
`TAIL1`/`TAIL2`/`TAIL3` all print as `TAIL` in the viewer file — harmless to the picture (they are bonded and drawn
identically) but a real collision for anything that reads names back.

**T7 — the thinner bonds and the frames: DONE, 2026-10-14.** `ngl-beads.js`'s `BEAD_STICK_FRACTION` is 1/4 with
`BEAD_ASPECT_RATIO` 4 (the product is 1, so the ball keeps the model's radius), the mock draws through the same
numbers, and the draft's frames were re-derived through the fixed code. Tests:
`test_the_ball_keeps_the_models_radius_and_the_stick_is_a_quarter_of_it` and
`test_the_mock_draws_the_same_bead_and_bond_as_the_module` (both fast tier, `tests/dashboard/unit/test_ngl_beads.py`),
and `test_the_sticks_are_thinner_and_the_balls_are_not_shrunk` (browser tier,
`tests/dashboard/browser/test_pdc_bead_radii_browser.py`), which reads the drawn radii off the buffers the
representation draws from.

## Not doing

- **Not drawing a schematic.** (c) is refused, in the plan and in the panel's own words.
- **Not rendering solvent or ions** the build does not have, guesses at, or could compute dishonestly.
- **Not predicting the micelle.** The assessment decides that, after CG MD, and this panel does not re-litigate it.
- **Not creating a run, a job or a manifest** from a preview, and not making it appear in the runs list.
- **Not touching the Complexes panel's own build door**, or what it sends.
- **Not adding controls to the panel.** The preview reads the fields that are already there.

## Verification

- `node --check` on every inline script of the mock, re-run after each change to its viewer (it caught a real syntax
  error once: an unterminated template literal that silently stopped the whole preview script). All five frames are
  `text/plain` data blocks and are not code.
- The mock's own measurement script, printed on the page, measured in a browser at 1700 × 1000 and at 1280 × 800 with
  the app's stylesheets and `vendor/ngl.js` from the running dashboard.
- The frames: re-derived 2026-10-14 through `pdc_placement` / `pdc_box` / `pdc_build.stamp` / `pdc_view.system_pdb` (see
  *The two changes the user asked for, second round*), with their bead and byte counts printed in the mock and in this
  plan; each frame's residue composition checked (230 `PRO` residues / 542 beads + 150 `DET` for chain A; 1 626 + 150 for
  the trimer; 1 650 `DET` for an empty micelle).
- **The orientation (2026-10-14), measured rather than argued:** on the pre-fix frames every detergent's head beads lay
  0.3167 nm **inward** of its own centre and its tails 0.8447 nm outward, in 0 of 660 molecules outward; every lattice
  centre sat exactly 3.000 nm from the micelle's centre. On the frames this plan now describes — the same inputs, the
  same seed, re-derived through the fixed stamp — every molecule's head beads lie 0.3167 nm **outward** and its tails
  0.8447 nm inward, **660 of 660**, with only the detergent `HETATM` records changed and every byte count identical. A
  fresh derive in a second interpreter and a second scratch tree is byte-identical (sha256); the build's own
  `system.gro` agrees with the derived frames to within half its rounding step (0.0005 nm); and a browser reading the
  frame the mock loads finds 150/150 heads outward (empty micelle) and 150/150 heads further from the protein than the
  tails (trimer). All of it from fresh interpreters against the checked-out tree — not from a long-lived session, whose
  stale import first reported the fix as having changed nothing.
- The drawn bead sizes, measured in a browser off the two buffers the representation draws from: the ball 2.64 Å (R),
  2.30 (S) and 1.91 (T) — the model's own radii, unchanged by the thinner bonds — and the stick halved from 1.32 Å to
  0.66 Å (tail) and 1.15 Å to 0.575 Å (sugar). The mock draws the same bead at twice those radii (5.28 Å) with the
  same stick, measured on the page itself.
- Tests: `tests/dashboard/unit/test_pdc_placement.py` and `tests/dashboard/unit/test_pdc_build_stamp.py` (see T6) and
  `tests/dashboard/unit/test_ngl_beads.py` (see T7), which pass; the fast tier as a whole was **not** green when the
  orientation landed, because another workstream was mid-flight in
  the same checkout (`osmotic.py` rewritten under a running test, T4's `cg_protein` tests written against a reader not
  yet in the tree). Recorded rather than tidied: the failures were in files this change does not touch, and the
  failing set changed between two consecutive runs of the same command.
- Once built: the fast tier, the browser tier, and `ruff check dashboard tests` (gate: F, E9, I).
