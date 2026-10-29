"""The reviewed physics of every MDP this project writes, one named profile per stage.

Each profile is the whole file: the settings a stage would otherwise inherit by copying a template and patching it in
place. The physics is here rather than in a per-run JSON document because it does not vary with the run -- the
integrator, the thermostat, the couplings, the cut-offs, the timestep and the constraints are decisions, and a run
records only which reviewed profile it used (the `version`, e.g. `cg-equilibration-v1`) beside the numbers it chose.

Sources, in the order a reader needs them:

* AA (`aa-*`): `dashboard/execution/adapters/aa.py:mdp()` is the ruleset this table reproduces; the force-field block is
  the registry entry's own (`dashboard.execution.forcefields`), read at render time and not copied here.
* CG (`cg-*`): `resources/templates/small_mols_fast_forward/` -- `3_initial_CG/initial.mdp` and
  `4_CG_sim/inputs/{minimization,eq,md}.mdp` -- as `cg.prepare` patches them and `cg.mdp_integration` states the
  timestep, the output strides and the seed.
* PDC (`pdc-*`): `resources/templates/protein_detergent/{minimisation,nvt,npt}.mdp` for the three legs, the pdc
  legs' genion fix-up tpr, and the CG production template plus `cg.mdp_integration` for the assessment and
  extension legs. The two `pdc-restart-*` profiles are the raw CG templates; `prepare` writes them from here when
  the run asks for the removal path, for the system it rebuilds.
* Osmotic (`osmotic-*`): `detergent_validation/execution/adapters/osmotic_mdp.py:osmotic_mdps` -- the CG templates with the
  paper's z-only coupling and the PLUMED flat-bottomed confinement.

Changing a value here is changing physics for every future run, and is exactly what the parity gate in
`tests/dashboard/unit/test_mdp_writer.py` is written to make visible: every profile must render the key/value map the
current code produces.
"""
from .writer import Profile

# --------------------------------------------------------------------------------------------------------------------
# AA-only stages.
# --------------------------------------------------------------------------------------------------------------------

# The protocol's own knobs, common to every AA stage (`aa.mdp`'s `common` before the force-field block).
_AA_PROTOCOL = {
    'nstlist': 20,
    'pbc': 'xyz',
    'constraint-algorithm': 'lincs',
    'verlet-buffer-tolerance': -1,
}

_AA_SOURCE = ('dashboard/execution/adapters/aa.py:mdp() -- the versioned single-solute protocol; the force-field block '
              'is dashboard.execution.forcefields.entry() at render time')

# The protocol's own knobs and the shared minimisation/dynamics vocabulary, in value-neutral words so one comment can
# sit beside whichever value a profile sets (`integrator = steep` and `integrator = md` are not the same statement).
_AA_PROTOCOL_COMMENTS = {
    'nstlist': 'with the Verlet scheme nstlist is a performance knob, not an accuracy one (GROMACS manual)',
    'pbc': 'periodic boundaries in x, y and z',
    'constraint-algorithm': 'LINCS, the constraint solver the force field prescribes',
    'verlet-buffer-tolerance': '-1 disables the automatic buffer: a 2.5 nm box with 1.2 nm cut-offs has no room for one',
}
_AA_MINIMISATION_COMMENTS = {
    'integrator': 'steep: steepest-descent minimisation',
    'nsteps': 'the minimisation cap',
    'emtol': 'stop when the maximum force falls below this (kJ/mol/nm)',
    'emstep': 'initial steepest-descent step (nm)',
}
_AA_DYNAMICS_COMMENTS = {
    'dt': '2 fs: the atomistic timestep of this protocol (the AA half integrates at 2 fs by standing decision)',
    'nstxout-compressed': "one compressed frame per `output_interval_ps`, converted at this file's dt",
    'nstenergy': 'energies every min(interval steps, 500)',
    'nstlog': 'the log every min(interval steps, 500)',
    'tc-grps': 'one coupling group, the whole system',
    'tau-t': 'coupling time (ps)',
    'ref-t': "the run's temperature (K)",
    'gen-temp': "the run's temperature (K), the velocity draw's target",
    'gen-seed': "the run's seed for the velocity draw",
    'ld-seed': "the run's seed for the stochastic term, the same number as gen-seed",
}
_AA_NVT_COMMENTS = {
    **_AA_PROTOCOL_COMMENTS, **_AA_DYNAMICS_COMMENTS,
    'nsteps': "the run's NVT duration in steps at 2 fs",
    'continuation': 'this leg starts the dynamics',
    'gen-vel': 'the first dynamics leg is where velocities are drawn',
    'pcoupl': 'this leg is NVT',
}
_AA_NPT_COMMENTS = {
    **_AA_PROTOCOL_COMMENTS, **_AA_DYNAMICS_COMMENTS,
    'nsteps': "the run's NPT duration in steps at 2 fs",
    'continuation': 'continues the NVT velocities',
    'gen-vel': 'the NVT leg already drew them',
    'pcoupl': 'C-rescale: the equilibration barostat',
    'pcoupltype': 'isotropic pressure coupling',
    'tau-p': '5 ps pressure-coupling time constant',
    'ref-p': "the run's pressure (bar)",
    'compressibility': "4.5e-5: the papers' water compressibility (1/bar)",
}
_AA_PRODUCTION_COMMENTS = {
    **_AA_PROTOCOL_COMMENTS, **_AA_DYNAMICS_COMMENTS,
    'nsteps': "the run's production duration in steps at 2 fs",
    'continuation': 'continues the NPT state',
    'gen-vel': 'the velocities come from the equilibration legs',
    'pcoupl': 'Parrinello-Rahman: the production barostat',
    'pcoupltype': 'isotropic pressure coupling',
    'tau-p': '5 ps pressure-coupling time constant',
    'ref-p': "the run's pressure (bar)",
    'compressibility': "4.5e-5: the papers' water compressibility (1/bar)",
}

