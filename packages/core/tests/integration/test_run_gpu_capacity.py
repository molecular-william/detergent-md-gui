"""Admission is per GPU: a run on a free device starts beside a run on a busy one.

The coordinator's active runs are the claim on a device. A job names its own device in `settings['mdrun_gpu']`,
which is the index its mdrun will use, so the same index is what refuses the next start. The runs here never
execute: `run_job` is replaced with a no-op, which leaves the admitted worker registered -- the same state an
active simulation is in while it runs.

`gpu_sharing` changes only that admission: `share` may take one slot beyond the ceiling, and `queue` is never
refused -- while its device is busy it is stored held, with `gpu_queue` and no worker, until a slot opens.
"""
import time
from pathlib import Path

import pytest
from dashboard import files
from dashboard.execution import devices, protocol, workflow
from dashboard.execution.coordination import errors

pytestmark = pytest.mark.usefixtures('gpu_host')


def record(owner, jid, gpu, sharing=None):
    """One job a caller wants to start on `gpu`; the fields admission reads and nothing else."""
    settings = {'mdrun_gpu': gpu}
    if sharing is not None:
        settings['gpu_sharing'] = sharing
    return {'id': jid, 'label': jid, 'status': 'queued', 'stage': 'queued', 'created': owner.now(),
            'settings': settings, 'run_type': 'osmotic'}


class _FakeAdapter:
    """What `run_job` asks an adapter for, without a molecule or a model: ready, and a prepared directory."""

    def readiness(self, payload):
        return {'ready': True, 'checks': [], 'blockers': []}

    def prepare(self, root, metadata):
        root = Path(root)
        (root / 'inputs').mkdir()
        files.atomic_json(root / 'manifest.json', {'stages': [], 'stage_plan': [], 'inputs': []})


def test_a_run_on_a_free_gpu_starts_beside_a_run_on_a_busy_one(dashboard, monkeypatch):
    owner = dashboard.coordinator
    monkeypatch.setattr(owner, 'run_job', lambda *args, **kwargs: None)

    first = record(owner, 'aaaaaaaaaaaa', 0)
    second = record(owner, 'bbbbbbbbbbbb', 2)

    owner.admit_jobs([first], first)
    owner.admit_jobs([second], second)

    assert set(owner.WORKERS) == {'aaaaaaaaaaaa', 'bbbbbbbbbbbb'}
    assert owner.busy_devices() == {0: ['aaaaaaaaaaaa'], 2: ['bbbbbbbbbbbb']}


def test_a_second_run_on_the_same_gpu_is_refused_with_the_gpu_message(dashboard, monkeypatch):
    owner = dashboard.coordinator
    monkeypatch.setattr(owner, 'run_job', lambda *args, **kwargs: None)
    first = record(owner, 'aaaaaaaaaaaa', 1)
    owner.admit_jobs([first], first)

    second = record(owner, 'bbbbbbbbbbbb', 1)
    with pytest.raises(errors.CapacityFull) as refused:
        owner.admit_jobs([second], second)

    assert str(refused.value) == 'This GPU is busy. Either wait for the run to stop or choose a free GPU.'
    assert set(owner.WORKERS) == {'aaaaaaaaaaaa'}, 'the refused run still registered a worker'
    assert owner.database().get('bbbbbbbbbbbb') is None, 'the refused run was inserted'


def test_the_device_is_read_from_the_run_its_own_settings_name(dashboard, monkeypatch):
    """A string a form sent is the same device as its integer: `mdrun_gpu` is compared as the index it names."""
    owner = dashboard.coordinator
    monkeypatch.setattr(owner, 'run_job', lambda *args, **kwargs: None)
    first = record(owner, 'aaaaaaaaaaaa', '1')
    owner.admit_jobs([first], first)

    second = record(owner, 'bbbbbbbbbbbb', 1)
    with pytest.raises(errors.CapacityFull):
        owner.admit_jobs([second], second)
    assert owner.busy_devices() == {1: ['aaaaaaaaaaaa']}


def test_a_host_without_a_gpu_is_refused_without_claiming_one(dashboard, monkeypatch):
    """Admission keeps its one-at-a-time fallback, but the refusal must not name a GPU this host does not have."""
    monkeypatch.setattr(devices, 'detect', lambda *arguments, **keywords: [])
    owner = dashboard.coordinator
    monkeypatch.setattr(owner, 'run_job', lambda *args, **kwargs: None)
    first = record(owner, 'aaaaaaaaaaaa', 0)
    owner.admit_jobs([first], first)

    second = record(owner, 'bbbbbbbbbbbb', 0)
    with pytest.raises(errors.CapacityFull) as refused:
        owner.admit_jobs([second], second)

    message = str(refused.value)
    assert 'GPU' not in message, message
    assert message == ('A simulation is already running on this host. '
                       'Wait for it to stop before starting another.')


def test_a_share_run_is_admitted_one_beyond_the_ceiling_and_the_next_is_refused(dashboard, monkeypatch):
    """`share` buys exactly one extra slot: the run alongside stays, the third is refused as today."""
    owner = dashboard.coordinator
    monkeypatch.setattr(owner, 'run_job', lambda *args, **kwargs: None)
    first = record(owner, 'aaaaaaaaaaaa', 0)
    owner.admit_jobs([first], first)
    second = record(owner, 'bbbbbbbbbbbb', 0, 'share')
    owner.admit_jobs([second], second)

    third = record(owner, 'cccccccccccc', 0, 'share')
    with pytest.raises(errors.CapacityFull):
        owner.admit_jobs([third], third)

    assert set(owner.WORKERS) == {'aaaaaaaaaaaa', 'bbbbbbbbbbbb'}
    assert owner.database().get('cccccccccccc') is None


