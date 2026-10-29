"""The draft's constraints against the geometry a mapped structure actually has.

A ring's constraints are fitted to one conformer -- the isolated molecule's MMFF structure -- and then handed to a
simulation whose molecule came from somewhere else. This pins the measurement of that difference on geometry whose
answer is known by hand, so the number reported for a real draft can be read as a number rather than as a plausibility.

The pairing rule is pinned too, because it is the one assumption the measurement rests on: a run renames its beads
`B01..` while the mapping calls them `S1A`/`TAIL2`, so names match in one direction and never in the other, and the
report has to say which route it took rather than quietly guessing.
"""
from __future__ import annotations

import math

import pytest
from detergent_validation.analysis.runs import draft_geometry

SIDE = 0.30
SCALE = 1.15

#: A three-bead ring, equilateral to the last digit that matters, and the same ring with one vertex pulled in.
DRAFT = {'molecule_id': 'TEST', 'beads': [
    {'name': 'R1', 'position': [0.0, 0.0, 0.0]},
    {'name': 'R2', 'position': [SIDE, 0.0, 0.0]},
    {'name': 'R3', 'position': [SIDE / 2, SIDE * math.sqrt(3) / 2, 0.0]},
]}
MAPPED = {'R1': [0.0, 0.0, 0.0], 'R2': [SIDE, 0.0, 0.0], 'R3': [SIDE / 2, 0.20, 0.0]}


def rows(mapped=None, names=('R1', 'R2', 'R3')):
    """A structure as a `.gro` reader returns it: one `(name, position)` per bead, in the file's own order."""
    mapped = mapped or MAPPED
    return [(name, list(mapped[key])) for name, key in zip(names, MAPPED)]


def topology(scale=SCALE, function=1, length=None):
    """The generated topology a drawft carries: the atoms, then the ring's three constraints."""
    lines = ['; a draft', '[ moleculetype ]', 'TEST 1', '', '[ atoms ]']
    for index, bead in enumerate(DRAFT['beads'], 1):
        lines.append(f'{index} SP1r 1 TEST {bead["name"]} {index} 0 72')
    lines += ['', '[ constraints ]']
    for first, second in ((1, 2), (1, 3), (2, 3)):
        value = length if length is not None else round(SIDE * scale, 6)
        lines.append(f'{first} {second} {function} {value:g}')
    return '\n'.join(lines) + '\n'


def draft(scale=SCALE, function=1, length=None):
    return {**DRAFT, 'topology': topology(scale=scale, function=function, length=length)}


def test_the_constraints_are_named_through_the_drafts_own_atoms_section():
    rows = draft_geometry.constraints(topology())

    assert [row['beads'] for row in rows] == [('R1', 'R2'), ('R1', 'R3'), ('R2', 'R3')]
    assert [row['length_nm'] for row in rows] == [pytest.approx(SIDE * SCALE)] * 3


def test_the_measurement_is_the_constraint_against_the_mapped_distance():
    measured = draft_geometry.measure(draft(), rows())

    assert measured['molecule_id'] == 'TEST' and measured['beads'] == 3
    # The draft is the equilateral triangle, so every constraint asks for the same 15% extension of it.
    assert [row['constraint_nm'] for row in measured['pairs']] == [pytest.approx(SIDE * SCALE)] * 3
    assert [row['draft_nm'] for row in measured['pairs']] == [pytest.approx(SIDE, abs=1e-6)] * 3
    # The mapped ring has a shorter side, and it is the two pairs through the pulled-in vertex.
    by_pair = {tuple(row['beads']): row for row in measured['pairs']}
    assert by_pair[('R1', 'R2')]['mapped_nm'] == pytest.approx(SIDE, abs=1e-6)
    assert by_pair[('R1', 'R2')]['constraint_over_mapped_pct'] == pytest.approx(15.0, abs=0.05)
    assert by_pair[('R1', 'R3')]['mapped_nm'] == pytest.approx(math.hypot(SIDE / 2, 0.20), abs=1e-6)
    assert by_pair[('R1', 'R3')]['constraint_over_mapped_pct'] == pytest.approx(38.0, abs=0.5)


def test_the_largest_mismatch_leads_because_that_is_the_one_that_has_to_be_acted_on():
    measured = draft_geometry.measure(draft(), rows())

    assert measured['pairs'][0]['beads'] in (['R1', 'R3'], ['R2', 'R3'])
    assert measured['largest_over_nm'] == pytest.approx(measured['pairs'][0]['constraint_over_mapped_nm'])
    assert measured['largest_over_pct'] == pytest.approx(38.0, abs=0.5)
    assert 'constraint' in draft_geometry.format_report(measured)


def test_a_run_spells_its_beads_differently_and_the_pairing_says_so():
    """`B01..` in a run's mapped structure, `R1..` in the mapping: the indices are what travel between the two."""
    measured = draft_geometry.measure(draft(), rows(names=('B01', 'B02', 'B03')))

    assert measured['paired_by'] == draft_geometry.BY_ORDER
    assert measured['largest_over_pct'] == pytest.approx(38.0, abs=0.5)


def test_a_structure_that_names_the_beads_is_paired_by_name_even_out_of_order():
    measured = draft_geometry.measure(draft(), rows(names=('R3', 'R1', 'R2')))

    assert measured['paired_by'] == draft_geometry.BY_NAME
    assert measured['largest_over_pct'] == pytest.approx(38.0, abs=0.5)


def test_a_structure_that_is_not_this_molecule_is_refused():
    with pytest.raises(ValueError, match='do not describe the same molecule'):
        draft_geometry.measure(draft(), rows(names=('B01', 'B02')))


def test_only_a_length_constraint_is_measurable():
    with pytest.raises(ValueError, match='function 2'):
        draft_geometry.constraints(topology(function=2))


def test_a_gro_is_read_in_file_order_and_in_nanometres(tmp_path):
    path = tmp_path / 'mapped.gro'
    path.write_text('Written by the test\n'
                    '    3\n'
                    '    1DDM    B01    1   0.100   0.200   0.300\n'
                    '    1DDM    B02    2   0.400   0.200   0.300\n'
                    '    1DDM    B03    3   0.250   0.373   0.300\n'
                    '   5.00000   5.00000   5.00000\n')

    rows = draft_geometry.read_gro(path)

    assert [name for name, _ in rows] == ['B01', 'B02', 'B03']
    assert rows[1][1] == pytest.approx([0.4, 0.2, 0.3])


def test_a_gro_that_claims_more_atoms_than_it_has_is_refused(tmp_path):
    path = tmp_path / 'short.gro'
    path.write_text('Written by the test\n    4\n    1DDM    B01    1   0.100   0.200   0.300\n')

    with pytest.raises(ValueError, match='4 atoms claimed, 1 present'):
        draft_geometry.read_gro(path)
