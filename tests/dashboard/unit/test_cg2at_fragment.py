"""The CG2AT2 fragment a mapping implies: every atom accounted for, in a shape the converter reads.

CG2AT2 converts a coarse-grained residue from a fragment in its own database (`[ BEAD ]` sections of ATOM lines, plus an
itp), and the vendored database covers lipids and sterols only -- `non_protein/` has 48 of them and no detergent, which is
why a DDM complex stops at "DDM is not in the fragment database!". The mapping already says which atoms each bead covers and
the molecule's own topology says what every atom is, so the fragment is a rewrite of data we hold.

These tests pin the four decisions that make one: hydrogens follow their heavy neighbour, every bead owns at least one atom
(the converter's centre-of-mass routine indexes atom 1 of every bead, and duplicated atoms would be written out twice), bead
names fit the four characters a PDB atom-name field holds, and the file opens with a `[ BEAD ]` header because the reader
stops on any line that arrives before one.
"""
import json

from detergent_pdc.execution.scripts import cg2at_fragment as fragment

MAPPING = {
    'name': 'DDM_CG_20261021',
    'beads': [
        {'name': 'S1A', 'atoms': [1, 2]},
        {'name': 'S1B', 'atoms': [3, 4]},
        {'name': 'S1VS', 'atoms': []},
        {'name': 'TAIL1', 'atoms': [5, 6]},
        {'name': 'TAIL2', 'atoms': [7]},
    ],
    'connections': [['S1A', 'S1B'], ['S1A', 'TAIL1'], ['TAIL1', 'TAIL2']],
}

TOPOLOGY = """[ atomtypes ]
C1  6  12.0110  0.0  A  0.3  0.2

[ moleculetype ]
; Name nrexcl
LIG1  3

[ atoms ]
; nr type resnr resid atom cgnr charge mass
1  C1  1  LIG1  C1  1  0.0  12.0110
2  C1  1  LIG1  C2  2  0.0  12.0110
3  C1  1  LIG1  C3  3  0.0  12.0110
4  C1  1  LIG1  C4  4  0.0  12.0110
5  C1  1  LIG1  C5  5  0.0  12.0110
6  C1  1  LIG1  C6  6  0.0  12.0110
7  C1  1  LIG1  C7  7  0.0  12.0110
8  H1  1  LIG1  H1  8  0.0   1.0080
9  H1  1  LIG1  H2  9  0.0   1.0080

[ bonds ]
1  2  1  0.15  250000
1  8  1  0.10  250000
3  9  1  0.10  250000
"""

COORDINATES = """ATOM      1  C1  LIG1    1       0.000   0.000   0.000  1.00  0.00           C
ATOM      2  C2  LIG1    1       1.000   0.000   0.000  1.00  0.00           C
ATOM      3  C3  LIG1    1       2.000   0.000   0.000  1.00  0.00           C
ATOM      4  C4  LIG1    1       3.000   0.000   0.000  1.00  0.00           C
ATOM      5  C5  LIG1    1       4.000   0.000   0.000  1.00  0.00           C
ATOM      6  C6  LIG1    1       5.000   0.000   0.000  1.00  0.00           C
ATOM      7  C7  LIG1    1       6.000   0.000   0.000  1.00  0.00           C
ATOM      8  H1  LIG1    1       0.000   1.000   0.000  1.00  0.00           H
ATOM      9  H2  LIG1    1       2.000   1.000   0.000  1.00  0.00           H
"""


def test_a_hydrogen_follows_the_bead_of_the_heavy_atom_it_is_bonded_to():
    beads = fragment.bead_atoms(MAPPING, TOPOLOGY)

    assert 8 in beads['S1A'], 'H1 is bonded to C1, which S1A holds'
    assert 9 in beads['S1B'], 'H2 is bonded to C3, which S1B holds'


def test_every_atom_lands_in_exactly_one_bead():
    beads = fragment.bead_atoms(MAPPING, TOPOLOGY)
    owned = [number for numbers in beads.values() for number in numbers]

    assert sorted(owned) == list(range(1, 10)), 'the fragment must describe the whole molecule, hydrogens included'
    assert len(owned) == len(set(owned)), 'an atom in two beads is written out twice by the converter'


def test_a_virtual_site_borrows_one_atom_rather_than_staying_empty():
    """An empty section raised `KeyError: 1` inside the converter's centre-of-mass routine."""
    beads = fragment.bead_atoms(MAPPING, TOPOLOGY)

    assert beads['S1VS'], 'a virtual site must own at least one atom'
    owned = [number for numbers in beads.values() for number in numbers]
    assert len(owned) == len(set(owned))
    assert sorted(owned) == list(range(1, 10))


def test_a_bead_naming_an_atom_the_topology_lacks_is_refused():
    import pytest

    broken = {'name': 'X', 'beads': [{'name': 'S1A', 'atoms': [99]}], 'connections': []}
    with pytest.raises(ValueError, match='the topology does not have'):
        fragment.bead_atoms(broken, TOPOLOGY)


def test_bead_names_are_cut_to_the_four_characters_a_pdb_field_holds():
    names = fragment.safe_names(['S1A', 'S1VS', 'TAIL1', 'TAIL2', 'TAIL3'])

    assert names['S1A'] == 'S1A' and names['S1VS'] == 'S1VS', 'a short name is left alone'
    assert names['TAIL1'] == 'TAI1' and names['TAIL2'] == 'TAI2' and names['TAIL3'] == 'TAI3'
    assert len(set(names.values())) == len(names), 'a collision would attribute one bead atoms to another'


