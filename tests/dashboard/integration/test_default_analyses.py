"""A terminal run queues the analyses it owes its reader, and the run is never failed by a skip.

The frames a reader looks at are part of what a run publishes, so `snapshots` is registered as a kind a run runs for
itself (`kinds.TABLE`) and the run's own worker notifies the analysis coordinator when its stages are done. Two
things must hold, and they are the two the wiring can get wrong: a completed run gets the task without anyone
asking, and a run whose trajectory is missing records the producer's own reason as a `skipped` task -- the run
stays `completed`.

The analysis itself is not run here: what the subprocess does about a missing trajectory is pinned in
`tests/dashboard/unit/test_snapshot_skip.py`, and a worker standing in for it is what makes these fast.
"""
import subprocess
import time
from pathlib import Path

import pytest

from dashboard import files
from dashboard.execution import workflow
from tests.dashboard import support

JID = '123456abcdef'


def seed(dashboard, *, trajectory=False, analyses=()):
    """A run of this dashboard, with its directory, and nothing holding it."""
    coordinator = dashboard.coordinator
    job = {'id': JID, 'label': 'Frames', 'detergent': 'DDM', 'method': 'fast_forward', 'profile': 'draft-smoke',
           'status': 'completed', 'stage': 'complete', 'created': coordinator.now(), 'analyses': list(analyses)}
    coordinator.database().replace([job])
    run = coordinator.RUNS / JID
    run.mkdir(parents=True, exist_ok=True)
    if trajectory:
        support.cg_fixture_run(run, [[0., 0., 0.], [.4, 0., 0.], [0., .4, 0.], [0., 0., .4]], frames=3)
    return coordinator, run


def test_a_runs_own_kinds_are_its_types_defaults_beside_the_universal_ones(dashboard):
    """D5: the kinds a run queues for itself are two facets of one table, read in one place.

    `snapshots` runs for every run (`runs_for_every_run`). `dihedral-fit` and `bonded-cross-check` are an
    AA-to-CG run's own: they declare inputs in stages 2 and 3 only -- no CG trajectory -- so they are available
    the moment the fit is, which is what the sources planted here are. A run type that declares no defaults of its
    own is not a special case, and neither is a record that names none at all: this run type's defaults are not
    every run's, so a record that cannot say what it is gets the universal kinds only.
    """
    coordinator, run = seed(dashboard, trajectory=True)
    for relative in ('2_mapping/mapped.gro', '2_mapping/mapped.xtc', '2_mapping/model.json',
                     '3_initial_CG/SUCR_ff_inter.itp', '3_initial_CG/SUCR_initial.itp'):
        source = run / 'stages' / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text('Where a kind is resolved from, not what it reads: the queue hashes these.\n')

    assert coordinator.automatic_analyses(JID) == ['snapshots']

    coordinator.database().update(JID, run_type='aa_cg')
    assert coordinator.automatic_analyses(JID) == ['snapshots', 'bonded-cross-check', 'dihedral-fit']

    coordinator.database().update(JID, run_type='aa_only')
    assert coordinator.automatic_analyses(JID) == ['snapshots']


def tasks(coordinator):
    return coordinator.lookup(JID).get('analyses', [])