AA_PROFILES = (
    Profile(settings={**_AA_PROTOCOL, 'integrator': 'steep', 'nsteps': 0, 'emtol': 1000, 'emstep': 0.01,
                      'coulombtype': 'Cut-off'},
            comments={**_AA_PROTOCOL_COMMENTS, **_AA_MINIMISATION_COMMENTS,
                      'nsteps': 'this mdp exists only to make a tpr for genion',
                      'coulombtype': "Cut-off: the ions fix-up only; it replaces the force field's PME"},
            source=_AA_SOURCE, version='aa-ions-v1', force_field=True),
    Profile(settings={**_AA_PROTOCOL, 'integrator': 'steep', 'nsteps': 20000, 'emtol': 1000, 'emstep': 0.01},
            comments={**_AA_PROTOCOL_COMMENTS, **_AA_MINIMISATION_COMMENTS,
                      'nsteps': 'the minimisation cap (20000 steps)'},
            source=_AA_SOURCE, version='aa-em-v1', force_field=True),
    Profile(settings={**_AA_PROTOCOL, 'integrator': 'md', 'dt': 0.002, 'nsteps': None, 'continuation': 'no',
                      'tcoupl': 'V-rescale', 'tc-grps': 'System', 'tau-t': 1, 'ref-t': None, 'gen-vel': 'yes',
                      'gen-temp': None, 'gen-seed': None, 'ld-seed': None, 'pcoupl': 'no',
                      'nstxout-compressed': None, 'nstenergy': None, 'nstlog': None},
            comments=_AA_NVT_COMMENTS,
            source=_AA_SOURCE, version='aa-nvt-v1', force_field=True),
    Profile(settings={**_AA_PROTOCOL, 'integrator': 'md', 'dt': 0.002, 'nsteps': None, 'continuation': 'yes',
                      'tcoupl': 'V-rescale', 'tc-grps': 'System', 'tau-t': 1, 'ref-t': None, 'gen-vel': 'no',
                      'gen-temp': None, 'gen-seed': None, 'ld-seed': None, 'pcoupl': 'C-rescale',
                      'nstxout-compressed': None, 'nstenergy': None, 'nstlog': None, 'pcoupltype': 'isotropic',
                      'tau-p': 5, 'ref-p': None, 'compressibility': '4.5e-5'},
            comments=_AA_NPT_COMMENTS,
            source=_AA_SOURCE, version='aa-npt-v1', force_field=True),
    Profile(settings={**_AA_PROTOCOL, 'integrator': 'md', 'dt': 0.002, 'nsteps': None, 'continuation': 'yes',
                      'tcoupl': 'V-rescale', 'tc-grps': 'System', 'tau-t': 1, 'ref-t': None, 'gen-vel': 'no',
                      'gen-temp': None, 'gen-seed': None, 'ld-seed': None, 'pcoupl': 'Parrinello-Rahman',
                      'nstxout-compressed': None, 'nstenergy': None, 'nstlog': None, 'pcoupltype': 'isotropic',
                      'tau-p': 5, 'ref-p': None, 'compressibility': '4.5e-5'},
            comments=_AA_PRODUCTION_COMMENTS,
            source=_AA_SOURCE, version='aa-production-v1', force_field=True),
)

# --------------------------------------------------------------------------------------------------------------------
# CG half of an AA-to-CG run.
# --------------------------------------------------------------------------------------------------------------------

# The Martini 3 conventions the coarse-grained files share -- the physics every one of them states in the same words.
_MARTINI_COMMENTS = {
    'nstcomm': 'remove the centre-of-mass motion every 100 steps',
    'comm-grps': 'for the whole system',
    'comm-mode': 'linear: a uniform drift is removed, not a shape',
    'nstxout': 'no full-precision coordinates written',
    'nstvout': 'no velocities written',
    'nstfout': 'no forces written',
    'nstlist': '40 steps: one list rebuild per 0.8 ps at the CG production step',
    'pbc': 'periodic in all three directions',
    'verlet-buffer-tolerance': '0.005: GROMACS sizes rlist from this tolerance for this system',
    'coulombtype': 'Martini 3 electrostatics',
    'rcoulomb': 'electrostatic cut-off (nm)',
    'epsilon-r': 'water dielectric for the reaction field',
    'epsilon-rf': 'reaction field at infinity',
    'vdw-modifier': 'Martini 3 shifts the potential to zero at the cut-off',
    'rvdw': 'van der Waals cut-off (nm)',
    'tc-grps': 'one coupling group, the whole system',
    'tau-t': 'coupling time (ps)',
    'constraints': 'coarse-grained beads carry no distance constraints',
    'constraint-algorithm': 'LINCS, named as the templates name it, with nothing to solve',
    'lincs-iter': 'the template value; inert with constraints = none',
    'lincs-order': 'the template value; inert with constraints = none',
    'lincs-warnangle': "the template value; inert with constraints = none",
}

