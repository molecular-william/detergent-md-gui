"""Staging a conversion's inputs: the fragment, the force field, the mirrored library and a gro the tool can read back.

The back-map stage used to hand CG2AT2 a CG structure and hope. Everything it needed was already in the repository -- the
mapping says which atoms each bead covers, the molecule's topology says what those atoms are -- so `pdc_backmap.py` puts
them where the tool reads them, inside the stage. These tests pin the four things that make that staging correct, and the
one refusal that matters: a run with no mapping cannot be converted, and saying so is better than a conversion that
silently drops the detergent.

GROMACS and the tool are not run here; the end-to-end result is measured on the run itself (76 detergents, 81 atoms each).
"""
import json
from pathlib import Path

import pytest
from detergent_pdc.execution.scripts import pdc_backmap

MAPPING = {'name': 'DDM_CG_test', 'beads': [
    {'name': 'S1A', 'atoms': [1, 2]},
    {'name': 'S1B', 'atoms': [3, 4]},
    {'name': 'S1VS', 'atoms': []},
    {'name': 'TAIL1', 'atoms': [5]},
    {'name': 'TAIL2', 'atoms': [6]},
]}

TOPOLOGY = """[ atomtypes ]
CR  6  12.0110  0.0  A  0.36  0.23

[ pairtypes ]
CR  CR  1  0.34  0.04

[ moleculetype ]
; Name nrexcl
LIG1  3

[ atoms ]
; nr type resnr resid atom cgnr charge mass
1  CR  1  LIG1  C1  1  0.0  12.0110
2  CR  1  LIG1  C2  2  0.0  12.0110
3  CR  1  LIG1  C3  3  0.0  12.0110
4  CR  1  LIG1  C4  4  0.0  12.0110
5  CR  1  LIG1  C5  5  0.0  12.0110
6  CR  1  LIG1  C6  6  0.0  12.0110
7  H1  1  LIG1  H1  7  0.0   1.0080

[ bonds ]
1  2  1  0.15  250000
1  7  1  0.10  250000
"""

def atom_line(number, name, element, x, y, z):
    """A PDB ATOM line in the columns the reader uses: serial 7-11, name 13-16, x/y/z 31-54, element 77-78."""
    return (f'ATOM  {number:5d} {name:<4} LIG A{1:4d}    '
            f'{x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00          {element:>2}\n')


COORDINATES = ''.join(atom_line(number, f'C{number}', 'C', float(number), 0.0, 0.0)
                      for number in range(1, 7)) + atom_line(7, 'H1', 'H', 0.0, 1.0, 0.0)

def gro_line(number, residue, atom, x):
    """A gro line in its own columns: residue number 1-5, residue name 6-10, atom name 11-15, number 16-20."""
    return f'{number:5d}{residue:<5}{atom:>5}{number:5d}{x:8.3f}{0.0:8.3f}{0.0:8.3f}\n'


GRO = ('system\n'
       '    3\n'
       + gro_line(1, 'DDM', 'S1A', 0.1) + gro_line(2, 'DDM', 'TAIL1', 0.4)
       + gro_line(3, 'W', 'W', 0.7) +
       '   8.00000   8.00000   8.00000\n')


def build_run(tmp_path, *, mapping=True) -> Path:
    """A run directory and a project root shaped like the repository's."""
    root = tmp_path / 'repo'
    run = root / 'workspace/dashboard/runs/abc123'
    stage = run / 'stages/10_backmap'
    (run / 'inputs').mkdir(parents=True)
    (run / 'stages/08_extension/prod').mkdir(parents=True)
    stage.mkdir()
    (run / 'stages/08_extension/prod/run.gro').write_text(GRO)

    molecule = root / 'molecules/DDM'
    (molecule / 'results/MMFF').mkdir(parents=True)
    (molecule / 'results/MMFF/lig1.itp').write_text(TOPOLOGY)
    (molecule / 'results/MMFF/lig1.pdb').write_text(COORDINATES)

    mapping_path = tmp_path / 'mapping.json'
    mapping_path.write_text(json.dumps(MAPPING))
    (run / 'inputs/pdc-settings.json').write_text(json.dumps({
        'detergent_model': {'mapping': str(mapping_path) if mapping else '', 'residue': 'DDM'}, 'backmap': True}))

    library = root / 'tools/cg2at/database/fragments/martini_3-0_charmm36'
    (library / 'non_protein/POPC').mkdir(parents=True)
    (library / 'non_protein/POPC/POPC.pdb').write_text('[ NC3 ]\nATOM\n')
    (library / 'solvent').mkdir()
    (library / 'solvent/W.itp').write_text('[ moleculetype ]\nW 1\n')
    force_field = root / 'tools/cg2at/database/forcefields/charmm36-mar2019-updated.ff'
    force_field.mkdir(parents=True)
    (force_field / 'ffnonbonded.itp').write_text('[ atomtypes ]\nCA  6  12.0  0.0  A  0.3  0.2\n\n'
                                                 '[ pairtypes ]\nCA  CA  1  0.3  0.2\n')
    (force_field / 'forcefield.itp').write_text('#include "ffnonbonded.itp"\n')
    return run


