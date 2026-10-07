"""The osmotic mdps, checked against the method rather than against themselves.

Every assertion here is a statement from the paper or from Task 0.1's probe. The one that is neither is the duration
arithmetic, and that is checked against the step count the file itself states.
"""
import re

import pytest

from dashboard.execution.adapters import osmotic_mdp

#: What the tests confine. Every mdp call goes through `mdps()` so the count is stated once, and the per-molecule
#: coordinates are exercised rather than a single-coordinate special case.
MOLECULES = 3


def mdps(**overrides):
    """The three stages for a condition, with the temperature and molecule count the tests use."""
    return osmotic_mdp.osmotic_mdps(temperature=308.15, solute_molecules=MOLECULES, **overrides)


def settings(text):
    """An mdp as a dict, ignoring comments and blanks -- what GROMACS would read."""
    found = {}
    for line in text.splitlines():
        line = line.split(';', 1)[0].strip()
        if '=' in line:
            key, _, value = line.partition('=')
            found[key.strip().lower()] = value.strip()
    return found


def test_the_three_stages_exist_and_are_their_own_method():
    built = mdps()

    assert set(built) == {'minimization', 'equilibration', 'production'}
    assert settings(built['minimization'])['integrator'] == 'steep'
    assert settings(built['equilibration'])['integrator'] == 'md'
    assert settings(built['production'])['integrator'] == 'md'
    assert osmotic_mdp.STAGES == ('minimization', 'equilibration', 'production')


def test_only_z_is_coupled_and_the_cg_half_s_isotropic_coupling_is_not_reused():
    """The mechanism, not a preference: zero compressibility in xy means the box is not rescaled there."""
    built = mdps()

    for stage in ('equilibration', 'production'):
        read = settings(built[stage])
        assert read['pcoupltype'] == 'semiisotropic'
        compressibility = read['compressibility'].split()
        assert compressibility[0] == '0'
        assert float(compressibility[1]) > 0.0
        assert read['ref_p'].split() == ['1.0', '1.0']


def test_the_equilibration_uses_a_berendsen_barostat_because_the_paper_says_so():
    """This is the one place the osmotic series deliberately differs from every other CG run here, whose
    equilibration uses c-rescale. The paper names Berendsen; the CG half's value would be a different method."""
    equilibration = settings(mdps()['equilibration'])
    production = settings(mdps()['production'])

    assert equilibration['pcoupl'] == 'berendsen'
    assert equilibration['tcoupl'] == 'v-rescale'
    # The paper does not name the production barostat; this repository's CG production uses Parrinello-Rahman, and
    # that is what runs -- recorded here so the choice is visible rather than assumed.
    assert production['pcoupl'] == 'parrinello-rahman'


def test_the_solute_is_confined_in_every_stage_including_minimization():
    """A stage without the confinement is a stage where the solute can drift out of the slab, and minimization is
    exactly where a bad initial configuration would. The mdp switches the potential on; `plumed_walls` writes it."""
    built = mdps()

    for stage, text in built.items():
        # The mdp carries a note, not a switch: this build reaches PLUMED at the mdrun call (`-plumed plumed.dat`).
        # An mdp entry named `plumed` is answered with "Unknown left-hand 'plumed' in parameter file" -- two
        # warnings against `-maxwarn 1`, which is what stopped the first run that carried them.
        assert 'the confinement is PLUMED' in text, stage
        assert not [key for key in settings(text) if key.startswith('plumed')], stage


def test_every_molecule_gets_its_own_wall_pair():
    """One wall pair per molecule, which is what the paper describes: "At a distance of 2.52078 nm from the center
    of the box, a harmonic force with a force constant 1000 kJ/nm2 was applied to the solute molecules."

    This started as *one* group for the whole solute, then as one `pull` coordinate per molecule against a reference
    bead. Both are gone. A `pull` is a spring between two groups, so the coordinate it reports is the *unwrapped*
    z-difference: the run that died at 2.4 ns of equilibration had grown one to 4.91 nm, nearly half the box, while
    its own trajectory showed the solute 1.64 nm from the origin and the origin 0.026 nm from the box centre. And a
    coordinate free to pass half the box is a potential free to act on the wrong side of it -- once the minimum image
    flips, a flat-bottom pushes *away*. PLUMED evaluates each wall on an absolute coordinate, so neither can happen.
    """
    text = osmotic_mdp.plumed_walls(solute_molecules=4, solute_atoms=range(1, 21), box_centre_nm=5.0)

    for molecule in range(1, 5):
        first = (molecule - 1) * 5 + 1
        assert f'm{molecule}: COM ATOMS=' + ','.join(str(i) for i in range(first, first + 5)) in text
    # One wall pair per molecule, on that molecule's own absolute z: 5.0 is the box centre, so the walls sit at
    # 2.47922 and 7.52078, and KAPPA is half the paper's force constant -- the engine's convention, measured.
    for molecule in range(1, 5):
        assert f'upper{molecule}: UPPER_WALLS ARG=m{molecule}.z AT=7.52078 KAPPA=500 EXP=2' in text
        assert f'lower{molecule}: LOWER_WALLS ARG=m{molecule}.z AT=2.47922 KAPPA=500 EXP=2' in text
    assert 'pull' not in text.lower()
    # No periodic CV at all: an absolute coordinate needs none, and the one that measured a group's centre of mass
    # returned 61.75 nm in a 10.08 nm box.
    assert 'CUSTOM' not in text