#: The coarse-grained dynamics neighbour list: the Martini 3 paper's Verlet list with its cadence doubled and the
#: tolerance it states kept. `nstlist = 40` was measured on a 100 ns DDM micelle against the 20-step profile: 8% faster
#: per step at the same tolerance, with the thermostat, barostat and volume statistics within their own error bars.
#: `rlist` is deliberately absent from these files: GROMACS sizes it from the tolerance for the system at hand (1.554
#: nm for that micelle; the old pinned 1.35 nm was the 20-step value, and a wrong value for a 40-step list).
_DYNAMICS_NEIGHBOUR_COMMENTS = {
    'nstlist': '40 steps: one list rebuild per 0.8 ps at the CG production step',
    'verlet-buffer-tolerance': '0.005: GROMACS sizes rlist from this tolerance for this system',
}

_CG_TOPOLOGY_COMMENTS = {
    'integrator': 'steep: steepest-descent minimisation',
    'nsteps': 'the step cap',
    'nstxout': 'no full-precision coordinates written',
    'nstfout': 'no forces written',
    'nstlog': 'the log every 100 steps',
    'nstlist': 'not an accuracy knob with the Verlet scheme',
    'pbc': 'periodic in all three directions',
    'verlet-buffer-tolerance': "this template keeps GROMACS' automatic buffer",
    'coulombtype': 'Martini 3 electrostatics',
    'rcoulomb': 'electrostatic cut-off (nm)',
    'epsilon-r': 'water dielectric for the reaction field',
    'epsilon-rf': 'reaction field at infinity',
    'vdw-modifier': 'Martini 3 shifts the potential to zero at the cut-off',
    'rvdw': 'van der Waals cut-off (nm)',
}

_CG_EQUILIBRATION_COMMENTS = {
    **_MARTINI_COMMENTS,
    'dt': '5 fs: the standing coarse-grained EQUILIBRATION timestep (production is 20 fs)',
    'nsteps': "the run's duration in steps, at this file's dt",
    'nstlog': 'cg.mdp_integration: the log every 100 steps',
    'nstenergy': 'cg.mdp_integration: energies every 100 steps',
    'nstxtcout': "the run's output interval in steps (`output_interval_ps`), at this file's dt",
    'xtc-precision': 'cg.mdp_integration: coarse-grained beads need the extra precision',
    'xtc-grps': 'unset: every group is written',
    'ref-t': "the run's temperature (K)",
    'pcoupl': 'the equilibration barostat both Martini 3 papers describe',
    'pcoupltype': 'isotropic pressure coupling',
    'tau-p': 'the equilibration time constant the template states',
    'compressibility': "4.5e-5: the papers' water compressibility, not GROMACS' 3e-4 default for an unknown system",
    'ref-p': 'the pressure-coupling target',
    'gen-vel': 'this leg draws its own velocities',
    'gen-temp': "the run's temperature (K), the velocity draw's target",
    'gen-seed': "the run's CG seed",
    'ld-seed': "the run's CG seed, for the stochastic term",
    'continuation': 'this leg starts from the minimised system',
}

_CG_PRODUCTION_COMMENTS = {
    **_CG_EQUILIBRATION_COMMENTS,
    'dt': '20 fs: the coarse-grained PRODUCTION timestep (equilibration is 5 fs)',
    'pcoupl': 'the production barostat at 1 bar (the Martini 3 protocol)',
    'tau-p': '12 ps: the production time constant the template states',
    'gen-vel': 'production continues the equilibrated velocities',
    'continuation': 'this leg continues the equilibrated state',
}

_CG_TEMPLATE = 'resources/templates/small_mols_fast_forward'
_CG_PREPARE_SOURCE = (f'{_CG_TEMPLATE}/4_CG_sim/inputs/{{eq,md}}.mdp as cg.mdp_integration and cg.prepare patch it: '
                      'the timestep, the output strides and the seed')

