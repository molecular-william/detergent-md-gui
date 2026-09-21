# CG bead assignment, bonded states, and analysis workspace

Status: design for final user review; implementation has not started.

This specification consolidates the user's dashboard request and answers to
Q1–Q22. It covers the existing local Flask/Python/GROMACS application. Micelle
builder development remains outside this change. Existing simulation outputs
remain immutable. No current run is restarted to deploy this design.

## 1. User experience

Use this exact navigation order:

**Runs → New run → CG Bead Assignment → CG Bond Interactions**

The explicit ordered list takes precedence over the original ambiguous request
to put the new tab “on the left” of CG mappings.

CG Bead Assignment owns the molecule/SwissParam source, bead names, atom
membership, types, massive/virtual site definitions, and canonical sugar-ring
identity. Keep the assignment form on the left and molecular visualization on
the right. Preserve existing mapping selection, generation, export, review,
and deletion workflows, subject to dependency checks.

CG Bond Interactions owns connectivity, constraints, bonds, angles, dihedrals,
fit options, and manual parameter edits. Move the current advanced bonded JSON
editor out of the bead-assignment tab. The main editor is a structured table
with an expandable generated ITP preview. The new page can start from a saved
mapping without parameters, a compatible completed Fast-Forward fit, or a copy
of an existing bonded state. “Load” initially uses the repository's saved
mappings and run artifacts; arbitrary external topology import is outside this
increment because atom identity and force-field compatibility need a separate
import contract.

Page layout: mapping and bonded-state selectors at the top; interaction tables
on the left; the AA 2D molecular structure with CG beads and connectivity on the
right. Keep saved-state identity, revision, source fit, reference, and validation
summary visible. Provide save, save as new state, fit, short validation, export,
and delete actions in the context of the selected state.

## 2. Domain model and reproducibility

One saved bead mapping supports multiple named bonded states. A state belongs
to one exact mapping identity/hash; it cannot silently follow edits to AA atom
assignments, bead order, types, virtual sites, or ring definitions. Changing
these creates a new mapping and requires an explicitly compatible new state or
refit. Matching bead count alone is insufficient.

A bonded state records:

- Stable state ID, mapping ID/hash, name, creation time, current revision, and
  parent state/revision where applicable. Empty names receive a readable unique
  default; names do not serve as storage keys.
- Origin: mapping-only, Fast-Forward fit, manually edited, cloned, or legacy.
- Exact AA reference and source run IDs/hashes, fitting method, temperature,
  force-field/tool versions, fitting options, and parameter hash where known.
- Explicit interaction identities, bead membership, function numbers, units,
  equilibrium parameters, force constants, multiplicities, and source of each
  term. Multi-term periodic dihedrals must survive loading and exporting.
- Protected paper geometry, explicit expert overrides, review status, and
  diagnostic links. Missing parameters are null/unset, never valid-looking
  zero defaults. Fitted or mechanically stable does not mean scientifically
  validated.

Save as new state is the default. The user-requested **Edit in place** option
retains the same named state ID but creates a new immutable revision and moves
its current-revision pointer. Existing revisions and run snapshots remain
unchanged. Display a confirmation naming the affected state; use an expected
revision check to reject concurrent stale edits. It must be impossible for an
edit to change an active or completed run's topology.

Before execution, every job snapshots its exact mapping and bonded revision,
records hashes, and stores the final effective ITP. Also preserve the raw fitted
ITP when fitting occurs. A saved manually edited ITP is not sent back through
Fast-Forward unless the user explicitly chooses refitting.

State deletion requires confirmation. Reject it while any undeleted job
references any revision of that state, including queued, failed, cancelled,
temporary, and legacy jobs. Show the blocking runs. Once those run records are
deleted, deletion is allowed. Parent-state provenance can retain the deleted
ID/hash without requiring its files. Mapping deletion must not orphan remaining
bonded states; expose those dependencies instead of silently cascading.

## 3. Bond editor and interactive diagram

Separate table sections for bonds, angles, dihedrals, constraints, and virtual
site definitions/links. Each row exposes supported function-specific parameters
and units. Preserve unsupported imported terms in a read-only preview with an
explicit explanation; never discard or approximate them silently.

