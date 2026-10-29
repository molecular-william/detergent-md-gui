"""The dihedral fit, on inputs whose answers can be checked by hand.

The decisive test is the round trip: a potential that *is* two cosines must come back as those two cosines with those
amplitudes and phases, because every step of the workflow -- histogram, inversion, smoothing, series -- is invertible
in that direction. A factor-of-57 error in the degrees/radians conversion survives every test that only looks at the
residual, and dies here.
"""
import json
import math

import MDAnalysis as mda
import numpy as np
import pytest
from dashboard.analysis import worker
from dashboard.analysis.runs import dihedral_fit

R_GAS = dihedral_fit.R_GAS


def _two_cosine_potential(angles_deg):
    """8(1 + cos(2 phi - 0.5)) + 3(1 + cos(3 phi + 1.0)), in kJ/mol, as a function of degrees."""
    phi = np.radians(np.asarray(angles_deg, dtype=float))
    return 8.0 * (1.0 + np.cos(2 * phi - 0.5)) + 3.0 * (1.0 + np.cos(3 * phi + 1.0))


def _frames_from(potential, temperature, *, count=40000, seed=20261005):
    """Angles drawn from p(phi) proportional to exp(-F(phi)/RT), by sampling a fine grid with those weights.

    This is the exact inverse of the inversion the fit performs, which is what makes it an input with a known answer.
    """
    grid = np.linspace(-180.0, 180.0, 3601)[:-1]
    weights = np.exp(-potential(grid) / (R_GAS * temperature / 1000.0))
    weights /= weights.sum()
    return np.random.default_rng(seed).choice(grid, size=count, p=weights)


# --- the smoothing -------------------------------------------------------------------------------------------


def test_a_first_order_window_leaves_a_straight_line_alone():
    """A polynomial window of order one fits a line exactly, at the edges as well as in the interior -- which is the
    property that makes an edge treatment honest rather than an extrapolation."""
    line = np.linspace(-5.0, 5.0, 41)

    smoothed = dihedral_fit.savitzky_golay(line, window=7, order=1)

    assert smoothed == pytest.approx(line, abs=1e-9)


def test_a_zeroth_order_window_is_a_moving_average_away_from_the_edges():
    """Order zero is a plain window mean. The edges truncate the window instead of reaching beyond the data, so they
    are excluded here rather than asserted against a differently-weighted number."""
    values = np.array([1.0, 2.0, 9.0, 4.0, 5.0, 6.0, 7.0])

    smoothed = dihedral_fit.savitzky_golay(values, window=3, order=0)

    assert smoothed[1:6] == pytest.approx([(1 + 2 + 9) / 3, (2 + 9 + 4) / 3, (9 + 4 + 5) / 3,
                                           (4 + 5 + 6) / 3, (5 + 6 + 7) / 3])


def test_a_window_or_an_order_the_data_cannot_carry_is_refused():
    values = np.arange(20.0)
    with pytest.raises(ValueError, match='odd'):
        dihedral_fit.savitzky_golay(values, window=8, order=2)
    with pytest.raises(ValueError, match='smaller than the window'):
        dihedral_fit.savitzky_golay(values, window=5, order=5)
    with pytest.raises(ValueError, match='cannot smooth'):
        dihedral_fit.savitzky_golay(np.arange(4.0), window=9, order=2)


# --- the inversion -------------------------------------------------------------------------------------------


def test_an_even_distribution_gives_a_flat_potential_and_no_empty_bins():
    """36 bins with ten frames each: the probability is uniform, so -R T ln p is constant."""
    bins = 36
    edges = np.linspace(-180.0, 180.0, bins + 1)
    centres = 0.5 * (edges[:-1] + edges[1:])
    frames = np.repeat(centres - 1.0, 10)  # just inside each bin, away from an edge

    pmf = dihedral_fit.inverted_boltzmann(frames, 303.15, bins=bins)

    assert pmf['empty_bins'] == 0
    assert pmf['frames'] == 360
    assert float(np.ptp(pmf['energy_kj_mol'])) == pytest.approx(0.0, abs=1e-9)
    assert float(pmf['energy_kj_mol'].min()) == pytest.approx(0.0, abs=1e-12)