CG_PROFILES = (
    Profile(settings={'integrator': 'steep', 'nsteps': 0, 'nstxout': 0, 'nstfout': 0, 'nstlog': 100,
                      'cutoff-scheme': 'Verlet', 'nstlist': 20, 'ns-type': 'grid', 'pbc': 'xyz',
                      'verlet-buffer-tolerance': 0.005, 'coulombtype': 'reaction-field', 'rcoulomb': 1.1,
                      'epsilon-r': 15, 'epsilon-rf': 0, 'vdw-type': 'cutoff',
                      'vdw-modifier': 'Potential-shift-verlet', 'rvdw': 1.1},
            comments={**_CG_TOPOLOGY_COMMENTS, 'nsteps': 'this mdp writes the draft topology, not a trajectory'},
            source=f'{_CG_TEMPLATE}/3_initial_CG/initial.mdp as cg.prepare patches it (nsteps = 0)',
            version='cg-initial-v1'),
    Profile(settings={'integrator': 'steep', 'nsteps': 20000, 'nstxout': 0, 'nstfout': 0, 'nstlog': 100,
                      'cutoff-scheme': 'Verlet', 'nstlist': 20, 'ns-type': 'grid', 'pbc': 'xyz',
                      'verlet-buffer-tolerance': 0.005, 'coulombtype': 'reaction-field', 'rcoulomb': 1.1,
                      'epsilon-r': 15, 'epsilon-rf': 0, 'vdw-type': 'cutoff',
                      'vdw-modifier': 'Potential-shift-verlet', 'rvdw': 1.1, 'define': ''},
            comments={**_CG_TOPOLOGY_COMMENTS, 'nsteps': 'cg.prepare stamps 20000 steps',
                      'define': "empty: cg.prepare clears the template's -DFLEXIBLE"},
            source=f'{_CG_TEMPLATE}/4_CG_sim/inputs/minimization.mdp as cg.prepare patches it (nsteps, define)',
            version='cg-minimization-v1'),
    Profile(settings={'title': 'Martini', 'integrator': 'md', 'dt': 0.005, 'nsteps': None, 'nstcomm': 100,
                      'comm-grps': 'System', 'comm-mode': 'Linear', 'nstxout': 0, 'nstvout': 0, 'nstfout': 0,
                      'nstlog': 100, 'nstenergy': 100, 'nstxtcout': None, 'xtc-precision': 1000, 'xtc-grps': '',
                      'cutoff-scheme': 'Verlet', 'nstlist': 40, 'ns-type': 'grid', 'pbc': 'xyz',
                      'verlet-buffer-tolerance': 0.005, 'coulombtype': 'reaction-field',
                      'rcoulomb': 1.1, 'epsilon-r': 15, 'epsilon-rf': 0, 'vdw-type': 'cutoff',
                      'vdw-modifier': 'Potential-shift-verlet', 'rvdw': 1.1, 'tcoupl': 'v-rescale',
                      'tc-grps': 'System', 'tau-t': 1.0, 'ref-t': None, 'pcoupl': 'c-rescale',
                      'pcoupltype': 'isotropic', 'tau-p': 4.0, 'compressibility': 4.5e-5, 'ref-p': 1.0,
                      'gen-vel': 'yes', 'gen-temp': None, 'gen-seed': None, 'continuation': 'no',
                      'constraints': 'none', 'constraint-algorithm': 'Lincs', 'lincs-iter': 1, 'lincs-order': 4,
                      'lincs-warnangle': 30, 'ld-seed': None},
            comments=_CG_EQUILIBRATION_COMMENTS,
            source=_CG_PREPARE_SOURCE, version='cg-equilibration-v1'),
    Profile(settings={'title': 'Martini', 'integrator': 'md', 'dt': 0.02, 'nsteps': None, 'nstcomm': 100,
                      'comm-grps': 'System', 'comm-mode': 'Linear', 'nstxout': 0, 'nstvout': 0, 'nstfout': 0,
                      'nstlog': 100, 'nstenergy': 100, 'nstxtcout': None, 'xtc-precision': 1000, 'xtc-grps': '',
                      'cutoff-scheme': 'Verlet', 'nstlist': 40, 'ns-type': 'grid', 'pbc': 'xyz',
                      'verlet-buffer-tolerance': 0.005, 'coulombtype': 'reaction-field',
                      'rcoulomb': 1.1, 'epsilon-r': 15, 'epsilon-rf': 0, 'vdw-type': 'cutoff',
                      'vdw-modifier': 'Potential-shift-verlet', 'rvdw': 1.1, 'tcoupl': 'v-rescale',
                      'tc-grps': 'System', 'tau-t': 1.0, 'ref-t': None, 'pcoupl': 'parrinello-rahman',
                      'pcoupltype': 'isotropic', 'tau-p': 12.0, 'compressibility': 4.5e-5, 'ref-p': 1.0,
                      'gen-vel': 'no', 'constraints': 'none', 'constraint-algorithm': 'Lincs',
                      'continuation': 'yes', 'lincs-order': 4, 'lincs-warnangle': 30, 'gen-seed': None,
                      'ld-seed': None, 'gen-temp': None},
            comments=_CG_PRODUCTION_COMMENTS,
            source=_CG_PREPARE_SOURCE, version='cg-production-v1'),
)

# --------------------------------------------------------------------------------------------------------------------
# PDC legs.
# --------------------------------------------------------------------------------------------------------------------

# The three equilibration legs' steps come from `resources/templates/protein_detergent/`; the run supplies the step
# count and, for the leg that draws velocities, the seed.
_PDC_TEMPLATE = 'resources/templates/protein_detergent'
_PDC_LEG_COMMENTS = {
    'nsteps': "the run's own step count, from the leg's duration at this file's dt",
    'nstlog': 'the log every 1000 steps',
    'nstlist': 'not an accuracy knob with the Verlet scheme',
    'pbc': 'periodic in all three directions',
    'verlet-buffer-tolerance': 'the automatic buffer is disabled, as in the CG templates',
    'rlist': 'neighbour-list cut-off (nm)',
    'coulombtype': "the CG half's electrostatics everywhere in this pipeline",
    'rcoulomb': 'electrostatic cut-off (nm)',
    'epsilon-r': 'water dielectric for the reaction field',
    'epsilon-rf': 'reaction field at infinity',
    'rvdw': 'van der Waals cut-off (nm)',
    'dt': '5 fs: the standing coarse-grained EQUILIBRATION timestep (production stays 20 fs)',
    'nstcomm': 'remove the centre-of-mass motion every 100 steps',
    'comm-grps': 'remove it for the whole system',
    'comm-mode': 'linear: a uniform drift is removed, not a shape',
    'nstxout': 'no full-precision coordinates written',
    'nstvout': 'no velocities written',
    'nstfout': 'no forces written',
    'nstenergy': 'energies every 100 steps',
    'nstxtcout': 'a compressed frame every 100 steps',
    'xtc-precision': "the templates' own precision",
    'tc-grps': 'one coupling group, the whole system',
    'tau-t': '1.0 ps coupling time',
    'ref-t': 'the coupling target the templates state',
    'pcoupltype': 'isotropic pressure coupling',
    'tau-p': "c-rescale's equilibration time constant",
    'ref-p': 'the pressure-coupling target',
    'compressibility': '4.5e-5, the papers\' water compressibility',
    'gen-temp': "the velocity draw's target",
    'gen-seed': "the run's seed, for the velocity draw",
    'constraints': 'coarse-grained beads carry no distance constraints',
    'constraint-algorithm': 'named by the templates, with nothing to solve',
    'lincs-warnangle': 'the angle above which LINCS warns (degrees)',
}

