import copy

import pytest
from dashboard.models import mappings
from dashboard.models.sugars.validation import derive_representation, validate_representation


def test_physical_only_removes_tc4_but_preserves_physical_ring_data():
    source = mappings.automatic_candidate(mappings.molecule(), 'DDM')
    physical = derive_representation(source, 'physical_only_ring_constrained')

    assert all(not bead.get('virtual_site') for bead in physical['beads'])
    assert [ring['beads'] for ring in physical['rings']] == [ring['beads'] for ring in source['rings']]
    assert all(ring['scale'] == 1.15 for ring in physical['rings'])
    assert physical['source_mapping_hash'] == mappings.candidate_identity(source)
    assert physical['transformation'] == 'remove_tc4_retain_ring_constraints@1'


def test_tc4_derivation_is_identity_copy():
    source = mappings.automatic_candidate(mappings.molecule(), 'DDM')
    result = derive_representation(source, 'tc4')

    assert result == source
    assert result is not source


def test_physical_only_rejects_mapping_without_ring_definitions():
    source = {'name': 'plain', 'beads': [{'name': 'A', 'size': 'S', 'type': 'S1', 'atoms': [1]}],
              'rings': [], 'connections': []}
    with pytest.raises(ValueError, match='ring'):
        derive_representation(source, 'physical_only_ring_constrained')


def test_physical_only_schema_accepts_ring_without_virtual_site():
    source = mappings.automatic_candidate(mappings.molecule(), 'DDM')
    source['beads'] = [bead for bead in source['beads'] if not bead.get('virtual_site')]
    for ring in source['rings']:
        ring.pop('virtual_site', None)

    validate_representation(source, 'physical_only_ring_constrained')


def test_physical_only_mapping_passes_structural_validation():
    source = mappings.automatic_candidate(mappings.molecule(), 'DDM')
    physical = derive_representation(source, 'physical_only_ring_constrained')
    result = mappings.validate(physical)
    assert result['virtual_sites'] == 0
    assert result['can_export'] is True


def test_legacy_candidate_identity_does_not_change():
    source = mappings.automatic_candidate(mappings.molecule(), 'DDM')
    clone = copy.deepcopy(source)
    assert mappings.candidate_identity(source) == mappings.candidate_identity(clone)
