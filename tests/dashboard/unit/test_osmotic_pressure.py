"""The osmotic pressure arithmetic, checked against the paper's own numbers rather than against itself.

Two halves. The first is the validation leg's: a series of points is complete or it is not, and an evidence-tier
series needs the paper's five hundred nanoseconds and a target with an uncertainty. The second is the *measurement*,
which the paper's method defines as arithmetic over the trajectory -- "the force was recomputed from the trajectory"
-- and whose inputs are checked against numbers that came from somewhere else: the paper prints 13.04 bar at 0.5
molal, the box is the paper's, and PLUMED's own `KAPPA` is a measurement of this engine rather than a convention.
"""
import pytest

from dashboard.analysis.runs import osmotic_pressure as op
from dashboard.analysis.validation.osmotic import pressure_from_force, validate_series

#: Ebrahimi & Sadeghi 2016, the paper's own box: 5.04156 x 5.04156 x 10.08312 nm, so the dividing area is the xy face.
BOX_NM = (5.04156, 5.04156, 10.08312)
AREA_NM2 = BOX_NM[0] * BOX_NM[1]
CENTRE_NM = BOX_NM[2] / 2
HALF_NM = BOX_NM[2] / 4
PAPER_FORCE_CONSTANT = 1000.0


def test_pressure_from_force_uses_area_and_finite_units():
    assert pressure_from_force(10.0, 2.0) == pytest.approx(5.0)
    with pytest.raises(ValueError, match='area'):
        pressure_from_force(1.0, 0.0)


def test_series_marks_missing_concentration_incomplete():
    result = validate_series([{'molal': 0.0}, {'molal': 2.5}], 'evidence')
    assert result['complete'] is False
    assert result['missing']


def test_setup_series_can_be_short_but_remains_diagnostic():
    result = validate_series([{'molal': 0.0, 'duration_ns': 1}], 'setup')
    assert result['diagnostic_only'] is True


def test_evidence_series_requires_target_values():
    result = validate_series([{
        'molal': molal, 'duration_ns': 500, 'flat_bottom_restraint': True,
        'pressure_coupling': 'z', 'target_pressure': 1.0, 'target_uncertainty': 0.1,
    } for molal in (0, 0.5, 1, 1.5, 2, 2.5)], 'evidence')
    assert result['complete'] is True


def test_the_conversion_is_the_one_a_pressure_needs():
    """1 kJ/mol/nm3 is 1e30 J/mol/m3, and per molecule that is 1.6605e6 Pa -- 16.605 bar.

    This is the only place a factor of 1e5 or of Avogadro can hide in the measurement, so it is written as itself.
    """
    assert op.KJ_MOL_NM2_TO_BAR == pytest.approx(16.6054, rel=1e-4)
    assert op.pressure_bar(1.0, 1.0) == pytest.approx(16.6054, rel=1e-4)


def test_the_paper_s_number_comes_back_out_of_the_arithmetic():
    """The round trip that has to hold before any measurement is believed: the paper's 13.04 bar at 0.5 molal.

    13.04 bar over this box's dividing area is 0.7852 kJ/mol/nm2 of wall force; computing the pressure back from it
    must return the paper's number. If the conversion or the area were wrong by any factor, this is where it shows.
    """
    force = 13.04 / op.KJ_MOL_NM2_TO_BAR * AREA_NM2
    assert op.pressure_bar(force, AREA_NM2) == pytest.approx(13.04, rel=1e-9)
    # 13.04 bar is a *pressure*, and 0.7852 is that pressure once the area is divided out -- kJ/mol/nm2, which is
    # not the force. The force is that times the area, about 19.96 kJ/mol/nm. This assertion first said 0.7852 for
    # the force, which is a unit confusion inside the test rather than in the module.
    assert 13.04 / op.KJ_MOL_NM2_TO_BAR == pytest.approx(0.7852, rel=1e-3)
    assert force == pytest.approx(19.96, rel=1e-2)


