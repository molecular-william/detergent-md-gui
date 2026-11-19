"""The protein-detergent New run form's help text, keyed by the control names it posts.

The MDP and mdrun sentences are the engine's own (`dashboard.execution.settings_help`), reused rather than retyped:
they are quoted from the GROMACS manual and the installed `gmx mdrun -h`, so they are environment facts and there is
one copy of each. A pdc leg posts its own prefixed name for the same option, so an alias is a lookup in that table.
The sentences the dashboard owns -- the seed, the box margin, the initial z, the contact and removal rules, salt --
say so in their text, exactly as the engine's `PROJECT_HELP` does.
"""
from dashboard.execution.settings_help import HELP as CORE_HELP
from dashboard.execution.settings_help import MDP_HELP
from dashboard.execution.settings_help import SOURCES as CORE_SOURCES

#: Where each family of sentences comes from, so the panel attributes the text it shows. The project family is the
#: dashboard's own text, and each project sentence below says so rather than leaving the reader to guess.
SOURCES = dict(CORE_SOURCES)

# pdc-specific MDP sentences: option meanings the engine's table does not carry, in its voice and quoting the same
# manual page. Named here rather than inlined so the aliased legs cannot drift apart.
_NSTEPS = ('the minimisation step cap (the manual states nsteps: maximum number of steps to integrate or minimise): '
           'a minimisation has no duration to convert, so GROMACS takes at most this many steps; 0 asks for no '
           'minimisation, and the stage is skipped (dashboard text, not GROMACS)')
_EMTOL = ('the force tolerance steepest descents converges against (the manual states emtol: the minimisation is '
          'converged when the maximum force is smaller than this value), in kJ mol^-1 nm^-1')
_EMSTEP = ('the initial step size for steepest descents (the manual states emstep: the initial step size for '
           'steepest-descent minimisation), in nm')
_REF_T = ('the reference temperature the thermostat couples to (the manual states ref-t: reference temperature for '
          'coupling), in K')
_REF_P = ('the reference pressure the barostat couples to (the manual states ref-p: reference pressure for coupling), '
          'in bar')
_DT_NVT = ('the time step; the manual states dt (0.001) [ps]. The form names it in femtoseconds and the run writes '
           "fs/1000; blank keeps the reviewed profile's own 5 fs equilibration step")
_DT_NPT = ('the time step; the manual states dt (0.001) [ps]. The form names it in femtoseconds and the run writes '
           "fs/1000; blank keeps the reviewed profile's own 5 fs equilibration step")
_DT_ASSESSMENT = ('the time step; the manual states dt (0.001) [ps]. The form names it in femtoseconds and the run '
                  "writes fs/1000; blank keeps the reviewed profile's own 20 fs production step")
_DT_EXTENSION = ('the time step; the manual states dt (0.001) [ps]. The form names it in femtoseconds and the run '
                 "writes fs/1000; blank keeps the reviewed profile's own 20 fs production step")

# The project's own rules: the protocol's decisions, not GROMACS options, so each sentence carries the attribution.
_POSRES = ('holds the protein backbone with the POSRES block martinize2 wrote (dashboard text, not GROMACS): the '
           'define is per mdp, so each leg states its own. The minimisation and NPT legs hold it by default and NVT '
           "does not -- the reference bilayer protocol's window -- while the assessment and extension legs are "
           'always released, because they are the sampling that is judged and back-mapped')
_NVT_PS = ('the NVT equilibration duration (dashboard text, not GROMACS): the run converts it to nsteps at this '
           "leg's timestep and holds the box fixed; 0 asks for no NVT leg, and the stage is skipped")
_NPT_PS = ('the NPT equilibration duration (dashboard text, not GROMACS): the run converts it to nsteps at this '
           "leg's timestep and holds the pressure at the target; 0 asks for no NPT leg, and the stage is skipped")
_ASSESSMENT_NS = ('the CG assessment duration (dashboard text, not GROMACS): the production leg whose end state the '
                  'micelle assessment judges. With out-of-micelle removal off, this and the extension are one plain '
                  'CG MD leg')
_EXTENSION_NS = ('the CG extension duration (dashboard text, not GROMACS): the leg that continues the assessment '
                 'after the out-of-micelle detergents are removed. A run with removal off has no extension stage')
_SALT = ('the salt concentration the system is solvated at (dashboard text, not GROMACS): the build adds NA and CL '
         'ions to this molarity and neutralises the net charge; 0 is no added salt')
_SEED = ('the seed the run draws from (dashboard text, not GROMACS): the placement is deterministic in it, and the '
         'NVT leg writes it as gen-seed, so the same number repeats a run')
_BOX_MARGIN = ('the clearance between a box face and the system (dashboard text, not GROMACS): x and y are the '
               "protein's own footprint plus this margin on each side, and a membrane-stating protein's z is "
               'centred on its membrane with at least this margin to the furthest atom or the slab')
