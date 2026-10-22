# Handoff and history

State, measurements and open items for this repository. `AGENTS.md` holds the rules; this holds the record they were
derived from. Read it before starting work on the DDM CG chain or the coordinator.

## Landed 2026-10-22: the bond panel reads in rows, detergents are placed by their bodies, and the device is a setting

Five commits, each with its own gate run.

`f120b49` **bond layout.** `.bonded-model-body` holds the seven inputs (three equal columns, three rows) with the
Torsion refinement fieldset beside them, and `.bonded-run-cards` puts Job and Result at half width on one row. Measured
at the browser tier's 1700x1050 viewport: fields 985x273 at x 49, fieldset 597x279 at x 1054, run cards 818 px each at
y 1183.7, card body 794 -> 279 px. The assertions are geometry, and one of them is `scrollWidth <= innerWidth` -- the
check that caught the `.hint` overflow on 2026-10-21. Assertions live in the cadence test because it is the only one
where a revision makes Result visible beside a job.

`da2bbf0` **placement geometry.** Three faults, each confirmed before it was changed: the clearance gate tested the
detergent's head *site* so a 2-3 nm body could cross the protein; `_self_assemble` returned one radial vector for every
detergent; and `pack_micelle` used `radius_nm` as the sphere's radius, so one selected subunit kept the whole complex's
3 nm shell. Now `detergent_profile`/`body_beads` gate every bead at `BEAD_CLEARANCE_NM = 0.25`, orientations are drawn
from the seed and flipped head-outward, and the sphere's radius is `max(radius_nm, extent of the selection + clearance +
detergent length)` with `radius_nm` a floor and `radius_source` recording which decided. `capacity()` bisects over the
placer's own gate across three seeds. Flipping orientations *after* the gate was a real bug the work found (a 0.012 nm
clash in a probe) and is pinned. Two old expectations asserted the defect and were replaced; the belt-selection test's
chain B had 24 atoms 0.26 nm apart, which is empty under a 0.25 nm gate, so it keeps six.

`495bf62` **preview and report.** The panel says what it measured (`the shell is 7.69 nm - measured from the protein this
selection includes - clearance measured against all 12 beads ...`) and offers `Use N` from the measured capacity, which
writes the field and queues nothing. `pdc_build` records `placement_shell`, `placement_capacity`, `orientation_policy`.
Two sentences that had become false -- the module docstring and the guide -- are corrected.

`0b4f161` **the device.** `-gpu_id 0` lived in eight places; `mdrun_gpu` (default 0) is now the only statement of it,
`aa.mdrun_command_flags` the only builder, and `workflow.py` exports `MDRUN_FLAGS_PME` so `aa_reference.sh`'s dynamics
legs stop carrying their own bracket. Byte-identical by measurement: the default returns
`-ntomp 8 -gpu_id 0 -nb gpu -pin on -pme gpu -pmefft gpu`. `execution/devices.py` probes `nvidia-smi` (recorded text in
every test, no GPU needed); prepare refuses an index the host reports and lacks, and does not refuse a host reporting
none; `environment.devices`, `stages[i].resource_usage.gpu` and `settings.mdrun_gpu` record what ran; the panel's select
carries a sharing note and never a refusal.

`7ac75ea` **AGENTS.md** went from 181 human lines to 118 by moving detail into `PROJECT_GUIDE.md`'s new *Module notes*,
and now states its own contract, enforced by `tests/dashboard/unit/test_agents_contract.py`: a 120-line budget, a fixed
heading set, every invariant naming code or a pointer, no dated narrative. The rule found two offenders on its first run.

**Owed:** `AGENTS.md`'s Verify counts still read 1,852 / 236 / 67 where the tree measures 1,890 / 240 / 67, and its
Invariants section does not yet carry the two device bullets (`mdrun_gpu` is the only statement of the device; a
prepared run records `environment.devices` and each stage `resource_usage.gpu`). Both edits need the write guard's
approval, which timed out twice; nothing is lost -- the text is in this record and in the GPU commit message.

**Decided 2026-10-22: the CPU budget is the run's.** `cg.RUN_EXECUTION_SETTINGS` now keeps `mdrun_gpu`,
`mdrun_ntomp` and `mdrun_ranks`, so an AA-to-CG form that asks for 16 threads and 2 ranks gets them on the atomistic
half as well as the coarse-grained one, instead of the dialect filter dropping them and the run executing 8 while the
panel showed 16. The AA reference's own recorded budget stays provenance -- what it cost to make -- rather than an
instruction to a run that consumes it. The offload schemes (`mdrun_nb`, `mdrun_pme`) are still filtered out of an
AA-to-CG run: they are choices about one half's execution rather than about the budget, and whether an AA-CG run should
own them is a separate question, recorded rather than answered.

## Landed 2026-10-21: one serializer, one store, one name per model

**One JSON serializer, and a migration that proves every rewrite, `657489a`.** `files.json_sha256` hashed with the
default separators while `mappings.identity` hashed compact, so one document had two digests and a stored hash meant
whichever module wrote it. The compact one survived because it is the one *compared* -- a parameterization is found by
`mapping_content_hash` at four sites -- so `files.canonical_json` is now the only serializer and `identity` delegates to
it. Mapping identities did not move (`b54dbab6…`, pinned by a test). `dashboard/cli/migrate_digests.py` keeps the old
serializer as an oracle and rewrites a record only when re-serializing its own body reproduces the stored digest; anything
it cannot prove it reports and leaves alone, and a second run is a no-op. **Measured on this workspace: 0 records carried
an old digest**, so nothing was rewritten here.

**The flat bonded-state store is gone, `1667ff5`.** `models/bonded/states.py`, its seven `/api/bonded-states` routes,
`paths.bonded_states`, the reset-list entry, `compositions.bonded_state()` and the `state_id` a composition wrote all
went. The `import-legacy` route was worse than dead: it called `coordinator.import_legacy_bonded_states`, which never
existed, so the one route meant to rescue an old workspace would have answered with a stack trace. Three test files went
with their subject; the layout guard now lists the module as retired, and a route test pins the seven paths answering 404
(a `POST` on a two-segment path answers 405 because the GET-only page route `/<section>/<panel>` shadows it -- true of
`/api/not-a-route` too, so it is the router).

**A parameterization records the mappings that claimed it, `2ad8aa5`.** `owners` on the record, `claim` on save,
`release` on a draft delete; the revisions go with the last claim. The draft store releases by name (the file is gone by
then) and falls back to asking the drafts on disk only for a record written before claims existed.
`cli/migrate_parameterization_owners.py` claimed the one record this workspace had (`10c318949ba5`, `DDM_CG_20261021`).

**One content identity is one saved mapping, `c8620be`.** `save_draft` refuses a second draft with the same beads, rings
and connections (`DuplicateMapping`, naming the file that holds it); the route answers 409 with `existing`; the editor
already withdrew Save-as-new from `duplicate_file`, and now also names the file and selects the existing mapping. A
rename is an in-place save, so it is not a duplicate. Writing that sentence exposed a layout bug worth more than the
copy: `.hint` had no `overflow-wrap` and the message sits in the dashboard shell, so a 40-character file name made the
whole document wider than the viewport -- `figure_viewer`'s `scrollWidth <= innerWidth` assertion caught it, and `.hint`
now wraps anywhere.

What this leaves: the "a second mapping with identical content gets its own empty record" half of the ownership design is
moot rather than blocked -- a second copy cannot be saved, so there is nothing to give a record to.

## Decided 2026-10-21, not yet built: three plans, and what each decision rules out

The user asked for plans and HTML drafts before any of this is executed; the drafts were measured in a browser at
1280 px (fields 664 px ending at x 753, torsion from x 773, three per row; Job and Result 558 px each at the same y).

**CG Bond Interactions layout** — `docs/superpowers/plans/2026-10-21-bond-panel-layout.md`,
`docs/design/drafts/bond-interactions-layout.html`. The model card becomes two columns (seven fields three per row, the
Torsion refinement fieldset beside them), Job and Result one row at half width. Pure presentation; the ids do not move.

**The mdrun device** — `docs/superpowers/plans/2026-10-21-mdrun-gpu-device.md`,
`docs/design/drafts/new-run-mdrun-and-placement.html`. `-gpu_id 0` is a literal in `aa.py:41-42` and `pdc.py:524`
today; it becomes a setting (`mdrun_gpu`), validated against `nvidia-smi` at prepare, with `environment.devices` and
`resource_usage.gpu` recorded per run. **Decided: device 0 stays the default** (byte-identical commands for every
existing run), and the convenience `auto` seems to offer is served by a *readiness note* naming the processes already on
the chosen device — measured when shown, never a gate. `auto` and resolving-`auto`-to-the-emptiest-device were both
rejected: the first names no device in the metadata, the second is a stale answer dressed as a measurement. One index
for now; `-gpu_id 0,1` across ranks is a follow-up.

**Detergent placement** — `docs/superpowers/plans/2026-10-21-pdc-detergent-placement.md`. Three faults, each with a
test that fails today: the clearance tests only a detergent's head site (the module docstring says so), `_outward` gives
every self-assembled detergent the cloud's radial vector, and `pack_micelle` uses `radius_nm` as the sphere's radius so
one selected subunit keeps the whole complex's 3 nm shell. Fixes: a bead-level body gate at 0.25 nm, orientations drawn
from the seed then flipped head-outward, and a shell measured from the selected subunits with `radius_nm` demoted to a
floor — the role it already has on the torus. **Decided: the aggregation number stays the user's**, with a capacity
report (bisection over the placer's own gate, three seeds) so a refusal says what the shell can hold and offers it;
auto-scaling needs a headgroup area this project does not measure. **Decided: the random cloud stays the default** and no
`belt-seed` mode is built.

### Open measurement: cloud versus rough belt

Not a task. One protein, one seed, two 100 ns assessment legs — a random cloud and a rough belt seeded tangent to the
measured hydrophobic surface — comparing `fraction_removed`, final aggregation number and belt thickness around the
slab. The reason it is a measurement rather than a switch: `pdc_assess` judges a run by the fraction of detergents
outside the counted micelle against `selection_threshold_fraction = 0.10`, and that threshold was calibrated against a
cloud's own removal rate. A pre-seeded belt passes it by construction, so adopting the belt also requires a pass
criterion a pre-seeded arrangement cannot satisfy trivially — a change to the assessment's science, not to placement
code. Until that measurement exists, the cloud is the control and the belt is unbuilt.

## Landed 2026-10-20, later: the panel stops choosing a profile, and offers only a mapping a run can reuse

**The `Execution` combobox is gone, and one route fallback had to move with it.** The control was visible only for
`cg_composition`, where `composition.normalize_settings` drops the profile argument by name, so the choice changed
nothing the run did; `aa_only` and `aa_cg` already hid it. It is removed from `dashboard.html` and every reference in
`new-run.js` is gone -- the panel sends no `profile` key at all. What replaced the panel's copy of the answer is
`protocol.profile_for_run_type` (`aa_cg` -> `cg.AA_CG_PROFILE`, every other type `standard`), read by the queue route
and by `/api/defaults`. **The order mattered:** with the control gone and the route untouched,
`/api/defaults?run_type=aa_cg` answered `cg_equil_ps` 5000 / `cg_production_ps` 100000 from its `standard` fallback,
and the form posts its fields back as explicit settings, so the run would have integrated 100 ns of CG production
while its own record said 10 ns. Measured after the fix: 10 / 10000, which is what the queue stamps. A regression
test in `test_dashboard.py` asks `/api/defaults?run_type=aa_cg` with no profile and compares it against
`cg.normalize_settings(None, cg.AA_CG_PROFILE)`.

**The CG mapping picker offers only what a run can reuse.** `new-run.js` filters `/api/mappings?view=summary` on
`validation.can_reuse` -- the same verdict `models/molecules/draft.py:38` refuses a run with -- so the browser does not
restate the rule and cannot list a candidate the queue would reject. On this workspace that is 6 saved candidates to
3, of which 2 are DDM's: the three dropped ones carry "Missing heavy atoms: 24, 25, ... 35". The `· needs repair`
suffix and the synthetic `Unavailable candidate · ...` option were removed with the filter; a remembered choice that
cannot run is left unselected rather than shown.

**Stage settings inputs are wider:** `new-run.css`'s `max-width` 6.5rem -> 8.5rem. Measured on the live panel: 104 px
-> 136 px at a 1600 px viewport, 115 px at 1265 (where the grid cell, not the cap, is the constraint), 136 px at
390 px with no horizontal overflow.

**The protein-detergent workflow got the same filter, `4fe57dc`.** It has two mapping pickers and neither asked
whether a build could use what it listed: the Complexes panel (`pdc.js`, `#pdc-mapping`) listed every candidate for
the template's molecule, and the New run panel (`new-run.js`, `#new-mapping`) listed them all and then defaulted to
the first. Both filter on `validation.can_reuse` now, and the Complexes queue button is disabled when nothing is
usable. Five browser fixtures had to say `can_reuse` with them -- a stub without it is a mapping list with nothing in
it, which is how this filter first showed up as four pdc files failing on a selected mapping they no longer got.

