# Dashboard directory reorganization

The user approved the preceding audit recommendations for implementation.
Preserve HTTP routes, scientific behavior, cancellation, resource admission,
reference dependencies, immutable run inputs and verified resume.

Move scientific modules into models/, analysis/ and execution/. Separate the
generic stage runner from DDM preparation, and shared tool configuration from
both adapters. Introduce centralized application paths and a Flask application
factory with one coordinator per application. Route modules own HTTP adaptation;
the coordinator owns worker state and locks. Native browser modules own tab state.
Tests move to tests/dashboard with fixtures isolating all writable stores.

Keep original scientific references canonical. Runtime data is configured as one
workspace root; old locations remain supported. A migration inventories source
hashes, checks coordinator/run leases, copies and verifies data before cutover,
and preserves originals for rollback. Never rewrite historical run manifests or
captured scripts. Archive obsolete prototypes/checkpoints and the hardcoded
benchmark separately from active code. Keep compatibility entry points only
where callers or historical invocations need them.

Consolidate developer guidance in docs/PROJECT_GUIDE.md and a short dashboard
README. No new framework or external service is required. Existing tests form
the behavioral baseline; add focused factory-isolation and migration tests.
