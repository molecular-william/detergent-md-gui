"""The system view: a .gro becomes a PDB the viewer can read, with the solvent left out.

The claims worth pinning are the ones a picture would hide: water and ions are dropped by default, the coordinates
are converted from nanometres to the Angstroms PDB uses, the residue column separates protein from detergent, a
malformed .gro is an error rather than a half-drawn system, **and the element column states each bead's own size
class** -- the stand-in a viewer resolves a radius from (`ngl-beads.js`), which is the difference between beads drawn
in the model's 0.264/0.230/0.191 nm proportion and beads drawn all at one size.

The fixtures are formatted rather than hand-typed: a .gro is fixed-width, and a hand-typed line that looks right
shifts every float by a character.
"""
import pytest

from dashboard.execution.adapters import pdc_view
from tests.dashboard.support import DDM_BEADS, DDM_BONDS, DDM_CLASSES, DDM_CONSTRAINTS, DDM_TYPES, ddm_moleculetype

#: The stand-in element each class is written with -- `models/compositions/topology.py`'s own choice, written out here
#: so this file fails if the writer's and the viewer's tables ever disagree.
ELEMENTS = {'R': 'C', 'S': 'N', 'T': 'H'}


def _line(residue, name, index, position):
    """One .gro atom line: 5-char residue number, 5-char residue, 5-char name, 5-char number, three 8.3f values."""
    return (f'{index:5d}{residue:<5}{name:>5}{index:5d}'
            + ''.join(f'{value:8.3f}' for value in position))


def _gro(tmp_path, atoms, name='system.gro', count=None):
    declared = len(atoms) if count is None else count
    count_line = f'{declared:5d}' if isinstance(declared, int) else str(declared)
    path = tmp_path / name
    path.write_text('\n'.join(['PDC system', count_line]
                              + [_line(atom[0], atom[1], index, atom[2]) for index, atom in enumerate(atoms, start=1)]
                              + ['  10.00000  10.00000  10.00000']) + '\n')
    return path


ATOMS = (('PRO', 'BB', (1.0, 2.0, 3.0)), ('PRO', 'SC1', (1.1, 2.1, 3.1)),
         ('DDM', 'C1', (4.0, 5.0, 6.0)), ('W', 'W', (7.0, 8.0, 9.0)))


def test_water_and_ions_are_dropped_and_the_rest_kept(tmp_path):
    atoms = pdc_view.read_gro(_gro(tmp_path, ATOMS))
    assert len(atoms) == 4
    records = [line for line in pdc_view.system_pdb(atoms).splitlines() if line.startswith('HETATM')]
    assert len(records) == 3, 'the water bead is not part of the view'
    assert 'WATER AND IONS OMITTED' in pdc_view.system_pdb(atoms)


def test_the_coordinates_are_converted_to_angstrom(tmp_path):
    first = next(line for line in pdc_view.system_pdb(pdc_view.read_gro(_gro(tmp_path, ATOMS))).splitlines()
                 if line.startswith('HETATM'))
    assert abs(float(first[30:38]) - 10.0) < 1e-6      # 1.000 nm -> 10.000 A
    assert abs(float(first[38:46]) - 20.0) < 1e-6
    assert abs(float(first[46:54]) - 30.0) < 1e-6


def test_the_residue_column_separates_protein_from_detergent(tmp_path):
    pdb = pdc_view.system_pdb(pdc_view.read_gro(_gro(tmp_path, ATOMS)))
    residues = {line[12:16].strip(): line[17:20].strip() for line in pdb.splitlines() if line.startswith('HETATM')}
    assert residues['BB'] == 'PRO'
    assert residues['C1'] == 'DET'


def test_solvent_can_be_included_when_that_is_what_is_wanted(tmp_path):
    atoms = pdc_view.read_gro(_gro(tmp_path, ATOMS))
    assert len([line for line in pdc_view.system_pdb(atoms, include_water=True).splitlines()
                if line.startswith('HETATM')]) == 4


