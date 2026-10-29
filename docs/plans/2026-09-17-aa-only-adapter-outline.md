# AA-only adapter implementation outline

> For execution: use superpowers:executing-plans to work through independently
> tested phases. This is the requested architectural outline, not implementation
> code or authorization to run a production simulation.

**Goal:** Run one pre-parameterized molecule in water directly from a molecule
directory, publish a reusable AA reference, and let multiple CG jobs consume it
without duplicating its trajectories.

**Architecture:** Extract AA preparation and execution from the DDM workflow into
an AA module. Keep the existing coordinator, SQLite job store, worker cancellation,
resource limits, logs, and immutable run directories. Use explicit per-run stage
plans selected by server-owned workflow definitions; preserve the legacy DDM plan.

**Tech stack:** Python, Flask, SQLite, subprocess-based GROMACS, existing trajectory
analysis libraries, and vanilla browser JavaScript/CSS. No new execution service.

**Design basis:** User decisions on 2026-09-17 and the design below. Read
`docs/PROJECT_GUIDE.md`, `docs/DDM_CALIBRATION.md`, and `molecules/README.md` first.

## Settled scope and invariants

- One molecule in water, neutral or charged.
- CHARMM36 July 2022 and its CHARMM TIP3P water model for the first release.
- Minimization → NVT equilibration → NPT equilibration → NPT production.
- The user supplies an existing AA parameterization. Generating charges, atom
  types, protonation states, and bonded parameters is outside this adapter.
- Molecule directory inputs remain canonical; each run captures immutable input
  snapshots, transitive topology dependencies, metadata, tool versions and hashes.
- AA-only needs no Martini mapping, bonded CG state, Fast_Forward tools, or CG
  scientific-validation gate. It still requires a compatible AA topology/protocol.
- Execution completion, technical reference eligibility, and scientific validation
  are distinct states. Completion does not establish convergence or model accuracy.
- Existing simulations and analyses are not overwritten or deleted by migration.
- No broad adapter framework or general-purpose dependency engine is needed.

## Pre-implementation baseline (historical)

`dashboard/execution/scripts/aa_reference.sh` already runs GROMACS minimization,
equilibration, production, and solute extraction. It assumes the packaged PDB,
`LIG1`, and an eight-thread execution configuration. It includes no ion placement.

`dashboard/execution/workflow.py` has a global AA–CG stage list. Readiness probes CG tools;
settings validation couples the output interval to CG duration; preparation loads
a CG mapping; resume follows the global list. Simply stopping after AA would
retain those unwanted dependencies.

`dashboard/models/aa_molecules.py` checks directory files and atom correspondence but
admits only the exact packaged DDM source. Its parser does not resolve ITP includes.
An `executable` boolean is consequently too coarse: AA and DDM-CG readiness must
be reported separately.

`/api/references` currently accepts completed DDM jobs with AA artifacts regardless
of job type. Reference reuse copies the AA directory. Deletion protects only
active dependents, which is insufficient once completed CG jobs share source files.

AA protocol facts: tutorial templates use NPT, while draft profiles override
pressure coupling to make them NVT. The current temperature override sets `ref_t`
but does not update `gen_temp`. The new protocol must not inherit those behaviours
implicitly. `spc216.gro` is a starting coordinate template; the force-field water
topology determines the TIP3P model.

## Proposed module ownership

| File | Responsibility |
| --- | --- |
| `dashboard/models/aa_molecules.py` | Catalogue, molecule identity, AA input/dependency validation, capability reporting |
| New `dashboard/execution/aa_workflow.py` | AA protocol settings, preparation, system topology, commands, output contract |
| `dashboard/execution/workflow.py` | Shared execution of a selected stage plan; plan-aware resume and provenance |
| `dashboard/app.py` | Run-type validation, dispatch, resource admission, dependency scheduling, reference API |
| `dashboard/store.py` | Atomic reference relationships and job lifecycle updates |
| New `dashboard/analysis/aa_references.py` | Reference publication, compatibility checks, immutable source resolution |
| `dashboard/web/static/js/main.js`, `dashboard/web/templates/dashboard.html`, `dashboard/web/static/new-run.css` | Real AA-only settings/readiness, compact summary and reference selection |