Overlay CG beads on the existing AA chemical drawing using the same bead-to-AA
assignment geometry as the bead editor. Draw bonds between CG bead centers.
Show bonds by default; separate toggles enable angles, dihedrals, constraints,
and virtual-site links. Selecting a row highlights its participating beads,
assigned AA atoms, and ordered interaction path. Diagram selection focuses the
corresponding table row. For angles and dihedrals, show bead order and values in
the selection caption rather than drawing every term at once. Distinguish
constraints and virtual links with line styles as well as colors.

Connectivity edits must keep the massive-bead graph connected. Validate term
arity, unique bead membership, references, function/parameter counts, finite
values, unit/range rules, and duplicate interaction identity. Explicit
multi-term periodic torsions are distinguished by their term identities.
Changes update the diagram and preview immediately. Invalid edits block save
and execution with row-specific reasons.

Paper ring constraints are visible and locked by default. **Expert override**
shows a warning and requires explicit acknowledgement plus a reason. Record the
override on the saved revision and label the state as departing from the paper
geometry. Do not change canonical mapping scale metadata to disguise it. Only
explicitly supported constraint parameter changes are editable; positivity,
triangle validity, virtual-site consistency, and GROMACS preprocessing remain
mandatory. Overrides do not unlock arbitrary changes to massless-site identity
or exclusions.

The generated ITP preview and export must represent the exact topology that will
run, including every locked or unsupported preserved section. Bead assignment
and topology approval remain distinct from physical validation.

## 4. New run and fitting flows

Replace ambiguous profile-first selection with explicit intent while retaining
compatible backend behavior for existing jobs and campaign scripts:

| Intent | Required inputs | Execution |
|---|---|---|
| Fit and simulate | Mapping; compatible AA source/settings | Map AA, fit, publish state, simulate, assess |
| Fit only | Mapping; compatible AA source/settings | Map AA, fit, publish state and fitting diagnostics, stop successfully |
| Simulate saved bonded state | Mapping; complete compatible state; reference for assessment | Reuse exact parameters, simulate, assess; do not refit |

Mapping-only workflows may create a fresh AA reference or reuse a completed
compatible reference through the existing path. When reusing AA, retain the
current locked AA durations and reference temperature. Show which reference
and fitting temperature the state came from. Incompatible mapping/state/source
selections block launch with a concrete explanation.

Automatic continuation is the default for fit-and-simulate screening. Publish
the fitted state before CG execution so it is reviewable. Fit only provides the
review stop; it is a completed fitting job, not a paused MD worker occupying
resources. The user can then clone/edit the fit and start a simulation.

If fitting fails, stop before CG simulation. Preserve distributions, original
output, commands, and the diagnostic reason. Offer a diagnostic-only result or
manual editing of explicitly incomplete data. Do not publish failed/partial
parameters as a complete fitted state or silently substitute guesses. Failed
fits cannot launch MD until all required parameters are supplied and validated.

Retain the existing coordinator, subprocesses, admission limits, cancellation,
stage manifests, and immutable output layout. Reused or deliberately omitted
stages have explicit reasons in the manifest and timeline. Readiness must
reflect the actual selected intent; a reviewed mapping alone does not imply a
validated force field. Keep the old request shape working for saved campaigns
by adapting it explicitly to the fit-and-simulate flow.

## 5. Short CG validation from the bonded-state panel

**Run short CG validation** snapshots the selected mapping and state revision.
If parameters are missing, clearly offer fitting first using a compatible AA
reference. Reuse the same normal worker and stage implementations; do not add
a second simulation engine or execute GROMACS in a web request.

Defaults approved by the user:

- Minimization, 10 ps CG equilibration, 100 ps CG production.
- 300 K, 8 CPU threads, a newly generated and recorded seed for each attempt.
- Configurable durations and sufficient output cadence for short-run
  diagnostics; use 1 ps by default rather than retaining only about ten frames.
- Stability, interaction and distance comparison, and basic SASA diagnostics.
  Check reference temperature compatibility before launch; never change a
  reused AA reference silently.