PDC_LEG_PROFILES = (
    Profile(settings={'integrator': 'steep', 'nsteps': None, 'nstlog': 100, 'cutoff-scheme': 'Verlet',
                      'nstlist': 20, 'ns-type': 'grid', 'pbc': 'xyz', 'verlet-buffer-tolerance': -1, 'rlist': 1.35,
                      'coulombtype': 'reaction-field', 'rcoulomb': 1.1, 'epsilon-r': 15, 'epsilon-rf': 0,
                      'vdw-type': 'cutoff', 'vdw-modifier': 'Potential-shift-verlet', 'rvdw': 1.1},
            comments={**_PDC_LEG_COMMENTS, 'integrator': 'steep: steepest-descent minimisation',
                      'nstlog': 'the log every 100 steps',
                      'nsteps': "the run's own step count (`pdc_minimisation_steps`)"},
            source=f'{_PDC_TEMPLATE}/minimisation.mdp', version='pdc-minimisation-v1'),
    Profile(settings={'integrator': 'md', 'dt': 0.005, 'nsteps': None, 'nstcomm': 100, 'comm-grps': 'System',
                      'comm-mode': 'Linear', 'nstxout': 0, 'nstvout': 0, 'nstfout': 0, 'nstlog': 1000,
                      'nstenergy': 100, 'nstxtcout': 100, 'xtc-precision': 100, 'cutoff-scheme': 'Verlet',
                      'nstlist': 40, 'ns-type': 'grid', 'pbc': 'xyz', 'verlet-buffer-tolerance': 0.005,
                      'coulombtype': 'reaction-field', 'rcoulomb': 1.1, 'epsilon-r': 15, 'epsilon-rf': 0,
                      'vdw-type': 'cutoff', 'vdw-modifier': 'Potential-shift-verlet', 'rvdw': 1.1, 'tcoupl': 'v-rescale',
                      'tc-grps': 'System', 'tau-t': 1.0, 'ref-t': 300, 'pcoupl': 'no', 'gen-vel': 'yes',
                      'gen-temp': 300, 'gen-seed': None, 'continuation': 'no', 'constraints': 'none',
                      'constraint-algorithm': 'lincs', 'lincs-iter': 1, 'lincs-order': 4, 'lincs-warnangle': 30},
            comments={**_PDC_LEG_COMMENTS, **_DYNAMICS_NEIGHBOUR_COMMENTS,
                      'gen-vel': 'this is where the velocities are drawn',
                      'pcoupl': 'this leg is NVT', 'continuation': 'this leg starts from the minimised system'},
            source=f'{_PDC_TEMPLATE}/nvt.mdp, with the run\'s seed for gen-seed', version='pdc-nvt-v1'),
    Profile(settings={'integrator': 'md', 'dt': 0.005, 'nsteps': None, 'nstcomm': 100, 'comm-grps': 'System',
                      'comm-mode': 'Linear', 'nstxout': 0, 'nstvout': 0, 'nstfout': 0, 'nstlog': 1000,
                      'nstenergy': 100, 'nstxtcout': 100, 'xtc-precision': 100, 'cutoff-scheme': 'Verlet',
                      'nstlist': 40, 'ns-type': 'grid', 'pbc': 'xyz', 'verlet-buffer-tolerance': 0.005,
                      'coulombtype': 'reaction-field', 'rcoulomb': 1.1, 'epsilon-r': 15, 'epsilon-rf': 0,
                      'vdw-type': 'cutoff', 'vdw-modifier': 'Potential-shift-verlet', 'rvdw': 1.1, 'tcoupl': 'v-rescale',
                      'tc-grps': 'System', 'tau-t': 1.0, 'ref-t': 300, 'pcoupl': 'c-rescale',
                      'pcoupltype': 'isotropic', 'tau-p': 4.0, 'ref-p': 1.0, 'compressibility': 4.5e-5,
                      'gen-vel': 'no', 'gen-temp': 300, 'continuation': 'yes', 'constraints': 'none',
                      'constraint-algorithm': 'lincs', 'lincs-iter': 1, 'lincs-order': 4, 'lincs-warnangle': 30},
            comments={**_PDC_LEG_COMMENTS, **_DYNAMICS_NEIGHBOUR_COMMENTS,
                      'gen-vel': 'the NVT leg drew them',
                      'gen-temp': "the template's value, inert with gen-vel = no",
                      'pcoupl': "c-rescale: the NPT leg's barostat",
                      'continuation': 'continues the NVT state'},
            source=f'{_PDC_TEMPLATE}/npt.mdp', version='pdc-npt-v1'),
)

# The genion fix-up tpr, written from this profile rather than copied from a template.
_IONS_COMMENTS = {
    'integrator': 'steep: no dynamics, only a tpr for genion to fit ions to',
    'nsteps': 'nothing moves',
    'rlist': 'arbitrary here, because nothing is integrated',
    'coulombtype': "the CG half's electrostatics, as in every CG file here",
    'epsilon-r': 'water dielectric, as everywhere else in the CG pipeline',
}