## Phase 1 — Separate run identity and stage execution

- [x] Persist `run_type`, workflow/protocol version and the actual stage plan in
  each new job and manifest; reject unknown types and incompatible submitted fields.
- [x] Make readiness, settings, preparation, execution, clone, retry and resume
  dispatch by run type. Cover clone submission as well as the main queue endpoint.
- [x] Select executable stage definitions on the server. Never execute arbitrary
  scripts or commands supplied by a client or untrusted manifest.
- [x] Preserve the existing DDM plan for legacy jobs; do not relabel them AA-only.
- [x] Test that AA requests do not load mappings or probe Fast_Forward, CG requests
  keep their gates, and persisted stage checkpoints/resume follow the selected plan.

Deliverable: a tested AA workflow branch that cannot accidentally run CG stages.

## Phase 2 — Consume real molecule directories

- [x] Admit any molecule with a compatible supplied CHARMM AA topology, rather
  than requiring its files to match the packaged DDM source.
- [x] Resolve local topology includes and the selected force-field dependency tree.
  Reject traversal, symlinks, missing files and unsupported include directives with
  explicit reasons. Preserve required dependency ordering in the generated `.top`.
- [x] Capture metadata, GRO, ITP and resolved dependencies into the run input
  snapshot; verify checksums before using it. Keep atom order stable.
- [x] Build the system topology with the actual `[ moleculetype ]` name, one solute,
  CHARMM TIP3P and matching ion definitions. Build solute index groups explicitly
  rather than relying on a residue named `LIG1`.
- [x] Use GROMACS preprocessing to check topology/coordinate compatibility and
  parameter resolution. Do not claim a homemade parser proves force-field validity.
- [x] Test a neutral molecule, a charged molecule and a non-DDM topology name;
  include missing include files, reordered atoms and incompatible force-field cases.

Deliverable: reproducible prepared AA inputs, independent of CG parameterization.

## Phase 3 — Implement the AA protocol

- [x] Prepare the box, solvate, and neutralize charged systems with the selected
  force field's monovalent counterions. Default to no added salt; record actual
  water/ion counts and net charge. Report inability to neutralize explicitly.
- [x] Use separately recorded stages for preparation/solvation, ion placement,
  minimization, NVT equilibration, NPT equilibration, NPT production and publication.
  Their separate output directories must allow later stages to leave earlier
  checksummed outputs unchanged.
- [x] Supply versioned MDP templates with CHARMM-compatible nonbonded settings.
  Set thermostat and initial velocity temperatures consistently. Generate velocities
  only when starting dynamics; continue subsequent stages from checkpoints.
- [x] Expose separate NVT, NPT and production durations, temperature, pressure,
  output interval, box padding and recorded random seed. Use 300 K, 1 bar and
  the current 1.5 nm padding as initial UI defaults; validate geometry/cutoffs.
  Default durations are starting protocols, never a convergence guarantee.
- [x] Reuse current worker-owned process groups, cancellation, capacity and disk
  checks; record exact commands and environment for each invocation.
- [x] Test command construction, continuation, temperature changes, neutralization,
  failure, cancellation and checksum-verified resume without long MD jobs.

Deliverable: AA-only completion through production with no CG dependencies.

## Phase 4 — Publish an AA reference with technical checks

- [x] Retain full-system coordinates, trajectory, TPR, checkpoint, energies and logs.
- [x] Publish a solute trajectory plus matching coordinates, topology/index mapping,
  source hashes, frame times and protocol metadata. Use GRO/ITP for analysis where
  the installed trajectory library cannot read newer GROMACS TPR versions.
- [x] Check readable/nonempty outputs, matching atom counts/order, finite coordinates,
  recorded time coverage and consistent frames. Record diagnostics for temperature,
  pressure, density and energy where available, with units and source provenance.
