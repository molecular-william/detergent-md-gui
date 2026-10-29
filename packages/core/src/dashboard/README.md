# Dashboard development

Start from the repository root; `python dashboard/app.py` remains a compatibility entry point.

Source ownership, paths, run storage, backup/reset and recovery live in
[the project guide](../docs/PROJECT_GUIDE.md). Scientific status and limits live in
[DDM calibration](../docs/DDM_CALIBRATION.md).

Dashboard-local setup only:

- Tests live in each package's `tests/` tree (core, validation, pdc); shared fixtures isolate every writable store. Tier commands, worker split and
  the process-not-threads rule are in `AGENTS.md` (`## Verify`).
- Browser tests need the installed Python Playwright package and Google Chrome.
- Do not move an existing `.venv/`; its launchers contain absolute paths.
- `requirements-dashboard-tests.txt` carries the test-only imports (`pytest-xdist`, `playwright`, `vermouth`).

Carbohydrate validation is queued through `POST /api/jobs/<id>/carbohydrate-validation` for a completed source run;
the controls that used to launch it from CG Bead Assignment were removed. Attempts are immutable analyses. A setup
check is diagnostic-only; an evidence-complete report needs cited targets and the sampling minimums in the
carbohydrate validation design.
