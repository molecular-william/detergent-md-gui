"""Build a pdb2gmx virtual-site topology from a molecule ITP."""
from pathlib import Path

import pytest
from dashboard.execution import forcefields
from dashboard.execution.adapters import aa_vsites

FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures' / 'vsites'
NAMES = ('C1', 'H1', 'H2', 'H3', 'C2', 'O1', 'H4', 'C3', 'H5', 'H6', 'H7')
XYZ = ((0, 0, 0), (0.1, 0, 0), (-0.1, 0, 0), (0, 0.1, 0), (0.15, 0, 0),
       (0.25, 0, 0), (0.30, 0, 0), (-0.1, 0, 0), (-0.2, 0, 0), (-0.1, 0.1, 0), (-0.1, -0.1, 0))


def _gro() -> str:
    lines = ['MOL', str(len(NAMES))]
    for index, (name, xyz) in enumerate(zip(NAMES, XYZ), 1):
        lines.append(f'{1:5d}{"MOL":<5}{name:>5}{index:5d}' + ''.join(f'{value:8.3f}' for value in xyz))
    return '\n'.join([*lines, '3 3 3', ''])


def test_build_moves_the_methyl_hydrogens_to_dummies_and_keeps_mass_and_charge(tmp_path):
    gro = tmp_path / 'molecule.gro'
    gro.write_text(_gro())
    source = tmp_path / 'molecule.itp'
    source.write_text((FIXTURES / 'methyl_hydroxyl.itp').read_text().replace(' CT1 ', ' VCT1 ')
                      .replace(' CT2 ', ' VCT2 ').replace(' HC ', ' VHC ')
                      .replace(' OH ', ' VOH ').replace(' HO ', ' VHO '))
    result = aa_vsites.build(
        source_topology=source, coordinates=gro,
        force_field=forcefields.entry('charmm36-jul2022').tree(), water='tip3p',
        residue='MOL', choice='hydrogens')
    assert result.atom_count == 15, 'two CH3 groups add two dummy atoms each'
    assert result.charge == pytest.approx(0.0)
    assert result.mass == pytest.approx(59.0), 'the dummies receive the hydrogen mass, the total does not move'
    assert len(result.report['vsites']) == 1 and result.report['vsites'][0]['count'] == 2
    assert len(result.report['angle_constraints']) == 1
    assert '[ virtual_sites3 ]' in result.molecule_itp
    assert 'MCH3' in result.molecule_itp
    assert any(row.startswith('MCH3') for row in result.atomtypes_rows)
    assert result.molecule_gro.startswith('MOL')


def test_a_choice_without_a_construct_is_refused(tmp_path):
    gro = tmp_path / 'molecule.gro'
    gro.write_text(_gro())
    with pytest.raises(aa_vsites.VsiteBuildError, match='unsupported virtual-site choice'):
        aa_vsites.build(source_topology=FIXTURES / 'methyl_hydroxyl.itp', coordinates=gro,
                        force_field=forcefields.entry('charmm36-jul2022').tree(), water='tip3p',
                        residue='MOL', choice='none')


def test_gpu_update_is_refused_with_a_vsite_topology():
    """GROMACS update groups cannot carry pdb2gmx's virtual-site types; refuse before the NVT leg does."""
    from dashboard.execution.adapters import aa

    with pytest.raises(ValueError, match='mdrun_update gpu cannot be used with a pdb2gmx virtual-site topology'):
        aa.normalize_settings({'vsite': 'hydrogens', 'mdrun_update': 'gpu'})
    assert aa.normalize_settings({'vsite': 'none', 'mdrun_update': 'gpu'})['mdrun_update'] == 'gpu'