def test_the_potential_and_the_reference_the_failures_asked_for():
    """The two refusals that would otherwise be silent: a count the atoms do not divide into, and no reference to
    measure from. Either one produces a plumed.dat that runs and confines the wrong thing."""
    with pytest.raises(ValueError, match='do not divide'):
        osmotic_mdp.plumed_walls(solute_molecules=3, solute_atoms=range(1, 9), box_centre_nm=5.0)
    with pytest.raises(ValueError, match='box centre'):
        osmotic_mdp.plumed_walls(solute_molecules=1, solute_atoms=range(1, 9), box_centre_nm=0.0)


def test_the_origin_is_the_box_centre_and_it_is_named_outright():
    """The confinement is "to the center of the box", and the coordinate is the box's own z. Everything else was
    tried first: subtracting a group's centre of mass returned 61.75 nm in a 10.08 nm box, because a group that
    fills the box has no meaningful centre of mass. The centre is also the one coordinate the barostat cannot quietly
    invalidate here -- measured, it moved 0.006 nm over an equilibration.
    """
    text = osmotic_mdp.plumed_walls(solute_molecules=2, solute_atoms=range(1, 5), box_centre_nm=5.04156)

    assert 'The box centre is z = 5.04156 nm' in text
    assert 'AT=7.56234' in text and 'AT=2.52078' in text
    assert 'CUSTOM' not in text


def test_a_pure_solvent_control_has_nothing_to_confine_and_says_so():
    """0 molal is a legitimate condition: no solute, so no wall -- and its pressure is zero by construction. It is
    the condition that shows where the measurement floor is, so refusing it would delete a real measurement."""
    assert 'nothing is confined' in osmotic_mdp.restraint_block(solute_molecules=0)[0]

    with pytest.raises(ValueError, match='at least one solute molecule'):
        osmotic_mdp.plumed_walls(solute_molecules=0, solute_atoms=[], box_centre_nm=5.0)

    built = osmotic_mdp.osmotic_mdps(temperature=308.15, solute_molecules=0)
    for stage in ('equilibration', 'production'):
        assert not [key for key in settings(built[stage]) if key.startswith('plumed')], stage


def test_a_negative_molecule_count_is_refused():
    with pytest.raises(ValueError, match='cannot be negative'):
        osmotic_mdp.restraint_block(solute_molecules=-1)


def test_the_temperature_is_the_dataset_s_and_has_no_default():
    """308.15 K is maltose's, from Ebrahimi & Sadeghi 2016. A default would apply one dataset's temperature to
    another molecule's series and nothing in the output would say so."""
    with pytest.raises(TypeError):
        osmotic_mdp.osmotic_mdps()

    built = mdps()
    for stage in ('equilibration', 'production'):
        read = settings(built[stage])
        assert float(read['ref_t']) == pytest.approx(308.15)
        assert float(read['gen-temp']) == pytest.approx(308.15)


def test_each_stage_s_own_dt_turns_the_duration_into_its_step_count():
    built = mdps(equilibration_ps=10000.0, production_ps=500000.0)

    equilibration = settings(built['equilibration'])
    production = settings(built['production'])
    assert float(equilibration['dt']) == pytest.approx(0.005)
    assert int(equilibration['nsteps']) * 0.005 == pytest.approx(10000.0)
    assert float(production['dt']) == pytest.approx(0.02)
    assert int(production['nsteps']) * 0.02 == pytest.approx(500000.0)


def test_the_default_production_is_the_papers_five_hundred_nanoseconds():
    production = settings(mdps()['production'])

    assert int(production['nsteps']) * float(production['dt']) == pytest.approx(500000.0)
    assert osmotic_mdp.DEFAULT_PRODUCTION_PS == pytest.approx(500000.0)


