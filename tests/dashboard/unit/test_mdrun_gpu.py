"""`mdrun_gpu`: the device is a setting, and one builder is what writes it into every command.

The device was a literal in three places -- `aa.MDRUN_GPU_NONBONDED_FLAGS`, the pdc stage scripts' fallbacks and
the AA reference / CG launcher scripts -- which meant a run could record one device and execute another. It is one
integer setting now, `0` by default, and `aa.mdrun_command_flags` is the only thing that turns it into `-gpu_id`.

Two claims carry the acceptance:

* **The default is byte-identical.** A run that never touches the setting produces exactly the command every run
  before it produced, so nothing moves silently.
* **A named device is the one that reaches the flag**, in both brackets, under either launcher flavour, for every
  run type that publishes the setting.
"""
import json

import pytest

from dashboard.execution import devices
from dashboard.execution.adapters import aa, cg, osmotic, pdc
from tests.dashboard.support import PROJECT_ROOT

MOLECULES = PROJECT_ROOT / 'molecules'
#: The command every AA stage produced before the setting existed, and what an untouched form still produces.
DEFAULT_BRACKET = '-gpu_id 0 -nb gpu -pin on'
DEFAULT_DYNAMICS = DEFAULT_BRACKET + ' -pme gpu -pmefft gpu'


@pytest.fixture(autouse=True)
def clean_cache():
    devices.clear_cache()
    yield
    devices.clear_cache()


def two_devices(monkeypatch):
    """A host with two GPUs, recorded -- no test here needs one."""
    monkeypatch.setattr(devices, 'detect', lambda *arguments, **keywords: [
        {'index': 0, 'name': 'NVIDIA GeForce RTX 4090', 'memory_mib': 24564, 'uuid': 'GPU-aaaa'},
        {'index': 1, 'name': 'NVIDIA A100-SXM4-40GB', 'memory_mib': 40960, 'uuid': 'GPU-bbbb'}])


def test_the_constants_are_the_default_bracket():
    """The constants stay for the callers that read them, and they mean device 0 -- no more and no less."""
    assert aa.MDRUN_GPU_NONBONDED_FLAGS == '-gpu_id 0 -nb gpu -pin on'
    assert aa.MDRUN_GPU_PME_FLAGS == f'{DEFAULT_BRACKET} -pme gpu -pmefft gpu'


@pytest.mark.parametrize('flavour', ['mpi', 'thread-mpi'])
def test_untouched_settings_produce_the_command_they_always_did(flavour):
    assert aa.mdrun_command_flags({}, 'em', flavour) == ('', f'-ntomp 8 {DEFAULT_BRACKET}')
    assert aa.mdrun_command_flags({}, 'production', flavour) == ('', f'-ntomp 8 {DEFAULT_DYNAMICS}')
    # An explicit 0 is the same request as no key at all.
    assert aa.mdrun_command_flags({'mdrun_gpu': 0}, 'production', flavour) == \
        ('', f'-ntomp 8 {DEFAULT_DYNAMICS}')


@pytest.mark.parametrize('flavour', ['mpi', 'thread-mpi'])
def test_the_chosen_device_reaches_the_command_in_both_brackets(flavour):
    minimization = aa.mdrun_command_flags({'mdrun_gpu': 2}, 'em', flavour)[1]
    dynamics = aa.mdrun_command_flags({'mdrun_gpu': 2}, 'production', flavour)[1]
    assert ' -gpu_id 2 -nb gpu -pin on' in f' {minimization}'
    assert ' -gpu_id 2 -nb gpu -pin on -pme gpu -pmefft gpu' in f' {dynamics}'
    assert '-gpu_id 0' not in minimization and '-gpu_id 0' not in dynamics