def test_an_empty_bin_is_dropped_and_counted_rather_than_given_an_infinite_energy():
    """-R T ln 0 is not a large number, it is no number: one empty bin would otherwise dominate every fit."""
    frames = np.linspace(-90.0, 90.0, 900)

    pmf = dihedral_fit.inverted_boltzmann(frames, 303.15, bins=60)

    assert pmf['empty_bins'] > 0
    assert len(pmf['centres_deg']) == pmf['bins'] - pmf['empty_bins']
    assert np.isfinite(pmf['energy_kj_mol']).all()
    # The zero of a potential of mean force is a convention, so the offset it was measured against is reported --
    # and here it is computable by hand: 30 of 60 bins hold 1/30 of the frames each, so the minimum energy is
    # -R T ln(1/30), which is positive because no bin can hold more than all of them.
    assert pmf['offset_kj_mol'] == pytest.approx(dihedral_fit.R_GAS * 303.15 / 1000.0 * np.log(30.0), rel=1e-9)


# --- the series, which is the point --------------------------------------------------------------------------


def test_a_potential_made_of_two_cosines_comes_back_as_those_two_cosines():
    """The decisive arithmetic: the fit is linear in its coefficients, so an exact input must be recovered exactly."""
    angles = np.linspace(-180.0, 180.0, 721)[:-1]
    models = dihedral_fit.fit_terms(angles, _two_cosine_potential(angles), max_terms=4)

    three = next(model for model in models if model['terms'] == 3)
    assert three['multiplicities'] == [1, 2, 3]
    assert three['amplitudes'][0] == pytest.approx(0.0, abs=1e-8)   # nothing at the fundamental
    assert three['amplitudes'][1] == pytest.approx(8.0, rel=1e-8)
    assert three['amplitudes'][2] == pytest.approx(3.0, rel=1e-8)
    assert three['phases_rad'][1] == pytest.approx(0.5, abs=1e-8)
    # 3(1 + cos(3 phi + 1.0)) is 3(1 + cos(3 phi - (-1.0))), so the phase the GROMACS form wants is -1.0 rad.
    assert three['phases_rad'][2] == pytest.approx(-1.0, abs=1e-8)
    assert three['residual'] == pytest.approx(0.0, abs=1e-12)


def test_the_criterion_chooses_the_number_of_terms_the_data_needs():
    """With a little noise, so the residuals are above the machine floor: the criterion then has something real to
    weigh, and it must stop at the model that actually contains the potential rather than at the biggest one."""
    angles = np.linspace(-180.0, 180.0, 721)[:-1]
    noisy = _two_cosine_potential(angles) + np.random.default_rng(7).normal(0.0, 0.05, angles.size)

    models = dihedral_fit.fit_terms(angles, noisy, max_terms=6)

    assert [model['terms'] for model in models] == [1, 2, 3, 4, 5, 6]
    assert min(models, key=lambda model: model['bic'])['terms'] == 3
    # BIC penalises a parameter harder than AIC does, so it can never choose more terms than AIC on the same data.
    assert min(models, key=lambda model: model['aic'])['terms'] >= 3


def test_fit_dihedral_returns_gromacs_terms_with_the_phase_unit_named():
    """The end-to-end path on frames drawn from a known potential: histogram noise and smoothing make the recovery
    approximate, so the tolerances are loose and the *unit* is what is pinned exactly."""
    frames = _frames_from(_two_cosine_potential, 303.15)

    fitted = dihedral_fit.fit_dihedral(frames, 303.15)

    amplitudes = {term['multiplicity']: term['force_constant_kj_mol'] for term in fitted['dihedrals']}
    phases = {term['multiplicity']: term['phase_deg'] for term in fitted['dihedrals']}
    assert fitted['terms'] >= 2                       # a one-term model cannot hold a 2nd harmonic
    assert amplitudes[2] == pytest.approx(8.0, rel=0.35)
    assert phases[2] == pytest.approx(np.degrees(0.5), abs=25.0)
    assert all(term['phase_units'] == 'degrees' for term in fitted['dihedrals'])
    if 3 in amplitudes:
        # Only where the criterion kept the third harmonic: a factor-of-57 conversion error is nowhere near this.
        assert amplitudes[3] == pytest.approx(3.0, rel=0.6)
        assert phases[3] == pytest.approx(np.degrees(-1.0), abs=30.0)
    assert fitted['pmf']['centres_deg'][0] < -170.0 and fitted['pmf']['centres_deg'][-1] > 170.0
    assert float(min(fitted['pmf']['energy_kj_mol'])) == pytest.approx(0.0, abs=1e-12)
    assert fitted['criterion'] == 'bic' and len(fitted['models']) == 6
    assert 'shaker' in fitted['credit'] and 'CREDITS.md' in fitted['credit']
    assert 'Savitzky-Golay' in fitted['method']
    assert fitted['scientifically_validated'] is False


