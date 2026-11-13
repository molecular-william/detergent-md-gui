"""An AA run's vsite setting builds and validates a pdb2gmx topology at prepare."""
import json
from pathlib import Path

import pytest
from dashboard.execution.adapters import aa
from dashboard.models.molecules import aa as aa_molecules

from tests.harness.support import PROJECT_ROOT

FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures' / 'vsites'
NAMES = ('C1', 'H1', 'H2', 'H3', 'C2', 'O1', 'H4', 'C3', 'H5', 'H6', 'H7')
XYZ = ((0, 0, 0), (0.1, 0, 0), (-0.1, 0, 0), (0, 0.1, 0), (0.15, 0, 0),
       (0.25, 0, 0), (0.30, 0, 0), (-0.1, 0, 0), (-0.2, 0, 0), (-0.1, 0.1, 0), (-0.1, -0.1, 0))


def _molecule(root: Path) -> dict:
    folder = root / 'molecules' / 'MOL'
    folder.mkdir(parents=True)
    source = (FIXTURES / 'methyl_hydroxyl.itp').read_text()
    for old, new in ((' CT1 ', ' VCT1 '), (' CT2 ', ' VCT2 '), (' HC ', ' VHC '),
                     (' OH ', ' VOH '), (' HO ', ' VHO ')):
        source = source.replace(old, new)
    (folder / 'molecule.itp').write_text(source)
    lines = ['MOL', str(len(NAMES))]
    for index, (name, xyz) in enumerate(zip(NAMES, XYZ), 1):
        lines.append(f'{1:5d}{"MOL":<5}{name:>5}{index:5d}' + ''.join(f'{value:8.3f}' for value in xyz))
    (folder / 'molecule.gro').write_text('\n'.join([*lines, '3 3 3', '']))
    (folder / 'metadata.json').write_text(json.dumps({
        'name': 'MOL', 'molecule_type': 'MOL', 'force_field': 'charmm36-jul2022.ff',
        'water_model': 'tip3p', 'net_charge': 0, 'generated': True,
    }))
    return aa_molecules.selection(root / 'molecules', 'MOL', 'aa_only')


@pytest.mark.slow
def test_prepare_builds_a_vsite_topology_and_records_it(tmp_path):
    """The real DDM ITP exercises the complete RTP, overlay and grompp path."""
    snapshot = aa_molecules.selection(PROJECT_ROOT / 'molecules', 'DDM', 'aa_only')
    run = tmp_path / 'run'
    run.mkdir()
    settings = aa.normalize_settings({
        'vsite': 'hydrogens', 'force_field': 'charmm36-jul2022', 'box_nm': 4.0,
        'aa_nvt_ps': 1, 'aa_npt_ps': 1, 'aa_production_ps': 10, 'output_interval_ps': 1,
    })
    aa.prepare_run(run, PROJECT_ROOT / 'molecules', snapshot, settings)

    molecule = run / 'stages' / 'common' / 'molecule'
    assert '[ virtual_sites3 ]' in (molecule / 'molecule.itp').read_text()
    assert (molecule / 'atomtypes.itp').is_file()
    assert (molecule / 'constrainttypes.itp').is_file()
    record = json.loads((molecule / 'vsite.json').read_text())
    assert record['choice'] == 'hydrogens'
    assert record['generated']['atom_count'] == 83
    assert record['validation'] == {'grompp': 'ok'}
    top = (run / 'stages' / '01_solvation' / 'system.top').read_text()
    assert '#include "../common/molecule/atomtypes.itp"' in top
    assert '#include "../common/molecule/constrainttypes.itp"' in top
    ndx = (run / 'stages' / 'common' / 'solute.ndx').read_text()
    assert '83' in ndx.splitlines()[-1].split(), 'the solute group covers the generated atoms'
    manifest = json.loads((run / 'manifest.json').read_text())
    assert manifest['input_preparation']['vsite']['method'] == 'pdb2gmx + MkVsites'


def test_prepare_with_none_keeps_the_stored_topology(tmp_path):
    snapshot = _molecule(tmp_path)
    run = tmp_path / 'run'
    run.mkdir()
    settings = aa.normalize_settings({
        'force_field': 'charmm36-jul2022', 'box_nm': 4.0,
        'aa_nvt_ps': 1, 'aa_npt_ps': 1, 'aa_production_ps': 10, 'output_interval_ps': 1,
    })
    aa.prepare_run(run, tmp_path / 'molecules', snapshot, settings)
    molecule = run / 'stages' / 'common' / 'molecule'
    assert (molecule / 'molecule.itp').read_text().startswith('#include "')
    assert not (molecule / 'atomtypes.itp').exists()
    assert not (molecule / 'vsite.json').exists()
