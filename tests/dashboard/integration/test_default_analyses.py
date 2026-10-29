"""A terminal run queues the analyses it owes its reader, and the run is never failed by a skip.

A run type declares the checks it owes without anyone asking (`kinds.TABLE`'s `default_for_run_types`), and the run's
own worker notifies the analysis coordinator when its stages are done. Two things must hold, and they are the two the
wiring can get wrong: a completed `aa_cg` run gets its own checks without anyone asking, and a run whose producer
finds nothing to analyse records the producer's own reason as a `skipped` task -- the run stays `completed`.

The analyses themselves are not run here: a worker standing in for the subprocess is what makes these fast.
"""
import subprocess
import time
from pathlib import Path

import pytest
from dashboard import files
from dashboard.execution import workflow

from tests.dashboard import support

JID = '123456abcdef'
SOURCES = ('2_mapping/mapped.gro', '2_mapping/mapped.xtc', '2_mapping/model.json',
           '3_initial_CG/SUCR_ff_inter.itp', '3_initial_CG/SUCR_initial.itp')


def seed(dashboard, *, trajectory=False, analyses=(), run_type=None):
    """A run of this dashboard, with its directory, and nothing holding it."""
    coordinator = dashboard.coordinator
    job = {'id': JID, 'label': 'Analyses', 'detergent': 'DDM', 'method': 'fast_forward', 'profile': 'draft-smoke',
           'status': 'completed', 'stage': 'complete', 'created': coordinator.now(), 'analyses': list(analyses)}
    if run_type:
        job['run_type'] = run_type
    coordinator.database().replace([job])
    run = coordinator.RUNS / JID
    run.mkdir(parents=True, exist_ok=True)
    if trajectory:
        support.cg_fixture_run(run, [[0., 0., 0.], [.4, 0., 0.], [0., .4, 0.], [0., 0., .4]], frames=3)
    return coordinator, run


def plant_aa_cg_sources(run):
    """The two AA-CG checks declare inputs in stages 2 and 3; these are where the queue resolves them."""
    for relative in SOURCES:
        source = run / 'stages' / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text('Where a kind is resolved from, not what it reads: the queue hashes these.\n')


def test_a_runs_own_kinds_are_its_types_defaults(dashboard):
    """D5: the kinds a run queues for itself are a facet of the table, read in one place.

    `dihedral-fit` and `bonded-cross-check` are an AA-to-CG run's own: they declare inputs in stages 2 and 3 only --
    no CG trajectory -- so they are available the moment the fit is. A run type that declares no defaults of its own
    is not a special case, and neither is a record that names none at all.
    """
    coordinator, run = seed(dashboard, trajectory=True)
    plant_aa_cg_sources(run)

    assert coordinator.automatic_analyses(JID) == []

    coordinator.database().update(JID, run_type='aa_cg')
    assert coordinator.automatic_analyses(JID) == ['bonded-cross-check', 'dihedral-fit']

    coordinator.database().update(JID, run_type='aa_only')
    assert coordinator.automatic_analyses(JID) == []


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


def test_a_finished_run_queues_its_own_checks_without_being_asked(dashboard, monkeypatch):
    coordinator, run = seed(dashboard, trajectory=True, run_type='aa_cg')
    plant_aa_cg_sources(run)
    monkeypatch.setattr(coordinator.analysis_coordinator, 'run', lambda *args: None)

    coordinator.analysis_coordinator.run_completed(run)

    queued = wait_for_a_task(coordinator)
    assert [task['kind'] for task in queued] == ['bonded-cross-check']
    assert queued[0]['status'] == 'queued'


def test_the_checks_wait_for_the_run_its_worker_still_holds(dashboard, monkeypatch):
    """The notification arrives before `finish_job` has let go of the run, so the queue has to wait for it.

    This is the ordering the real site has: `workflow.run` finishes inside the run's own worker, which still holds
    the run's lease and its slot in `WORKERS` while the terminal status is written. `queue` refuses exactly that,
    so the checks are queued a moment later rather than by weakening the refusal.
    """
    coordinator, run = seed(dashboard, run_type='aa_cg')
    plant_aa_cg_sources(run)
    monkeypatch.setattr(coordinator.analysis_coordinator, 'run', lambda *args: None)
    coordinator.database().update(JID, status='running')
    coordinator.WORKERS[JID] = object()

    coordinator.analysis_coordinator.run_completed(run)
    time.sleep(.2)
    assert tasks(coordinator) == [], 'a run its worker still holds is not queued behind its back'

    coordinator.database().update(JID, status='completed')
    coordinator.WORKERS.pop(JID, None)

    assert [task['kind'] for task in wait_for_a_task(coordinator)] == ['bonded-cross-check']


class SkippingWorker:
    """Stands in for Worker: the subprocess wrote its reason and exited with the skip code."""
    run_dir = None
    lease_file = None
    limit_error = None

    def execute(self, command, **kwargs):
        attempt = Path(command[-1]).parent
        files.atomic_json(attempt / 'skip.json', {'kind': 'stability',
                                                  'reason': 'this run offers no log worth checking'})
        raise subprocess.CalledProcessError(workflow.SKIPPED_EXIT_CODE, command)


