import pytest

from dashboard.analysis.carbohydrate_geometry import block_summary, run


def test_block_summary_is_finite_and_deterministic():
    result = block_summary([1, 2, 3, 4, 5, 6], block_count=3)
    assert result['samples'] == 6
    assert result['mean'] == 3.5
    assert result['blocks'] == 3
    assert result['stderr'] >= 0


def test_geometry_rejects_less_than_200_ns_for_evidence(tmp_path):
    with pytest.raises(ValueError, match='200 ns'):
        run(tmp_path, {'representation_mode': 'tc4'}, {'tier': 'evidence', 'duration_ns': 10})


def test_setup_geometry_reports_diagnostic_only_when_sources_are_missing(tmp_path):
    result = run(tmp_path, {'representation_mode': 'tc4'}, {'tier': 'setup', 'duration_ns': 1})
    assert result['status'] == 'insufficient_data'
    assert result['diagnostic_only'] is True