Create a normal registered job with an explicit temporary-validation purpose
and state/reference links. Use an isolated temporary execution directory at
`dashboard/runs/<temporary-job-id>/analysis/bonded-validation/`, with its own
stages, manifest, logs, command provenance, input snapshots, and outputs. This
gives mapping-only states a location without requiring a prior simulation run
and follows the agreed per-run analysis placement. Centralize execution-root
resolution so all artifact, cancellation, assessment, and deletion paths agree.
The AA source is read/copied as an input, never the cleanup target.

Show the attempt and its status in the bonded panel, with a link to the ordinary
run details. Temporary jobs are visibly marked in Runs and can be filtered.
Label results as short screening, not physical validation. Temporary jobs are
never eligible as AA reference sources. Do not modify the source bonded state
based on the result. Users may explicitly save a derived state themselves.

### Retention and promotion

The user approved regular cleanup of temporary validation data. This permission
applies only to marked temporary jobs, never existing permanent runs or AA data.

Resolve the count/age interaction conservatively: protect the latest five
attempts per bonded state; among older attempts, successful ones become
eligible after 7 days and failed/cancelled ones after 30 days, measured from
terminal completion. Thus five recent attempts may remain indefinitely. This
interpretation is explicit for review; manual deletion remains available.
Protect queued/running/cancelling attempts, active leases, promotion in progress,
and any attempt whose results have undeleted dependent jobs.

Run an idempotent, bounded cleanup sweep at coordinator startup and at most once
per day while it is running. Record what was deleted, why, and when. Clean only
registered owned directories within the allowed temporary root; reject symlinks
and path escapes. Use the same lease/reference guards as explicit run deletion.
On filesystem failure, retain the job record and report cleanup failure for
retry. Never remove metadata first and leave untracked outputs behind.

Provide **Delete temporary validations** with a confirmation listing affected
attempts, while still protecting active work and dependants. Automatic expiry
removes the temporary job/reference record after successful deletion so it no
longer blocks state deletion. A minimal cleanup audit is not a live run reference.

**Keep permanently** promotes a completed successful attempt by copying and
verifying its snapshot, provenance, results, and logs into a normal permanent
run record before allowing the temporary copy to expire. Preserve its short
duration and screening status. Promotion never turns it into an AA reference or
a scientifically validated model. Promoted jobs reference the exact state
revision and therefore prevent deleting that state until the job is deleted.

## 6. Analysis figures, captions, and sizing

Continue to show one selected figure per run, with keyboard-accessible figure
tabs and zoom/pan. New analyses emit structured figure metadata beside results.
Metadata includes a stable figure kind, title, explanation of the ideal result,
metric identity and direction, units, statistics, sampling/frame range, source
hashes, relevant method settings, and artifact links. It is published only with
valid output; missing scores remain missing.

| Figure | Caption guidance |
|---|---|
| Score matrix | Lower mismatch is better: 0 means identical distributions; values approaching 1 indicate poor overlap for the current normalized scoring method. Explain the diagonal and bead-pair labels. |
| Interaction distributions | AA and simulated CG peaks, widths, and populations should agree. The curve height itself is not a quality score. Report the actual method's lower-is-better mismatch where available. |
| Distance distributions | Desired agreement is in distance distributions, not uniformly shorter distances. Separate deliberate rigid-ring expansion from remaining distance error. |
| Fitted interactions | The fitted model should reproduce the mapped-AA target density. This tests a fit; it does not prove the independently simulated CG trajectory agrees. Label harmonic/circular/periodic conventions accurately. |
| Surface overlay | Inspect spatial agreement after the stated alignment and distinguish raw-mapped, expanded, and simulated CG when available. A single aligned snapshot is not an ensemble validation. |
| SASA over time | AA and CG means and variability should agree; larger or smaller SASA is not inherently better. Report nm², ns, frame counts, mean and standard deviation. |

Do not label every available distance/statistic as a universal 0–1 score.
Wasserstein distances are in nm and have no universal upper bound. Parse the
actual artifact and method metadata. Explain that systematic within-ring
mismatch may reflect the intentional 15% expansion and constraints.

Legacy figures receive inferred captions through a lightweight classifier and
a visible **Legacy caption** indicator. Parse existing report values where
unambiguous, record their source, and do not invent missing statistics. Store
new derived caption metadata beside analyses, without rewriting old figures.
Caption changes alone must not rerun trajectories or surface calculations.

