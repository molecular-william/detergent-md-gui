"""The complex adapter's contract: what a build must carry, and the stages it will run.

These are the parts of the protocol that can be checked without a structure, a detergent or GROMACS, which is why
they are checked here rather than discovered halfway through a run.
"""
import pytest

from dashboard.execution.adapters import pdc


def test_a_build_requires_a_seed_and_a_positive_aggregation_number():
    """A missing seed is an error, not a default: two builds must not look comparable when they were not."""
    with pytest.raises(ValueError, match='seed'):
        pdc.validate_payload({'template': 'ddm', 'aggregation_number': 4})
    with pytest.raises(ValueError, match='aggregation'):
        pdc.validate_payload({'template': 'ddm', 'aggregation_number': 0, 'seed': 1})
    with pytest.raises(ValueError, match='aggregation'):
        pdc.validate_payload({'template': 'ddm', 'aggregation_number': 2.5, 'seed': 1})
    accepted = pdc.validate_payload({'template': 'ddm', 'aggregation_number': 4, 'seed': 1})
    assert accepted['salt_molar'] == 0.15          # the agreed default, in one place
    assert accepted['aggregation_number'] == 4 and accepted['seed'] == 1


def test_a_protein_free_build_is_expressible():
    """Empty micelles are in scope, so "no protein" must be a real value rather than an empty string."""
    accepted = pdc.validate_payload({'template': 'ddm', 'aggregation_number': 4, 'seed': 1, 'protein': ''})
    assert accepted['protein'] is None


def test_the_stage_list_is_the_protocol_in_order():
    assert [stage.name for stage in pdc.STAGES] == [
        'System preparation', 'CG assessment MD', 'Micelle assessment', 'CG extension MD',
        'Final assessment', 'Back-mapping (CG2AT2)']


def test_the_settings_carry_every_protocol_number_with_bounds():
    for key in ('pdc_assessment_ns', 'pdc_extension_ns', 'pdc_seed', 'aggregation_number', 'salt_molar',
                'box_margin_nm', 'initial_z_nm', 'contact_nm', 'selection_threshold_fraction'):
        label, low, high = pdc.SETTING_SPECS[key]
        assert label and low < high, (key, label, low, high)
