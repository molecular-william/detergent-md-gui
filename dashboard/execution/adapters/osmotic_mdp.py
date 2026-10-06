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
EQUILIBRATION_DT = 0.005               # 5 fs, the time step the CG equilibration integrates at
PRODUCTION_DT = 0.02                   # 20 fs, the time step CG production integrates at
WATER_COMPRESSIBILITY = 4.5e-5         # the CG templates' own value, from the papers


def _every_steps(interval_ps, dt, what):
    """An output interval as a step count, which is what every `nst*` option is.

    The first version of this module divided the *duration* by the interval and passed the result as a step count, so
    a 500 ns run asked for a frame every 10 ps would have written one every nanosecond -- 500 frames instead of 50,000.
    A flat-bottom force averaged over those would have been a number with no error bar worth reporting, and the run
    would have cost the same.
    """
    steps = float(interval_ps) / dt
    if abs(steps - round(steps)) > 1e-9:
        raise ValueError(f'{what} output interval {interval_ps:g} ps is not a whole number of {dt * 1000:g} fs steps')
    return int(round(steps))


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


def restraint_block(*, solute_molecules, reference_group='REFERENCE',
                    confinement_nm=DEFAULT_CONFINEMENT_NM,
                    force_constant=DEFAULT_CONFINEMENT_KJ_MOL_NM2):
    """The flat-bottomed pull that confines the solute to a slab at the centre, as mdp lines.

    `geometry = direction-periodic` with `vec = 0 0 1` measures the z projection of the two groups' separation, so
    `init` is the half-width of the slab: flat inside it, harmonic beyond. The force is *not* read back from this
    machinery -- the analysis recomputes it from the trajectory -- so what matters here is that the confinement
    reproduces the potential the analysis assumes.

    **Two settings together, and neither works alone** -- this is what grompp's own message says, in full: "The
    maximum distance from the chosen PBC atom (280) of pull group 1 to other atoms in the group is larger than 0.5
    times half the box size. Set the pull-pbc-ref-prev-step-com option to yes." The solute fills the box in xy (only
    z is confined), so its extent is comparable to the box and no single atom can be within a quarter box of all of
    it. Naming a pbcatom alone fails the distance check; `pull-pbc-ref-prev-step-com` alone fails the "specific atom
    selected" check. Both together are accepted. The *atom* is not known here -- it depends on where the molecules
    were placed -- so the runner appends it to each mdp, which is also why that file is written after placement.

    **The geometry is `direction`, not `direction-periodic`**, and that is forced rather than chosen: the box is
    dynamic -- the paper couples pressure at 1 bar -- and grompp refuses the pair outright with "Can not have dynamic
    box while using pull geometry 'direction-periodic' (dim z)". The periodic geometry only applies to a fixed box.

    **One coordinate per solute molecule**, which is what the paper describes: "At a distance of 2.52078 nm from the
    center of the box, a harmonic force with a force constant 1000 kJ/nm2 was applied to the solute molecules." Each
    coordinate is one molecule's centre of mass against the frozen reference bead, so every molecule is confined
    individually and the force the analysis averages is the sum over molecules -- the quantity divided by the xy area.

    **Why not one group for the whole solute**, which is what this started as: with the solute filling the box in xy,
    that group cannot be given a PBC reference atom -- GROMACS requires every atom within a quarter box of one, and
    the group's own extent is larger than that. grompp refuses it three different ways, and when it was forced
    through, mdrun aborted the run after 76 ns when the coordinate it computed from the wrong reference exceeded
    half the box. A single molecule is about 0.5 nm across, so the check passes on its own and no
    `pull-group*-pbcatom` and no `pull-pbc-ref-prev-step-com` is needed at all.
    """
    molecules = int(solute_molecules)
    if molecules < 0:
        raise ValueError('a solute molecule count cannot be negative')
    if molecules == 0:
        # The pure-solvent control. There is nothing to confine, and its osmotic pressure is zero by construction --
        # refusing it would delete the one condition in a series that shows where the measurement floor is.
        return ['pull                    = no']
    reference = molecules + 1
    lines = ['pull                    = yes',
             f'pull-ngroups            = {molecules + 1}',
             f'pull-ncoords            = {molecules}']
    lines += [f'pull-group{index}-name        = MOL{index}' for index in range(1, molecules + 1)]
    lines += [f'pull-group{reference}-name        = {reference_group}']
    for coordinate in range(1, molecules + 1):
        lines += [f'pull-coord{coordinate}-groups      = {coordinate} {reference}',
                  f'pull-coord{coordinate}-geometry    = direction',
                  f'pull-coord{coordinate}-vec         = 0 0 1',
                  f'pull-coord{coordinate}-type        = flat-bottom',
                  f'pull-coord{coordinate}-init        = {float(confinement_nm):g}',
                  f'pull-coord{coordinate}-rate        = 0',
                  f'pull-coord{coordinate}-k           = {float(force_constant):g}']
    return lines