Initial display targets: score matrix fits within approximately 420×420 CSS px;
interaction and fitted-interaction figures fit within approximately 440 px
height; the surface scene uses about 520 px and SASA about 360 px. Preserve
aspect ratios and center smaller plots. Exact responsive dimensions may be
tuned during browser QA without changing analysis data. Zoom and Open original
remain available for dense plots. Reset fits to the figure-specific viewport,
not to the full card width regardless of image aspect ratio.

## 7. Surface overlay and SASA computation

Reuse `surfaces.py`, which already generates Plotly probe-inflated meshes and
massive-bead least-squares alignment. Expose the AA/simulated-CG overlay directly
in Analysis graphs, with optional raw/expanded CG traces from the same cached
data. Consolidate the existing surface comparison rather than duplicate it.

Align massive simulated CG beads to mapped massive AA COGs with a proper
rotation (no reflection), then apply that transform to the whole CG structure
and its virtual sites. AA and CG trajectories are independent; equal timestamp
values do not make their frames paired observations. Default to the first saved
production frame of each and display both timestamps. Allow explicit frame
selection without implying that this snapshot represents the whole ensemble.

Use Plotly HTML with opacity, trace visibility, camera rotation, and zoom.
Retain the structure inside the surface. Use the verified AA and Martini radii
and the run's explicitly recorded probe. Label the mesh **solvent-accessible
envelope**; it is not a reconstructed re-entrant solvent-excluded surface.

SASA over time shows AA and simulated CG traces on their own elapsed-production
time axes in ns, with nm² on the vertical axis. Compute statistics from all
valid selected frames, independently per trajectory. Preserve existing compatible
GROMACS SASA series and their provenance; do not recompute them merely to plot.
If old radius/probe provenance is missing or incompatible, identify that and
calculate a new derived series. Report missing/invalid frames explicitly.

Use a configurable display limit, initially 2,000 points per trace. Decimation
preserves extrema/endpoints where possible; it does not affect statistics or
the downloadable full-resolution series. Do not hide brief SASA spikes by
using a moving average as the only display.

## 8. Per-run analysis cache

Cache derived data within each owning run, e.g.
`dashboard/runs/<id>/analysis/cache/<kind>/<content-key>/`.
Separate numeric products (SASA series, selected-frame meshes, alignment) from
their Plotly rendering and captions, so display changes reuse computation.
Existing immutable analysis attempts remain the provenance/failure record.

Cache keys include only dependencies that affect that product: source
trajectory and topology/mapping content hashes, bead order, radius tables,
probe, selected frames/range/stride, alignment reference/settings, mesh
resolution where relevant, algorithm version, and relevant tool versions.
The render key additionally tracks presentation code; camera, color, and
opacity changes are browser operations. Changing SASA display point count only
rebuilds the view, not GROMACS SASA or summary statistics.

Hash finalized immutable source files once using their manifests; do not hash
entire trajectories at every UI poll. Unverified legacy inputs require content
hashing before reuse. mtime/size alone are insufficient scientific identity.
Do not cache a still-growing trajectory as final output. Perform analyses when
their required stages have finalized the inputs.

Concurrent requests for the same product share one admitted computation and
its progress record. Build into a private temporary directory; validate outputs
and publish atomically with a manifest. Never reuse failed/partial results.
Cache hits verify manifest/output availability and integrity. Existing cached
results load without recopying source trajectories or executing GROMACS.
Do not retain copies of entire source trajectories in each mesh cache entry.

Generate baseline SASA plots once their series exist. Generate missing surfaces
on first selection or as an admitted completion analysis; show waiting/running/
failed state within the figure panel and a retry action on failure. Opening a
figure repeatedly cannot enqueue duplicate work. For old runs, new derived
results use the same cache and metadata path. No per-run cache is shared across
independently owned run directories, per the user's choice.

## 9. Repository integration and migration

Extend the existing service instead of introducing another backend/framework.
Use the existing SQLite store for bonded identities/revision pointers and job
references, with immutable topology/snapshot artifacts. Reference checks and
state/run admission must be transactional so deletion cannot race job creation.

Responsibilities to preserve or extend:

