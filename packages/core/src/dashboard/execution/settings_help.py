"""The one server-side map from a New run setting to the text that explains it.

The MDP option text is quoted from the GROMACS manual page for `.mdp` options, and the execution-flag text from the
installed `gmx mdrun -h` (GROMACS 2026.3 here): both are environment facts, not the dashboard's opinion, so they live
here rather than in `dashboard.html`, and `/api/defaults` returns this map so the form renders one copy of it.

`PROJECT_HELP` is the exception and says so in its own text: GROMACS has no manual entry for a seed the dashboard
draws from, or for the box shape the protocol chose, so those sentences are the project's.

The manual the MDP text comes from: https://manual.gromacs.org/2026-rc/user-guide/mdp-options.html (2026-rc edition,
the one this build documents). `MDRUN_SOURCE` names the binary whose `-h` the execution text quotes.
"""
MDP_MANUAL_URL = 'https://manual.gromacs.org/2026-rc/user-guide/mdp-options.html'
MDRUN_SOURCE = 'gmx mdrun -h (GROMACS 2026.3)'
PROJECT_SOURCE = 'Dashboard text, not GROMACS'

#: MDP option meanings, quoted from the manual page above and keyed by the setting name the form posts. The manual
#: spells the option with dashes (`verlet-buffer-tolerance`); the form posts the underscores it stores.
MDP_HELP = {
    'nstlog': 'number of steps that elapse between writing energies to the log file, the first and last energies '
              'are always written',
    'nstenergy': 'number of steps that elapse between writing energies to the energy file (edr), the first and '
                 'last energies are always written, should be a multiple of nstcalcenergy',
    'nstxtcout': 'number of steps that elapse between writing position coordinates using lossy compression (xtc '
                 'file); the manual spells this option nstxout-compressed',
    'xtc_precision': 'precision with which to write to the compressed trajectory file; the manual spells this '
                     'option compressed-x-precision',
    'nstcomm': 'interval for center of mass motion removal',
    'nstlist': 'interval between steps that update the neighbor list; with dynamics and a Verlet buffer tolerance '
               'this is a minimum value and gmx mdrun might increase it',
    'verlet_buffer_tolerance': 'the maximum allowed error for pair interactions per particle caused by the Verlet '
                               'buffer, which indirectly sets rlist',
    'rlist': 'cut-off distance for the short-range neighbor list; with dynamics this is by default set by the '
             'verlet-buffer-tolerance and the value of rlist is ignored',
    'rcoulomb': 'the distance for the Coulomb cut-off',
    'rvdw': 'distance for the LJ or Buckingham cut-off',
    'tau_t': 'time constant for coupling (one for each group in tc-grps); -1 means no temperature coupling',
    'tau_p': 'the time constant for pressure coupling (one value for all directions)',
    'compressibility': 'the compressibility, in bar^-1; for water at 1 atm and 300 K it is 4.5e-5 bar^-1',
}

#: Execution-flag meanings, quoted from `gmx mdrun -h` on the installed build.
MDRUN_HELP = {
    'mdrun_ntomp': 'Number of OpenMP threads per MPI rank to start (0 is guess)',
    'mdrun_ranks': 'The MPI ranks are separate processes under mpirun, so this is the rank count; '
                   '`-ntmpi` is a thread-MPI option and this build was compiled without thread-MPI',
    'mdrun_gpu': 'List of unique GPU device IDs available to use; the index is the CUDA ordinal',
    'mdrun_nb': 'Calculate non-bonded interactions on: auto, cpu, gpu',
    'mdrun_pme': 'Perform PME calculations on: auto, cpu, gpu',
    'mdrun_pmefft': 'Perform PME FFT calculations on: auto, cpu, gpu',
    'mdrun_update': 'Perform update and constraints on: auto, cpu, gpu',
    'mdrun_tunepme': 'Optimize PME load between PP/PME ranks or GPU/CPU; GROMACS defaults to on, so auto emits '
                     'no flag',
    'mdrun_cpt': 'Checkpoint interval (minutes)',
}

#: Settings GROMACS has no entry for: the seed the dashboard writes into the CG MDPs, and the unit cell the
#: single-solute protocol builds.
PROJECT_HELP = {
    'cg_seed': 'The seed written into the CG MDPs as gen-seed and ld-seed (dashboard text, not GROMACS): the same '
               'number for the velocity draw and the stochastic term, so a run can be repeated.',
    'box_shape': 'The unit cell the single-solute protocol builds (dashboard text, not GROMACS). The cube is the '
                 'protocol shape and the measured faster one here; the dodecahedron holds this cut-off in more '
                 'water and ran 12% slower.',
}

#: What the form renders: one map keyed by setting name, whichever source a sentence came from.
HELP = {**MDP_HELP, **MDRUN_HELP, **PROJECT_HELP}

#: Where each family of sentences comes from, so the panel can attribute the text it shows.
SOURCES = {'mdp': MDP_MANUAL_URL, 'mdrun': MDRUN_SOURCE, 'project': PROJECT_SOURCE}

__all__ = ['HELP', 'MDP_HELP', 'MDRUN_HELP', 'PROJECT_HELP', 'SOURCES', 'MDP_MANUAL_URL', 'MDRUN_SOURCE']