**The dihedral check reads the Fourier series Fast-Forward writes, `361f675`.** The first real fit in this workspace
(mapping `3dbdd5fb…` -- deleted by the owner at 18:37:49 on 2026-10-20, so the hash is history rather than something to
look up; AA reference `dbc366ae772b`, fast-forward) completed its revision with `dihedral-fit` recorded as
an error: `funct 9 is not a proper dihedral, and this reader has nothing to say about it`. `ff_inter` writes `funct 9`
-- one `phi C mult` triplet per line and eight lines for one quadruple, which is one dihedral as a Fourier series, not
eight dihedrals. The reader keyed on `funct 1` and so refused a topology its own tool wrote.

It now reads both and merges a quadruple's lines into one entry whose `terms` are its harmonics, with the largest-|C|
harmonic as the entry's scalar fields (the rule `publish` already used on the fitted side). A series has no single
phase to agree with, so the report gains `energy_rms_kj_mol`: the RMS between the two whole curves, with the constant
a series carries removed first -- each term is `C (1 + cos)`, whose mean is `C`, so a series carries the sum of its
coefficients as an offset the two sides need not share. On that fit, raw was 15.9 kJ/mol, the offset was 11.5 of it,
and the shape difference is 4.39 against the criterion's own residual of 2.48. Also `declared` in the report:
`{dihedrals: 1, multi_term: 1, harmonics: 8, functs: ['9']}`.

What that fit measured, one row and so not a diagnosis: `B01 B02 B05 B06`, both sides dominant 1-fold (-4.43 vs 7.26
kJ/mol), both curves bottoming out at -98 and -96 degrees -- the phase conventions are *not* mirrored there, so the
4.39 is shape. The stored revision 1 keeps its recorded error: a check is recorded rather than gating, and a stored
record is not rewritten after the fact. Re-fitting (the frames are staged; only the fit runs) produces the revision
whose check passes.

**A parameterized mapping can be deleted where it is edited, and the panel was told the wrong rule, `0b7de02`.** The
editor's confirm said a mapping's bonded states were *not* deleted; `mappings.delete_draft` deletes them -- it kept them
for another saved mapping carrying the same content hash until `c8620be` made that second copy unsaveable -- and removes
the fit jobs and staged frames too. It now states that, and the
notice afterwards reports what the route's answer says went -- the revision count, or who still holds the content. The
CG Bond Interactions panel gained a delete control beside the fit. It was first wired to the editor's own route, so it
deleted the *mapping*; on 2026-10-21 the user made it what the panel is about -- **Delete this parameterization**
(`DELETE /api/bonded-parameterizations/<content_hash>`), which takes the revisions, the fits that produced them, their
work and the recorded histograms, and leaves the saved mapping alone. It warns with the count the panel has read,
refuses while a fit of that model runs, is enabled only when the model holds a revision (and only for a saved mapping --
a `composition:<id>` entry is not one), and after deleting re-reads that model's record and says the mapping is
untouched.