def test_the_device_travels_with_the_ranks_that_share_it():
    """Several ranks still name one device -- the panel says so, and the flag says so."""
    launcher, flags = aa.mdrun_command_flags({'mdrun_gpu': 1, 'mdrun_ranks': 3, 'mdrun_ntomp': 4}, 'production', 'mpi')
    assert launcher == 'mpirun -np 3 '
    assert ' -gpu_id 1 ' in f' {flags}' and '-ntomp 4' in flags


def test_the_device_is_a_whole_index_defaulting_to_zero():
    assert aa.normalize_settings({})['mdrun_gpu'] == 0
    assert isinstance(aa.normalize_settings({})['mdrun_gpu'], int)
    assert aa.normalize_settings({'mdrun_gpu': '1'})['mdrun_gpu'] == 1
    with pytest.raises(ValueError, match='mdrun_gpu must be an integer'):
        aa.normalize_settings({'mdrun_gpu': 1.5})
    with pytest.raises(ValueError, match='mdrun_gpu must be between'):
        aa.normalize_settings({'mdrun_gpu': -1})


def test_every_run_type_that_runs_mdrun_publishes_the_device():
    for adapter in (aa.PROTOCOL, cg.PROTOCOL, pdc.PROTOCOL, osmotic.PROTOCOL):
        assert adapter.settings_specs()['mdrun_gpu'] == ('mdrun GPU device', 0, 64), adapter.name


def test_an_aa_cg_run_keeps_the_device_it_was_given():
    """The AA half's key is filtered out of an AA-to-CG build -- except the ones that are the run's own execution."""
    assert cg.run_settings({'mdrun_gpu': 1, 'aa_nvt_ps': 20, 'cg_seed': 7}) == {'mdrun_gpu': 1, 'cg_seed': 7}
    assert cg.normalize_settings({'mdrun_gpu': 1})['mdrun_gpu'] == 1


def test_the_cpu_budget_a_form_posts_is_the_runs_and_reaches_both_halves():
    """The budget belongs to the run, not to the reference it consumes.

    The dialect filter used to drop `mdrun_ntomp` and `mdrun_ranks` with the rest of the AA half's keys, so an AA-to-CG
    form asking for 16 threads ran the atomistic half at 8 while the panel showed 16 -- a control whose value no stage
    consumed. Kept here, they survive the filter and the one builder turns them into the command the stage runs; the
    reference's own recorded budget stays provenance, not an instruction.
    """
    kept = cg.run_settings({'mdrun_ntomp': 16, 'mdrun_ranks': 2, 'mdrun_gpu': 1, 'aa_nvt_ps': 20, 'cg_seed': 7})
    assert kept == {'mdrun_ntomp': 16, 'mdrun_ranks': 2, 'mdrun_gpu': 1, 'cg_seed': 7}
    launcher, flags = aa.mdrun_command_flags(kept, 'md', 'pme')
    assert '-ntomp 16' in flags and '-gpu_id 1' in flags
    assert 'np 2' in launcher


def test_pdc_and_osmotic_accept_the_setting_and_default_it():
    assert pdc.normalize_settings({})['mdrun_gpu'] == 0
    assert pdc.normalize_settings({'mdrun_gpu': 2})['mdrun_gpu'] == 2
    with pytest.raises(ValueError, match='mdrun_gpu must be an integer'):
        pdc.normalize_settings({'mdrun_gpu': 0.5})
    assert osmotic.normalize_settings({'molalities': [1.0]})['mdrun_gpu'] == 0
    assert osmotic.normalize_settings({'molalities': [1.0], 'mdrun_gpu': 1})['mdrun_gpu'] == 1
    with pytest.raises(ValueError, match='mdrun_gpu must be a whole device index'):
        osmotic.normalize_settings({'molalities': [1.0], 'mdrun_gpu': 1.5})