def test_an_unknown_criterion_is_refused_rather_than_defaulted():
    frames = _frames_from(_two_cosine_potential, 303.15, count=2000)

    with pytest.raises(ValueError, match='criterion must be one of'):
        dihedral_fit.fit_dihedral(frames, 303.15, criterion='rmsd')


def test_the_series_reproduces_the_gromacs_form_it_claims_to():
    """`k (1 + cos(n phi - phi_s))` peaks where `n phi = phi_s`, so its maximum is at `phi_s / n`, and half a period
    away from that it is zero.

    Angles are degrees and the phase is radians -- the mix this module exists to keep straight -- so the test converts
    once and passes degrees. Assuming the peak sits at `phi_s` rather than at `phi_s / n` is what made it fail first.
    """
    peak_deg = float(np.degrees(0.5 / 2))  # n = 2, so the peak is at half the phase
    angles = np.array([0.0, peak_deg, peak_deg + 90.0])  # 90 degrees is half a period of the 2nd harmonic

    values = dihedral_fit.series(angles, [4.0], [0.5], [2])

    assert values[1] == pytest.approx(8.0)
    assert values[2] == pytest.approx(0.0, abs=1e-12)
    assert values[0] == pytest.approx(4.0 * (1.0 + np.cos(-0.5)))


# --- the torsion, the declared dihedrals, and the analysis that compares them --------------------------------

DIHEDRAL_TOPOLOGY = """\
; the shape Fast_Forward writes, with one dihedral it fitted
[ dihedrals ]
1 2 3 4 1 180.0 3.5 2
"""


def _placed(torsion, *, arm=1.0):
    """Four points whose dihedral is the angle asked for, by construction.

    The 1-2 bond is the x axis, the 0th point sits perpendicular to it, and the 3rd point is that same perpendicular
    arm rotated about the axis -- which is what a dihedral measures, so the expected answer is the rotation itself and
    nothing has to be looked up. Sign included: the construction's sign is the one the module documents.
    """
    angle = np.radians(torsion)
    return (np.array([0.0, arm, 0.0]), np.array([0.0, 0.0, 0.0]), np.array([1.0, 0.0, 0.0]),
            np.array([1.0, arm * np.cos(angle), arm * np.sin(angle)]))


def test_a_torsion_is_the_rotation_between_the_two_planes():
    for torsion in (0.0, 60.0, 90.0, 180.0, -120.0, 179.0):
        assert dihedral_fit.torsion_deg(*_placed(torsion)) == pytest.approx(torsion, abs=1e-9), torsion


def test_a_declared_dihedral_is_read_with_its_phase_constant_and_multiplicity(tmp_path):
    """`i j k l funct phi_s cp mult` -- eight fields, and the order of the last three is what a reader gets wrong."""
    path = tmp_path / 'DDM_ff_inter.itp'
    path.write_text(DIHEDRAL_TOPOLOGY)

    terms = dihedral_fit.read_declared_dihedrals(path)

    assert len(terms) == 1, terms
    assert terms[0]['atoms'] == (1, 2, 3, 4)
    assert terms[0]['phase_deg'] == pytest.approx(180.0)
    assert terms[0]['force_constant'] == pytest.approx(3.5)
    assert terms[0]['multiplicity'] == 2


def test_a_dihedral_of_another_function_type_and_a_short_line_are_both_refused(tmp_path):
    """This reader's whole output is a comparison, so a number it invented would not be a small error."""
    other = tmp_path / 'other.itp'
    other.write_text('[ dihedrals ]\n1 2 3 4 3 180.0 3.5 2\n')
    with pytest.raises(ValueError, match='not a proper dihedral'):
        dihedral_fit.read_declared_dihedrals(other)

    short = tmp_path / 'short.itp'
    short.write_text('[ dihedrals ]\n1 2 3 4 1 180.0 3.5\n')
    with pytest.raises(ValueError, match='needs 8 fields'):
        dihedral_fit.read_declared_dihedrals(short)


FUNCT9_TOPOLOGY = """[ dihedrals ]
; Fast_Forward writes one harmonic per line, for the same four beads
1 2 3 4 9 180.0 3.5 2
1 2 3 4 9 90.0 0.4 4
"""