**Live state, 2026-10-21: the DDM model's revision 1 holds 13 histograms, not 68.** It was fitted at 11:04:49 HKT,
inside the twelve minutes between `68847f2` (10:59:54, which copied the bonded family) and `48e62a2` (11:12:13, which
copies the tool's own `*distr.dat` glob). So its baseline covers every bond, angle and dihedral and **no** bead-pair
distance: a run of it today scores the interactions against real histograms and prints **0.00** for every distance,
which is the skipped-pair default and reads as a perfect match. One more *Fit this model* records all 68 in revision 2.

**The two engines keep separate analyses (the user's decision, 2026-10-20).** Fast-Forward's models are scored by
`ff_assess` against `refine_bonded`'s histograms; BARTENDER's models get BARTENDER's own graphs. Unifying them is
postponed. Measured while deciding: with `-noplot` removed, BARTENDER writes one figure per fitted parameter (29 files,
51 s, `Bond_Hooke_1-2.png` … `Simple_periodic_1-2-4-5.png`), exports **no** text histograms, bins at 0.001 nm / 1° / 10°
and analyses bonded terms only -- whereas `ff_assess` also scores every bead pair's distance distribution, so re-binning
BARTENDER's internals into the assessor's bins would invent a comparison. Kept for whoever builds the bartender route:
`ff_assess -f mapped.xtc -s mapped.gro -i <model>.itp -d . -dists .` reproduces `refine_bonded`'s 13 histograms byte for
byte in 7.8 s (`-dists` writes them; `-plot-data` does not). Until then a bartender-parameterized mapping cannot be scored -- and, at the user's
request, it runs: the empty inventory carries the reason and the assessment records `skipped` with it.

**The baseline was misplaced, not missing, `68847f2`.** The fit that produced revision 1 of the arm-B mapping had
already measured its reference's interaction histograms -- 13 files (4 bonds, 8 angles, 1 dihedral, the ITP's own
counts) in `parameterizations/work/10c31894...-dbc366ae772b/3_initial_CG` -- alongside 55 distance files. The
consuming path copied only the topology, so stage 5 looked in `3_initial_CG` (its `-d`) and found nothing. What landed:
`save(..., work=)` copies and hashes them beside the revision, `distributions()` reads them back,
`cg.prepare` stages them into `3_initial_CG` (verifying each digest, writing `distributions.json`, naming them in
`bonded.reference_distributions`), `use_parameterization.py` re-checks and records them, `delete()` takes them with the
mapping. A revision with none still runs (`74c996a`): `prepare` writes an empty inventory carrying the reason -- bartender's
own analysis is unbuilt, D6a -- and stage 5 exits 4 with it, so the run completes with the assessment `skipped` and the
step's tooltip says why. The existing revision 1 predates this and records none -- the
remedy is a re-fit (30 s), which appends revision 2; runs that already recorded the old digest keep it. One
correction to the copy (`48e62a2`): it takes *every* `*distr.dat`, the tool's own glob, so the 55 distance histograms
travel with the 13 interaction ones -- 68 files, 2.0 MB. A copy of the bonded family alone leaves the distance half of
the score unbaselined, and `fast_forward/score.py` skips such a pair rather than failing it, so its matrix cell reads
**0.00** (identical) for a comparison that never happened: the 0.00 matrix in `255eb0750d60`'s log.

**A run of this type died in assessment, and its progress bar counted nothing, `194ee69`.** Run `255eb0750d60`
(DDM, AA–CG, 100 ns, consumed `dbc366ae772b`) failed in stage 5 after 131 s: `report_interactions.out` says
`Overall Score : nan ± nan` with empty `bonds`/`angles`/`dihedrals` sections, and `validate_run.py` refuses nonfinite
scores. `ff_assess` printed `B01_B11_bonds_distr.dat file not found!` for every interaction, plus "your prefix is set
to the default value": it scores a CG trajectory against **pre-computed reference distributions**, and a run that
*consumed* a parameterization never produces them -- the in-run fitting path leaves `*_distr.dat` in `3_initial_CG/`
(which is why runs `22075892b606` and `a2a457cf9413` completed with the same `-d ../3_initial_CG` line), and
`use_parameterization.sh` does not. Nothing in this workspace holds them for `dbc366ae772b` either: AA-only runs have no
assessment stage. **The fix is a copy, not a re-measurement, and it landed in `68847f2`** -- see the entry below.

Progress: the run card had an ETA from GROMACS' log and no fraction, because a three-leg script stage (min, eq, md)
gives GROMACS' "remaining wall clock time" for one leg and `assess.sh` prints no step at all. `web/progress.py` now
counts the stage's own structure -- legs announced by `gmx mdrun -deffnm`, each leg's length from the mdp `grompp`
built it from, the step within the current leg from GROMACS' counter -- so two of three legs is 67% and half of the third
is 83%. It streams the file rather than reading a tail (leg markers stand at the start of legs), `run_view` carries
`progress` beside the ETA from one resolution of the stage and its log, and the card draws the bar with its leg, step
and percent. Measured on this failed run's own log: `leg md, 500000/500000, 100%`.

**New Run pins the AA source to the fit's run, `61618f0`.** A mapping carrying a parameterization chooses its own AA
reference on New Run: the picker locks to `aa_reference.run_id`, the AA half's settings are filled from that run's own
record and locked, deleting that source is hidden, and the CG settings stay editable. Measured live on arm-B:
`dbc366ae772b` locked, `aa_production_ps` 200000, `aa_nvt_ps` 100, `temperature_k` **303.15** where the panel's own
default is 300 -- the mismatch the pin removes -- two readiness calls for the interaction. The cost of getting it wrong
is recorded in the code and here: an `enforce` that treated a null readiness answer as "unlock" dropped and retook the
pin on every re-ask, eighteen requests in five seconds with the card never drawn; the pin is released on a *mapping*
change only, and releases its chosen source with it.

**The 3D diagram never drew a bonded term, `0a2e43a`.** Asked for dihedrals as dashed half-transparent lines, the
answer was that it drew nothing to style: the scene draws the mapping's own bead names (`S1A`, `TAIL3`) and a revision
names beads by export name (`B01`, `B11`; `mappings/exports.py` writes `B{i+1:02d}` over the mapping's bead list,
virtual sites included), and nothing joined the two, so every term missed its bead. On the stored arm-B revision: 28
table rows and 0 term traces before, 26 after `bonded.js` gained `revisionAliases`. Every kind now has its own style
(`bonded-plot.TERM_STYLES`): bonds green solid, constraints a darker green and left on the bond they fix, angles amber,
dihedrals green dashed at alpha 0.5, impropers slate dash-dot, virtual sites violet dotted with an open diamond drawn
for the bead itself (a solid circle reads as an atom the model lacks) and a star from the site to each parent, since the
term names the site alone and the parents live on the mapping's bead record. An angle is an amber **arc** between its
two arms (16 segments, radius 35% of the shorter arm, alpha 0.7), which is the notation the quantity has. A dihedral is
now an arc too, and one trace: the displaced **spine** names its four atoms (1.8% of the molecule's diagonal, 0.035 nm
on the 1.95 nm arm-B molecule, seeded per (kind, bead set) so the eight harmonics of one torsion coincide and a re-render
moves nothing), a null separates it from the **arc**, and the arc is the torsion itself -- the two outer atoms projected
onto the plane perpendicular to the central bond and swept between about its axis, **signed**, because the same four
atoms can turn either way and the two signs are different torsions. Alpha 0.7 for both arcs, up from 0.5 for the
dihedral and down from 1 for the angle. Two tags were added for it: one renders the plot module directly and asserts the
style contract, one drives the panel and asserts a stored revision's `B01…B04` terms arrive on the scene.

**A fit landed where the panel never looked, `6ba1d29`.** A fit from the CG Bond Interactions panel completed and
stored a revision, and the panel said `no parameterization` with the job box stuck on `queued`. One cause: a
candidate's content hash depended on how its numbers were spelled. The panel posts the mapping back through JavaScript,
which writes a file's `1.0` as `1`, so `rings[].scale` gave the file one digest (`b860d11b…`) and the posted snapshot
another (`10c31894…`); `fitting.start` keys the job and revision by the posted one, and everything that reads asks by
the file's. Measured then: the file's hash answered `parameterized: False` and `{"jobs": []}`, the posted one answered
revision 1 with 26 terms. `identity.candidate_identity` now hashes a number's value (`numbers_as_values`; `1.15` and
booleans untouched; `canonical_sha256` deliberately not normalised), reads fall back to `legacy_content_identity`, and
`fitting.work_dir` reuses a pair staged under the legacy digest. Second cause, fixed at the same time: the box polls
`?job_id=` rather than the mapping's hash, because the id is the job it queued and the hash is a different question
about a mapping. Nothing was left behind to clean up, and the note that said otherwise was wrong: `records/` holds
one record, the 18:38 fit's. The 15:38 fit's record went at 18:37:49 with the mapping it belonged to -- the request log
has `DELETE /api/mappings/drafts/mapping_candidate_2bcc24c3e5f149fab1e4f11f5d80ae0e.json` -> 200 -- and
`parameterization.delete` takes the record, that mapping's fit jobs and its staged work directory together, which is the
documented cascade working. The wrong note was written from a work-directory name seen *before* that deletion and never
re-checked against `records/`: the name outlived the record by minutes, and the inference did not.

**A mapping written by an agent's API check, not by the bead editor.** `workspace/dashboard/mapping_drafts/` holds
four candidates now. It once held `mapping_candidate_3f6d922c2f4b416dadacca7bc6f2f4ca.json` -- named plainly `probe`,
created 2026-10-20 09:34 UTC, `schema_version` 2, `molecule_snapshot` null -- which a session wrote as a deletion probe
rather than a mapping anyone meant to keep; it is gone. The fact it documented stays true for any record like it: a null
`molecule_snapshot` keeps it out of every molecule-scoped picker, so it appears only where the mapping list is unscoped
(CG Bond Interactions).

Measured: fast tier 1,792 passed in 17.4 s; browser 223 passed in 37.6 s at `-n 24 --dist worksteal`; `ruff check
dashboard tests` clean. The live page reads Run type · Method · Force field in the run-configuration row, two DDM
mappings in the picker, and 10000 ps CG production in the review row.

## Landed 2026-10-20: the in-flight lazy-Plotly slice, the waits that pinned files, and a fact-check

**Two slices a killed session (14:07 today) left uncommitted are landed and green.** `67411ac` takes the 4.8 MB
Plotly bundle out of every page load: `dashboard.html` publishes the route's URL in a `<meta name="plotly-src">`,
`web/static/js/plotly-loader.js` fetches it on demand behind one shared promise (an element in the document is the
record two module copies share; a failed load removes its element so a retry is not a wait on a dead script), and
both drawing panels await it. As handed over it was broken -- `mapping-validation.js` used `drawGeneration` with no
declaration, so the comparison panel threw a `ReferenceError` and 11 browser tests timed out. The slice also carries
a defect found while proving the click wiring: Plotly's first plot re-initialises the div's event emitter, so a
`plotly_click` listener added before `react` is dropped, and bead selection was dead in that window.

`e625716` rewrites the Run view's browser waits around a per-*draw* discriminator (`mark_stage` + `fresh=True`). A
per-file caption wait cannot tell a re-draw of the same file from the render already up, and `mapped.gro` and
`LIG1.pdb` are both eight-bead files. A temporary probe showed both old predicates true before the click, the new
wait timing out without one and satisfied in 0.32 s with one.

**Measured on the tree after all three commits:** fast tier 1,792 passed in 17.75 s (1,787 in 19.2 s before the
readiness slice); browser 223 passed in 37.07 s at `-n 24 --dist worksteal`; slow 66 passed in 64.4 s serial; 2,081
collected; `ruff check dashboard tests` clean; the four affected browser files 49 passed serially.
`scripts/gate_commit.sh` carried all three commits.

**Then the readiness probe, `393c66f`.** `probe_tool` was `@lru_cache(maxsize=8)` on the path string, so its answer
belonged to the process -- the one thing this file's own open item forbade, and worse than what it asked for: a tool
repaired under a running dashboard kept its first verdict until a restart. The cache is now keyed on the file,
`(str(path), st_mtime_ns, st_size)`, with a path that does not stat deliberately not remembered. `cg.readiness`
probes `gmx`, `ff_inter` and `ff_assess` through a thread pool and keeps `pool.map`'s order, so the checks list is
byte-identical while the wait is the slowest tool rather than their sum. The two readiness integration tests inject
the probe in every module that bound the name, and exactly one test still asks the real environment end to end.
Measured: `cg.readiness` 2.02 s cold and 0.01 s warm against ~5 s; three probes 4.8-5.1 s sequential against
1.9-2.0 s concurrent; those two tests 5.27 s and 3.79 s against 0.02 s each; `-k readiness` 11.4 s against 6.76 s;
the fast tier 1,792 in 17.75 s with five new tests; the live route 2.18 s on a freshly started process.
`pdc.readiness` keeps its sequential probes (1.83 s cold, a smaller payoff) and inherits only the cache.

**The fact-check that preceded them corrected five statements, three of which `AGENTS.md` now states correctly.**
The suite is 2,081 = 1,792 + 223 + 66, not the 2,065 = 1,787 + 218 + 60 this file gave; the slow tier's count was
never "60+", it is 66. `pdc.GENERATED_STAGES` holds four entries, and `0_prepare/pdc_prepare.sh` is copied like the
other `pdc_*` scripts rather than filled at prepare time. `cg.mdp_integration` stamps `dt` on the atomistic half
only; the CG timestep is the templates' own `dt` (`md.mdp` 0.02, `eq.mdp` 0.005), read back per file by `prepare`,
and a unit test pins `'dt' not in mdp_integration(cg_dir, ...)`. The retired-key comment and the cleanup fixtures
were closed by `89e3e2c`, not `4748261`. The coordinator paragraph further down named a pid and a log that no longer
exist: nothing is running and port 5000 refuses connections (started again 2026-10-20 14:49 as pid 3945138).

