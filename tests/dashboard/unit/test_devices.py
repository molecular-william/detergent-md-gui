"""The host's GPU devices, as a record -- read from recorded `nvidia-smi` text, never from a GPU.

Three things this module has to get right, and each has a test because each has a failure mode that reads as a
plausible answer rather than as an error:

* **A device name can carry a comma.** `nvidia-smi` prints `index, name, memory, uuid` as plain CSV, so the split
  is from the right: an unquoted name with a comma in it otherwise becomes an extra field and the UUID lands in
  the name.
* **A host without the tool reports no devices.** `[]` is the answer, not a refusal -- and not an exception. What
  the run then does is mdrun's business.
* **A process on a device this host no longer reports is not counted.** `--query-compute-apps` answers in UUIDs
  and a stale process can name a device that is gone (a MIG slice, a GPU reset); counting it against whatever
  index is free would be the panel saying "device 1 is busy" about a device 1 that is not the one.
"""
import pytest

from dashboard.execution import devices

SINGLE = '0, NVIDIA GeForce RTX 4090, 24564, GPU-0a1b2c3d-1111-2222-3333-444455556666\n'
#: Two devices, and the second's name carries a comma. That is what a real `nvidia-smi` answers for a MIG
#: instance, and it is the case that makes "split on every comma" wrong.
TWO = ('0, NVIDIA GeForce RTX 4090, 24564, GPU-aaaa-1111\n'
       '1, NVIDIA A100-SXM4-40GB, MIG 1g.5gb, 4864, GPU-bbbb-2222\n')
PROCESSES = ('GPU-aaaa-1111, 4242, /usr/lib/python3/dist-packages/pymol\n'
             'GPU-bbbb-2222, 4343, gmx_mpi\n'
             'GPU-bbbb-2222, 4444, gmx_mpi\n')


@pytest.fixture(autouse=True)
def clean_cache():
    """Each test asks its own host: the device list is remembered for 30 s, which would outlive a stub."""
    devices.clear_cache()
    yield
    devices.clear_cache()


def recorded(monkeypatch, gpus='', processes=''):
    """Answer the query with recorded text, so no test needs a GPU or an `nvidia-smi`."""
    def run(arguments, timeout):
        return processes if arguments[0].startswith('--query-compute-apps') else gpus
    monkeypatch.setattr(devices, '_run', run)


def test_a_recorded_line_becomes_a_device(monkeypatch):
    recorded(monkeypatch, SINGLE)
    assert devices.detect() == [{'index': 0, 'name': 'NVIDIA GeForce RTX 4090',
                                 'memory_mib': 24564, 'uuid': 'GPU-0a1b2c3d-1111-2222-3333-444455556666'}]


def test_a_name_that_carries_a_comma_is_one_name(monkeypatch):
    recorded(monkeypatch, TWO)
    first, second = devices.detect()
    assert first['index'] == 0 and first['memory_mib'] == 24564 and first['uuid'] == 'GPU-aaaa-1111'
    assert second == {'index': 1, 'name': 'NVIDIA A100-SXM4-40GB, MIG 1g.5gb', 'memory_mib': 4864,
                      'uuid': 'GPU-bbbb-2222'}


def test_a_host_without_the_tool_reports_no_devices(monkeypatch):
    """No `nvidia-smi` is an answer: this is a CPU-only host, and no run is refused for it."""
    monkeypatch.setattr(devices, '_executable', lambda: None)
    assert devices.detect() == []
    assert devices.in_use() == {}
    assert devices.describe(0) is None


def test_a_line_that_does_not_parse_is_skipped_not_raised(monkeypatch):
    recorded(monkeypatch, 'not a device line\n' + SINGLE + '0, GPU with no uuid, 100\n')
    found = devices.detect()
    assert [device['index'] for device in found] == [0]
    assert found[0]['name'] == 'NVIDIA GeForce RTX 4090'


def test_a_mig_slice_reports_no_total_and_is_still_a_device(monkeypatch):
    """`[N/A]` memory is not a parse failure: the device exists and is selectable, its memory is unknown."""
    recorded(monkeypatch, '2, NVIDIA H100, [N/A], GPU-cccc-3333\n')
    assert devices.detect() == [{'index': 2, 'name': 'NVIDIA H100', 'memory_mib': None, 'uuid': 'GPU-cccc-3333'}]


def test_in_use_counts_processes_by_device_and_skips_unknown_uuids(monkeypatch):
    recorded(monkeypatch, TWO, PROCESSES + 'GPU-gone-9999, 5555, a process on a device nobody reports\n')
    assert devices.in_use() == {0: 1, 1: 2}


def test_in_use_of_an_idle_host_is_empty(monkeypatch):
    """Nothing running is `{}` -- and that is "nothing reported", which is what the note must say."""
    recorded(monkeypatch, TWO, '')
    assert devices.in_use() == {}


def test_describe_answers_one_index_or_none(monkeypatch):
    recorded(monkeypatch, TWO)
    assert devices.describe(1)['uuid'] == 'GPU-bbbb-2222'
    assert devices.describe(7) is None
    assert devices.describe('not an index') is None


def test_usage_is_the_record_a_run_keeps(monkeypatch):
    recorded(monkeypatch, TWO, PROCESSES)
    assert devices.usage(1) == {'index': 1, 'name': 'NVIDIA A100-SXM4-40GB, MIG 1g.5gb',
                                'uuid': 'GPU-bbbb-2222', 'compute_processes': 2}
    recorded(monkeypatch, TWO, '')
    assert devices.usage(0)['compute_processes'] == 0


def test_usage_without_a_device_keeps_the_index_and_invents_nothing(monkeypatch):
    recorded(monkeypatch, '')
    assert devices.usage(3) == {'index': 3, 'name': None, 'uuid': None, 'compute_processes': 0}


def test_require_names_the_devices_that_exist(monkeypatch):
    recorded(monkeypatch, TWO)
    assert devices.require(1)['name'] == 'NVIDIA A100-SXM4-40GB, MIG 1g.5gb'
    with pytest.raises(ValueError) as refusal:
        devices.require(4)
    message = str(refusal.value)
    assert 'GPU 4 is not present on this host' in message
    assert '0 (NVIDIA GeForce RTX 4090)' in message and '1 (NVIDIA A100-SXM4-40GB, MIG 1g.5gb)' in message


def test_require_does_not_refuse_a_host_that_reports_nothing(monkeypatch):
    """Headless and CPU-only hosts exist, and today's command already assumed a GPU: mdrun speaks, not prepare."""
    recorded(monkeypatch, '')
    assert devices.require(3) is None


def test_the_environment_record_carries_every_device(monkeypatch):
    recorded(monkeypatch, TWO)
    assert devices.environment_record({'PATH': '/bin'}) == {
        'PATH': '/bin', 'devices': devices.detect()}
    assert len(devices.environment_record()['devices']) == 2