- `mappings.py`, `carbohydrates.py`, `draft_model.py`: bead identity, canonical
  mapping, topology structure, compatibility validation.
- `bonded.py` and a focused bonded-state persistence owner: term validation,
  fitting, revisions, provenance, and exact topology reuse.
- `app.py`, `store.py`, `workflow.py`: intent validation, reference-safe state
  lifecycle, short/fit-only job execution, snapshots, admission and cancellation.
- `analysis.py`, `surfaces.py`, `observability.py`: cached numerical products,
  authoritative figure metadata, and legacy artifact interpretation.
- `dashboard.html` and focused frontend modules: navigation, bead/state editor,
  linked diagram interaction, run intent form, and figure presentation. Extract
  the affected owners from the large existing JS file as needed without an
  unrelated frontend rewrite.

Migration is additive and idempotent, with a database backup and recorded schema
version. Index existing candidate snapshots and fitted ITPs as read-only legacy
states, attached to the exact corresponding mapping. Distinguish the raw FF
output from the actual simulated topology; do not mislabel an overridden state
as an untouched FF fit. Record unavailable provenance explicitly. Derive legacy
records alongside existing runs instead of mutating their manifests or outputs.
Legacy states may be cloned into editable new states after compatibility checks.

Do not relabel old `optimization` metadata as effective fitting: earlier variants
did not apply it. Import the actual topology bytes. Existing jobs, retries, and
analysis artifacts stay readable. New GUI launches explicitly select a mapping
and either fitting intent or a compatible state. Old API callers receive an
explicit compatibility translation. Deploy backend changes only between active
workers; never terminate a simulation to refresh the dashboard.

## 10. Delivery sequence and acceptance evidence

Prepare implementation plans for three coherent increments after design approval:

1. Figure interpretation, compact sizing, reusable surface/SASA analyses, and
   per-run caching. This produces a independently usable analysis improvement.
2. Mapping/bonded-state separation, revisions, interactive editor, legacy
   migration, and explicit fitting/reuse intent in New run.
3. Temporary short validation, panel results, promotion, and guarded retention,
   built on the same state and worker owners from increment 2.

Acceptance tests must demonstrate:

- Two bonded states share one mapping; saving a new state and editing the named
  state in place both preserve earlier run snapshots and old revision hashes.
- State/mapping incompatibility, incomplete parameters, stale revisions, and
  references to virtual sites in unsupported terms block execution clearly.
- Protected constraints require acknowledged expert override and remain
  numerically valid; multi-term torsions and virtual sites survive ITP roundtrip.
- Table and diagram selections agree, highlight assigned AA atoms, and work
  with keyboard focus; mobile layout remains usable.
- Fit-only finishes without MD; reuse bypasses fitting; fit failure does not
  launch MD or publish a falsely complete state.
- Short validation uses exactly the selected revision, approved durations and
  8 threads, records a fresh seed, and supports cancellation and admission.
- Retention boundaries, latest-five protection, promotion, active leases,
  referenced-state deletion, symlink rejection, and partial cleanup recovery
  are tested using controlled clocks and temporary fixtures.
- Cache hits perform no repeated numerical calculation; meaningful dependency
  changes invalidate the appropriate product; simultaneous requests deduplicate;
  interrupted generation never appears as a valid cache hit.
- Full-frame SASA statistics remain unchanged by display decimation; all
  captions state the correct units/direction and distinguish legacy inference.
- Compact plot defaults retain readable captions, reset behavior, zoom, and
  original export. Desktop/mobile browser checks show no runtime errors.
- Existing runs and source hashes are unchanged by migration/analysis, and an
  existing campaign request still enters the correct workflow.

Use focused tests for scientific conversions, state transitions, deletion races,
commands, parsing, and cache invalidation; use real GROMACS preprocessing and
one approved short DDM validation for the end-to-end proof. No new long MD
campaign is needed solely to validate this dashboard refactor.

## 11. Review notes

All Q1–Q22 choices are represented above. Two reconciliations are explicit:
in-place editing updates a named state's current revision while preserving old
revisions; retention ages apply to attempts outside the latest five. Temporary
validation directories have their own owning job, so a bonded state need not
already have a simulation run. Runtime code and retention behavior have not
been changed by drafting this document.
