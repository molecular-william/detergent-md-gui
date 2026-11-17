# Plan: New run — queue on the GPU or share it

Status: **built** (2026-11-17). User decision: "Queue run on GPU" creates the run now and starts it by itself when
that device has a free slot; "Share run on GPU" starts immediately on a device that already runs a simulation, with
its own thread and mdrun settings; the split applies to both AA and CG runs started from the engine's New run form.

## Today

`max_concurrent_runs` is a per-device ceiling (`config/dashboard.json`: 1) and `Coordinator.admit_device` **refuses**
a second run on a busy device. `queued` exists only between create and the worker's first moment; `reconcile` fails a
queued row whose worker is gone after a restart, and nothing ever starts a queued job later. The form's one button is
`#start-run` in `web/templates/dashboard.html`, labelled "Start AA run"/"Start CG run" by `new-run.js`.

## The choice

One recorded run setting, `gpu_sharing`, advertised as a choice in the AA and CG adapters' `CHOICE_SPECS` (an
unadvertised setting is dropped by `web/routes/runs.py`):

- `queue` — the run is created `queued`; if its device has room it starts at once (the normal case), otherwise it waits
  with `gpu_queue: {device, requested_at}` on the record and starts by itself when that device frees.
- `share` — admitted even when the device is at the ceiling, one run beyond it; the manifest records `gpu_sharing=share`.
- absent — today's behaviour (refuse when busy), so an older client is unchanged.

## Work

### Backend (`execution/coordination/coordinator.py`, `web/routes/runs.py`, adapters)
1. `admit_device`: a `share` run may be one beyond `max_concurrent_runs`; a `queue` run never raises `CapacityFull` and
   is held instead. A queued run still passes the storage admission.
2. `admit_jobs` / the CG create path: when a `queue` run's device is full, insert the row with the `gpu_queue` marker and
   no worker; otherwise start as today. One helper that starts a held row (worker + thread), used by both.
3. `start_queued()`: under `JOBS_LOCK`, oldest first, start every held `queue` row whose device now has room; called
   where a run's worker is released (completion, failure, cancel) and from `ensure_service` after `reconcile`.
4. `reconcile`: a held `queue` row (no run directory yet) stays queued across a restart instead of being failed; every
   other queued row keeps today's failure.
5. `GET /api/run/devices` gains `active`: `{device index: [run ids]}` from `busy_devices()`, the dashboard's own answer
   to "is a run on this device" (NVML's `in_use` is empty between create and mdrun and is not this question).

### Frontend (`templates/dashboard.html`, `static/js/new-run.js`, `static/js/gpu-device.js`, `new-run.css`)
- `#start-run` keeps its id and becomes **Queue run on GPU**; a second button `#start-run-share` is **Share run on GPU**.
  Both post the run with `gpu_sharing` set to their own value.
- Share is disabled whenever the selected device has no active run (`/api/run/devices` `active`), and whenever
  readiness is not ready; queue is disabled only by readiness. Both are disabled while a submit is in flight.
- Labels are the user's words for both run types; the panel's type remains visible in the form itself.

## Verification

- Fast tier: `test_operations.py`/`test_jobs_*`/`test_dashboard.py` plus new cases — share admits one beyond the
  ceiling and refuses the next; queue while busy inserts a held row with no worker; a released worker starts the held
  row on its device; a held row survives `reconcile`.
- Browser tier: the New run form shows two buttons, share disabled on a free device and enabled when the device reports
  an active run, and each button posts its own `gpu_sharing` value (route assertion).
- `ruff` clean; the gate runs the fast tier and commits.

## Built

- Backend: `gpu_sharing` is a choice of the AA and CG adapters; `admit_device` lets a `share` run take one slot past
  the per-device ceiling and never refuses a `queue` run; a queue run whose device is full is stored with
  `gpu_queue` and no worker (`_hold_for_gpu`), and `start_queued()` starts held rows oldest-first wherever a worker is
  released and after `reconcile`, so the queue survives a restart. `/api/run/devices` also answers
  `active: {device: [run ids]}`.
- A held row can be cancelled (`cancel_job` ends it itself; `ownership_flags` offers `can_cancel` for it) and
  `start_queued` will not revive it.
- `cg_run.normalize_settings` lifts, validates and restores `gpu_sharing` around each kind's dialect, so a composition
  or published-reference CG run accepts the same posting instead of answering "Unknown composition CG setting".
- Frontend: `#start-run` is **Queue run on GPU**, `#start-run-share` is **Share run on GPU**; share is enabled only
  when the selected device reports an active run, both obey readiness and an in-flight submit, and each posts its own
  `gpu_sharing` value. The device map is re-read on the select's change, on mount and after a submit -- not polled.
- Tests: `test_run_gpu_capacity.py` (share one-beyond, held row, release starts it, reconcile keeps it, cancel),
  `test_run_devices_api.py` (`active`), `test_job_create_paths.py` (advertisement), `test_composition_workflow.py`
  (choice across kinds), and the New run browser module (button gates and the posted value).
