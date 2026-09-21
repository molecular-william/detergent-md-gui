# Workflow Contract Clean-Break Design

## Goal

Make the maintained AA-only and AA-to-CG workflows use one explicit stage
contract and one current run layout. The fresh implementation must not carry
legacy DDM preparation, legacy flat-run fallbacks, or generic CG contracts
that still name DDM artifacts.

## Scope

This design changes execution code and its focused tests. It does not change
scientific force-field inputs, molecule validation rules, subprocess
ownership, resource limits, manifest provenance, or the distinction between
technical completion and scientific validation.

The new workspace starts empty. Existing generated runs, manifests, job
records, mapping drafts, bonded states, model registry records, compositions,
reports, notebook checkpoints, and compatibility-only files are outside the
new runtime and may be removed by the approved reset procedure. Canonical
source assets under `molecules/`, `references/`, and `resources/` remain.

## Design

`dashboard/execution/stages.py` becomes the single stage declaration surface.
Both adapters declare tuples of `Stage` objects. A shared function derives the
ordered plan and input/output contracts. Runtime code consumes the declaration
objects or the derived immutable plan; it does not maintain a second
adapter-specific tuple plus two dictionaries.

CG output contracts use the prepared molecule's `CGNames` values. A generic
run must never validate `DDM.itp`, `DDM_initial.itp`, or a DDM-specific report
filename unless the selected molecule actually resolves to those names.
Stage-local output resolvers may accept glob patterns for generated diagnostic
files, but required identity-bearing topology files are exact prepared names.

The maintained CG path always consumes a shared AA reference. Inline SwissParam
DDM preparation and the legacy reference validator are deleted. The coordinator
creates or attaches the AA-only source before admitting the CG consumer. A
fresh run always uses layout version 2 with `inputs/`, `stages/`, `logs/`, and a
manifest at the run root.

Fit-only is represented by an explicit workflow plan ending at CG topology and
assessment inputs. The runner executes the selected plan and marks the run
complete only after the last selected stage succeeds. It never breaks out of a
full plan and then reports a misleadingly complete run. The public run record
exposes the selected workflow stages so a completed fit-only run is complete
for its declared purpose.

The `dashboard.execution.ddm` re-export, legacy `prepare()` path, legacy
`execution_root()` fallback, and old reference validation are removed after
all maintained callers and tests use the current APIs. No compatibility alias
is retained for deleted internal symbols.

## Invariants

- Every selected stage records command, environment, inputs, outputs, hashes,
  timestamps, exit code, and log path.
- A stage can be reused only when its recorded output hashes verify.
- A run never overlays an old attempt or silently changes its molecule,
  mapping, force-field, or reference identity.
- A completed run has completed every stage in its declared workflow plan.
- A CG run has an identity-checked AA reference before preparation.
- All prepared executable paths stay inside the current run directory.
- A completed run remains `scientifically_validated: false` unless a separate
  reviewed scientific decision changes that field.

## Error handling

Missing dynamic outputs, mismatched molecule names, unavailable AA references,
and malformed stage declarations fail during preparation or admission before a
worker starts. A subprocess failure records the stage failure and preserves
the failed run directory for inspection. Cancellation remains owned by the
current worker process group.

## Tests and acceptance

- Unit tests prove `Stage` derivation for AA and CG, including exact dynamic
  topology names and diagnostic globs.
- Integration tests prepare a non-DDM molecule and assert that no DDM-only
  filenames enter its contracts or manifest.
- Workflow tests prove fit-only completion contains only its selected stages,
  resume verifies hashes, and a missing shared AA reference blocks admission.
- Existing command-construction, cancellation, failure-recovery, and
  manifest-provenance tests are updated to the current layout.
- GitNexus impact checks cover `Stage`, `stage_tables`, `execution_root`,
  `workflow.run`, `cg_adapter.prepare`, and coordinator run admission before
  implementation edits.

## Non-goals

This does not add protein orientation, micelle construction, new force fields,
automatic scientific model approval, or a second execution service.