_INITIAL_Z = ('the z extent of the box a protein with no stated membrane is inserted into (dashboard text, not '
              'GROMACS): x and y come from the protein footprint, while z is this stated number. Auto measures the '
              "selected protein and sets z to its z extent plus twice the box margin; a membrane-stating protein's "
              'box is already centred on its membrane and clears it by the margin')
_CONTACT = ("the distance within which two detergents' tail beads count as touching (dashboard text, not GROMACS): "
            "the contact graph's largest connected cluster is the micelle, and a detergent in a smaller cluster is "
            'outside it')
_THRESHOLD = ('the fraction of detergents removed from outside the micelle above which the extension records the '
              'removal as above threshold (dashboard text, not GROMACS): it records how much the removal took, not '
              'the criterion -- that is the largest tail-bead contact cluster')
_VSITE = ("the back-map's pdb2gmx -vsite choice (dashboard text, not GROMACS): the wrapper adds the flag to every "
          'pdb2gmx call CG2AT2 makes. None passes nothing, Hydrogens adds -vsite hydrogens, and Aromatics adds '
          '-vsite aromatics (the GROMACS-deprecated choice, and only the constructs present in the derived .vsd '
          'file are converted)')

#: One sentence per control in the New run form's Stage settings fieldset, keyed by the name it posts. The engine's
#: own key is reused where the form posts the same name; a pdc leg's prefixed name looks its option up in the engine's
#: table, so an option explained there is not explained twice.
HELP = {
    # The three equilibration legs and the production pair, each posting its own prefixed name for an MDP option.
    'pdc_minimisation_steps': _NSTEPS,
    'pdc_minimisation_emtol': _EMTOL,
    'pdc_minimisation_emstep': _EMSTEP,
    'pdc_posres_min': _POSRES,
    'pdc_nvt_ps': _NVT_PS,
    'pdc_nvt_dt_fs': _DT_NVT,
    'pdc_nvt_nstlist': MDP_HELP['nstlist'],
    'pdc_nvt_ref_t': _REF_T,
    'pdc_nvt_tau_t': MDP_HELP['tau_t'],
    'pdc_posres_nvt': _POSRES,
    'pdc_npt_ps': _NPT_PS,
    'pdc_npt_dt_fs': _DT_NPT,
    'pdc_npt_nstlist': MDP_HELP['nstlist'],
    'pdc_npt_ref_t': _REF_T,
    'pdc_npt_tau_t': MDP_HELP['tau_t'],
    'pdc_npt_pcoupl': MDP_HELP['pcoupl'],
    'pdc_npt_pcoupltype': MDP_HELP['pcoupltype'],
    'pdc_npt_ref_p': _REF_P,
    'pdc_npt_tau_p': MDP_HELP['tau_p'],
    'pdc_npt_compressibility': MDP_HELP['compressibility'],
    'pdc_posres_npt': _POSRES,
    'pdc_assessment_ns': _ASSESSMENT_NS,
    'pdc_assessment_dt_fs': _DT_ASSESSMENT,
    'pdc_extension_ns': _EXTENSION_NS,
    'pdc_extension_dt_fs': _DT_EXTENSION,
    'pdc_production_nstlist': MDP_HELP['nstlist'],
    'pdc_production_ref_t': _REF_T,
    'pdc_production_tau_t': MDP_HELP['tau_t'],
    'pdc_production_tau_p': MDP_HELP['tau_p'],
    'pdc_production_ref_p': _REF_P,
    'pdc_production_compressibility': MDP_HELP['compressibility'],
    # Output cadence and cut-offs: the same options the engine's table explains, posted under the same names.
    'nstlog': CORE_HELP['nstlog'],
    'nstenergy': CORE_HELP['nstenergy'],
    'nstxtcout': CORE_HELP['nstxtcout'],
    'xtc_precision': CORE_HELP['xtc_precision'],
    'nstcomm': CORE_HELP['nstcomm'],
    'verlet_buffer_tolerance': CORE_HELP['verlet_buffer_tolerance'],
    'rlist': CORE_HELP['rlist'],
    'rcoulomb': CORE_HELP['rcoulomb'],
    'rvdw': CORE_HELP['rvdw'],
    # The dashboard's own rules, and the choices the back-map and the scheduler carry.
    'salt_molar': _SALT,
    'pdc_seed': _SEED,
    'box_margin_nm': _BOX_MARGIN,
    'initial_z_nm': _INITIAL_Z,
    'contact_nm': _CONTACT,
    'selection_threshold_fraction': _THRESHOLD,
    'protein_vsite': _VSITE,
    'mdrun_gpu': CORE_HELP['mdrun_gpu'],
    'mdrun_ntomp': CORE_HELP['mdrun_ntomp'],
    'mdrun_ranks': CORE_HELP['mdrun_ranks'],
    'mdrun_cpt': CORE_HELP['mdrun_cpt'],
    'mdrun_nb': CORE_HELP['mdrun_nb'],
    'mdrun_update': CORE_HELP['mdrun_update'],
}

__all__ = ['HELP', 'SOURCES']
