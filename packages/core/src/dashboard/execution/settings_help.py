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
    'dt': 'the time step; the manual states dt (0.001) [ps]. The form names it in femtoseconds and the run writes '
          'fs/1000: 2 fs is this protocol, and a longer step needs hydrogen masses large enough for it -- the '
          'Hydrogen mass repartitioning field applies that to every dynamics leg',
    'mass_repartition_factor': 'scales the masses of the lightest atoms (the hydrogens) to this factor of their mass '
                               'and subtracts the difference from the atom each is bound to; the manual notes that '
                               'with constraints=h-bonds a factor of 3 will usually enable a 4 fs time step. Blank '
                               'writes no line, which is the manual default of 1 (no repartitioning); GROMACS '
                               'refuses a factor its topology cannot take',
    'nstlist': 'interval between steps that update the neighbor list; with dynamics and a Verlet buffer tolerance '
               'this is a minimum value and mdrun might increase it',
    'verlet_buffer_tolerance': 'the maximum allowed error for pair interactions per atom pair caused by the Verlet '
                               'buffer, in kJ mol^-1 ps^-1, which indirectly sets rlist; -1 uses the rlist the file '
                               'pins and disables the automatic buffer',
    'rlist': 'cut-off distance for the short-range neighbor list; with dynamics this is by default set by the '
             'verlet-buffer-tolerance and the value of rlist is ignored',
    'rcoulomb': 'the distance for the Coulomb cut-off',
    'rvdw': 'distance for the LJ or Buckingham cut-off',
    'tcoupl': 'temperature coupling: V-rescale (velocity rescaling with a stochastic term, the reviewed thermostat '
              'and a proper canonical ensemble), Nose-Hoover, Berendsen, or no',
    'tau_t': 'time constant for temperature coupling (one for each group in tc-grps); -1 means no temperature '
             'coupling',
    'pcoupl': 'pressure coupling: C-rescale (stochastic volume relaxation, used for equilibration and production), '
              'Parrinello-Rahman, Berendsen, or no (a fixed box); NVT fixes the box, so it has no barostat',
    'pcoupltype': 'the kind of pressure coupling: isotropic (one value each for compressibility and ref-p), '
                  'semiisotropic (two, x/y and z) or anisotropic (six, xx yy zz xy xz yz). The form states one '
                  'compressibility and one pressure, so a larger kind repeats them for every direction',
    'tau_p': 'the time constant for pressure coupling (one value for all directions)',
    'compressibility': 'the compressibility, in bar^-1; for water at 1 atm and 300 K it is 4.5e-5 bar^-1',
    'constraints': 'select which bonds to convert to constraints: none, h-bonds, all-bonds, h-angles, all-angles; '
                   "a topology's own [ constraints ] block is enforced whatever this says",
}

#: The three AA dynamics stages each carry their own copy of the same MDP options, and the form asks for help by the
#: setting name its input carries: one sentence per option, keyed by each stage's setting name. NVT has no barostat,
#: because it fixes the box, so it carries the thermostat's keys only.
for _stage in ('nvt', 'npt', 'production'):
    _aliases = {'dt_fs': 'dt', 'nstlist': 'nstlist', 'verlet_buffer_tolerance': 'verlet_buffer_tolerance',
                'tcoupl': 'tcoupl', 'tau_t': 'tau_t'}
    if _stage != 'nvt':
        _aliases.update({'pcoupl': 'pcoupl', 'pcoupltype': 'pcoupltype', 'tau_p': 'tau_p',
                         'compressibility': 'compressibility'})
    MDP_HELP.update({f'aa_{_stage}_{name}': MDP_HELP[source] for name, source in _aliases.items()})