def _lines(*, dt, nsteps, nstxtcout, nstenergy, thermostat, barostat, tau_p, temperature,
           compressibility, gen_vel, continuation, restraint, pull_nstfout=0):
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
        # The reference bead defines the coordinate's origin, so it must not move. It is frozen rather than
        # restrained: a spring would let it drift, and the drift would be indistinguishable from an osmotic pressure.
        'freezegrps               = REFERENCE',
        'freezedim                = Y Y Y',
        f'gen_vel                  = {gen_vel}',
        f'gen-temp                 = {float(temperature):g}',
        'gen-seed                 = -1',
        f'continuation             = {continuation}',
        '',
        '; the method: the solute is confined to the centre, and the walls sit at the quarter box',
        # The engine's own force on the restraint, written every `pull_nstfout` steps. The analysis recomputes the
        # force from the trajectory; this is the independent measurement it is checked against, and it costs one
        # number per frame.
    ] + ([f'pull-nstfout            = {int(pull_nstfout)}'] if pull_nstfout else []) + restraint


def osmotic_mdps(*, temperature, solute_molecules, production_ps=DEFAULT_PRODUCTION_PS,
                 equilibration_ps=DEFAULT_EQUILIBRATION_PS,
                 output_interval_ps=DEFAULT_OUTPUT_INTERVAL_PS,
                 reference_group='REFERENCE',
                 confinement_nm=DEFAULT_CONFINEMENT_NM,
                 force_constant=DEFAULT_CONFINEMENT_KJ_MOL_NM2):
    """The three mdp files for one condition, as `{'minimization'|'equilibration'|'production': text}`.

    Durations are in picoseconds and the step counts are derived from each file's own `dt` -- 5 fs where the paper's
    equilibration runs and 20 fs in production, the same split as every other CG run here.
    """
    restraint = restraint_block(solute_molecules=solute_molecules, reference_group=reference_group,
                                confinement_nm=confinement_nm, force_constant=force_constant)
    equilibration_ps, output_interval_ps = _check_duration(equilibration_ps, output_interval_ps, 'equilibration')
    production_ps, _ = _check_duration(production_ps, output_interval_ps, 'production')

    equilibration = _lines(
        dt=EQUILIBRATION_DT, nsteps=math.ceil(equilibration_ps / EQUILIBRATION_DT),
        nstxtcout=_every_steps(output_interval_ps, EQUILIBRATION_DT, 'equilibration'),
        nstenergy=_every_steps(output_interval_ps, EQUILIBRATION_DT, 'equilibration'),
        thermostat='v-rescale', barostat='berendsen', tau_p=4.0, temperature=temperature,
        compressibility=WATER_COMPRESSIBILITY, gen_vel='yes', continuation='no', restraint=restraint,
        pull_nstfout=(_every_steps(output_interval_ps, EQUILIBRATION_DT, 'equilibration')
                      if int(solute_molecules) else 0))
    production = _lines(
        dt=PRODUCTION_DT, nsteps=int(round(production_ps / PRODUCTION_DT)),
        nstxtcout=_every_steps(output_interval_ps, PRODUCTION_DT, 'production'),
        nstenergy=_every_steps(output_interval_ps, PRODUCTION_DT, 'production'),
        thermostat='v-rescale', barostat='parrinello-rahman', tau_p=12.0, temperature=temperature,
        compressibility=WATER_COMPRESSIBILITY, gen_vel='no', continuation='yes', restraint=restraint,
        pull_nstfout=(_every_steps(output_interval_ps, PRODUCTION_DT, 'production')
                      if int(solute_molecules) else 0))
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
        # The same freeze as the other two stages, and most needed here: minimization is where a badly placed
        # configuration moves furthest, and a reference that drifts is indistinguishable from an osmotic pressure.
        'freezegrps               = REFERENCE',
        'freezedim                = Y Y Y',
        '',
        '; the method: the solute is confined to the centre, from the first step',
    ] + restraint
    return {'minimization': '\n'.join(minimization) + '\n',
            'equilibration': '\n'.join(equilibration) + '\n',
            'production': '\n'.join(production) + '\n'}
