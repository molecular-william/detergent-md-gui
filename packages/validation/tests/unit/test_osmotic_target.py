"""The maltose osmotic target: whether it is citable, and whether it reaches the leg that needs it.

The numbers came from Ebrahimi & Sadeghi 2016 through its fitted equation 8 and a Gibbs-Duhem conversion, so the test
that matters is not that the JSON parses -- it is that the conversion's provenance is in the entry, that the point
count is the paper's series minus the trivial one, and that the osmotic leg's own required molalities are the ones the
registry now carries values for.
"""

import pytest
from dashboard.analysis.validation import carbohydrate_targets
from detergent_validation.analysis.validation import osmotic, targets

from tests.harness.support import PROJECT_ROOT

ROOT = PROJECT_ROOT
DATASET = 'maltose-osmotic-ebrahimi-2016'


def test_the_osmotic_kind_is_allowed_at_all():
    """It was not, until this dataset needed it: the registry could hold partition free energies and nothing else."""
    assert 'osmotic_pressure' in targets.ALLOWED


def test_the_dataset_is_selectable_and_carries_its_citation():
    dataset = carbohydrate_targets.validate_selection(ROOT, 'Maltose', DATASET)

    assert dataset['availability'] == 'measured'
    assert dataset['citation'] == '10.1016/j.fluid.2016.02.030'
    assert len(dataset['targets']) == 5


def test_every_point_carries_its_value_its_uncertainty_and_where_it_came_from():
    dataset = carbohydrate_targets.validate_selection(ROOT, 'Maltose', DATASET)
    by_value = {target['value']: target for target in dataset['targets']}

    assert sorted(by_value) == [13.04, 26.54, 40.58, 56.09, 72.72]
    point = by_value[26.54]
    assert point['kind'] == 'osmotic_pressure'
    assert point['unit'] == 'bar'
    assert point['uncertainty'] == pytest.approx(0.08)
    # Every point carries its own provenance rather than a pointer to another's, which is what the registry is for.
    assert 'equation 8' in point['conditions']
    assert '308.15' in point['conditions']
    assert 'propagated' in point['conditions']
    # And the entry that states it in full names what the uncertainty is *not*.
    assert 'does not state' in by_value[13.04]['conditions']


def test_the_points_are_the_legs_molalities_minus_the_trivial_one():
    """A cross-check between two files that have no other reason to agree: the leg's required molalities and the
    registry's targets were written from the same paper and must not drift apart."""
    dataset = carbohydrate_targets.validate_selection(ROOT, 'Maltose', DATASET)
    carried = {target['id'].rsplit('-', 1)[-1] for target in dataset['targets']}
    required = {f'{value:.1f}'.replace('.', 'p') for value in osmotic.REQUIRED_MOLAL}

    assert carried == required - {'0p0'}
    assert 0.0 in osmotic.REQUIRED_MOLAL


def test_the_absent_zero_point_is_explained_rather_than_missing():
    """The registry refuses a target with no uncertainty, and at zero molality the pressure is zero by definition.
    Registering it would mean inventing an uncertainty, so it is absent and the dataset says why."""
    dataset = carbohydrate_targets.validate_selection(ROOT, 'Maltose', DATASET)

    assert 'note' in dataset and 'zero by definition' in dataset['note']
    assert all(target['uncertainty'] > 0 for target in dataset['targets'])


def test_the_earlier_maltose_dataset_is_left_alone():
    """The partition free energy is a different quantity and is still missing; this work does not pretend otherwise."""
    dataset = carbohydrate_targets.validate_selection(ROOT, 'Maltose', 'maltose-pilot-v1')

    assert dataset['availability'] == 'metadata_only'
    assert dataset['targets'] == []
    assert 'experimental source' in dataset['missing']
