from dashboard.models.mappings import depiction
from dashboard.models.mappings.context import build_context

from tests.dashboard.unit.test_mapping_context import _write_fixture


def test_empty_mapping_does_not_remove_structure(tmp_path):
    _write_fixture(tmp_path)
    context = build_context(tmp_path, "Fixture")
    scene = depiction.build_scene(context)
    assert set(scene["positions"]) == {1, 2, 3, 4}
    assert 'data-atom-id="5"' not in scene["svg"]
    assert "H1" not in scene["svg"]
    assert context["source_quality"]["bond_order"] == "fallback"
    assert scene == depiction.build_scene(context)


def test_context_render_has_interactive_atom_ids_and_overlay(tmp_path):
    _write_fixture(tmp_path)
    context = build_context(tmp_path, "Fixture")
    mapping = {"name": "Fixture draft", "beads": [
        {"name": "B1", "size": "R", "type": "C1", "atoms": [1, 2, 3, 4]}
    ]}
    svg = depiction.render(mapping, context=context)
    assert 'data-atom-id="1"' in svg
    assert 'class="bead-overlays"' in svg
    assert 'data-atoms="1 2 3 4"' in svg


def test_long_straight_carbon_chain_uses_zigzag_layout():
    atoms = [
        {'id': index, 'name': f'C{index}', 'element': 'C', 'heavy': True,
         'display_xy': [float(index), 0.0], 'xyz': [float(index), 0.0, 0.0]}
        for index in range(1, 7)
    ]
    context = {
        'name': 'Chain', 'atoms': atoms,
        'bonds': [{'a': index, 'b': index + 1} for index in range(1, 6)],
    }
    positions = depiction.build_scene(context)['positions']
    y_values = [round(positions[index][1], 4) for index in range(1, 7)]
    assert len(set(y_values)) == 2
    assert y_values[0] == y_values[2] == y_values[4]
    assert y_values[1] == y_values[3] == y_values[5]
