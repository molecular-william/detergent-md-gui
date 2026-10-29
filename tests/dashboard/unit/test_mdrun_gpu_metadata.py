"""A run records which device it ran on, by the name the host reported for it.

Two places, and they answer different questions:

* `environment.devices` on the prepared run -- **every** device this host had at prepare, so a report written
  later can still say what the machine was. Written by the one shared manifest writer, plus the pdc adapter's own
  merge, so no run type can quietly omit it.
* `resource_usage.gpu` on each stage -- the index the run chose, the name and UUID the host reported for it, and
  how many compute processes were already on it when that stage started. That is what makes "which GPU produced
  this trajectory" answerable from the run's own record rather than from a flag string.
"""
import json
import subprocess

import pytest
from dashboard.execution import devices, protocol, workflow
from dashboard.execution.adapters import aa
from dashboard.models.molecules import aa as aa_molecules
from dashboard.web import views

from tests.dashboard.support import PROJECT_ROOT

MOLECULES = PROJECT_ROOT / 'molecules'
DEVICES = [{'index': 0, 'name': 'NVIDIA GeForce RTX 4090', 'memory_mib': 24564, 'uuid': 'GPU-aaaa'},
           {'index': 1, 'name': 'NVIDIA A100-SXM4-40GB', 'memory_mib': 40960, 'uuid': 'GPU-bbbb'}]


@pytest.fixture(autouse=True)
def clean_cache():
    devices.clear_cache()
    yield
    devices.clear_cache()


def stubbed_host(monkeypatch, busy=None):
    """Two devices, and `{index: count}` compute processes measured on them."""
    monkeypatch.setattr(devices, 'detect', lambda *arguments, **keywords: [dict(device) for device in DEVICES])
    monkeypatch.setattr(devices, 'in_use', lambda *arguments, **keywords: dict(busy or {}))


def prepared_run(tmp_path, monkeypatch, settings=None):
    """A real AA-only run, prepared with the tool probes stubbed -- the record a stage then extends."""
    monkeypatch.setattr(aa, 'tool_metadata', lambda: {'gmx': {'path': 'gmx', 'version_output': 'test'}})
    monkeypatch.setattr(aa, 'gromacs_flavour', lambda *arguments, **keywords: 'mpi')
    selected = aa_molecules.selection(MOLECULES, 'DDM', run_type='aa_only')
    aa.prepare_run(tmp_path, MOLECULES, selected, {'box_nm': 4.0, **(settings or {})})
    return tmp_path


def test_the_shared_writer_records_every_device_beside_the_environment(tmp_path, monkeypatch):
    stubbed_host(monkeypatch)
    run = tmp_path / 'run'
    (run / 'inputs').mkdir(parents=True)
    document = protocol.write_prepared_manifest(run, {'run_type': 'aa_only'}, tools={}, plan=[],
                                               environment={'PATH': '/bin'})
    assert document['environment'] == {'PATH': '/bin', 'devices': DEVICES}


def test_a_run_that_records_no_environment_still_records_none(tmp_path, monkeypatch):
    """The pdc adapter writes its own environment; the shared writer does not invent one for a run type."""
    stubbed_host(monkeypatch)
    run = tmp_path / 'run'
    (run / 'inputs').mkdir(parents=True)
    assert 'environment' not in protocol.write_prepared_manifest(run, {}, tools={}, plan=[])


def test_the_prepared_run_records_the_hosts_devices(tmp_path, monkeypatch):
    stubbed_host(monkeypatch)
    prepared_run(tmp_path, monkeypatch, {'mdrun_gpu': 1})
    manifest = json.loads((tmp_path / 'manifest.json').read_text())
    assert manifest['environment']['devices'] == DEVICES
    assert manifest['settings']['mdrun_gpu'] == 1


def test_each_stage_records_the_device_and_what_was_on_it(tmp_path, monkeypatch):
    """One stage run for real (its command stubbed), so the record is the one the executor writes."""
    stubbed_host(monkeypatch, busy={1: 2})
    prepared_run(tmp_path, monkeypatch, {'mdrun_gpu': 1})
    (tmp_path / 'logs').mkdir()

    def execute(command, **kwargs):
        directory = kwargs['cwd']
        (directory / 'system.gro').write_text('completed solvation output')
        (directory / 'system.top').write_text('[ system ]\n')
        return subprocess.CompletedProcess(command, 0)

    workflow.run(tmp_path, tmp_path / 'logs/console.log', execute=execute,
                 stop_after=aa.STAGES[0][0])
    stage = json.loads((tmp_path / 'manifest.json').read_text())['stages'][0]
    assert stage['resource_usage']['gpu'] == {'index': 1, 'name': 'NVIDIA A100-SXM4-40GB',
                                             'uuid': 'GPU-bbbb', 'bus_id': None, 'nvml_index': None,
                                             'compute_processes': 2}
    # The flags the stage actually ran with name the same device, and both brackets come from the one builder.
    assert '-gpu_id 1 ' in stage['environment']['MDRUN_FLAGS'] + ' '
    assert '-gpu_id 1 ' in stage['environment']['MDRUN_FLAGS_PME'] + ' '
    assert '-pme gpu' in stage['environment']['MDRUN_FLAGS_PME']
    assert '-pme gpu' not in stage['environment']['MDRUN_FLAGS']


def test_a_host_that_reports_nothing_records_the_index_and_no_name(tmp_path, monkeypatch):
    monkeypatch.setattr(devices, 'detect', lambda *arguments, **keywords: [])
    monkeypatch.setattr(devices, 'in_use', lambda *arguments, **keywords: {})
    prepared_run(tmp_path, monkeypatch)
    manifest = json.loads((tmp_path / 'manifest.json').read_text())
    assert manifest['environment']['devices'] == []
    assert manifest['settings']['mdrun_gpu'] == 0


def test_the_run_view_names_the_device_from_the_manifest():
    """The run's summary reads the name from its own record, not from the form that asked for it."""
    manifest = {'settings': {'mdrun_gpu': 1}, 'environment': {'devices': DEVICES},
                'stages': [{'resource_usage': {'gpu': {'index': 1, 'name': 'NVIDIA A100-SXM4-40GB',
                                                       'uuid': 'GPU-bbbb', 'compute_processes': 0}}}]}
    assert views.gpu_name(manifest) == 'NVIDIA A100-SXM4-40GB'
    # A run prepared before the device was recorded has no name to show, and invents none.
    assert views.gpu_name({'settings': {}, 'stages': []}) is None
    # The stage's own record answers when the environment does not carry the list.
    assert views.gpu_name({'settings': {'mdrun_gpu': 0}, 'stages': manifest['stages'] + [
        {'resource_usage': {'gpu': {'index': 0, 'name': 'NVIDIA GeForce RTX 4090', 'uuid': 'GPU-aaaa'}}}]}) \
        == 'NVIDIA GeForce RTX 4090'
    assert views.gpu_name({'settings': {'mdrun_gpu': 'not an index'}, 'stages': []}) is None