def test_a_molecule_inside_the_flat_region_pushes_on_neither_wall():
    """The paper's flat bottom: "within 2.52078 nm of the centre", nothing. The mean force is an average over the
    rare excursions that reach a wall -- a quantity with a sample size, rather than a constant."""
    assert op.wall_force_kj_nm(CENTRE_NM, centre_nm=CENTRE_NM, half_width_nm=HALF_NM,
                               force_constant_kj_mol_nm2=PAPER_FORCE_CONSTANT) == (0.0, 0.0)
    assert op.wall_force_kj_nm(CENTRE_NM + HALF_NM - 1e-9, centre_nm=CENTRE_NM, half_width_nm=HALF_NM,
                               force_constant_kj_mol_nm2=PAPER_FORCE_CONSTANT) == (0.0, 0.0)


def test_a_molecule_beyond_a_wall_pushes_on_that_wall_and_not_the_other():
    """One wall's load at a time, proportional to the excursion -- the paper's 1000 kJ/mol/nm2."""
    excursion = 0.4
    up, down = op.wall_force_kj_nm(CENTRE_NM + HALF_NM + excursion, centre_nm=CENTRE_NM, half_width_nm=HALF_NM,
                                   force_constant_kj_mol_nm2=PAPER_FORCE_CONSTANT)
    assert (up, down) == (pytest.approx(PAPER_FORCE_CONSTANT * excursion), 0.0)

    up, down = op.wall_force_kj_nm(CENTRE_NM - HALF_NM - excursion, centre_nm=CENTRE_NM, half_width_nm=HALF_NM,
                                   force_constant_kj_mol_nm2=PAPER_FORCE_CONSTANT)
    assert (up, down) == (0.0, pytest.approx(PAPER_FORCE_CONSTANT * excursion))


def test_a_force_and_an_area_from_different_runs_are_refused_and_both_are_named():
    """The failure this refusal exists for: two numbers that each came from a real run and together mean nothing."""
    with pytest.raises(ValueError) as refusal:
        op.divide(1.0, AREA_NM2, force_run_id='3767b3975adc', area_run_id='a557054e5b51')
    assert '3767b3975adc' in str(refusal.value)
    assert 'a557054e5b51' in str(refusal.value)


def test_the_same_run_s_force_and_area_divide():
    assert op.divide(1.0, AREA_NM2, force_run_id='x', area_run_id='x') == pytest.approx(op.pressure_bar(1.0, AREA_NM2))


def test_the_walls_are_read_from_the_file_the_simulation_ran_with(tmp_path):
    """The grouping is not re-derived: it is read out of the run's own `plumed.dat`, so the analysis and the walls
    cannot disagree about what a molecule is. The centre and the constant come from the same file for the same
    reason -- two definitions of either would be a silent disagreement."""
    (tmp_path / op.WALLS).write_text(
        '# The box centre is z = 5.04156 nm, so the walls sit at 2.52078 and 7.56234.\n'
        'UNITS LENGTH=nm ENERGY=kj/mol TIME=ps\n'
        '\n'
        'm1: COM ATOMS=1,2,3,4\n'
        'm2: COM ATOMS=5,6,7,8\n'
        'm3: COM ATOMS=9,10,11,12\n'
        '\n'
        'upper1: UPPER_WALLS ARG=m1.z AT=7.56234 KAPPA=500 EXP=2 EPS=1 OFFSET=0\n'
        'lower1: LOWER_WALLS ARG=m1.z AT=2.52078 KAPPA=500 EXP=2 EPS=1 OFFSET=0\n'
        'upper2: UPPER_WALLS ARG=m2.z AT=7.56234 KAPPA=500 EXP=2 EPS=1 OFFSET=0\n'
        'lower2: LOWER_WALLS ARG=m2.z AT=2.52078 KAPPA=500 EXP=2 EPS=1 OFFSET=0\n'
        'upper3: UPPER_WALLS ARG=m3.z AT=7.56234 KAPPA=500 EXP=2 EPS=1 OFFSET=0\n'
        'lower3: LOWER_WALLS ARG=m3.z AT=2.52078 KAPPA=500 EXP=2 EPS=1 OFFSET=0\n')

    walls = op.read_walls(tmp_path / op.WALLS)

    assert walls['molecules'] == [[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12]]
    assert walls['centre_nm'] == pytest.approx(5.04156)
    assert walls['upper_nm'] == pytest.approx(7.56234)
    assert walls['kappa_kj_mol_nm2'] == pytest.approx(500.0)
    # The walls sit where the centre and the half-width say: the file's own two statements have to agree, and the
    # measurement's `half` comes from the condition record rather than from here.
    assert walls['upper_nm'] - walls['centre_nm'] == pytest.approx(HALF_NM, abs=1e-5)


