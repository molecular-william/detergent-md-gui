"""The combined-geometry panel's bead positions.

The tail's positions are the recipe's own; the head's are a layout, because the composition catalog
carries no sugar reference positions and drawing them would invent a structure. These tests pin that
split, the linkage beads, and the join -- and that the caption says no more than a preview.
"""

import pytest
from dashboard.models.compositions import topology


def _result():
    return {
        "mapping": {"beads": [{"name": "P1", "type": "SP1", "size": "R"},
                              {"name": "P2", "type": "SP1", "size": "R"},
                              {"name": "VS", "type": "VS", "size": "S", "virtual_site": True},
                              {"name": "C1", "type": "SC1", "size": "R"},
                              {"name": "C2", "type": "SC1", "size": "R"}]},
        "tail": {"beads": [{"name": "C1", "type": "SC1", "mass": 54.0},
                           {"name": "C2", "type": "SC1", "mass": 54.0}],
                 "coordinates": [[0.0, 0.0, 0.0], [0.47, 0.0, 0.0]]},
        "topology": {"bonds": [{"a": "P1", "b": "P2", "function": 1, "length": 0.47},
                               {"a": "C1", "b": "C2", "function": 1, "length": 0.47},
                               {"a": "P2", "b": "C1", "function": 1, "length": 0.47}]},
    }


def test_the_fragments_split_on_the_recipes_own_bead_names_and_skip_virtual_sites():
    geometry = topology.preview_geometry(_result())
    assert [bead["name"] for bead in geometry["head"]["beads"]] == ["P1", "P2"]
    assert [bead["name"] for bead in geometry["tail"]["beads"]] == ["C1", "C2"]
    assert geometry["head"]["edges"] == [["P1", "P2"]]
    assert geometry["tail"]["edges"] == [["C1", "C2"]]


def test_the_tail_keeps_the_recipe_coordinates_and_the_head_is_laid_out():
    geometry = topology.preview_geometry(_result())
    assert [bead["position"] for bead in geometry["tail"]["beads"]] == [[0.0, 0.0, 0.0], [0.47, 0.0, 0.0]]
    head = [bead["position"] for bead in geometry["head"]["beads"]]
    assert all(len(position) == 3 for position in head)
    assert head[0] != head[1], "a layout must not collapse the beads onto one point"


def test_the_link_is_the_head_tail_bond_and_the_join_places_them_a_bond_length_apart():
    geometry = topology.preview_geometry(_result())
    assert geometry["link"] == {"head_bead": "P2", "tail_bead": "C1"}
    assert geometry["joined"]["link"] == ["P2", "C1"]
    joined = {bead["name"]: bead["position"] for bead in geometry["joined"]["beads"]}
    assert joined["C1"][0] == pytest.approx(joined["P2"][0] + 0.47, abs=1e-6)
    assert joined["C1"][1] == pytest.approx(joined["P2"][1], abs=1e-6)


def test_the_caption_states_the_layout_and_that_nothing_is_minimised():
    basis = topology.preview_geometry(_result())["basis"]
    assert "layout" in basis
    assert "minimised" in basis
    assert "CG" in basis
