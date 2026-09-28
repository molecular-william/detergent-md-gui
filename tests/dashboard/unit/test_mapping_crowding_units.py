"""The bead-crowding metric, in one unit and in three dimensions.

It reported that every pair of beads overlapped for any molecule chosen in the dashboard: the bead radii
were converted from nanometres to angstroms while the distances they were compared against stayed in
nanometres, so the comparison was always true. It also measured the distance in the xy projection only,
which is not what a three-dimensional overlap is.
"""
from dashboard import paths
from dashboard.models.mappings import context as mapping_context
from dashboard.models.mappings import graph
from dashboard.models.sugars import candidate

MOLECULES = paths.DEFAULT.project_root / 'molecules'


def report_for(molecule):
    structure = mapping_context.as_structure(mapping_context.build_context(MOLECULES, molecule))
    return graph.validate(candidate(structure, molecule), structure)


def test_a_real_mapping_is_no_longer_reported_as_fully_crowded():
    """Measured: 10 of sucrose's 15 bead pairs are closer than the sum of their radii, which is the
    paper's model rather than a defect -- an S-bead ring at 0.3 nm constraints interpenetrates. What was
    wrong was every pair counting, with a crowding of 0.947."""
    report = report_for('Sucrose')
    assert report['overlap_pairs'] == 10, report['overlap_pairs']
    assert report['overlap_crowding'] < 0.3, f"was 0.947 before the fix, measured {report['overlap_crowding']}"


def test_a_sugar_with_a_chain_is_measured_the_same_way():
    report = report_for('DDM')
    assert report['overlap_crowding'] < 0.2, f"measured {report['overlap_crowding']}"


def test_the_metric_does_not_depend_on_which_unit_the_structure_is_in():
    """The same molecule in angstroms and in nanometres must give the same crowding."""
    structure = mapping_context.as_structure(mapping_context.build_context(MOLECULES, 'Sucrose'))
    data = candidate(structure, 'Sucrose')
    in_nm = graph.validate(data, structure)['overlap_crowding']
    legacy = {key: value for key, value in structure.items() if key not in ('molecule_id', 'snapshot')}
    legacy['atoms'] = [{**atom, 'xyz': [value * 10 for value in atom['xyz']]} for atom in structure['atoms']]
    in_angstrom = graph.validate(data, legacy)['overlap_crowding']
    assert abs(in_nm - in_angstrom) < 0.01, f'{in_nm} against {in_angstrom}'
