"""The system view: a .gro becomes a PDB the viewer can read, with the solvent left out.

The claims worth pinning are the ones a picture would hide: water and ions are dropped by default, the coordinates
are converted from nanometres to the Angstroms PDB uses, the residue column separates protein from detergent, and a
malformed .gro is an error rather than a half-drawn system.

The fixtures are formatted rather than hand-typed: a .gro is fixed-width, and a hand-typed line that looks right
shifts every float by a character.
"""
import pytest

from dashboard.execution.adapters import pdc_view


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