def test_a_setup_check_can_run_five_nanoseconds_of_the_same_system():
    """The tier exists: a setup check must be able to run the same mdps short, so the duration is a parameter."""
    text = mdps(production_ps=5000.0)['production']

    assert int(settings(text)['nsteps']) * 0.02 == pytest.approx(5000.0)


def test_the_output_interval_divides_the_duration_exactly():
    """GROMACS would simply write the frames that fit. Two conditions with different effective averaging windows are
    not comparable, which is what makes this worth refusing."""
    with pytest.raises(ValueError, match='whole number'):
        mdps(production_ps=5005.0, output_interval_ps=10.0)
    with pytest.raises(ValueError, match='shorter than its output interval'):
        mdps(production_ps=5.0, output_interval_ps=10.0)
    with pytest.raises(ValueError, match='positive'):
        mdps(output_interval_ps=0.0)


def test_the_trajectory_is_written_often_enough_to_average_a_force_over():
    """The analysis recomputes the force from the trajectory, so the frame interval is what sets the sample size.
    500 ns at 10 ps is fifty thousand frames; at 1 ns it would be five hundred.

    `nstxtcout` is a *step* count, so the interval it implies is `nstxtcout * dt`. This test used to write
    `duration / nstxtcout`, which is a frame interval only if the step count were a frame count -- and that division
    returns 10 for exactly the numbers the buggy code produced. It passed while the run would have written one frame
    per nanosecond, and it would have blocked the fix.
    """
    production = settings(mdps()['production'])

    dt = float(production['dt'])
    interval_ps = int(production['nstxtcout']) * dt
    assert interval_ps == pytest.approx(10.0)
    assert int(production['nsteps']) * dt == pytest.approx(500000.0)
    assert int(production['nsteps']) / int(production['nstxtcout']) == 50000


def test_the_confinement_constants_are_the_papers_and_are_overridable_only_on_purpose():
    """The paper's two numbers, and where they now live: `plumed_walls` writes the potential, and the mdp only
    switches it on. The constants stayed in the mdp's signature for the callers that still name them."""
    assert osmotic_mdp.DEFAULT_CONFINEMENT_NM == pytest.approx(2.52078)
    assert osmotic_mdp.DEFAULT_CONFINEMENT_KJ_MOL_NM2 == pytest.approx(1000.0)

    text = osmotic_mdp.plumed_walls(solute_molecules=2, solute_atoms=range(1, 9), box_centre_nm=5.0,
                                    confinement_nm=1.0, force_constant=5.0)
    # KAPPA is half of it: PLUMED writes V = KAPPA*(x-AT)**2, so a force constant of 5 is KAPPA = 2.5 here, and
    # the walls sit 1 nm either side of the centre at 5.0.
    assert 'upper1: UPPER_WALLS ARG=m1.z AT=6 KAPPA=2.5 EXP=2' in text
    assert 'lower2: LOWER_WALLS ARG=m2.z AT=4 KAPPA=2.5 EXP=2' in text


def test_the_reference_bead_is_restrained_to_the_box_centre_in_every_stage():
    """It defines the coordinate's origin, so it must not move -- and it must not be *frozen* either, because the
    paper couples pressure at 1 bar and a frozen atom is not scaled by the barostat. `refcoord-scaling = all` is what
    makes the restraint target follow the box, so the bead is the centre for every box size. This is the fix for the
    run that aborted: its box contracted 19% and the frozen origin stopped being the centre."""
    built = mdps()

    for stage, text in built.items():
        read = settings(text)
        assert read['refcoord-scaling'] == 'all', stage
        assert 'freezegrps' not in read, stage
        # No POSRES: a bare [ position_restraints ] section applies on its own, and defining the unused macro is a
        # warning that pushed the equilibration past the runner's -maxwarn 1. The bead's position in the stage files
        # is the evidence that the restraint is live.
        assert 'define' not in read, stage


def test_every_line_is_a_comment_a_blank_or_a_key_value():
    """An mdp that GROMACS would reject is not worth writing, and the cheapest way to know is to look."""
    for stage, text in mdps().items():
        for number, line in enumerate(text.splitlines(), start=1):
            stripped = line.split(';', 1)[0].strip()
            assert not stripped or '=' in stripped, f'{stage}:{number}: {line!r}'
            assert not re.search(r'\s;', line.split(';')[0] + ' '), f'{stage}:{number}: {line!r}'
