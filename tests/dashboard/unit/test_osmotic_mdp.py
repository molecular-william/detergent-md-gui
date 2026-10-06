"""The osmotic mdps, checked against the method rather than against themselves.

Every assertion here is a statement from the paper or from Task 0.1's probe. The one that is neither is the duration
arithmetic, and that is checked against the step count the file itself states.
"""
import re

import pytest

from dashboard.execution.adapters import osmotic_mdp


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
    mdps = osmotic_mdp.osmotic_mdps(temperature=308.15)

    assert set(mdps) == {'minimization', 'equilibration', 'production'}
    assert settings(mdps['minimization'])['integrator'] == 'steep'
    assert settings(mdps['equilibration'])['integrator'] == 'md'
    assert settings(mdps['production'])['integrator'] == 'md'
    assert osmotic_mdp.STAGES == ('minimization', 'equilibration', 'production')


def test_only_z_is_coupled_and_the_cg_half_s_isotropic_coupling_is_not_reused():
    """The mechanism, not a preference: zero compressibility in xy means the box is not rescaled there."""
    mdps = osmotic_mdp.osmotic_mdps(temperature=308.15)

    for stage in ('equilibration', 'production'):
        read = settings(mdps[stage])
        assert read['pcoupltype'] == 'semiisotropic'
        compressibility = read['compressibility'].split()
        assert compressibility[0] == '0'
        assert float(compressibility[1]) > 0.0
        assert read['ref_p'].split() == ['1.0', '1.0']


def test_the_equilibration_uses_a_berendsen_barostat_because_the_paper_says_so():
    """This is the one place the osmotic series deliberately differs from every other CG run here, whose
    equilibration uses c-rescale. The paper names Berendsen; the CG half's value would be a different method."""
    equilibration = settings(osmotic_mdp.osmotic_mdps(temperature=308.15)['equilibration'])
    production = settings(osmotic_mdp.osmotic_mdps(temperature=308.15)['production'])

    assert equilibration['pcoupl'] == 'berendsen'
    assert equilibration['tcoupl'] == 'v-rescale'
    # The paper does not name the production barostat; this repository's CG production uses Parrinello-Rahman, and
    # that is what runs -- recorded here so the choice is visible rather than assumed.
    assert production['pcoupl'] == 'parrinello-rahman'


def test_the_solute_is_confined_in_every_stage_including_minimization():
    """A stage without the restraint is a stage where the solute can drift out of the slab, and minimization is
    exactly where a bad initial configuration would."""
    mdps = osmotic_mdp.osmotic_mdps(temperature=308.15)

    for stage, text in mdps.items():
        read = settings(text)
        assert read['pull'] == 'yes', stage
        assert read['pull-coord1-type'] == 'flat-bottom', stage
        assert read['pull-coord1-geometry'] == 'direction', stage
        assert read['pull-coord1-vec'].split() == ['0', '0', '1'], stage
        assert float(read['pull-coord1-init']) == pytest.approx(2.52078), stage
        assert float(read['pull-coord1-k']) == pytest.approx(1000.0), stage
        assert read['pull-coord1-rate'] == '0', stage


def test_the_restraint_needs_two_groups_because_the_probe_says_one_is_refused():
    """`pull-coord1-groups should contain 2 pull group indices with geometry`, from grompp on 2026-10-06. The second
    is a reference at the box centre, and the builder's job is to make that name true."""
    read = settings(osmotic_mdp.osmotic_mdps(temperature=308.15, solute_group='MALTOSE',
                                            reference_group='CENTRE')['production'])

    assert read['pull-ngroups'] == '2'
    assert read['pull-coord1-groups'].split() == ['1', '2']
    assert read['pull-group1-name'] == 'MALTOSE'
    assert read['pull-group2-name'] == 'CENTRE'


def test_the_temperature_is_the_dataset_s_and_has_no_default():
    """308.15 K is maltose's, from Ebrahimi & Sadeghi 2016. A default would apply one dataset's temperature to
    another molecule's series and nothing in the output would say so."""
    with pytest.raises(TypeError):
        osmotic_mdp.osmotic_mdps()

    mdps = osmotic_mdp.osmotic_mdps(temperature=308.15)
    for stage in ('equilibration', 'production'):
        read = settings(mdps[stage])
        assert float(read['ref_t']) == pytest.approx(308.15)
        assert float(read['gen-temp']) == pytest.approx(308.15)