def test_prepare_refuses_a_device_the_host_does_not_have(tmp_path, monkeypatch):
    two_devices(monkeypatch)
    monkeypatch.setattr(aa, 'tool_metadata', lambda: {'gmx': {'path': 'gmx', 'version_output': 'test'}})
    monkeypatch.setattr(aa, 'gromacs_flavour', lambda *arguments, **keywords: 'mpi')
    from dashboard.models.molecules import aa as aa_molecules
    selected = aa_molecules.selection(MOLECULES, 'DDM', run_type='aa_only')
    with pytest.raises(ValueError) as refusal:
        aa.prepare_run(tmp_path, MOLECULES, selected, {'box_nm': 4.0, 'mdrun_gpu': 5})
    message = str(refusal.value)
    assert 'GPU 5 is not present on this host' in message
    assert '0 (NVIDIA GeForce RTX 4090)' in message and '1 (NVIDIA A100-SXM4-40GB)' in message
    # Refused before anything was written, so there is no half-built run to mistake for a prepared one.
    assert not (tmp_path / 'stages').exists()


def test_prepare_does_not_refuse_when_the_host_reports_no_devices(tmp_path, monkeypatch):
    """A headless or CPU-only host is not an error: today's command already assumed a GPU, and mdrun speaks."""
    monkeypatch.setattr(devices, 'detect', lambda *arguments, **keywords: [])
    monkeypatch.setattr(aa, 'tool_metadata', lambda: {'gmx': {'path': 'gmx', 'version_output': 'test'}})
    monkeypatch.setattr(aa, 'gromacs_flavour', lambda *arguments, **keywords: 'mpi')
    from dashboard.models.molecules import aa as aa_molecules
    selected = aa_molecules.selection(MOLECULES, 'DDM', run_type='aa_only')
    aa.prepare_run(tmp_path, MOLECULES, selected, {'box_nm': 4.0, 'mdrun_gpu': 3})
    manifest = json.loads((tmp_path / 'manifest.json').read_text())
    assert manifest['settings']['mdrun_gpu'] == 3
    assert manifest['environment']['devices'] == []
    # And the command still names the device it was asked for -- mdrun is what refuses, not this adapter.
    assert '-gpu_id 3 ' in (tmp_path / 'stages/04_nvt/run.sh').read_text()


def test_a_chosen_device_is_in_the_aa_stage_commands(tmp_path, monkeypatch):
    two_devices(monkeypatch)
    monkeypatch.setattr(aa, 'tool_metadata', lambda: {'gmx': {'path': 'gmx', 'version_output': 'test'}})
    monkeypatch.setattr(aa, 'gromacs_flavour', lambda *arguments, **keywords: 'mpi')
    from dashboard.models.molecules import aa as aa_molecules
    selected = aa_molecules.selection(MOLECULES, 'DDM', run_type='aa_only')
    aa.prepare_run(tmp_path, MOLECULES, selected, {'box_nm': 4.0, 'mdrun_gpu': 1})
    minimization = (tmp_path / 'stages/03_minimization/run.sh').read_text()
    dynamics = (tmp_path / 'stages/05_npt/run.sh').read_text()
    assert '-gpu_id 1 -nb gpu -pin on' in minimization and '-pme gpu' not in minimization
    assert '-gpu_id 1 -nb gpu -pin on -pme gpu -pmefft gpu' in dynamics


def test_a_pdc_runs_own_settings_build_the_flags_its_scripts_read():
    """The pdc stages are shell scripts, and what they read is `MDRUN_FLAGS`.

    The chain this closes: the pdc adapter's own settings keep `mdrun_gpu`, `workflow.py` hands those settings to the
    one builder, and the script reads what the builder wrote. Written here as one assertion because the failure it
    guards is a script stating a device of its own -- which is what the pdc literals used to do.
    """
    settings = pdc.normalize_settings({'mdrun_gpu': 1})
    flags = aa.mdrun_command_flags(settings, 'em', 'mpi')[1]
    assert f' {flags} '.find(' -gpu_id 1 ') >= 0
    assert '-gpu_id 0' not in flags
    assert '${MDRUN_FLAGS:-' in (PROJECT_ROOT / 'dashboard/execution/scripts/pdc_assessment.sh').read_text()
