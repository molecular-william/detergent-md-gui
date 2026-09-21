# SDD ledger — plan: docs/superpowers/plans/2026-09-18-dashboard-performance.md
Approved design: preceding chat recommendation; user requested implementation.
No Git metadata: preserve rollback source in /tmp; isolated test stores only.

| Tasks | Shared contract | Ruling |
|---|---|---|
| Tab/New run and mapping/bonded | shared.js cache and tab activation | agreed exports in plan; separate owned files |
| Backend and frontend | opt-in summary/detail APIs | retain old API shape by default |
| Runs and backend | compact stage records, figure revision | summary retains capability checks; detail lazy |
| Each task | tests and boundaries | regression tests plus request count/payload evidence |

Completed: parent integrated all code after interrupting the frontend delegate;
retained and corrected its request-cache tests. Full suite: 164 passed, 15 existing
warnings; all nine JavaScript modules parse. Tests demonstrate lazy initial loads,
shared catalogue reuse, keyboard/hash/direct activation, preserved edits and
clone settings, readiness debounce/cancellation, cache rejection retry and
invalidation, compact/full API compatibility, and one indexed figure request.
Storage admission remains uncached. Measurements and verification evidence are
recorded in the plan. No remaining implementation tasks or data migration.