# The production leg: the CG production template with `cg.mdp_integration`'s patches.
_PDC_PRODUCTION_SETTINGS = {
    'title': 'Martini', 'integrator': 'md', 'dt': 0.02, 'nsteps': None, 'nstcomm': None, 'comm-grps': 'System',
    'comm-mode': 'Linear', 'nstxout': 0, 'nstvout': 0, 'nstfout': 0, 'nstlog': None, 'nstenergy': None,
    'nstxtcout': None, 'xtc-precision': None, 'xtc-grps': '', 'cutoff-scheme': 'Verlet', 'nstlist': None,
    'ns-type': 'grid', 'pbc': 'xyz', 'verlet-buffer-tolerance': None, 'coulombtype': 'reaction-field',
    'rcoulomb': None, 'epsilon-r': 15, 'epsilon-rf': 0, 'vdw-type': 'cutoff',
    'vdw-modifier': 'Potential-shift-verlet', 'rvdw': None, 'tcoupl': 'v-rescale', 'tc-grps': 'System',
    'tau-t': None, 'ref-t': None, 'pcoupl': 'parrinello-rahman', 'pcoupltype': 'isotropic', 'tau-p': None,
    'compressibility': None, 'ref-p': None, 'gen-vel': 'no', 'constraints': 'none',
    'constraint-algorithm': 'Lincs', 'continuation': 'yes', 'lincs-order': 4, 'lincs-warnangle': 30,
    'gen-seed': 20260911,
}

_PDC_PRODUCTION_COMMENTS = {
    **_MARTINI_COMMENTS,
    'dt': '20 fs: the coarse-grained PRODUCTION timestep (equilibration is 5 fs)',
    'nsteps': "the run's own duration in steps: assessment_ns (plus extension_ns when removal is off) at this dt",
    'nstcomm': "the run's own centre-of-mass removal interval",
    'nstlog': "the run's own log interval",
    'nstenergy': "the run's own energy interval",
    'nstxtcout': "the run's own compressed-trajectory stride",
    'xtc-precision': "the run's own trajectory precision",
    'nstlist': "the run's own neighbour-list rebuild interval",
    'verlet-buffer-tolerance': "the run's own Verlet buffer tolerance",
    'rcoulomb': "the run's own Coulomb cut-off",
    'rvdw': "the run's own van der Waals cut-off",
    'tau-t': "the run's own thermostat coupling time",
    'ref-t': "the run's own temperature",
    'tau-p': "the run's own barostat coupling time",
    'compressibility': "the run's own water compressibility",
    'ref-p': "the run's own pressure target",
    'xtc-grps': 'unset: every group is written',
    'pcoupl': 'parrinello-rahman at 1 bar: the production barostat',
    'pcoupltype': 'isotropic pressure coupling',
    'gen-vel': 'no: the extension continues the trajectory it was given',
    'gen-seed': "cg.mdp_integration's fixed seed: this stage does not take the run's seed",
    'continuation': 'yes: continues the assessment state',
}

PDC_PRODUCTION_PROFILES = (
    Profile(settings={'integrator': 'steep', 'nsteps': 0, 'cutoff-scheme': 'Verlet', 'rlist': 1.1,
                      'coulombtype': 'reaction-field', 'epsilon-r': 15},
            comments=_IONS_COMMENTS,
            source='the pdc legs\' genion fix-up (steep, no steps, reaction field), written by pdc.prepare',
            version='pdc-ions-v1'),
    Profile(settings=dict(_PDC_PRODUCTION_SETTINGS), comments=_PDC_PRODUCTION_COMMENTS,
            source=f'{_CG_TEMPLATE}/4_CG_sim/inputs/md.mdp as cg.mdp_integration patches it (the CG branch)',
            version='pdc-assessment-v1'),
    # The extension's file is the assessment's, continued: `pdc.prepare` writes it from this profile at the
    # assessment's step count, and gen-vel is already `no`. Registered separately because that is the name a run
    # records.
    Profile(settings=dict(_PDC_PRODUCTION_SETTINGS), comments=_PDC_PRODUCTION_COMMENTS,
            source='the pdc assessment profile, continued (gen-vel = no, continuation)',
            version='pdc-extension-v1'),
)

# The removal path rebuilds the system from kept coordinates, so `pdc.prepare` writes these two files from these
# profiles with the templates' own values: no step count, seed or temperature comes from the run.
_PDC_RESTART_COMMENTS = {
    **_CG_TOPOLOGY_COMMENTS,
    'nsteps': "the template's own 200000 steps, unpatched",
    'define': "-DFLEXIBLE: the CG template's own define, unpatched",
}
_PDC_RESTART_EQ_COMMENTS = {
    **_MARTINI_COMMENTS,
    'dt': "the template's own 5 fs equilibration step",
    'nsteps': "the template's own 1,000,000 steps, unpatched",
    'nstlog': "the template's own 10000",
    'nstenergy': "the template's own 100",
    'nstxtcout': "the template's own 100000",
    'xtc-precision': "the template's own 100",
    'xtc-grps': 'unset: every group is written',
    'ref-t': "the template's own 300 K, unpatched",
    'pcoupl': "c-rescale: the template's equilibration barostat",
    'pcoupltype': 'isotropic pressure coupling',
    'tau-p': "4 ps: the template's equilibration time constant",
    'compressibility': "4.5e-5: the papers' water compressibility",
    'ref-p': 'the pressure-coupling target',
    'gen-vel': 'yes: this file draws velocities, as the template does',
    'gen-temp': "the template's own 300 K",
    'gen-seed': "the template's own -1, unpatched",
    'continuation': 'no',
}