def wait_for_a_task(coordinator, timeout=5.0):
    """The queueing is handed to a thread, so a test waits for the record rather than for a return value."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if tasks(coordinator):
            return tasks(coordinator)
        time.sleep(.02)
    return tasks(coordinator)


def test_a_finished_run_queues_its_frames_without_being_asked(dashboard, monkeypatch):
    coordinator, run = seed(dashboard, trajectory=True)
    started = []
    monkeypatch.setattr(coordinator.analysis_coordinator, 'run', lambda *args: started.append(args))

    coordinator.analysis_coordinator.run_completed(run)

    queued = wait_for_a_task(coordinator)
    assert [task['kind'] for task in queued] == ['snapshots']
    assert queued[0]['status'] == 'queued'


def test_a_run_with_nothing_to_sample_is_queued_too_because_the_kind_decides(dashboard, monkeypatch):
    """The queue does not pre-judge the trajectory: a run with none is asked, and the kind answers with a skip."""
    coordinator, run = seed(dashboard, trajectory=False)
    monkeypatch.setattr(coordinator.analysis_coordinator, 'run', lambda *args: None)

    coordinator.analysis_coordinator.run_completed(run)

    assert [task['kind'] for task in wait_for_a_task(coordinator)] == ['snapshots']


def test_the_frames_wait_for_the_run_its_worker_still_holds(dashboard, monkeypatch):
    """The notification arrives before `finish_job` has let go of the run, so the queue has to wait for it.

    This is the ordering the real site has: `workflow.run` finishes inside the run's own worker, which still holds
    the run's lease and its slot in `WORKERS` while the terminal status is written. `queue` refuses exactly that,
    so the frames are queued a moment later rather than by weakening the refusal.
    """
    coordinator, run = seed(dashboard)
    monkeypatch.setattr(coordinator.analysis_coordinator, 'run', lambda *args: None)
    coordinator.database().update(JID, status='running')
    coordinator.WORKERS[JID] = object()

    coordinator.analysis_coordinator.run_completed(run)
    time.sleep(.2)
    assert tasks(coordinator) == [], 'a run its worker still holds is not queued behind its back'

    coordinator.database().update(JID, status='completed')
    coordinator.WORKERS.pop(JID, None)

    assert [task['kind'] for task in wait_for_a_task(coordinator)] == ['snapshots']


class SkippingWorker:
    """Stands in for Worker: the subprocess wrote its reason and exited with the skip code."""
    run_dir = None
    lease_file = None
    limit_error = None

    def execute(self, command, **kwargs):
        attempt = Path(command[-1]).parent
        files.atomic_json(attempt / 'skip.json', {'kind': 'snapshots',
                                                  'reason': 'run offers no trajectory to review'})
        raise subprocess.CalledProcessError(workflow.SKIPPED_EXIT_CODE, command)


def test_a_skip_is_recorded_as_skipped_and_leaves_the_run_completed(dashboard):
    aid = '000000000001'
    directory = f'analyses/snapshots/signature/{aid}'
    task = {'id': aid, 'kind': 'snapshots', 'payload': {}, 'signature': 'signature',
            'directory': directory, 'status': 'queued'}
    coordinator, run = seed(dashboard, analyses=[task])

    coordinator.analysis_coordinator.run(JID, aid, SkippingWorker())

    recorded = tasks(coordinator)[0]
    assert recorded['status'] == 'skipped'
    assert 'no trajectory to review' in recorded['error'], 'the producer\'s own reason is the message'
    assert recorded['ended_at']
    assert coordinator.lookup(JID)['status'] == 'completed', 'nothing to sample is not a failure'


def test_a_run_whose_sources_cannot_be_resolved_is_left_alone(dashboard):
    """A broken record is neither a skip nor a failure, and the run's own bookkeeping invents nothing.

    The queue's door resolves a kind's sources before it creates an attempt, so a run whose reference run is gone
    never reaches the worker's own skip. Nothing is recorded for it here -- and a person asking for the frames still
    gets the resolver's refusal, which names every path it looked for.
    """
    coordinator, run = seed(dashboard)
    files.atomic_json(run / 'manifest.json', {'run_type': 'aa_only', 'status': 'completed', 'stages': []})

    assert coordinator.analysis_coordinator.queue_defaults(JID) == []
    assert tasks(coordinator) == []
    assert coordinator.lookup(JID)['status'] == 'completed'
    with pytest.raises((OSError, ValueError)):
        coordinator.analysis_coordinator.queue(JID, 'snapshots', {})


def test_a_snapshots_payload_naming_a_cg_stage_is_no_longer_refused(dashboard, monkeypatch):
    """The guard that refused any stage but `1_AA-reference` is gone.

    The producer takes no stage at all -- `layout.frame_source` reads the run's own layout -- so the payload's
    `stage` constrains nothing, and a coarse-grained run's frames are supported. What is left refusing anything is
    the run-state check, which is about the run and not about the payload.
    """
    coordinator, run = seed(dashboard, trajectory=True)
    monkeypatch.setattr(coordinator.analysis_coordinator, 'run', lambda *args: None)

    task, status = coordinator.analysis_coordinator.queue(JID, 'snapshots', {'stage': '4_CG_sim'})

    assert status == 202
    assert task['kind'] == 'snapshots'
    assert task['payload'] == {'stage': '4_CG_sim'}


def test_the_runs_own_defaults_are_queued_by_the_path_that_queues_them(dashboard, monkeypatch):
    """D5's other half: the queueing path asks the resolver instead of restating half of it.

    Two independent reviewers found this in the commit that declared the defaults: `automatic_analyses` answered
    `['snapshots', 'bonded-cross-check', 'dihedral-fit']` for an AA-to-CG run, and `queue_defaults` -- the only
    caller that creates attempts -- still iterated `for_every_run()`, so the two checks were declared and queued by
    nobody. This pins the seam rather than the resolver (which its own test pins above): the queueing path goes
    through the one function that reads both facets, and it attempts every kind that function names.

    The kinds' own sources are deliberately not planted here. A kind whose sources this fixture cannot resolve is
    skipped by the queue's own door, which is the behaviour `test_a_run_whose_sources_cannot_be_resolved_is_left_alone`
    already holds; what went wrong was that the resolver was never consulted at all.
    """
    coordinator, _ = seed(dashboard)
    asked, attempted = [], []

    def resolver(jid):
        asked.append(jid)
        return ['snapshots', 'bonded-cross-check', 'dihedral-fit']

    def queue(jid, kind, payload):
        attempted.append(kind)
        return {'id': f'task-{len(attempted)}', 'kind': kind, 'status': 'queued'}, 202

    monkeypatch.setattr(coordinator, 'automatic_analyses', resolver)
    monkeypatch.setattr(coordinator.analysis_coordinator, 'queue', queue)

    coordinator.analysis_coordinator.queue_defaults(JID)

    assert asked == [JID], 'the queueing path must ask the run what it owes its reader'
    assert attempted == ['snapshots', 'bonded-cross-check', 'dihedral-fit'], \
        'every kind the resolver names is attempted, in its order'
