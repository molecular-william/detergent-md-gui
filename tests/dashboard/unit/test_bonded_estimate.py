"""The equipartition estimator as arithmetic, on values a person can check by hand.

The reference pinning against shaker's own numbers is `test_bonded_estimate_reference.py`; this file is the arithmetic
underneath it, so a factor-of-3283 error and a circular-mean error each fail here first.
"""
import json

import MDAnalysis as mda
import numpy as np
import pytest
from dashboard.analysis import worker
from dashboard.analysis.runs import bonded_estimate


def test_a_known_spread_gives_the_equipartition_force_constant():
    """Hand-computed: R T at 300 K is 2494.34 J/mol = 2.49434 kJ/mol, and sigma is 0.1 nm, so k = 2.49434/0.01."""
    assert bonded_estimate.force_constant(0.1, 300.0, kind='bond') == pytest.approx(249.434, rel=1e-5)


def test_an_angle_spread_in_degrees_is_converted_before_the_division():
    """GROMACS writes the angle in degrees and the constant per radian. Skipping the conversion is a factor of
    (180/pi)^2 -- about 3283 -- and the result still looks like a force constant.

    The expected value is built from the module's own R, which `test_a_known_spread_...` pins by hand; what this test
    pins is the conversion, so it must not also carry a truncated R of its own.
    """
    expected = bonded_estimate.R_GAS * 300.0 / 1000.0 / np.radians(5.0) ** 2
    assert bonded_estimate.force_constant(5.0, 300.0, kind='angle') == pytest.approx(expected, rel=1e-12)
    assert bonded_estimate.force_constant(5.0, 300.0, kind='angle') == pytest.approx(327.54, rel=1e-3)


def test_a_zero_spread_is_refused_rather_than_answered_with_an_infinity():
    with pytest.raises(ValueError, match='constraint'):
        bonded_estimate.force_constant(0.0, 303.15, kind='bond')


def test_one_frame_is_refused_because_a_spread_needs_two():
    with pytest.raises(ValueError, match='two frames'):
        bonded_estimate.estimate_bond([0.27], 303.15)
    with pytest.raises(ValueError, match='two frames'):
        bonded_estimate.estimate_angle([145.0], 303.15)


def test_a_bond_reports_its_length_its_spread_and_its_constant():
    # A spread of 0.02 nm at 303 K is k near 6300, which is a flexible spring under this repository's threshold --
    # not the near-zero spread a synthetic sample accidentally has, which would honestly read as a constraint.
    lengths = [0.24, 0.27, 0.30, 0.27, 0.26, 0.28]
    estimate = bonded_estimate.estimate_bond(lengths, 303.15)

    assert estimate['value'] == pytest.approx(np.mean(lengths))
    assert estimate['sigma'] == pytest.approx(np.std(lengths, ddof=1))
    assert estimate['sigma'] == pytest.approx(0.02, abs=1e-6)
    assert estimate['sigma_units'] == 'nm' and estimate['force_constant_units'] == 'kJ/mol/nm^2'
    assert estimate['force_constant'] == pytest.approx(
        bonded_estimate.force_constant(estimate['sigma'], 303.15, kind='bond'))
    assert estimate['force_constant'] == pytest.approx(6301.0, rel=1e-3)
    assert estimate['frames'] == 6
    assert estimate['constraint'] is False


def test_the_threshold_is_the_repositorys_own_and_shaker_s_is_recorded_beside_it():
    """It is a parameter because the two conventions disagree about a real molecule: DDM's inter-ring link fitted
    near 12965, which is a rigid constraint at 10000 and a flexible spring at shaker's 25000."""
    assert bonded_estimate.DEFAULT_CONSTRAINT_THRESHOLD == 10000.0
    documentation = bonded_estimate.__doc__ or ''
    assert '25000' in documentation and '-constraints 10000' in documentation
    assert '12965' in documentation


def test_a_rigid_link_and_a_soft_one_are_told_apart_by_the_threshold():
    """The same measurement, read two ways: this is why the threshold cannot be a hidden default.

    A spread of 0.015 nm puts k near 11100 -- above this repository's 10000 and below shaker's 25000, so the two
    conventions disagree about the same frames. DDM's inter-ring link sits the same way at 12965.
    """
    stiff = [0.272 + offset for offset in (0.013, -0.013, 0.013, -0.013)]

    ours = bonded_estimate.estimate_bond(stiff, 303.15, constraint_threshold=10000)
    shakers = bonded_estimate.estimate_bond(stiff, 303.15, constraint_threshold=25000)

    assert ours['value'] == pytest.approx(shakers['value'])
    assert ours['force_constant'] == pytest.approx(shakers['force_constant'])
    assert ours['force_constant'] == pytest.approx(11185.0, rel=1e-3)
    assert ours['constraint'] is True and shakers['constraint'] is False


