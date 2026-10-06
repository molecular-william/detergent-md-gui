"""The three mdp files for one osmotic-pressure condition.

Derived from this repository's own CG templates (`resources/templates/small_mols_fast_forward/4_CG_sim/inputs`), so
that everything not named below is the same physics as every other CG run here. The differences are the method:

| the paper's method | what this changes from the CG half |
| --- | --- |
| pressure coupled only in z | `pcoupltype = semiisotropic` with `compressibility = 0 <water>`; the CG half is isotropic |
| the solute confined by a flat-bottomed potential | a `pull` coordinate, flat within 2.52078 nm of the centre and harmonic at 1000 kJ/mol/nm2 beyond it |
| a 10 ns equilibration with a Berendsen barostat | `pcoupl = berendsen` there, where the CG equilibration uses c-rescale |
| the temperature of the experimental dataset | `ref_t`, `gen-temp` and `ref_p` are **parameters with no default** |

**No default temperature, deliberately.** 308.15 K is maltose's, from Ebrahimi & Sadeghi 2016. A default would apply
one dataset's temperature to another molecule's series and nothing in the output would say so.

**Two pull groups are mandatory, and one of them is a reference.** Verified by probe on 2026-10-06 against
`/usr/local/gromacs/2026.3/bin/gmx`: `geometry = direction` with `vec = 0 0 1` is accepted with two groups and refused
with one -- *"pull-coord1-groups should contain 2 pull group indices with geometry"*. The second group must be
something whose centre of mass **is** the box centre: a frozen, interaction-excluded bead placed there by the builder.
The solvent is the obvious choice and the wrong one -- its centre of mass moves the opposite way as the solute moves,
which amplifies the coordinate rather than measuring it. `reference_group` is therefore a parameter and the builder's
job is to make that name true.

**The restraint is in every stage, including minimization.** A stage without it is a stage where the solute is free to
drift out of the slab, and a minimization is where a bad initial configuration would do exactly that.
"""
import math

STAGES = ('minimization', 'equilibration', 'production')
DEFAULT_CONFINEMENT_NM = 2.52078
DEFAULT_CONFINEMENT_KJ_MOL_NM2 = 1000.0
DEFAULT_EQUILIBRATION_PS = 10000.0     # 10 ns, the paper's
DEFAULT_PRODUCTION_PS = 500000.0       # 500 ns, the paper's
DEFAULT_OUTPUT_INTERVAL_PS = 10.0      # dense enough that the force average is not a handful of frames
WATER_COMPRESSIBILITY = 4.5e-5         # the CG templates' own value, from the papers


def _check_duration(duration_ps, output_interval_ps, what):
    duration_ps = float(duration_ps)
    output_interval_ps = float(output_interval_ps)
    if duration_ps <= 0 or output_interval_ps <= 0:
        raise ValueError(f'{what} duration and output interval must both be positive')
    if duration_ps < output_interval_ps:
        raise ValueError(f'{what} duration {duration_ps} ps is shorter than its output interval '
                         f'{output_interval_ps} ps, which would write one frame')
    ratio = duration_ps / output_interval_ps
    if abs(ratio - round(ratio)) > 1e-9:
        # Not fatal for GROMACS, which simply writes the frames that fit. Fatal for an average over the series, where
        # two conditions with different effective windows are not comparable.
        raise ValueError(f'{what} duration {duration_ps} ps is not a whole number of {output_interval_ps} ps intervals')
    return duration_ps, output_interval_ps


def restraint_block(*, solute_group='SOLUTE', reference_group='REFERENCE',
                    confinement_nm=DEFAULT_CONFINEMENT_NM,
                    force_constant=DEFAULT_CONFINEMENT_KJ_MOL_NM2):
    """The flat-bottomed pull that confines the solute to a slab at the centre, as mdp lines.

    `geometry = direction` with `vec = 0 0 1` measures the z projection of the two groups' separation, so `init` is
    the half-width of the slab: flat inside it, harmonic beyond. The force is *not* read back from this machinery --
    the analysis recomputes it from the trajectory -- so what matters here is that the confinement reproduces the
    potential the analysis assumes.
    """
    return [
        'pull                    = yes',
        'pull-ngroups            = 2',
        f'pull-group1-name        = {solute_group}',
        f'pull-group2-name        = {reference_group}',
        'pull-ncoords            = 1',
        'pull-coord1-groups      = 1 2',
        'pull-coord1-geometry    = direction',
        'pull-coord1-vec         = 0 0 1',
        'pull-coord1-type        = flat-bottom',
        f'pull-coord1-init        = {float(confinement_nm):g}',
        'pull-coord1-rate        = 0',
        f'pull-coord1-k           = {float(force_constant):g}',
    ]


