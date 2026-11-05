"""The remainder splitter never cuts a bead across a branch.

`_walk` followed one neighbour at a time and `_balanced` sliced the resulting list, so at a branch it
walked one arm to its dead end, appended the untouched arms in raw atom-id order and then cut across the
join. On LMNG that made one bead of two headgroup linkers and a chain end, spanning 7.6 A, with atoms
that are not one connected group in the bond graph -- which this project's own validator rejects.

The fixture here is LMNG's own remainder, by connectivity and atom numbering only: atom 11 is the
quaternary carbon, `1..10` and `12..21` are its two long chains, and `22` and `46` are the one-atom
linkers into the two symmetric sugar arms.
"""
from dashboard.models.sugars import coords


def graph_of(elements, bonds, ids=None):
    atoms = {index: {'id': index, 'element': element, 'heavy': True}
             for index, element in zip(ids or range(1, len(elements) + 1), elements)}
    adjacency = {index: set() for index in atoms}
    for first, second in bonds:
        adjacency[first].add(second)
        adjacency[second].add(first)
    return atoms, adjacency


def connected(adjacency, group):
    seen = {group[0]}
    pending = [group[0]]
    while pending:
        for neighbour in adjacency[pending.pop()] & set(group) - seen:
            seen.add(neighbour)
            pending.append(neighbour)
    return seen == set(group)


def lmng_remainder():
    bonds = [(11, 10), (11, 12), (11, 22), (11, 46)]
    bonds += [(index, index + 1) for index in range(1, 10)]
    bonds += [(index, index + 1) for index in range(12, 21)]
    return graph_of(['C'] * 23, bonds, ids=list(range(1, 23)) + [46])


def test_a_branch_bead_joins_the_vertex_to_one_atom_of_each_symmetric_arm():
    atoms, adjacency = lmng_remainder()
    beads, notes = coords.remainder_beads(atoms, adjacency, set())
    assert next(bead for bead in beads if 11 in bead['atoms'])['atoms'] == [11, 22, 46]
    assert notes == []


def test_the_two_long_chains_are_partitioned_separately_from_the_branch():
    atoms, adjacency = lmng_remainder()
    beads, _notes = coords.remainder_beads(atoms, adjacency, set())
    assert [bead['atoms'] for bead in beads] == [[11, 22, 46], [1, 2, 3, 4], [5, 6, 7], [8, 9, 10],
                                                [12, 13, 14, 15], [16, 17, 18], [19, 20, 21]]


def test_no_bead_crosses_the_branch_so_every_bead_is_one_connected_group():
    atoms, adjacency = lmng_remainder()
    beads, _notes = coords.remainder_beads(atoms, adjacency, set())
    assert len(beads) == 7, 'the branch bead plus three chunks for each chain'
    for bead in beads:
        assert 1 <= len(bead['atoms']) <= 4, bead
        assert connected(adjacency, bead['atoms']), bead


def test_three_equally_long_arms_take_one_atom_each_and_stay_inside_four_atoms():
    """A vertex whose arms all tie is symmetric all round; the branch bead holds the first three."""
    bonds = []
    for root in (2, 6, 10):
        bonds.append((1, root))
        bonds += [(root + step, root + step + 1) for step in range(3)]
    atoms, adjacency = graph_of(['C'] * 13, bonds)
    beads, _notes = coords.remainder_beads(atoms, adjacency, set())
    branch = next(bead for bead in beads if 1 in bead['atoms'])
    assert branch['atoms'] == [1, 2, 6, 10], 'the vertex and the root of three tied arms'
    assert len(branch['atoms']) == 4
    assert [len(bead['atoms']) for bead in beads] == [4, 3, 3, 3]


def test_a_component_with_a_cycle_keeps_the_old_draft_path():
    """A ring no template covers is still drafted as before; the caller carries the warning."""
    atoms, adjacency = graph_of(['C', 'C', 'C', 'C', 'C', 'C'],
                                [(1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 1)])
    beads, notes = coords.remainder_beads(atoms, adjacency, set())
    assert all(bead['name'].startswith('RING') for bead in beads)
    assert notes
