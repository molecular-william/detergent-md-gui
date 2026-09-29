"""The comparison body: what a row carries, which claims may be badged, and what the reference decides.

The numbers are hand-built so the arithmetic is checkable, and the two claims are deliberately separated:
a CG mean can sit inside the AA observed range while lying outside the spread of the AA mean, and a
reference value can agree with the CG mean while the CG mean is nowhere near the AA ensemble. Each case is
one test rather than one assertion inside a long one.
"""
from dashboard.analysis.runs import consistency

BEADS = {1: (1, 'A'), 2: (1, 'B'), 3: (1, 'C'), 4: (2, 'A'), 5: (2, 'B'), 6: (2, 'C')}
PAIR_AB = frozenset((1, 2))
PAIR_AC = frozenset((1, 3))
PAIR_DE = frozenset((4, 5))


def measured(samples, run='run', frames=None):
    return {'run': run, 'beads': BEADS, 'samples': samples, 'frames': frames or 20, 'molecule': 'Sucrose'}


def ramp(start, step, count=20):
    return [start + step * index for index in range(count)]


AA = measured({PAIR_AB: ramp(0.28, 0.004), PAIR_AC: ramp(0.50, 0.002)}, run='aa-run')
CG = measured({PAIR_AB: ramp(0.30, 0.003), PAIR_AC: ramp(0.49, 0.002)}, run='cg-run')


def row_for(rows, labels):
    return next(row for row in rows if row['pair'] == labels)


def test_a_row_carries_both_ensembles_with_their_spread_and_range():
    row = row_for(consistency.compare(AA, CG), [[1, 'A'], [1, 'B']])
    assert row['compared'] is True
    assert row['aa']['count'] == 20 and row['cg']['count'] == 20
    for side in ('aa', 'cg'):
        assert row[side]['min'] < row[side]['mean'] < row[side]['max']
        assert row[side]['stderr'] > 0 and row[side]['blocks'] == 10
    assert row['delta_pct'] == round(100 * (row['cg']['mean'] - row['aa']['mean']) / row['aa']['mean'], 3)


def test_the_block_count_the_caller_asks_for_is_the_one_reported():
    row = consistency.compare(AA, CG, block_count=4)[0]
    assert row['aa']['blocks'] == 4 and row['cg']['blocks'] == 4


def test_a_cg_mean_inside_the_aa_range_but_outside_the_spread_reports_both_ways():
    """The two claims are different, and a row must be able to say one is true and the other is not."""
    narrow = measured({PAIR_AB: ramp(0.30, 0.0001)})
    aa = measured({PAIR_AB: ramp(0.28, 0.004)})
    row = consistency.compare(aa, narrow)[0]
    assert row['inside_range'] is True
    assert row['inside_spread'] is False


def test_a_cg_mean_outside_the_aa_range_is_reported_as_outside():
    wide = measured({PAIR_AB: ramp(0.60, 0.002)})
    row = consistency.compare(AA, wide)[0]
    assert row['inside_range'] is False and row['inside_spread'] is False


def test_a_pair_without_cg_samples_is_reported_rather_than_scored():
    cg = measured({PAIR_AC: ramp(0.49, 0.002)})
    rows = consistency.compare(AA, cg)
    missing = row_for(rows, [[1, 'A'], [1, 'B']])
    assert missing['compared'] is False and missing['cg'] is None
    assert missing['inside_range'] is None and missing['inside_spread'] is None
    assert 'holds no sample' in missing['note']


def test_a_pair_the_cg_run_alone_holds_produces_no_row():
    rows = consistency.compare(measured({PAIR_AB: ramp(0.28, 0.004)}), CG)
    assert [row['pair'] for row in rows] == [[[1, 'A'], [1, 'B']]]


def test_the_reference_sets_no_verdict_and_its_delta_is_our_derived_value():
    """Context is context: a reference value that matches the CG mean changes no claim about our own AA.

    The delta reported against the entry is the atomistic side's, because that is the quantity the entry is
    a target for; the CG mean never enters it.
    """
    wide = measured({PAIR_AB: ramp(0.40, 0.001)})
    cg_mean = sum(ramp(0.40, 0.001)) / 20
    row = consistency.compare(AA, wide, {frozenset(((1, 'A'), (1, 'B'))): cg_mean})[0]
    assert row['inside_range'] is False and row['inside_spread'] is False
    assert abs(row['cg']['mean'] - cg_mean) < 1e-9, 'the entry sits exactly where the CG mean is'
    assert row['delta_vs_reference_pct'] == round(100 * (row['aa']['mean'] - cg_mean) / cg_mean, 3)


def test_a_pair_the_entry_does_not_constrain_says_unconstrained():
    row = consistency.compare(AA, CG, {})[0]
    assert row['reference_nm'] is None and row['unconstrained'] is True
    assert row['delta_vs_reference_pct'] is None


def test_the_reported_delta_against_the_reference_is_the_aa_mean_against_it():
    reference = {frozenset(((1, 'A'), (1, 'B'))): 0.35}
    row = consistency.compare(AA, CG, reference)[0]
    assert row['reference_nm'] == 0.35
    assert row['delta_vs_reference_pct'] == round(100 * (row['aa']['mean'] - 0.35) / 0.35, 3)


def test_the_report_says_which_two_ensembles_were_compared_and_counts_what_it_found():
    payload = consistency.report(AA, CG, {frozenset(((1, 'A'), (1, 'B'))): 0.35}, entry='SUCR')
    assert payload['comparison'] == 'AA vs CG'
    assert payload['entry'] == 'SUCR' and payload['molecule'] == 'Sucrose'
    assert payload['aa']['run'] == 'aa-run' and payload['cg']['run'] == 'cg-run'
    assert payload['aa']['frames'] == 20 and payload['cg']['frames'] == 20
    assert payload['counts'] == {'pairs': 2, 'compared': 2, 'cg_outside_aa_range': 0}
    assert 'context' in payload['reference_role']
    assert payload['diagnostic_only'] is True and payload['scientifically_validated'] is False


def test_the_report_counts_the_pairs_the_cg_run_missed():
    payload = consistency.report(AA, measured({}), {})
    assert payload['counts'] == {'pairs': 2, 'compared': 0, 'cg_outside_aa_range': 0}
    assert all(row['compared'] is False for row in payload['rows'])