def test_an_angle_crossing_the_period_is_averaged_around_the_circle():
    """+179 and -179 are two degrees apart. The arithmetic mean puts them at 0 -- the far side of the circle -- and
    reports a wildly stretched term for a molecule that never moved."""
    angles = [179.0, -179.0, 178.0, -178.0, 180.0, -180.0]

    estimate = bonded_estimate.estimate_angle(angles, 303.15)

    assert abs(estimate['value']) == pytest.approx(180.0, abs=1.0)
    assert estimate['sigma'] < 5.0, estimate
    # And the force constant is the soft one a nearly rigid geometry implies, not the stiff one a 180-degree spread
    # would give.
    assert estimate['force_constant'] > 1000.0


def test_the_circular_spread_matches_the_arithmetic_one_when_nothing_is_wrapped():
    """Away from the period the two definitions have to agree, or the circular one is doing something other than
    what it says."""
    angles = [100.0, 101.0, 102.0, 103.0, 104.0]

    value, spread = bonded_estimate.circular_mean_and_spread(angles)

    assert value == pytest.approx(np.mean(angles), abs=1e-9)
    assert spread == pytest.approx(0.0, abs=1e-9) or spread < 2.0, spread


# --- the fitted topology, and the comparison against it ------------------------------------------------------

TOPOLOGY = """\
; a fitted topology, the shape Fast_Forward writes
[ bonds ]
1 2 1 0.200 5000.0
1 3 1 0.550 4000.0
[ constraints ]
2 3 1 0.330
[ angles ]
2 1 3 1 120.0 25.0
"""


def _mapped_run(tmp_path, *, topology: str | None = TOPOLOGY, name: str = 'DDM_ff_inter.itp'):
    """A work directory with the mapped trajectory and one topology, laid out as the worker stages them.

    B01 sits at the origin, B02 moves between 0.20 and 0.24 nm, and B03 sits still at 0.55 -- so the pair B01-B02 has
    a real spread, B01-B03 has none, and B02-B03 inherits B02's movement. Four frames of a 0.04 nm oscillation give
    sigma = 0.023094 nm with the sample (ddof=1) definition, so k = 4725.8.
    """
    work = tmp_path / 'work'
    (work / '3_initial_CG').mkdir(parents=True)
    (work / '2_mapping').mkdir(parents=True)
    if topology is not None:
        (work / '3_initial_CG' / name).write_text(topology)
    length = 4
    identity = np.repeat(np.arange(length), 3)
    universe = mda.Universe.empty(length * 3, n_residues=length, atom_resindex=identity, trajectory=True)
    universe.add_TopologyAttr('names', (['B01', 'B02', 'B03'] * length))
    universe.add_TopologyAttr('resnames', ['DDM'] * length)
    universe.add_TopologyAttr('resids', np.arange(1, length + 1))
    with mda.Writer(str(work / '2_mapping' / 'mapped.xtc'), n_atoms=length * 3) as writer:
        for frame, second in enumerate((0.20, 0.24, 0.20, 0.24)):
            positions = np.tile(np.array([[0.0, 0.0, 0.0], [second, 0.0, 0.0], [0.55, 0.0, 0.0]]), (length, 1))
            universe.atoms.positions = positions * 10.0  # written in angstroms, like a real trajectory
            universe.trajectory.ts.time = float(frame)
            if frame == 0:
                universe.atoms.write(str(work / '2_mapping' / 'mapped.gro'))
            writer.write(universe.atoms)
    return work


def test_a_topology_is_read_section_by_section_and_only_for_what_it_declares():
    """Bonds and constraints only, and the section matters: the same two indices are a spring in one section and a
    rigid rod in the other, and the comparison has to carry which it read."""
    terms = bonded_estimate.parse_topology_terms(TOPOLOGY)

    assert [(term['kind'], term['atoms']) for term in terms] == [
        ('bond', (1, 2)), ('bond', (1, 3)), ('constraint', (2, 3))]
    assert terms[0]['value'] == pytest.approx(0.200) and terms[0]['force_constant'] == pytest.approx(5000.0)
    # A constraint carries a length and no force constant, because a rigid rod has none.
    assert terms[2]['force_constant'] is None and terms[2]['value'] == pytest.approx(0.330)
    # The angle is not read here, and is not read as a bond either.
    assert all(term['kind'] != 'angle' for term in terms)


def test_a_non_harmonic_function_type_is_refused_rather_than_read_as_a_length():
    """`funct 2` is a GROMACS cubic bond: its third field is not a length, and reading it as one would put a
    meaningless number next to a real one in the comparison."""
    with pytest.raises(ValueError, match='not harmonic'):
        bonded_estimate.parse_topology_terms('[ bonds ]\n1 2 2 0.3 5000 1.0\n')


def test_a_topology_line_with_too_few_fields_is_refused():
    with pytest.raises(ValueError, match='needs 5 fields'):
        bonded_estimate.parse_topology_terms('[ bonds ]\n1 2 1 0.3\n')