def test_a_run_that_confines_nothing_is_refused_rather_than_zeroed(tmp_path):
    """A file with no molecule in it would produce a force of zero and a pressure that looks like a measurement."""
    (tmp_path / op.WALLS).write_text('# The box centre is z = 5.04156 nm\nUNITS LENGTH=nm\n'
                                     'upper1: UPPER_WALLS ARG=m1.z AT=7.56234 KAPPA=500 EXP=2\n')

    with pytest.raises(ValueError, match='no solute molecule'):
        op.read_walls(tmp_path / op.WALLS)


def test_a_wall_file_without_its_centre_is_refused(tmp_path):
    """The centre, the wall and the constant are all needed; a missing one is not defaulted, because a defaulted
    centre is a pressure computed about the wrong plane."""
    (tmp_path / op.WALLS).write_text('UNITS LENGTH=nm\nm1: COM ATOMS=1,2\n'
                                     'upper1: UPPER_WALLS ARG=m1.z AT=7.56234 KAPPA=500 EXP=2\n')

    with pytest.raises(ValueError, match='box centre'):
        op.read_walls(tmp_path / op.WALLS)


def test_measure_returns_the_force_the_frames_imply(tmp_path):
    """The units, end to end, on a system whose answer is known by hand.

    One molecule sits beyond the upper wall and one beyond the lower, each by the same excursion, so the two walls
    carry equal loads of `1000 * excursion` and a slab in the middle. The mean force is therefore that excursion's
    force and `symmetry` is 1.0 -- a one-sided system would halve it, which is the failure the symmetry guard exists
    to catch rather than to compute through.

    This is the test the module needed and did not have: the first version multiplied Angstroms by ten where it
    should have divided and its own comment said "Angstrom -> nm", so every other check in this file agreed with a
    force a hundred times too large. MDAnalysis reads a .gro in Angstroms, the walls are in nm, and this is where
    the two meet.
    """
    import MDAnalysis as mda

    excursion = 0.43766
    deep, high = CENTRE_NM - HALF_NM - excursion, CENTRE_NM + HALF_NM + excursion
    (tmp_path / 'prod').mkdir()
    side = CENTRE_NM
    (tmp_path / op.STRUCTURE[0]).write_text(
        'a test system\n'
        '    4\n'
        f'{1:5d}{"MOL1":<5s}{"B01":>5s}{1:5d}{side:8.3f}{side:8.3f}{deep - 0.1:8.3f}\n'
        f'{1:5d}{"MOL1":<5s}{"B02":>5s}{2:5d}{side:8.3f}{side:8.3f}{deep + 0.1:8.3f}\n'
        f'{2:5d}{"MOL2":<5s}{"B01":>5s}{1:5d}{side:8.3f}{side:8.3f}{high - 0.1:8.3f}\n'
        f'{2:5d}{"MOL2":<5s}{"B02":>5s}{2:5d}{side:8.3f}{side:8.3f}{high + 0.1:8.3f}\n'
        f'{BOX_NM[0]:9.5f}{BOX_NM[1]:9.5f}{BOX_NM[2]:9.5f}\n')
    (tmp_path / op.WALLS).write_text(
        f'# The box centre is z = {CENTRE_NM} nm, so the walls sit at {CENTRE_NM - HALF_NM} and {CENTRE_NM + HALF_NM}.\n'
        'UNITS LENGTH=nm ENERGY=kj/mol TIME=ps\n'
        'm1: COM ATOMS=1,2\n'
        'm2: COM ATOMS=3,4\n'
        f'upper1: UPPER_WALLS ARG=m1.z AT={CENTRE_NM + HALF_NM:g} KAPPA=500 EXP=2 EPS=1 OFFSET=0\n'
        f'lower1: LOWER_WALLS ARG=m1.z AT={CENTRE_NM - HALF_NM:g} KAPPA=500 EXP=2 EPS=1 OFFSET=0\n'
        f'upper2: UPPER_WALLS ARG=m2.z AT={CENTRE_NM + HALF_NM:g} KAPPA=500 EXP=2 EPS=1 OFFSET=0\n'
        f'lower2: LOWER_WALLS ARG=m2.z AT={CENTRE_NM - HALF_NM:g} KAPPA=500 EXP=2 EPS=1 OFFSET=0\n')
    (tmp_path / op.MANIFEST).write_text(
        '{"dividing_area_nm2": %r, "confinement_nm": %r}\n' % (AREA_NM2, HALF_NM))
    universe = mda.Universe(str(tmp_path / op.STRUCTURE[0]))
    with mda.Writer(str(tmp_path / op.TRAJECTORY[0]), universe.atoms.n_atoms) as writer:
        for _ in range(2):
            writer.write(universe.atoms)

    measured = op.measure(tmp_path)

    # A .gro is written to three decimals, so the centre of mass of two beads 0.2 nm apart is the intended value to
    # within the file's own precision rather than exactly it: 437.78 against 437.66 is 0.03%, and the first version
    # of this assertion was tight enough to fail on it.
    assert measured['frames'] == 2
    assert measured['molecules'] == 2
    assert measured['upper_force_kj_nm'] == pytest.approx(PAPER_FORCE_CONSTANT * excursion, rel=5e-4)
    assert measured['lower_force_kj_nm'] == pytest.approx(PAPER_FORCE_CONSTANT * excursion, rel=5e-4)
    assert measured['force_kj_nm'] == pytest.approx(PAPER_FORCE_CONSTANT * excursion, rel=5e-4)
    # Two walls, each carrying the whole pressure, is the symmetry a real slab has. A one-sided reading halves the
    # mean, and `symmetry` is the number that says so.
    assert measured['symmetry'] == pytest.approx(1.0, rel=1e-3)
    assert measured['pressure_bar'] == pytest.approx(
        PAPER_FORCE_CONSTANT * excursion / AREA_NM2 * op.KJ_MOL_NM2_TO_BAR, rel=5e-4)


def test_the_kind_is_registered_in_all_four_places():
    """A kind missing the fourth is accepted by the queue and then produces nothing -- learned here the hard way, so
    the four are asserted together rather than discovered one at a time as each failure surfaces.

    The fourth is the dispatch arm, which used to have no name to look up -- its source was read for the branch, a
    text check that a comment can fool. It is `row.run` now, so the arm is compared with the function it must be.
    """
    from dashboard.analysis import worker
    from dashboard.analysis.kinds import TABLE

    row = TABLE['osmotic-pressure']
    assert 'osmotic-pressure' in worker.KINDS and row.name == 'osmotic-pressure'
    assert list(row.sources) == ['01_simulate/osmotic_condition.json', '01_simulate/plumed.dat',
                                 '01_simulate/solvated.gro', '01_simulate/prod/md_whole.xtc']
    note, units = row.ideal_result, row.units_or_direction
    assert 'bar' in units
    assert 'converged' in note
    # The arm is the function it has to be, compared rather than read out of a source file. A dispatch that names a
    # module the worker cannot import is the failure this catches, and comparing the callable catches it exactly.
    from dashboard.analysis.runs import osmotic_pressure
    assert row.run is osmotic_pressure.publish
