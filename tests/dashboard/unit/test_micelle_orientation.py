"""The orientation report: what a structure's own statement does to it, and what stays exactly as it was.

`infer_orientation` had no test until now, which is how its OPM branch came to discard the one thing that branch
exists to carry.
"""
from micelle.orientation import infer_orientation

PROTEIN = [[0.0, 0.0, -1.0], [0.0, 0.0, 1.0], [0.0, 0.0, 3.0]]


def test_metadata_that_states_a_slab_supplies_the_span_rather_than_the_default():
    report = infer_orientation(PROTEIN, opm={'axis': (0, 0, 1), 'span': (-1.18, 1.18),
                                             'origin': (0.0, 0.0, 0.0)})
    assert report.method == 'opm' and report.confidence == 1.0
    assert report.span == (-1.18, 1.18)          # not the (-1., 1.) the unset default would have given
    assert report.origin == (0.0, 0.0, 0.0)


def test_metadata_with_no_statement_keeps_the_span_it_had_before():
    """A structure that states nothing has to behave exactly as it did, or the default is being changed by stealth."""
    report = infer_orientation(PROTEIN, opm={'axis': (0, 0, 1)})
    assert report.span == (-1.0, 1.0) and report.origin == (0.0, 0.0, 0.0)


def test_the_heuristic_report_is_unchanged_apart_from_the_new_field():
    report = infer_orientation(PROTEIN)
    assert report.method == 'heuristic' and report.confidence == 0.35
    assert report.span == (-1.0, 1.0) and report.origin == (0.0, 0.0, 0.0)


def test_opm_metadata_outranks_an_explicit_axis_and_normalises_its_direction():
    """A measured statement beats an asserted one, and a direction stated as a vector is normalised before use."""
    report = infer_orientation(PROTEIN, opm={'axis': (0, 0, 2)}, explicit_axis=(1, 0, 0))
    assert report.method == 'opm'
    assert report.axis == (0.0, 0.0, 1.0)


def test_an_explicit_axis_still_carries_its_own_span():
    report = infer_orientation(PROTEIN, explicit_axis=(0, 0, 1), explicit_span=(-0.5, 0.5))
    assert report.method == 'explicit' and report.confidence == 0.9
    assert report.span == (-0.5, 0.5)


def test_the_report_is_a_dict_the_manifest_can_hold():
    """`cli.build` writes `orientation.__dict__` straight into the report, so a new field has to arrive with it."""
    assert set(infer_orientation(PROTEIN).__dict__) == {'axis', 'span', 'method', 'confidence', 'evidence', 'origin'}