def test_each_stage_s_own_dt_turns_the_duration_into_its_step_count():
    mdps = osmotic_mdp.osmotic_mdps(temperature=308.15, equilibration_ps=10000.0, production_ps=500000.0)

    equilibration = settings(mdps['equilibration'])
    production = settings(mdps['production'])
    assert float(equilibration['dt']) == pytest.approx(0.005)
    assert int(equilibration['nsteps']) * 0.005 == pytest.approx(10000.0)
    assert float(production['dt']) == pytest.approx(0.02)
    assert int(production['nsteps']) * 0.02 == pytest.approx(500000.0)


def test_the_default_production_is_the_papers_five_hundred_nanoseconds():
    production = settings(osmotic_mdp.osmotic_mdps(temperature=308.15)['production'])

    assert int(production['nsteps']) * float(production['dt']) == pytest.approx(500000.0)
    assert osmotic_mdp.DEFAULT_PRODUCTION_PS == pytest.approx(500000.0)


def test_a_setup_check_can_run_five_nanoseconds_of_the_same_system():
    """The tier exists: a setup check must be able to run the same mdps short, so the duration is a parameter."""
    text = osmotic_mdp.osmotic_mdps(temperature=308.15, production_ps=5000.0)['production']

    assert int(settings(text)['nsteps']) * 0.02 == pytest.approx(5000.0)


def test_the_output_interval_divides_the_duration_exactly():
    """GROMACS would simply write the frames that fit. Two conditions with different effective averaging windows are
    not comparable, which is what makes this worth refusing."""
    with pytest.raises(ValueError, match='whole number'):
        osmotic_mdp.osmotic_mdps(temperature=308.15, production_ps=5005.0, output_interval_ps=10.0)
    with pytest.raises(ValueError, match='shorter than its output interval'):
        osmotic_mdp.osmotic_mdps(temperature=308.15, production_ps=5.0, output_interval_ps=10.0)
    with pytest.raises(ValueError, match='positive'):
        osmotic_mdp.osmotic_mdps(temperature=308.15, output_interval_ps=0.0)


def test_the_trajectory_is_written_often_enough_to_average_a_force_over():
    """The analysis recomputes the force from the trajectory, so the frame interval is what sets the sample size.
    500 ns at 10 ps is fifty thousand frames; at 1 ns it would be five hundred.

    `nstxtcout` is a *step* count, so the interval it implies is `nstxtcout * dt`. This test used to write
    `duration / nstxtcout`, which is a frame interval only if the step count were a frame count -- and that division
    returns 10 for exactly the numbers the buggy code produced. It passed while the run would have written one frame
    per nanosecond, and it would have blocked the fix.
    """
    production = settings(osmotic_mdp.osmotic_mdps(temperature=308.15)['production'])

    dt = float(production['dt'])
    interval_ps = int(production['nstxtcout']) * dt
    assert interval_ps == pytest.approx(10.0)
    assert int(production['nsteps']) * dt == pytest.approx(500000.0)
    assert int(production['nsteps']) / int(production['nstxtcout']) == 50000


def test_the_confinement_constants_are_the_papers_and_are_overridable_only_on_purpose():
    assert osmotic_mdp.DEFAULT_CONFINEMENT_NM == pytest.approx(2.52078)
    assert osmotic_mdp.DEFAULT_CONFINEMENT_KJ_MOL_NM2 == pytest.approx(1000.0)

    block = '\n'.join(osmotic_mdp.restraint_block(confinement_nm=1.0, force_constant=5.0))
    assert 'pull-coord1-init        = 1' in block
    assert 'pull-coord1-k           = 5' in block


def test_the_reference_bead_is_frozen_in_every_stage():
    """It defines the coordinate's origin, so it must not move: a spring would let it drift, and that drift would be
    indistinguishable from an osmotic pressure. The group name comes from the index file the build writes."""
    mdps = osmotic_mdp.osmotic_mdps(temperature=308.15)

    for stage, text in mdps.items():
        read = settings(text)
        assert read['freezegrps'] == 'REFERENCE', stage
        assert read['freezedim'] == 'Y Y Y', stage


def test_every_line_is_a_comment_a_blank_or_a_key_value():
    """An mdp that GROMACS would reject is not worth writing, and the cheapest way to know is to look."""
    for stage, text in osmotic_mdp.osmotic_mdps(temperature=308.15).items():
        for number, line in enumerate(text.splitlines(), start=1):
            stripped = line.split(';', 1)[0].strip()
            assert not stripped or '=' in stripped, f'{stage}:{number}: {line!r}'
            assert not re.search(r'\s;', line.split(';')[0] + ' '), f'{stage}:{number}: {line!r}'