def backmap_stage(run: Path) -> Path:
    return run / 'stages/10_backmap'


def test_the_fragment_lands_inside_a_mirrored_library(tmp_path):
    """`-fg` takes a path, and the tool reads `<parent>/<name>/non_protein/...`, so the mirror keeps the library's name."""
    run = build_run(tmp_path)

    record = pdc_backmap.stage_inputs(backmap_stage(run), tmp_path / 'repo')

    library = Path(record['library'])
    assert library.name == 'martini_3-0_charmm36'
    installed = library / 'non_protein/DDM'
    assert (installed / 'DDM.pdb').is_file() and (installed / 'DDM.itp').is_file()
    assert (library / 'non_protein/POPC').is_symlink(), 'the vendored entries are linked, not copied'
    assert (library / 'solvent/W.itp').is_symlink(), 'and their contents keep working through the link'


def test_the_force_field_the_tool_is_given_carries_the_molecules_types(tmp_path):
    run = build_run(tmp_path)

    record = pdc_backmap.stage_inputs(backmap_stage(run), tmp_path / 'repo')

    written = (Path(record['force_field']) / 'ffnonbonded.itp').read_text()
    types, pairs = written.split('[ pairtypes ]')
    assert 'CR  6  12.0110' in types and 'CR  CR  1  0.34  0.04' in pairs
    assert Path(record['force_field']).name.endswith('.ff'), 'pdb2gmx only sees a force field named *.ff'


def test_the_structure_handed_over_is_a_gro_with_readable_bead_names(tmp_path):
    """The tool rewrites its input to PDB; a five-character bead name does not survive that, a gro's does."""
    run = build_run(tmp_path)

    record = pdc_backmap.stage_inputs(backmap_stage(run), tmp_path / 'repo')

    structure = Path(record['structure'])
    assert structure.suffix == '.gro'
    lines = structure.read_text().splitlines()
    assert lines[2][10:15].strip() == 'S1A'
    assert lines[3][10:15].strip() == 'TAI1', 'TAIL1 shortened, so the fragment lookup can find it'
    assert lines[4][10:15].strip() == 'W', 'and no other residue is touched'
    assert lines[-1].strip() == '8.00000   8.00000   8.00000'


def test_the_record_says_what_was_built_and_from_what(tmp_path):
    run = build_run(tmp_path)

    record = pdc_backmap.stage_inputs(backmap_stage(run), tmp_path / 'repo')

    assert record['residue'] == 'DDM' and record['atoms'] == 7
    assert record['mapping_sha256'] and record['fragment']['DDM.pdb']
    assert record['box_nm'] == ['8.00000', '8.00000', '8.00000']
    written = json.loads((backmap_stage(run) / pdc_backmap.OUTPUT_NAME).read_text())
    assert written['library'] == record['library'], 'the file the stage reads is the record this call returned'


def test_a_run_with_no_mapping_refuses_rather_than_dropping_the_detergent(tmp_path):
    run = build_run(tmp_path, mapping=False)

    with pytest.raises(SystemExit, match='no mapping'):
        pdc_backmap.stage_inputs(backmap_stage(run), tmp_path / 'repo')


def test_a_molecule_without_its_own_topology_is_refused_by_name(tmp_path):
    run = build_run(tmp_path)
    (tmp_path / 'repo/molecules/DDM/results/MMFF/lig1.itp').unlink()

    with pytest.raises(SystemExit, match='lig1.itp'):
        pdc_backmap.stage_inputs(backmap_stage(run), tmp_path / 'repo')
