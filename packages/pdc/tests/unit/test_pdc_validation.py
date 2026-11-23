"""`micelle.validation` owns the overlap gate; this pins the additive pair report the preview's marks read."""
import numpy as np
from micelle.validation import validate_positions


def test_the_overlap_report_keeps_its_keys_and_adds_the_offending_pair():
    """The four keys every caller already reads are unchanged; the pair report is additive."""
    report = validate_positions([[0.0, 0.0, 0.0], [0.1, 0.0, 0.0], [2.0, 0.0, 0.0]], 3)

    assert report['valid'] is False
    assert report['issues'] == ['detergent overlap: minimum 0.100 nm']
    assert report['aggregation_number'] == 3
    assert report['minimum_distance_nm'] == 0.1
    assert report['minimum_pair'] == [0, 1]
    assert report['overlap_pairs'] == [[0, 1]]


def test_a_clear_placement_reports_no_pair_and_no_overlap():
    """Nothing below the gate: no pair is invented, and `minimum_pair` still names the closest two."""
    report = validate_positions([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], 2)

    assert report['valid'] is True and report['issues'] == []
    assert report['minimum_distance_nm'] == 1.0
    assert report['minimum_pair'] == [0, 1]
    assert report['overlap_pairs'] == []


def test_a_single_site_has_no_pair():
    """One site (or none) has no two distinct points to measure, and the additive keys say so."""
    single = validate_positions([[0.0, 0.0, 0.0]], 1)
    empty = validate_positions(np.empty((0, 3)), 0)

    assert single['minimum_pair'] is None and single['overlap_pairs'] == []
    assert empty['minimum_pair'] is None and empty['overlap_pairs'] == []