**Browser tier width, measured 2026-10-20 evening at 230 tests.** `-n 16 --dist worksteal` 47 s then 43 s, both green;
`-n 24 --dist worksteal` 37 s then 38 s, both green. The failed runs that evening -- four tests, then one, then eleven --
came with wall times of 62, 96 and 185 s for a tier that takes 37 on an idle box, i.e. another job was on the machine,
and the same tests fail at 16 as at 24. So `-n 16` is what `AGENTS.md` prescribes for headroom, and it is a choice
rather than a repair: the flakiness is load, not parallelism.

**The tier's expectation timeout is 15 s, `9118eb3`.** Every flake it has shown has one shape: an `expect(...)` naming
something a fetch fills in, expiring at Playwright's 5 s default while sixteen workers load the Plotly bundle and draw
WebGL scenes. The session fixture sets 15 s for the whole tier; after it, two runs at `-n 16 --dist worksteal` were 46 s
and 43 s green, against 45 s with two failures immediately before.

**Not reproduced.** The browser flake this file has carried since 2026-10-16 ran green twelve times (six at `-n 6`,
six at `-n 24 --dist worksteal`) after `e625716` rewrote its waits. One new intermittent was seen once and not
since: `test_the_across_molecules_card_refuses_to_call_different_edges_a_spread` failed 1 of 4 combined runs,
reporting `pairs_match: true` for edges that differ; neither `acrossTable` nor the transferability route is touched
by these slices.

## Landed 2026-10-16 → 2026-10-20: the panel, the reviews, and what four reviewers found

### Open items, with what to do next

1. **The readiness probe's cost and its cache -- closed 2026-10-20 (`393c66f`).** `environment.probe_tool` was
   `@lru_cache(maxsize=8)` on the path string, a cache for the life of the process, which is the one thing this item
   forbade. It is now keyed on the executable's `(str(path), st_mtime_ns, st_size)` -- an unchanged tool answers from
   the cache, a repaired one is measured again, an absent one is not remembered -- and `cg.readiness` probes its three
   tools concurrently, so the checks keep their order while the wait is the slowest of them. The two readiness
   integration tests inject the probe and exactly one still asks the real environment. Left undone, deliberately:
   `pdc.readiness`'s three probes stay sequential (1.83 s cold) and only inherit the cache, and four other readiness
   tests still spawn real probes (1.65-2.40 s each) when one of them is next touched.
2. **`pytest-socket` is not installed.** The suite makes no outbound HTTPS (measured), and nothing enforces it. Next:
   add it with `--allow-hosts=127.0.0.1,localhost` so a future fetch fails in the test rather than in someone's CI.
3. **The fixed panel diff has not been re-reviewed.** The skill's loop is review, fix, review again; `4748261`
   carries the four reviewers' fixes and no second review. Next: re-run the spec review over the panel files in that
   commit.
4. **The tier-level fast-tier intermittency.** One run once reported 4 failures; five runs on 2026-10-20 reported 0,
   two of them without a private `MPLCONFIGDIR`. Next: capture a failing run with `-p no:cacheprovider` and a fixed
   order -- a count that moves without a named test is not a diagnosis.
5. **A new, once-seen card intermittency.** `test_the_across_molecules_card_refuses_to_call_different_edges_a_spread`
   failed 1 of 4 combined browser runs on 2026-10-20, reporting `pairs_match: true` for `1B-1C`/`1A-1C`. If the route
   answers that, it is a defect in the card's reading rather than a flake. Next: stub the card's route to replay the
   payload and read `pairs_match` off it.
6. **The slow tier** was "60+ unmeasured"; it is measured now -- 66 tests, 64.4 s serial, and 2,081 in the suite.

**CG Bond Interactions now produces a parameterization, New Run shows which one a run will use, and deleting a
mapping takes its bond interactions with it.** `89e3e2c` carried the six routes, the panel (model card, Fit, job box
with cancel, result card, `source` column, revision strip) and the `02 · CG MODEL` card. The mapping-deletion change
followed with the rule that matters: revisions are keyed by *content* hash while deletion is by *name*, so a delete
removes them only when no remaining saved mapping carries the same content -- two drafts may legitimately share
content, and a name is not an identity.

**Four reviewers ran spec-then-quality, one per workstream, and two returned work.** All findings fixed: an
unfiltered jobs answer for a mapping with no record (`bonded.py` built `mapping_content_hash: None` and then filtered
nothing, answering `jobs: 3 of 3`); the "which jobs are this mapping's" truth implemented twice; three controls
deleted against the spec; a `fit()` response able to paint the screen after a newer selection; a fabricated `source`
fallback in the interactions table; a card link opening the panel on the wrong mapping; stale model state painted
under a newly picked mapping's name. The `bartender-fit` workstream passed as delivered -- its reviewer reproduced
the shared-reference measurement against the real run instead of trusting the comment.

**Measured on the tree after the fixes:** fast tier 1,787 passed in 25.5 s; ruff clean over every changed path;
browser tier 217 passed with one recorded flake,
`test_run_view_browser.py::test_a_cg_run_colours_its_beads_by_family_and_only_then_shows_the_legend`, which passes
serially (`-n 0`, 21 passed in that file). The flake predates this slice and is the next thing to chase.

**Suite speed, same pass:** the five subprocess-shaped files moved onto the `slow` marker, taking the fast tier from
35.8 s to ~26 s. `--durations` also named the readiness tests as the slowest single tests in the tier -- they probe
`ff_inter`/`ff_assess`/`gmx` per call, the same probe that makes a live readiness request sit at "Checking
requirements..." for ten seconds. Injecting the probe in those tests and keeping one real-probe test is the next
measured win, and it is not done.

**Not applicable, measured:** the suite makes no outbound HTTPS call, so no recording tool (VCR.py and the like)
has anything to accelerate; the product's single HTTPS fetch, `pdc_import.py:161`, is already behind an injected
`fetcher`, and every test supplies one. `pytest-socket` with `--allow-hosts=127.0.0.1,localhost` would turn that
audit into a guarantee.

## Landed 2026-10-16: the run type owns its fit, and a parameterization can be produced without a run

**The AA-CG run type now fits its own bonded parameters, and the three controls that made that a per-run choice are
gone.** `b56cddb` (22 files) removed `bonded_intent` and `bonded_state_id` from the run contract and the panel,
un-gated the mapping staging from the duration profile, renamed stage 3 to `CG parameterization`, and added
`kinds.default_for_run_types` / `published()` / `default_for()`. The decision rests on the run store rather than on
reading the code: of 8 jobs, `draft-smoke` was never used and `standard` was used only by the 6 `aa_only` runs;
`bonded_intent` was never `fit_only` or `reuse_state`; `bonded_state_id` was carried by none; and of 8 runs none wrote
`BOND_STATE.itp` and none has a `bonded_fit.json` holding a torsion. Measured at landing: fast tier 1735 passed, ruff
clean over 17 Python paths, browser tier 195 passed.

**Two defects found after it landed, both by measurement rather than by the tiers.** `d6a87fd`: `cg.readiness()` fell
back to `'standard'` when a caller named no profile, so an AA-CG run's mapping check never ran and the panel showed a
blocker about a profile no AA-CG run has used; the fallback is now `AA_CG_PROFILE`, which is also `prepare()`'s
default, and a test pins both. `740c3fa`: the tool probe failed for a cause that two of my own readings got wrong --
`environment()` inherited the caller's `PYTHONPATH`/`PYTHONHOME`, so a runtime that sets them pointed the tool's
interpreter at a foreign search path (`ImportError: cannot import name '_imaging' from 'PIL'`, from a python3.14
site-packages while the tool's own packages came from the project's python3.12). Both variables are dropped now, and
`probe_command()` hands a python console script to `sys.executable` rather than trusting a shebang that names an
absolute interpreter a moved checkout no longer has.

**A parameterization can now be produced without a run.** `44f8cc7`: `models/bonded/parameterization.py` (the revision
store), `models/bonded/fitting.py` (the job -- mapped frames from a linked AA reference, one of three engines, the two
checks, and provenance: engine, ensemble, `-constraints` threshold, temperature, frames, torsion model),
`execution/scripts/use_parameterization.{sh,py}` (stage 3 of a consuming run takes the model's terms and says in its
own artefact that it did not fit), and `prepare`/`readiness` record which of the two happened. Revisions are keyed by
content identity, so a rename keeps them and a changed bead assignment does not. The same commit closes the gap two
reviewers found independently: `queue_defaults` iterated `for_every_run()` and never asked `automatic_analyses`, so
`dihedral-fit` and `bonded-cross-check` were declared for AA-CG runs and queued by nobody. Fast tier 1811 passed,
ruff clean over 12 Python paths.

**Reviews over `b56cddb`/`d6a87fd`.** Spec compliance: PASS WITH GAPS, one substantive gap (the un-queued analyses,
now closed). Quality: the same gap, plus two minor findings still open -- `models/bonded/states.py:156` reads two
retired keys with nothing saying why (records written before D1), and the fixtures in
`test_temporary_validation_cleanup.py` key on the removed field, so the retention grouping is untested.
(Both closed in `4748261`: the retired-key read carries its comment, and the fixtures key on what the cleanup reads.)

**Standing decisions taken with the owner.** A parameterization belongs to the mapping and the bonded states are its
revisions, so a run consumes a model rather than a state id. Producing one is a job of the CG Bond Interactions panel
and makes no MD, so it is not a run. The engines are Fast-Forward and BARTENDER restricted to `-refit -owntraj` against
our own mapped trajectory; the reference-free `reference-informed` engine and its "Generate reference-informed draft"
button were removed on the owner's instruction (2026-10-20, `388b4b1`) because a revision nobody had fitted is not what
the panel is for. A model with no parameterization is fitted by the
run, which records that it did. The torsion model is a property of the mapping. `method: 'bartender'` remains a
provenance label, not a pipeline: no stage invokes the tool.

**Closed since.** The web half landed (`89e3e2c`, its review findings fixed in `4748261`), and
`bartender-fit`'s declared `1_AA-reference/prod/...` paths resolve through `reads_aa_reference` against the
paired AA run's `stages/07_reference/` -- a test now pins that substitution, which nothing covered before.

