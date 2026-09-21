from dashboard.models import depiction
from dashboard.models.mapping_context import build_context
from tests.dashboard.unit.test_mapping_context import _write_fixture


def test_empty_mapping_does_not_remove_structure(tmp_path):
    _write_fixture(tmp_path)
    context = build_context(tmp_path, "Fixture")
    scene = depiction.build_scene(context)
    assert set(scene["positions"]) == {1, 2, 3, 4, 5}
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