def test_a_fourier_series_dihedral_is_one_dihedral_with_its_harmonics(tmp_path):
    """funct 9 as `ff_inter` writes it: one harmonic per line, all for the same four beads.

    Eight lines are one dihedral, not eight. Read as eight, the report measures the same torsion eight times, lists it
    eight times, and picks a "dominant" from single harmonics that were never separate terms.
    """
    path = tmp_path / 'funct9.itp'
    path.write_text('[ dihedrals ]\n'
                    '1 2 3 4 9 -93.484 -4.431 1\n'
                    '1 2 3 4 9 -17.242 4.021 2\n'
                    '1 2 3 4 9 64.043 -3.081 3\n')

    terms = dihedral_fit.read_declared_dihedrals(path)

    assert len(terms) == 1, terms
    entry = terms[0]
    assert entry['funct'] == '9' and entry['term_count'] == 3
    assert [term['multiplicity'] for term in entry['terms']] == [1, 2, 3]
    # The scalar fields are the harmonic with the largest force constant by magnitude -- -4.431 here, not 4.021.
    assert entry['multiplicity'] == 1
    assert entry['force_constant'] == pytest.approx(-4.431)
    assert entry['phase_deg'] == pytest.approx(-93.484)


def test_one_line_may_carry_several_terms_and_two_quadruples_stay_apart(tmp_path):
    """GROMACS allows several `phi C mult` triplets on one funct 9 line; two quadruples are two dihedrals."""
    path = tmp_path / 'two.itp'
    path.write_text('[ dihedrals ]\n'
                    '1 2 3 4 9 180.0 3.5 2 90.0 0.4 4\n'
                    '2 3 4 5 9 0.0 1.0 1\n')

    terms = dihedral_fit.read_declared_dihedrals(path)

    assert [entry['atoms'] for entry in terms] == [(1, 2, 3, 4), (2, 3, 4, 5)]
    assert terms[0]['term_count'] == 2 and terms[1]['term_count'] == 1
    assert [term['multiplicity'] for term in terms[0]['terms']] == [2, 4]


def test_a_one_term_fourier_dihedral_reads_as_the_periodic_one_it_is(tmp_path):
    """funct 1 and a one-triplet funct 9 are the same function, so the numbers must not change with the spelling."""
    periodic = tmp_path / 'periodic.itp'
    periodic.write_text('[ dihedrals ]\n1 2 3 4 1 180.0 3.5 2\n')
    fourier = tmp_path / 'fourier.itp'
    fourier.write_text('[ dihedrals ]\n1 2 3 4 9 180.0 3.5 2\n')

    one = dihedral_fit.read_declared_dihedrals(periodic)[0]
    nine = dihedral_fit.read_declared_dihedrals(fourier)[0]

    for field in ('phase_deg', 'force_constant', 'multiplicity', 'term_count'):
        assert one[field] == nine[field], field
    assert one['funct'] == '1' and nine['funct'] == '9'


def test_a_quadruple_declared_with_two_functions_is_refused(tmp_path):
    path = tmp_path / 'mixed.itp'
    path.write_text('[ dihedrals ]\n1 2 3 4 1 180.0 3.5 2\n1 2 3 4 9 180.0 3.5 2\n')

    with pytest.raises(ValueError, match='cannot be both'):
        dihedral_fit.read_declared_dihedrals(path)


def test_the_curve_difference_ignores_the_constant_a_series_carries():
    """A series carries the sum of its coefficients as a constant, and the two sides need not share it.

    Aligning on the minimum instead would count well depth as shape; the number this reports is disagreement about
    shape alone, which is why a shift that no torsion feels must read as no difference.
    """
    terms = [{'phase_deg': 180.0, 'force_constant': 3.5, 'multiplicity': 2}]
    same = [{'phase_deg': 180.0, 'force_constant_kj_mol': 3.5, 'multiplicity': 2}]
    shifted = [{'phase_deg': 180.0, 'force_constant_kj_mol': 3.5, 'multiplicity': 2},
               {'phase_deg': 0.0, 'force_constant_kj_mol': 12.0, 'multiplicity': 0}]
    other = [{'phase_deg': 0.0, 'force_constant_kj_mol': 3.5, 'multiplicity': 2}]

    assert dihedral_fit.curve_rms(terms, same) == pytest.approx(0.0, abs=1e-12)
    assert dihedral_fit.curve_rms(terms, shifted) == pytest.approx(0.0, abs=1e-12)
    assert dihedral_fit.curve_rms(terms, other) > 1.0


