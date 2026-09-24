from dashboard.models import mappings
from dashboard.models.mappings.context import build_context
from tests.dashboard.unit.test_mapping_context import _write_fixture


def test_nonring_site_is_advisory_not_automatic_sugar_scaling(tmp_path):
    _write_fixture(tmp_path)
    context = build_context(tmp_path, "Fixture")
    draft = mappings.new_draft(context, "Site experiment")
    draft["beads"] = [
        {"name": f"B{i}", "size": "T", "type": "TC1", "atoms": [i]}
        for i in (1, 2, 3)
    ]
    proposal = mappings.ring_site_preview(draft, context, ["B1", "B2", "B3"])
    assert proposal["bead"]["type"] == "TC4"
    assert proposal["bead"]["atoms"] == []
    assert proposal["ring"] is None
    assert any(w["code"] == "not_ring_like" for w in proposal["warnings"])
