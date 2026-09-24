from dashboard.models import mappings
from dashboard.models.carbohydrate_validation import derive_representation
from dashboard.models.sugar_mapping import coordinates
from dashboard.models.sugar_topology import topology


def test_physical_only_has_ring_constraints_without_virtual_sites():
    structure = mappings.molecule()
    tc4 = mappings.automatic_candidate(structure, 'DDM')
    physical = derive_representation(tc4, 'physical_only_ring_constrained')

    tc4_itp = topology(tc4, structure, representation_mode='tc4')
    physical_itp = topology(physical, structure, representation_mode='physical_only_ring_constrained')

    assert '[ virtual_sitesn ]' in tc4_itp
    assert '[ virtual_sitesn ]' not in physical_itp
    assert '[ exclusions ]' in tc4_itp
    assert '[ exclusions ]' not in physical_itp
    assert physical_itp.count('[ constraints ]') == tc4_itp.count('[ constraints ]')


def test_physical_only_coordinates_keep_scaled_ring_cogs_without_tc4_atoms():
    structure = mappings.molecule()
    tc4 = mappings.automatic_candidate(structure, 'DDM')
    physical = derive_representation(tc4, 'physical_only_ring_constrained')
    positions = [atom['xyz'] for atom in structure['atoms']]

    assert len(coordinates(physical, positions, scaled=True)) == len(physical['beads'])


def test_scaled_coordinates_ignore_redundant_component_links():
    structure = mappings.molecule()
    candidate = mappings.automatic_candidate(structure, 'DDM')
    candidate['connections'].append(['TAIL1', 'TAIL3'])
    positions = [atom['xyz'] for atom in structure['atoms']]

    result = coordinates(candidate, positions, scaled=True)

    assert len(result) == len(candidate['beads'])