def test_a_skip_is_recorded_as_skipped_and_leaves_the_run_completed(dashboard):
    aid = '000000000001'
    directory = f'analyses/stability/signature/{aid}'
    task = {'id': aid, 'kind': 'stability', 'payload': {}, 'signature': 'signature',
            'directory': directory, 'status': 'queued'}
    coordinator, run = seed(dashboard, analyses=[task])

    coordinator.analysis_coordinator.run(JID, aid, SkippingWorker())

    recorded = tasks(coordinator)[0]
    assert recorded['status'] == 'skipped'
    assert 'no log worth checking' in recorded['error'], 'the producer\'s own reason is the message'
    assert recorded['ended_at']
    assert coordinator.lookup(JID)['status'] == 'completed', 'nothing to analyse is not a failure'


def test_automatic_queueing_does_not_replace_a_manual_payload(dashboard, monkeypatch):
    """A manual payload is not overwritten by the kind's default payload when the attempt finishes.

    The completion chain queues its owed kinds with `{}`; a manual payload has a different signature, so a
    signature-only queue minted a second attempt beside it and the newer one won. Automatic queueing now treats a
    completed/skipped kind as current regardless of payload; Recompute still uses the signature.
    """
    coordinator, _ = seed(dashboard, trajectory=True)
    monkeypatch.setattr(coordinator, 'automatic_analyses', lambda jid: ['bonded-cross-check'])
    monkeypatch.setattr(coordinator.analysis_coordinator, 'run', lambda *args: None)
    task, status = coordinator.analysis_coordinator.queue(JID, 'bonded-cross-check', {'threshold': 0.1})
    assert status == 202
    coordinator.analysis_coordinator.update(JID, task['id'], status='completed')

    assert coordinator.analysis_coordinator.drain(JID, automatic=True) == {'queued': [], 'owed': []}
    assert len(tasks(coordinator)) == 1, 'the automatic pass replaced the manual payload'
    assert tasks(coordinator)[0]['payload'] == {'threshold': 0.1}


def test_a_skip_is_not_requeued_by_its_own_signature(dashboard, monkeypatch):
    """A skip is an answer: the same sources and code would skip again, so the chain must move on.

    Measured before the fix: a kind skipped, `chain` drained the run's owed kinds again, and `queue` -- which
    deduplicated queued/running/completed but not skipped -- minted another attempt every ~20 seconds. A skip is
    now current by signature, so the chain advances past it and a person's Recompute is still free.
    """
    coordinator, _ = seed(dashboard, trajectory=True)
    monkeypatch.setattr(coordinator, 'automatic_analyses', lambda jid: ['bonded-cross-check'])
    monkeypatch.setattr(coordinator.analysis_coordinator, 'run', lambda *args: None)
    task, status = coordinator.analysis_coordinator.queue(JID, 'bonded-cross-check', {})
    assert status == 202
    coordinator.analysis_coordinator.update(JID, task['id'], status='skipped')

    assert coordinator.analysis_coordinator.drain(JID) == {'queued': [], 'owed': []}
    assert [entry['status'] for entry in tasks(coordinator)] == ['skipped'], 'the skip was minted again'

    # The next owed kind still starts after a skip: the chain is not stopped, only the skip is not repeated.
    assert coordinator.analysis_coordinator.chain(JID, task['id']) == {'queued': [], 'owed': []}


def test_a_run_whose_sources_cannot_be_resolved_is_left_alone(dashboard):
    """A broken record is neither a skip nor a failure, and the run's own bookkeeping invents nothing.

    The queue's door resolves a kind's sources before it creates an attempt, so a run whose reference run is gone
    never reaches the worker's own skip. Nothing is recorded for it here -- and a person asking for the kind still
    gets the resolver's refusal, which names every path it looked for.
    """
    coordinator, run = seed(dashboard)
    files.atomic_json(run / 'manifest.json', {'run_type': 'aa_only', 'status': 'completed', 'stages': []})

    assert coordinator.analysis_coordinator.queue_defaults(JID) == []
    assert tasks(coordinator) == []
    assert coordinator.lookup(JID)['status'] == 'completed'
    with pytest.raises((OSError, ValueError)):
        coordinator.analysis_coordinator.queue(JID, 'bartender-fit', {})


def test_the_runs_own_defaults_are_queued_by_the_path_that_queues_them(dashboard, monkeypatch):
    """D5's other half: the queueing path asks the resolver instead of restating half of it.

    `automatic_analyses` answers with the run type's own checks, and `queue_defaults` -- the only caller that
    creates attempts -- must attempt every kind that function names. This pins the seam rather than the resolver
    (which its own test pins above): the queueing path goes through the one function that reads both facets.

    The kinds' own sources are deliberately not planted here. A kind whose sources this fixture cannot resolve is
    skipped by the queue's own door, which is the behaviour `test_a_run_whose_sources_cannot_be_resolved_is_left_alone`
    already holds; what went wrong was that the resolver was never consulted at all.
    """
    coordinator, _ = seed(dashboard)
    asked, attempted = [], []

    def resolver(jid):
        asked.append(jid)
        return ['bonded-cross-check', 'dihedral-fit']

    def queue(jid, kind, payload, automatic=False):
        attempted.append(kind)
        return {'id': f'task-{len(attempted)}', 'kind': kind, 'status': 'queued'}, 202

    monkeypatch.setattr(coordinator, 'automatic_analyses', resolver)
    monkeypatch.setattr(coordinator.analysis_coordinator, 'queue', queue)

    coordinator.analysis_coordinator.queue_defaults(JID)

    assert asked == [JID], 'the queueing path must ask the run what it owes its reader'
    assert attempted == ['bonded-cross-check', 'dihedral-fit'], \
        'every kind the resolver names is attempted, in its order'
