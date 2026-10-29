import pytest
from dashboard.analysis.validation.transfer import build_protocol, lambda_windows, parse_bar, run


def test_lambda_windows_has_nineteen_ordered_values():
    values = lambda_windows()
    assert len(values) == 19 and values[0] == 0.0 and values[-1] == 1.0
    assert values == sorted(values)


def test_bar_parser_rejects_missing_uncertainty():
    with pytest.raises(ValueError, match='uncertainty'):
        parse_bar('Delta G = -2.4 kJ/mol')


def test_transfer_requires_octanol_source(tmp_path):
    with pytest.raises(ValueError, match='octanol'):
        run(tmp_path, {'water': {}, 'target': {}})


def test_protocol_requires_nineteen_windows_and_both_solvents():
    result = build_protocol({'solvents': ['water', 'octanol'], 'lambda_windows': lambda_windows()})
    assert result['lambda_windows'] == lambda_windows()
