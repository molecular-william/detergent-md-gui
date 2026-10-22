"""A count stays a count through the panel, the job record and the validator.

`aggregation_number` reached `validate_payload` as `120.0`: the settings normalizer converted every supplied number to
`float`, and the validator demanded an `int`, so a build that named an aggregation number was refused at `prepare` with
"pdc aggregation number must be a positive integer" -- before a single stage directory existed. The number in the job
record is the number the run will use, so the fix is in the normalizer (counts are stored as counts) with the validator
tolerant of a whole number that arrived through a float, which is what every record written before this carries.
"""
import pytest

from dashboard.execution.adapters import pdc


def test_a_supplied_aggregation_number_is_stored_as_a_count():
    numbers = pdc.normalize_settings({'aggregation_number': 120, 'pdc_seed': 20261013, 'attempts_max': 3})

    assert numbers['aggregation_number'] == 120
    assert isinstance(numbers['aggregation_number'], int), 'a count is not a size: the record says 120, not 120.0'
    assert isinstance(numbers['seed'], int) and isinstance(numbers['attempts_max'], int)


def test_a_size_is_still_a_size():
    numbers = pdc.normalize_settings({'box_margin_nm': 2, 'salt_molar': 1})

    assert isinstance(numbers['box_margin_nm'], float) and isinstance(numbers['salt_molar'], float)


def test_a_whole_number_arriving_as_a_float_is_still_the_count():
    """What a record written before the normalizer kept counts integral carries, and what a JSON float is."""
    choices = pdc.validate_payload({'seed': 1, 'aggregation_number': 120.0})

    assert choices['aggregation_number'] == 120
    assert isinstance(choices['aggregation_number'], int)


def test_a_fraction_is_not_a_count():
    with pytest.raises(ValueError, match='aggregation number must be a positive integer'):
        pdc.validate_payload({'seed': 1, 'aggregation_number': 120.5})


def test_a_string_is_not_a_number_the_builders_can_use():
    with pytest.raises(ValueError, match='aggregation number must be a positive integer'):
        pdc.validate_payload({'seed': 1, 'aggregation_number': '120'})


def test_an_absent_aggregation_number_takes_the_default():
    assert pdc.validate_payload({'seed': 1})['aggregation_number'] == pdc.DEFAULTS['aggregation_number']


def test_a_normalized_payload_validates_end_to_end():
    """The two halves read the same record: what `normalize_settings` writes, `validate_payload` accepts."""
    numbers = pdc.normalize_settings({'aggregation_number': 120, 'pdc_seed': 20261013})

    choices = pdc.validate_payload(numbers)

    assert choices['aggregation_number'] == 120 and choices['seed'] == 20261013