## Landed 2026-10-15: the gate, the mutation signal, and 29 property tests

**The gate the docs name exists in two places now, and the docs were right all along.** This file's "no CI" row
named `gate_commit.sh` as the repository's enforcement; a session on 2026-10-15 first reported that script as
absent from the machine, **and that report was wrong**. The error was a `find … -maxdepth 6`, which cannot reach
`~/.hermes/profiles/moldym/skills/software-development/detergent-md-dashboard/scripts/gate_commit.sh` -- ten levels
deep -- where the gate has lived since 2026-10-12 and where the skill's `references/verification-and-commit-gates.md`
documents it, browser-tier behaviour included. What was actually true is narrower and worth keeping: **the
repository carried no copy**, so a reader working inside the repo could not run the thing this file named.
`scripts/gate_commit.sh` (`c6ec468`, brought to full parity in the commit that corrected this paragraph) is that
copy: it resolves the repository from its own location so it needs no environment, captures each status from the
command itself rather than from a pipeline, gives `ruff` only the `.py` paths that still exist (a template parses as
Python; a deleted path arrives as `E902`), stages exactly the named paths with `git add -A --`, commits with
`git commit -F <message-file>`, and reports the browser tier on front-end paths without gating on it. Proven both
ways before it landed: a file with an unused import is refused with `gate: NOT committing (pytest 0, ruff 1)` and
nothing staged; its first real use caught an unused `pytest` import in a freshly written test file. Two copies of
one script is a trap of its own, so a behaviour change belongs in both -- or this file should name one of them.

**There is a mutation signal, confined to `analysis/` and the adapters.** `scripts/mutation_check.py` with
`scripts/mutants.json` (`901920a`) applies one mutation at a time, runs the test selection that mutant names, and
reports caught or survived -- eleven mutants, about four seconds each. Measured: **10 caught, 1 survived, 0 error,
0 stale**. The survivor is the control, a mutant whose replacement is its own target: a harness that cannot report
a survivor cannot tell "the tests caught this" from "the selection never ran". Three safeguards, one per way the
instrument could lie -- a target that does not occur exactly once is `stale` and fails the run; the file is
restored and the restore verified by hash; a module with an uncommitted change is refused rather than restored
over.

**What it found on its first run: the run card's range boundary was unpinned** (`2791f76`). Flipping
`aa.min <= cg.mean <= aa.max` to the strict form survived the whole fast tier, because every other fixture in
`unit/test_consistency_report.py` sits strictly inside the range or strictly outside it. The range is closed, and
the new test asserts both ends with values exact in binary (0.25, 0.5), so the comparison is *on* the boundary
rather than near it.

**Property tests, and the one defect the first of them found** (`ed5b2ab`). Three files under
`tests/dashboard/unit/`: `test_properties_mapping_schema.py` (arbitrary bodies; the ring-scale range from both
ends; the name and bead-count bounds measured after `strip()`), `test_properties_terms.py` (a written term read
back at every length; arbitrary text as well-formed or absent beads; the linkage's spread recomputed from the
result's own per-molecule means), `test_properties_mdp.py` (every key exactly once -- the `doubly defined`
refusal -- every value back through `cg._mdp_value`, the timestep on the atomistic half only, the barostat never
stamped). The validator property found the defect: `check_schema` read `data.get('representation_mode')` *before*
the isinstance test meant to refuse a non-dict, so that test was dead code and a list or `None` came back as an
`AttributeError` where the contract is the `ValueError` a route turns into a 400 -- latent rather than live, since
every mapping route goes through `routes/common.json_object`, which answers 400 first. `hypothesis>=6,<7` is
declared in `requirements-dashboard-tests.txt`.

**State, measured 2026-10-15.** Tests: fast tier **1,687 passed** in ~30 s, browser **173** in ~85 s, slow **7**
in ~19 s, **1,867 collected**; `ruff check dashboard tests` exits 0, repo-wide `ruff check .` exits 1 on the 19
pre-existing `micelle/` findings. Branch **432 commits ahead of `origin/main`**, HEAD `2791f76`, tree clean apart
from the untracked reference assets. Store: **8 jobs, all completed** (6 `aa_only`, 2 `aa_cg`) and **5 saved
mapping candidates**. Coordinator on `http://127.0.0.1:5000`, pid 280798, started 2026-10-14 18:27, logging to
`~/.hermes/profiles/moldym/cache/scratch/dashboard-1827.log`. **No cron jobs are scheduled and none is to be rebuilt** -- the user cancelled
the scheduled drivers on 2026-10-15 (see the cancellation note below).

## Where things stand (2026-10-05, linkage and surfaces work)
Tree clean except untracked reference assets: vendored M3-Lipid duplicates, `.git-upstream/`, the user's PDFs. **The M3-Lipid set stays untracked by the user's instruction. Do not tidy it into the index.** Nothing pushed since pre-refactor baseline `e0504a3`. The branch is 426 commits ahead of `origin/main`, HEAD `fe30ef2` -- both **as of this 2026-10-05 snapshot**; measured on 2026-10-15 it is 432 / `2791f76`, in the section above.

## Landed 2026-10-12 → 2026-10-15: the protein-detergent chain and the run view
**The protein-detergent chain is a real pipeline now.** `execution/adapters/pdc.py` owns ten stages and runs its own `pdc_*.sh` scripts rather than the CG half's: Protein preparation (optional PDB2PQR rebuild+protonation, `prepare_protein`, off by default, skippable), System preparation, Energy minimisation, NVT equilibration, NPT equilibration, **CG assessment MD (production only — it reads `../4_npt/`, so the chain no longer equilibrates twice)**, Micelle assessment, CG extension MD, Final assessment, Back-mapping (CG2AT2, a toggle). The three equilibration legs run `resources/templates/protein_detergent/{minimisation,nvt,npt}.mdp` (`pdc.LEGS`), and only `1_system/prepare_system.sh` plus those legs are filled at prepare time (`pdc.GENERATED_STAGES`). The prepare step's rules live in `execution/adapters/pdc_preparation.py` (measured on 4iar: 20 of 928 beads were `nan`, 312 missing atoms across 25 residues).

**The protein belt is a torus.** With a stated membrane the lattice places detergents on a tube whose centre-line is the protein's slab circle and whose radius is the detergent's measured length, heads on the outer surface and tails facing the centre (`pdc_placement._belt_torus`, `SHAPE_TORUS`); `radius_nm` is a **floor** on that centre-line. A build with no stated membrane — the empty micelle, a packaged protein, an import that states none — keeps the old sphere, where `radius_nm` is the radius (`SHAPE_SPHERE`).

**Secondary structure is mdtraj's, through martinize2.** The CG stage asks martinize2 with the bare `-dssp` flag, which vermouth answers with `mdtraj.compute_dssp` (`pdc_build.SS_SOURCE`); `MDAnalysis.analysis.dssp` is the recorded fallback (`SS_FALLBACK_SOURCE`). The two disagree — 42 of 230 residues on 1AT9 — so the assignment's letters are written into the run report. `mdtraj` and `pdb2pqr` are declared in `requirements-dashboard-tests.txt`.

**The osmotic run type is one run owning N concentrations.** `settings.molalities` is the plan; each concentration gets its own directory and its own checkpoint, resumed with `gmx mdrun -cpi`; `series_on_failure` is `carry_on` or `stop`; the type is gated to sugars. The one-concentration `osmotic_molality` shape is removed from the vocabulary, not deprecated.

**New panels.** A `Run view` in **both** workspaces (a chooser scoped per workspace by `web/sections.SECTIONS[...]['run_types']`, AA and CG structures through the artifact route, figures listed inline, the transport row under the canvas, `pdc` runs delegated to Complexes) — landed `98f5825`. The protein-detergent `New run` with a live **system preview** (`GET /api/pdc/preview/placement`, `execution/pdc_preview.py`) and the `prepare_protein` toggle, plus the encapsulation estimate and subunit/back-map choices. The `Osmotic Series` panel.

**Bead rendering and the bond rule.** One shared size table and one family colouring with an on-screen legend (`web/static/js/ngl-beads.js`: `BEAD_RADII_NM`, `BEAD_FAMILY_COLOURS`); `run-view-structure.js` decides the loader — a file carrying `CONECT` is drawn from those records and never guessed at, a coarse-grained file is `inferBonds: 'none'`, and only an all-atom file with no CONECT is left to the viewer's inference. `GET /api/jobs/<id>/structure` serves a run's coarse-grained structure with its own topology's bonds as CONECT.

**Snapshots run by default.** The `snapshots` kind carries `runs_for_every_run=True` (`kinds.py:194-205`) and `analysis_coordinator.queue_defaults` queues it for every run that reaches a terminal state; a run with no trajectory records `skipped` with the producer's reason and stays `complete`. The producer resolves the run's own layout (`observability.generate` → `layout.frame_source`): `07_reference/` for an AA-only run, `4_CG_sim/` for a consumer, and it records the trajectory, role and stride it used.

**The Run view's beads are drawn at 0.3, and the row can now produce the frames it plays.** `run-view.js`'s `BEAD_SCALE` (0.3) multiplies `ngl-beads.js`'s model radii at its own `applyBeadRadii` call -- the scale the New Run preview draws at too, so one mapped sugar is one size in the preview the reader judges and the run they then inspect. At 1 the beads read as one lump: a Martini 3 bonded pair sits 1.4-2.2 A apart at bead centres (measured on `a2a457cf9413`'s `stages/2_mapping/mapped.gro`, 1.40 A at the closest pair) while an S bead's own radius is 2.30 A, so every bonded pair overlaps by 2-3 A. The readout names the multiplier, the browser test asserts the class radius *and* the multiplier, and a source-level test holds the two panels to one number.

**A `Generate trajectory` control sits at the right of the frame slider.** It queues the `snapshots` analysis for the run on screen (`POST /api/jobs/<jid>/snapshots`) where that run has published no frame series, and is drawn disabled with its reason where it holds no `.xtc` under `stages/`. It reads the task's own status back rather than assuming one: `completed` re-reads the run, `failed` names the error. That re-read asks the route for `refresh=1`, and `runs.py`'s artifacts route now honours it: `artifact_index` is cached in the store and a *completed* run's index is otherwise frozen for the life of the process, so without it a run that had just published frames would show them only after a restart. The control's tests stub the queue route rather than clicking it against a live coordinator, which would start a real analysis.

