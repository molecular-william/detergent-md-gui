"""Coordinate units, which one place now decides.

A context structure holds nanometres; the packaged SwissParam reference holds angstroms. The sugar
topology writer and the mapping export divided by ten unconditionally, so for every molecule chosen in
the dashboard the generated constraint lengths came out about 0.03 nm where the reference has 0.3 to
0.47 nm -- a factor of ten, which is invisible in a plot of a molecule and fatal to a CG model.
"""
from dashboard import paths
from dashboard.models.mappings import context as mapping_context
from dashboard.models.molecules import packaged
from dashboard.models.sugars import angstrom_factor

MOLECULES = paths.DEFAULT.project_root / 'molecules'


def context_structure(name):
    return mapping_context.as_structure(mapping_context.build_context(MOLECULES, name))


def test_a_context_structure_is_in_nanometres():
    structure = context_structure('Sucrose')
    assert angstrom_factor(structure) == 1.0
    distances = [abs(atom['xyz'][0]) for atom in structure['atoms'] if atom.get('heavy')]
    assert max(distances) < 2.0, 'nanometres, not angstroms: sucrose is about one nanometre across'


def test_the_packaged_reference_is_in_angstroms():
    structure = packaged.molecule()
    assert angstrom_factor(structure) == 0.1
    assert max(abs(atom['xyz'][0]) for atom in structure['atoms'] if atom.get('heavy')) > 2.0


def test_the_adapter_carries_the_markers_that_make_units_decidable():
    """The legacy adapter shape used to drop them, which is why these consumers guessed angstroms."""
    context = mapping_context.build_context(MOLECULES, 'Sucrose')
    structure = mapping_context.as_structure(context)
    assert structure['molecule_id'] == context['molecule_id']
    assert structure['snapshot'] == context['snapshot']


def test_every_coordinate_consumer_agrees_on_the_factor():
    """One rule, so the lengths a topology writes match the coordinates an export emits."""
    structure = context_structure('Sucrose')
    assert angstrom_factor(structure) == 1.0
    assert angstrom_factor({k: v for k, v in structure.items() if k not in ('molecule_id', 'snapshot')}) == 0.1
