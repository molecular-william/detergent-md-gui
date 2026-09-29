"""The mdrun scheme choices: what they add to a command, and what they refuse to add.

`-nb` and `-pme` are the two mdrun levers whose values are not numbers, so they travel as strings and are
validated as choices rather than ranges. The load-bearing claim is the first test: leaving both on 'auto' has to
produce exactly the command every run produced before these settings existed, or the manifests already recorded
would stop meaning what they say.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.execution.adapters.aa import mdrun_command_flags, mdrun_launch, normalize_settings  # noqa: E402


def flags(settings):
    """The flavour is stated rather than probed: the builder is what is under test, not this host's build.

    Asking the binary costs 1.3 s per call here, and the answer would make these assertions depend on the
    GROMACS build installed on the machine. test_aa_gromacs_invocation.py pins the probe and the launcher
    choice it drives, with an explicit flavour for each side of it.
    """
    return mdrun_launch(settings, 'mpi')[1]


def test_auto_emits_nothing_so_an_untouched_run_keeps_its_command():
    assert flags({}) == '-ntomp 8'
    assert flags({'mdrun_nb': 'auto', 'mdrun_pme': 'auto'}) == '-ntomp 8'
    # The execution profile's own GPU flags are not duplicated here: 'auto' leaves them to the profile.
    assert '-nb' not in flags({}) and '-pme' not in flags({})


def test_the_nonbonded_choice_reaches_the_command():
    assert flags({'mdrun_nb': 'cpu'}) == '-ntomp 8 -nb cpu'
    assert flags({'mdrun_nb': 'gpu'}) == '-ntomp 8 -nb gpu'


def test_the_pme_choice_carries_its_fft_flag_and_needs_the_gpu_nonbonded_scheme():
    assert flags({'mdrun_nb': 'gpu', 'mdrun_pme': 'gpu'}) == '-ntomp 8 -nb gpu -pme gpu -pmefft gpu'
    with pytest.raises(ValueError, match='needs mdrun_nb gpu'):
        flags({'mdrun_pme': 'gpu'})


def test_the_thread_budget_and_the_scheme_choices_coexist():
    assert flags({'mdrun_ranks': 2, 'mdrun_ntomp': 4, 'mdrun_nb': 'cpu'}) == '-ntomp 4 -nb cpu'
    assert mdrun_launch({'mdrun_ranks': 2}, 'mpi')[0] == 'mpirun -np 2 '


def test_an_unknown_scheme_is_refused_rather_than_passed_through():
    with pytest.raises(ValueError, match='must be one of'):
        flags({'mdrun_nb': 'cuda'})
    with pytest.raises(ValueError, match='must be one of'):
        normalize_settings({'mdrun_pme': 'both'})


def test_the_shared_flag_helper_replaces_the_gpu_bracket_rather_than_stacking_on_it():
    """A generated command and a stage script read the same flags, so the bracket and the settings must agree.

    The bracket is what these stages have always run: GPU nonbonded, PME on the GPU except in minimisation. A
    setting replaces the flag it names -- emitting both would leave GROMACS to take the last one -- and with
    everything on 'auto' the result is the command these stages produced before the settings existed.
    """
    # A setting replaces the bracket flag it names, so no value appears twice and none contradicts it.
    assert mdrun_command_flags({}, 'em', 'mpi') == ('', '-ntomp 8 -gpu_id 0 -nb gpu -pin on')
    assert mdrun_command_flags({}, 'production', 'mpi') == (
        '', '-ntomp 8 -gpu_id 0 -nb gpu -pin on -pme gpu -pmefft gpu')
    cpu_nb = mdrun_command_flags({'mdrun_nb': 'cpu'}, 'production', 'mpi')[1].split()
    assert cpu_nb.count('-nb') == 1 and cpu_nb[cpu_nb.index('-nb') + 1] == 'cpu'
    cpu_pme = mdrun_command_flags({'mdrun_nb': 'gpu', 'mdrun_pme': 'cpu'}, 'production', 'mpi')[1].split()
    assert cpu_pme.count('-pme') == 1 and cpu_pme[cpu_pme.index('-pme') + 1] == 'cpu'
    assert '-pmefft' not in cpu_pme  # the FFT flag belongs to a GPU PME and goes with it
    launcher, flags = mdrun_command_flags({'mdrun_ranks': 2, 'mdrun_ntomp': 4}, 'production', 'mpi')
    assert launcher == 'mpirun -np 2 ' and flags.startswith('-ntomp 4 ')


def test_a_choice_survives_normalization_and_the_numeric_ranges_still_apply():
    normalized = normalize_settings({'mdrun_nb': 'gpu', 'mdrun_pme': 'gpu'})
    assert normalized['mdrun_nb'] == 'gpu' and normalized['mdrun_pme'] == 'gpu'
    assert normalized['mdrun_ntomp'] == 8  # the defaults still carry the numeric settings
    with pytest.raises(ValueError, match='must be one of'):
        normalize_settings({'mdrun_nb': 1})  # a number is not a choice
    with pytest.raises(ValueError, match='must be between'):
        normalize_settings({'mdrun_ntomp': 999})