**The series' cadence is the reader's, set before it is generated.** The producer took 40 evenly spaced frames and nothing else. `observability.generate` now also takes `interval_ns` -- nanoseconds per frame -- honoured in frames (`interval_ns * 1000 / dt`), capped at `SERIES_CAP` 200, and refused with its reason on a trajectory that states no time step. The series record states its own cadence (`interval_ns`, `duration_ns`, `frame_ps`, `requested_interval_ns`) so the note prints it and the prompt names it rather than re-deriving either. `kinds._snapshots` is the one adapter that forwards a payload to its producer and `routes/analyses.py` checks the cadence before queueing, so a cadence that means nothing is a 400 the reader can act on rather than a failure inside a worker. Measured on this workspace's own run: `md.xtc` holds 20,001 frames at 10 ps (200 ns), so the default 40 frames is 5.13 ns per frame, and 1 / 2 / 5 / 10 / 20 ns per frame are 201 / 101 / 41 / 21 / 11 frames. The protein-detergent chain's snapshot sampler is a *different* producer and defaults to 20 ns per frame capped at 20 (`adapters/pdc.py`).

**Replacing a published series is a question, not a click.** With a series published the control stays on the transport row's right -- that is how the cadence is changed -- and the cadence field sits on its own line under that row, because the row is `flex-wrap: nowrap` by decision and a fourth control in it scrolled the page sideways at 390 px (caught by the transport row's own geometry test, not by eye). Pressing Generate then opens a native `<dialog>` naming what is published -- the frames and the cadence, read from the record -- and what replacing means: this panel plays the newest attempt and the earlier one stays in the run's own analysis tree. Cancel queues nothing, and the test asserts exactly that.

**A frame series carries the run's own colours and bonds.** The first series this pipeline published was written straight out of MDAnalysis's PDB writer, which knows nothing a viewer here reads: measured, b-factor `0.00` on every bead and zero `CONECT` records, so the panel could only draw grey spheres with no connectivity beside the same run's own structure. A coarse-grained series and its three moments are now written through `pdc_view.series_pdb` / `system_pdb` -- the writer the run's own structure uses -- so every model carries the size-class element stand-in, the Martini 3 family code in the b-factor column, and the moleculetype's own bonds as `CONECT`, per model. An all-atom series keeps the reader's own output, because there the elements are real chemistry.
Two things had to reach the producer for that to work: the run's `3_initial_CG/*.itp` is now a declared source of the `snapshots` kind, and the worker stages the run's `manifest.json` -- the only place `FINAL_ITP` names which of six `.itp` files the simulation ran with -- before the baseline hash. Regenerating `a2a457cf9413`'s series at 1 ns per frame produced 200 models, 1400 `CONECT` records, family codes 1/2/3, and the panel draws it in three family colours with seven bonds per model.
Two fixtures were lying about the same thing and are fixed with it: their bead records sat a column off the PDB standard (a four-character residue name), so the element column was blank and a family code landed where no reader looks. A fixture that cannot carry a readable family code cannot fail when the colouring breaks, which is how this reached a published series.

**A frame series can be fitted, so a reader sees the molecule's own motion.** In a run's own coordinates a molecule does its own translation and rotation as well as its internal motion, and the first two dominate the picture: measured on `a2a457cf9413`'s 200 ns sucrose trajectory sampled at 1 ns, the raw RMSD to the first frame reaches 5.73 A while the fit leaves 2.31 A -- 60% of what a reader sees is the molecule moving as a whole. The `snapshots` payload takes `align`, the fit is Kabsch written out in the producer, and it applies to the series and to the three labelled moments (a strip button that jumped to an unfitted moment would leave the molecule where the series does not have it). The file carries a `REMARK 950 FITTED SERIES` line naming the reference model, the beads superposed and the RMSD left, so a composite cannot be taken for the run's coordinates, and the record carries the same numbers as `series.aligned`. The panel has an `align` switch beside the cadence, reports an installed fitted series, and follows it. One miss worth remembering: the row forwarded the cadence and dropped the switch, so a queued fit did nothing -- the payload and the producer meet in exactly one place, and that place is what a test of a payload setting has to exercise.

**A fit can be aimed at one fragment, and the file names the fragments.** Fitting on the whole molecule is not what a reader watching one sugar ring against another is asking for, and the numbers show why: on `a2a457cf9413`'s own 200 ns trajectory, holding all 8 beads still leaves 0.23 nm of motion spread over the model, while holding one ring still leaves the other two moving 0.57 and 0.61 nm -- the whole-molecule fit averages away exactly the motion they want to see. `align_on` names the fragment the fit is made on (the rotation and translation come from that fragment's beads and are applied to all of them), and the run's own `2_mapping/model.json` supplies the grouping -- read through `pdc_view.read_subunits`, so the single structure, the series and the record all name the same rings. The file carries them in the chain column (`A`, `B`, `C`, and the virtual sites as `V` for `VS`, which the REMARK states) plus a `REMARK 950 CHAIN LETTERS` line listing every fragment with its beads. A fragment the mapping does not place is refused, naming what it does state.

**A two-monitor layout draft sits beside the panel, for review.** `dashboard/web/static/run-view-draft.html` (served at `/static/run-view-draft.html`) is two NGL monitors side by side, each with its own `choose a run` combo above it, its own canvas and transport, and its own `what this run holds` / `frames` / `figures` sub-panels *below* the canvas, collapsed. Only completed runs are offered and the combo filters as you type. It reads the same API, so the runs and structures in it are real, and it *imports* the panel's own rules (`ngl-beads.js`, `run-view-structure.js`) rather than restating them. It opens on a coarse-grained run and the atomistic reference that run names in `reference_run_id`, and links the two monitors by *time* rather than by frame index, because two series rarely share a cadence. The draft and its test (`tests/dashboard/browser/test_run_view_draft_browser.py`) are to be deleted together when the layout lands in the panel; the draft is not a stand-in and nothing may read it as one.

**A run's figures are its current set, not every attempt's.** An analysis publishes its figures again on every attempt, so `/figures` listing the whole index read as a bug on screen: `a2a457cf9413` held 38 images, 33 of them the same three snapshot SVGs from eleven attempts -- "CG-first.svg, six times". `dashboard.analysis.runs.figures.current_figures` holds the rule (the newest set per analysis kind, `superseded` counting the rest, which stay on disk and reachable through the artifact index the Runs gallery reads), the panel and the draft both read it, and the draft's own bug of multiplying each artifact by its three-file list is gone with it.

**A canvas holds one thing.** The draft cleared only the component it had loaded itself, so picking a second run on one monitor left the first series drawn underneath it, holding its own frame 0 still while the new one played -- reported as a frozen snapshot that stays when play is pressed. `removeAllComponents()` before every load now, which is the panel's own idiom, and a test reads `compList.length` after two picks.

**The two-monitor layout, decided with the reader.** Of the suggestions the draft invited: the *comparison strip* under the pair is wanted (the runs' own figures and numbers first, with a button for optional parameters computed on the fly, since some of what a pair comparison needs is cheap to compute and none of it should be computed unasked); *pair presets* are wanted (each CG run with its reference); *remembering the pair and the collapse states* is wanted; *empty states on the canvas itself* is wanted (a monitor whose run has no series should say so under the canvas, not only inside a closed panel); and *cheaper reads* are wanted (the summary already carries `analyses`, so the task-list call per run can go). Not wanted, and recorded so nobody rebuilds them: locking the two orientations together, a shared time bar above the pair, a third column, a focus notion for a shared transport, and moving the old scope controls into the header.

**A `.gro` is bondless by format, not by intent.** The bond rule (`web/static/js/run-view-structure.js`) used to send every `.gro` down the coarse-grained branch and empty the structure's bond store, which is right for a bead and wrong for chemistry -- the one case the viewer's distance guess is right about. An all-atom `.gro` now keeps the guess, the published series is handed to the loader by the rule rather than with `inferBonds: 'none'` written into the call, and the run structure route's PDB answer (a `.gro`'s moleculetype written as `CONECT`) is loaded as the PDB it is. Measured on the atomistic reference run: 0 bonds stated, 46 resolved, where the panel reported 0 before.

**The Run view is two monitors.** The panel is the layout that was drafted and judged: two runs side by side, each with its own combo (a text input that filters as you type, completed runs only), its own canvas, transport and readout, and its own `what this run holds` / `frames` / `figures` panels below the canvas, collapsed. A monitor's whole job is in `web/static/js/run-view-monitor.js`; the host (`run-view.js`) owns the scope, the run list, the two combos, pairing, swapping, the time link and the remembered pair, and draws nothing. Every element id in the monitor is suffixed by side, so two of them cannot reach into each other, and its per-run work is the old panel's code moved rather than rewritten: the moments strip, `fit on:`, the overwrite prompt, the readout, the generate controls and the Complexes delegation all survive, per monitor. The pair opens on a coarse-grained run and the atomistic reference it names in `reference_run_id`, playback links by *time* rather than frame index, and `static/run-view-draft.html` and its test are deleted together with nothing left at either path.

**`a2a457cf9413` is the run this was built for.** It completed 2026-09-29, before `runs_for_every_run` landed, so it holds five `.xtc` files (`stages/4_CG_sim/md.xtc` the largest) and no `snapshots` attempt at all -- not even a `skipped` one. That is why its transport row drew two disabled buttons over an empty strip: every run that predates the default, plus any run whose analysis was skipped, is waiting for exactly this control.