def test_a_malformed_gro_is_an_error_rather_than_a_partial_system(tmp_path):
    with pytest.raises(ValueError, match='does not state an atom count'):
        pdc_view.read_gro(_gro(tmp_path, ATOMS, name='bad.gro', count='x'))
    with pytest.raises(ValueError, match='declares 4 atoms'):
        pdc_view.read_gro(_gro(tmp_path, ATOMS[:1], name='short.gro', count=4))
    truncated = tmp_path / 'cut.gro'
    truncated.write_text('PDC system\n    1\n    1PRO      BB    1   1.000   2.000\n')
    with pytest.raises(ValueError, match='truncated atom line'):
        pdc_view.read_gro(truncated)


def _detergent_beads(molecules=2, beads=DDM_BEADS):
    """`molecules` detergents in the moleculetype's own bead order, each its own residue number."""
    return [(2 + molecule, 'DDM', name, (molecule * 3.0 + index * 0.3, 1.0, 2.0))
            for molecule in range(molecules) for index, name in enumerate(beads)]


def _system_gro(tmp_path, atoms, name='system.gro'):
    """A .gro whose lines carry the residue number each bead belongs to.

    `_gro` numbers every residue after its atom, which is what the viewer's own tests want and wrong for a molecule
    of eleven beads: a residue per bead is neither the model nor the thing under test here.
    """
    lines = ['PDC system', f'{len(atoms):5d}']
    lines += [f'{residue_id:5d}{residue:<5}{bead:>5}{index:5d}'
              + ''.join(f'{value:8.3f}' for value in xyz)
              for index, (residue_id, residue, bead, xyz) in enumerate(atoms, start=1)]
    lines.append('  10.00000  10.00000  10.00000')
    path = tmp_path / name
    path.write_text('\n'.join(lines) + '\n')
    return path


def test_the_moleculetype_reader_takes_the_bonds_and_the_constraints_that_hold_the_head_ring(tmp_path):
    """The model's own bonded terms: four `[ bonds ]` and the six `[ constraints ]` NGL draws either way.

    A ring held by constraints is Martini practice, and a viewer draws a constraint as a bond, so both sections are
    the model as far as a picture is concerned. The sections in between ([ angles ], [ dihedrals ], [ virtual_sitesn ],
    [ exclusions ]) are not bonds and must not become any.
    """
    path = tmp_path / 'detergent_CG.itp'
    path.write_text(ddm_moleculetype())

    moleculetype = pdc_view.read_moleculetype(path)

    assert moleculetype['atoms'] == list(DDM_BEADS)
    assert moleculetype['bonds'] == list(DDM_BONDS)
    assert moleculetype['constraints'] == list(DDM_CONSTRAINTS)


def test_a_moleculetype_without_beads_is_an_error_rather_than_a_molecule(tmp_path):
    path = tmp_path / 'empty.itp'
    path.write_text('[ moleculetype ]\nDDM 1\n\n[ bonds ]\n1 2 1 0.4 1000\n')

    with pytest.raises(ValueError, match='declares no atoms'):
        pdc_view.read_moleculetype(path)


def test_each_detergent_molecule_gets_its_own_residue_number(tmp_path):
    """Measured: six detergents were written as residue 1 with one chain, so the file itself said one molecule.

    A viewer cannot separate molecules it is told are one, and the reader's complaint -- bonds between one
    detergent's beads -- starts from a picture that never said which beads belong to which molecule.
    """
    atoms = pdc_view.read_gro(_system_gro(tmp_path, [(1, 'PRO', 'BB', (0.0, 0.0, 0.0))]
                                        + _detergent_beads(molecules=3)))

    numbers = [line[22:26].strip() for line in pdc_view.system_pdb(atoms).splitlines()
               if line.startswith('HETATM')]

    assert len(set(numbers)) == 4, f'the protein and three detergents: {numbers}'
    assert numbers.count(numbers[1]) == 11, 'the eleven beads of one detergent are one residue'


