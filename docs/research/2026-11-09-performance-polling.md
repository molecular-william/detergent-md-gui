# Live run-status polling: audit, measurements, and a minimal coalescing proposal

Lane B of `docs/plans/2026-11-09-performance-follow-up.md`. Evidence gathered 2026-11-09 against the live dashboard
at `http://127.0.0.1:5000` (GET only: nothing was restarted, stopped, or written). No tracked file was edited; this
file is the lane's one artifact.

Server timings are `curl -w` totals (wall clock, one connection each) and bytes are decoded response bytes;
"wire bytes" for `/api/jobs/<id>/analyses` were also checked as compact JSON because `jsonify` writes no spaces.

## 1. Every recurring poll in the browser code

Search: `setTimeout` / `setInterval` / `visibilitychange` / `online` / `requestAnimationFrame` under
`packages/*/src/**/static/js`. Hits were classified into **recurring polls** (a timer that re-arms), **debounces**
(a timer that fires once per user event), and **one-shots** (mount/prefetch).

| # | Where (`file:line`) | Path it fetches | Interval / backoff | Hidden tab? | Hidden panel? | Bytes measured | Requests/min idle |
|---|---|---|---|---|---|---|---|
| 1 | `runs.js:274-281` poll loop | `/api/jobs?view=summary&page=1&limit=20&status=&search=` (conditional, `If-None-Match`, `runs.js:259`) | 5000 ms; doubles on failure to a 60000 ms cap (`pollDelay`, `runs.js:280`) | **no** – wakes every 30000 ms and returns before fetching (`runs.js:277`) | **no** – same guard | 38,412 B (HTTP 200, 10 runs), **0 B** (304) | **12** (≈450 KiB/min) |
| 2 | `console.js:36-40`, driven by #1 (`runs.js:279`) | `/api/jobs/<id>/log?offset=<n>&source=<log>` | shares #1's tick | inherits #1 | only while the card's `details` is open and its console is not paused (`console.js:37`) | 12,232 B first read; **68 B** steady state | 12 only with the console open |
| 3 | `run-view-analysis.js:439` (`schedule`) | `/api/jobs/<id>/analyses` | 2000 ms while a task is `queued`/`running`/`cancelling`; stops on the answer that settles it (`:438`) | **YES, polls** – no `document.hidden` test anywhere in the file | **YES, polls** – no panel test | **527,290 B** on run `67bc79a995d6`; 452 B, 3,038 B, 6,560 B and 37,081 B on the other four measured runs | **30** (≈15 MiB/min for this run) |
| 4 | `run-view-trajectory.js:757-765` (`ensurePolling`) | `/api/jobs/<id>/analyses` (**same path as #3**) | 2000 ms while a `frame-series` build is in flight | **YES, polls** | **YES, polls** | same 527,290 B | **30** (duplicate of #3 while both are active) |
| 5 | `bonded-parameterization.js:413-427` (`schedule`/`poll`) | `/api/bonded-parameterizations/jobs?job_id=<id>` | 3000 ms (`POLL_MS`, `:45`) while the fit is live | **no** – `visible()` reads `document.hidden` (`:174`), resumes on `visibilitychange`/`dashboard:tab` (`:448-449`) | **no** – same predicate | 12 B | 20 while a fit runs |
| 6 | `run-view-pdc.js:195-203` (`arm`) | `/api/pdc/<id>/whole-trajectory` | 2000 ms (`WHOLE_POLL_MS`, `:99`) while `state.status === 'running'` | **YES, polls** until the rebuild ends | **YES, polls** | 544 B | 30 while a rebuild runs |
| 7 | `new-run.js:806` readiness | `/api/readiness?...` | 150 ms **debounce**, not recurring; fires once per form change | n/a | guarded (`new-run.js:805`) | 4,034 B | 0 idle |
| 8 | `new-run-pdc.js:1424` preview, `:1526` readiness | `/api/pdc/...` preview, readiness | 250 ms debounce each | n/a | guarded | not polled | 0 idle |
| 9 | `main.js:103-104` prefetch | the 7 catalogue paths (`main.js:18-27`) | once, 1500 ms after load then idle | n/a | n/a | not recurring | 0 after the first minute |

Not polls, checked and left alone: the search/status debounce `runs.js:272` (150 ms), `run-view.js:103` `loadRuns`
(two `/api/jobs?…&run_type=…&status=completed` reads, 16,410 B + 17,209 B, on mount only), `run-view-monitor.js`'s
one-shot `/trajectory` (536 B), artifact-index walk and `/structure` reads on run selection, `/api/storage`
(378 B, 77 ms) on Runs mount, `/figures` (62 B – 5,253 B) on Analysis mount and after a task settles.
`run-view-monitor.js` has **no timer** — its "status" line is written from the job record it was handed, never refreshed.

### Request counts per minute for one idle open tab

- **Runs panel, everything settled:** 12 requests/min (`/api/jobs`), ≈450 KiB/min; the console adds 12 × 68 B only
  while its disclosure is open.
- **Runs panel, tab or panel hidden:** 0 requests/min (2 wake-ups/min that return before fetching).
- **Run view, nothing in flight:** 0 recurring requests.
- **Run view, one analysis running on one monitor:** 30 `/analyses`/min from #3, plus 30 more from #4 if a
  `frame-series` build is the running task — up to **60 requests and ≈30 MiB/min on one monitor**. Two monitors each
  with a task in flight: up to 120 requests and ≈60 MiB/min. This is the expensive case, and it is the case a reader
  is watching.

## 2. Server side: what already exists

### `/api/jobs` is conditional, and the ETag is computed from the finished payload

`web/routes/runs.py:184-186`:

```python
etag = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
if request.if_none_match.contains(etag): return Response(status=304, headers={'ETag': etag})
response = jsonify(payload); response.set_etag(etag); return response
```

So the 304 is honest but **not cheap**: the payload is fully built first, which means `views.run_view` runs per job —
`analysis_view`, `consistency_summary`, `stage_view`, `resume_stages` (a filesystem walk), `trajectory_bytes`,
`eta()` (a 64 KiB tail of the running stage's log) and `progress()` (the **whole** stage log, `views.py:252-274`,
"the file, not a tail"). Measured against the live dashboard:

| Request | Bytes | Time |
|---|---|---|
| `GET /api/jobs?view=summary&page=1&limit=20` | 38,412 | 0.042–0.048 s |
| same, `If-None-Match` → 304 | 0 | 0.042–0.088 s |

The 304 saves the 38 KB but no server work. Marked inference: with a run mid-mdrun the `progress()` full-log read
makes the 304 much more expensive than these idle numbers; it could not be measured because no run is active.

The summary is already lean: `views.py:30-36` whitelists `VISIBLE_FIELDS`, `ANALYSIS_SUMMARY_FIELDS`,
`STAGE_SUMMARY_FIELDS`. 38 KB for 10 runs is ~3.8 KB/run and includes per-job analyses summaries, stage lists,
`resume_stages`, `workflow_stages`. It is not a payload worth a new endpoint.

### A cheap changed-marker already exists, but it cannot replace the poll

- `jobs.revision` (integer, `store.py:86`: bumped on **every** `database.update`) is already **in the payload**
  (`runs.py:183` `| {'revision': revision}`). No browser module reads it.
- `jobs.artifact_revision` (float) is bumped only when the artifact index is rebuilt (`coordinator.py:265-270`).
- `views.py:370` adds `detail_revision` (sha256 of the manifest) to each summary run.

None of them moves for the one thing that changes every poll on a running run: GROMACS' percent and ETA are
**parsed from the stage log at request time** (`views.py:205-274`; the `gromacs_eta`/`eta_minutes` fields are in
`HIDDEN_FIELDS`, `views.py:33`). A "has the revision changed?" gate would therefore leave the progress line frozen,
and a client that skipped the fetch on an unchanged revision would be caching live run state — which the plan
forbids. **Conclusion: do not add a compact runs endpoint, and do not gate the run-list poll on `revision`.**

### The one payload that is worth shrinking

`/api/jobs/<id>/analyses` (`web/routes/analyses.py:175-181`) returns the job record's full analysis list, including
each attempt's `result`, `payload`, `outputs`, `environment`, `tools` and `command`. The Analysis card reads only
`id, kind, status, created_at, started_at, ended_at, error, directory, progress` (`run-view-analysis.js:114-183`),
but the Trajectory card also needs `payload` and `outputs` for a `frame-series` task
(`run-view-trajectory.js:255-271, 888`). On the measured run, one `ff-interactions` record carries a 451 KB
`result`:

| `/api/jobs/67bc79a995d6/analyses` | wire bytes |
|---|---|
| as served | 527,290 |
| only the fields the 2 s pollers read | 7,691 |

That is a 68× reduction on the path that the two pollers hit 60 times a minute. It is the same records with fields
dropped — the `view=summary` pattern `/api/jobs` already uses, not a second source of truth. **Recommended as the
follow-up behind the scheduler** (proposal below), because coalescing alone still ships 527 KB per tick.

## 3. Proposed minimal design: one scheduler in `shared.js`

No new module. `shared.js` already owns every browser primitive the panels share (`$`, `api`, `guarded`, `loadOnce`,
`cachedApi`, `invalidateResource`); a scheduler is three small exports there, and a sixth file would be a file whose
only job is to be imported by five others.

```js
// shared.js — the one place that knows a page can be hidden
const liveVisible = () => !document.hidden && navigator.onLine;
const resumers = new Set();
function whenLive(fn) { resumers.add(fn); return () => resumers.delete(fn); }
for (const event of ['visibilitychange', 'online']) window.addEventListener(event, () => {
  if (liveVisible()) for (const fn of [...resumers]) fn();
});
// Same-path requests inside one tick share one answer and leave nothing behind: `loadOnce` with
// `maxAge: 0` shares an in-flight promise and expires the settled entry immediately.
const liveApi = path => loadOnce(path, () => api(path), {maxAge: 0});
export { liveVisible, whenLive, liveApi };
```

- (a) **Pauses when hidden or offline:** each poller tests `liveVisible()` before arming its timer, exactly as
  `runs.js:277` and `bonded-parameterization.js:174` already do; JS timers do not fire in a fully discarded tab, so
  the test is a guard against the hidden-but-alive tab and the offline case.
- (b) **Refreshes immediately on return:** `whenLive(resume)`; `resume` runs `reload`/`poll` now, not after the
  interval. The answer overwrites the progress line in the same pass, so the "Updated …" stamp and the progress text
  come from one request — the run list's current `poll()` already does this (`runs.js:279`).
- (c) **Coalesces same-path requests in a tick:** `liveApi` shares the in-flight promise. The duplicate is #3/#4
  asking for the same `/analyses` twice; `maxAge: 0` means the second caller waits for the first request and neither
  caller's *next* tick reuses it, so no live state is cached.
- (d) **Each panel keeps its interval and semantics:** the helper owns no timer. #3/#4 keep 2000 ms and their own
  "is anything unsettled?" stop rule; #5 keeps 3000 ms and its terminal rule; #1 keeps 5000 ms and its 2× backoff;
  #6 keeps 2000 ms and `state.status === 'running'`.

### Call sites to change

| Site | Change |
|---|---|
| `runs.js:277,281,283` | replace the inline `document.hidden \|\| !navigator.onLine` test and the local `['visibilitychange','online']` listener with `liveVisible()` / `whenLive(poll)`; keep the 5 s/30 s/backoff numbers |
| `run-view-analysis.js:437-440` | add `if (!liveVisible() \|\| !panelShown()) return;` before arming; `whenLive(() => reload())`; reload the same conditional path |
| `run-view-trajectory.js:757-765` | add the same guard; `whenLive(() => loadTasks(runToken))`; read `/analyses` through `liveApi` |
| `bonded-parameterization.js:174,448-449` | replace its local `visible()`/listener pair with `liveVisible()` + `whenLive(resume)`; behaviour unchanged (it is already correct — this is de-duplication, optional if the integrator prefers no churn) |
| `run-view-pdc.js:195-203` | add `liveVisible()` before arming and `whenLive(arm)`; keep `isCurrent()` |

### What stays exactly as it is

- `console.js` — it has no timer; it inherits the Runs tick and already returns while paused/hidden/closed.
- `new-run.js:790-806, 915` and `new-run-pdc.js:1424, 1526` — event debounces, not polls; readiness must not be
  retried on a schedule.
- `main.js:103-104` prefetch — one-shot after idle, and catalogues only.
- `run-view.js` `loadRuns`, `run-view-monitor.js` one-shot loads, `/figures`, `/api/storage`.
- The `/api/jobs` ETag conditional request: keep it (38 KB → 0 on the common idle 304), knowing it saves bytes not
  CPU.

### Follow-up behind the scheduler (only if the byte count still matters)

Add `?view=summary` to `/api/jobs/<jid>/analyses` (`analyses.py:175-181`) with the same whitelist split `/api/jobs`
uses, and have the two pollers ask for it while the card's detailed needs (frame-series `payload`/`outputs`) keep the
full answer on load and on the settling read. Measured effect on the polled path: 527,290 B → 7,691 B. This is a
second *view*, not a second source of truth, and it is the only place the measurements show a payload worth
changing.

## 4. Tests: what already pins this, and what to add

Existing:

- `packages/core/tests/integration/test_operations.py::test_paginated_poll_does_not_scan_artifacts_and_supports_etag`
  — a poll must not scan artifacts, and the conditional request answers 304.
- `packages/core/tests/integration/test_performance_api.py::test_compact_runs_preserve_checkpoints_and_full_detail`
  — the summary shape and its 304.
- `packages/core/tests/integration/test_jobs_run_type_filter.py::test_the_etag_belongs_to_the_answer_the_caller_asked_for`
  — the ETag follows the filtered answer.
- `packages/core/tests/browser/test_bonded_parameterization_browser.py:459` —
  `test_polling_stops_while_the_panel_is_off_screen_and_picks_up_when_it_returns`: hides the panel, dispatches
  `visibilitychange`, asserts the route count stops, then resumes.
- `…/test_bonded_parameterization_browser.py:496` — the default cadence is a few seconds and stops on the terminal
  answer.
- `…/test_run_view_trajectory_browser.py:233` and `…/test_run_view_analysis_browser.py` — the `__runViewPollMs` seam.

Nothing pins the Runs panel's hidden behaviour, the Analysis card's hidden behaviour, or the coalescing.

Proposed regression tests (browser tier, request counting — the repo has no JS unit runner):

1. `test_runs_table_browser.py`: **the run list stops asking while the tab is hidden and refreshes once on return.**
   Count `route` hits for `/api/jobs?`; `page.evaluate` defines `document.hidden` true (and dispatches
   `visibilitychange`), wait four cadences (seam: a new `window.__runsPollMs` would be needed, or the existing 5 s
   band), assert the count is unchanged; restore, assert exactly one new hit and that `#connection` says `Updated`.
2. `test_run_view_analysis_browser.py`: **a queued task stops polling while the Run view is hidden and the first
   read on return is immediate.** Queue a stubbed unsettled task, switch to another panel (`dashboard:tab`),
   assert `/analyses` hits stop, switch back and assert one hit within a few hundred ms and the task line updated.
3. `test_run_view_analysis_browser.py`: **two pollers, one request.** With a `frame-series` build running, register
   both the Analysis card and the Trajectory block on one run and assert `/analyses` is requested once per tick
   (route counter), not twice — the `liveApi` coalescing.
4. `test_operations.py` (fast tier, cheap): if the `/analyses?view=summary` follow-up is taken,
   assert the summary drops `result`/`payload` and keeps `id, kind, status, directory`, the way
   `test_compact_runs_preserve_checkpoints_and_full_detail` does for `/api/jobs`.

## 5. Risks

- **A paused poll must not read as a frozen run.** The Analysis card's `setNote('Reading this run's analyses…')` and
  the task lines stay on screen while hidden; on return the first answer must land before anything claims freshness.
  The resume path must call the same `reload()`/`poll()` the timer would, not a lighter "status only" read.
- **`guarded` + shared promise.** `liveApi` shares one promise between two callers that each hold their own
  generation token; a `DROP` from one caller's supersede is the other caller's answer too. Both pollers already treat
  a dropped answer as "write nothing", so this is safe, but a test should cover it.
- **Unmounting.** The panels have no teardown; `whenLive` returns a disposer that nothing calls yet. If a panel is
  rebuilt (Bonded mounts once, Run view mounts once), a stale resume callback would fetch for a run that is no longer
  selected — the existing per-call token checks (`runToken`, `jobToken`, `token`, `isCurrent`) already guard the
  write, so the risk is a wasted request, not a wrong one.
- **304 is not free.** Keeping the conditional request is right for bytes; do not read its speed as evidence that the
  server is cheap. If the Runs poll is ever measured as server-heavy during an mdrun, the fix is trimming
  `progress()`'s full-log read, not the client cadence.
- **The 2 s Analysis cadence is a product decision**, not a bug: it is what makes a queued analysis feel live. The
  proposal keeps it; only the hidden-tab case and the duplicate request change. If the user wants fewer bytes while
  a run is active, the `/analyses?view=summary` follow-up is the lever, not the interval.
