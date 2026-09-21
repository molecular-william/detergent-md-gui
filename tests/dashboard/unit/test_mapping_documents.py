import pytest

from dashboard.models import mappings
from dashboard.models.mapping_context import build_context
from tests.dashboard.unit.test_mapping_context import _write_fixture
from dashboard.models import mapping_store


def test_partial_draft_can_save_but_cannot_export(tmp_path, monkeypatch):
    _write_fixture(tmp_path)
    context = build_context(tmp_path, "Fixture")
    draft = mappings.new_draft(context, "Manual start")
    result = mappings.validate(draft, context=context, allow_partial=True)
    assert result["can_save"] and not result["can_export"]
    monkeypatch.setattr(mapping_store, "storage_root", lambda: tmp_path / "drafts")
    first = mappings.save_draft(draft, context=context)
    second = mappings.save_draft(first, context=context)
    assert first["file"] != second["file"]
    assert first["mapping_hash"] == second["mapping_hash"]
    with pytest.raises(ValueError, match="incomplete"):
        mappings.require_usable(first, context, operation="export")


def test_schema_three_identity_changes_with_molecule_snapshot(tmp_path):
    _write_fixture(tmp_path)
    context = build_context(tmp_path, "Fixture")
    draft = mappings.new_draft(context)
    altered = dict(draft, molecule_snapshot={"files": {"molecule.itp": "changed"}})
    assert mappings.mapping_identity(draft) != mappings.mapping_identity(altered)


def test_mapping_content_identity_ignores_candidate_name():
    candidate = {
        'schema_version': 3,
        'molecule_id': 'Fixture',
        'molecule_snapshot': {'snapshot_sha256': 'snapshot'},
        'name': 'First label',
        'beads': [{'name': 'B01', 'size': 'S', 'type': 'P1', 'atoms': [1, 2, 3]}],
        'rings': [],
        'connections': [],
    }
    renamed = {**candidate, 'name': 'Different label'}
    assert mappings.mapping_content_identity(candidate) == mappings.mapping_content_identity(renamed)
