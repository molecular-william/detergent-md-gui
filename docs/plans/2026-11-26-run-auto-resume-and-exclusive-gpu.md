# Runs: automatic resume (up to 3) and exclusively queued resumes

Status: built (2026-11-26, the user's request)

## The request

- A run that fails but is **resume-able** should be resumed automatically, up to **3 times**.
- When a run is resumed, it must **always be queued to the GPU**, and **never shared**.

## Decisions

- **Resume-able means what the Resume button means**: the stopped stage has its own mdrun checkpoint on disk
  (`workflow.continue_plan`). A run with no checkpoint, whose only option is Restart from stage, is not auto-restarted;
  the allowance is not spent. The auto-resume calls `continue_in_place`, the same path the button uses.
- **Three attempts per run**, persisted on the job row as `auto_resume_count` (`Coordinator.AUTO_RESUME_LIMIT`).
  It counts automatic attempts only: a manual Resume neither increments nor resets it. A fourth failure is left for a
  person. An attempt that never started (preparation refused) gives its allowance back.
- **Triggered by the failure itself**: in `run_job` once the terminal row and lease are written, and in `reconcile` for
  a run the dashboard restart marked failed. Only `failed` is resumed: a cancelled run is the person's decision.
- **Every resume is queued and exclusive**: `_queue_in_place` forces `settings.gpu_sharing='queue'` (a recorded `share`
  is overridden), admits through the queue, and if the device already holds `max_concurrent_runs` runs, holds the
  prepared run with `gpu_queue` and no worker. `start_queued` starts it when a slot frees. The forced choice is
  written to the row and the run's manifest, so the record no longer says `share`.
- **A held resume survives a restart**: `_held_queue_row` recognises a queued run with `resume_in_place` (its prepared
  directory already exists) as never-started, so `reconcile` does not mark it failed; `start_queued` starts it.
- **The admission copy**: `_hold_for_gpu` marks the row it is given as queued. The resume path gives it a copy, so a
  database failure after the hold still rolls the manifest back against the run's terminal `failed` status (the
  rollback test covers exactly this).

## Files

- `execution/coordination/coordinator.py`: `AUTO_RESUME_LIMIT`, `_auto_resume`, the failure hook in `run_job`, the
  `reconcile` collection, the forced queue/hold in `_queue_in_place`, the held-resume recognition.
- `tests/integration/test_continue_in_place.py`: three auto-continues then the fourth left failed; no checkpoint
  skipped; cancelled skipped; a real failing stage's hook queues the next continue.
- `tests/integration/test_in_place_resume.py`: a resume of a `share` run on a busy GPU is held with
  `gpu_sharing='queue'`, its manifest says queue, and it starts when the slot frees; the capacity refusal case was
  removed from the rejection table.

## Not in scope

No backoff/delay between automatic attempts, no new UI field (the count is on the row and each continue is in
`resume_history`), and no auto-Restart-from-stage for a run with no checkpoint.
