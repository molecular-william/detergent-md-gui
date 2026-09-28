"""The AA stage commands must be runnable by the GROMACS build this host actually has.

`/usr/local/gromacs/2026.3/bin/gmx` on this machine is a symlink to `gmx_mpi`: an MPI build with no
thread-MPI. `-ntmpi` is a thread-MPI option, so passing it made mdrun abort before the first minimization
step, which is why no run had ever completed here. `-ntomp` is valid for both builds.
"""
import subprocess

from dashboard.execution.adapters import aa


def test_no_generated_mdrun_command_passes_a_thread_mpi_only_flag():
    """-ntmpi is only valid for a thread-MPI build; this host has none. Checked against the mdrun command
    lines rather than the whole file, because the file's own comment names the flag it must not pass."""
    commands = [line for line in open(aa.__file__).read().splitlines() if 'gmx mdrun' in line]
    assert commands, 'the adapter builds mdrun commands'
    assert not any('-ntmpi' in line for line in commands), commands
    assert any('-ntomp' in line for line in commands)


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