def test_a_queue_run_created_while_busy_is_held_with_the_marker_and_no_worker(dashboard, monkeypatch):
    """A full device does not refuse a `queue` run; it is stored waiting and stays out of `WORKERS`."""
    owner = dashboard.coordinator
    monkeypatch.setattr(owner, 'run_job', lambda *args, **kwargs: None)
    first = record(owner, 'aaaaaaaaaaaa', 0)
    owner.admit_jobs([first], first)

    held = record(owner, 'bbbbbbbbbbbb', 0, 'queue')
    owner.admit_jobs([held], held)

    row = owner.database().get('bbbbbbbbbbbb')
    assert row['status'] == 'queued' and row['stage'] == 'queued'
    assert row['gpu_queue']['device'] == 0 and row['gpu_queue']['requested_at']
    assert 'bbbbbbbbbbbb' not in owner.WORKERS, 'a held run started a worker'


def test_a_queue_run_created_with_room_starts_at_once(dashboard, monkeypatch):
    """`queue` is held only for capacity: on a free device it takes the normal path, with no marker."""
    owner = dashboard.coordinator
    monkeypatch.setattr(owner, 'run_job', lambda *args, **kwargs: None)
    job = record(owner, 'aaaaaaaaaaaa', 0, 'queue')
    owner.admit_jobs([job], job)

    assert 'aaaaaaaaaaaa' in owner.WORKERS
    assert owner.database().get('aaaaaaaaaaaa').get('gpu_queue') is None


def test_releasing_the_busy_run_starts_the_held_queue_run(dashboard, monkeypatch):
    """A worker's release is what frees the slot, so the same release starts the held row.

    The busy run is completed by the real `run_job` with a ready adapter and an empty stage plan: its exit hook
    pops the worker and starts the held row. The held row's marker is cleared only after its worker is registered,
    so a cleared marker is the proof a thread was started rather than merely intended.
    """
    owner = dashboard.coordinator
    monkeypatch.setattr(protocol, 'adapter_for', lambda name: _FakeAdapter())
    monkeypatch.setattr(workflow, 'run', lambda *args, **kwargs: None)
    busy = dict(record(owner, 'aaaaaaaaaaaa', 0), status='running', stage='input', layout_version=2)
    owner.database().insert(busy)
    busy_worker = owner.Worker()
    owner.WORKERS['aaaaaaaaaaaa'] = busy_worker

    held = record(owner, 'bbbbbbbbbbbb', 0, 'queue')
    owner.admit_jobs([held], held)
    assert 'bbbbbbbbbbbb' not in owner.WORKERS

    owner.run_job('aaaaaaaaaaaa', busy_worker)

    assert owner.lookup('aaaaaaaaaaaa')['status'] == 'completed'
    row = owner.lookup('bbbbbbbbbbbb')
    assert row['gpu_queue'] is None, 'the held row was not started when the device freed'
    deadline = time.monotonic() + 10
    while row['status'] == 'queued' and time.monotonic() < deadline:
        time.sleep(.02)
        row = owner.lookup('bbbbbbbbbbbb')
    assert row['status'] != 'queued', row


def test_a_held_queue_row_survives_reconcile_but_other_queued_rows_still_fail(dashboard):
    """A restart must not fail a run that never started; a queued row with no marker keeps today's failure."""
    owner = dashboard.coordinator
    held = record(owner, 'bbbbbbbbbbbb', 0, 'queue')
    held['gpu_queue'] = {'device': 0, 'requested_at': owner.now()}
    orphan = record(owner, 'cccccccccccc', 0)
    owner.database().insert_many([held, orphan])

    owner.reconcile()

    assert owner.lookup('bbbbbbbbbbbb')['status'] == 'queued'
    assert owner.lookup('cccccccccccc')['status'] == 'failed'



def test_a_held_queue_run_can_be_cancelled_and_is_never_started(dashboard, monkeypatch):
    """A run waiting for a device has no worker, so Cancel is the record's own move and the queue cannot revive it."""
    owner = dashboard.coordinator
    monkeypatch.setattr(owner, 'run_job', lambda *args, **kwargs: None)
    busy = record(owner, 'aaaaaaaaaaaa', 0)
    owner.admit_jobs([busy], busy)
    held = record(owner, 'bbbbbbbbbbbb', 0, 'queue')
    owner.admit_jobs([held], held)

    assert owner.ownership(owner.lookup('bbbbbbbbbbbb'))['can_cancel'] is True, 'a held run offers no Cancel'

    cancelled, status = owner.cancel_job('bbbbbbbbbbbb')

    assert status == 200 and cancelled['status'] == 'cancelled'
    row = owner.lookup('bbbbbbbbbbbb')
    assert row['gpu_queue'] is None, 'the cancelled row still claims the device queue'
    assert row['error'] == 'Cancelled while waiting for a free GPU'
    assert owner.ownership(row)['can_delete'] is True

    # The release that would have started it must not: a cancelled row is no longer queued.
    owner.WORKERS.pop('aaaaaaaaaaaa', None)
    owner.start_queued()
    assert owner.lookup('bbbbbbbbbbbb')['status'] == 'cancelled'
    assert 'bbbbbbbbbbbb' not in owner.WORKERS