def test_the_models_bonds_are_written_as_conect_records_and_the_remark_says_where_from(tmp_path):
    (tmp_path / 'detergent_CG.itp').write_text(ddm_moleculetype())
    topology = pdc_view.read_moleculetype(tmp_path / 'detergent_CG.itp')
    atoms = pdc_view.read_gro(_system_gro(tmp_path, _detergent_beads(molecules=2)))

    text = pdc_view.system_pdb(atoms, topology=topology)
    conect = [line for line in text.splitlines() if line.startswith('CONECT')]

    assert conect == [f'CONECT{first:5d}{second:5d}' for first, second in
                      [(1, 11), (2, 5), (9, 10), (10, 11), (1, 2), (1, 3), (2, 3), (5, 6), (5, 7), (6, 7),
                       (12, 22), (13, 16), (20, 21), (21, 22), (12, 13), (12, 14), (13, 14), (16, 17), (16, 18),
                       (17, 18)]]
    assert "BONDS ARE THE MODEL'S OWN" in text and '[ constraints ]' in text
    assert 'ELEMENTS ARE RADIUS STAND-INS' in text, 'the elements are still stand-ins, and the file still says so'


def _elements(text):
    """Every HETATM's element column, in file order -- the column a viewer resolves a bead's class from (77-78)."""
    return [line[76:78].strip() for line in text.splitlines() if line.startswith('HETATM')]


def test_the_element_column_states_each_beads_own_size_class(tmp_path):
    """The file states the class the model states, so a viewer's radii come out in proportion -- 2.64/2.30/1.91 A.

    Measured before this: the writer met one `C` for every bead, so `ngl-beads.js` resolved every bead to the model's
    R and drew the sugar ring's small beads at a tail bead's size -- uniform 2.64 A where the model says 0.264 / 0.230
    / 0.191 nm. `models/compositions/topology.py`'s `render_pdb` already chose its stand-in from each bead's class;
    this writer now reads the same class out of the moleculetype it is already handed.
    """
    (tmp_path / 'detergent_CG.itp').write_text(ddm_moleculetype())
    topology = pdc_view.read_moleculetype(tmp_path / 'detergent_CG.itp')
    atoms = pdc_view.read_gro(_system_gro(tmp_path, _detergent_beads(molecules=2)))

    text = pdc_view.system_pdb(atoms, topology=topology)

    expected = [ELEMENTS[DDM_CLASSES[name]] for name in list(DDM_BEADS) * 2]
    assert _elements(text) == expected
    assert len(set(expected)) == 3, 'the fixture must span R, S and T for this test to say anything'
    assert 'ELEMENTS ARE RADIUS STAND-INS' in text, 'the elements are still stand-ins, and the file still says so'


def test_the_moleculetype_reader_takes_each_beads_own_type(tmp_path):
    """The type column is where a moleculetype states a bead's Martini 3 class, so it is read beside the name."""
    path = tmp_path / 'detergent_CG.itp'
    path.write_text(ddm_moleculetype())

    moleculetype = pdc_view.read_moleculetype(path)

    assert moleculetype['atoms'] == list(DDM_BEADS)
    assert moleculetype['types'] == [DDM_TYPES[DDM_CLASSES[name]] for name in DDM_BEADS]


def test_a_bead_whose_class_the_model_does_not_state_keeps_the_stand_in(tmp_path):
    """Two ways a class goes unresolved, and both draw at the `C` stand-in -- the model's R, 0.264 nm.

    A protein bead is not a bead the detergent's moleculetype sizes, and a detergent bead a mapping does not name has
    no class either; without a topology there is no class anywhere. A picture that guessed a smaller class for these
    would be inventing a size the model does not state, so they keep the neutral stand-in and the file says so.
    """
    (tmp_path / 'detergent_CG.itp').write_text(ddm_moleculetype())
    topology = pdc_view.read_moleculetype(tmp_path / 'detergent_CG.itp')
    atoms = pdc_view.read_gro(_system_gro(tmp_path, [(1, 'PRO', 'BB', (0.0, 0.0, 0.0))]
                                        + _detergent_beads(molecules=1)
                                        + [(3, 'DDM', 'ZZZ', (9.0, 0.0, 0.0))]))

    elements = _elements(pdc_view.system_pdb(atoms, topology=topology))

    # The protein bead, one detergent's eleven beads in the moleculetype's own order, then the bead no model names.
    assert elements == ['C'] + [ELEMENTS[DDM_CLASSES[name]] for name in DDM_BEADS] + ['C'], elements
    assert set(_elements(pdc_view.system_pdb(atoms))) == {'C'}, 'no topology, no class'


