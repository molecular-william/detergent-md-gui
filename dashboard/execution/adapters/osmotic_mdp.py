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


def plumed_walls(*, solute_molecules, solute_atoms, solvent_atoms,
                 confinement_nm=DEFAULT_CONFINEMENT_NM,
                 force_constant=DEFAULT_CONFINEMENT_KJ_MOL_NM2,
                 print_stride=500):
    """The flat-bottomed confinement as a PLUMED input, which is the paper's potential and GROMACS's `pull` cannot be.

    **Why PLUMED rather than the pull.** The paper's confinement is an *external* potential -- Luo and Roux's
    flat-bottom, "to the center of the box" -- and GROMACS's `pull` is a spring between two groups. The run that died
    at 2.4 ns of equilibration, read from its own trajectory and its own pull output: the solute's centre of mass sat
    1.64 nm from the origin, comfortably inside the 2.52078 nm wall, and the origin within 0.026 nm of the box centre
    -- but the *coordinate* `pull` reports is the unwrapped z-difference and it grew to 4.91 nm, nearly half the box,
    until mdrun's half-box check aborted the run. A coordinate free to pass half the box is also a potential free to
    act on the wrong side of it: once the minimum image flips, the flat-bottom pushes away rather than back. PLUMED
    evaluates the wall on an absolute coordinate, so there is no image to flip and no half-box readout to trip.

    The reference is the **solvent's centre of mass**, which is the box centre by symmetry and, being ~2000 beads,
    absorbs the reaction force as 1/2000 of itself per bead -- the pull had a single reference atom and could not.
    """
    molecules = int(solute_molecules)
    if molecules < 1:
        raise ValueError('plumed walls need at least one solute molecule to confine, or there is nothing to write')
    solute = [int(index) for index in solute_atoms]
    solvent = [int(index) for index in solvent_atoms]
    if not solvent:
        raise ValueError('plumed walls need the solvent as the reference, and none was given')
    per_molecule = len(solute) // molecules
    if per_molecule * molecules != len(solute):
        raise ValueError(f'{len(solute)} solute atoms do not divide into {molecules} molecules')
    lines = ['# The flat-bottomed confinement, generated by dashboard/execution/adapters/osmotic_mdp.py',
             '# The paper: "At a distance of 2.52078 nm from the center of the box, a harmonic force with a force',
             '# constant 1000 kJ/nm2 was applied to the solute molecules."',
             'UNITS LENGTH=nm ENERGY=kj/mol TIME=ps',
             '']
    # The box centre, as the solvent's centre of mass: by symmetry it is the centre, and it moves with the box.
    lines.append('ref: COM ATOMS=' + ','.join(str(i) for i in solvent))
    lines.append('centre: CUSTOM ARG=ref.z PERIODIC=NO FUNC=x')
    lines.append('')
    names = []
    for molecule in range(1, molecules + 1):
        first = (molecule - 1) * per_molecule + 1
        atoms = ','.join(str(i) for i in range(first, first + per_molecule))
        lines.append(f'm{molecule}: COM ATOMS={atoms}')
        lines.append(f'd{molecule}: CUSTOM ARG=m{molecule}.z,centre PERIODIC=NO FUNC=y-x')
        names.append(f'd{molecule}')
    lines.append('')
    arguments = ','.join(names)
    lines.append(f'# the two walls, each on every molecule: flat inside, quadratic beyond, k = {force_constant:g}')
    lines.append(f'upper: UPPER_WALLS ARG={arguments} AT={float(confinement_nm):g} '
                 f'KAPPA={float(force_constant):g} EXP=2 EPS=1 OFFSET=0')
    lines.append(f'lower: LOWER_WALLS ARG={arguments} AT=-{float(confinement_nm):g} '
                 f'KAPPA={float(force_constant):g} EXP=2 EPS=1 OFFSET=0')
    if int(print_stride) > 0:
        lines.append('')
        lines.append("# The walls' own energy, so the constant this engine applies is measured rather than assumed.")
        lines.append('# PLUMED writes the harmonic wall as k(x-AT)^2, so the force it applies is 2k(r-AT) -- twice the')
        lines.append("# paper's stated 1000 kJ/mol/nm2 if KAPPA is read as that constant. The analysis recomputes the force")
        lines.append('# from the trajectory with the paper\'s own constant either way; this file is how the simulation\'s')
        lines.append('# convention is checked against it.')
        lines.append(f'PRINT ARG=upper.bias,lower.bias,d1 FILE=plumed_bias.dat STRIDE={int(print_stride)}')
    return '\n'.join(lines) + '\n'


