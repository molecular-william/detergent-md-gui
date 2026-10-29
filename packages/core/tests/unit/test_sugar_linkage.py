"""The linkage seed: the reference's stiffness where an entry matches, and the derived length recorded.

The reference fixes one inter-residue bond per disaccharide -- 6200 for sucrose, 9000 for trehalose, 11250
for lactose -- and this writer gave every non-ring bond the same 5000, the sugar-to-alkyl link and the
bonds along a detergent tail included. The stiffness now comes from the reference when the connectivity
identifies an entry; the length stays derived from the mapped geometry, with the reference's value written
beside it, because a published length on local coordinates starts a run by pulling the system onto someone
else's structure.
"""
from dashboard import paths
from dashboard.models.mappings import context as mapping_context
from dashboard.models.sugars import candidate, reference
from dashboard.models.sugars.topology import topology

MOLECULES = paths.DEFAULT.project_root / 'molecules'


def structure(name):
    return mapping_context.as_structure(mapping_context.build_context(MOLECULES, name))


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


def generated(name):
    selected = structure(name)
    return topology(candidate(selected, name), selected, residue_name=name)


def test_the_sucrose_linkage_takes_the_references_stiffness():
    itp = generated('Sucrose')
    rows = sections(itp)['bonds']
    assert len(rows) == 1, 'sucrose has exactly one non-ring bond, the linkage'
    assert float(rows[0][4]) == 6200.0
    assert 'linkage of SUCR' in itp


def test_the_linkage_length_stays_derived_while_the_reference_value_is_recorded():
    itp = generated('Sucrose')
    length = float(sections(itp)['bonds'][0][3])
    assert length != 0.369, 'the published length is not imposed on local coordinates'
    assert abs(length - 0.369) < 0.15, length
    assert 'reference length 0.369' in itp


def test_a_sugar_carrying_a_chain_takes_the_reference_stiffness_for_its_link_only():
    """DDM is a maltoside with a dodecyl chain: the sugar-sugar bond follows LAC, the rest does not."""
    forces = {float(row[4]) for row in sections(generated('DDM'))['bonds']}
    assert 11250.0 in forces, 'the sugar-sugar linkage takes lactose stiffness'
    assert 5000.0 in forces, 'the tail and the sugar-alkyl link keep the generic seed'


def test_the_delta_table_reports_the_link_beside_the_ring_constraints():
    delta = reference.parameter_delta(generated('Sucrose'), 'SUCR')
    assert [row['residue'] for row in delta] == [1, 1, 1, 2, 2, 2, 'link']
    link = delta[-1]
    assert link['pair'] == ['A', 'A']
    assert link['reference'] == 0.369
    assert link['reference_force'] == 6200.0
    assert link['generated_force'] == 6200.0
    assert link['generated'] is not None and link['relative'] is not None


def test_a_mapping_without_a_reference_match_keeps_the_generic_seed():
    """A molecule the templates cover but no entry matches must not borrow anyone's linkage."""
    selected = structure('Sucrose')
    data = candidate(selected, 'Sucrose')
    data['reference'] = None
    itp = topology(data, selected, residue_name='SUCR')
    assert float(sections(itp)['bonds'][0][4]) == 5000.0


def test_a_cyclic_glycan_maps_and_takes_its_reference_linkage():
    """Trehalose: alpha,alpha-1,1, both anomeric carbons joined, so there is no acceptor end to order against.

    The recogniser used to refuse this outright -- "Cyclic glycan needs explicit linkage ordering" -- because its
    walk arrived back at an anomeric carbon it had already seen. Both rings are equivalent, so the walk stops, and
    the reference's own trehalose entry supplies the linkage stiffness the same way it does for sucrose.
    """
    itp = generated('Trehalose')
    rows = sections(itp)['bonds']

    assert len(rows) == 1, 'trehalose has exactly one non-ring bond, the 1,1 linkage'
    assert float(rows[0][4]) == 9000.0, 'the reference fixes 9000 for trehalose'
    assert 'linkage of TREH' in itp