def test_beads_that_do_not_match_the_moleculetype_are_left_unbonded_with_a_remark(tmp_path):
    (tmp_path / 'detergent_CG.itp').write_text(ddm_moleculetype())
    topology = pdc_view.read_moleculetype(tmp_path / 'detergent_CG.itp')
    atoms = pdc_view.read_gro(_system_gro(tmp_path, _detergent_beads(molecules=2, beads=DDM_BEADS[:3])))

    text = pdc_view.system_pdb(atoms, topology=topology)

    assert not [line for line in text.splitlines() if line.startswith('CONECT')]
    assert 'NO BONDS RECORDED' in text


def _families(text):
    """Every HETATM's b-factor column read back as its code -- columns 61-66, the carrier a viewer colours from."""
    return [int(round(float(line[60:66]))) for line in text.splitlines() if line.startswith('HETATM')]


#: One bead of each of the four families, plus the two spellings a type uses (a plain `P1` and a prefixed `SN6`) and
#: a type whose letter names no family. The code column is `pdc_view.BEAD_FAMILIES`'s own order.
FAMILY_TYPES = (('AH', 'Q5', 4), ('BH', 'P1', 3), ('CH', 'N6', 2), ('DH', 'C4', 1),
                ('EH', 'TC4', 1), ('FH', 'SN6', 2), ('GH', 'WF1', 0))


def test_the_type_column_decides_the_family_the_b_factor_column_carries(tmp_path):
    """A bead's Martini 3 polarity family reaches the file, so a viewer can colour it without guessing one.

    The four families are here, in both spellings a type uses -- a plain `P1` and a one-letter size prefix on `SN6`
    and `TC4` -- beside the two beads that state no family: a protein bead, which no moleculetype sizes, and a bead
    the moleculetype does not name. Both keep code 0, which is the neutral colour rather than whichever family
    happens to be first.
    """
    rows = '\n'.join(f'{index} {bead_type} 1 DDM {name} {index} 0 54'
                     for index, (name, bead_type, _) in enumerate(FAMILY_TYPES, 1))
    topology = pdc_view.read_moleculetype_text(f'[ moleculetype ]\nDDM 1\n\n[ atoms ]\n{rows}\n',
                                               source='fixture.itp')
    atoms = pdc_view.read_gro(_system_gro(
        tmp_path,
        [(1, 'PRO', 'BB', (0.0, 0.0, 0.0))]
        + [(2, 'DDM', name, (1.0 + index * 0.3, 0.0, 0.0)) for index, (name, _, _) in enumerate(FAMILY_TYPES)]
        + [(3, 'DDM', 'ZZZ', (9.0, 0.0, 0.0))]))

    text = pdc_view.system_pdb(atoms, topology=topology)

    assert _families(text) == [0] + [code for _, _, code in FAMILY_TYPES] + [0]
    assert len({code for code in _families(text)}) == 5, 'the fixture must span all five codes to say anything'
    assert 'POLARITY FAMILY' in text and 'A VIEWER COLOURS FROM IT' in text


def test_the_type_column_decides_the_family_on_the_runs_own_moleculetype(tmp_path):
    """The saved DDM mapping's own types, through the file the complexes panel and the preview card are served.

    `SP1r` and `SP4r` are polar and `TC4` apolar however small they are -- the size class is the `S`/`T` prefix and
    the family is the letter after it -- and the tail's plain `C1` is apolar. A viewer handed this file colours the
    heads and the tails apart without being told which bead is which.
    """
    (tmp_path / 'detergent_CG.itp').write_text(ddm_moleculetype())
    topology = pdc_view.read_moleculetype(tmp_path / 'detergent_CG.itp')
    atoms = pdc_view.read_gro(_system_gro(tmp_path, _detergent_beads(molecules=2)))

    families = _families(pdc_view.system_pdb(atoms, topology=topology))

    expected = [pdc_view.bead_family(DDM_TYPES[DDM_CLASSES[name]]) for name in list(DDM_BEADS) * 2]
    assert families == [pdc_view.BEAD_FAMILIES.index(family) for family in expected]
    assert set(expected) == {'P', 'C'}, 'the fixture must state two families for this test to say anything'