- [x] Atomically mark a completed AA-only job technically reusable only after these
  checks. Keep scientific validation/convergence separate; short screening data must
  remain visibly short and must not masquerade as validated reference evidence.
- [x] Filter `/api/references` by AA-only type, completion, verified artifacts,
  molecule identity, topology/force field and consumer protocol requirements.

Deliverable: an AA reference selectable without mistakenly including arbitrary CG jobs.

## Phase 5 — Share references with CG consumers

- [x] Persist a source job ID and immutable artifact hashes for every CG consumer.
  Resolve source paths from stored relationships, never client-supplied filesystem
  paths. Verify source hashes at handoff.
- [x] Update mapping/fitting commands to read the shared AA artifacts. Write new
  mapped trajectories and fitted outputs under the CG job. Do not copy the source AA
  trajectory into every CG run. Any necessary analysis scratch copies are temporary
  and accounted for explicitly.
- [x] Protect shared AA sources from deletion while any retained consumer depends
  on them, including completed consumers. Perform dependency attachment/deletion
  checks atomically; disk reporting counts canonical source storage once.
- [x] For “AA–CG with new AA”, create a distinct AA job and a CG job waiting for it.
  A waiting CG job must not occupy the only simulation slot. AA failure/cancellation
  produces an explicit blocked/cancelled consumer state without running CG commands.
- [x] Keep old combined runs readable. Inventory any proposed legacy reference
  extraction separately; do not silently classify combined runs as AA-only or delete
  historical AA copies in this change.
- [x] Test two consumers sharing one source, altered/missing source artifacts,
  source deletion with completed dependents, and scheduling with concurrency one.

Deliverable: the previously agreed shared-reference workflow works end to end.

## Phase 6 — Connect the GUI and verify acceptance

- [x] Enable AA-only launch once backend readiness passes. Show AA settings and
  GROMACS requirements only; preserve CG selections when switching modes.
- [x] Make the compact review reflect actual run type, protocol, durations and source.
  Keep the immediate launch blocker visible; put detailed checks/hashes behind the
  existing disclosure. Show actual per-run stage checkpoints in Runs.
- [x] Lock inherited reference settings, preserve manually edited values when switching
  back to a new reference, and enforce the same conditions server-side.
- [x] Add self-contained API/worker/browser fixtures that do not depend on deleted
  legacy mapping files. Cover submit, clone, retry and resume for each run type.
- [x] Run focused unit/API/browser checks, then a short real GROMACS acceptance run
  for neutral DDM and one independently sourced compatible charged fixture. Record
  source provenance and keep the short tests explicitly unvalidated.
- [x] Confirm a non-DDM molecule reaches AA production without any CG mapping;
  two CG consumers link to one completed AA-only source without AA trajectory copies.
- [x] Update project and molecule-directory documentation with protocol versions,
  outputs, eligibility rules and compatibility limits.

## Verification record — 2026-09-17

Implementation and acceptance evidence are recorded in
[the AA adapter report](../../../reports/validation/aa-adapter-20260917/REPORT.md).
The checked items describe this first-release scope, not general force-field or
scientific validation. Unit/API tests cover both run types, clone/retry/resume,
source integrity/deletion, and scheduling. Browser checks cover directory-based
AA submission and paired AA–CG creation. Real short DDM and CHARMM ammonium runs
completed all seven AA stages; two separate consumers completed shared-source
mapping. Full downstream CG fitting/production against these new AA sources was
not part of this short acceptance check.

The final lifecycle tests also exposed and fixed a resume admission bug: the
endpoint's own inspection lease was counted as an external simulation worker.
Inspection now releases that lease before admission while retaining the
coordinator lock; preparation reacquires the source lease and verifies hashes.

## Acceptance boundary

The adapter is complete when a compatible directory can produce a verified AA-only
reference, show accurate resumable stages, and be reused by CG jobs under the
established immutability and deletion rules. Multi-molecule aggregates, protein
systems, arbitrary force fields, AA parameter generation and automatic convergence
claims are separate work.
