"""The builder's belt score, measured from the plane it was told about rather than from the protein's middle.

The default is unchanged on purpose: no caller that passes no origin may see a different number, because the pdc path
does not use this function at all and the standalone builder's behaviour is not this phase's business to move.
"""
from micelle.geometry import candidate_score

# An asymmetric protein, as one with a large soluble domain on a single side is: mean z = +0.375, extent -1 .. +2.
OFF_CENTRE = [[0.0, 0.0, -1.0], [0.0, 0.0, -0.5], [0.0, 0.0, 1.0], [0.0, 0.0, 2.0]]
POINT = [0.0, 0.0, 0.0]


def test_a_belt_stated_against_the_plane_holds_the_atoms_the_plane_holds():
    scored = candidate_score(POINT, OFF_CENTRE, span=(-1.0, 1.0), origin=(0.0, 0.0, 0.0))
    assert scored['coverage'] == 0.75          # three of the four atoms are inside -1 .. +1
    assert scored['exposure'] == 0.25


def test_without_an_origin_the_belt_is_still_measured_from_the_centroid():
    """The behaviour every existing caller has, pinned so this change cannot move it silently."""
    scored = candidate_score(POINT, OFF_CENTRE, span=(-1.0, 1.0))
    assert scored['coverage'] == 0.5           # the same width, centred on +0.375 instead of on the plane
    assert scored['exposure'] == 0.5


def test_the_stated_origin_changes_the_score_the_placement_reads():
    as_stated = candidate_score(POINT, OFF_CENTRE, span=(-1.0, 1.0), origin=(0.0, 0.0, 0.0))['score']
    as_centred = candidate_score(POINT, OFF_CENTRE, span=(-1.0, 1.0))['score']
    assert as_stated != as_centred


def test_an_origin_of_all_zeros_is_honoured_rather_than_read_as_absent():
    """`(0, 0, 0)` is the membrane plane in OPM's own frame -- the one value a falsy check would throw away."""
    assert candidate_score(POINT, OFF_CENTRE, span=(-1.0, 1.0), origin=(0.0, 0.0, 0.0))['coverage'] == 0.75


def test_an_empty_protein_asks_for_no_belt_rather_than_dividing_by_nothing():
    """A protein-free build reaches here with an empty array, and the score it has always returned must stand."""
    assert candidate_score(POINT, []) == {'score': 1.0, 'clash': False, 'exposure': 1.0}
