from copy import deepcopy

from dashboard.models.mapping_context import build_context
from dashboard.models.mapping_references import load_index
from dashboard.models.mapping_suggestions import generate_baseline, suggest_bead
from tests.dashboard.fixtures import PROJECT_ROOT


def test_ddm_baseline_is_deterministic_and_keeps_inputs():
    context = build_context(PROJECT_ROOT / "molecules", "DDM")
    original = deepcopy(context)
    index = load_index(PROJECT_ROOT)
    first = generate_baseline(context, index)
    assert first["available"]
    assert first == generate_baseline(context, index)
    assert context == original
    assert "file" not in first["candidate"]
    assert first["candidate"]["provenance"]["algorithm"]


def test_suggestion_returns_catalog_type_or_explicit_heuristic():
    context = build_context(PROJECT_ROOT / "molecules", "DDM")
    index = load_index(PROJECT_ROOT)
    result = suggest_bead(context, [1, 2, 3], index)
    assert result["suggestions"]
    assert result["suggestions"][0]["confidence"] in {"exact-context", "fragment-match", "heuristic"}