def _lines(*, dt, nsteps, nstxtcout, nstenergy, thermostat, barostat, tau_p, temperature,
           compressibility, gen_vel, continuation, restraint):
    return [
        'title                    = Martini, osmotic pressure series',
        '',
        'integrator               = md',
        f'dt                       = {dt:g}',
        f'nsteps                   = {int(nsteps)}',
        '',
        'nstcomm                  = 100',
        'comm-grps                = System',
        'comm-mode                = Linear',
        '',
        'nstxout                  = 0',
        'nstvout                  = 0',
        'nstfout                  = 0',
        'nstlog                   = 10000',
        f'nstenergy                = {int(nstenergy)}',
        f'nstxtcout                = {int(nstxtcout)}',
        'xtc_precision            = 100',
        '',
        'cutoff-scheme            = Verlet',
        'nstlist                  = 20',
        'pbc                      = xyz',
        'verlet-buffer-tolerance  = -1',
        'rlist                    = 1.35',
        'coulombtype              = reaction-field',
        'rcoulomb                 = 1.1',
        'epsilon_r                = 15',
        'epsilon_rf               = 0',
        'vdw_type                 = cutoff',
        'vdw-modifier             = potential-shift-verlet',
        'rvdw                     = 1.1',
        '',
        f'tcoupl                   = {thermostat}',
        'tc-grps                  = System',
        'tau_t                    = 1.0',
        f'ref_t                    = {float(temperature):g}',
        f'pcoupl                   = {barostat}',
        'pcoupltype               = semiisotropic',
        # Only z is coupled: zero compressibility in xy means the box is not rescaled there.
        f'compressibility          = 0 {compressibility:g}',
        f'tau_p                    = {tau_p:g}',
        'ref_p                    = 1.0 1.0',
        '',
        'constraints              = none',
        'constraint_algorithm     = Lincs',
        'lincs_order              = 4',
        'lincs_warnangle          = 30',
        f'gen_vel                  = {gen_vel}',
        f'gen-temp                 = {float(temperature):g}',
        'gen-seed                 = -1',
        f'continuation             = {continuation}',
        '',
        '; the method: the solute is confined to the centre, and the walls sit at the quarter box',
    ] + restraint


def osmotic_mdps(*, temperature, production_ps=DEFAULT_PRODUCTION_PS,
                 equilibration_ps=DEFAULT_EQUILIBRATION_PS,
                 output_interval_ps=DEFAULT_OUTPUT_INTERVAL_PS,
                 solute_group='SOLUTE', reference_group='REFERENCE',
                 confinement_nm=DEFAULT_CONFINEMENT_NM,
                 force_constant=DEFAULT_CONFINEMENT_KJ_MOL_NM2):
    """The three mdp files for one condition, as `{'minimization'|'equilibration'|'production': text}`.

    Durations are in picoseconds and the step counts are derived from each file's own `dt` -- 5 fs where the paper's
    equilibration runs and 20 fs in production, the same split as every other CG run here.
    """
    restraint = restraint_block(solute_group=solute_group, reference_group=reference_group,
                                confinement_nm=confinement_nm, force_constant=force_constant)
    equilibration_ps, output_interval_ps = _check_duration(equilibration_ps, output_interval_ps, 'equilibration')
    production_ps, _ = _check_duration(production_ps, output_interval_ps, 'production')

    equilibration = _lines(
        dt=0.005, nsteps=math.ceil(equilibration_ps / 0.005),
        nstxtcout=int(equilibration_ps / output_interval_ps), nstenergy=100,
        thermostat='v-rescale', barostat='berendsen', tau_p=4.0, temperature=temperature,
        compressibility=WATER_COMPRESSIBILITY, gen_vel='yes', continuation='no', restraint=restraint)
    production = _lines(
        dt=0.02, nsteps=int(round(production_ps / 0.02)),
        nstxtcout=int(production_ps / output_interval_ps), nstenergy=int(1000 / 0.02),
        thermostat='v-rescale', barostat='parrinello-rahman', tau_p=12.0, temperature=temperature,
        compressibility=WATER_COMPRESSIBILITY, gen_vel='no', continuation='yes', restraint=restraint)
    minimization = [
        'title                    = Martini, osmotic pressure series, minimization',
        '',
        'integrator               = steep',
        'nsteps                   = 20000',
        'emtol                    = 100.0',
        'emstep                   = 0.01',
        '',
        'cutoff-scheme            = Verlet',
        'nstlist                  = 20',
        'pbc                      = xyz',
        'verlet-buffer-tolerance  = -1',
        'rlist                    = 1.35',
        'coulombtype              = reaction-field',
        'rcoulomb                 = 1.1',
        'epsilon_r                = 15',
        'epsilon_rf               = 0',
        'vdw_type                 = cutoff',
        'vdw-modifier             = potential-shift-verlet',
        'rvdw                     = 1.1',
        '',
        'constraints              = none',
        'constraint_algorithm     = Lincs',
        '',
        '; the method: the solute is confined to the centre, from the first step',
    ] + restraint
    return {'minimization': '\n'.join(minimization) + '\n',
            'equilibration': '\n'.join(equilibration) + '\n',
            'production': '\n'.join(production) + '\n'}
