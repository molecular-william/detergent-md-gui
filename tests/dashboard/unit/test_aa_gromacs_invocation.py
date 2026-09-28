"""The AA stage commands must be runnable by the GROMACS build this host actually has.

`/usr/local/gromacs/2026.3/bin/gmx` on this machine is a symlink to `gmx_mpi`: an MPI build with no
thread-MPI. `-ntmpi` is a thread-MPI option, so passing it made mdrun abort before the first minimization
step, which is why no run had ever completed here. `-ntomp` is valid for both builds.
"""
import os
import subprocess

from dashboard.execution.adapters import aa


def test_no_mdrun_command_in_the_project_passes_a_thread_mpi_only_flag():
    """The generated commands are not the only ones that can run here.

    The legacy launchers under `execution/scripts/` are kept and have their own tests, so a thread-MPI flag
    there is exactly as fatal as one in a generated command -- and it fails on the one machine that matters, at
    the first mdrun, which is how the runs directory stayed empty.
    """
    from pathlib import Path

    scripts = sorted((Path(aa.__file__).parents[1] / 'scripts').glob('*.sh'))
    sources = [Path(aa.__file__), *scripts]
    commands = [(path.name, line) for path in sources
                for line in path.read_text().splitlines() if 'gmx mdrun' in line]
    assert commands, 'mdrun commands were found to check'
    assert [name for name, line in commands if '-ntmpi' in line] == [], 'thread-MPI flag in an mdrun command'


def test_no_generated_mdrun_command_passes_a_thread_mpi_only_flag():
    """-ntmpi is only valid for a thread-MPI build; this host has none. Checked against the mdrun command
    lines rather than the whole file, because the file's own comment names the flag it must not pass. What
    the flags actually render to is pinned by the mdrun_launch tests below."""
    commands = [line for line in open(aa.__file__).read().splitlines() if 'gmx mdrun' in line]
    assert commands, 'the adapter builds mdrun commands'
    assert not any('-ntmpi' in line for line in commands), commands


def test_the_resolved_gromacs_is_indeed_an_mpi_build():
    """The reason the flag is absent, checked against the binary rather than asserted in prose."""
    resolved = '/usr/local/gromacs/2026.3/bin/gmx'
    try:
        report = subprocess.run([resolved, '--version'], capture_output=True, text=True, timeout=60)
    except OSError:
        return
    text = report.stdout + report.stderr
    assert 'MPI library' in text, text[:200]
    assert 'thread MPI' not in text, 'if this becomes a thread-MPI build, -ntmpi is valid again'


def test_the_mdrun_cpu_budget_comes_from_the_stage_settings():
    """This host has no thread-MPI, so the second CPU lever is MPI ranks under mpirun, not -ntmpi."""
    assert aa.mdrun_launch({'mdrun_ntomp': 16, 'mdrun_ranks': 2}) == ('mpirun -np 2 ', '-ntomp 16')


def test_a_single_rank_keeps_the_command_it_always_had():
    assert aa.mdrun_launch({}) == ('', '-ntomp 8')


def test_the_cpu_budget_is_checked_against_the_machine():
    cores = os.cpu_count() or 1
    try:
        aa.mdrun_launch({'mdrun_ntomp': cores, 'mdrun_ranks': 2})
    except ValueError as error:
        assert 'CPU slots' in str(error)
    else:
        raise AssertionError('using more CPU slots than the machine has must be refused')


def test_both_settings_are_offered_to_the_run_panel_with_bounds():
    """The panel renders SETTING_SPECS, so a setting that is not in here cannot be chosen."""
    assert aa.SETTING_SPECS['mdrun_ntomp'] == ('mdrun OpenMP threads per rank', 1, 72)
    assert aa.SETTING_SPECS['mdrun_ranks'] == ('mdrun MPI ranks', 1, 72)