## Where things stand (2026-10-05, linkage and surfaces work) — continued
### Landed
| commit | what |
| --- | --- |
| `a9c2b07` | cross-molecule signature says when its molecules named different edges (`pairs_match`) |
| `c46a632` | cross-molecule comparison route and card (Phase 3 surface), plus the panel's unpaged job read |
| `34392d6` | the reader's answer written under Task 3.3 |
| `8b9534a` | complex panel hint is the template's own limitation; a browser test red since `34af539` |
| `5a098b1` | a mapping states the ring distance scale its geometry was built with (arm B) |
| `75029f0` | CG topology lets Fast_Forward constrain its stiffest bonds (`-constraints 10000`, was 1000000000) |
| `c0a0b85`, `bff44f9` | ring head-to-head and arm C: what failed, and the six causes eliminated |
| `a20d844` | CG half keeps the barostat its template prescribes; `cg.py` no longer stamps `pcoupl = no` |
| `da99e89`, `c51e8db` | CG equilibration integrates at 10 fs, then 5 fs, by the user's decision |
| `8417284` | navigation rail moves right of the content |
| `cdb2ccc` | the linkage compared across molecules: the `inter` rows the pairs table cannot reach |
| `767c90d` | card 3 draws the run's solvent-accessible envelope analysis |
| `4fc2513` | BARTENDER fit returns: `-improperIncrement 10`, because the 1-degree default never converged |
| `672c196` | migration script's only public door gets a test; bonded module's tested privates documented |
| `aa318e0` | bead editor keeps one diagram (3D only); workspace subtitle shortened |
| `c6f018e` | bonded diagram draws the candidate's own molecule, not the packaged reference |
| `ce77222` | the delete test waits for the panel it clicks |
| `47346a1` | `AGENTS.md` compressed; history moved here |

Documentation commits between those are evidence too (`c46ae38`, `3ac600f`, `ab29fd0`, `6aca073`, and the later ones that correct them). Each records what an arm eliminated. Several were wrong about something a later measurement overturned. Read them as a sequence, not as conclusions.

## Phase 3 closed: same bead type across sucrose, maltose and trehalose
`GET /api/runs/transferability?ids=...` reads each run's own published comparison and the mapping from its own manifest. Card 5 of Mapping Validation draws it. Measured over `a2a457cf9413`, `22075892b606`, `4e4ff51e7417`:

| bead types | maltose | sucrose | trehalose | spread | molecules named |
| --- | --- | --- | --- | --- | --- |
| `SN6`/`SP1r` | 0.4222 | 0.4230 | 0.4226 | 0.20% | same edge each |
| `SN6`/`SP4r` | 0.3161 | 0.3160 | 0.3159 | 0.06% | same edge each |
| `SP1r`/`SP1r` | 0.3130 | 0.4019 | 0.4027 | 24.08% | **different**: `1B–1C`, `1A–1C`, `2A–2C` |
| `SP1r`/`SP4r` | 0.3464 | 0.3244 | 0.3339 | 6.57% | **different**: three edges against three others |

The 24% is not a transfer failure. It is one molecule's `B–C` ring edge against two others' `A–C`, three different bonds sharing two types. Reporting it as-is would answer the paper's question wrongly, which is why a signature carries `pairs_match` and the card names the edges behind every mean. Where the same edge is named in all three molecules, the types agree to 0.2% and 0.06%.

The linkage, which that table cannot reach, is compared too (`cdb2ccc`). Every row above is a constrained ring distance inside one residue, so the `inter` role never fired there and the interaction that actually differs between disaccharides was absent. It lives in the comparison's `terms`. For a two-ring molecule `terms` is nothing but the linkage. Measured over the same three molecules:

| term | types | role | spread | maltose | sucrose | trehalose |
| --- | --- | --- | --- | --- | --- | --- |
| bonds | `SN6`/`SP1r` | inter | **19.92%** | 0.310 | 0.298 | 0.363 |
| angles | `SN6`/`SP1r`/`SP4r` | inter | 26.06% | 131.060 | 121.993 | 100.363 |
| angles | `SN6`/`SP1r`/`SP1r` | inter | 34.61% | 100.898 | 99.017 | 69.785 |
| dihedrals | `SN6`/`SP1r`/`SP4r`/`SP4r` | inter | withheld | −97.21 | +5.42 | −118.22 |

The signature that agrees to 0.06–0.20% on ring edges is **19.92% apart on the linkage bond**. A dihedral's spread is withheld in the reader and in the card, because a mean of a wrapped angle is not a difference however it is subtracted. That is asserted, not merely commented.

## The DDM CG run: six arms, one failure, and the onset is stochastic
One mapping, one set of settings. Each arm differs from the one before by a single variable. The failure time, re-read from each run's own log rather than from the warning it was first quoted for:

