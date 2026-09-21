# Repository Cleanup and Readability Design

## Goal

Remove obsolete generated and compatibility material from the fresh repository
and improve readability at the execution, analysis, and HTTP boundaries without
changing the new public behavior or scientific calculations.

## Scope

The approved reset removes generated runtime state, reports, notebook
checkpoints, and compatibility-only files. It preserves maintained source,
tests, canonical scientific inputs, current documentation, and the paused
experimental `micelle/` package.

The application becomes a clean-break release. Old `/history`, `/run/<id>`,
and `/console/<id>` aliases, old DDM import shims, and legacy-only browser
storage fallbacks are removed. New API routes and browser storage keys are the
only supported contract.

## Design

Generated directories and local environments are excluded by `.gitignore`.
Notebook checkpoints and Python cache directories are removed from the working
tree. The reset procedure records what it removed; source directories are
never selected by a broad recursive cleanup.

Execution and analysis code is rewritten from compressed statements into
small named helpers with one decision per branch. The refactor keeps behavior
stable while making the following boundaries explicit:

- stage-entry creation and finalization;
- dynamic output validation;
- analysis source fingerprinting and result publication;
- numerical report parsing; and
- subprocess command construction.

The analysis modules retain native units, missing-value semantics, source
hashes, and scientific-validation disclaimers. Readability changes must not
turn diagnostic completion into model validation.

`dashboard/web/routes/models.py` gets shared request helpers for JSON-object
payload validation, molecule-context resolution, and consistent 400/404/409
translation. Route functions remain thin: parse the request, call a model
operation, and serialize the result. Endpoint paths, response fields, and
status codes in the new contract are documented and tested together.

The model registry and mapping routes use the repository helper from the
persistence spec. They no longer load records with ad hoc directory loops or
repeat broad exception handling. Validation errors remain domain-specific and
are translated at the HTTP boundary.

Documentation is consolidated around the fresh-workspace workflow. The old
compatibility and migration narrative is removed from active guides; archived
reports remain outside the maintained runtime. The current README points to
the three design/plan documents and states that old generated state is not
readable by the new release.

## Invariants

- Cleanup is path-contained, symlink-safe, explicit, and auditable.
- No source, reference, resource, test, or paused-package file is deleted by
  runtime cleanup.
- New routes reject malformed payloads before model code runs.
- Route handlers never expose filesystem paths outside the configured
  workspace or canonical input roots.
- Browser state uses one documented key namespace and one current schema.
- Analysis reports preserve units, source identity, missing values, and the
  `scientifically_validated` boundary.

## Tests and acceptance

- Cleanup tests prove generated paths disappear and canonical assets remain.
- Route tests cover malformed JSON, invalid IDs, stale molecule snapshots,
  missing records, and current response schemas.
- Static checks reject remaining imports of `dashboard.execution.ddm`, legacy
  route aliases, `jobs.json`, and old layout fallbacks in maintained code.
- Analysis tests cover named helper behavior, parser failures, missing metrics,
  source-hash changes, and immutable output publication.
- Browser tests run against a fresh workspace and assert only current tabs,
  routes, and storage keys are used.
- GitNexus impact checks cover route helpers, `dashboard.web.routes.models`,
  analysis worker entry points, and the deleted compatibility symbols before
  implementation edits.

## Non-goals

This does not redesign the dashboard visual layout, change scientific metrics,
remove canonical reference assets, or resume the micelle-builder project.
