"""The initial composite is laid out coplanar, and the composite's own bonds live in that plane.

Coplanar is a convention for a starting geometry: the head's positions are a layout from its bead set, and
the bonded terms are seeded from whatever these coordinates are. The tests below pin the geometry the
fitting stage will have to correct, so a change to the layout is a change to the seeds and cannot pass
silently.
"""

import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

# `compositions` is a `dashboard` subpackage -- it imports through `from ... import` -- so it must be
# imported under that package name. (`sugars/` is the opposite case: it ships standalone and may not.)
from dashboard.models.compositions.topology import expand_tail, preview_geometry, tail_recipe_catalog  # noqa: E402


def _recipe_id():
    return tail_recipe_catalog()[0]["id"]


def test_the_tail_is_laid_in_the_head_plane():
    tail = expand_tail(_recipe_id(), 8)
    coordinates = tail["coordinates"]
    # A recipe's unit is beads, not carbons: linear-c1 packs four carbons per bead, so 8 carbons is 2 beads.
    assert len(coordinates) == len(tail["beads"]) == 2, [bead["name"] for bead in tail["beads"]]
    assert [coordinate[2] for coordinate in coordinates] == [0.0] * len(coordinates)
    assert [coordinate[1] for coordinate in coordinates] == [0.0] * len(coordinates)
    steps = [coordinates[index][0] - coordinates[index - 1][0] for index in range(1, len(coordinates))]
    assert len(steps) == len(coordinates) - 1
    assert all(abs(step - 0.47) < 1e-9 for step in steps), steps


def _preview_with_one_tail_bead():
    """A minimal preview result: three head beads and a two-bead tail joined by one bond."""
    tail = {"id": "test", "recipe_id": _recipe_id(), "carbon_count": 2,
            "beads": [{"name": "C01", "type": "C1", "mass": 54.0}, {"name": "C02", "type": "C1", "mass": 54.0}],
            "coordinates": [[0.0, 0.0, 0.0], [0.47, 0.0, 0.0]]}
    mapping = {"beads": [{"name": "A", "type": "SP1", "size": "S"}, {"name": "B", "type": "SP1", "size": "S"},
                         {"name": "C", "type": "SP1", "size": "S"}, {"name": "C01", "type": "C1", "size": "S"},
                         {"name": "C02", "type": "C1", "size": "S"}]}
    topology = {"bonds": [{"a": "A", "b": "B", "function": 1}, {"a": "B", "b": "C", "function": 1},
                          {"a": "A", "b": "C01", "function": 1}, {"a": "C01", "b": "C02", "function": 1}]}
    return {"tail": tail, "mapping": mapping, "topology": topology}


def _plane_residual(points):
    """Largest distance from the best-fit plane of the points, via the smallest singular direction."""
    centre = [sum(point[axis] for point in points) / len(points) for axis in range(3)]
    centred = [[point[axis] - centre[axis] for axis in range(3)] for point in points]
    # Power iteration would be overkill: for three axes, the normal is the cross product of the two
    # widest-spread centred vectors, which is exact for a degenerate (collinear) set too.
    wide = sorted(centred, key=lambda row: sum(value * value for value in row), reverse=True)[:2]
    normal = [wide[0][1] * wide[1][2] - wide[0][2] * wide[1][1],
              wide[0][2] * wide[1][0] - wide[0][0] * wide[1][2],
              wide[0][0] * wide[1][1] - wide[0][1] * wide[1][0]]
    norm = math.sqrt(sum(value * value for value in normal))
    assert norm > 1e-9, "the composite is collinear, so its plane is undetermined"
    normal = [value / norm for value in normal]
    return max(abs(sum(row[axis] * normal[axis] for axis in range(3))) for row in centred)


def test_every_bead_of_the_joined_composite_is_coplanar():
    geometry = preview_geometry(_preview_with_one_tail_bead())
    joined = geometry["joined"]["beads"]
    assert len(joined) == 5, [bead["name"] for bead in joined]
    assert [bead["position"][2] for bead in joined] == [0.0] * 5
    assert _plane_residual([bead["position"] for bead in joined]) < 1e-9


def test_the_coplanar_layout_keeps_the_link_length_the_recipes_give():
    geometry = preview_geometry(_preview_with_one_tail_bead())
    joined = {bead["name"]: bead["position"] for bead in geometry["joined"]["beads"]}
    head, tail = joined["A"], joined["C01"]
    distance = math.dist(head, tail)
    # The joined view places the tail endpoint beside the head's, so the gap is a preview arrangement: it
    # must stay positive and in the plane rather than collapse the two fragments onto each other.
    assert 0.0 < distance < 1.0, distance
    assert abs(head[2] - tail[2]) == 0.0