def test_a_fourier_series_topology_is_compared_by_its_whole_curve(tmp_path):
    """The end-to-end path for what `ff_inter` actually writes: a term with two harmonics, compared as a curve."""
    work = _dihedral_run(tmp_path, FUNCT9_TOPOLOGY)

    report = dihedral_fit.publish(work, {'temperature': 303.15})

    assert report['declared'] == {'dihedrals': 1, 'multi_term': 1, 'harmonics': 2, 'functs': ['9']}
    assert len(report['rows']) == 1 and not report['unmeasured']
    row = report['rows'][0]
    assert row['ours']['term_count'] == 2
    assert row['multiplicities_agree'] is True
    # A series has no single phase, so the shape comparison is the number this row leans on; it is a measurement and
    # its size is not pinned here -- pinning it would pin the criterion's choice of harmonics, which is not this test's
    # subject. That the number is zero when the two sides state the same series is the test below.
    assert math.isfinite(row['energy_rms_kj_mol']) and row['energy_rms_kj_mol'] >= 0.0
    assert any('funct 9' in line for line in report['limitations'])


def test_a_topology_that_states_the_fits_own_series_has_no_curve_difference(tmp_path):
    """The shape comparison measured against itself: the same series on both sides must differ by nothing.

    This is what makes `energy_rms_kj_mol` a number a reader can trust before trusting its size on a real molecule:
    the two curves are evaluated by the same function, and a fit written back into a topology has to reproduce it.
    """
    work = _dihedral_run(tmp_path)
    first = dihedral_fit.publish(work)
    chosen = first['rows'][0]['fit']['dihedrals']
    lines = '\n'.join(f"1 2 3 4 9 {term['phase_deg']} {term['force_constant_kj_mol']} {term['multiplicity']}"
                       for term in chosen)
    (work / '3_initial_CG' / 'DDM_ff_inter.itp').write_text('[ dihedrals ]\n' + lines + '\n')

    second = dihedral_fit.publish(work)

    row = second['rows'][0]
    assert row['ours']['term_count'] == len(chosen)
    assert row['energy_rms_kj_mol'] == pytest.approx(0.0, abs=1e-9)
    assert row['multiplicities_agree'] is True


def _dihedral_run(tmp_path, topology=DIHEDRAL_TOPOLOGY, *, frames=2000, amplitude=6.0, seed=11):
    """A work directory whose four beads take torsions drawn from a known 2-fold potential.

    The frames come from `p ~ exp(-F/RT)` with `F = amplitude (1 + cos 2 phi)`, so the distribution has its two
    minima at 0 and 180 degrees -- what a 2-fold term looks like -- and the answer the fit should find is known
    before it runs. That is the same construction as the one-cosine test above, one dimension down.
    """
    work = tmp_path / 'work'
    (work / '2_mapping').mkdir(parents=True)
    (work / '3_initial_CG').mkdir(parents=True)
    (work / '3_initial_CG' / 'DDM_ff_inter.itp').write_text(topology)
    grid = np.linspace(-180.0, 180.0, 721)[:-1]
    weights = np.exp(-amplitude * (1.0 + np.cos(2.0 * np.radians(grid))) / (dihedral_fit.R_GAS * 303.15 / 1000.0))
    torsions = np.random.default_rng(seed).choice(grid, size=frames, p=weights / weights.sum())
    universe = mda.Universe.empty(4, n_residues=1, atom_resindex=[0, 0, 0, 0], trajectory=True)
    universe.add_TopologyAttr('names', ['B01', 'B02', 'B03', 'B04'])
    universe.add_TopologyAttr('resnames', ['DDM'])
    universe.add_TopologyAttr('resids', [1])
    with mda.Writer(str(work / '2_mapping' / 'mapped.xtc'), n_atoms=4) as writer:
        for index, torsion in enumerate(torsions):
            universe.atoms.positions = np.array(_placed(torsion)) * 10.0  # written in angstroms
            universe.trajectory.ts.time = float(index)
            if index == 0:
                universe.atoms.write(str(work / '2_mapping' / 'mapped.gro'))
            writer.write(universe.atoms)
    return work