#: The CG stages each carry their own copy of the same MDP options, keyed by the setting name their input posts.
#: Production's own overrides already use the generic names above; the other two legs prefix theirs, so the form
#: asks for help by those exact names. Their timesteps and the minimisation's cap are stated here rather than through
#: the AA `dt`/`nsteps` sentence, because the CG legs have no hydrogen repartitioning and a minimisation has no
#: duration to convert.
_CG_STAGE_HELP = {
    'cg_minimization_nstlist': 'nstlist',
    'cg_minimization_verlet_buffer_tolerance': 'verlet_buffer_tolerance',
    'cg_equil_nstlist': 'nstlist',
    'cg_equil_verlet_buffer_tolerance': 'verlet_buffer_tolerance',
    'cg_equil_tau_t': 'tau_t',
    'cg_equil_tau_p': 'tau_p',
    'cg_equil_compressibility': 'compressibility',
}
MDP_HELP.update({name: MDP_HELP[source] for name, source in _CG_STAGE_HELP.items()})
MDP_HELP.update({
    'cg_minimization_steps': 'the minimisation step cap: a minimisation has no duration to convert, so GROMACS takes '
                             'at most this many steps',
    'cg_equil_dt_fs': 'the time step; the manual states dt (0.001) [ps]. The form names it in femtoseconds and the run '
                      'writes fs/1000: 5 fs is the reviewed equilibration step (production is 20 fs)',
    'cg_production_dt_fs': 'the time step; the manual states dt (0.001) [ps]. The form names it in femtoseconds and the '
                           'run writes fs/1000: 20 fs is the reviewed production step (equilibration is 5 fs)',
})

#: Execution-flag meanings, quoted from `gmx mdrun -h` on the installed build.
MDRUN_HELP = {
    'mdrun_ntomp': 'Number of OpenMP threads per MPI rank to start (0 is guess)',
    'mdrun_ranks': 'The MPI ranks are separate processes under mpirun, so this is the rank count; '
                   '`-ntmpi` is a thread-MPI option and this build was compiled without thread-MPI',
    'mdrun_gpu': 'List of unique GPU device IDs available to use; the index is the CUDA ordinal',
    'mdrun_nb': 'Calculate non-bonded interactions on: auto, cpu, gpu. The energy-minimisation stage always uses '
                'auto and emits no flag for it.',
    'mdrun_pme': 'Perform PME calculations on: auto, cpu, gpu. The energy-minimisation stage always uses auto and '
                 'emits no flag for it.',
    'mdrun_pmefft': 'Perform PME FFT calculations on: auto, cpu, gpu. The energy-minimisation stage always uses '
                    'auto and emits no flag for it.',
    'mdrun_update': 'Perform update and constraints on: auto, cpu, gpu. The energy-minimisation stage always uses '
                    'auto and emits no flag for it.',
    'mdrun_tunepme': 'Optimize PME load between PP/PME ranks or GPU/CPU; GROMACS defaults to on, so auto emits '
                     'no flag. The energy-minimisation stage always uses auto.',
    'mdrun_cpt': 'Checkpoint interval (minutes). The energy-minimisation stage writes no checkpoint flag.',
}

#: Settings GROMACS has no entry for: the seed the dashboard writes into the CG MDPs, and the unit cell the
#: single-solute protocol builds.
PROJECT_HELP = {
    'cg_seed': 'The seed written into the CG MDPs as gen-seed and ld-seed (dashboard text, not GROMACS): the same '
               'number for the velocity draw and the stochastic term, so a run can be repeated.',
    'vsite': 'Builds the atomistic topology with gmx pdb2gmx -vsite (dashboard text, not GROMACS): an RTP residue '
             'and force-field overlay are assembled from the molecule ITP and the parameters MkVsites derives, and '
             'the generated topology is checked with grompp before the run starts. None consumes the stored ITP '
             'unchanged. Aromatics is the GROMACS-deprecated choice and only the constructs present in the derived '
             '.vsd file are converted.',
    'box_shape': 'The unit cell the single-solute protocol builds (dashboard text, not GROMACS). Every shape is sized '
                 'by the same minimum image distance d, so all four have |a|=|b|=|c|=d: the cube is d^3, both rhombic '
                 'dodecahedra (xy-square and xy-hexagon) are 0.707 d^3, and the truncated octahedron is 0.770 d^3 -- '
                 'the same image distance with less solvent. GROMACS editconf makes them with -box d, or with '
                 '-bt triclinic -box d d d -angles 60 60 60 for the xy-hexagon cell.',
}

#: What the form renders: one map keyed by setting name, whichever source a sentence came from.
HELP = {**MDP_HELP, **MDRUN_HELP, **PROJECT_HELP}

#: Where each family of sentences comes from, so the panel can attribute the text it shows.
SOURCES = {'mdp': MDP_MANUAL_URL, 'mdrun': MDRUN_SOURCE, 'project': PROJECT_SOURCE}

__all__ = ['HELP', 'MDP_HELP', 'MDRUN_HELP', 'PROJECT_HELP', 'SOURCES', 'MDP_MANUAL_URL', 'MDRUN_SOURCE']