def test_the_fragment_file_opens_with_a_bead_header(tmp_path):
    """The reader sets `bead` from a `[ BEAD ]` line and stops on "error reading" for anything before one."""
    beads = fragment.bead_atoms(MAPPING, TOPOLOGY)
    pdb = fragment.fragment_pdb('DDM', beads, fragment.read_pdb_atoms(_write(tmp_path, COORDINATES, 'lig.pdb')))

    assert pdb.splitlines()[0].startswith('[ '), 'a comment or blank line before the first section stops the conversion'
    assert [line.split()[1] for line in pdb.splitlines() if line.startswith('[')] == list(beads)
    assert pdb.count('ATOM') == 9


def test_the_topology_is_carried_renamed_and_not_reparameterised():
    itp = fragment.fragment_itp(TOPOLOGY, 'DDM')

    assert 'DDM      3' in itp and 'LIG1' not in itp, 'the molecule keeps its parameters, renamed'
    atoms = [line for line in itp.splitlines() if line.strip().startswith('1 ') and 'DDM' in line]
    assert atoms and 'DDM' in atoms[0]


def test_the_molecule_itp_carries_no_force_field_sections():
    """GROMACS refuses `[ atomtypes ]` in an itp included after a moleculetype, which is what a converted complex is."""
    itp = fragment.fragment_itp(TOPOLOGY, 'DDM')

    assert itp.splitlines()[0].startswith('[ moleculetype ]'), 'the force-field preamble belongs in the force field'
    assert '[ atomtypes ]' not in itp and 'C1  6  12.0110' not in itp


def test_the_preamble_sections_are_reported_rather_than_dropped():
    assert fragment.atomtype_lines(TOPOLOGY) == ['C1  6  12.0110  0.0  A  0.3  0.2']
    assert fragment.pairtype_lines(TOPOLOGY) == [], 'no pairtypes section, no pairs'


def test_the_force_field_gains_the_molecules_types_and_pairs(tmp_path):
    tree = tmp_path / 'charmm36.ff'
    tree.mkdir()
    (tree / 'ffnonbonded.itp').write_text('[ atomtypes ]\nCA  6  12.0  0.0  A  0.3  0.2\n\n'
                                          '[ pairtypes ]\nCA  CA  1  0.3  0.2\n')
    (tree / 'ffbonded.itp').write_text('[ bondtypes ]\n')
    out = fragment.extend_forcefield(tree, ['CR  6  12.0110  0.0  A  0.36  0.23'], tmp_path / 'ddm.ff',
                                     ['CR  CR  1  0.34  0.04'])

    written = (out / 'ffnonbonded.itp').read_text()
    types, pairs = written.split('[ pairtypes ]')
    assert 'CR  6  12.0110' in types, 'an atomtype must sit inside [ atomtypes ], not after its header'
    assert 'CR  CR  1  0.34  0.04' in pairs, 'a pair entry must sit inside [ pairtypes ]'
    assert (out / 'ffbonded.itp').is_symlink(), 'the rest of the tree is linked, not copied'
    assert (tree / 'ffnonbonded.itp').read_text().startswith('[ atomtypes ]\nCA'), 'the vendored tree is not edited'


def test_the_renamed_gro_changes_only_the_named_beads(tmp_path):
    def line(residue, atom, number):
        # A gro's columns: residue number 1-5, residue name 6-10, atom name 11-15, atom number 16-20.
        return f'{number:5d}{residue:<5}{atom:>5}{number:5d}{0.1 * number:8.3f}{0.2:8.3f}{0.3:8.3f}\n'

    gro = ('system\n'
           '    4\n'
           + line('DDM', 'TAIL1', 1) + line('DDM', 'S1A', 2)
           + line('W', 'W', 3) + line('DDM', 'TAIL2', 4) +
           '   8.00000   8.00000   8.00000\n')
    names = fragment.safe_names(['TAIL1', 'TAIL2', 'S1A'])
    out = fragment.renamed_gro(gro, 'DDM', names).splitlines()

    assert out[2][10:15].strip() == 'TAI1' and out[3][10:15].strip() == 'S1A'
    assert out[4][10:15].strip() == 'W', 'another residue is not touched'
    assert out[5][10:15].strip() == 'TAI2'
    assert out[-1].strip() == '8.00000   8.00000   8.00000', 'the box line is what the simulation wrote'


def test_writing_a_fragment_reports_what_it_did(tmp_path):
    mapping = tmp_path / 'mapping.json'
    mapping.write_text(json.dumps(MAPPING))
    topology, coordinates = _write(tmp_path, TOPOLOGY, 'lig.itp'), _write(tmp_path, COORDINATES, 'lig.pdb')

    written = fragment.write(tmp_path / 'out', mapping, topology, coordinates, 'DDM')

    assert written['atoms'] == 9 and written['residue'] == 'DDM'
    assert written['renamed'] == {'TAIL1': 'TAI1', 'TAIL2': 'TAI2'}
    assert (tmp_path / 'out/DDM.pdb').exists() and (tmp_path / 'out/DDM.itp').exists()


def _write(directory, text, name):
    path = directory / name
    path.write_text(text)
    return path