def restraint_block(*, solute_molecules):
    """What the confinement contributes to the *mdp*: nothing but a note saying where it went.

    **PLUMED, not `pull`, and the runs say why.** The paper's flat-bottom is an *external* potential -- Luo and
    Roux's, "to the center of the box" -- while `pull` is a spring between two groups. Three runs died on that
    difference. The last one's numbers, from its own output: the coordinate `pull` reports is the *unwrapped*
    z-difference and it grew to 4.91 nm, nearly half the box, until mdrun's half-box check aborted the run -- while
    the trajectory shows the solute's centre of mass 1.64 nm from the origin, comfortably inside the 2.52078 nm wall,
    and the origin itself within 0.026 nm of the box centre. So the wall was holding the solute and the *readout* is
    what failed. A coordinate free to pass half the box is also a potential free to act on the wrong side of it: once
    the minimum image flips, the flat-bottom pushes away rather than back. PLUMED evaluates each wall on an absolute
    coordinate, so there is no image to flip and no half-box readout to trip.

    **This build reaches PLUMED through `mdrun -plumed plumed.dat`, not through the mdp.** `gmx mdrun -h` lists
    `-plumed [<.dat>] (plumed.dat)` with `plumed.dat` as its own default; `gmx grompp -h` mentions PLUMED nowhere,
    and naming `plumed` or `plumed-file` in an mdp is answered with "Unknown left-hand 'plumed' in parameter file" --
    two warnings, and `-maxwarn 1` stops the run before it starts. So the confinement is switched on at the mdrun
    call, and all this function has to say is where to look.
    """
    molecules = int(solute_molecules)
    if molecules < 0:
        raise ValueError('a solute molecule count cannot be negative')
    if molecules == 0:
        # The pure-solvent control. There is nothing to confine, and its osmotic pressure is zero by construction --
        # refusing it would delete the one condition in a series that shows where the measurement floor is.
        return ['; the pure-solvent control: nothing is confined, so mdrun takes no -plumed']
    return ['; the confinement is PLUMED (plumed_walls writes plumed.dat): mdrun -plumed plumed.dat']


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
        # The reference bead defines the coordinate's origin. It is **restrained to the box centre rather than
        # frozen**, and `refcoord-scaling = all` is what makes the target follow the box: a frozen atom is not scaled
        # by the barostat, so at 1 bar in z the original centre stops being the centre. With the reference coordinates
        # scaled, the restraint target moves with the box and the bead is at the centre for every box size -- which is
        # what the paper's "flat-bottomed potential to the center of the box" means.
        'refcoord-scaling         = all',
        # No `define = -DPOSRES`: this project's `[ position_restraints ]` is not wrapped in that macro, so the
        # section applies on its own -- and defining an unused macro is a warning grompp counts, which pushed the
        # equilibration past the runner's `-maxwarn 1`. Verified the restraint is live without it: the bead sits at
        # the box centre to within the .gro rounding through solvation and minimization.
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
                 origin_group='REFERENCE',
                 confinement_nm=DEFAULT_CONFINEMENT_NM,
                 force_constant=DEFAULT_CONFINEMENT_KJ_MOL_NM2):
    """The three mdp files for one condition, as `{'minimization'|'equilibration'|'production': text}`.

    Durations are in picoseconds and the step counts are derived from each file's own `dt` -- 5 fs where the paper's
    equilibration runs and 20 fs in production, the same split as every other CG run here.

    The confinement's own numbers -- `confinement_nm`, `force_constant`, and the group that used to serve as its
    origin -- are accepted here for the callers that still name them, but they are spent by `plumed_walls`, which
    writes the potential itself. The mdp only switches it on.
    """
    restraint = restraint_block(solute_molecules=solute_molecules)
    equilibration_ps, output_interval_ps = _check_duration(equilibration_ps, output_interval_ps, 'equilibration')
    production_ps, _ = _check_duration(production_ps, output_interval_ps, 'production')

    equilibration = _lines(
        dt=EQUILIBRATION_DT, nsteps=math.ceil(equilibration_ps / EQUILIBRATION_DT),
        nstxtcout=_every_steps(output_interval_ps, EQUILIBRATION_DT, 'equilibration'),
        nstenergy=_every_steps(output_interval_ps, EQUILIBRATION_DT, 'equilibration'),
        thermostat='v-rescale', barostat='berendsen', tau_p=4.0, temperature=temperature,
        compressibility=WATER_COMPRESSIBILITY, gen_vel='yes', continuation='no', restraint=restraint)
    production = _lines(
        dt=PRODUCTION_DT, nsteps=int(round(production_ps / PRODUCTION_DT)),
        nstxtcout=_every_steps(output_interval_ps, PRODUCTION_DT, 'production'),
        nstenergy=_every_steps(output_interval_ps, PRODUCTION_DT, 'production'),
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
        # The same restraint as the other two stages, and most needed here: minimization is where a badly placed
        # configuration moves furthest. `refcoord-scaling` keeps the reference at the box centre -- see the note in
        # restraint_block.
        'refcoord-scaling         = all',
        '',
        '; the method: the solute is confined to the centre, from the first step',
    ] + restraint
    return {'minimization': '\n'.join(minimization) + '\n',
            'equilibration': '\n'.join(equilibration) + '\n',
            'production': '\n'.join(production) + '\n'}
