import pytest

from dashboard.analysis.osmotic_pressure import pressure_from_force, validate_series


def test_pressure_from_force_uses_area_and_finite_units():
    assert pressure_from_force(10.0, 2.0) == pytest.approx(5.0)
    with pytest.raises(ValueError, match='area'):
        pressure_from_force(1.0, 0.0)


def test_series_marks_missing_concentration_incomplete():
    result = validate_series([{'molal': 0.0}, {'molal': 2.5}], 'evidence')
    assert result['complete'] is False
    assert result['missing']


def test_setup_series_can_be_short_but_remains_diagnostic():
    result = validate_series([{'molal': 0.0, 'duration_ns': 1}], 'setup')
    assert result['diagnostic_only'] is True


def test_evidence_series_requires_target_values():
    result = validate_series([{
        'molal': molal, 'duration_ns': 500, 'flat_bottom_restraint': True,
        'pressure_coupling': 'z', 'target_pressure': 1.0, 'target_uncertainty': 0.1,
    } for molal in (0, 0.5, 1, 1.5, 2, 2.5)], 'evidence')
    assert result['complete'] is True
