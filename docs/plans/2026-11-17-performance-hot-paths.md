# Plan: performance hot paths (live-log scan, per-poll work, cold page load)

Status: implementing (2026-11-17). Source evidence: the audit that produced this plan, measured read-only against
`workspace/dashboard` — a running run's whole stage log is rescanned on every poll (0.94 s per 52 MB, 0.98 s per
108 MB), `/api/jobs` builds every row before it hashes its ETag, each live worker re-walks `runs/` every 5 s, every
SQLite read opens with DDL and `BEGIN IMMEDIATE`, and a cold page load ships 49 requests / ≈2.35 MB with a 1.28 MB
parser-blocking NGL script. Prior art: `docs/research/2026-11-09-performance-polling.md` (which named "trim
`progress()`'s full-log read" as the fix to make if the poll proved server-heavy) and the delivered slices in
`docs/plans/2026-11-09-performance-follow-up.md`.

## Slices (disjoint write scopes)

### A. Live log scan: read only the new bytes
- `packages/core/src/dashboard/web/progress.py`: a bounded, lock-guarded per-file scan state keyed
  `(resolved path, st_ino, st_mtime_ns, st_size)` that keeps `(consumed offset, legs, grompp)` and resumes from the
  offset when the file only grew; rescan from zero when it shrank or was replaced. `scan()` gains optional
  accumulator arguments so an incremental pass produces exactly the array a full pass would.
- `packages/core/src/dashboard/web/views.py`: `eta()` caches the 64 KiB tail parse per `(path, mtime_ns, size)` the
  way `performance_ns_per_day` already does; `detail_revision` is cached per
  `(manifest path, mtime_ns, size, run_type)` so a summary poll does not re-serialise and SHA-256 every manifest.
- Semantics: same readings; legs only move forward while a run writes. A replaced file (new inode, or a smaller size)
  is rescanned, never continued.

### B. Route-level duplicate work
- `packages/core/src/dashboard/web/routes/runs.py`: `figures_api` does one `lookup`, drops the `revision` field no
  client reads, and answers its conditional request from `artifact_revision`.
- **Not implemented: a pre-build ETag for `/api/jobs`.** After slice A the payload build costs ~1 ms per row, so the
  measured 9.7 ms saving does not justify a marker that must also carry every running log's size/mtime or the
  progress line freezes — the risk both 2026-11-09 audits rejected. A is the root-cause fix; this stays open and
  documented rather than half-built.

### C. Background quota and queue polling
- `packages/core/src/dashboard/execution/coordination/resources.py`: `usage(runs_root)` is TTL-cached (10 s) for the
  worker's 5 s check, and `check_worker` stops walking the run twice by measuring the run once and the root once.
  A stale-by-10-s quota answer cannot admit a run: the limit still stops the worker, only the observation moves.
- `packages/core/src/dashboard/execution/coordination/analysis_coordinator.py`: the two 50 ms SQLite busy-wait loops
  back off (0.05 → 0.5 s cap) instead of re-reading the record 20 times a second.

### D. Store read path
- `packages/core/src/dashboard/store.py`: one `read()` context (no `mkdir`, no `CREATE TABLE`, no `BEGIN IMMEDIATE`)
  used by `get`/`all`/`names`/`retired_names`/`page`/`artifacts`-read; the write context keeps the DDL and
  `BEGIN IMMEDIATE`, and the schema is created once per file (the `_WAL` once-per-path pattern).

### E. Browser cold load and poll hygiene
- `app.py`: `SEND_FILE_MAX_AGE_DEFAULT` one hour, so the 49 subresources stop revalidating on every navigation.
- `dashboard.html` + a new `ngl-loader.js` modelled on `plotly-loader.js`: NGL becomes a lazy `<meta name="ngl-src">`
  load instead of a 1.28 MB parser-blocking `<script>` in `<head>`, with the three consumers awaiting it.
- `main.js`: engine panels mount from the static graph; a feature's *panel* module is imported when its tab first
  opens (extensions that only register hooks stay eager). `pdcSetRun` is already promise-backed.
- `run-view-analysis.js`: fetch `/figures` only on the settling tick or when the drawn signature moved.
- `run-view.js`: one `/api/jobs` request with repeated `run_type`, not one per type.
- `run-view-pdc.js`: the 2 s whole-trajectory poll is gated on the Run view panel, not just page visibility.
- `runs.js`: stop re-arming while the document is hidden; `whenLive` already resumes.
- `new-run-pdc.js`: one `AbortController` per debounce so a superseded preview/extent request is cancelled.

### F. Catalogue and index re-reads
- `web/routes/molecules.py`: `/api/molecules` answers from a 10 s per-process cache (same convention as
  `/api/storage`), so a panel mount does not rescan the catalogue.
- `analysis/runs/observability.py`: one `analysis-metadata.json` read per directory inside a walk.
- `models/bonded/fitting.py`: a `job_id=` poll reads that one record instead of globbing and parsing every job file.

## Verification

Each lane runs the narrowest test that pins its change (`-n 0 -p no:cacheprovider`, private `MPLCONFIGDIR`); the
integrator then runs the fast tier, `ruff`, and the browser tier once, reads `git status` in full, and commits through
`scripts/gate_commit.sh`. Measured before/after: one `views.run_view` on a synthetic running job with a 50 MB log
(A), one `/api/jobs` poll with 20 rows (A+B), and the page's subresource list (E).

## Risks

- **Progress must not freeze.** A cached reading is only served while the file's size and mtime are unchanged; any
  write moves both.
- **Lazy NGL/feature imports must not change first-paint contracts.** Browser tests that read `window.ngl` or call
  `pdcSetRun` immediately after `load` are the regression surface; the boot module already publishes hooks before its
  first `await` and that rule is unchanged.
- **Quota freshness.** A 10 s storage cache delays a headroom stop by at most one worker tick; stage boundaries
  re-check.
