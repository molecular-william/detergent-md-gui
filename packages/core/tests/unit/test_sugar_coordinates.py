"""`coordinates_many` is `coordinates` for a whole block of frames: the same numbers, as array ops.

The per-frame function is the oracle rather than a second implementation, so every case here asserts exact
float64 equality, frame by frame: the batched version exists to be faster, not to be different. The mapping is
built by hand so that the branches `coordinates` has are all reached -- ring dilation, the connected-rigid-group
translation (two rings joined by a linker), a virtual site, an atom-id permutation, an ungrouped bead -- and so
that a block boundary can be checked not to change a value.
"""
import numpy as np
import pytest
from dashboard.models.sugars.coords import coordinates, coordinates_many

RNG = np.random.default_rng(20261118)


def mapping(atoms=range(1, 13), links=True):
    """Two three-bead rings joined through a linker bead, plus one virtual site per ring."""
    return {
        'beads': [
            {'name': 'S1A', 'letter': 'A', 'residue': 1, 'atoms': [atoms[0], atoms[1]]},
            {'name': 'S1B', 'letter': 'B', 'residue': 1, 'atoms': [atoms[2], atoms[3]]},
            {'name': 'S1C', 'letter': 'C', 'residue': 1, 'atoms': [atoms[4]]},
            {'name': 'S1VS', 'letter': 'VS', 'residue': 1, 'atoms': [],
             'virtual_site': {'parents': ['S1A', 'S1B', 'S1C'], 'function': 1}},
            {'name': 'S2A', 'letter': 'A', 'residue': 2, 'atoms': [atoms[6], atoms[7]]},
            {'name': 'S2B', 'letter': 'B', 'residue': 2, 'atoms': [atoms[8], atoms[9]]},
            {'name': 'S2C', 'letter': 'C', 'residue': 2, 'atoms': [atoms[10]]},
            {'name': 'S2VS', 'letter': 'VS', 'residue': 2, 'atoms': [],
             'virtual_site': {'parents': ['S2A', 'S2B', 'S2C'], 'function': 1}},
            {'name': 'LINK', 'atoms': [atoms[5]]},
        ],
        'rings': [{'beads': ['S1A', 'S1B', 'S1C'], 'scale': 1.15},
                  {'beads': ['S2A', 'S2B', 'S2C'], 'scale': 1.15}],
        'connections': ([['S1A', 'S1B'], ['S1A', 'S1C'], ['S1B', 'S1C'], ['S1C', 'LINK'],
                         ['LINK', 'S2A'], ['S2A', 'S2B'], ['S2A', 'S2C'], ['S2B', 'S2C']]
                        if links else []),
    }


def frames(count=7, atoms=12, dtype=np.float64):
    """A block of frames: random positions, so every bead centre is a sum that could round differently."""
    return (RNG.standard_normal((count, atoms, 3)) * 4.0).astype(dtype)


def per_frame(data, block, **options):
    return np.asarray([coordinates(data, frame.tolist(), **options) for frame in block])


@pytest.mark.parametrize('scaled', [False, True])
@pytest.mark.parametrize('representation_mode', ['tc4', 'physical_only_ring_constrained'])
def test_the_block_equals_the_per_frame_reference_exactly(scaled, representation_mode):
    data, block = mapping(), frames()
    got = coordinates_many(data, block, scaled=scaled, representation_mode=representation_mode)
    assert got.shape == (7, len(data['beads']), 3)
    assert np.array_equal(got, per_frame(data, block, scaled=scaled,
                                         representation_mode=representation_mode))


def test_the_ring_dilation_and_the_rigid_translation_are_both_reached():
    """`scaled` with connections translates the second ring onto the linker; a plain centre would miss it."""
    data, block = mapping(), frames()
    scaled = coordinates_many(data, block, scaled=True)
    plain = coordinates_many(data, block, scaled=False)
    assert not np.allclose(scaled, plain), 'the dilation and the rigid placement must both move beads'
    assert np.array_equal(scaled, per_frame(data, block, scaled=True))


def test_a_mapping_without_connections_still_dilates_the_rings():
    data, block = mapping(links=False), frames()
    assert np.array_equal(coordinates_many(data, block, scaled=True), per_frame(data, block, scaled=True))


def test_a_mapping_with_connections_but_no_rings_still_places_its_groups():
    data = mapping()
    data['rings'] = []
    block = frames()
    assert np.array_equal(coordinates_many(data, block, scaled=True), per_frame(data, block, scaled=True))


def test_a_virtual_site_is_the_equal_weight_mean_of_its_parents():
    data, block = mapping(), frames()
    got = coordinates_many(data, block, scaled=True)
    for index, bead in enumerate(data['beads']):
        if not bead.get('virtual_site'):
            continue
        parents = [i for i, other in enumerate(data['beads'])
                   if other['name'] in bead['virtual_site']['parents']]
        assert np.array_equal(got[:, index], got[:, parents].mean(axis=1))


def test_physical_only_leaves_the_virtual_sites_empty():
    data, block = mapping(), frames()
    got = coordinates_many(data, block, scaled=True,
                           representation_mode='physical_only_ring_constrained')
    virtual = [i for i, bead in enumerate(data['beads']) if bead.get('virtual_site')]
    assert not got[:, virtual].any()


def test_a_float32_trajectory_gives_the_numbers_its_python_floats_would():
    """MDAnalysis hands positions over as float32; `.tolist()` widens them exactly and so must the block."""
    data = mapping()
    block = frames(dtype=np.float32)
    assert np.array_equal(coordinates_many(data, block, scaled=True),
                          per_frame(data, block, scaled=True))


def test_atom_ids_name_the_atom_each_column_holds():
    data = mapping(atoms=range(100, 112))
    block, ids = frames(), [100 + index for index in range(12)]
    got = coordinates_many(data, block, atom_ids=ids, scaled=True)
    assert np.array_equal(got, per_frame(data, block, atom_ids=ids, scaled=True))


def test_a_permuted_atom_id_list_is_read_through_the_same_lookup():
    order = RNG.permutation(12)
    data = mapping(atoms=range(100, 112))
    canonical = frames()
    block = canonical[:, order, :]
    ids = [100 + int(index) for index in order]
    got = coordinates_many(data, block, atom_ids=ids, scaled=True)
    assert np.array_equal(got, per_frame(data, block, atom_ids=ids, scaled=True))
    assert np.array_equal(got, per_frame(data, canonical, atom_ids=list(range(100, 112)), scaled=True))


def test_a_block_boundary_changes_no_value():
    """A frame's beads are its own: two half blocks must stack to the whole one, bit for bit."""
    data, block = mapping(), frames(count=9)
    whole = coordinates_many(data, block, scaled=True)
    halves = np.concatenate([coordinates_many(data, block[:4], scaled=True),
                             coordinates_many(data, block[4:], scaled=True)])
    assert np.array_equal(whole, halves)


def test_one_frame_is_a_one_row_block():
    data, block = mapping(), frames(count=1)
    got = coordinates_many(data, block, scaled=True)
    assert got.shape == (1, len(data['beads']), 3)
    assert np.array_equal(got[0], coordinates(data, block[0].tolist(), scaled=True))


def test_a_two_dimensional_array_is_refused_rather_than_read_as_frames_of_atoms():
    with pytest.raises(ValueError, match='frame, atom, 3'):
        coordinates_many(mapping(), frames()[0])


def test_an_unknown_representation_is_refused():
    with pytest.raises(ValueError, match='Unknown carbohydrate representation'):
        coordinates_many(mapping(), frames(), representation_mode='all-atom')
