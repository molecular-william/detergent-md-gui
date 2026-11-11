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


#: The default recipe at both head shapes: a single ring (GLC) and a two-ring sugar (LAC). The `.gro` is the
#: geometry a CG run starts from, so it is pinned against the arrangement the panel and the PDB draw.
RUN_PAYLOADS = (
    ('GLC', 'C'),
    ('LAC', 'A1'),
)


def _built(sugar, endpoint):
    result = topology.build_preview({'head_fragment_id': f'builtin:martini-sugars-v2:{sugar}',
                                     'tail_recipe_id': 'linear-c1', 'carbon_count': 12,
                                     'head_endpoint': {'bead': endpoint}, 'tail_endpoint': {'bead': 'C01'},
                                     'linkage_profile_id': 'sugar-alkyl-ether-ddm-transfer'})
    result['pdb'] = topology.render_pdb(result)
    return result


def _gro_positions(text):
    """The `.gro`'s coordinates in nanometres, by bead name (the format's fixed columns, not a split)."""
    lines = text.splitlines()
    count = int(lines[1])
    positions = {}
    for line in lines[2:2 + count]:
        positions[line[10:15].strip()] = tuple(float(line[start:start + 8]) for start in (20, 28, 36))
    return positions


def _pdb_positions(text):
    """The PDB's coordinates in nanometres, by bead name; a virtual site is deliberately absent from the file."""
    positions = {}
    for line in text.splitlines():
        if line.startswith('HETATM'):
            positions[line[12:16].strip()] = tuple(float(line[start:start + 8]) / 10 for start in (30, 38, 46))
    return positions


@pytest.mark.parametrize('sugar,endpoint', RUN_PAYLOADS)
def test_the_gro_writes_the_joined_layout_the_panel_draws(sugar, endpoint):
    """The defect this pins: the run's geometry was a 0.1 nm z-stack, not the arrangement the reader approves."""
    result = _built(sugar, endpoint)
    gro = _gro_positions(result['gro'])
    joined = {bead['name']: bead['position'] for bead in topology.preview_geometry(result)['joined']['beads']}
    assert set(joined) <= set(gro)
    for name, position in joined.items():
        assert gro[name] == pytest.approx(tuple(position), abs=1e-3), name
    # A virtual site is not simulated at its written coordinate; the file writes its parents' centroid so it is
    # coherent with the virtual_sitesn block.
    for site in result['topology']['virtual_sites']:
        parents = [joined[name] for name in site['parents']]
        centroid = tuple(round(sum(point[axis] for point in parents) / len(parents), 6) for axis in range(3))
        assert gro[site['site']] == pytest.approx(centroid, abs=1e-3), site  # .gro is 0.001 nm


@pytest.mark.parametrize('sugar,endpoint', RUN_PAYLOADS)
def test_no_two_physical_beads_are_written_on_top_of_each_other(sugar, endpoint):
    """The failure the broken `.gro` caused: coincident beads made GROMACS' first step `Epot=1e35` then `-nan`.

    The layout is a starting point, not a conformer: adjacent head beads are 0.30-0.61 nm apart and tail beads
    0.47 nm, so the guard is the distance at which Martini beads overlap hard, not a bond length.
    """
    result = _built(sugar, endpoint)
    gro = _gro_positions(result['gro'])
    virtual = {site['site'] for site in result['topology']['virtual_sites']}
    physical = [position for name, position in gro.items() if name not in virtual]
    for first in range(len(physical)):
        for second in range(first + 1, len(physical)):
            distance = sum((physical[first][axis] - physical[second][axis]) ** 2 for axis in range(3)) ** 0.5
            assert distance >= 0.25, (first, second, physical[first], physical[second])


@pytest.mark.parametrize('sugar,endpoint', RUN_PAYLOADS)
def test_the_gro_and_the_pdb_place_the_same_bead_at_the_same_point(sugar, endpoint):
    result = _built(sugar, endpoint)
    gro, pdb = _gro_positions(result['gro']), _pdb_positions(result['pdb'])
    assert pdb, 'the PDB names no bead'
    for name, position in pdb.items():
        assert name in gro, f'{name} is in the PDB but not the .gro'
        assert gro[name] == pytest.approx(position, abs=1e-3), name  # .gro is 0.001 nm, PDB 0.001 A


@pytest.mark.parametrize('sugar,endpoint', RUN_PAYLOADS)
def test_the_linkage_bead_starts_one_bond_from_its_head_endpoint(sugar, endpoint):
    result = _built(sugar, endpoint)
    gro = _gro_positions(result['gro'])
    link = topology.preview_geometry(result)['joined']['link']
    distance = sum((gro[link[0]][axis] - gro[link[1]][axis]) ** 2 for axis in range(3)) ** 0.5
    assert distance == pytest.approx(0.47, abs=1e-3)