| arm | run | variable | failed at |
| --- | --- | --- | --- |
| A, control | `860eb013a82c` | rings at measured x 1.15, `-constraints 1000000000` | **858.4 ps** |
| B, measured scale | `e08dc53410f9` | rings at measured x 1.0 (needs `5a098b1`) | 199.6 ps |
| C, FF's threshold | `6404c3951674` | `-constraints 10000`, so the stiff link is rigid | 113.2 ps |
| D, barostat | `207ff34ce8bc` | the CG templates' Parrinello-Rahman restored (`a20d844`) | 72.5 ps |
| E, 10 fs equilibration | `5bb303eb9ff5` | the Methods' exception, first value | 445.9 ps |
| F, 5 fs equilibration | `c48c50265874` | the same idea taken further (the user's call) | **53.5 ps** |

Arm E was read as a trend and was not one: it looked like 2–6x the arms before it until F, the same idea taken further, failed first of all. Arm A's own log showed 858 ps, the longest of the six. The honest reading is a stochastic onset across an order of magnitude, 53–858 ps, for configurations whose physics barely differs. None of the six variables moved it out of that band.

Six candidate causes are eliminated by measurement, each with the number that kills it. The ring scale (B). The stiff harmonic link at k 12964.8 and the integration instability it implies (C). The missing barostat: its absence showed as −583 bar, its restoration gave 1.36 bar and a 9% contraction to the right density (D). Energy pumping (`md.edr` flat, −14850 ± 120 kJ/mol). The box or a periodic image (2.54 nm clearance against a 1.35 nm cutoff). The bonded-pair exclusion convention: the published `SUCR` entry excludes only its ring virtual site, as ours does.

Then the parameters got the same treatment and gave a different kind of answer. The link's length is not a DDM defect: every one of our disaccharides states it at ~0.272 in its initial topology (maltose 0.272008, DDM 0.269607). The divergence from the published set's 0.357–0.417 is this pipeline's convention for this bead partition. Its stiffness is not a discriminator either: sucrose's fitted link is 24030.9 and trehalose's is 77167.6, six times DDM's 12964.8, and both run 200 ns with zero LINCS warnings. The fitted values are reproducible by resampling: cutting a stable sugar's series into 2,001-frame windows gives mean 2.7776–3.2655 and sigma 0.1546–0.2148, and DDM sits at **2.7731 / 0.1563**. DDM's fitted link is what a normal disaccharide's link looks like sampled that briefly.

One column separates DDM from all three stable molecules: the **sample size**. Every sugar's parameters were fitted from 20,001 mapped frames, a 200 ns AA reference. DDM's came from 2,001, 20 ns; its own reference run is labelled "DDM AA reference (short)". That is not a diagnosis, it is a confound, and it is the one being removed.

## The DDM chain in flight
`dbc366ae772b` is the same AA reference at 200 ns: same seed 20260928, same 4.0 nm box, same force field, only `aa_production_ps` 20,000 to 200,000. Its prepared production mdp is `dt = 0.002, nsteps = 100000000`, `nstxout-compressed = 5000`: the mapping stage sees 20,001 frames where it saw 2,001. Seed and initial conditions are unchanged, so **the new run contains the old one as its prefix**. That makes the comparison DDM against DDM, not an analogy with maltose.

Measured cost: the short reference ran at 676.9 and 590.5 ns/day in this box. The long one has been running at ~1250 ns/day.

The CG arm that consumes this reference -- `mapping_candidate_2bcc24c3e5f149fab1e4f11f5d80ae0e.json`,
"DDM CG from the 200 ns reference (matched sampling), published protocol, 20 ns" -- was **never queued**: the
scheduled driver that was to queue it is cancelled, so queueing it is a deliberate manual act now, and the item it
served is written off below.

Restart the coordinator after that arm completes. The user asked for this explicitly: the running process still held the Python module from before `cdb2ccc` and `767c90d`, so the linkage card and the envelope card showed their empty states. It was deferred so as not to orphan the 200 ns run's subprocess group; the window between the reference finishing and the CG arm starting is the natural seam. A later session restarted it, and both cards render since.

## The other stages' parameters, reviewed
- The AA half is right. `2321ee23a536` runs 2 fs with C-rescale NPT and then Parrinello-Rahman production at `ref-p = 1`: real pressure coupling at 1 bar, and the guide's 303.15 K for CHARMM36m.
- The CG half's barostat was missing and is fixed (`a20d844`). `cg.py`'s `mdp_integration` used to stamp `pcoupl: 'no'` over both mdps, so every CG production run was NVT with `ref_p` and `compressibility` as dead keys while the manifest recorded `pressure_bar: 1.0`. The templates carry C-rescale to equilibrate and Parrinello-Rahman at `tau_p = 12` to produce, and `cg.py` no longer overrides them. A grep for `pcoupl` in `cg.py` finds only a docstring saying it used to. Verified on arm D, the first arm ever to run the published protocol: mean pressure 1.36 bar against the NVT arms' −583 bar, the box contracting about 9% to the correct density. It failed anyway, and sooner.
- The CG equilibration is 5 fs (`c51e8db`, the user's decision). Same 10 ps as before, so 2,000 steps rather than 500. The template's `dt` decides it, and the adapter reads each file's own `dt` back when it turns the requested duration into a step count. The Martini 3 Methods exclude equilibration from the 20 fs rule without naming a value, so both 10 fs and 5 fs are defensible on the paper's authority. Neither is evidenced to help, which the six arms above show.
- Everything else is standard Martini 3 and matches the reference set: `dt` 20 fs in production, `rlist` 1.35 with `rcoulomb`/`rvdw` 1.1, reaction-field with `epsilon_r` 15, Verlet with `verlet-buffer-tolerance -1`, `nstlist` 20, frames every 10 ps.
- `ff_inter` is fitted at 303 K (`cg.fit_temperature` rounds the run's 303.15 for an int argument) and the thermostats are at 303.15 K, so the fit and the simulation agree.
- `-constraints 10000` (`75029f0`) is Fast_Forward's own default and it matters. A bond fitted above it becomes a rigid constraint, which is how DDM's inter-ring link (fitted at 12964.8) became rigid while maltose's (2985.6) stayed flexible.

## The cron drivers: cancelled by the user, 2026-10-15
The scheduled drivers are cancelled and every mention of them has been removed from this file and from the skill.
Nothing is scheduled, checked today: `~/.hermes/profiles/moldym/cron/jobs.json` reads `{"jobs": []}`, `cron/output/`
holds no files, and `hermes -p moldym cron list` answers "No scheduled jobs in profile 'moldym'". **Do not rebuild
one.** What they were, in one line: a no-LLM job that woke on a timer, asked the live API what already existed,
queued only the next thing that did not, and took itself off the schedule when finished. The narration of what each
one did went with them, deliberately -- what survives that matters is that the DDM arm one of the four existed to
queue was never queued, and that item is written off below.

## The coordinator
`http://127.0.0.1:5000`, concurrency 2 (`config/dashboard.json`), restarted for each Python change. Measured from `workspace/dashboard/jobs.sqlite3` on 2026-10-15: **8 jobs, all completed** (6 `aa_only`, 2 `aa_cg`) and **5 saved mapping candidates** -- the sixth was the stray head-only candidate, deleted through `DELETE /api/mappings/drafts/<name>` on 2026-10-15 with a byte-exact copy of it kept at `~/.hermes/profiles/moldym/cache/scratch/mapping_candidate_d17dac35a91a40ada85301877e70a7d1.json` (sha256 `4fdb9c92…`, the file's own). (The figure this section carried earlier — 38 jobs, 13 completed — described a workspace that no longer exists.)

**That process is gone, measured 2026-10-20: pid 280798 no longer exists, `http://127.0.0.1:5000` refuses
connections, and `…/scratch/dashboard-1827.log` therefore stops where the process did.** The paragraph this replaces
described it as serving code whose every file predated it, so no restart was owed; that is history now. A reader
opening this section should start the coordinator rather than assume one. The path this section used to name,
`…/scratch/coordinator-run.log`, is a stale file from an earlier process -- it stops at 2026-10-13 13:04 -- and a
reader who tails it concludes the dashboard is dead.

**Most of that list no longer exists, and saying so is the point of this paragraph.** Measured on 2026-10-15 with `find workspace/dashboard/runs -name "*<id>*"` and a query against `jobs.sqlite3`: the runs that survive are the eight the store still holds -- the four E3 runs (`a2a457cf9413`, `22075892b606`, plus the two AA references `a54ac8f64710`, `0bfa1a39ef76`), the two earlier sucrose runs (`13ba0a087fad`, `03875cf39790`), the second AA reference (`38f54e67f13d`), and `dbc366ae772b` (the 200 ns DDM reference). Gone from both the store and the disk: `2321ee23a536`, `8a73fe6448f2` (the pdc run that completed end to end), every one of the six DDM arms (`860eb013a82c`, `e08dc53410f9`, `6404c3951674`, `207ff34ce8bc`, `5bb303eb9ff5`, `c48c50265874`), and `1322f9e0782e` -- the BARTENDER run whose fitted link is quoted throughout the arms section above. Their numbers remain evidence about what the old code did; their directories do not exist to re-read, and a lost record has no substitute, so do not go looking for them in a later session and do not rebuild a file at the same path to stand in for one.

**`8a73fe6448f2`'s system is void for geometry.** It was built while `detergent_cg.bead_centres` divided by ten. Every DDM arm dies before any production sampling, so their coordinates are evidence about the failure and about nothing else.

## Still open

Checked against the tree, the live store and the running app on 2026-10-15. A row that was paid, or that was never
true, is marked rather than carried forward.

| item | state (2026-10-15) |
| --- | --- |
| the DDM CG run, Task 2.4 | **written off by the user, 2026-10-15.** Six arms failed with a stochastic onset and the six candidate causes are eliminated. `dbc366ae772b` -- the 200 ns reference the matched-sampling arm consumes -- is `completed`; that arm was never queued, its driver is cancelled, and no schedule may be rebuilt. The sampling question stays answered by the cheaper resampling control: a stable sugar cut into 2,001-frame windows reproduced DDM's fitted link (mean 2.7776, sigma 0.1546 against 2.7763/0.1563) |
| the tail-off control | superseded. Not a mapping edit: the validator refuses a candidate that leaves heavy atoms unmapped ("Missing heavy atoms: 1 ... 12" for the dodecyl chain), so it needs DDM's head as a molecule of its own with its own AA topology. The user set it aside 2026-10-05 |
| Phase 4: sucrose and maltose sources | `resources/validation/carbohydrates/targets-v1.json` still carries `availability: metadata_only` for both entries (re-read 2026-10-15); lead is `10.1016/j.carres.2004.12.038`. Deferred by the user 2026-10-05 |
| pdc phase C, the retry half | the contact rule **exists**: `micelle/validation.assess_micelle` builds the tail-bead contact graph, judges the largest cluster against the aggregation number, and reports `protein_contact_count` with its own stated limitation. What does not exist anywhere is a retry policy -- `grep retry` over `pdc_assessment.py`, `pdc_assess.py` and `micelle/validation.py` finds nothing |
| pdc phase D, back-mapping | **paid, and the earlier row was wrong.** CG2AT2 is vendored under `tools/cg2at/` (a clone dated 2026-09-30, `cg2at -> database/bin/cg2at.py`) and `dashboard/execution/scripts/pdc_backmap.sh` drives it; `docs/PROJECT_GUIDE.md:258` says the same. The sentence "CG2AT2 is not vendored yet" described the tree before that clone |
| pdc phase E | documentation; the pdc depth reference is `references/pdc-workflow.md`. Nothing else is claimed open here |
| D1's other half | **paid.** `runs.js:consistencyLine` renders the numbered line -- "Consistency: CG 6 of 6 ring distances inside the AA observed range" -- off the `consistency` field `/api/jobs` already carries, measured on both `aa_cg` runs as `{'compared': 6, 'outside': 0, 'pairs': 6}`. D1 asked for "inside the AA *spread*"; the card says *range* deliberately, because the spread is the cross-molecule comparison on the mapping-validation tab. A browser test pins the line |
| the iterative mapping refinement panel | **cancelled by the user, 2026-10-15.** The human review gate made the workflow more complicated than the decision it supported. No panel is built and no further increment is planned. What was already landed stays: `/api/refinement/reviews`, `/api/refinement/variants` and the `refinement-score` analysis kind, all from 2026-09-24/25, reachable and tested. Deleting them is a separate decision, not implied by this one |
| the micelle builder | paused at the user's request; `micelle/` is a partial skeleton and explicitly not a validated model |
| **no CI** | still no `.github/workflows` -- the path does not exist. Enforcement is `gate_commit.sh`: the script has lived in Hermes's skill directory since 2026-10-12 (and the skill's `references/verification-and-commit-gates.md` documents it), and as of 2026-10-15 the repository carries its own copy at `scripts/gate_commit.sh` (`c6ec468`) so a reader inside the repo can run it. It runs the fast tier and `ruff` over the named paths, stages only those paths, blocks on any finding, and reports the browser tier without gating on it. The browser and slow tiers still run only when named |
| **no coverage signal** | no coverage configuration and no per-line signal on which tests are load-bearing. Unchanged |
| **a mutation signal exists, and it is narrow** | `scripts/mutation_check.py` + `scripts/mutants.json` (`901920a`): 11 mutants confined to `analysis/` and the adapters, 10 caught, 1 survived (the control), about 4 s each. Extending the list is the next work here |
| **property-based tests** | three files landed (`ed5b2ab`): the mapping validator, the term reader and the MDP writer. Still unfuzzed: the published-artifact readers beyond `term_beads`, the export writers, and `pdc_placement`'s geometry |
| a stray mapping candidate | **closed 2026-10-15.** Deleted through `DELETE /api/mappings/drafts/<name>`; a byte-exact copy is kept at `~/.hermes/profiles/moldym/cache/scratch/mapping_candidate_d17dac35a91a40ada85301877e70a7d1.json` (sha256 `4fdb9c92…`) in case the head-only molecule is ever built. 5 candidates remain |

## Closed 2026-10-15
- The gate the "no CI" row named also exists inside the repo as `scripts/gate_commit.sh` (`c6ec468`, parity with the
  skill's own copy in the commit after it), proven refusing a red ruff and landing the commit after that.
- A mutation signal, confined to `analysis/` and the adapters, with a control that survived (`901920a`).
- 29 tests: 28 property tests over the validator, the term reader and the MDP writer, plus the range-boundary test
  the mutation check asked for (`ed5b2ab`, `2791f76`).
- The validator's dead type check, which raised `AttributeError` for a non-dict body instead of the `ValueError` a
  route turns into a 400 (`ed5b2ab`).
- The stray head-only mapping candidate, deleted through the route with a copy kept (`d17dac35…`).
- Three rows of this file that were wrong: D1's numbered line (present), CG2AT2 (vendored), the refinement panel
  (the spec was withdrawn). Two more that had gone stale without being paid: the fast-tier count and the cron
  list.
- Two user decisions, taken on 2026-10-15 after this verification: the scheduled cron drivers were cancelled and
  every mention of them removed; the mapping refinement panel was cancelled and its spec withdrawn.


## Closed 2026-10-12
- The suffix `pyproject.toml` measurement ("79.3 s serial / 19.6 s with these flags") is gone from that file.
- No `skip` remains in the browser tier: it reports no skips at all.
- `config/benchmark.json` and `config/performance.json` are deleted; the launcher flags live in the adapters and the measured benchmark table in the skill reference `aa-run-protocol-and-performance.md`.
- The bead editor's 2D depiction is gone (`aa318e0`), and the bonded panel's wrong-molecule bug is fixed (`c6f018e`).