PDC_RESTART_PROFILES = (
    Profile(settings={'integrator': 'steep', 'nsteps': 200000, 'nstxout': 0, 'nstfout': 0, 'nstlog': 100,
                      'cutoff-scheme': 'Verlet', 'nstlist': 20, 'ns-type': 'grid', 'pbc': 'xyz',
                      'verlet-buffer-tolerance': 0.005, 'coulombtype': 'reaction-field', 'rcoulomb': 1.1,
                      'epsilon-r': 15, 'epsilon-rf': 0, 'vdw-type': 'cutoff',
                      'vdw-modifier': 'Potential-shift-verlet', 'rvdw': 1.1, 'define': '-DFLEXIBLE'},
            comments=_PDC_RESTART_COMMENTS, source=f'{_CG_TEMPLATE}/4_CG_sim/inputs/minimization.mdp (the template values)',
            version='pdc-restart-minimization-v1'),
    Profile(settings={'title': 'Martini', 'integrator': 'md', 'dt': 0.005, 'nsteps': 1000000, 'nstcomm': 100,
                      'comm-grps': 'System', 'comm-mode': 'Linear', 'nstxout': 0, 'nstvout': 0, 'nstfout': 0,
                      'nstlog': 10000, 'nstenergy': 100, 'nstxtcout': 100000, 'xtc-precision': 100, 'xtc-grps': '',
                      'cutoff-scheme': 'Verlet', 'nstlist': 40, 'ns-type': 'grid', 'pbc': 'xyz',
                      'verlet-buffer-tolerance': 0.005, 'coulombtype': 'reaction-field',
                      'rcoulomb': 1.1, 'epsilon-r': 15, 'epsilon-rf': 0, 'vdw-type': 'cutoff',
                      'vdw-modifier': 'Potential-shift-verlet', 'rvdw': 1.1, 'tcoupl': 'v-rescale',
                      'tc-grps': 'System', 'tau-t': 1.0, 'ref-t': 300, 'pcoupl': 'c-rescale',
                      'pcoupltype': 'isotropic', 'tau-p': 4.0, 'compressibility': 4.5e-5, 'ref-p': 1.0,
                      'gen-vel': 'yes', 'gen-temp': 300, 'gen-seed': -1, 'continuation': 'no',
                      'constraints': 'none', 'constraint-algorithm': 'Lincs', 'lincs-iter': 1, 'lincs-order': 4,
                      'lincs-warnangle': 30},
            comments=_PDC_RESTART_EQ_COMMENTS, source=f'{_CG_TEMPLATE}/4_CG_sim/inputs/eq.mdp (the template values)',
            version='pdc-restart-equilibration-v1'),
)

# --------------------------------------------------------------------------------------------------------------------
# Osmotic pressure series.
# --------------------------------------------------------------------------------------------------------------------

_OSMOTIC_SOURCE = ('detergent_validation/execution/adapters/osmotic_mdp.py:osmotic_mdps(), derived from '
                   f'{_CG_TEMPLATE}/4_CG_sim/inputs and the paper\'s method (z-only coupling, PLUMED confinement)')
_OSMOTIC_COMMENTS = {
    'nsteps': "the run's own duration in steps, at this file's dt",
    'emtol': 'the convergence target this series minimises to (kJ/mol/nm)',
    'emstep': 'initial steepest-descent step (nm)',
    'dt': '5 fs equilibrating (the paper\'s 10 ns) and 20 fs producing: the CG split every run here uses',
    'nstcomm': 'remove the centre-of-mass motion every 100 steps',
    'comm-grps': 'remove it for the whole system',
    'comm-mode': 'linear: a uniform drift is removed, not a shape',
    'nstxout': 'no full-precision coordinates written',
    'nstvout': 'no velocities written',
    'nstfout': 'no forces written',
    'nstenergy': "the run's output interval in steps: dense enough that the force average has frames",
    'nstxtcout': "the run's output interval in steps",
    'nstlist': 'with the Verlet scheme nstlist is a performance knob, not an accuracy one',
    'pbc': 'periodic in all three directions',
    'verlet-buffer-tolerance': 'the automatic buffer is disabled, as in the CG templates',
    'rlist': 'neighbour-list cut-off (nm)',
    'coulombtype': 'Martini 3 electrostatics',
    'rcoulomb': 'electrostatic cut-off (nm)',
    'epsilon-r': 'water dielectric for the reaction field',
    'epsilon-rf': 'reaction field at infinity',
    'rvdw': 'van der Waals cut-off (nm)',
    'tc-grps': 'one coupling group, the whole system',
    'tau-t': '1.0 ps coupling time',
    'ref-t': "the run's temperature (K), the experimental dataset's",
    'pcoupl': 'berendsen equilibrating and parrinello-rahman producing: the paper\'s barostats',
    'pcoupltype': 'semiisotropic: only z is coupled, which is the paper\'s method',
    'compressibility': '0 in xy: the box is not rescaled there; 4.5e-5 in z',
    'ref-p': '1.0 1.0 bar: xy and z, the CG templates\' target',
    'constraints': 'coarse-grained beads carry no distance constraints',
    'constraint-algorithm': 'named by the template, with nothing to solve',
    'lincs-warnangle': 'the angle above which LINCS warns (degrees)',
    'refcoord-scaling': 'the restrained reference bead follows the box, so the walls stay at the box centre',
    'gen-temp': "the run's temperature (K), the velocity draw's target",
    'gen-seed': '-1: GROMACS draws its own, as osmotic_mdps writes it',
}

_OSMOTIC_NOTES = ('the method: the solute is confined to the centre, and the walls sit at the quarter box',
                  'the confinement is PLUMED (plumed_walls writes plumed.dat): mdrun -plumed plumed.dat')

