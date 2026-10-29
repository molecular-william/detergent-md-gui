# Dashboard reorganization implementation plan

**Goal:** Make source ownership explicit and separate tests and state from code.
**Spec:** ../specs/2026-09-17-dashboard-reorganization-design.md
**Stack:** Existing Python/Flask/SQLite, vanilla ES modules, pytest/Playwright.

- [x] Capture a source rollback archive and run the 139-test baseline.
- [x] Move model and analysis modules, separate shared tools and DDM preparation
  from stage execution; preserve run snapshot helper filenames and CLI behavior.
- [x] Add centralized Paths, create_app, application-owned coordinator and route
  blueprints. Exercise two applications with distinct writable stores.
- [x] Split browser code into tab modules, keep static URLs and browser storage
  semantics; move static/templates into web/. Verify the real browser flows.
- [x] Move tests into unit/integration/browser groups, consolidate shared fixtures
  and remove reads/writes of user-owned state from tests.
- [x] Implement guarded workspace migration with inventory, copy/hash proof,
  retained originals and rollback; apply only while source leases are available.
- [x] Archive prototypes/checkpoints/obsolete benchmark; consolidate docs and
  ignore generated state. Update supported launch and test commands.
- [x] Run full tests, syntax checks, isolated launch/browser checks and review
  remaining path references. Record migration and completion evidence.

No Git metadata exists. `archive/dashboard-development-20260917/source-before-reorganization.tar` supplies
a retained source rollback snapshot. Scientific outputs are preserved separately and never patched.

Verification and migration results: [completion report](../../../reports/dashboard/reorganization-20260917/REPORT.md).
