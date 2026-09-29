"""The generated topology reads like the reference it follows.

The writer used to name every atom B01..B08 inside one residue, so a two-residue reference model came out
as a single residue and could not be compared bead for bead with the published entry. Atom names follow
the reference's per-residue A/B/C/VS convention, the residue number comes from the bead's own residue, and
the pairs the reference constrains are the pairs this topology constrains.
"""
import pytest

from dashboard import paths
from dashboard.models.mappings import context as mapping_context
from dashboard.models.sugars import candidate, reference
from dashboard.models.sugars.topology import topology

MOLECULES = paths.DEFAULT.project_root / 'molecules'


@pytest.fixture(scope='module')
def sucrose():
    return mapping_context.as_structure(mapping_context.build_context(MOLECULES, 'Sucrose'))


@pytest.fixture(scope='module')
def itp(sucrose):
    return topology(candidate(sucrose, 'Sucrose'), sucrose, residue_name='SUCR')


def sections(text):
    current, table = None, {}
    for line in text.splitlines():
        clean = line.split(';')[0].strip()
        if clean.startswith('['):
            current = clean.strip('[] ').lower()
            table.setdefault(current, [])
        elif clean and current:
            table[current].append(clean.split())
    return table


def pairs(rows):
    return [(int(row[0]), int(row[1])) for row in rows]


def test_the_atom_lines_carry_the_reference_names_and_residue_numbers(itp):
    rows = sections(itp)['atoms']
    assert [(int(row[2]), row[4]) for row in rows] == [(1, 'A'), (1, 'B'), (1, 'C'), (1, 'VS'),
                                                      (2, 'A'), (2, 'B'), (2, 'C'), (2, 'VS')]
    assert [row[1] for row in rows] == ['SP1r', 'SP4r', 'SP1r', 'TC4', 'SN6', 'SP4r', 'SP1r', 'TC4']
    assert [int(row[3] == 'SUCR') for row in rows] == [1] * 8
    assert [float(row[7]) for row in rows] == [54.0, 54.0, 54.0, 0.0, 54.0, 54.0, 54.0, 0.0]


def test_the_topology_has_two_residues_not_one(itp):
    rows = sections(itp)['atoms']
    assert {int(row[2]) for row in rows} == {1, 2}


def test_each_virtual_site_is_built_from_its_own_residues_beads(itp):
    sites = sections(itp)['virtual_sitesn']
    assert [(int(row[0]), [int(field) for field in row[2:]]) for row in sites] == [(4, [1, 2, 3]),
                                                                                  (8, [5, 6, 7])]


def test_the_ring_constraint_pairs_are_the_reference_pairs(itp):
    """The reference constrains each ring as a triangle, and the partitions give the same triangle."""
    expected = [(item['i'], item['j']) for item in reference.entry('SUCR')['constraints']]
    assert pairs(sections(itp)['constraints']) == expected


def test_the_linkage_bond_joins_the_two_glycosidic_beads(itp):
    reference_bond = [(item['i'], item['j']) for item in reference.entry('SUCR')['bonds']]
    assert reference_bond == [(1, 5)]
    assert (1, 5) in pairs(sections(itp)['bonds'])


def test_a_bead_without_a_reference_letter_keeps_a_positional_name(sucrose):
    """Leftover fragments are not reference residues, so they must not borrow a reference letter."""
    data = candidate(mapping_context.as_structure(
        mapping_context.build_context(MOLECULES, 'DDM')), 'DDM')
    generated = topology(data, mapping_context.as_structure(
        mapping_context.build_context(MOLECULES, 'DDM')), residue_name='DDM')
    names = [row[4] for row in sections(generated)['atoms']]
    assert 'A' in names
    assert any(name.startswith('B') and name[1:].isdigit() for name in names)


def test_the_run_own_files_name_beads_by_position_instead(sucrose):
    """A run identifies a bead by position, and the topology has to agree with the mapped coordinates.

    `gmx grompp` reconciles a topology against a `.gro` by atom name, and a two-residue sugar names two
    beads `A`: with letters the CG topology stage counts eight mismatches and refuses the run with "Too
    many warnings (1)". The `.map`, the `.ndx` and the mapped trajectory all say `B01..`, so the topology
    a run is prepared with says the same.
    """
    names = [row[4] for row in sections(topology(candidate(sucrose, 'Sucrose'), sucrose,
                                                residue_name='SUCR', export_names=True))['atoms']]
    assert names == [f'B{index:02d}' for index in range(1, 9)]
    assert len(set(names)) == len(names)


def test_the_seeded_topology_a_run_is_prepared_from_carries_them(sucrose):
    from dashboard.models.molecules import draft

    generated = draft.initial_topology(candidate(sucrose, 'Sucrose'), molecule_root=MOLECULES,
                                       residue_name='LIG1')
    assert [row[4] for row in sections(generated)['atoms']] == [f'B{index:02d}' for index in range(1, 9)]


def test_only_the_name_column_differs_between_the_two_conventions(sucrose):
    """Which file gets which names is a presentation choice; no term may change with it."""
    letters = topology(candidate(sucrose, 'Sucrose'), sucrose, residue_name='SUCR')
    exports = topology(candidate(sucrose, 'Sucrose'), sucrose, residue_name='SUCR', export_names=True)
    body = lambda text: [row[:4] + row[5:] for row in (line.split() for line in text.splitlines()
                                                      if line and not line.startswith(';'))]
    assert body(letters) == body(exports)