_OSMOTIC_MINIMIZATION_COMMENTS = {
    **_OSMOTIC_COMMENTS,
    'integrator': 'steep: steepest-descent minimisation, with the confinement already imposed',
    'nsteps': 'the minimisation cap osmotic_mdps writes',
}

OSMOTIC_PROFILES = (
    Profile(settings={'title': 'Martini, osmotic pressure series, minimization', 'integrator': 'steep',
                      'nsteps': 20000, 'emtol': 100.0, 'emstep': 0.01, 'cutoff-scheme': 'Verlet', 'nstlist': 20,
                      'pbc': 'xyz', 'verlet-buffer-tolerance': -1, 'rlist': 1.35, 'coulombtype': 'reaction-field',
                      'rcoulomb': 1.1, 'epsilon-r': 15, 'epsilon-rf': 0, 'vdw-type': 'cutoff',
                      'vdw-modifier': 'potential-shift-verlet', 'rvdw': 1.1, 'constraints': 'none',
                      'constraint-algorithm': 'Lincs', 'refcoord-scaling': 'all'},
            comments=_OSMOTIC_MINIMIZATION_COMMENTS, source=_OSMOTIC_SOURCE,
            version='osmotic-minimization-v1', notes=_OSMOTIC_NOTES),
    Profile(settings={'title': 'Martini, osmotic pressure series', 'integrator': 'md', 'dt': 0.005, 'nsteps': None,
                      'nstcomm': 100, 'comm-grps': 'System', 'comm-mode': 'Linear', 'nstxout': 0, 'nstvout': 0,
                      'nstfout': 0, 'nstlog': 10000, 'nstenergy': None, 'nstxtcout': None, 'xtc-precision': 100,
                      'cutoff-scheme': 'Verlet', 'nstlist': 20, 'pbc': 'xyz', 'verlet-buffer-tolerance': -1,
                      'rlist': 1.35, 'coulombtype': 'reaction-field', 'rcoulomb': 1.1, 'epsilon-r': 15,
                      'epsilon-rf': 0, 'vdw-type': 'cutoff', 'vdw-modifier': 'potential-shift-verlet', 'rvdw': 1.1,
                      'tcoupl': 'v-rescale', 'tc-grps': 'System', 'tau-t': 1.0, 'ref-t': None, 'pcoupl': 'berendsen',
                      'pcoupltype': 'semiisotropic', 'compressibility': '0 4.5e-05', 'tau-p': 4.0,
                      'ref-p': '1.0 1.0', 'constraints': 'none', 'constraint-algorithm': 'Lincs',
                      'lincs-order': 4, 'lincs-warnangle': 30, 'refcoord-scaling': 'all', 'gen-vel': 'yes',
                      'gen-temp': None, 'gen-seed': -1, 'continuation': 'no'},
            comments={**_OSMOTIC_COMMENTS, 'pcoupl': "berendsen: the paper's equilibration barostat",
                      'tau-p': "4 ps: the paper's equilibration time constant",
                      'gen-vel': 'this leg draws its own velocities',
                      'continuation': 'no: this leg starts the dynamics'},
            source=_OSMOTIC_SOURCE, version='osmotic-equilibration-v1', notes=_OSMOTIC_NOTES),
    Profile(settings={'title': 'Martini, osmotic pressure series', 'integrator': 'md', 'dt': 0.02, 'nsteps': None,
                      'nstcomm': 100, 'comm-grps': 'System', 'comm-mode': 'Linear', 'nstxout': 0, 'nstvout': 0,
                      'nstfout': 0, 'nstlog': 10000, 'nstenergy': None, 'nstxtcout': None, 'xtc-precision': 100,
                      'cutoff-scheme': 'Verlet', 'nstlist': 20, 'pbc': 'xyz', 'verlet-buffer-tolerance': -1,
                      'rlist': 1.35, 'coulombtype': 'reaction-field', 'rcoulomb': 1.1, 'epsilon-r': 15,
                      'epsilon-rf': 0, 'vdw-type': 'cutoff', 'vdw-modifier': 'potential-shift-verlet', 'rvdw': 1.1,
                      'tcoupl': 'v-rescale', 'tc-grps': 'System', 'tau-t': 1.0, 'ref-t': None,
                      'pcoupl': 'parrinello-rahman', 'pcoupltype': 'semiisotropic', 'compressibility': '0 4.5e-05',
                      'tau-p': 12.0, 'ref-p': '1.0 1.0', 'constraints': 'none', 'constraint-algorithm': 'Lincs',
                      'lincs-order': 4, 'lincs-warnangle': 30, 'refcoord-scaling': 'all', 'gen-vel': 'no',
                      'gen-temp': None, 'gen-seed': -1, 'continuation': 'yes'},
            comments={**_OSMOTIC_COMMENTS,
                      'pcoupl': 'parrinello-rahman in production, at the same 1 bar as the CG half',
                      'tau-p': '12 ps: production, where Parrinello-Rahman is more stable with a larger tau-p',
                      'gen-vel': 'production continues the equilibrated velocities',
                      'continuation': 'yes: this leg continues the equilibrated state'},
            source=_OSMOTIC_SOURCE, version='osmotic-production-v1', notes=_OSMOTIC_NOTES),
)

#: Every reviewed MDP this project writes, keyed by the name a run records.
PROFILES = {profile.version: profile
            for profile in (*AA_PROFILES, *CG_PROFILES, *PDC_LEG_PROFILES, *PDC_PRODUCTION_PROFILES,
                            *PDC_RESTART_PROFILES, *OSMOTIC_PROFILES)}

__all__ = ['PROFILES']