def test_the_analysis_fits_a_declared_dihedral_and_compares_it_with_ours(tmp_path):
    """The end-to-end path: a 2-fold potential sampled into a trajectory, a topology declaring a 2-fold term, and a
    report that says the two agree -- with the residual that says how much the histogram and smoothing cost."""
    work = _dihedral_run(tmp_path)

    report = dihedral_fit.publish(work, {'temperature': 303.15})

    assert report['molecule'] == 'DDM'
    assert report['frames_measured'] == 2000 and report['frames_in_trajectory'] == 2000
    assert report['ours_from'] == '3_initial_CG/DDM_ff_inter.itp'
    assert 'Fast_Forward' in report['ours_provenance']
    assert len(report['rows']) == 1 and not report['unmeasured']
    row = report['rows'][0]
    assert row['beads'] == ['B01', 'B02', 'B03', 'B04']
    assert row['ours']['phase_deg'] == 180.0
    assert row['ours']['force_constant_kj_mol'] == 3.5
    assert row['ours']['multiplicity'] == 2
    # funct 1 is one term; the series fields exist for every topology so a reader has one shape to handle.
    assert row['ours']['funct'] == '1' and row['ours']['term_count'] == 1
    assert row['ours']['terms'] == [{'phase_deg': 180.0, 'force_constant': 3.5, 'multiplicity': 2, 'line': 3}]
    assert row['energy_rms_kj_mol'] >= 0.0
    assert report['declared'] == {'dihedrals': 1, 'multi_term': 0, 'harmonics': 1, 'functs': ['1']}
    assert row['fit']['terms'] >= 2                      # one harmonic has one minimum, not two
    assert row['fit']['dominant_multiplicity'] == 2
    assert row['fit']['residual_rms_kj_mol'] > 0.0
    assert row['multiplicities_agree'] is True
    assert report['disagreements'] == []
    assert json.loads((work / dihedral_fit.REPORT).read_text())['rows'] == report['rows']


def test_a_topology_whose_multiplicity_the_fit_does_not_choose_is_named_as_a_disagreement(tmp_path):
    """The finding this analysis exists for: the tool's default term count against a criterion's."""
    work = _dihedral_run(tmp_path, DIHEDRAL_TOPOLOGY.replace('1 180.0 3.5 2', '1 180.0 3.5 3'))

    report = dihedral_fit.publish(work)

    assert report['rows'][0]['ours']['multiplicity'] == 3
    assert report['rows'][0]['fit']['dominant_multiplicity'] == 2
    assert report['rows'][0]['multiplicities_agree'] is False
    assert report['disagreements'] == [['B01', 'B02', 'B03', 'B04']]
    assert any('mirrored' in line for line in report['limitations'])


def test_a_dihedral_the_trajectory_cannot_form_is_listed_rather_than_dropped(tmp_path):
    """A term naming a bead the trajectory does not have is reported with the bead named -- dropped, it would look
    like a topology that declares less than it does."""
    work = _dihedral_run(tmp_path, DIHEDRAL_TOPOLOGY.replace('1 2 3 4 1', '1 2 3 9 1'))

    report = dihedral_fit.publish(work)

    assert report['rows'] == []
    assert [entry['beads'] for entry in report['unmeasured']] == [['B01', 'B02', 'B03', '#9']]
    assert 'no bead' in report['unmeasured'][0]['reason']


def test_a_run_with_no_topology_is_refused(tmp_path):
    work = _dihedral_run(tmp_path)
    (work / '3_initial_CG' / 'DDM_ff_inter.itp').unlink()

    with pytest.raises(ValueError, match='neither a fit nor a draft'):
        dihedral_fit.publish(work)


def test_the_dihedral_fit_kind_is_registered_in_all_four_places():
    """One row holds all four: the name, the sources, the dispatch and the description.

    The fourth place used to be an `elif kind == ...` line in the worker's source, and a kind missing it was accepted
    by the queue and then produced nothing at all -- which reads as a stuck worker rather than a missing line. It is
    `row.run` now.
    """
    from dashboard.analysis.kinds import TABLE
    row = TABLE['dihedral-fit']
    assert worker.known('dihedral-fit') and row.name == 'dihedral-fit'
    assert list(row.sources) == [
        '2_mapping/mapped.gro', '2_mapping/mapped.xtc', '2_mapping/model.json',
        '3_initial_CG/*_ff_inter.itp', '3_initial_CG/*initial*.itp']
    assert callable(row.run), 'the dispatch is the row'
    assert row.title != 'Dihedral Fit', 'a title the code invents is the fallback this replaced'