def test_the_cross_check_compares_our_fit_with_the_estimate_term_by_term(tmp_path):
    """Hand-checkable: B01-B02 measures 0.22 nm with a 0.023094 nm spread, so k = 4725.8, against our fit's 0.200/5000."""
    work = _mapped_run(tmp_path)

    record = bonded_estimate.cross_check(work, {'temperature': 303.15})

    assert record['molecule'] == 'DDM'
    assert record['threshold'] == 10000.0
    assert record['frames_measured'] == 4 and record['frames_in_trajectory'] == 4
    assert record['ours_from'] == '3_initial_CG/DDM_ff_inter.itp'
    assert 'Fast_Forward' in record['ours_provenance']
    assert 'equipartition' in record['estimate_provenance']

    by_pair = {tuple(row['beads']): row for row in record['rows']}
    assert set(by_pair) == {('B01', 'B02'), ('B02', 'B03')}, by_pair
    measured = by_pair[('B01', 'B02')]
    assert measured['ours'] == {'value': 0.200, 'force_constant': 5000.0, 'constraint': False}
    assert measured['estimate']['value'] == pytest.approx(0.22)
    assert measured['estimate']['sigma'] == pytest.approx(0.023094, rel=1e-4)
    assert measured['estimate']['force_constant'] == pytest.approx(4725.8, rel=1e-3)
    assert measured['delta_value'] == pytest.approx(0.02)
    assert measured['ratio_force_constant'] == pytest.approx(0.94516, rel=1e-3)
    assert measured['verdicts_agree'] is True

    # (work / bonded_estimate.REPORT) is the published artifact, and it is the same record.
    assert json.loads((work / bonded_estimate.REPORT).read_text())['rows'] == record['rows']


def test_a_term_the_fit_wrote_as_a_constraint_and_the_measurement_reads_as_a_spring_is_named(tmp_path):
    """This is the DDM ring-1 shape: the same pair, two verdicts. The numbers alone do not show it and the report has
    to, because a rigid rod and a soft spring are different molecules."""
    work = _mapped_run(tmp_path)

    record = bonded_estimate.cross_check(work)

    row = next(row for row in record['rows'] if tuple(row['beads']) == ('B02', 'B03'))
    assert row['ours']['constraint'] is True and row['estimate']['constraint'] is False
    assert row['verdicts_agree'] is False
    assert record['disagreements'] == [['B02', 'B03']]
    assert any('different molecule' not in line for line in record['limitations'])  # limitations are its own text
    assert any('same mapped frames' in line for line in record['limitations'])
    assert any('angle' in line for line in record['limitations'])


def test_a_term_with_no_measurable_spread_is_listed_rather_than_dropped(tmp_path):
    """B01-B03 is 0.55 nm in every frame, so it has no spread and no equipartition constant. Dropping it would hide
    a term the fit declares; reporting it as zero spread tells the reader what was found."""
    work = _mapped_run(tmp_path)

    record = bonded_estimate.cross_check(work)

    assert [entry['beads'] for entry in record['unmeasured']] == [['B01', 'B03']]
    entry = record['unmeasured'][0]
    assert entry['value'] == pytest.approx(0.550)
    assert 'spread of zero' in entry['reason'], entry


def test_when_no_fit_has_run_the_draft_answers_and_says_so(tmp_path):
    """A run whose fit stage was skipped still has a topology, and the report must not present the draft as a fit."""
    work = _mapped_run(tmp_path, topology=TOPOLOGY.replace('1 2 1 0.200 5000.0', '1 2 1 0.205 4800.0'),
                       name='DDM_initial.itp')

    record = bonded_estimate.cross_check(work)

    assert record['ours_from'] == '3_initial_CG/DDM_initial.itp'
    assert 'draft' in record['ours_provenance']
    assert record['rows'][0]['ours']['force_constant'] == pytest.approx(4800.0)


def test_a_run_with_neither_a_fit_nor_a_draft_is_refused(tmp_path):
    work = _mapped_run(tmp_path, topology=None)

    with pytest.raises(ValueError, match='neither a fit nor a draft'):
        bonded_estimate.cross_check(work)


def test_the_cross_check_kind_is_registered_in_all_four_places():
    """One row holds all four: the name, the sources, the dispatch and the description.

    This used to assert the kind separately in `worker.KINDS`, in `worker.PATTERNS`, in `metadata.DESCRIPTIONS` and as
    an `elif kind == ...` line in the worker's own source -- four places to keep in step, where a kind missing the last
    one was accepted by the queue and then produced nothing at all, which reads as a stuck worker rather than a missing
    line. The row is the same claim with one thing to keep right, and `row.run` is what the dispatch arm used to be.
    """
    from dashboard.analysis.kinds import TABLE
    row = TABLE['bonded-cross-check']
    assert 'bonded-cross-check' in worker.KINDS and row.name == 'bonded-cross-check'
    assert list(row.sources) == [
        '2_mapping/mapped.gro', '2_mapping/mapped.xtc', '2_mapping/model.json',
        '3_initial_CG/*_ff_inter.itp', '3_initial_CG/*initial*.itp']
    assert callable(row.run), 'the dispatch is the row'
    assert row.title != 'Bonded Cross Check', 'a title the code invents is the fallback this replaced'
