"""Admission is per GPU: a run on a free device starts beside a run on a busy one.

The coordinator's active runs are the claim on a device. A job names its own device in `settings['mdrun_gpu']`,
which is the index its mdrun will use, so the same index is what refuses the next start. The runs here never
execute: `run_job` is replaced with a no-op, which leaves the admitted worker registered -- the same state an
active simulation is in while it runs.
"""
import pytest
from dashboard.execution import devices
from dashboard.execution.coordination import errors

pytestmark = pytest.mark.usefixtures('gpu_host')


def record(owner, jid, gpu):
    """One job a caller wants to start on `gpu`; the fields admission reads and nothing else."""
    return {'id': jid, 'label': jid, 'status': 'queued', 'stage': 'queued', 'created': owner.now(),
            'settings': {'mdrun_gpu': gpu}, 'run_type': 'osmotic'}


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
